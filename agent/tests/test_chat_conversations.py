import unittest
from datetime import datetime
from uuid import UUID

from fastapi.testclient import TestClient

from main import create_app


class CreateChatConversationTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
