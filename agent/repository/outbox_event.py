from datetime import datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from model.outbox_event import OutboxEvent


async def create_outbox_event(
    session: AsyncSession,
    outbox_event: OutboxEvent,
) -> OutboxEvent:
    session.add(outbox_event)
    await session.flush()
    return outbox_event


async def claim_pending_outbox_events(
    session: AsyncSession,
    *,
    limit: int,
    now: datetime,
    lease_expires_at: datetime,
) -> list[OutboxEvent]:
    result = await session.execute(
        select(OutboxEvent)
        .where(
            or_(
                and_(
                    OutboxEvent.status == "pending",
                    OutboxEvent.available_at <= now,
                ),
                and_(
                    OutboxEvent.status == "publishing",
                    OutboxEvent.available_at <= now,
                ),
            )
        )
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    events = list(result.scalars().all())
    for event in events:
        event.status = "publishing"
        event.available_at = lease_expires_at
    await session.flush()
    return events


async def mark_outbox_event_published(
    session: AsyncSession,
    *,
    event_id: str,
    now: datetime,
    lease_expires_at: datetime,
) -> bool:
    result = await session.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == event_id)
        .where(OutboxEvent.status == "publishing")
        .where(OutboxEvent.available_at == lease_expires_at)
        .values(
            status="published",
            published_at=now,
            last_error=None,
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


async def mark_outbox_event_retryable(
    session: AsyncSession,
    *,
    event_id: str,
    error: str,
    available_at: datetime,
    lease_expires_at: datetime,
) -> bool:
    result = await session.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == event_id)
        .where(OutboxEvent.status == "publishing")
        .where(OutboxEvent.available_at == lease_expires_at)
        .values(
            status="pending",
            attempt_count=OutboxEvent.attempt_count + 1,
            available_at=available_at,
            last_error=error,
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1
