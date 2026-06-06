from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from model.message import Message


async def create_message(
    session: AsyncSession,
    message: Message,
) -> Message:
    session.add(message)
    await session.flush()
    return message


async def get_messages_by_conversation_id(
    session: AsyncSession,
    *,
    conversation_id: str,
) -> list[Message]:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )

    return list(result.scalars().all())
