from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from model.message import Message


async def create_message(session: AsyncSession, message: Message) -> Message:
    session.add(message)
    await session.flush()
    return message


async def update_message(
    session: AsyncSession,
    *,
    message_id: str,
    content: str,
    reasoning: str,
    status: str,
) -> None:
    message = await session.get(Message, message_id)
    if message is None:
        return

    message.content = content
    message.reasoning = reasoning
    message.status = status
    await session.flush()


async def get_message_by_id(session: AsyncSession, message_id: str) -> Message | None:
    result = await session.execute(
        select(Message)
        .where(Message.id == message_id)
        .options(
            selectinload(Message.tool_invocations),
            selectinload(Message.timeline_parts),
        )
    )
    return result.scalar_one_or_none()


async def get_messages_by_conversation_id(
    session: AsyncSession,
    conversation_id: str,
) -> list[Message]:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .options(
            selectinload(Message.tool_invocations),
            selectinload(Message.timeline_parts),
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    return list(result.scalars().all())
