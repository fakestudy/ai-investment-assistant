import asyncio
import json
from collections.abc import AsyncIterator, AsyncIterable, Awaitable, Callable
from datetime import UTC, datetime

import psycopg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import DATABASE_URL, AsyncSessionLocal
from model.agent_run_event import AgentRunEvent
from repository.agent_run_event import create_agent_run_event, list_run_events_after

STABLE_EVENT_TYPES = {"done", "error", "approval_required"}
EventLoader = Callable[[str, int], Awaitable[list[AgentRunEvent]]]
NotificationWaiter = Callable[[str, float], Awaitable[bool]]


async def append_run_event(
    session: AsyncSession,
    run_id: str,
    event_type: str,
    payload: dict[str, object],
) -> AgentRunEvent:
    persisted_payload = {**payload, "runId": run_id}
    event = await create_agent_run_event(
        session,
        AgentRunEvent(
            agent_run_id=run_id,
            event_type=event_type,
            payload=persisted_payload,
            created_at=datetime.now(UTC),
        ),
    )
    await session.execute(
        text("SELECT pg_notify('agent_run_events', :run_id)"),
        {"run_id": run_id},
    )
    return event


async def stream_run_events(
    run_id: str,
    *,
    after_event_id: int,
    wait_for_new_events: bool = False,
    event_loader: EventLoader | None = None,
    notification_waiter: NotificationWaiter | None = None,
    heartbeat_seconds: float = 15,
    max_idle_cycles: int | None = None,
) -> AsyncIterator[str]:
    cursor = after_event_id
    idle_cycles = 0
    load_events = event_loader or load_run_events_after
    wait_for_notification = notification_waiter or wait_for_run_event_notification

    while True:
        events = await load_events(run_id, cursor)
        if events:
            idle_cycles = 0
            for event in events:
                cursor = event.id
                yield format_persisted_sse(event)
                if event.event_type in STABLE_EVENT_TYPES:
                    return
            if not wait_for_new_events:
                return
            continue

        if not wait_for_new_events:
            return

        notified = await wait_for_notification(run_id, heartbeat_seconds)
        if not notified:
            idle_cycles += 1
            yield ": heartbeat\n\n"
            if max_idle_cycles is not None and idle_cycles >= max_idle_cycles:
                return


async def load_run_events_after(
    run_id: str,
    after_event_id: int,
) -> list[AgentRunEvent]:
    async with AsyncSessionLocal() as session:
        return await list_run_events_after(
            session,
            run_id=run_id,
            after_event_id=after_event_id,
        )


async def wait_for_run_event_notification(
    run_id: str,
    timeout_seconds: float,
) -> bool:
    try:
        async with await psycopg.AsyncConnection.connect(
            _psycopg_url(DATABASE_URL),
            autocommit=True,
        ) as connection:
            await connection.execute("LISTEN agent_run_events")
            return await wait_for_matching_run_notification(
                run_id,
                _notification_payloads(connection, timeout_seconds),
            )
    except Exception:
        await asyncio.sleep(timeout_seconds)
    return False


async def wait_for_matching_run_notification(
    run_id: str,
    payloads: AsyncIterable[str],
) -> bool:
    async for payload in payloads:
        if payload == run_id:
            return True
    return False


async def _notification_payloads(
    connection: psycopg.AsyncConnection,
    timeout_seconds: float,
) -> AsyncIterator[str]:
    async for notify in connection.notifies(timeout=timeout_seconds):
        yield notify.payload


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def format_persisted_sse(event: AgentRunEvent) -> str:
    payload = {**event.payload, "runId": event.agent_run_id}
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.id}\ndata: {data}\n\n"
