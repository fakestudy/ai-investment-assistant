from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.agent_run import ACTIVE_RUN_STATUSES, AgentRun


async def create_agent_run(
    session: AsyncSession,
    agent_run: AgentRun,
) -> AgentRun:
    session.add(agent_run)
    await session.flush()
    return agent_run


async def get_active_run_by_conversation_id(
    session: AsyncSession,
    *,
    conversation_id: str,
) -> AgentRun | None:
    result = await session.execute(
        select(AgentRun)
        .where(AgentRun.conversation_id == conversation_id)
        .where(AgentRun.status.in_(ACTIVE_RUN_STATUSES))
        .order_by(AgentRun.updated_at.desc(), AgentRun.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()
