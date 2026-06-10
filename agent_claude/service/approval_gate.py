from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
from claude_agent_sdk.types import PermissionResult, ToolPermissionContext

from core.database import AsyncSessionLocal
from model.approval import ApprovalBatch as ApprovalBatchModel
from model.approval import ApprovalRequest as ApprovalRequestModel
from repository.agent_run import update_run_status
from repository.agent_run_event import append_run_event as append_run_event_row
from repository.approval import create_approval_batch, resolve_approval_batch
from schema.chat import (
    ApprovalBatch,
    ApprovalDecisionsRequest,
    ApprovalRequestSummary,
    ApprovalRequiredEvent,
    ApprovalResolvedEvent,
    ApprovalTimelinePart,
)
from service import run_events


DecisionMap = dict[str, str]

_approval_futures: dict[str, asyncio.Future[DecisionMap]] = {}


def _uuid_str() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ApprovalGateDependencies:
    async_session_factory: Any = AsyncSessionLocal
    create_approval_batch: Any = create_approval_batch
    resolve_approval_batch: Any = resolve_approval_batch
    update_run_status: Any = update_run_status
    append_run_event_row: Any = append_run_event_row
    stream_run_events: Any = run_events.stream_run_events
    notify_run_event: Any = run_events.notify_run_event
    id_factory: Callable[[], str] = _uuid_str
    now_factory: Callable[[], datetime] = _utcnow


@dataclass(frozen=True)
class RunApprovalContext:
    run_id: str
    conversation_id: str
    message_id: str
    approval_required_tools: tuple[str, ...]
    dependencies: ApprovalGateDependencies = field(
        default_factory=ApprovalGateDependencies
    )


def build_can_use_tool(run_context: RunApprovalContext):
    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResult:
        if tool_name not in run_context.approval_required_tools:
            return PermissionResultAllow()

        batch = await create_and_emit_approval_required(
            run_context,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_invocation_id=context.tool_use_id
            or run_context.dependencies.id_factory(),
        )
        future = register_approval_future(
            batch.id,
            asyncio.get_running_loop().create_future(),
        )
        run_context.dependencies.notify_run_event(
            run_context.run_id,
            batch.event_id,
        )

        try:
            decisions = await future
        finally:
            _approval_futures.pop(batch.id, None)

        if all(decision == "approve" for decision in decisions.values()):
            return PermissionResultAllow(updated_input=tool_input)
        return PermissionResultDeny(message="Tool execution rejected by user")

    return can_use_tool


@dataclass(frozen=True)
class CreatedApprovalBatch:
    id: str
    event_id: int


async def create_and_emit_approval_required(
    run_context: RunApprovalContext,
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    tool_invocation_id: str,
) -> CreatedApprovalBatch:
    deps = run_context.dependencies
    now = deps.now_factory()
    batch_id = deps.id_factory()
    request_id = deps.id_factory()
    part_id = deps.id_factory()

    batch_model = ApprovalBatchModel(
        id=batch_id,
        run_id=run_context.run_id,
        message_id=run_context.message_id,
        status="pending",
        expires_at=now + timedelta(minutes=30),
        created_at=now,
    )
    request_model = ApprovalRequestModel(
        id=request_id,
        approval_batch_id=batch_id,
        tool_invocation_id=tool_invocation_id,
        tool_name=tool_name,
        args=tool_input,
        decision="pending",
        created_at=now,
    )

    async with deps.async_session_factory() as session:
        batch = await deps.create_approval_batch(
            session,
            batch=batch_model,
            requests=[request_model],
        )
        projected = project_approval_batch(batch)
        event = ApprovalRequiredEvent(
            type="approval_required",
            run_id=run_context.run_id,
            message_id=run_context.message_id,
            part=ApprovalTimelinePart(
                id=part_id,
                type="approval",
                batch=projected,
            ),
            approval_batch=projected,
        )
        await deps.update_run_status(
            session,
            run_id=run_context.run_id,
            status="awaiting_approval",
        )
        row = run_events.build_run_event_row(
            run_id=run_context.run_id,
            conversation_id=run_context.conversation_id,
            message_id=run_context.message_id,
            event=event,
        )
        persisted = await deps.append_run_event_row(session, event=row)
        await session.commit()

    return CreatedApprovalBatch(id=batch_id, event_id=int(persisted.id))


async def submit_approval_decisions(
    batch_id: str,
    req: ApprovalDecisionsRequest,
    *,
    dependencies: ApprovalGateDependencies | None = None,
) -> AsyncIterator[str]:
    deps = dependencies or ApprovalGateDependencies()
    decisions = {
        decision.approval_request_id: decision.decision
        for decision in req.decisions
    }

    async with deps.async_session_factory() as session:
        batch = await deps.resolve_approval_batch(
            session,
            batch_id=batch_id,
            decisions=decisions,
        )
        projected = project_approval_batch(batch)
        event = ApprovalResolvedEvent(
            type="approval_resolved",
            run_id=batch.run_id,
            message_id=batch.message_id,
            batch=projected,
            approval_batch=projected,
        )
        updated_run = await deps.update_run_status(
            session,
            run_id=batch.run_id,
            status="resuming",
        )
        row = run_events.build_run_event_row(
            run_id=batch.run_id,
            conversation_id=getattr(updated_run, "conversation_id", None)
            or getattr(batch, "conversation_id", None)
            or batch.run_id,
            message_id=batch.message_id,
            event=event,
        )
        persisted = await deps.append_run_event_row(session, event=row)
        await session.commit()

    future = _approval_futures.get(batch_id)
    if future is not None and not future.done():
        future.set_result(decisions)
    deps.notify_run_event(batch.run_id, int(persisted.id))

    async for frame in deps.stream_run_events(batch.run_id, req.after_event_id):
        yield frame


def register_approval_future(
    batch_id: str,
    future: asyncio.Future[DecisionMap],
) -> asyncio.Future[DecisionMap]:
    _approval_futures[batch_id] = future
    return future


def clear_approval_futures() -> None:
    for future in list(_approval_futures.values()):
        if not future.done():
            future.cancel()
    _approval_futures.clear()


def project_approval_batch(batch: Any) -> ApprovalBatch:
    return ApprovalBatch(
        id=batch.id,
        status=batch.status,
        expires_at=_format_datetime(getattr(batch, "expires_at", None)),
        requests=[
            ApprovalRequestSummary(
                id=request.id,
                tool_invocation_id=request.tool_invocation_id,
                tool_name=request.tool_name,
                args=request.args,
                decision=request.decision,
                decided_at=_format_datetime(getattr(request, "decided_at", None)),
            )
            for request in sorted(
                list(getattr(batch, "requests", []) or []),
                key=lambda request: request.id,
            )
        ],
        resolution_source=getattr(batch, "resolution_source", None),
        resolved_at=_format_datetime(getattr(batch, "resolved_at", None)),
    )


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
