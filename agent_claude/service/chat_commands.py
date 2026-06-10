from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from repository.message import update_message
from schema.chat import DeltaEvent, DoneEvent, ToolCallEvent, ToolResultEvent
from service import stream_persistence
from service.deepseek_balance import (
    fetch_deepseek_balance,
    format_balance_summary,
    safe_balance_error_message,
)


GET_BALANCE_COMMAND = "/get-balance"
GET_BALANCE_TOOL_NAME = "get_deepseek_balance"

BalanceFetcher = Callable[[], Awaitable[dict[str, Any]]]


def is_get_balance_command(message: str) -> bool:
    return message.strip() == GET_BALANCE_COMMAND


async def stream_get_balance_command(
    *,
    message_id: str,
    fetch_balance: BalanceFetcher = fetch_deepseek_balance,
    async_session_factory: Any,
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> AsyncIterator[ToolCallEvent | ToolResultEvent | DeltaEvent | DoneEvent]:
    tool_id = f"{message_id}:get_deepseek_balance"
    started_at = now_factory()
    invocation, next_order_index = await stream_persistence.persist_tool_call(
        message_id=message_id,
        tool_id=tool_id,
        tool_name=GET_BALANCE_TOOL_NAME,
        args={},
        order_index=0,
        async_session_factory=async_session_factory,
    )
    yield ToolCallEvent(
        type="tool_call",
        message_id=message_id,
        invocation=stream_persistence.project_tool_invocation(invocation),
    )

    result: dict[str, Any] | None
    error: str | None
    try:
        result = await fetch_balance()
        error = None
        content = format_balance_summary(result)
    except Exception as exc:
        result = None
        error = safe_balance_error_message(exc)
        content = f"DeepSeek 余额查询失败：{error}"

    invocation = await stream_persistence.persist_tool_result(
        message_id=message_id,
        tool_id=tool_id,
        result=result,
        error=error,
        latency_ms=_latency_ms(started_at, now_factory()),
        order_index=next_order_index,
        async_session_factory=async_session_factory,
    )
    yield ToolResultEvent(
        type="tool_result",
        message_id=message_id,
        invocation=stream_persistence.project_tool_invocation(invocation),
    )

    async with async_session_factory() as session:
        await update_message(
            session,
            message_id=message_id,
            content=content,
            reasoning="",
            status="done",
        )
        await session.commit()

    yield DeltaEvent(type="delta", message_id=message_id, text=content)
    yield DoneEvent(type="done", message_id=message_id)


def _latency_ms(started_at: datetime, finished_at: datetime) -> int:
    return max(0, int((finished_at - started_at).total_seconds() * 1000))
