from sqlalchemy.ext.asyncio import AsyncSession

from model.outbox_event import OutboxEvent


async def create_outbox_event(
    session: AsyncSession,
    outbox_event: OutboxEvent,
) -> OutboxEvent:
    session.add(outbox_event)
    await session.flush()
    return outbox_event
