import asyncio
import unittest
from datetime import datetime
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from main import create_app
from core.database import AsyncSessionLocal, engine
from model.conversation import Conversation


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
