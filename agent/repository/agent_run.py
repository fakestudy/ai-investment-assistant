from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from model.approval import ApprovalBatch
from model.agent_run import ACTIVE_RUN_STATUSES, AgentRun
from model.agent_run_event import AgentRunEvent


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


async def get_last_event_id_for_run(
    session: AsyncSession,
    *,
    run_id: str,
) -> int | None:
    result = await session.execute(
        select(func.max(AgentRunEvent.id)).where(AgentRunEvent.agent_run_id == run_id)
    )
    return result.scalar_one_or_none()


async def get_pending_approval_batch_for_run(
    session: AsyncSession,
    *,
    run_id: str,
) -> ApprovalBatch | None:
    result = await session.execute(
        select(ApprovalBatch)
        .where(ApprovalBatch.agent_run_id == run_id)
        .where(ApprovalBatch.status == "pending")
        .options(selectinload(ApprovalBatch.requests))
        .order_by(ApprovalBatch.sequence.desc(), ApprovalBatch.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()
