import asyncio
import json
import unittest
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.messages import AIMessageChunk
from langgraph.types import Interrupt
from fastapi import HTTPException
from sqlalchemy import delete, select

from controller.chat import run_stream_chat, submit_approval_decisions_stream
from core.database import AsyncSessionLocal, engine
from model.agent_run import AgentRun
from model.agent_run_event import AgentRunEvent
from model.approval import ApprovalBatch, ApprovalRequest
from model.conversation import Conversation
from model.message import Message
from model.message_part import MessagePart
from model.outbox_event import OutboxEvent
from model.tool_invocation import ToolInvocation
from schema.chat import ApprovalDecisionRequest, ChatStreamRequest
from service.approval import expire_approval_batch
from service.run_events import stream_run_events
from worker.command_consumer import CommandConsumer
from worker.run_executor import AgentRunCommand, RunExecutor


class FakeAgent:
    def __init__(self, chunks: list[object]) -> None:
        self.chunks = chunks
        self.calls: list[object] = []

    async def astream(self, input: object, **_: object):
        self.calls.append(input)
        for chunk in self.chunks:
            yield chunk


class FakeIncomingMessage:
    def __init__(
        self,
        *,
        message_id: str,
        message_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.message_id = message_id
        self.type = message_type
        self.body = json.dumps(payload).encode()
        self.acks = 0
        self.nacks: list[bool] = []

    async def ack(self) -> None:
        self.acks += 1

    async def nack(self, *, requeue: bool = True) -> None:
        self.nacks.append(requeue)


class HitlFlowAcceptanceTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        asyncio.run(engine.dispose())

    def test_manual_approval_streams_required_resolved_and_done(self) -> None:
        asyncio.run(self._test_manual_approval_streams_required_resolved_and_done())

    def test_timeout_expires_pending_batch_and_resume_completes(self) -> None:
        asyncio.run(self._test_timeout_expires_pending_batch_and_resume_completes())

    def test_active_run_conflict_is_scoped_to_conversation(self) -> None:
        asyncio.run(self._test_active_run_conflict_is_scoped_to_conversation())

    async def _test_manual_approval_streams_required_resolved_and_done(self) -> None:
        conversation_id = "conversation-hitl-manual"
        now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
        await self._reset_conversation(conversation_id)
        await self._create_conversation(conversation_id, now=now)

        response = await run_stream_chat(
            ChatStreamRequest.model_validate(
                {"conversationId": conversation_id, "message": "查天气"}
            )
        )
        stream = response.body_iterator.__aiter__()
        run_created_frame = await stream.__anext__()
        await stream.aclose()
        run_created = _parse_frame(run_created_frame)
        self.assertEqual(run_created["type"], "run_created")
        run_id = str(run_created["runId"])
        assistant_message_id = str(run_created["assistantMessageId"])

        start_outbox = await self._get_outbox_by_type(run_id, "agent.run.start")
        await self._execute_start_command(
            command_id=start_outbox.id,
            run_id=run_id,
            now=now,
        )

        approval_frames = [
            _parse_frame(frame)
            async for frame in stream_run_events(
                run_id,
                after_event_id=int(run_created_frame.split(":", 1)[1].split("\n", 1)[0]),
            )
        ]
        self.assertEqual(
            [event["type"] for event in approval_frames],
            ["tool_call", "approval_required"],
        )
        self.assertNotIn("done", [event["type"] for event in approval_frames])
        approval_required = approval_frames[-1]
        batch = approval_required["part"]["batch"]
        batch_id = str(batch["id"])

        approval_response = await submit_approval_decisions_stream(
            batch_id,
            ApprovalDecisionRequest.model_validate(
                {
                    "afterEventId": await self._last_event_id(run_id),
                    "decisions": [
                        {
                            "approvalRequestId": batch["requests"][0]["id"],
                            "decision": "approve",
                        }
                    ],
                }
            ),
        )
        approval_stream = approval_response.body_iterator.__aiter__()
        resolved = _parse_frame(await approval_stream.__anext__())
        self.assertEqual(resolved["type"], "approval_resolved")
        self.assertEqual(resolved["batch"]["status"], "resolved")

        resume_outbox = await self._get_outbox_by_type(batch_id, "agent.run.resume")
        await self._execute_resume_command(
            command_id=resume_outbox.id,
            payload=resume_outbox.payload,
            now=now + timedelta(minutes=1),
        )
        resumed_events = [
            _parse_frame(await approval_stream.__anext__()),
            _parse_frame(await approval_stream.__anext__()),
        ]
        await approval_stream.aclose()
        self.assertEqual([event["type"] for event in resumed_events], ["delta", "done"])

        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            assistant = await session.get(Message, assistant_message_id)
        self.assertIsNotNone(run)
        self.assertIsNotNone(assistant)
        assert run is not None and assistant is not None
        self.assertEqual(run.status, "completed")
        self.assertEqual(assistant.status, "done")
        self.assertEqual(assistant.content, "天气查询已完成")

        await self._reset_conversation(conversation_id)

    async def _test_timeout_expires_pending_batch_and_resume_completes(self) -> None:
        conversation_id = "conversation-hitl-timeout"
        now = datetime(2026, 6, 7, 11, 0, tzinfo=UTC)
        await self._reset_conversation(conversation_id)
        await self._create_conversation(conversation_id, now=now)
        run_id = await self._create_run_and_project_approval(
            conversation_id,
            now=now,
        )
        batch = await self._get_pending_batch(run_id)
        timeout_message = FakeIncomingMessage(
            message_id="timeout-hitl",
            message_type="approval.timeout.ready",
            payload={
                "batchId": batch.id,
                "expiresAt": batch.expires_at.isoformat().replace("+00:00", "Z"),
            },
        )
        consumer = CommandConsumer(
            executor=RunExecutor(agent=FakeAgent([])),
            expire_approval_batch=expire_approval_batch,
            session_factory=AsyncSessionLocal,
            now_factory=lambda: batch.expires_at,
        )

        await consumer.handle_message(timeout_message)

        self.assertEqual(timeout_message.acks, 1)
        self.assertEqual(timeout_message.nacks, [])
        resume_outbox = await self._get_outbox_by_type(batch.id, "agent.run.resume")
        self.assertEqual(
            resume_outbox.payload["decisions"],
            [{"type": "reject", "message": "Approval timed out after 30 minutes"}],
        )

        await self._execute_resume_command(
            command_id=resume_outbox.id,
            payload=resume_outbox.payload,
            now=batch.expires_at + timedelta(seconds=1),
        )
        events = await self._events(run_id)
        self.assertEqual(
            [event.event_type for event in events],
            [
                "run_created",
                "tool_call",
                "approval_required",
                "approval_resolved",
                "delta",
                "done",
            ],
        )
        self.assertEqual(events[3].payload["batch"]["status"], "expired")

        await self._reset_conversation(conversation_id)

    async def _test_active_run_conflict_is_scoped_to_conversation(self) -> None:
        first_conversation = "conversation-hitl-conflict-1"
        second_conversation = "conversation-hitl-conflict-2"
        now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
        await self._reset_conversation(first_conversation)
        await self._reset_conversation(second_conversation)
        await self._create_conversation(first_conversation, now=now)
        await self._create_conversation(second_conversation, now=now)

        first_response = await run_stream_chat(
            ChatStreamRequest.model_validate(
                {"conversationId": first_conversation, "message": "first"}
            )
        )
        first_stream = first_response.body_iterator.__aiter__()
        await first_stream.__anext__()
        await first_stream.aclose()

        with self.assertRaises(HTTPException) as caught:
            await run_stream_chat(
                ChatStreamRequest.model_validate(
                    {"conversationId": first_conversation, "message": "second"}
                )
            )
        self.assertEqual(caught.exception.status_code, 409)

        second_response = await run_stream_chat(
            ChatStreamRequest.model_validate(
                {"conversationId": second_conversation, "message": "parallel"}
            )
        )
        second_stream = second_response.body_iterator.__aiter__()
        second_run = _parse_frame(await second_stream.__anext__())
        await second_stream.aclose()
        self.assertEqual(second_run["type"], "run_created")

        await self._reset_conversation(first_conversation)
        await self._reset_conversation(second_conversation)

    async def _create_run_and_project_approval(
        self,
        conversation_id: str,
        *,
        now: datetime,
    ) -> str:
        response = await run_stream_chat(
            ChatStreamRequest.model_validate(
                {"conversationId": conversation_id, "message": "查天气"}
            )
        )
        stream = response.body_iterator.__aiter__()
        run_created = _parse_frame(await stream.__anext__())
        await stream.aclose()
        run_id = str(run_created["runId"])
        start_outbox = await self._get_outbox_by_type(run_id, "agent.run.start")
        await self._execute_start_command(
            command_id=start_outbox.id,
            run_id=run_id,
            now=now,
        )
        return run_id

    async def _execute_start_command(
        self,
        *,
        command_id: str,
        run_id: str,
        now: datetime,
    ) -> None:
        executor = RunExecutor(
            agent=FakeAgent(
                [
                    (
                        "messages",
                        (
                            AIMessageChunk(
                                content="",
                                tool_call_chunks=[
                                    {
                                        "name": "get_weather",
                                        "args": '{"city":"Shanghai"}',
                                        "id": f"call-{run_id}-weather",
                                        "index": 0,
                                        "type": "tool_call_chunk",
                                    }
                                ],
                                response_metadata={"finish_reason": "tool_calls"},
                            ),
                            {"langgraph_node": "model"},
                        ),
                    ),
                    ("updates", {"__interrupt__": (self._interrupt(run_id),)}),
                ]
            ),
            session_factory=AsyncSessionLocal,
            worker_id="hitl-test-worker",
            now_factory=lambda: now,
        )
        await executor.execute_start(AgentRunCommand(id=command_id, run_id=run_id))

    async def _execute_resume_command(
        self,
        *,
        command_id: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        executor = RunExecutor(
            agent=FakeAgent(
                [
                    (
                        "messages",
                        (
                            AIMessageChunk(content="天气查询已完成"),
                            {"langgraph_node": "model"},
                        ),
                    )
                ]
            ),
            session_factory=AsyncSessionLocal,
            worker_id="hitl-test-worker-restarted",
            now_factory=lambda: now,
        )
        await executor.execute_resume(AgentRunCommand.from_payload(command_id, payload))

    def _interrupt(self, run_id: str) -> Interrupt:
        return Interrupt(
            id=f"interrupt-{run_id}",
            value={
                "action_requests": [
                    {
                        "name": "get_weather",
                        "args": {"city": "Shanghai"},
                        "description": "Approve weather lookup",
                    }
                ],
                "review_configs": [
                    {
                        "action_name": "get_weather",
                        "allowed_decisions": ["approve", "reject"],
                    }
                ],
            },
        )

    async def _create_conversation(self, conversation_id: str, *, now: datetime) -> None:
        async with AsyncSessionLocal() as session:
            session.add(
                Conversation(
                    id=conversation_id,
                    title="HITL flow",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

    async def _get_outbox_by_type(
        self,
        aggregate_id: str,
        event_type: str,
    ) -> OutboxEvent:
        async with AsyncSessionLocal() as session:
            outbox = (
                await session.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.aggregate_id == aggregate_id)
                    .where(OutboxEvent.event_type == event_type)
                    .order_by(OutboxEvent.created_at.desc())
                )
            ).scalars().first()
        self.assertIsNotNone(outbox)
        assert outbox is not None
        return outbox

    async def _get_pending_batch(self, run_id: str) -> ApprovalBatch:
        async with AsyncSessionLocal() as session:
            batch = (
                await session.execute(
                    select(ApprovalBatch)
                    .where(ApprovalBatch.agent_run_id == run_id)
                    .where(ApprovalBatch.status == "pending")
                )
            ).scalar_one()
        return batch

    async def _last_event_id(self, run_id: str) -> int:
        events = await self._events(run_id)
        return events[-1].id

    async def _events(self, run_id: str) -> list[AgentRunEvent]:
        async with AsyncSessionLocal() as session:
            return list(
                (
                    await session.execute(
                        select(AgentRunEvent)
                        .where(AgentRunEvent.agent_run_id == run_id)
                        .order_by(AgentRunEvent.id.asc())
                    )
                )
                .scalars()
                .all()
            )

    async def _reset_conversation(self, conversation_id: str) -> None:
        async with AsyncSessionLocal() as session:
            run_ids = select(AgentRun.id).where(
                AgentRun.conversation_id == conversation_id
            )
            message_ids = select(Message.id).where(
                Message.conversation_id == conversation_id
            )
            batch_ids = select(ApprovalBatch.id).where(
                ApprovalBatch.agent_run_id.in_(run_ids)
            )
            await session.execute(
                delete(ApprovalRequest).where(
                    ApprovalRequest.approval_batch_id.in_(batch_ids)
                )
            )
            await session.execute(
                delete(MessagePart).where(MessagePart.message_id.in_(message_ids))
            )
            await session.execute(
                delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(batch_ids))
            )
            await session.execute(
                delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(run_ids))
            )
            await session.execute(
                delete(ApprovalBatch).where(ApprovalBatch.agent_run_id.in_(run_ids))
            )
            await session.execute(
                delete(AgentRunEvent).where(AgentRunEvent.agent_run_id.in_(run_ids))
            )
            await session.execute(delete(AgentRun).where(AgentRun.id.in_(run_ids)))
            await session.execute(
                delete(ToolInvocation).where(ToolInvocation.message_id.in_(message_ids))
            )
            await session.execute(
                delete(Message).where(Message.conversation_id == conversation_id)
            )
            await session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            )
            await session.commit()


def _parse_frame(frame: str | bytes) -> dict[str, Any]:
    text = frame.decode() if isinstance(frame, bytes) else frame
    data_line = next(line for line in text.splitlines() if line.startswith("data: "))
    return json.loads(data_line.removeprefix("data: "))


if __name__ == "__main__":
    unittest.main()
