from sqlalchemy.ext.asyncio import AsyncSession

from model.message_part import MessagePart


async def create_message_part(
    session: AsyncSession,
    part: MessagePart,
) -> MessagePart:
    session.add(part)
    await session.flush()
    return part


async def update_message_part_text(
    session: AsyncSession,
    *,
    part_id: str,
    text: str,
) -> MessagePart | None:
    part = await session.get(MessagePart, part_id)
    if part is None:
        return None

    part.text = text
    await session.flush()
    return part
