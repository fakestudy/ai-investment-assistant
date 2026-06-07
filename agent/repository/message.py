from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from model.approval import ApprovalBatch
from model.message import Message
from model.message_part import MessagePart


async def create_message(
    session: AsyncSession,
    message: Message,
) -> Message:
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
) -> Message | None:
    message = await session.get(Message, message_id)
    if message is None:
        return None

    message.content = content
    message.reasoning = reasoning
    message.status = status
    await session.flush()
    return message


async def get_messages_by_conversation_id(
    session: AsyncSession,
    *,
    conversation_id: str,
) -> list[Message]:
    role_order = case(
        (Message.role == "user", 0),
        (Message.role == "assistant", 1),
        else_=2,
    )

    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .options(
            selectinload(Message.tool_invocations),
            selectinload(Message.timeline_parts).selectinload(
                MessagePart.tool_invocation
            ),
            selectinload(Message.timeline_parts)
            .selectinload(MessagePart.approval_batch)
            .selectinload(ApprovalBatch.requests),
        )
        .order_by(Message.created_at.asc(), role_order.asc(), Message.id.asc())
    )

    return list(result.scalars().all())
