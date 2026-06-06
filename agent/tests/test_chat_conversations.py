import asyncio
import unittest
from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from main import create_app
from core.database import AsyncSessionLocal, engine
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
        payload = asyncio.run(self._seed_message_with_tool_timeline())
        client = TestClient(create_app())

        try:
            response = client.get(
                f"/api/conversation/messages/{payload['conversation_id']}"
            )

            self.assertEqual(response.status_code, 200)
            messages = response.json()
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
            asyncio.run(self._delete_conversation(payload["conversation_id"]))

    def test_lists_user_before_assistant_when_messages_share_created_at(self) -> None:
        conversation_id = "conversation-same-time-order"
        asyncio.run(self._seed_user_and_assistant_with_same_created_at(conversation_id))
        client = TestClient(create_app())

        try:
            response = client.get(f"/api/conversation/messages/{conversation_id}")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                [message["role"] for message in response.json()],
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
