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
            message=_project_stream_message(assistant_message),
        )
    )

    content = ""
    reasoning = ""
    has_partial_text = False
    has_partial_thinking = False
    sdk_session_id = getattr(existing_agent_session, "sdk_session_id", None)
    session_store = PostgresSessionStore(AsyncSessionLocal)

    try:
        async for sdk_message in stream_query(
            prompt=message,
            session_store=session_store,
            resume=sdk_session_id,
        ):
            sdk_session_id = _extract_session_id(sdk_message) or sdk_session_id
            sdk_result_error = _extract_result_error_message(sdk_message)
            if sdk_result_error is not None:
                raise RuntimeError(sdk_result_error)

            is_partial_delta = _is_content_block_delta_event(sdk_message)

            thinking_deltas = (
                _extract_thinking_deltas(sdk_message)
                if is_partial_delta or not has_partial_thinking
                else []
            )
            if is_partial_delta and thinking_deltas:
                has_partial_thinking = True
            for text in thinking_deltas:
                reasoning += text
                yield _to_sse(
                    ReasoningEvent(
                        type="reasoning",
                        message_id=assistant_message_id,
                        text=text,
                    )
                )

            text_deltas = (
                _extract_text_deltas(sdk_message)
                if is_partial_delta or not has_partial_text
                else []
            )
            if is_partial_delta and text_deltas:
                has_partial_text = True
            for text in text_deltas:
                content += text
                yield _to_sse(
                    DeltaEvent(
                        type="delta",
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
            if sdk_session_id:
                await upsert_agent_session(
                    session,
                    conversation_id=conversation_id,
                    sdk_session_id=sdk_session_id,
                )
            await session.commit()

        yield _to_sse(
            ErrorEvent(
                type="error",
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


def _is_content_block_delta_event(sdk_message: Any) -> bool:
    event = getattr(sdk_message, "event", None)
    return isinstance(event, dict) and event.get("type") == "content_block_delta"


def _extract_result_error_message(sdk_message: Any) -> str | None:
    if not _is_error_result_message(sdk_message):
        return None

    errors = getattr(sdk_message, "errors", None)
    if isinstance(errors, list):
        for error in errors:
            message = _extract_error_text(error)
            if message:
                return message

    return "SDK stream result failed"


def _is_error_result_message(sdk_message: Any) -> bool:
    if getattr(sdk_message, "is_error", False) is True:
        return True

    subtype = getattr(sdk_message, "subtype", None)
    if isinstance(subtype, str) and subtype.lower() in {"error", "failed", "failure"}:
        return True

    errors = getattr(sdk_message, "errors", None)
    return bool(errors)


def _extract_error_text(error: Any) -> str | None:
    if isinstance(error, str) and error:
        return error
    if isinstance(error, dict):
        message = error.get("message") or error.get("error")
        return message if isinstance(message, str) and message else None

    message = getattr(error, "message", None)
    return message if isinstance(message, str) and message else None


def _extract_text_deltas(sdk_message: Any) -> list[str]:
    event = getattr(sdk_message, "event", None)
    if isinstance(event, dict):
        if event.get("type") == "content_block_delta":
            delta = event.get("delta")
            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                text = delta.get("text")
                return [text] if isinstance(text, str) and text else []
            return []

    if getattr(sdk_message, "type", None) == "stream_event":
        return []

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
        if event.get("type") == "content_block_delta":
            delta = event.get("delta")
            if isinstance(delta, dict) and delta.get("type") == "thinking_delta":
                thinking = delta.get("thinking")
                return [thinking] if isinstance(thinking, str) and thinking else []
            return []

    if getattr(sdk_message, "type", None) == "stream_event":
        return []

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
