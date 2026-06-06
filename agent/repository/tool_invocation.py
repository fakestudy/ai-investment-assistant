from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from model.tool_invocation import ToolInvocation


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
    result: Any | None,
    error: str | None,
    latency_ms: int | None,
    status: str,
) -> ToolInvocation | None:
    invocation = await session.get(ToolInvocation, invocation_id)
    if invocation is None:
        return None

    invocation.result = result
    invocation.error = error
    invocation.latency_ms = latency_ms
    invocation.status = status
    await session.flush()
    return invocation
