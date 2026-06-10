from __future__ import annotations

import json
from datetime import UTC, datetime

from model.conversation import Conversation
from model.message import Message
from model.message_part import MessagePart
from model.tool_invocation import ToolInvocation


class FakeChatStreamSession:
    def __init__(self) -> None:
        self.messages: dict[str, Message] = {}
        now = datetime(2026, 6, 8, 4, 0, tzinfo=UTC)
        self.conversations: dict[str, Conversation] = {
            "conversation-1": Conversation(
                id="conversation-1",
                title="Conversation",
                created_at=now,
                updated_at=now,
            ),
            "conversation-title": Conversation(
                id="conversation-title",
                title="Conversation",
                created_at=now,
                updated_at=now,
            ),
        }
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def add(self, row) -> None:
        if isinstance(row, Conversation):
            self.conversations[row.id] = row
            return
        if isinstance(row, Message):
            self.messages[row.id] = row
            return
        if isinstance(row, ToolInvocation):
            self.messages.setdefault("_tool_invocations", {})[row.id] = row
            return
        if isinstance(row, MessagePart):
            self.messages.setdefault("_message_parts", {})[row.id] = row
            return
        raise AssertionError(f"unexpected row type: {type(row)!r}")

    async def get(self, model, object_id: str):
        if model is Conversation:
            return self.conversations.get(object_id)
        if model is Message:
            return self.messages.get(object_id)
        if model is ToolInvocation:
            return self.messages.get("_tool_invocations", {}).get(object_id)
        if model is MessagePart:
            return self.messages.get("_message_parts", {}).get(object_id)
        return None

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


async def fake_get_conversation_by_id(
    session: FakeChatStreamSession, conversation_id: str
):
    return await session.get(Conversation, conversation_id)


class FakeChatStreamSessionFactory:
    def __init__(self) -> None:
        self.session = FakeChatStreamSession()

    def __call__(self) -> FakeChatStreamSession:
        return self.session


def decode_sse(frame: str) -> dict:
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    return json.loads(frame.removeprefix("data: ").strip())
