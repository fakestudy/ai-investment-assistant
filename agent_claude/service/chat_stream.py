import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from claude_agent_sdk.types import CanUseTool

from core.database import AsyncSessionLocal
from model.message import Message
from repository.agent_session import (
    get_agent_session_by_conversation_id,
    upsert_agent_session,
)
from repository.conversation import get_conversation_by_id, update_conversation_title
from repository.message import create_message, update_message
from schema.chat import (
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    MessageCreatedEvent,
    ReasoningEvent,
    TitleEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from service import stream_persistence
from service.runtime import generate_title as generate_title_with_agent
from service.runtime import stream_query
from service.sdk_events import (
    calculate_latency_ms,
    extract_result_error_message,
    extract_session_id,
    extract_text_deltas,
    extract_thinking_deltas,
    extract_tool_call,
    extract_tool_result,
    is_content_block_delta_event,
    pop_ready_tool_call,
    record_tool_call,
    record_tool_json_delta,
)
from service.session_store import PostgresSessionStore
from service.sse import to_sse


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatStreamDependencies:
    async_session_factory: Any = AsyncSessionLocal
    get_conversation_by_id: Any = get_conversation_by_id
    get_agent_session_by_conversation_id: Any = get_agent_session_by_conversation_id
    upsert_agent_session: Any = upsert_agent_session
    stream_query: Any = stream_query
    update_conversation_title: Any = update_conversation_title
    generate_title: Any = generate_title_with_agent


class _StreamState:
    def __init__(self, assistant_message_id: str) -> None:
        self.assistant_message_id = assistant_message_id
        self.content = ""
        self.reasoning = ""
        self.current_reasoning_part_text = ""
        self.has_partial_text = False
        self.has_partial_thinking = False
        self.next_order_index = 0
        self.reasoning_part_id: str | None = None
        self.tool_invocation_started_at: dict[str, datetime] = {}
        self.projected_tool_ids: set[str] = set()
        self.pending_tools: dict[str, dict[str, Any]] = {}
        self.tool_block_keys_by_index: dict[int, str] = {}


async def stream_chat(
    *,
    conversation_id: str,
    message: str,
    generate_title: bool | None = None,
    parent_message_id: str | None = None,
    regenerate_from_message_id: str | None = None,
    precreated_assistant_message_id: str | None = None,
    create_user_message: bool = True,
    emit_message_created: bool = True,
    executor_prompt: str | None = None,
    resume_sdk_session: bool = True,
    can_use_tool: CanUseTool | None = None,
    dependencies: ChatStreamDependencies | None = None,
) -> AsyncIterator[str]:
    deps = dependencies or ChatStreamDependencies()
    assistant_message_id = precreated_assistant_message_id or str(uuid4())
    now = datetime.now(UTC)
    _ = (parent_message_id, regenerate_from_message_id)

    async with deps.async_session_factory() as session:
        conversation = await _get_conversation_or_none(
            session,
            conversation_id,
            deps.get_conversation_by_id,
        )
        if conversation is None:
            yield to_sse(
                ErrorEvent(
                    type="error",
                    message_id=None,
                    message="Conversation not found",
                )
            )
            return

        if create_user_message:
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

        assistant_message = None
        if precreated_assistant_message_id is None:
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
        existing_agent_session = None
        if resume_sdk_session:
            existing_agent_session = await deps.get_agent_session_by_conversation_id(
                session,
                conversation_id,
            )
        await session.commit()

    if emit_message_created and assistant_message is not None:
        yield to_sse(
            MessageCreatedEvent(
                type="message_created",
                message=stream_persistence.project_stream_message(assistant_message),
            )
        )

    stream_state = _StreamState(assistant_message_id)
    sdk_session_id = getattr(existing_agent_session, "sdk_session_id", None)
    session_store = PostgresSessionStore(deps.async_session_factory)

    title_task: asyncio.Task[str | None] | None = None
    main_task: asyncio.Task[Any] | None = None
    try:
        stream_query_kwargs = {
            "prompt": executor_prompt if executor_prompt is not None else message,
            "session_store": session_store,
            "resume": sdk_session_id if resume_sdk_session else None,
        }
        if can_use_tool is not None:
            stream_query_kwargs["can_use_tool"] = can_use_tool

        if generate_title:
            title_task = asyncio.create_task(
                _generate_and_persist_title(
                    conversation_id=conversation_id,
                    message=message,
                    generate_title_fn=deps.generate_title,
                    async_session_factory=deps.async_session_factory,
                    update_conversation_title_fn=deps.update_conversation_title,
                )
            )

        sdk_messages = deps.stream_query(**stream_query_kwargs).__aiter__()
        main_task = asyncio.create_task(anext(sdk_messages))

        while main_task is not None:
            pending_tasks: set[asyncio.Task[Any]] = {main_task}
            if title_task is not None:
                pending_tasks.add(title_task)

            done_tasks, _ = await asyncio.wait(
                pending_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if title_task is not None and title_task in done_tasks:
                title = title_task.result()
                title_task = None
                if title:
                    yield to_sse(
                        TitleEvent(
                            type="title",
                            conversation_id=conversation_id,
                            title=title,
                        )
                    )

            if main_task not in done_tasks:
                continue

            try:
                sdk_message = main_task.result()
            except StopAsyncIteration:
                main_task = None
                break
            main_task = asyncio.create_task(anext(sdk_messages))

            sdk_session_id = extract_session_id(sdk_message) or sdk_session_id
            sdk_result_error = extract_result_error_message(sdk_message)
            if sdk_result_error is not None:
                raise RuntimeError(sdk_result_error)

            is_partial_delta = is_content_block_delta_event(sdk_message)

            thinking_deltas = (
                extract_thinking_deltas(sdk_message)
                if is_partial_delta or not stream_state.has_partial_thinking
                else []
            )
            if is_partial_delta and thinking_deltas:
                stream_state.has_partial_thinking = True
            for text in thinking_deltas:
                stream_state.reasoning += text
                stream_state.current_reasoning_part_text += text
                (
                    stream_state.reasoning_part_id,
                    stream_state.next_order_index,
                ) = await stream_persistence.persist_reasoning_delta(
                    message_id=assistant_message_id,
                    part_id=stream_state.reasoning_part_id,
                    text=stream_state.current_reasoning_part_text,
                    order_index=stream_state.next_order_index,
                    async_session_factory=deps.async_session_factory,
                )
                yield to_sse(
                    ReasoningEvent(
                        type="reasoning",
                        message_id=assistant_message_id,
                        text=text,
                    )
                )

            record_tool_json_delta(
                sdk_message,
                pending_tools=stream_state.pending_tools,
                tool_block_keys_by_index=stream_state.tool_block_keys_by_index,
            )

            tool_call = extract_tool_call(sdk_message)
            if tool_call is not None:
                record_tool_call(
                    sdk_message,
                    tool_call=tool_call,
                    pending_tools=stream_state.pending_tools,
                    tool_block_keys_by_index=stream_state.tool_block_keys_by_index,
                )

            tool_result = extract_tool_result(sdk_message)
            ready_tool_call = pop_ready_tool_call(
                sdk_message,
                tool_call=tool_call,
                pending_tools=stream_state.pending_tools,
                projected_tool_ids=stream_state.projected_tool_ids,
                tool_block_keys_by_index=stream_state.tool_block_keys_by_index,
                tool_result=tool_result,
            )
            if ready_tool_call is not None:
                (
                    invocation,
                    stream_state.next_order_index,
                ) = await stream_persistence.persist_tool_call(
                    message_id=assistant_message_id,
                    tool_id=ready_tool_call["id"],
                    tool_name=ready_tool_call["name"],
                    args=ready_tool_call["args"],
                    order_index=stream_state.next_order_index,
                    async_session_factory=deps.async_session_factory,
                )
                stream_state.reasoning_part_id = None
                stream_state.current_reasoning_part_text = ""
                stream_state.projected_tool_ids.add(invocation.id)
                stream_state.tool_invocation_started_at[invocation.id] = datetime.now(UTC)
                yield to_sse(
                    ToolCallEvent(
                        type="tool_call",
                        message_id=assistant_message_id,
                        invocation=stream_persistence.project_tool_invocation(invocation),
                    )
                )

            if tool_result is not None:
                started_at = stream_state.tool_invocation_started_at.get(tool_result["id"])
                latency_ms = calculate_latency_ms(started_at, datetime.now(UTC))
                invocation = await stream_persistence.persist_tool_result(
                    message_id=assistant_message_id,
                    tool_id=tool_result["id"],
                    result=tool_result["result"],
                    error=tool_result["error"],
                    latency_ms=latency_ms,
                    order_index=stream_state.next_order_index,
                    async_session_factory=deps.async_session_factory,
                )
                if invocation.id not in stream_state.projected_tool_ids:
                    stream_state.projected_tool_ids.add(invocation.id)
                    stream_state.next_order_index += 1
                yield to_sse(
                    ToolResultEvent(
                        type="tool_result",
                        message_id=assistant_message_id,
                        invocation=stream_persistence.project_tool_invocation(invocation),
                    )
                )
                stream_state.reasoning_part_id = None
                stream_state.current_reasoning_part_text = ""

            text_deltas = (
                extract_text_deltas(sdk_message)
                if is_partial_delta or not stream_state.has_partial_text
                else []
            )
            if is_partial_delta and text_deltas:
                stream_state.has_partial_text = True
            for text in text_deltas:
                stream_state.content += text
                yield to_sse(
                    DeltaEvent(
                        type="delta",
                        message_id=assistant_message_id,
                        text=text,
                    )
                )

        async with deps.async_session_factory() as session:
            await update_message(
                session,
                message_id=assistant_message_id,
                content=stream_state.content,
                reasoning=stream_state.reasoning,
                status="done",
            )
            if sdk_session_id:
                await deps.upsert_agent_session(
                    session,
                    conversation_id=conversation_id,
                    sdk_session_id=sdk_session_id,
                )
            await session.commit()

        if title_task is not None:
            title = await title_task
            title_task = None
            if title:
                yield to_sse(
                    TitleEvent(
                        type="title",
                        conversation_id=conversation_id,
                        title=title,
                    )
                )

        yield to_sse(
            DoneEvent(
                type="done",
                message_id=assistant_message_id,
            )
        )
    except Exception as exc:
        if main_task is not None and not main_task.done():
            main_task.cancel()
            with suppress(asyncio.CancelledError):
                await main_task
        if title_task is not None and not title_task.done():
            title_task.cancel()
            with suppress(asyncio.CancelledError):
                await title_task

        async with deps.async_session_factory() as session:
            await update_message(
                session,
                message_id=assistant_message_id,
                content=stream_state.content,
                reasoning=stream_state.reasoning,
                status="error",
            )
            if sdk_session_id:
                await deps.upsert_agent_session(
                    session,
                    conversation_id=conversation_id,
                    sdk_session_id=sdk_session_id,
                )
            await session.commit()

        yield to_sse(
            ErrorEvent(
                type="error",
                message_id=assistant_message_id,
                message=str(exc) or exc.__class__.__name__,
            )
        )


async def _get_conversation_or_none(
    session: Any,
    conversation_id: str,
    get_conversation_by_id_fn: Any,
) -> Any | None:
    return await get_conversation_by_id_fn(session, conversation_id)


async def _generate_and_persist_title(
    *,
    conversation_id: str,
    message: str,
    generate_title_fn: Any,
    async_session_factory: Any,
    update_conversation_title_fn: Any,
) -> str | None:
    try:
        title = _normalize_generated_title(
            await generate_title_fn(message),
            fallback_prompt=message,
        )
    except Exception:
        logger.exception("Failed to generate conversation title")
        return None

    if title is None:
        return None

    title_updated = await stream_persistence.persist_title(
        conversation_id=conversation_id,
        title=title,
        async_session_factory=async_session_factory,
        update_conversation_title_fn=update_conversation_title_fn,
    )
    return title if title_updated else None


def _normalize_generated_title(
    raw_title: str | None,
    *,
    fallback_prompt: str,
) -> str | None:
    if raw_title is None or not raw_title.strip():
        return None
    source = " ".join(fallback_prompt.strip().split())
    title = _generate_title(raw_title)
    if len(source) > 20 and title == source[:60]:
        return None
    return title


def _generate_title(prompt: str) -> str:
    title = " ".join(prompt.strip().split())
    return title[:60] if title else "New chat"
