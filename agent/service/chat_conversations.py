from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from model.conversation import Conversation
from repository.conversation import (
    create_conversation,
    delete_conversation,
    get_conversation_by_id,
    conversations_list,
    update_conversation_title,
)
from repository.message import get_messages_by_conversation_id
from model.message import Message
from model.message_part import MessagePart
from model.tool_invocation import ToolInvocation
from schema.chat import (
    ChatMessage,
    ReasoningTimelinePart,
    ToolInvocation as ToolInvocationSchema,
    ToolTimelinePart,
    ChatTimelinePart,
)
from schema.chat_conversations import ChatConversation


async def create_chat_conversation(
    session: AsyncSession,
    *,
    id_factory: Callable[[], str] = lambda: str(uuid4()),
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ChatConversation:
    now = now_factory()

    conversation = Conversation(
        id=id_factory(),
        title="New chat",
        created_at=now,
        updated_at=now,
    )

    try:
        await create_conversation(session, conversation)
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    return ChatConversation(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


async def get_conversations_list(session: AsyncSession):
    return await conversations_list(session=session)


async def update_chat_conversation_title(
    session: AsyncSession,
    *,
    conversation_id: str,
    title: str,
) -> ChatConversation | None:
    try:
        conversation = await update_conversation_title(
            session=session,
            conversation_id=conversation_id,
            title=title,
        )
        if conversation is None:
            return None

        await session.commit()
    except Exception:
        await session.rollback()
        raise

    return _to_chat_conversation(conversation)


async def delete_chat_conversation(
    session: AsyncSession,
    *,
    conversation_id: str,
) -> bool:
    conversation = await get_conversation_by_id(
        session=session,
        conversation_id=conversation_id,
    )
    if conversation is None:
        return False

    try:
        await delete_conversation(session=session, conversation=conversation)
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    return True


async def get_conversation_messages(
    session: AsyncSession,
    *,
    conversation_id: str,
) -> list[ChatMessage]:
    messages = await get_messages_by_conversation_id(
        session=session,
        conversation_id=conversation_id,
    )

    return [_to_chat_message(message) for message in messages]


def _to_tool_invocation(invocation: ToolInvocation) -> ToolInvocationSchema:
    return ToolInvocationSchema(
        id=invocation.id,
        message_id=invocation.message_id,
        tool_name=invocation.tool_name,
        args=invocation.args,
        result=invocation.result,
        error=invocation.error,
        latency_ms=invocation.latency_ms,
        status=invocation.status,
        created_at=invocation.created_at.isoformat(),
    )


def _to_timeline_part(part: MessagePart) -> ChatTimelinePart | None:
    if part.type == "tool" and part.tool_invocation is not None:
        return ToolTimelinePart(
            id=part.id,
            type="tool",
            order_index=part.order_index,
            invocation=_to_tool_invocation(part.tool_invocation),
        )
    if part.type == "tool":
        return None

    return ReasoningTimelinePart(
        id=part.id,
        type="reasoning",
        order_index=part.order_index,
        text=part.text,
    )


def _to_chat_message(message: Message) -> ChatMessage:
    tool_invocations = sorted(
        message.tool_invocations,
        key=lambda invocation: (invocation.created_at, invocation.id),
    )
    timeline_parts = sorted(
        message.timeline_parts,
        key=lambda part: (part.order_index, part.id),
    )

    return ChatMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        reasoning=message.reasoning,
        tool_invocations=[_to_tool_invocation(item) for item in tool_invocations],
        timeline_parts=[
            item
            for item in (_to_timeline_part(part) for part in timeline_parts)
            if item is not None
        ],
        status=message.status,
        created_at=message.created_at.isoformat(),
    )


def _to_chat_conversation(conversation: Conversation) -> ChatConversation:
    return ChatConversation(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )
