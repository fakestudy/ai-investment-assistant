from collections.abc import AsyncIterator

from core.database import AsyncSessionLocal
from repository.agent_session import (
    get_agent_session_by_conversation_id,
    upsert_agent_session,
)
from repository.conversation import get_conversation_by_id, update_conversation_title
from service.chat_stream import ChatStreamDependencies
from service.chat_stream import stream_chat as _stream_chat
from service.runtime import generate_title as generate_conversation_title
from service.runtime import stream_query


async def stream_chat(
    *,
    conversation_id: str,
    message: str,
    generate_title: bool | None = None,
) -> AsyncIterator[str]:
    dependencies = ChatStreamDependencies(
        async_session_factory=AsyncSessionLocal,
        get_conversation_by_id=get_conversation_by_id,
        get_agent_session_by_conversation_id=get_agent_session_by_conversation_id,
        upsert_agent_session=upsert_agent_session,
        stream_query=stream_query,
        update_conversation_title=update_conversation_title,
        generate_title=generate_conversation_title,
    )
    async for frame in _stream_chat(
        conversation_id=conversation_id,
        message=message,
        generate_title=generate_title,
        dependencies=dependencies,
    ):
        yield frame


__all__ = ["stream_chat"]
