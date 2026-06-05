import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk, ToolMessage
from langchain_deepseek import ChatDeepSeek

from agent_tools.deepseek import get_deepseek_balance
from agent_tools.get_weather import get_weather
from schema.chat import ChatStreamRequest


TITLE_MAX_LENGTH = 60


def get_conversation_title(prompt: str, model: Any | None = None) -> str:
    fallback = _normalize_title(prompt, "New chat")
    title_model = model or get_model()

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


def get_model() -> ChatDeepSeek:
    return ChatDeepSeek(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        reasoning_effort="max",
        extra_body={"thinking": {"type": "enabled"}},
    )


def get_agent():
    model = get_model()
    return create_agent(
        model=model,
        tools=[get_weather, get_deepseek_balance],
        system_prompt=(
            "You are a helpful assistant. "
            "Only call get_deepseek_balance when the user explicitly asks about "
            "DeepSeek balance, account balance, remaining quota, or costs. "
            "Do not query balance during ordinary conversations."
        ),
    )


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
        runtime_agent = agent or get_agent()
        stream = runtime_agent.stream(
            input={
                "messages": [{"role": "user", "content": request.message}],
            },
            stream_mode="messages",
        )

        pending_tool_chunk: AIMessageChunk | None = None
        tool_invocations: dict[str, dict[str, Any]] = {}
        tool_started_at: dict[str, float] = {}

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
                    and message.response_metadata.get("finish_reason")
                    == "tool_calls"
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
                        (
                            monotonic()
                            - tool_started_at.get(tool_call_id, monotonic())
                        )
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


        if request.generate_title:
            yield {
                "type": "title",
                "conversationId": request.conversation_id,
                "title": title_generator(request.message),
            }


        yield {"type": "done", "messageId": assistant_id}
    except Exception as exc:
        yield {
            "type": "error",
            "messageId": assistant_id,
            "message": str(exc),
        }


def iter_sse_events(request: ChatStreamRequest) -> Iterator[str]:
    for event in iter_chat_events(request):
        yield format_sse_data(event)


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
