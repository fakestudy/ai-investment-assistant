from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from model.approval import ApprovalBatch, ApprovalRequest


DECISION_VALUES = {
    "approve": "approved",
    "reject": "rejected",
}


async def create_approval_batch(
    session: AsyncSession,
    *,
    batch: ApprovalBatch,
    requests: list[ApprovalRequest],
) -> ApprovalBatch:
    batch.requests.extend(requests)
    session.add(batch)
    await session.flush()
    return batch


async def append_approval_request_to_batch(
    session: AsyncSession,
    *,
    batch_id: str,
    request: ApprovalRequest,
) -> ApprovalBatch:
    result = await session.execute(
        select(ApprovalBatch)
        .where(ApprovalBatch.id == batch_id)
        .options(selectinload(ApprovalBatch.requests))
        .with_for_update()
    )
    batch = result.scalar_one_or_none()
    if batch is None:
        raise LookupError(f"ApprovalBatch not found: {batch_id}")
    if batch.status != "pending":
        raise ValueError("Approval batch is already resolved")

    request.approval_batch_id = batch.id
    batch.requests.append(request)
    await session.flush()
    return batch


async def get_pending_approval_batch_by_run_id(
    session: AsyncSession,
    *,
    run_id: str,
) -> ApprovalBatch | None:
    result = await session.execute(
        select(ApprovalBatch)
        .where(
            ApprovalBatch.run_id == run_id,
            ApprovalBatch.status == "pending",
        )
        .options(selectinload(ApprovalBatch.requests))
        .order_by(ApprovalBatch.created_at.desc(), ApprovalBatch.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def resolve_approval_batch(
    session: AsyncSession,
    *,
    batch_id: str,
    decisions: dict[str, str],
) -> ApprovalBatch:
    result = await session.execute(
        select(ApprovalBatch)
        .where(ApprovalBatch.id == batch_id)
        .options(selectinload(ApprovalBatch.requests))
        .with_for_update()
    )
    batch = result.scalar_one_or_none()
    if batch is None:
        raise LookupError(f"ApprovalBatch not found: {batch_id}")
    if batch.status != "pending":
        raise ValueError("Approval batch is already resolved")

    request_ids = {request.id for request in batch.requests}
    decision_ids = set(decisions)
    invalid_decision_ids = {
        request_id
        for request_id in request_ids & decision_ids
        if decisions[request_id] not in DECISION_VALUES
    }
    if request_ids != decision_ids or invalid_decision_ids:
        raise ValueError("Approval decisions must resolve every request exactly once")

    now = datetime.now(UTC)
    batch.status = "resolved"
    batch.resolved_at = now
    batch.resolution_source = "manual"

    for request in batch.requests:
        request.decision = DECISION_VALUES[decisions[request.id]]
        request.decided_at = now

    await session.flush()
    return batch
