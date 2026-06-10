from datetime import UTC, datetime

from model.message import Message
from model.message_part import MessagePart
from model.tool_invocation import ToolInvocation
from repository.agent_run import get_active_run_by_conversation_id
from repository.approval import get_pending_approval_batch_by_run_id
from repository.message import get_messages_by_conversation_id
from schema.chat import (
    ActiveRunSummary,
    ApprovalBatch,
    ApprovalRequestSummary,
    ChatMessage,
    ChatConversation,
    ChatTimelinePart,
    ConversationMessagesResponse,
    ReasoningTimelinePart,
    ToolInvocation as ToolInvocationSchema,
    ToolTimelinePart,
)


def project_conversation(conversation) -> ChatConversation:
    return ChatConversation(
        id=conversation.id,
        title=conversation.title,
        created_at=_format_datetime(conversation.created_at),
        updated_at=_format_datetime(conversation.updated_at),
    )


async def get_conversation_messages(session, *, conversation_id: str) -> ConversationMessagesResponse:
    messages = await get_messages_by_conversation_id(
        session=session,
        conversation_id=conversation_id,
    )
    active_run = await get_active_run_by_conversation_id(
        session=session,
        conversation_id=conversation_id,
    )
    approval_batch = (
        await get_pending_approval_batch_by_run_id(session=session, run_id=active_run.id)
        if active_run is not None
        else None
    )
    return project_conversation_messages(
        messages,
        active_run=_to_active_run_summary(
            active_run,
            approval_batch=approval_batch,
        )
        if active_run is not None
        else None,
    )


def project_conversation_messages(
    messages: list[Message],
    *,
    active_run: ActiveRunSummary | None = None,
) -> ConversationMessagesResponse:
    return ConversationMessagesResponse(
        messages=[_to_chat_message(message) for message in messages],
        active_run=active_run,
    )


def _to_active_run_summary(run, *, approval_batch=None) -> ActiveRunSummary:
    return ActiveRunSummary(
        run_id=run.id,
        status=run.status,
        last_event_id=run.last_event_id,
        assistant_message_id=run.assistant_message_id,
        approval_batch=_to_approval_batch(approval_batch)
        if approval_batch is not None
        else None,
    )


def _to_approval_batch(batch) -> ApprovalBatch:
    return ApprovalBatch(
        id=batch.id,
        status=batch.status,
        expires_at=_format_optional_datetime(getattr(batch, "expires_at", None)),
        requests=[
            ApprovalRequestSummary(
                id=request.id,
                tool_invocation_id=request.tool_invocation_id,
                tool_name=request.tool_name,
                args=request.args,
                decision=request.decision,
                decided_at=_format_optional_datetime(
                    getattr(request, "decided_at", None)
                ),
            )
            for request in sorted(
                list(getattr(batch, "requests", []) or []),
                key=lambda request: request.id,
            )
        ],
        resolution_source=getattr(batch, "resolution_source", None),
        resolved_at=_format_optional_datetime(getattr(batch, "resolved_at", None)),
    )


def _to_chat_message(message: Message) -> ChatMessage:
    invocations = sorted(
        list(getattr(message, "tool_invocations", []) or []),
        key=lambda invocation: (_safe_datetime(invocation.created_at), invocation.id),
    )
    timeline_parts = sorted(
        list(getattr(message, "timeline_parts", []) or []),
        key=lambda part: (part.order_index, part.id),
    )
    invocation_by_id = {invocation.id: invocation for invocation in invocations}

    return ChatMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        reasoning=message.reasoning or None,
        tool_invocations=[_to_tool_invocation(invocation) for invocation in invocations],
        timeline_parts=[
            projected
            for projected in (
                _to_timeline_part(part, invocation_by_id) for part in timeline_parts
            )
            if projected is not None
        ],
        status=message.status,
        created_at=_format_datetime(message.created_at),
    )


def _to_timeline_part(
    part: MessagePart,
    invocation_by_id: dict[str, ToolInvocation],
) -> ChatTimelinePart | None:
    if part.type == "reasoning":
        return ReasoningTimelinePart(
            id=part.id,
            type="reasoning",
            order_index=part.order_index,
            text=part.text,
        )

    if part.type == "tool":
        invocation_id = getattr(part, "tool_invocation_id", None)
        invocation = invocation_by_id.get(invocation_id)
        if invocation is None:
            return None
        return ToolTimelinePart(
            id=part.id,
            type="tool",
            order_index=part.order_index,
            invocation=_to_tool_invocation(invocation),
        )

    return None


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
        created_at=_format_datetime(invocation.created_at),
    )


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _format_optional_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _format_datetime(value)


def _safe_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
