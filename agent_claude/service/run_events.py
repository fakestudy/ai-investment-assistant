from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from core.database import AsyncSessionLocal
from model.agent_run import AgentRun
from model.agent_run_event import AgentRunEvent
from repository.agent_run import TERMINAL_RUN_STATUSES, get_run_by_id
from repository.agent_run_event import (
    append_run_event as append_run_event_row,
    list_run_events_after,
)
from schema.chat import ChatStreamEvent, ChatStreamEventAdapter
from service.sse import to_sse


EventAppender = Callable[[AgentRunEvent], Awaitable[AgentRunEvent]]
EventLoader = Callable[[str, int], Awaitable[Sequence[Any]]]
EventByIdLoader = Callable[[int], Awaitable[Any | None]]
RunLoader = Callable[[str], Awaitable[Any | None]]

_subscribers: dict[str, set[asyncio.Queue[int]]] = {}
_TERMINAL_STATUSES = set(TERMINAL_RUN_STATUSES) | {"completed", "failed"}


async def append_run_event(
    *,
    run_id: str,
    conversation_id: str,
    message_id: str | None = None,
    event: ChatStreamEvent,
    appender: EventAppender | None = None,
    notify: bool = True,
) -> int:
    row = build_run_event_row(
        run_id=run_id,
        conversation_id=conversation_id,
        message_id=message_id,
        event=event,
    )

    if appender is None:
        persisted = await _append_with_default_session(row)
    else:
        persisted = await appender(row)

    event_id = int(persisted.id)
    if notify:
        notify_run_event(run_id, event_id)
    return event_id


def build_run_event_row(
    *,
    run_id: str,
    conversation_id: str,
    message_id: str | None = None,
    event: ChatStreamEvent,
) -> AgentRunEvent:
    payload_model = ChatStreamEventAdapter.validate_python(event)
    payload_run_id = getattr(payload_model, "run_id", None)
    if payload_run_id is not None and payload_run_id != run_id:
        raise ValueError("event run_id does not match target run_id")

    payload = payload_model.model_dump(by_alias=True, exclude_none=True)
    payload["runId"] = run_id
    return AgentRunEvent(
        run_id=run_id,
        conversation_id=conversation_id,
        message_id=message_id or _infer_message_id(payload_model),
        event_type=payload_model.type,
        payload=payload,
        created_at=datetime.now(UTC),
    )


def format_persisted_event(event: Any) -> str:
    payload_model = ChatStreamEventAdapter.validate_python(event.payload)
    return to_sse(payload_model, event_id=int(event.id))


async def replay_events_after(
    run_id: str,
    after_event_id: int,
    *,
    event_loader: EventLoader | None = None,
) -> AsyncIterator[str]:
    events = await _load_events_after(run_id, after_event_id, event_loader=event_loader)
    for event in _events_after(events, after_event_id):
        yield format_persisted_event(event)


async def subscribe_to_live_events(
    run_id: str,
    *,
    after_event_id: int = 0,
    event_by_id_loader: EventByIdLoader | None = None,
) -> AsyncIterator[str]:
    cursor = after_event_id
    async with _subscription_queue(run_id) as queue:
        while True:
            event_id = await queue.get()
            if event_id <= cursor:
                continue
            event = await _load_event_by_id(
                event_id,
                event_by_id_loader=event_by_id_loader,
            )
            if event is None or getattr(event, "run_id", None) != run_id:
                continue
            cursor = int(event.id)
            yield format_persisted_event(event)


async def stream_run_events(
    run_id: str,
    after_event_id: int,
    *,
    event_loader: EventLoader | None = None,
    event_by_id_loader: EventByIdLoader | None = None,
    run_loader: RunLoader | None = None,
    poll_interval_seconds: float = 15,
) -> AsyncIterator[str]:
    cursor = after_event_id
    async with _subscription_queue(run_id) as queue:
        events = await _load_events_after(run_id, cursor, event_loader=event_loader)
        for event in _events_after(events, cursor):
            if _is_terminal_event(event) and not await _run_is_terminal_and_caught_up(
                run_id,
                int(event.id),
                run_loader=run_loader,
            ):
                break
            cursor = int(event.id)
            yield format_persisted_event(event)
            if _is_terminal_event(event):
                return

        while True:
            events = await _load_events_after(
                run_id,
                cursor,
                event_loader=event_loader,
            )
            emitted = False
            for event in _events_after(events, cursor):
                if _is_terminal_event(event) and not await _run_is_terminal_and_caught_up(
                    run_id,
                    int(event.id),
                    run_loader=run_loader,
                ):
                    break
                cursor = int(event.id)
                emitted = True
                yield format_persisted_event(event)
                if _is_terminal_event(event):
                    return

            if await _run_is_terminal_and_caught_up(
                run_id,
                cursor,
                run_loader=run_loader,
            ):
                return

            if emitted:
                continue

            await _next_notified_event_id(queue, poll_interval_seconds)


def clear_subscribers() -> None:
    _subscribers.clear()


async def load_event_by_id(event_id: int) -> AgentRunEvent | None:
    async with AsyncSessionLocal() as session:
        return await session.get(AgentRunEvent, event_id)


async def load_events_after(run_id: str, after_event_id: int) -> list[AgentRunEvent]:
    async with AsyncSessionLocal() as session:
        return await list_run_events_after(
            session,
            run_id=run_id,
            after_event_id=after_event_id,
        )


async def load_run_by_id(run_id: str) -> AgentRun | None:
    async with AsyncSessionLocal() as session:
        return await get_run_by_id(session, run_id)


async def _append_with_default_session(row: AgentRunEvent) -> AgentRunEvent:
    async with AsyncSessionLocal() as session:
        persisted = await append_run_event_row(session, event=row)
        await session.commit()
        return persisted


async def _load_events_after(
    run_id: str,
    after_event_id: int,
    *,
    event_loader: EventLoader | None,
) -> Sequence[Any]:
    if event_loader is not None:
        return await event_loader(run_id, after_event_id)
    return await load_events_after(run_id, after_event_id)


async def _load_event_by_id(
    event_id: int,
    *,
    event_by_id_loader: EventByIdLoader | None,
) -> Any | None:
    if event_by_id_loader is not None:
        return await event_by_id_loader(event_id)
    return await load_event_by_id(event_id)


async def _load_run_by_id(
    run_id: str,
    *,
    run_loader: RunLoader | None,
) -> Any | None:
    if run_loader is not None:
        return await run_loader(run_id)
    return await load_run_by_id(run_id)


async def _run_is_terminal_and_caught_up(
    run_id: str,
    cursor: int,
    *,
    run_loader: RunLoader | None,
) -> bool:
    run = await _load_run_by_id(run_id, run_loader=run_loader)
    if run is None:
        raise LookupError(f"AgentRun not found: {run_id}")

    status = getattr(run, "status", None)
    last_event_id = getattr(run, "last_event_id", None)
    return status in _TERMINAL_STATUSES and (
        last_event_id is None or int(last_event_id) <= cursor
    )


def _events_after(events: Sequence[Any], after_event_id: int) -> list[Any]:
    return sorted(
        (
            event
            for event in events
            if int(event.id) > after_event_id
        ),
        key=lambda event: int(event.id),
    )


def _infer_message_id(event: Any) -> str | None:
    message_id = getattr(event, "message_id", None)
    if message_id is not None:
        return message_id

    message = getattr(event, "message", None)
    if message is not None:
        return getattr(message, "id", None)
    return None


def _is_terminal_event(event: Any) -> bool:
    event_type = getattr(event, "event_type", None)
    if event_type is None:
        payload = getattr(event, "payload", {}) or {}
        event_type = payload.get("type")
    return event_type in {"done", "error"}


def _notify_subscribers(run_id: str, event_id: int) -> None:
    for queue in tuple(_subscribers.get(run_id, ())):
        queue.put_nowait(event_id)


def notify_run_event(run_id: str, event_id: int) -> None:
    _notify_subscribers(run_id, event_id)


@asynccontextmanager
async def _subscription_queue(run_id: str) -> AsyncIterator[asyncio.Queue[int]]:
    queue: asyncio.Queue[int] = asyncio.Queue()
    _subscribers.setdefault(run_id, set()).add(queue)
    try:
        yield queue
    finally:
        queues = _subscribers.get(run_id)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            _subscribers.pop(run_id, None)


async def _next_notified_event_id(
    queue: asyncio.Queue[int],
    timeout_seconds: float,
) -> int | None:
    try:
        return await asyncio.wait_for(queue.get(), timeout=timeout_seconds)
    except TimeoutError:
        return None
