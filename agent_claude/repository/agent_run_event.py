from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.agent_run import AgentRun
from model.agent_run_event import AgentRunEvent


async def append_run_event(
    session: AsyncSession,
    *,
    event: AgentRunEvent,
) -> AgentRunEvent:
    session.add(event)
    await session.flush()
    run = await session.get(AgentRun, event.run_id)
    if run is None:
        raise LookupError(f"AgentRun not found: {event.run_id}")
    run.last_event_id = event.id
    run.updated_at = datetime.now(UTC)
    await session.flush()
    return event


async def list_run_events_after(
    session: AsyncSession,
    *,
    run_id: str,
    after_event_id: int,
) -> list[AgentRunEvent]:
    result = await session.execute(
        select(AgentRunEvent)
        .where(AgentRunEvent.run_id == run_id)
        .where(AgentRunEvent.id > after_event_id)
        .order_by(AgentRunEvent.id.asc())
    )
    return list(result.scalars().all())
