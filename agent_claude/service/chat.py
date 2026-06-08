import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from core.database import AsyncSessionLocal
from model.message import Message
from repository.agent_session import (
    get_agent_session_by_conversation_id,
    upsert_agent_session,
)
from repository.message import create_message, update_message
from schema.chat import (
    ChatMessage,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    MessageCreatedEvent,
    ReasoningEvent,
)
from service.runtime import stream_query
from service.session_store import PostgresSessionStore


async def stream_chat(
    *,
    conversation_id: str,
    message: str,
) -> AsyncIterator[str]:
    run_id = str(uuid4())
    assistant_message_id = str(uuid4())
    now = datetime.now(UTC)

    async with AsyncSessionLocal() as session:
        await create_message(
            session,
            Message(
                id=str(uuid4()),
                conversation_id=conversation_id,
                role="user",
                content=message,
                reasoning="",
                status="done",
                created_at=now,
            ),
        )
        assistant_message = await create_message(
            session,
            Message(
                id=assistant_message_id,
                conversation_id=conversation_id,
                role="assistant",
                content="",
                reasoning="",
                status="streaming",
                created_at=now,
            ),
        )
        existing_agent_session = await get_agent_session_by_conversation_id(
            session,
            conversation_id,
        )
        await session.commit()

    yield _to_sse(
        MessageCreatedEvent(
            type="message_created",
            run_id=run_id,
            message=_project_stream_message(assistant_message),
        )
    )

    content = ""
    reasoning = ""
    sdk_session_id = getattr(existing_agent_session, "sdk_session_id", None)
    session_store = PostgresSessionStore(AsyncSessionLocal)

    try:
        async for sdk_message in stream_query(
            prompt=message,
            session_store=session_store,
            resume=sdk_session_id,
        ):
            sdk_session_id = _extract_session_id(sdk_message) or sdk_session_id

            for text in _extract_thinking_deltas(sdk_message):
                reasoning += text
                yield _to_sse(
                    ReasoningEvent(
                        type="reasoning",
                        run_id=run_id,
                        message_id=assistant_message_id,
                        text=text,
                    )
                )

            for text in _extract_text_deltas(sdk_message):
                content += text
                yield _to_sse(
                    DeltaEvent(
                        type="delta",
                        run_id=run_id,
                        message_id=assistant_message_id,
                        text=text,
                    )
                )

        async with AsyncSessionLocal() as session:
            await update_message(
                session,
                message_id=assistant_message_id,
                content=content,
                reasoning=reasoning,
                status="done",
            )
            if sdk_session_id:
                await upsert_agent_session(
                    session,
                    conversation_id=conversation_id,
                    sdk_session_id=sdk_session_id,
                )
            await session.commit()

        yield _to_sse(
            DoneEvent(
                type="done",
                run_id=run_id,
                message_id=assistant_message_id,
            )
        )
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            await update_message(
                session,
                message_id=assistant_message_id,
                content=content,
                reasoning=reasoning,
                status="error",
            )
            await session.commit()

        yield _to_sse(
            ErrorEvent(
                type="error",
                run_id=run_id,
                message_id=assistant_message_id,
                message=str(exc) or exc.__class__.__name__,
            )
        )


def _project_stream_message(message: Message) -> ChatMessage:
    return ChatMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        reasoning=None,
        tool_invocations=[],
        timeline_parts=[],
        status=message.status,
        created_at=_format_datetime(message.created_at),
    )


def _to_sse(event: Any) -> str:
    payload = event.model_dump(by_alias=True, exclude_none=True)
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _extract_session_id(sdk_message: Any) -> str | None:
    session_id = getattr(sdk_message, "session_id", None)
    if isinstance(session_id, str) and session_id:
        return session_id
    return None


def _extract_text_deltas(sdk_message: Any) -> list[str]:
    event = getattr(sdk_message, "event", None)
    if isinstance(event, dict):
        delta = event.get("delta")
        if isinstance(delta, dict) and delta.get("type") == "text_delta":
            text = delta.get("text")
            return [text] if isinstance(text, str) and text else []

    content = getattr(sdk_message, "content", None)
    if isinstance(content, list):
        return [
            block.text
            for block in content
            if isinstance(getattr(block, "text", None), str) and block.text
        ]
    return []


def _extract_thinking_deltas(sdk_message: Any) -> list[str]:
    event = getattr(sdk_message, "event", None)
    if isinstance(event, dict):
        delta = event.get("delta")
        if isinstance(delta, dict) and delta.get("type") == "thinking_delta":
            thinking = delta.get("thinking")
            return [thinking] if isinstance(thinking, str) and thinking else []

    content = getattr(sdk_message, "content", None)
    if isinstance(content, list):
        return [
            block.thinking
            for block in content
            if isinstance(getattr(block, "thinking", None), str) and block.thinking
        ]
    return []


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
