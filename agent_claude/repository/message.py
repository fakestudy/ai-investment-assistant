from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from model.message import Message


def _message_projection_options():
    return (
        selectinload(Message.tool_invocations),
        selectinload(Message.timeline_parts),
    )


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
) -> Message:
    message = await session.get(Message, message_id)
    if message is None:
        raise LookupError(f"Message not found: {message_id}")

    message.content = content
    message.reasoning = reasoning
    message.status = status
    await session.flush()
    return message


async def get_message_by_id(session: AsyncSession, message_id: str) -> Message | None:
    result = await session.execute(
        select(Message)
        .where(Message.id == message_id)
        .options(*_message_projection_options())
    )
    return result.scalar_one_or_none()


async def get_message_in_conversation(
    session: AsyncSession,
    *,
    conversation_id: str,
    message_id: str,
) -> Message | None:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.id == message_id)
        .options(*_message_projection_options())
    )
    return result.scalar_one_or_none()


async def get_messages_by_conversation_id(
    session: AsyncSession,
    conversation_id: str,
) -> list[Message]:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .options(*_message_projection_options())
        .order_by(Message.seq.asc())
    )
    return list(result.scalars().all())


async def edit_user_message(
    session: AsyncSession,
    *,
    message_id: str,
    content: str,
) -> Message:
    message = await get_message_by_id(session, message_id)
    if message is None:
        raise LookupError("Message not found")
    if message.role != "user":
        raise ValueError("Only user messages can be edited")

    message.content = content
    await session.flush()
    return message


async def delete_messages_after_seq(
    session: AsyncSession,
    *,
    conversation_id: str,
    seq: int,
) -> None:
    await session.execute(
        delete(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.seq > seq)
    )
    await session.flush()


async def get_previous_user_message_before_seq(
    session: AsyncSession,
    *,
    conversation_id: str,
    seq: int,
) -> Message | None:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.role == "user")
        .where(Message.seq < seq)
        .options(*_message_projection_options())
        .order_by(Message.seq.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
