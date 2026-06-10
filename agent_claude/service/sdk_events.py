import json
from datetime import datetime
from typing import Any
from uuid import uuid4


def extract_session_id(sdk_message: Any) -> str | None:
    session_id = getattr(sdk_message, "session_id", None)
    if isinstance(session_id, str) and session_id:
        return session_id
    return None


def is_content_block_delta_event(sdk_message: Any) -> bool:
    event = getattr(sdk_message, "event", None)
    return isinstance(event, dict) and event.get("type") == "content_block_delta"


def record_tool_call(
    sdk_message: Any,
    *,
    tool_call: dict[str, Any],
    pending_tools: dict[str, dict[str, Any]],
    tool_block_keys_by_index: dict[int, str],
) -> None:
    tool_key = tool_state_key(tool_call["id"])
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
    if tool_call["args"] is not None:
        pending_tool["args"] = tool_call["args"]

    block_index = extract_content_block_index(sdk_message)
    if block_index is not None:
        tool_block_keys_by_index[block_index] = tool_key


def record_tool_json_delta(
    sdk_message: Any,
    *,
    pending_tools: dict[str, dict[str, Any]],
    tool_block_keys_by_index: dict[int, str],
) -> None:
    delta = extract_input_json_delta(sdk_message)
    if delta is None:
        return

    block_index = extract_content_block_index(sdk_message)
    if block_index is None:
        return

    tool_key = tool_block_keys_by_index.get(block_index)
    if tool_key is None:
        tool_key = tool_state_key(str(uuid4()))
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


def pop_ready_tool_call(
    sdk_message: Any,
    *,
    tool_call: dict[str, Any] | None,
    pending_tools: dict[str, dict[str, Any]],
    projected_tool_ids: set[str],
    tool_block_keys_by_index: dict[int, str],
    tool_result: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    tool_key: str | None = None
    if tool_call is not None:
        tool_key = tool_state_key(tool_call["id"])
    elif tool_result is not None:
        tool_key = tool_state_key(tool_result["id"])
    else:
        block_index = extract_content_block_index(sdk_message)
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

    json_buffer = pending_tool.get("json_buffer")
    args = _try_parse_object(json_buffer) if json_buffer else pending_tool.get("args")
    if args is not None:
        pending_tool["args"] = args
    if args is None:
        return None
    if (
        args == {}
        and tool_call is not None
        and _is_tool_call_start_event(sdk_message)
        and extract_content_block_index(sdk_message) is not None
        and not json_buffer
    ):
        return None

    pending_tools.pop(tool_key, None)
    return {
        "id": tool_id,
        "name": pending_tool["name"],
        "args": args,
    }


def extract_tool_call(sdk_message: Any) -> dict[str, Any] | None:
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


def extract_tool_result(sdk_message: Any) -> dict[str, Any] | None:
    block = _extract_content_block(sdk_message)
    if not _is_tool_result_block(block):
        return None

    tool_id = _read_value(block, "tool_use_id") or _read_value(block, "id")
    if not isinstance(tool_id, str) or not tool_id:
        return None

    error = _extract_tool_result_error(block)
    result = None if error else _extract_tool_result_payload(block)
    return {"id": tool_id, "result": result, "error": error}


def extract_text_deltas(sdk_message: Any) -> list[str]:
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


def extract_thinking_deltas(sdk_message: Any) -> list[str]:
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


def extract_result_error_message(sdk_message: Any) -> str | None:
    if not _is_error_result_message(sdk_message):
        return None

    errors = getattr(sdk_message, "errors", None)
    if isinstance(errors, list):
        for error in errors:
            message = _extract_error_text(error)
            if message:
                return message

    return "SDK stream result failed"


def extract_input_json_delta(sdk_message: Any) -> str | None:
    event = getattr(sdk_message, "event", None)
    if _read_value(event, "type") != "content_block_delta":
        return None

    delta = _read_value(event, "delta")
    if _read_value(delta, "type") != "input_json_delta":
        return None

    partial_json = _read_value(delta, "partial_json")
    return partial_json if isinstance(partial_json, str) else None


def extract_content_block_index(sdk_message: Any) -> int | None:
    event = getattr(sdk_message, "event", None)
    index = _read_value(event, "index")
    return index if isinstance(index, int) else None


def tool_state_key(tool_id: str) -> str:
    return f"id:{tool_id}"


def calculate_latency_ms(started_at: datetime | None, finished_at: datetime) -> int | None:
    if started_at is None:
        return None
    return max(0, int((finished_at - started_at).total_seconds() * 1000))


def _try_parse_object(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _read_value(source: Any, key: str) -> Any | None:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


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


def _extract_tool_result_payload(block: Any) -> Any | None:
    result = _read_value(block, "result")
    if result is not None:
        return result
    return _normalize_tool_result_content(_read_value(block, "content"))


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


def _extract_error_text(error: Any) -> str | None:
    if isinstance(error, str) and error:
        return error
    if isinstance(error, dict):
        message = error.get("message") or error.get("error")
        return message if isinstance(message, str) and message else None

    message = getattr(error, "message", None)
    return message if isinstance(message, str) and message else None


def _is_tool_call_start_event(sdk_message: Any) -> bool:
    return _read_value(getattr(sdk_message, "event", None), "type") == "content_block_start"


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


def _has_value(source: Any, key: str) -> bool:
    if isinstance(source, dict):
        return key in source
    return hasattr(source, key)


def _is_error_result_message(sdk_message: Any) -> bool:
    if getattr(sdk_message, "is_error", False) is True:
        return True

    subtype = getattr(sdk_message, "subtype", None)
    if isinstance(subtype, str) and subtype.lower() in {"error", "failed", "failure"}:
        return True

    errors = getattr(sdk_message, "errors", None)
    return bool(errors)
