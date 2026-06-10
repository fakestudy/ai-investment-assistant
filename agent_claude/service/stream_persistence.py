from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from core.database import AsyncSessionLocal
from model.message import Message
from model.message_part import MessagePart
from model.tool_invocation import ToolInvocation
from repository.conversation import update_conversation_title
from repository.message_part import create_message_part, update_message_part_text
from repository.tool_invocation import create_tool_invocation, update_tool_invocation
from schema.chat import (
    ChatMessage,
    ToolInvocation as ToolInvocationSchema,
)


async def persist_reasoning_delta(
    *,
    message_id: str,
    part_id: str | None,
    text: str,
    order_index: int,
    async_session_factory: Any = AsyncSessionLocal,
) -> tuple[str, int]:
    async with async_session_factory() as session:
        if part_id is None:
            part_id = str(uuid4())
            await create_message_part(
                session,
                MessagePart(
                    id=part_id,
                    message_id=message_id,
                    type="reasoning",
                    order_index=order_index,
                    text=text,
                    tool_invocation_id=None,
                    created_at=datetime.now(UTC),
                ),
            )
            next_order_index = order_index + 1
        else:
            await update_message_part_text(session, part_id=part_id, text=text)
            next_order_index = order_index
        await session.commit()
    return part_id, next_order_index


async def persist_tool_call(
    *,
    message_id: str,
    tool_id: str,
    tool_name: str,
    args: dict[str, Any],
    order_index: int,
    async_session_factory: Any = AsyncSessionLocal,
) -> tuple[ToolInvocation, int]:
    async with async_session_factory() as session:
        invocation = await create_tool_invocation(
            session,
            ToolInvocation(
                id=tool_id,
                message_id=message_id,
                tool_name=tool_name,
                args=args,
                result=None,
                error=None,
                latency_ms=None,
                status="running",
                created_at=datetime.now(UTC),
            ),
        )
        await create_message_part(
            session,
            MessagePart(
                id=str(uuid4()),
                message_id=message_id,
                type="tool",
                order_index=order_index,
                text="",
                tool_invocation_id=tool_id,
                created_at=datetime.now(UTC),
            ),
        )
        await session.commit()
    return invocation, order_index + 1


async def persist_tool_result(
    *,
    message_id: str,
    tool_id: str,
    result: Any | None,
    error: str | None,
    latency_ms: int | None,
    order_index: int,
    async_session_factory: Any = AsyncSessionLocal,
) -> ToolInvocation:
    async with async_session_factory() as session:
        try:
            invocation = await update_tool_invocation(
                session,
                invocation_id=tool_id,
                result=result,
                error=error,
                latency_ms=latency_ms,
                status="error" if error else "completed",
            )
        except LookupError:
            invocation = await create_tool_invocation(
                session,
                ToolInvocation(
                    id=tool_id,
                    message_id=message_id,
                    tool_name="unknown",
                    args={},
                    result=result,
                    error=error,
                    latency_ms=latency_ms,
                    status="error" if error else "completed",
                    created_at=datetime.now(UTC),
                ),
            )
            await create_message_part(
                session,
                MessagePart(
                    id=str(uuid4()),
                    message_id=message_id,
                    type="tool",
                    order_index=order_index,
                    text="",
                    tool_invocation_id=tool_id,
                    created_at=datetime.now(UTC),
                ),
            )
        await session.commit()
    return invocation


async def persist_title(
    *,
    conversation_id: str,
    title: str,
    async_session_factory: Any = AsyncSessionLocal,
    update_conversation_title_fn: Any = update_conversation_title,
) -> bool:
    async with async_session_factory() as session:
        conversation = await update_conversation_title_fn(
            session,
            conversation_id=conversation_id,
            title=title,
        )
        if conversation is None:
            return False
        await session.commit()
    return True


def project_stream_message(message: Message) -> ChatMessage:
    return ChatMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        reasoning=None,
        tool_invocations=[],
        timeline_parts=[],
        status=message.status,
        created_at=format_datetime(message.created_at),
    )


def project_tool_invocation(invocation: ToolInvocation) -> ToolInvocationSchema:
    return ToolInvocationSchema(
        id=invocation.id,
        message_id=invocation.message_id,
        tool_name=invocation.tool_name,
        args=invocation.args,
        result=invocation.result,
        error=invocation.error,
        latency_ms=invocation.latency_ms,
        status=invocation.status,
        created_at=format_datetime(invocation.created_at),
    )


def format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
