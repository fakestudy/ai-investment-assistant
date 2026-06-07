import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from langchain_core.messages import AIMessageChunk
from langgraph.types import Interrupt
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from core.database import AsyncSessionLocal, engine
from model.agent_run import AgentRun
from model.agent_run_event import AgentRunEvent
from model.approval import ApprovalBatch, ApprovalRequest
from model.conversation import Conversation
from model.message import Message
from model.message_part import MessagePart
from model.outbox_event import OutboxEvent
from model.tool_invocation import ToolInvocation
from service.stream_projection import project_interrupt
from worker.run_executor import AgentRunCommand, RunExecutor


class FakeAgent:
    def __init__(self, chunks: list[object]) -> None:
        self.chunks = chunks

    async def astream(self, input: object, **kwargs: object):
        for chunk in self.chunks:
            yield chunk


class ApprovalInterruptTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        asyncio.run(engine.dispose())

    def test_interrupt_creates_ordered_batch_and_timeout_command(self) -> None:
        asyncio.run(self._test_interrupt_creates_ordered_batch_and_timeout_command())

    def test_run_executor_stops_stream_at_approval_required_without_done(self) -> None:
        asyncio.run(
            self._test_run_executor_stops_stream_at_approval_required_without_done()
        )

    def test_interrupt_binds_requests_to_matching_tool_calls(self) -> None:
        asyncio.run(self._test_interrupt_binds_requests_to_matching_tool_calls())

    def test_duplicate_interrupt_conflict_rereads_existing_batch(self) -> None:
        asyncio.run(self._test_duplicate_interrupt_conflict_rereads_existing_batch())

    def test_existing_interrupt_returns_event_for_that_batch(self) -> None:
        asyncio.run(self._test_existing_interrupt_returns_event_for_that_batch())

    async def _test_interrupt_creates_ordered_batch_and_timeout_command(self) -> None:
        run_id = "run-approval-direct"
        fixed_now = datetime(2026, 6, 7, 9, 0, tzinfo=UTC)
        await self._reset_run(run_id)
        await self._create_run(run_id, now=fixed_now, status="running")
        await self._create_tool_invocation(
            "call-weather-direct",
            run_id=run_id,
            name="get_weather",
            args={"city": "Shanghai"},
            order_index=0,
            now=fixed_now,
        )
        await self._create_tool_invocation(
            "call-balance-direct",
            run_id=run_id,
            name="get_deepseek_balance",
            args={},
            order_index=1,
            now=fixed_now,
        )

        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            result = await project_interrupt(
                session,
                run,
                self._interrupt("interrupt-direct"),
                now=fixed_now,
            )
            await session.commit()

        self.assertEqual(result.batch.sequence, 1)
        self.assertEqual(result.batch.expires_at, fixed_now + timedelta(minutes=30))
        self.assertEqual([item.order_index for item in result.requests], [0, 1])
        self.assertTrue(all(item.decision == "pending" for item in result.requests))
        self.assertEqual(result.outbox.event_type, "approval.timeout.schedule")
        self.assertEqual(result.event.event_type, "approval_required")

        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            batch_rows = await session.execute(
                select(ApprovalBatch).where(ApprovalBatch.agent_run_id == run_id)
            )
            request_rows = await session.execute(
                select(ApprovalRequest)
                .where(ApprovalRequest.approval_batch_id == result.batch.id)
                .order_by(ApprovalRequest.order_index.asc())
            )
            part_rows = await session.execute(
                select(MessagePart)
                .where(MessagePart.message_id == f"assistant-{run_id}")
                .order_by(MessagePart.order_index.asc())
            )
            outbox_rows = await session.execute(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == result.batch.id)
            )
            weather = await session.get(ToolInvocation, "call-weather-direct")
            balance = await session.get(ToolInvocation, "call-balance-direct")

        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run.status, "awaiting_approval")
        self.assertIsNone(run.lease_owner)
        self.assertIsNone(run.lease_expires_at)
        self.assertEqual(len(batch_rows.scalars().all()), 1)
        self.assertEqual(
            [request.tool_invocation_id for request in request_rows.scalars().all()],
            ["call-weather-direct", "call-balance-direct"],
        )
        self.assertEqual(
            [(part.type, part.approval_batch_id is not None) for part in part_rows.scalars().all()],
            [("tool", False), ("tool", False), ("approval", True)],
        )
        self.assertEqual(len(outbox_rows.scalars().all()), 1)
        self.assertIsNotNone(weather)
        self.assertIsNotNone(balance)
        assert weather is not None and balance is not None
        self.assertEqual(weather.status, "awaiting_approval")
        self.assertEqual(balance.status, "awaiting_approval")

        await self._reset_run(run_id)

    async def _test_interrupt_binds_requests_to_matching_tool_calls(self) -> None:
        run_id = "run-approval-bind-tools"
        fixed_now = datetime(2026, 6, 7, 11, 0, tzinfo=UTC)
        await self._reset_run(run_id)
        await self._create_run(run_id, now=fixed_now, status="running")
        await self._create_tool_invocation(
            "call-balance-bind",
            run_id=run_id,
            name="get_deepseek_balance",
            args={},
            order_index=0,
            now=fixed_now,
        )
        await self._create_tool_invocation(
            "call-weather-bind",
            run_id=run_id,
            name="get_weather",
            args={"city": "Shanghai"},
            order_index=1,
            now=fixed_now,
        )

        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            result = await project_interrupt(
                session,
                run,
                self._interrupt("interrupt-bind-tools"),
                now=fixed_now,
            )
            await session.commit()

        self.assertEqual(
            [request.tool_invocation_id for request in result.requests],
            ["call-weather-bind", "call-balance-bind"],
        )
        self.assertEqual(
            [(request.tool_name, request.args) for request in result.requests],
            [("get_weather", {"city": "Shanghai"}), ("get_deepseek_balance", {})],
        )

        await self._reset_run(run_id)

    async def _test_duplicate_interrupt_conflict_rereads_existing_batch(self) -> None:
        run_id = "run-approval-conflict-reread"
        fixed_now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
        await self._reset_run(run_id)
        await self._create_run(run_id, now=fixed_now, status="running")
        await self._create_tool_invocation(
            "call-weather-conflict",
            run_id=run_id,
            name="get_weather",
            args={"city": "Shanghai"},
            order_index=0,
            now=fixed_now,
        )
        await self._create_tool_invocation(
            "call-balance-conflict",
            run_id=run_id,
            name="get_deepseek_balance",
            args={},
            order_index=1,
            now=fixed_now,
        )
        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            existing = await project_interrupt(
                session,
                run,
                self._interrupt("interrupt-conflict-reread"),
                now=fixed_now,
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            with patch(
                "service.stream_projection.get_approval_batch_by_interrupt_id",
                side_effect=[None, existing.batch],
            ):
                with patch(
                    "service.stream_projection.create_approval_batch",
                    side_effect=IntegrityError("insert", {}, Exception("duplicate")),
                ):
                    result = await project_interrupt(
                        session,
                        run,
                        self._interrupt("interrupt-conflict-reread"),
                        now=fixed_now + timedelta(seconds=1),
                    )
                    event_batch_id = result.event.payload["part"]["batch"]["id"]
                    await session.rollback()

        self.assertEqual(result.batch.id, existing.batch.id)
        self.assertEqual(event_batch_id, existing.batch.id)

        await self._reset_run(run_id)

    async def _test_existing_interrupt_returns_event_for_that_batch(self) -> None:
        run_id = "run-approval-existing-event"
        fixed_now = datetime(2026, 6, 7, 13, 0, tzinfo=UTC)
        await self._reset_run(run_id)
        await self._create_run(run_id, now=fixed_now, status="running")
        await self._create_tool_invocation(
            "call-weather-existing-first",
            run_id=run_id,
            name="get_weather",
            args={"city": "Shanghai"},
            order_index=0,
            now=fixed_now,
        )
        await self._create_tool_invocation(
            "call-balance-existing-first",
            run_id=run_id,
            name="get_deepseek_balance",
            args={},
            order_index=1,
            now=fixed_now,
        )
        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            first = await project_interrupt(
                session,
                run,
                self._interrupt("interrupt-existing-first"),
                now=fixed_now,
            )
            await session.commit()

        await self._create_tool_invocation(
            "call-weather-existing-second",
            run_id=run_id,
            name="get_weather",
            args={"city": "Shanghai"},
            order_index=3,
            now=fixed_now,
        )
        await self._create_tool_invocation(
            "call-balance-existing-second",
            run_id=run_id,
            name="get_deepseek_balance",
            args={},
            order_index=4,
            now=fixed_now,
        )
        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            second = await project_interrupt(
                session,
                run,
                self._interrupt("interrupt-existing-second"),
                now=fixed_now + timedelta(minutes=1),
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            batch = await session.get(ApprovalBatch, first.batch.id)
            assert batch is not None
            result = await project_interrupt(
                session,
                run,
                self._interrupt("interrupt-existing-first"),
                now=fixed_now + timedelta(minutes=2),
            )

        self.assertNotEqual(first.batch.id, second.batch.id)
        self.assertEqual(result.batch.id, first.batch.id)
        self.assertEqual(result.event.payload["part"]["batch"]["id"], first.batch.id)

        await self._reset_run(run_id)

    async def _test_run_executor_stops_stream_at_approval_required_without_done(
        self,
    ) -> None:
        run_id = "run-approval-stream"
        fixed_now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
        await self._reset_run(run_id)
        await self._create_run(run_id, now=fixed_now, status="queued")
        agent = FakeAgent(
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
                                    "id": "call-stream-weather",
                                    "index": 0,
                                    "type": "tool_call_chunk",
                                },
                                {
                                    "name": "get_deepseek_balance",
                                    "args": "{}",
                                    "id": "call-stream-balance",
                                    "index": 1,
                                    "type": "tool_call_chunk",
                                },
                            ],
                            response_metadata={"finish_reason": "tool_calls"},
                        ),
                        {"langgraph_node": "model"},
                    ),
                ),
                ("updates", {"__interrupt__": (self._interrupt("interrupt-stream"),)}),
                ("messages", (AIMessageChunk(content="must-not-project"), {})),
            ]
        )
        notifications: list[str] = []
        executor = RunExecutor(
            agent=agent,
            session_factory=AsyncSessionLocal,
            worker_id="worker-approval",
            now_factory=lambda: fixed_now,
            notify_run_events=lambda run_id: self._record_notification(
                notifications,
                run_id,
            ),
        )

        await executor.execute_start(AgentRunCommand(id="cmd-approval", run_id=run_id))

        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            event_rows = await session.execute(
                select(AgentRunEvent)
                .where(AgentRunEvent.agent_run_id == run_id)
                .order_by(AgentRunEvent.id.asc())
            )
            events = event_rows.scalars().all()

        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run.status, "awaiting_approval")
        self.assertEqual(
            [event.event_type for event in events],
            ["tool_call", "tool_call", "approval_required"],
        )
        self.assertNotIn("done", [event.event_type for event in events])
        self.assertEqual(notifications, [run_id, run_id, run_id])

        await self._reset_run(run_id)

    async def _record_notification(self, calls: list[str], run_id: str) -> None:
        calls.append(run_id)

    def _interrupt(self, interrupt_id: str) -> Interrupt:
        return Interrupt(
            id=interrupt_id,
            value={
                "action_requests": [
                    {
                        "name": "get_weather",
                        "args": {"city": "Shanghai"},
                        "description": "Approve weather lookup",
                    },
                    {
                        "name": "get_deepseek_balance",
                        "args": {},
                        "description": "Approve balance lookup",
                    },
                ],
                "review_configs": [
                    {
                        "action_name": "get_weather",
                        "allowed_decisions": ["approve", "reject"],
                    },
                    {
                        "action_name": "get_deepseek_balance",
                        "allowed_decisions": ["approve", "reject"],
                    },
                ],
            },
        )

    async def _create_run(
        self,
        run_id: str,
        *,
        now: datetime,
        status: str,
    ) -> None:
        conversation_id = f"conversation-{run_id}"
        async with AsyncSessionLocal() as session:
            session.add(
                Conversation(
                    id=conversation_id,
                    title="Approval interrupt",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                Message(
                    id=f"user-{run_id}",
                    conversation_id=conversation_id,
                    role="user",
                    content="hello",
                    reasoning="",
                    status="done",
                    created_at=now,
                )
            )
            session.add(
                Message(
                    id=f"assistant-{run_id}",
                    conversation_id=conversation_id,
                    role="assistant",
                    content="",
                    reasoning="",
                    status="streaming",
                    created_at=now,
                )
            )
            await session.flush()
            session.add(
                AgentRun(
                    id=run_id,
                    conversation_id=conversation_id,
                    user_message_id=f"user-{run_id}",
                    assistant_message_id=f"assistant-{run_id}",
                    status=status,
                    version=0,
                    lease_owner="worker-approval" if status == "running" else None,
                    lease_expires_at=now + timedelta(seconds=60)
                    if status == "running"
                    else None,
                    active_command_id="cmd-approval" if status == "running" else None,
                    error=None,
                    created_at=now,
                    updated_at=now,
                    completed_at=None,
                )
            )
            await session.commit()

    async def _create_tool_invocation(
        self,
        invocation_id: str,
        *,
        run_id: str,
        name: str,
        args: dict[str, object],
        order_index: int,
        now: datetime,
    ) -> None:
        async with AsyncSessionLocal() as session:
            session.add(
                ToolInvocation(
                    id=invocation_id,
                    message_id=f"assistant-{run_id}",
                    tool_name=name,
                    args=args,
                    result=None,
                    error=None,
                    latency_ms=None,
                    status="running",
                    created_at=now + timedelta(milliseconds=order_index),
                )
            )
            await session.flush()
            session.add(
                MessagePart(
                    id=f"part-{invocation_id}",
                    message_id=f"assistant-{run_id}",
                    type="tool",
                    order_index=order_index,
                    text="",
                    tool_invocation_id=invocation_id,
                    approval_batch_id=None,
                    created_at=now + timedelta(milliseconds=order_index),
                )
            )
            await session.commit()

    async def _reset_run(self, run_id: str) -> None:
        conversation_id = f"conversation-{run_id}"
        async with AsyncSessionLocal() as session:
            tool_ids = select(ToolInvocation.id).where(
                ToolInvocation.message_id == f"assistant-{run_id}"
            )
            await session.execute(
                delete(ApprovalRequest).where(
                    ApprovalRequest.tool_invocation_id.in_(tool_ids)
                )
            )
            batch_ids = select(ApprovalBatch.id).where(
                ApprovalBatch.agent_run_id == run_id
            )
            await session.execute(
                delete(ApprovalRequest).where(
                    ApprovalRequest.approval_batch_id.in_(batch_ids)
                )
            )
            await session.execute(
                delete(MessagePart).where(
                    MessagePart.message_id == f"assistant-{run_id}"
                )
            )
            await session.execute(
                delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(batch_ids))
            )
            await session.execute(
                delete(ApprovalBatch).where(ApprovalBatch.agent_run_id == run_id)
            )
            await session.execute(
                delete(OutboxEvent).where(
                    OutboxEvent.aggregate_id.like(f"approval-batch-{run_id}-%")
                )
            )
            await session.execute(
                delete(AgentRunEvent).where(AgentRunEvent.agent_run_id == run_id)
            )
            await session.execute(delete(AgentRun).where(AgentRun.id == run_id))
            await session.execute(
                delete(ToolInvocation).where(
                    ToolInvocation.message_id == f"assistant-{run_id}"
                )
            )
            await session.execute(
                delete(Message).where(Message.conversation_id == conversation_id)
            )
            await session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            )
            await session.commit()


if __name__ == "__main__":
    unittest.main()
