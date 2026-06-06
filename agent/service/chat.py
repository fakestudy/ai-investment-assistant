import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessageChunk, ToolMessage
from langchain_deepseek import ChatDeepSeek

from core.database import AsyncSessionLocal
from model.message import Message
from model.message_part import MessagePart
from model.tool_invocation import ToolInvocation
from repository.conversation import update_conversation_title
from repository.message import (
    create_message,
    get_messages_by_conversation_id,
    update_message,
)
from repository.message_part import create_message_part, update_message_part_text
from repository.tool_invocation import create_tool_invocation, update_tool_invocation
from schema.chat import ChatStreamRequest
from service.agent_factory import build_agent

# from middleware.file_system_middleware import file_system_middleware


TITLE_MAX_LENGTH = 60
_TITLE_NOT_GENERATED = object()


class TimelineState:
    def __init__(self) -> None:
        self.next_order_index = 0
        self.last_part_id: str | None = None
        self.last_part_type: str | None = None
        self.last_part_text = ""


def get_conversation_title(prompt: str, model: Any | None = None) -> str:
    fallback = _normalize_title(prompt, "New chat")
    title_model = model or ChatDeepSeek(
        model=os.getenv("DEEPSEEK_MODEL_FLASH", "deepseek-v4-flash"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
    )

    try:
        response = title_model.invoke(
            [
                (
                    "system",
                    "Generate a concise conversation title from the user message. "
                    "Return only the title without quotes, markdown, or explanation.",
                ),
                ("human", prompt),
            ]
        )
    except Exception:
        return fallback

    return _normalize_title(_content_text(response.content), fallback)


def format_sse_data(chunk: object) -> str:
    payload = json.dumps(chunk, ensure_ascii=False)
    return f"data: {payload}\n\n"


def iter_chat_events(
    request: ChatStreamRequest,
    *,
    agent: Any | None = None,
    title_generator: Callable[[str], str] = get_conversation_title,
    message_id_factory: Callable[[], str] = lambda: str(uuid4()),
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC),
    input_messages: list[dict[str, str]] | None = None,
    generated_title: str | None | object = _TITLE_NOT_GENERATED,
) -> Iterator[dict[str, Any]]:
    assistant_id = message_id_factory()

    yield {
        "type": "message_created",
        "message": {
            "id": assistant_id,
            "conversationId": request.conversation_id,
            "role": "assistant",
            "content": "",
            "status": "streaming",
            "createdAt": _format_datetime(now_factory()),
        },
    }

    try:
        runtime_agent = agent or build_agent()
        stream = runtime_agent.stream(
            input={
                "messages": input_messages
                or [{"role": "user", "content": request.message}],
            },
            stream_mode="messages",
        )

        pending_tool_chunk: AIMessageChunk | None = None
        tool_invocations: dict[str, dict[str, Any]] = {}
        tool_started_at: dict[str, float] = {}
        if generated_title is _TITLE_NOT_GENERATED:
            title = title_generator(request.message) if request.generate_title else None
        else:
            title = generated_title

        for stream_item in stream:
            message = _stream_message(stream_item)

            if isinstance(message, AIMessageChunk):
                reasoning = _reasoning_text(message)
                if reasoning:
                    yield {
                        "type": "reasoning",
                        "messageId": assistant_id,
                        "text": reasoning,
                    }

                if message.tool_call_chunks:
                    pending_tool_chunk = (
                        message
                        if pending_tool_chunk is None
                        else pending_tool_chunk + message
                    )

                if (
                    pending_tool_chunk is not None
                    and message.response_metadata.get("finish_reason") == "tool_calls"
                ):
                    events, invocations, started_at = _tool_call_events(
                        pending_tool_chunk,
                        assistant_id,
                    )
                    tool_invocations.update(invocations)
                    tool_started_at.update(started_at)
                    yield from events
                    pending_tool_chunk = None

                content = _content_text(message.content)
                if content:
                    yield {
                        "type": "delta",
                        "messageId": assistant_id,
                        "text": content,
                    }
                continue

            if not isinstance(message, ToolMessage):
                continue

            if pending_tool_chunk is not None:
                events, invocations, started_at = _tool_call_events(
                    pending_tool_chunk,
                    assistant_id,
                )
                tool_invocations.update(invocations)
                tool_started_at.update(started_at)
                yield from events
                pending_tool_chunk = None

            tool_call_id = message.tool_call_id
            invocation = tool_invocations.get(tool_call_id)
            if invocation is None:
                invocation = {
                    "id": tool_call_id,
                    "messageId": assistant_id,
                    "toolName": message.name or "",
                    "args": {},
                    "status": "running",
                }
                tool_invocations[tool_call_id] = invocation
                tool_started_at[tool_call_id] = monotonic()
                yield {
                    "type": "tool_call",
                    "messageId": assistant_id,
                    "invocation": invocation,
                }

            result = _content_text(message.content)
            completed_invocation = {
                **invocation,
                "latencyMs": max(
                    0,
                    int(
                        (monotonic() - tool_started_at.get(tool_call_id, monotonic()))
                        * 1000
                    ),
                ),
            }
            if message.status == "error":
                completed_invocation.update(
                    {
                        "error": result,
                        "status": "error",
                    }
                )
            else:
                completed_invocation.update(
                    {
                        "result": result,
                        "status": "completed",
                    }
                )
            tool_invocations[tool_call_id] = completed_invocation
            yield {
                "type": "tool_result",
                "messageId": assistant_id,
                "invocation": completed_invocation,
            }

        if title is not None:
            yield {
                "type": "title",
                "conversationId": request.conversation_id,
                "title": title,
            }
        yield {"type": "done", "messageId": assistant_id}
    except Exception as exc:
        yield {
            "type": "error",
            "messageId": assistant_id,
            "message": str(exc),
        }


async def iter_chat_events_with_persistence(
    request: ChatStreamRequest,
    *,
    session_factory: Callable[[], Any] = AsyncSessionLocal,
    agent: Any | None = None,
    title_generator: Callable[[str], str] = get_conversation_title,
    message_id_factory: Callable[[], str] = lambda: str(uuid4()),
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> AsyncIterator[dict[str, Any]]:
    input_messages = await _load_history_and_persist_user_message(
        request=request,
        session_factory=session_factory,
        now_factory=now_factory,
    )
    title_task: asyncio.Task[str | None] | None = None
    if request.generate_title:
        title_task = asyncio.create_task(
            _update_conversation_title_for_request(
                request=request,
                session_factory=session_factory,
                title_generator=title_generator,
            )
        )

    assistant_id: str | None = None
    assistant_content: list[str] = []
    assistant_reasoning: list[str] = []
    assistant_status = "done"
    timeline_state = TimelineState()
    pending_tool_invocation_ids: set[str] = set()

    try:
        for event in iter_chat_events(
            request,
            agent=agent,
            title_generator=title_generator,
            message_id_factory=message_id_factory,
            now_factory=now_factory,
            input_messages=input_messages,
            generated_title=None,
        ):
            event_type = event.get("type")
            if event_type == "message_created":
                message = event["message"]
                assistant_id = message["id"]
                await _create_assistant_message_with_new_session(
                    session_factory=session_factory,
                    message_id=assistant_id,
                    conversation_id=request.conversation_id,
                    created_at=_parse_frontend_datetime(message["createdAt"]),
                )
            elif event_type == "delta":
                assistant_content.append(event["text"])
            elif event_type == "reasoning":
                assistant_reasoning.append(event["text"])
                await _persist_reasoning_part_with_new_session(
                    session_factory=session_factory,
                    message_id=assistant_id,
                    text=event["text"],
                    now_factory=now_factory,
                    timeline_state=timeline_state,
                )
            elif event_type == "tool_call":
                await _persist_tool_call_with_new_session(
                    session_factory=session_factory,
                    invocation=event["invocation"],
                    now_factory=now_factory,
                    timeline_state=timeline_state,
                )
                pending_tool_invocation_ids.add(event["invocation"]["id"])
            elif event_type == "tool_result":
                await _persist_tool_result_with_new_session(
                    session_factory=session_factory,
                    invocation=event["invocation"],
                )
                pending_tool_invocation_ids.discard(event["invocation"]["id"])
            elif event_type == "error":
                assistant_status = "error"
                await _mark_unfinished_tool_invocations_error_with_new_session(
                    session_factory=session_factory,
                    invocation_ids=pending_tool_invocation_ids,
                    error=event.get("message") or "Stream failed",
                )
                pending_tool_invocation_ids.clear()

            if event_type in {"done", "error"}:
                try:
                    await _update_assistant_message_with_new_session(
                        session_factory=session_factory,
                        message_id=assistant_id or message_id_factory(),
                        content="".join(assistant_content),
                        reasoning="".join(assistant_reasoning),
                        status=assistant_status,
                    )
                except Exception as exc:
                    yield {
                        "type": "error",
                        "messageId": assistant_id or "",
                        "message": f"Failed to persist assistant message: {exc}",
                    }
                    continue

            if event_type == "done" and title_task is not None:
                title = await _get_title_task_result(title_task)
                title_task = None
                if title is not None:
                    yield {
                        "type": "title",
                        "conversationId": request.conversation_id,
                        "title": title,
                    }

            yield event
    finally:
        if title_task is not None:
            title_task.cancel()
            await asyncio.gather(title_task, return_exceptions=True)


async def iter_sse_events(
    request: ChatStreamRequest,
) -> AsyncIterator[str]:
    async for event in iter_chat_events_with_persistence(request):
        yield format_sse_data(event)


async def _load_history_and_persist_user_message(
    *,
    request: ChatStreamRequest,
    session_factory: Callable[[], Any],
    now_factory: Callable[[], datetime],
) -> list[dict[str, str]]:
    async with session_factory() as session:
        try:
            history_messages = await get_messages_by_conversation_id(
                session=session,
                conversation_id=request.conversation_id,
            )
            input_messages = _build_agent_messages(history_messages, request.message)

            user_message = Message(
                id=str(uuid4()),
                conversation_id=request.conversation_id,
                role="user",
                content=request.message,
                reasoning="",
                status="done",
                created_at=now_factory(),
            )
            await create_message(session, user_message)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    return input_messages


async def _create_assistant_message_with_new_session(
    *,
    session_factory: Callable[[], Any],
    message_id: str,
    conversation_id: str,
    created_at: datetime,
) -> None:
    async with session_factory() as session:
        try:
            await create_message(
                session,
                Message(
                    id=message_id,
                    conversation_id=conversation_id,
                    role="assistant",
                    content="",
                    reasoning="",
                    status="streaming",
                    created_at=created_at,
                ),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _update_assistant_message_with_new_session(
    *,
    session_factory: Callable[[], Any],
    message_id: str,
    content: str,
    reasoning: str,
    status: str,
) -> None:
    async with session_factory() as session:
        try:
            updated_message = await update_message(
                session=session,
                message_id=message_id,
                content=content,
                reasoning=reasoning,
                status=status,
            )
            if updated_message is None:
                raise RuntimeError(f"Assistant message not found: {message_id}")
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _persist_tool_call_with_new_session(
    *,
    session_factory: Callable[[], Any],
    invocation: dict[str, Any],
    now_factory: Callable[[], datetime],
    timeline_state: TimelineState,
) -> None:
    async with session_factory() as session:
        try:
            persisted = await create_tool_invocation(
                session,
                ToolInvocation(
                    id=invocation["id"],
                    message_id=invocation["messageId"],
                    tool_name=invocation["toolName"],
                    args=invocation.get("args") or {},
                    result=None,
                    error=None,
                    latency_ms=None,
                    status="running",
                    created_at=now_factory(),
                ),
            )
            await create_message_part(
                session,
                MessagePart(
                    id=str(uuid4()),
                    message_id=persisted.message_id,
                    type="tool",
                    order_index=timeline_state.next_order_index,
                    text="",
                    tool_invocation_id=persisted.id,
                    created_at=now_factory(),
                ),
            )
            timeline_state.next_order_index += 1
            timeline_state.last_part_id = None
            timeline_state.last_part_type = "tool"
            timeline_state.last_part_text = ""
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _persist_tool_result_with_new_session(
    *,
    session_factory: Callable[[], Any],
    invocation: dict[str, Any],
) -> None:
    async with session_factory() as session:
        try:
            updated_invocation = await update_tool_invocation(
                session=session,
                invocation_id=invocation["id"],
                result=invocation.get("result"),
                error=invocation.get("error"),
                latency_ms=invocation.get("latencyMs"),
                status=invocation["status"],
            )
            if updated_invocation is None:
                raise RuntimeError(f"Tool invocation not found: {invocation['id']}")
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _mark_unfinished_tool_invocations_error_with_new_session(
    *,
    session_factory: Callable[[], Any],
    invocation_ids: set[str],
    error: str,
) -> None:
    if not invocation_ids:
        return

    async with session_factory() as session:
        try:
            for invocation_id in invocation_ids:
                await update_tool_invocation(
                    session=session,
                    invocation_id=invocation_id,
                    result=None,
                    error=error,
                    latency_ms=None,
                    status="error",
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _persist_reasoning_part_with_new_session(
    *,
    session_factory: Callable[[], Any],
    message_id: str | None,
    text: str,
    now_factory: Callable[[], datetime],
    timeline_state: TimelineState,
) -> None:
    if message_id is None or text == "":
        return

    async with session_factory() as session:
        try:
            if (
                timeline_state.last_part_type == "reasoning"
                and timeline_state.last_part_id
            ):
                timeline_state.last_part_text += text
                await update_message_part_text(
                    session=session,
                    part_id=timeline_state.last_part_id,
                    text=timeline_state.last_part_text,
                )
            else:
                part = await create_message_part(
                    session,
                    MessagePart(
                        id=str(uuid4()),
                        message_id=message_id,
                        type="reasoning",
                        order_index=timeline_state.next_order_index,
                        text=text,
                        tool_invocation_id=None,
                        created_at=now_factory(),
                    ),
                )
                timeline_state.next_order_index += 1
                timeline_state.last_part_id = part.id
                timeline_state.last_part_type = "reasoning"
                timeline_state.last_part_text = text
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _build_agent_messages(
    history_messages: list[Message],
    current_message: str,
) -> list[dict[str, str]]:
    messages = [
        {"role": message.role, "content": message.content}
        for message in history_messages
        if message.status == "done" and message.role in {"user", "assistant"}
    ]
    messages.append({"role": "user", "content": current_message})
    return messages


async def _update_conversation_title_for_request(
    *,
    request: ChatStreamRequest,
    session_factory: Callable[[], Any],
    title_generator: Callable[[str], str],
) -> str | None:
    if not request.generate_title:
        return None

    title = await asyncio.to_thread(title_generator, request.message)
    async with session_factory() as session:
        try:
            await update_conversation_title(
                session=session,
                conversation_id=request.conversation_id,
                title=title,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    return title


async def _get_title_task_result(
    title_task: asyncio.Task[str | None],
) -> str | None:
    try:
        return await title_task
    except Exception:
        return None


def _tool_call_events(
    chunk: AIMessageChunk,
    assistant_id: str,
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, float],
]:
    events: list[dict[str, Any]] = []
    invocations: dict[str, dict[str, Any]] = {}
    started_at: dict[str, float] = {}

    for call in chunk.tool_calls:
        tool_call_id = call.get("id")
        tool_name = call.get("name")
        if not tool_call_id or not tool_name:
            continue

        invocation = {
            "id": tool_call_id,
            "messageId": assistant_id,
            "toolName": tool_name,
            "args": call.get("args") or {},
            "status": "running",
        }
        invocations[tool_call_id] = invocation
        started_at[tool_call_id] = monotonic()
        events.append(
            {
                "type": "tool_call",
                "messageId": assistant_id,
                "invocation": invocation,
            }
        )

    return events, invocations, started_at


def _stream_message(stream_item: object) -> object:
    if isinstance(stream_item, tuple):
        return stream_item[0]
    return stream_item


def _reasoning_text(message: AIMessageChunk) -> str:
    for source in (message.additional_kwargs, message.response_metadata):
        for key in ("reasoning_content", "reasoning-content", "reasoning"):
            value = source.get(key)
            text = _content_text(value)
            if text:
                return text
    return ""


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts)


def _normalize_title(value: str, fallback: str) -> str:
    first_line = next(
        (line.strip() for line in value.splitlines() if line.strip()),
        fallback,
    )
    title = " ".join(first_line.split()).lstrip("#").strip()
    for prefix in ("Title:", "Title：", "标题:", "标题："):
        if title.startswith(prefix):
            title = title[len(prefix) :].strip()
            break
    title = title.strip("\"'“”‘’")
    return (title or fallback)[:TITLE_MAX_LENGTH]


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_frontend_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
