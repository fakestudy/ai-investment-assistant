from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.agent_run_event import AgentRunEvent


async def create_agent_run_event(
    session: AsyncSession,
    agent_run_event: AgentRunEvent,
) -> AgentRunEvent:
    session.add(agent_run_event)
    await session.flush()
    return agent_run_event


async def list_run_events_after(
    session: AsyncSession,
    *,
    run_id: str,
    after_event_id: int,
) -> list[AgentRunEvent]:
    result = await session.execute(
        select(AgentRunEvent)
        .where(AgentRunEvent.agent_run_id == run_id)
        .where(AgentRunEvent.id > after_event_id)
        .order_by(AgentRunEvent.id.asc())
    )
    return list(result.scalars().all())


async def has_run_event_at_or_before(
    session: AsyncSession,
    *,
    run_id: str,
    event_types: set[str],
    event_id: int,
) -> bool:
    result = await session.execute(
        select(AgentRunEvent.id)
        .where(AgentRunEvent.agent_run_id == run_id)
        .where(AgentRunEvent.event_type.in_(event_types))
        .where(AgentRunEvent.id <= event_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None
