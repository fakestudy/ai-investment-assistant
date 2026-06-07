from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from model.agent_run import AgentRun
from model.agent_run_event import AgentRunEvent
from model.approval import ApprovalBatch, ApprovalRequest
from model.outbox_event import OutboxEvent
from model.tool_invocation import ToolInvocation
from repository.outbox_event import create_outbox_event
from schema.chat import ApprovalDecisionRequest
from service.chat import _format_datetime
from service.run_events import append_run_event


class ApprovalDecisionValidationError(ValueError):
    pass


class ApprovalDecisionConflict(RuntimeError):
    pass


class ApprovalBatchNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class ApprovalDecisionResult:
    batch: ApprovalBatch
    requests: list[ApprovalRequest]
    run: AgentRun
    event: AgentRunEvent
    outbox: OutboxEvent


async def submit_approval_decisions(
    session: AsyncSession,
    batch_id: str,
    request: ApprovalDecisionRequest,
    *,
    now: datetime | None = None,
) -> ApprovalDecisionResult:
    decided_at = now or datetime.now(UTC)
    batch = await _lock_batch(session, batch_id)
    if batch is None:
        raise ApprovalBatchNotFound(batch_id)
    run = await _lock_run(session, batch.agent_run_id)
    if run is None:
        raise ApprovalBatchNotFound(batch_id)

    requests = sorted(batch.requests, key=lambda item: item.order_index)
    submitted = _validated_decision_map(request, requests)

    if batch.status != "pending":
        return await _existing_resolution(session, batch, requests, run, submitted)

    if decided_at >= batch.expires_at:
        raise ApprovalDecisionConflict("Approval batch has expired")

    for approval_request in requests:
        submitted_decision = submitted[approval_request.id]
        approval_request.decision = _stored_decision(submitted_decision)
        approval_request.decided_at = decided_at
        tool = await session.get(ToolInvocation, approval_request.tool_invocation_id)
        if tool is not None:
            tool.status = "running" if submitted_decision == "approve" else "rejected"

    batch.status = "resolved"
    batch.resolution_source = "manual"
    batch.resolved_at = decided_at
    run.status = "resume_queued"
    run.lease_owner = None
    run.lease_expires_at = None
    run.updated_at = decided_at
    run.version += 1

    outbox = await create_outbox_event(
        session,
        OutboxEvent(
            id=_resume_outbox_id(batch.id),
            event_type="agent.run.resume",
            aggregate_id=batch.id,
            payload={
                "runId": run.id,
                "batchId": batch.id,
                "interruptId": batch.interrupt_id,
                "decisions": _ordered_resume_decisions(submitted, requests),
            },
            status="pending",
            attempt_count=0,
            available_at=decided_at,
            published_at=None,
            last_error=None,
            created_at=decided_at,
        ),
    )
    event = await append_run_event(
        session,
        run.id,
        "approval_resolved",
        {
            "type": "approval_resolved",
            "batch": _approval_batch_payload(batch, requests),
        },
    )
    await session.flush()
    return ApprovalDecisionResult(
        batch=batch,
        requests=requests,
        run=run,
        event=event,
        outbox=outbox,
    )


async def _lock_batch(
    session: AsyncSession,
    batch_id: str,
) -> ApprovalBatch | None:
    result = await session.execute(
        select(ApprovalBatch)
        .options(selectinload(ApprovalBatch.requests))
        .where(ApprovalBatch.id == batch_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def _lock_run(session: AsyncSession, run_id: str) -> AgentRun | None:
    result = await session.execute(
        select(AgentRun).where(AgentRun.id == run_id).with_for_update()
    )
    return result.scalar_one_or_none()


def _validated_decision_map(
    request: ApprovalDecisionRequest,
    requests: list[ApprovalRequest],
) -> dict[str, str]:
    expected_ids = {item.id for item in requests}
    submitted_ids = [item.approval_request_id for item in request.decisions]
    if len(submitted_ids) != len(set(submitted_ids)):
        raise ApprovalDecisionValidationError("Duplicate approval request decision")
    if set(submitted_ids) != expected_ids:
        raise ApprovalDecisionValidationError("Approval decisions must match the batch")
    return {item.approval_request_id: item.decision for item in request.decisions}


async def _existing_resolution(
    session: AsyncSession,
    batch: ApprovalBatch,
    requests: list[ApprovalRequest],
    run: AgentRun,
    submitted: dict[str, str],
) -> ApprovalDecisionResult:
    if batch.status != "resolved" or batch.resolution_source != "manual":
        raise ApprovalDecisionConflict("Approval batch is not pending")
    existing = {
        item.id: "approve" if item.decision == "approved" else "reject"
        for item in requests
    }
    if submitted != existing:
        raise ApprovalDecisionConflict("Approval batch was resolved differently")
    event = await _existing_resolved_event(session, run.id, batch.id)
    outbox = await _existing_resume_outbox(session, batch.id)
    return ApprovalDecisionResult(
        batch=batch,
        requests=requests,
        run=run,
        event=event,
        outbox=outbox,
    )


async def _existing_resolved_event(
    session: AsyncSession,
    run_id: str,
    batch_id: str,
) -> AgentRunEvent:
    result = await session.execute(
        select(AgentRunEvent)
        .where(AgentRunEvent.agent_run_id == run_id)
        .where(AgentRunEvent.event_type == "approval_resolved")
        .order_by(AgentRunEvent.id.asc())
    )
    for event in result.scalars().all():
        if event.payload.get("batch", {}).get("id") == batch_id:
            return event
    raise ApprovalDecisionConflict("Resolved approval event not found")


async def _existing_resume_outbox(
    session: AsyncSession,
    batch_id: str,
) -> OutboxEvent:
    result = await session.execute(
        select(OutboxEvent)
        .where(OutboxEvent.id == _resume_outbox_id(batch_id))
        .where(OutboxEvent.event_type == "agent.run.resume")
    )
    outbox = result.scalar_one_or_none()
    if outbox is None:
        raise ApprovalDecisionConflict("Resume outbox event not found")
    return outbox


def _stored_decision(decision: str) -> str:
    return "approved" if decision == "approve" else "rejected"


def _ordered_resume_decisions(
    submitted: dict[str, str],
    requests: list[ApprovalRequest],
) -> list[dict[str, str]]:
    decisions: list[dict[str, str]] = []
    for approval_request in requests:
        if submitted[approval_request.id] == "approve":
            decisions.append({"type": "approve"})
        else:
            decisions.append({"type": "reject", "message": "Rejected by user"})
    return decisions


def _approval_batch_payload(
    batch: ApprovalBatch,
    requests: list[ApprovalRequest],
) -> dict[str, Any]:
    return {
        "id": batch.id,
        "status": batch.status,
        "expiresAt": _format_datetime(batch.expires_at),
        "resolutionSource": batch.resolution_source,
        "resolvedAt": _format_datetime(batch.resolved_at) if batch.resolved_at else None,
        "requests": [
            {
                "id": item.id,
                "toolInvocationId": item.tool_invocation_id,
                "toolName": item.tool_name,
                "args": item.args,
                "decision": item.decision,
                "decidedAt": _format_datetime(item.decided_at)
                if item.decided_at
                else None,
            }
            for item in requests
        ],
    }


def _resume_outbox_id(batch_id: str) -> str:
    return f"{batch_id}-resume"
