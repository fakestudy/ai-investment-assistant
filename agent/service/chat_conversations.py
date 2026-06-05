from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from schema.chat_conversations import ChatConversation


def create_chat_conversation(
    *,
    id_factory: Callable[[], str] = lambda: str(uuid4()),
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ChatConversation:
    now = now_factory()
    return ChatConversation(
        id=id_factory(),
        title="New chat",
        created_at=now,
        updated_at=now,
    )
