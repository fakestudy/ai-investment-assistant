from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.message_part import MessagePart


async def create_message_part(
    session: AsyncSession,
    message_part: MessagePart,
) -> MessagePart:
    session.add(message_part)
    await session.flush()
    return message_part


async def update_message_part_text(
    session: AsyncSession,
    *,
    part_id: str,
    text: str,
) -> None:
    message_part = await session.get(MessagePart, part_id)
    if message_part is None:
        return

    message_part.text = text
    await session.flush()


async def get_message_parts_by_message_id(
    session: AsyncSession,
    message_id: str,
) -> list[MessagePart]:
    result = await session.execute(
        select(MessagePart)
        .where(MessagePart.message_id == message_id)
        .order_by(MessagePart.order_index.asc(), MessagePart.id.asc())
    )
    return list(result.scalars().all())
