from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from model.approval import ApprovalBatch, ApprovalRequest


async def get_approval_batch_by_interrupt_id(
    session: AsyncSession,
    *,
    agent_run_id: str,
    interrupt_id: str,
) -> ApprovalBatch | None:
    result = await session.execute(
        select(ApprovalBatch)
        .where(ApprovalBatch.agent_run_id == agent_run_id)
        .where(ApprovalBatch.interrupt_id == interrupt_id)
    )
    return result.scalar_one_or_none()


async def next_approval_batch_sequence(
    session: AsyncSession,
    *,
    agent_run_id: str,
) -> int:
    result = await session.execute(
        select(func.max(ApprovalBatch.sequence)).where(
            ApprovalBatch.agent_run_id == agent_run_id
        )
    )
    current = result.scalar_one_or_none()
    return (current or 0) + 1


async def create_approval_batch(
    session: AsyncSession,
    batch: ApprovalBatch,
) -> ApprovalBatch:
    session.add(batch)
    await session.flush()
    return batch


async def create_approval_request(
    session: AsyncSession,
    request: ApprovalRequest,
) -> ApprovalRequest:
    session.add(request)
    await session.flush()
    return request
