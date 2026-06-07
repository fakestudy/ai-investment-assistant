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
from repository.agent_run import (
    get_active_run_by_conversation_id,
    get_last_event_id_for_run,
    get_pending_approval_batch_for_run,
)
from repository.message import get_messages_by_conversation_id
from model.agent_run import AgentRun
from model.approval import ApprovalBatch, ApprovalRequest
from model.message import Message
from model.message_part import MessagePart
from model.tool_invocation import ToolInvocation
from schema.chat import (
    ActiveRunSummary,
    ApprovalBatchPayload,
    ApprovalRequestPayload,
    ApprovalTimelinePart,
    ChatMessage,
    ConversationMessagesResponse,
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
) -> ConversationMessagesResponse:
    messages = await get_messages_by_conversation_id(
        session=session,
        conversation_id=conversation_id,
    )
    active_run = await get_active_run_by_conversation_id(
        session=session,
        conversation_id=conversation_id,
    )

    return ConversationMessagesResponse(
        messages=[_to_chat_message(message) for message in messages],
        active_run=await _to_active_run_summary(session, active_run),
    )


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
    if part.type == "approval" and part.approval_batch is not None:
        return ApprovalTimelinePart(
            id=part.id,
            type="approval",
            order_index=part.order_index,
            batch=_to_approval_batch_payload(part.approval_batch),
        )
    if part.type == "approval":
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


async def _to_active_run_summary(
    session: AsyncSession,
    run: AgentRun | None,
) -> ActiveRunSummary | None:
    if run is None:
        return None

    pending_batch = await get_pending_approval_batch_for_run(
        session=session,
        run_id=run.id,
    )
    return ActiveRunSummary(
        run_id=run.id,
        status=run.status,
        last_event_id=await get_last_event_id_for_run(session=session, run_id=run.id),
        assistant_message_id=run.assistant_message_id,
        approval_batch=_to_approval_batch_payload(pending_batch)
        if pending_batch is not None
        else None,
    )


def _to_approval_batch_payload(batch: ApprovalBatch) -> ApprovalBatchPayload:
    requests = sorted(batch.requests, key=lambda item: (item.order_index, item.id))
    return ApprovalBatchPayload(
        id=batch.id,
        status=batch.status,
        expires_at=_format_datetime(batch.expires_at),
        resolution_source=batch.resolution_source,
        resolved_at=_format_datetime(batch.resolved_at) if batch.resolved_at else None,
        requests=[_to_approval_request_payload(item) for item in requests],
    )


def _to_approval_request_payload(request: ApprovalRequest) -> ApprovalRequestPayload:
    return ApprovalRequestPayload(
        id=request.id,
        tool_invocation_id=request.tool_invocation_id,
        tool_name=request.tool_name,
        args=request.args,
        decision=request.decision,
        decided_at=_format_datetime(request.decided_at) if request.decided_at else None,
    )


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _to_chat_conversation(conversation: Conversation) -> ChatConversation:
    return ChatConversation(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )
