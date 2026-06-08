from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.tool_invocation import ToolInvocation

_UNSET = object()


async def create_tool_invocation(
    session: AsyncSession,
    invocation: ToolInvocation,
) -> ToolInvocation:
    session.add(invocation)
    await session.flush()
    return invocation


async def update_tool_invocation(
    session: AsyncSession,
    *,
    invocation_id: str,
    result: object | None = _UNSET,
    error: str | None = _UNSET,
    latency_ms: int | None = _UNSET,
    status: str,
) -> ToolInvocation:
    invocation = await session.get(ToolInvocation, invocation_id)
    if invocation is None:
        raise LookupError(f"Tool invocation not found: {invocation_id}")

    if result is not _UNSET:
        invocation.result = result
    if error is not _UNSET:
        invocation.error = error
    if latency_ms is not _UNSET:
        invocation.latency_ms = latency_ms
    invocation.status = status
    await session.flush()
    return invocation


async def get_tool_invocation_by_id(
    session: AsyncSession,
    invocation_id: str,
) -> ToolInvocation | None:
    result = await session.execute(
        select(ToolInvocation).where(ToolInvocation.id == invocation_id)
    )
    return result.scalar_one_or_none()


async def get_tool_invocations_by_message_id(
    session: AsyncSession,
    message_id: str,
) -> list[ToolInvocation]:
    result = await session.execute(
        select(ToolInvocation)
        .where(ToolInvocation.message_id == message_id)
        .order_by(ToolInvocation.created_at.asc(), ToolInvocation.id.asc())
    )
    return list(result.scalars().all())
