import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from main import create_app
from core.database import AsyncSessionLocal, engine
from model.agent_run import AgentRun
from model.agent_run_event import AgentRunEvent
from model.approval import ApprovalBatch, ApprovalRequest
from model.conversation import Conversation
from model.message import Message
from model.message_part import MessagePart
from model.tool_invocation import ToolInvocation


class CreateChatConversationTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        asyncio.run(engine.dispose())

    def test_creates_frontend_compatible_conversation(self) -> None:
        client = TestClient(create_app())

        response = client.post("/api/conversations", json={})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            set(payload),
            {"id", "title", "createdAt", "updatedAt"},
        )
        UUID(payload["id"])
        self.assertEqual(payload["title"], "New chat")
        created_at = datetime.fromisoformat(
            payload["createdAt"].replace("Z", "+00:00")
        )
        updated_at = datetime.fromisoformat(
            payload["updatedAt"].replace("Z", "+00:00")
        )
        self.assertEqual(created_at, updated_at)

        try:
            persisted = asyncio.run(self._get_conversation(payload["id"]))
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.title, "New chat")
        finally:
            asyncio.run(self._delete_conversation(payload["id"]))

    def test_lists_messages_with_tool_invocations_and_timeline_parts(self) -> None:
        seed = asyncio.run(self._seed_message_with_tool_timeline())
        client = TestClient(create_app())

        try:
            response = client.get(
                f"/api/conversation/messages/{seed['conversation_id']}"
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            messages = payload["messages"]
            self.assertIsNone(payload["activeRun"])
            assistant = next(item for item in messages if item["role"] == "assistant")
            self.assertEqual(assistant["toolInvocations"][0]["id"], "tool-history-1")
            self.assertEqual(len(assistant["timelineParts"]), 2)
            self.assertEqual(assistant["timelineParts"][0]["type"], "reasoning")
            self.assertEqual(assistant["timelineParts"][1]["type"], "tool")
            self.assertEqual(
                assistant["timelineParts"][1]["invocation"]["id"],
                "tool-history-1",
            )
        finally:
            asyncio.run(self._delete_conversation(seed["conversation_id"]))

    def test_lists_messages_with_approval_history_and_active_run(self) -> None:
        payload = asyncio.run(self._seed_approval_history_with_active_run())
        client = TestClient(create_app())

        try:
            response = client.get(
                f"/api/conversation/messages/{payload['conversation_id']}"
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(set(body), {"messages", "activeRun"})
            assistant = next(
                item
                for item in body["messages"]
                if item["id"] == payload["history_message_id"]
            )
            approval_parts = [
                part
                for part in assistant["timelineParts"]
                if part["type"] == "approval"
            ]
            self.assertEqual(
                [part["batch"]["requests"][0]["decision"] for part in approval_parts],
                ["approved", "rejected", "expired"],
            )
            expired = approval_parts[2]["batch"]
            self.assertEqual(expired["status"], "expired")
            self.assertEqual(expired["resolutionSource"], "timeout")
            self.assertEqual(
                [item["toolName"] for item in expired["requests"]],
                ["get_weather", "get_deepseek_balance"],
            )

            active_run = body["activeRun"]
            self.assertEqual(active_run["runId"], payload["active_run_id"])
            self.assertEqual(active_run["status"], "awaiting_approval")
            self.assertEqual(active_run["lastEventId"], payload["last_event_id"])
            self.assertEqual(
                active_run["assistantMessageId"],
                payload["active_message_id"],
            )
            self.assertEqual(
                active_run["approvalBatch"]["id"],
                payload["active_batch_id"],
            )
        finally:
            asyncio.run(self._delete_conversation(payload["conversation_id"]))

    def test_lists_user_before_assistant_when_messages_share_created_at(self) -> None:
        conversation_id = "conversation-same-time-order"
        asyncio.run(self._seed_user_and_assistant_with_same_created_at(conversation_id))
        client = TestClient(create_app())

        try:
            response = client.get(f"/api/conversation/messages/{conversation_id}")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                [message["role"] for message in response.json()["messages"]],
                ["user", "assistant"],
            )
        finally:
            asyncio.run(self._delete_conversation(conversation_id))

    async def _seed_message_with_tool_timeline(self) -> dict[str, str]:
        conversation_id = "conversation-history-shape"
        message_id = "assistant-history-shape"

        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(Message).where(Message.conversation_id == conversation_id)
            )
            await session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            )
            session.add(
                Conversation(
                    id=conversation_id,
                    title="History shape",
                    created_at=datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
                )
            )
            session.add(
                Message(
                    id=message_id,
                    conversation_id=conversation_id,
                    role="assistant",
                    content="今天晴。",
                    reasoning="先查工具。",
                    status="done",
                    created_at=datetime(2026, 6, 6, 12, 1, tzinfo=UTC),
                )
            )
            session.add(
                ToolInvocation(
                    id="tool-history-1",
                    message_id=message_id,
                    tool_name="get_weather",
                    args={"city": "北京"},
                    result='{"weather":"sunny"}',
                    error=None,
                    latency_ms=12,
                    status="completed",
                    created_at=datetime(2026, 6, 6, 12, 2, tzinfo=UTC),
                )
            )
            session.add_all(
                [
                    MessagePart(
                        id="part-history-reasoning",
                        message_id=message_id,
                        type="reasoning",
                        order_index=0,
                        text="先查工具。",
                        tool_invocation_id=None,
                        created_at=datetime(2026, 6, 6, 12, 1, 1, tzinfo=UTC),
                    ),
                    MessagePart(
                        id="part-history-tool",
                        message_id=message_id,
                        type="tool",
                        order_index=1,
                        text="",
                        tool_invocation_id="tool-history-1",
                        created_at=datetime(2026, 6, 6, 12, 2, 1, tzinfo=UTC),
                    ),
                    MessagePart(
                        id="part-history-orphan-tool",
                        message_id=message_id,
                        type="tool",
                        order_index=2,
                        text="",
                        tool_invocation_id=None,
                        created_at=datetime(2026, 6, 6, 12, 2, 2, tzinfo=UTC),
                    ),
                ]
            )
            await session.commit()

        return {"conversation_id": conversation_id, "message_id": message_id}

    async def _seed_approval_history_with_active_run(self) -> dict[str, object]:
        conversation_id = "conversation-approval-history"
        history_message_id = "assistant-approval-history"
        active_message_id = "assistant-active-run"
        active_run_id = "run-active-history"
        active_batch_id = "batch-active-history"
        now = datetime(2026, 6, 6, 14, 0, tzinfo=UTC)

        async with AsyncSessionLocal() as session:
            await self._delete_conversation(conversation_id)
            session.add(
                Conversation(
                    id=conversation_id,
                    title="Approval history",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add_all(
                [
                    Message(
                        id=f"user-{history_message_id}",
                        conversation_id=conversation_id,
                        role="user",
                        content="历史审批",
                        reasoning="",
                        status="done",
                        created_at=now,
                    ),
                    Message(
                        id=history_message_id,
                        conversation_id=conversation_id,
                        role="assistant",
                        content="审批历史",
                        reasoning="",
                        status="done",
                        created_at=now + timedelta(seconds=1),
                    ),
                    Message(
                        id=f"user-{active_run_id}",
                        conversation_id=conversation_id,
                        role="user",
                        content="当前审批",
                        reasoning="",
                        status="done",
                        created_at=now + timedelta(seconds=10),
                    ),
                    Message(
                        id=active_message_id,
                        conversation_id=conversation_id,
                        role="assistant",
                        content="",
                        reasoning="",
                        status="streaming",
                        created_at=now + timedelta(seconds=11),
                    ),
                ]
            )
            await session.flush()

            for index, decision in enumerate(["approved", "rejected", "expired"]):
                await self._add_approval_projection(
                    session=session,
                    conversation_id=conversation_id,
                    run_id=f"run-history-{decision}",
                    user_message_id=f"user-{history_message_id}",
                    assistant_message_id=history_message_id,
                    batch_id=f"batch-history-{decision}",
                    part_id=f"part-history-{decision}",
                    part_order=index,
                    batch_status="expired" if decision == "expired" else "resolved",
                    resolution_source="timeout"
                    if decision == "expired"
                    else "manual",
                    decisions=[decision]
                    if decision != "expired"
                    else ["expired", "expired"],
                    now=now + timedelta(seconds=index + 2),
                )

            await self._add_approval_projection(
                session=session,
                conversation_id=conversation_id,
                run_id=active_run_id,
                user_message_id=f"user-{active_run_id}",
                assistant_message_id=active_message_id,
                batch_id=active_batch_id,
                part_id="part-active-history",
                part_order=0,
                batch_status="pending",
                resolution_source=None,
                decisions=["pending"],
                now=now + timedelta(seconds=12),
                active=True,
            )
            event = AgentRunEvent(
                agent_run_id=active_run_id,
                event_type="approval_required",
                payload={"type": "approval_required", "runId": active_run_id},
                created_at=now + timedelta(seconds=13),
            )
            session.add(event)
            await session.flush()
            last_event_id = event.id
            await session.commit()

        return {
            "conversation_id": conversation_id,
            "history_message_id": history_message_id,
            "active_message_id": active_message_id,
            "active_run_id": active_run_id,
            "active_batch_id": active_batch_id,
            "last_event_id": last_event_id,
        }

    async def _add_approval_projection(
        self,
        *,
        session,
        conversation_id: str,
        run_id: str,
        user_message_id: str,
        assistant_message_id: str,
        batch_id: str,
        part_id: str,
        part_order: int,
        batch_status: str,
        resolution_source: str | None,
        decisions: list[str],
        now: datetime,
        active: bool = False,
    ) -> None:
        session.add(
            AgentRun(
                id=run_id,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                status="awaiting_approval" if active else "completed",
                version=0,
                lease_owner=None,
                lease_expires_at=None,
                active_command_id=None,
                error=None,
                created_at=now,
                updated_at=now,
                completed_at=None if active else now,
            )
        )
        session.add(
            ApprovalBatch(
                id=batch_id,
                agent_run_id=run_id,
                assistant_message_id=assistant_message_id,
                interrupt_id=f"interrupt-{batch_id}",
                sequence=1,
                status=batch_status,
                expires_at=now + timedelta(minutes=30),
                resolution_source=resolution_source,
                created_at=now,
                resolved_at=None if batch_status == "pending" else now,
            )
        )
        session.add(
            MessagePart(
                id=part_id,
                message_id=assistant_message_id,
                type="approval",
                order_index=part_order,
                text="",
                tool_invocation_id=None,
                approval_batch_id=batch_id,
                created_at=now,
            )
        )
        tools = (
            ["get_deepseek_balance", "get_weather"]
            if len(decisions) > 1
            else ["get_weather"]
        )
        for request_order, tool_name in enumerate(reversed(tools)):
            tool_id = f"{batch_id}-tool-{request_order}"
            decision = decisions[request_order]
            session.add(
                ToolInvocation(
                    id=tool_id,
                    message_id=assistant_message_id,
                    tool_name=tool_name,
                    args={"order": request_order},
                    result=None,
                    error=None,
                    latency_ms=None,
                    status=self._tool_status_for_decision(decision),
                    created_at=now + timedelta(milliseconds=request_order),
                )
            )
            session.add(
                ApprovalRequest(
                    id=f"{batch_id}-request-{request_order}",
                    approval_batch_id=batch_id,
                    tool_invocation_id=tool_id,
                    order_index=request_order,
                    tool_name=tool_name,
                    args={"order": request_order},
                    decision=decision,
                    decided_at=None if decision == "pending" else now,
                )
            )

    def _tool_status_for_decision(self, decision: str) -> str:
        if decision == "approved":
            return "completed"
        if decision == "pending":
            return "awaiting_approval"
        return decision

    async def _seed_user_and_assistant_with_same_created_at(
        self,
        conversation_id: str,
    ) -> None:
        created_at = datetime(2026, 6, 6, 13, 0, tzinfo=UTC)

        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(Message).where(Message.conversation_id == conversation_id)
            )
            await session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            )
            session.add(
                Conversation(
                    id=conversation_id,
                    title="Same time order",
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            session.add_all(
                [
                    Message(
                        id="assistant-same-time",
                        conversation_id=conversation_id,
                        role="assistant",
                        content="助手回复",
                        reasoning="",
                        status="done",
                        created_at=created_at,
                    ),
                    Message(
                        id="user-same-time",
                        conversation_id=conversation_id,
                        role="user",
                        content="用户消息",
                        reasoning="",
                        status="done",
                        created_at=created_at,
                    ),
                ]
            )
            await session.commit()

    async def _get_conversation(self, conversation_id: str) -> Conversation | None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            return result.scalar_one_or_none()

    async def _delete_conversation(self, conversation_id: str) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            )
            await session.commit()


if __name__ == "__main__":
    unittest.main()
