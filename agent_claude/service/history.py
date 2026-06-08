from datetime import UTC, datetime

from model.message import Message
from model.message_part import MessagePart
from model.tool_invocation import ToolInvocation
from repository.message import get_messages_by_conversation_id
from schema.chat import (
    ChatMessage,
    ChatTimelinePart,
    ConversationMessagesResponse,
    ReasoningTimelinePart,
    ToolInvocation as ToolInvocationSchema,
    ToolTimelinePart,
)


async def get_conversation_messages(session, *, conversation_id: str) -> ConversationMessagesResponse:
    messages = await get_messages_by_conversation_id(
        session=session,
        conversation_id=conversation_id,
    )
    return project_conversation_messages(messages)


def project_conversation_messages(messages: list[Message]) -> ConversationMessagesResponse:
    return ConversationMessagesResponse(
        messages=[_to_chat_message(message) for message in messages],
        active_run=None,
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


def _safe_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
