from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.agent_run import ACTIVE_RUN_STATUSES, AgentRun


TERMINAL_RUN_STATUSES = {"completed", "failed"}


async def create_run(session: AsyncSession, *, run: AgentRun) -> AgentRun:
    session.add(run)
    await session.flush()
    return run


async def get_active_run_by_conversation_id(
    session: AsyncSession,
    conversation_id: str,
) -> AgentRun | None:
    result = await session.execute(
        select(AgentRun)
        .where(AgentRun.conversation_id == conversation_id)
        .where(AgentRun.status.in_(ACTIVE_RUN_STATUSES))
        .order_by(AgentRun.created_at.desc(), AgentRun.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_run_by_id(session: AsyncSession, run_id: str) -> AgentRun | None:
    return await session.get(AgentRun, run_id)


async def update_run_status(
    session: AsyncSession,
    *,
    run_id: str,
    status: str,
    error: str | None = None,
) -> AgentRun:
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise LookupError(f"AgentRun not found: {run_id}")

    now = datetime.now(UTC)
    run.status = status
    run.updated_at = now
    if error is not None:
        run.error = error
    if status in TERMINAL_RUN_STATUSES:
        run.completed_at = now
    await session.flush()
    return run


async def request_cancel(
    session: AsyncSession,
    *,
    assistant_message_id: str,
) -> AgentRun | None:
    result = await session.execute(
        select(AgentRun)
        .where(AgentRun.assistant_message_id == assistant_message_id)
        .where(AgentRun.status.in_(ACTIVE_RUN_STATUSES))
        .order_by(AgentRun.created_at.desc(), AgentRun.id.asc())
        .limit(1)
        .with_for_update()
    )
    run = result.scalar_one_or_none()
    if run is None:
        return None

    now = datetime.now(UTC)
    run.cancel_requested_at = now
    run.updated_at = now
    await session.flush()
    return run
