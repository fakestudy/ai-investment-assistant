import asyncio
import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from core.database import AsyncSessionLocal, engine
from model.agent_run import AgentRun
from model.agent_run_event import AgentRunEvent
from model.approval import ApprovalBatch, ApprovalRequest
from model.conversation import Conversation
from model.message import Message
from model.outbox_event import OutboxEvent
from model.tool_invocation import ToolInvocation
from schema.chat import ApprovalDecisionRequest
from service.approval import (
    ApprovalDecisionConflict,
    ApprovalDecisionValidationError,
    submit_approval_decisions,
)


class ApprovalServiceTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        asyncio.run(engine.dispose())

    def test_manual_decisions_and_resume_outbox_commit_together(self) -> None:
        asyncio.run(self._test_manual_decisions_and_resume_outbox_commit_together())

    def test_rejects_incomplete_duplicate_foreign_and_expired_decisions(self) -> None:
        asyncio.run(
            self._test_rejects_incomplete_duplicate_foreign_and_expired_decisions()
        )

    def test_repeated_same_submission_is_idempotent_without_new_resume_outbox(
        self,
    ) -> None:
        asyncio.run(
            self._test_repeated_same_submission_is_idempotent_without_new_resume_outbox()
        )

    def test_repeated_different_submission_conflicts(self) -> None:
        asyncio.run(self._test_repeated_different_submission_conflicts())

    async def _test_manual_decisions_and_resume_outbox_commit_together(self) -> None:
        run_id = "run-approval-service"
        now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
        batch_id = await self._create_pending_batch(run_id, now=now)
        request = ApprovalDecisionRequest.model_validate(
            {
                "afterEventId": 4,
                "decisions": [
                    {
                        "approvalRequestId": f"{batch_id}-request-0",
                        "decision": "approve",
                    },
                    {
                        "approvalRequestId": f"{batch_id}-request-1",
                        "decision": "reject",
                    },
                ],
            }
        )

        async with AsyncSessionLocal() as session:
            result = await submit_approval_decisions(
                session,
                batch_id,
                request,
                now=now + timedelta(minutes=1),
            )
            await session.commit()

        self.assertEqual(
            [item.decision for item in result.requests],
            ["approved", "rejected"],
        )
        self.assertEqual(result.batch.resolution_source, "manual")
        self.assertEqual(result.run.status, "resume_queued")
        self.assertEqual(result.outbox.event_type, "agent.run.resume")
        self.assertEqual(result.outbox.id, f"{batch_id}-resume")
        self.assertEqual(result.event.event_type, "approval_resolved")
        self.assertEqual(
            result.outbox.payload["decisions"],
            [{"type": "approve"}, {"type": "reject", "message": "Rejected by user"}],
        )

        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            tool_0 = await session.get(ToolInvocation, f"{batch_id}-tool-0")
            tool_1 = await session.get(ToolInvocation, f"{batch_id}-tool-1")
            events = (
                await session.execute(
                    select(AgentRunEvent)
                    .where(AgentRunEvent.agent_run_id == run_id)
                    .order_by(AgentRunEvent.id.asc())
                )
            ).scalars().all()
            outboxes = (
                await session.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.aggregate_id == batch_id)
                    .where(OutboxEvent.event_type == "agent.run.resume")
                )
            ).scalars().all()

        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run.status, "resume_queued")
        self.assertIsNone(run.lease_owner)
        self.assertIsNone(run.lease_expires_at)
        self.assertIsNotNone(tool_0)
        self.assertIsNotNone(tool_1)
        assert tool_0 is not None and tool_1 is not None
        self.assertEqual(tool_0.status, "running")
        self.assertEqual(tool_1.status, "rejected")
        self.assertEqual([event.event_type for event in events], ["approval_resolved"])
        self.assertEqual(len(outboxes), 1)

        await self._reset_run(run_id)

    async def _test_rejects_incomplete_duplicate_foreign_and_expired_decisions(
        self,
    ) -> None:
        now = datetime(2026, 6, 7, 11, 0, tzinfo=UTC)
        batch_id = await self._create_pending_batch("run-approval-validation", now=now)
        foreign_batch_id = await self._create_pending_batch(
            "run-approval-foreign",
            now=now,
        )

        cases = [
            {
                "afterEventId": 1,
                "decisions": [
                    {
                        "approvalRequestId": f"{batch_id}-request-0",
                        "decision": "approve",
                    }
                ],
            },
            {
                "afterEventId": 1,
                "decisions": [
                    {
                        "approvalRequestId": f"{batch_id}-request-0",
                        "decision": "approve",
                    },
                    {
                        "approvalRequestId": f"{batch_id}-request-0",
                        "decision": "reject",
                    },
                ],
            },
            {
                "afterEventId": 1,
                "decisions": [
                    {
                        "approvalRequestId": f"{batch_id}-request-0",
                        "decision": "approve",
                    },
                    {
                        "approvalRequestId": f"{foreign_batch_id}-request-1",
                        "decision": "reject",
                    },
                ],
            },
        ]

        for payload in cases:
            async with AsyncSessionLocal() as session:
                with self.assertRaises(ApprovalDecisionValidationError):
                    await submit_approval_decisions(
                        session,
                        batch_id,
                        ApprovalDecisionRequest.model_validate(payload),
                        now=now + timedelta(minutes=1),
                    )
                await session.rollback()

        async with AsyncSessionLocal() as session:
            with self.assertRaises(ApprovalDecisionConflict):
                await submit_approval_decisions(
                    session,
                    batch_id,
                    ApprovalDecisionRequest.model_validate(
                        {
                            "afterEventId": 1,
                            "decisions": [
                                {
                                    "approvalRequestId": f"{batch_id}-request-0",
                                    "decision": "approve",
                                },
                                {
                                    "approvalRequestId": f"{batch_id}-request-1",
                                    "decision": "reject",
                                },
                            ],
                        }
                    ),
                    now=now + timedelta(minutes=31),
                )
            await session.rollback()

        await self._reset_run("run-approval-validation")
        await self._reset_run("run-approval-foreign")

    async def _test_repeated_same_submission_is_idempotent_without_new_resume_outbox(
        self,
    ) -> None:
        run_id = "run-approval-idempotent"
        now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
        batch_id = await self._create_pending_batch(run_id, now=now)
        request = ApprovalDecisionRequest.model_validate(
            {
                "afterEventId": 1,
                "decisions": [
                    {
                        "approvalRequestId": f"{batch_id}-request-0",
                        "decision": "approve",
                    },
                    {
                        "approvalRequestId": f"{batch_id}-request-1",
                        "decision": "reject",
                    },
                ],
            }
        )

        async with AsyncSessionLocal() as session:
            first = await submit_approval_decisions(
                session,
                batch_id,
                request,
                now=now + timedelta(minutes=1),
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            second = await submit_approval_decisions(
                session,
                batch_id,
                request,
                now=now + timedelta(minutes=2),
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            count = len(
                (
                    await session.execute(
                        select(OutboxEvent)
                        .where(OutboxEvent.aggregate_id == batch_id)
                        .where(OutboxEvent.event_type == "agent.run.resume")
                    )
                ).scalars().all()
            )

        self.assertEqual(first.outbox.id, second.outbox.id)
        self.assertEqual(first.event.id, second.event.id)
        self.assertEqual(count, 1)
        await self._reset_run(run_id)

    async def _test_repeated_different_submission_conflicts(self) -> None:
        run_id = "run-approval-different"
        now = datetime(2026, 6, 7, 13, 0, tzinfo=UTC)
        batch_id = await self._create_pending_batch(run_id, now=now)
        first_request = ApprovalDecisionRequest.model_validate(
            {
                "afterEventId": 1,
                "decisions": [
                    {
                        "approvalRequestId": f"{batch_id}-request-0",
                        "decision": "approve",
                    },
                    {
                        "approvalRequestId": f"{batch_id}-request-1",
                        "decision": "reject",
                    },
                ],
            }
        )
        different_request = ApprovalDecisionRequest.model_validate(
            {
                "afterEventId": 1,
                "decisions": [
                    {
                        "approvalRequestId": f"{batch_id}-request-0",
                        "decision": "reject",
                    },
                    {
                        "approvalRequestId": f"{batch_id}-request-1",
                        "decision": "reject",
                    },
                ],
            }
        )

        async with AsyncSessionLocal() as session:
            await submit_approval_decisions(
                session,
                batch_id,
                first_request,
                now=now + timedelta(minutes=1),
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            with self.assertRaises(ApprovalDecisionConflict):
                await submit_approval_decisions(
                    session,
                    batch_id,
                    different_request,
                    now=now + timedelta(minutes=2),
                )
            await session.rollback()

        await self._reset_run(run_id)

    async def _create_pending_batch(self, run_id: str, *, now: datetime) -> str:
        await self._reset_run(run_id)
        conversation_id = f"conversation-{run_id}"
        batch_id = f"{run_id}-batch"
        async with AsyncSessionLocal() as session:
            session.add(
                Conversation(
                    id=conversation_id,
                    title="Approval service",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add_all(
                [
                    Message(
                        id=f"user-{run_id}",
                        conversation_id=conversation_id,
                        role="user",
                        content="hello",
                        reasoning="",
                        status="done",
                        created_at=now,
                    ),
                    Message(
                        id=f"assistant-{run_id}",
                        conversation_id=conversation_id,
                        role="assistant",
                        content="",
                        reasoning="",
                        status="streaming",
                        created_at=now,
                    ),
                ]
            )
            await session.flush()
            session.add(
                AgentRun(
                    id=run_id,
                    conversation_id=conversation_id,
                    user_message_id=f"user-{run_id}",
                    assistant_message_id=f"assistant-{run_id}",
                    status="awaiting_approval",
                    version=0,
                    lease_owner=None,
                    lease_expires_at=None,
                    active_command_id=None,
                    error=None,
                    created_at=now,
                    updated_at=now,
                    completed_at=None,
                )
            )
            session.add(
                ApprovalBatch(
                    id=batch_id,
                    agent_run_id=run_id,
                    assistant_message_id=f"assistant-{run_id}",
                    interrupt_id=f"interrupt-{run_id}",
                    sequence=1,
                    status="pending",
                    expires_at=now + timedelta(minutes=30),
                    resolution_source=None,
                    created_at=now,
                    resolved_at=None,
                )
            )
            for index, tool_name in enumerate(["get_weather", "get_deepseek_balance"]):
                tool_id = f"{batch_id}-tool-{index}"
                session.add(
                    ToolInvocation(
                        id=tool_id,
                        message_id=f"assistant-{run_id}",
                        tool_name=tool_name,
                        args={"index": index},
                        result=None,
                        error=None,
                        latency_ms=None,
                        status="awaiting_approval",
                        created_at=now,
                    )
                )
                session.add(
                    ApprovalRequest(
                        id=f"{batch_id}-request-{index}",
                        approval_batch_id=batch_id,
                        tool_invocation_id=tool_id,
                        order_index=index,
                        tool_name=tool_name,
                        args={"index": index},
                        decision="pending",
                        decided_at=None,
                    )
                )
            await session.commit()
        return batch_id

    async def _reset_run(self, run_id: str) -> None:
        conversation_id = f"conversation-{run_id}"
        batch_id = f"{run_id}-batch"
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(OutboxEvent).where(OutboxEvent.aggregate_id == batch_id)
            )
            await session.execute(
                delete(OutboxEvent).where(OutboxEvent.id.like(f"{batch_id}-%"))
            )
            await session.execute(
                delete(AgentRunEvent).where(AgentRunEvent.agent_run_id == run_id)
            )
            await session.execute(delete(AgentRun).where(AgentRun.id == run_id))
            await session.execute(
                delete(Message).where(Message.conversation_id == conversation_id)
            )
            await session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            )
            await session.commit()


if __name__ == "__main__":
    unittest.main()
