from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.conversation import Conversation


async def create_conversation(
    session: AsyncSession,
    conversation: Conversation,
) -> Conversation:
    session.add(conversation)
    await session.flush()
    return conversation


async def get_conversation_by_id(
    session: AsyncSession,
    conversation_id: str,
) -> Conversation | None:
    result = await session.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    return result.scalar_one_or_none()


async def list_conversations(session: AsyncSession) -> list[Conversation]:
    result = await session.execute(
        select(Conversation).order_by(Conversation.updated_at.desc(), Conversation.id.asc())
    )
    return list(result.scalars().all())


async def update_conversation_title(
    session: AsyncSession,
    *,
    conversation_id: str,
    title: str,
) -> Conversation | None:
    conversation = await get_conversation_by_id(session, conversation_id)
    if conversation is None:
        return None

    conversation.title = title
    await session.flush()
    return conversation


async def delete_conversation(
    session: AsyncSession,
    conversation: Conversation,
) -> None:
    await session.delete(conversation)
    await session.flush()
