import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from core.database import AsyncSessionLocal
from model.message_part import MessagePart
from model.message import Message
from model.tool_invocation import ToolInvocation
from repository.agent_session import (
    get_agent_session_by_conversation_id,
    upsert_agent_session,
)
from repository.conversation import update_conversation_title
from repository.message import create_message, update_message
from repository.message_part import create_message_part, update_message_part_text
from repository.tool_invocation import create_tool_invocation, update_tool_invocation
from schema.chat import (
    ChatMessage,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    MessageCreatedEvent,
    ReasoningEvent,
    TitleEvent,
    ToolCallEvent,
    ToolInvocation as ToolInvocationSchema,
    ToolResultEvent,
)
from service.runtime import stream_query
from service.session_store import PostgresSessionStore


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

    stream_state = _StreamState(assistant_message_id)
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
                ) = await _persist_reasoning_delta(
                    message_id=assistant_message_id,
                    part_id=stream_state.reasoning_part_id,
                    text=stream_state.current_reasoning_part_text,
                    order_index=stream_state.next_order_index,
                )
                yield _to_sse(
                    ReasoningEvent(
                        type="reasoning",
                        message_id=assistant_message_id,
                        text=text,
                    )
                )

            _record_tool_json_delta(
                sdk_message,
                pending_tools=stream_state.pending_tools,
                tool_block_keys_by_index=stream_state.tool_block_keys_by_index,
            )

            tool_call = _extract_tool_call(sdk_message)
            if tool_call is not None:
                _record_tool_call(
                    sdk_message,
                    tool_call=tool_call,
                    pending_tools=stream_state.pending_tools,
                    tool_block_keys_by_index=stream_state.tool_block_keys_by_index,
                )

            ready_tool_call = _pop_ready_tool_call(
                sdk_message,
                tool_call=tool_call,
                pending_tools=stream_state.pending_tools,
                projected_tool_ids=stream_state.projected_tool_ids,
                tool_block_keys_by_index=stream_state.tool_block_keys_by_index,
            )
            if ready_tool_call is not None:
                invocation, stream_state.next_order_index = await _persist_tool_call(
                    message_id=assistant_message_id,
                    tool_id=ready_tool_call["id"],
                    tool_name=ready_tool_call["name"],
                    args=ready_tool_call["args"],
                    order_index=stream_state.next_order_index,
                )
                stream_state.reasoning_part_id = None
                stream_state.current_reasoning_part_text = ""
                stream_state.projected_tool_ids.add(invocation.id)
                stream_state.tool_invocation_started_at[invocation.id] = datetime.now(UTC)
                yield _to_sse(
                    ToolCallEvent(
                        type="tool_call",
                        message_id=assistant_message_id,
                        invocation=_project_tool_invocation(invocation),
                    )
                )

            tool_result = _extract_tool_result(sdk_message)
            if tool_result is not None:
                started_at = stream_state.tool_invocation_started_at.get(tool_result["id"])
                latency_ms = _calculate_latency_ms(started_at, datetime.now(UTC))
                invocation = await _persist_tool_result(
                    message_id=assistant_message_id,
                    tool_id=tool_result["id"],
                    result=tool_result["result"],
                    error=tool_result["error"],
                    latency_ms=latency_ms,
                    order_index=stream_state.next_order_index,
                )
                if invocation.id not in stream_state.projected_tool_ids:
                    stream_state.projected_tool_ids.add(invocation.id)
                    stream_state.next_order_index += 1
                yield _to_sse(
                    ToolResultEvent(
                        type="tool_result",
                        message_id=assistant_message_id,
                        invocation=_project_tool_invocation(invocation),
                    )
                )
                stream_state.reasoning_part_id = None
                stream_state.current_reasoning_part_text = ""

            text_deltas = (
                _extract_text_deltas(sdk_message)
                if is_partial_delta or not stream_state.has_partial_text
                else []
            )
            if is_partial_delta and text_deltas:
                stream_state.has_partial_text = True
            for text in text_deltas:
                stream_state.content += text
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
                content=stream_state.content,
                reasoning=stream_state.reasoning,
                status="done",
            )
            if sdk_session_id:
                await upsert_agent_session(
                    session,
                    conversation_id=conversation_id,
                    sdk_session_id=sdk_session_id,
                )
            await session.commit()

        if generate_title:
            title = _generate_title(message)
            title_updated = await _persist_title(
                conversation_id=conversation_id,
                title=title,
            )
            if title_updated:
                yield _to_sse(
                    TitleEvent(
                        type="title",
                        conversation_id=conversation_id,
                        title=title,
                    )
                )

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
                content=stream_state.content,
                reasoning=stream_state.reasoning,
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


async def _persist_reasoning_delta(
    *,
    message_id: str,
    part_id: str | None,
    text: str,
    order_index: int,
) -> tuple[str, int]:
    async with AsyncSessionLocal() as session:
        if part_id is None:
            part_id = str(uuid4())
            await create_message_part(
                session,
                MessagePart(
                    id=part_id,
                    message_id=message_id,
                    type="reasoning",
                    order_index=order_index,
                    text=text,
                    tool_invocation_id=None,
                    created_at=datetime.now(UTC),
                ),
            )
            next_order_index = order_index + 1
        else:
            await update_message_part_text(session, part_id=part_id, text=text)
            next_order_index = order_index
        await session.commit()
    return part_id, next_order_index


async def _persist_tool_call(
    *,
    message_id: str,
    tool_id: str,
    tool_name: str,
    args: dict[str, Any],
    order_index: int,
) -> tuple[ToolInvocation, int]:
    async with AsyncSessionLocal() as session:
        invocation = await create_tool_invocation(
            session,
            ToolInvocation(
                id=tool_id,
                message_id=message_id,
                tool_name=tool_name,
                args=args,
                result=None,
                error=None,
                latency_ms=None,
                status="running",
                created_at=datetime.now(UTC),
            ),
        )
        await create_message_part(
            session,
            MessagePart(
                id=str(uuid4()),
                message_id=message_id,
                type="tool",
                order_index=order_index,
                text="",
                tool_invocation_id=tool_id,
                created_at=datetime.now(UTC),
            ),
        )
        await session.commit()
    return invocation, order_index + 1


async def _persist_tool_result(
    *,
    message_id: str,
    tool_id: str,
    result: Any | None,
    error: str | None,
    latency_ms: int | None,
    order_index: int,
) -> ToolInvocation:
    async with AsyncSessionLocal() as session:
        try:
            invocation = await update_tool_invocation(
                session,
                invocation_id=tool_id,
                result=result,
                error=error,
                latency_ms=latency_ms,
                status="error" if error else "completed",
            )
        except LookupError:
            invocation = await create_tool_invocation(
                session,
                ToolInvocation(
                    id=tool_id,
                    message_id=message_id,
                    tool_name="unknown",
                    args={},
                    result=result,
                    error=error,
                    latency_ms=latency_ms,
                    status="error" if error else "completed",
                    created_at=datetime.now(UTC),
                ),
            )
            await create_message_part(
                session,
                MessagePart(
                    id=str(uuid4()),
                    message_id=message_id,
                    type="tool",
                    order_index=order_index,
                    text="",
                    tool_invocation_id=tool_id,
                    created_at=datetime.now(UTC),
                ),
            )
        await session.commit()
    return invocation


async def _persist_title(*, conversation_id: str, title: str) -> bool:
    async with AsyncSessionLocal() as session:
        conversation = await update_conversation_title(
            session,
            conversation_id=conversation_id,
            title=title,
        )
        if conversation is None:
            return False
        await session.commit()
    return True


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


def _project_tool_invocation(invocation: ToolInvocation) -> ToolInvocationSchema:
    return ToolInvocationSchema(
        id=invocation.id,
        message_id=invocation.message_id,
        tool_name=invocation.tool_name,
        args=invocation.args,
        result=invocation.result,
        error=invocation.error,
        latency_ms=invocation.latency_ms,
        status=invocation.status,
        created_at=_format_datetime(invocation.created_at),
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


def _record_tool_call(
    sdk_message: Any,
    *,
    tool_call: dict[str, Any],
    pending_tools: dict[str, dict[str, Any]],
    tool_block_keys_by_index: dict[int, str],
) -> None:
    tool_key = _tool_state_key(tool_call["id"])
    pending_tool = pending_tools.setdefault(
        tool_key,
        {
            "id": tool_call["id"],
            "name": tool_call["name"],
            "args": None,
            "json_buffer": "",
        },
    )
    pending_tool["id"] = tool_call["id"]
    pending_tool["name"] = tool_call["name"]
    if tool_call["args"]:
        pending_tool["args"] = tool_call["args"]

    block_index = _extract_content_block_index(sdk_message)
    if block_index is not None:
        tool_block_keys_by_index[block_index] = tool_key


def _record_tool_json_delta(
    sdk_message: Any,
    *,
    pending_tools: dict[str, dict[str, Any]],
    tool_block_keys_by_index: dict[int, str],
) -> None:
    delta = _extract_input_json_delta(sdk_message)
    if delta is None:
        return

    block_index = _extract_content_block_index(sdk_message)
    if block_index is None:
        return

    tool_key = tool_block_keys_by_index.get(block_index)
    if tool_key is None:
        tool_key = _tool_state_key(str(uuid4()))
        tool_block_keys_by_index[block_index] = tool_key

    pending_tool = pending_tools.setdefault(
        tool_key,
        {
            "id": tool_key.removeprefix("id:"),
            "name": "tool",
            "args": None,
            "json_buffer": "",
        },
    )
    pending_tool["json_buffer"] = f"{pending_tool.get('json_buffer', '')}{delta}"
    parsed_args = _try_parse_object(pending_tool["json_buffer"])
    if parsed_args is not None:
        pending_tool["args"] = parsed_args


def _pop_ready_tool_call(
    sdk_message: Any,
    *,
    tool_call: dict[str, Any] | None,
    pending_tools: dict[str, dict[str, Any]],
    projected_tool_ids: set[str],
    tool_block_keys_by_index: dict[int, str],
) -> dict[str, Any] | None:
    tool_key: str | None = None
    if tool_call is not None:
        tool_key = _tool_state_key(tool_call["id"])
    else:
        block_index = _extract_content_block_index(sdk_message)
        if block_index is not None:
            tool_key = tool_block_keys_by_index.get(block_index)

    if tool_key is None:
        return None

    pending_tool = pending_tools.get(tool_key)
    if pending_tool is None:
        return None

    tool_id = pending_tool["id"]
    if tool_id in projected_tool_ids:
        pending_tools.pop(tool_key, None)
        return None

    args = pending_tool.get("args")
    json_buffer = pending_tool.get("json_buffer")
    if args is None and json_buffer:
        args = _try_parse_object(json_buffer)
        if args is not None:
            pending_tool["args"] = args
    if args is None:
        return None

    pending_tools.pop(tool_key, None)
    return {
        "id": tool_id,
        "name": pending_tool["name"],
        "args": args,
    }


def _tool_state_key(tool_id: str) -> str:
    return f"id:{tool_id}"


def _extract_content_block_index(sdk_message: Any) -> int | None:
    event = getattr(sdk_message, "event", None)
    index = _read_value(event, "index")
    return index if isinstance(index, int) else None


def _extract_input_json_delta(sdk_message: Any) -> str | None:
    event = getattr(sdk_message, "event", None)
    if _read_value(event, "type") != "content_block_delta":
        return None

    delta = _read_value(event, "delta")
    if _read_value(delta, "type") != "input_json_delta":
        return None

    partial_json = _read_value(delta, "partial_json")
    return partial_json if isinstance(partial_json, str) else None


def _try_parse_object(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _extract_tool_call(sdk_message: Any) -> dict[str, Any] | None:
    block = _extract_content_block(sdk_message)
    if not _is_tool_use_block(block):
        return None

    tool_id = _read_value(block, "id") or _read_value(block, "tool_use_id")
    tool_name = _read_value(block, "name") or _read_value(block, "tool_name")
    args = _read_value(block, "input")
    if args is None:
        args = _read_value(block, "args") or {}

    if not isinstance(tool_id, str) or not tool_id:
        tool_id = str(uuid4())
    if not isinstance(tool_name, str) or not tool_name:
        tool_name = "tool"
    if not isinstance(args, dict):
        args = {"value": args}

    return {"id": tool_id, "name": tool_name, "args": args}


def _extract_tool_result(sdk_message: Any) -> dict[str, Any] | None:
    block = _extract_content_block(sdk_message)
    if not _is_tool_result_block(block):
        return None

    tool_id = _read_value(block, "tool_use_id") or _read_value(block, "id")
    if not isinstance(tool_id, str) or not tool_id:
        return None

    error = _extract_tool_result_error(block)
    result = None if error else _extract_tool_result_payload(block)
    return {"id": tool_id, "result": result, "error": error}


def _extract_content_block(sdk_message: Any) -> Any | None:
    event = getattr(sdk_message, "event", None)
    if event is not None:
        block = _read_value(event, "content_block")
        if block is not None:
            return block
        event_type = _read_value(event, "type")
        return event if event_type in {"tool_use", "tool_result"} else None

    content = getattr(sdk_message, "content", None)
    if isinstance(content, list):
        for block in content:
            if _is_tool_block(block):
                return block

    return sdk_message if _is_tool_block(sdk_message) else None


def _is_tool_block(block: Any) -> bool:
    return _is_tool_use_block(block) or _is_tool_result_block(block)


def _is_tool_use_block(block: Any) -> bool:
    if _read_value(block, "type") == "tool_use":
        return True
    return _has_value(block, "id") and _has_value(block, "name") and _has_value(block, "input")


def _is_tool_result_block(block: Any) -> bool:
    if _read_value(block, "type") == "tool_result":
        return True
    return _has_value(block, "tool_use_id") and (
        _has_value(block, "content") or _has_value(block, "is_error")
    )


def _extract_tool_result_payload(block: Any) -> Any | None:
    result = _read_value(block, "result")
    if result is not None:
        return result
    return _normalize_tool_result_content(_read_value(block, "content"))


def _normalize_tool_result_content(content: Any) -> Any | None:
    if isinstance(content, str):
        return _parse_json_string(content)

    if isinstance(content, list):
        text_values = [
            item.get("text")
            for item in content
            if (
                isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            )
        ]
        if len(text_values) == 1:
            return _parse_json_string(text_values[0])
        if text_values:
            return [_parse_json_string(text) for text in text_values]

    return content


def _parse_json_string(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _extract_tool_result_error(block: Any) -> str | None:
    error = _read_value(block, "error")
    if isinstance(error, str):
        return error or None
    if error is not None:
        return json.dumps(error, ensure_ascii=False)
    if _read_value(block, "is_error") is True:
        payload = _extract_tool_result_payload(block)
        if isinstance(payload, str) and payload:
            return payload
        if payload is not None:
            return json.dumps(payload, ensure_ascii=False)
        return "Tool execution failed"
    return None


def _read_value(source: Any, key: str) -> Any | None:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def _has_value(source: Any, key: str) -> bool:
    if isinstance(source, dict):
        return key in source
    return hasattr(source, key)


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


def _calculate_latency_ms(started_at: datetime | None, finished_at: datetime) -> int | None:
    if started_at is None:
        return None
    return max(0, int((finished_at - started_at).total_seconds() * 1000))


def _generate_title(prompt: str) -> str:
    title = " ".join(prompt.strip().split())
    return title[:60] if title else "New chat"
