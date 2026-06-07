from __future__ import annotations

from dataclasses import dataclass
from inspect import isawaitable
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessageChunk, ToolMessage
from langgraph.types import Interrupt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from model.agent_run import AgentRun
from model.agent_run_event import AgentRunEvent
from model.approval import ApprovalBatch, ApprovalRequest
from model.message_part import MessagePart
from model.outbox_event import OutboxEvent
from repository.conversation import update_conversation_title
from model.tool_invocation import ToolInvocation
from repository.approval import (
    create_approval_batch,
    create_approval_request,
    get_approval_batch_by_interrupt_id,
    next_approval_batch_sequence,
)
from repository.message import update_message
from repository.message_part import create_message_part, update_message_part_text
from repository.outbox_event import create_outbox_event
from repository.tool_invocation import create_tool_invocation, update_tool_invocation
from service.chat import (
    TimelineState,
    _content_text,
    _format_datetime,
    _reasoning_text,
    _stream_message,
    _tool_call_events,
)
from service.run_events import append_run_event


NowFactory = Callable[[], datetime]


@dataclass(frozen=True)
class ApprovalProjectionResult:
    batch: ApprovalBatch
    requests: list[ApprovalRequest]
    part: MessagePart
    event: AgentRunEvent
    outbox: OutboxEvent


class StreamProjection:
    def __init__(
        self,
        *,
        run: AgentRun,
        now_factory: NowFactory = lambda: datetime.now(UTC),
    ) -> None:
        self.run = run
        self.now_factory = now_factory
        self.assistant_content: list[str] = []
        self.assistant_reasoning: list[str] = []
        self.timeline_state = TimelineState()
        self.pending_tool_chunk: AIMessageChunk | None = None
        self.tool_invocations: dict[str, dict[str, Any]] = {}
        self.tool_started_at: dict[str, float] = {}
        self.pending_tool_invocation_ids: set[str] = set()

    async def project_item(
        self,
        session: AsyncSession,
        stream_item: object,
    ) -> list[dict[str, Any]]:
        interrupt = _stream_interrupt(stream_item)
        if interrupt is not None:
            result = await self.project_interrupt(session, interrupt)
            return [result.event.payload]

        message = _stream_message(stream_item)

        if isinstance(message, AIMessageChunk):
            return await self._project_ai_chunk(session, message)
        if isinstance(message, ToolMessage):
            return await self._project_tool_message(session, message)
        return []

    async def project_done(self, session: AsyncSession) -> dict[str, Any]:
        self.run.status = "completed"
        self.run.completed_at = self.now_factory()
        self._clear_lease()
        await self._update_assistant_message(session, status="done")
        return await self._append_event(
            session,
            {"type": "done", "messageId": self.run.assistant_message_id},
        )

    async def project_title(self, session: AsyncSession, title: str) -> dict[str, Any]:
        await update_conversation_title(
            session=session,
            conversation_id=self.run.conversation_id,
            title=title,
        )
        return await self._append_event(
            session,
            {
                "type": "title",
                "conversationId": self.run.conversation_id,
                "title": title,
            },
        )

    async def project_interrupt(
        self,
        session: AsyncSession,
        interrupt: Interrupt,
    ) -> ApprovalProjectionResult:
        return await project_interrupt(
            session,
            self.run,
            interrupt,
            now=self.now_factory(),
            next_order_index=self.timeline_state.next_order_index,
        )

    async def project_error(
        self,
        session: AsyncSession,
        error: Exception,
    ) -> dict[str, Any]:
        message = str(error)
        self.run.status = "failed"
        self.run.error = message
        self.run.completed_at = self.now_factory()
        self._clear_lease()
        await self._mark_pending_tools_error(session, message)
        await self._update_assistant_message(session, status="error")
        return await self._append_event(
            session,
            {
                "type": "error",
                "messageId": self.run.assistant_message_id,
                "message": message,
            },
        )

    async def _project_ai_chunk(
        self,
        session: AsyncSession,
        message: AIMessageChunk,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        reasoning = _reasoning_text(message)
        if reasoning:
            self.assistant_reasoning.append(reasoning)
            await self._persist_reasoning_part(session, reasoning)
            events.append(
                await self._append_event(
                    session,
                    {
                        "type": "reasoning",
                        "messageId": self.run.assistant_message_id,
                        "text": reasoning,
                    },
                )
            )

        if message.tool_call_chunks:
            self.pending_tool_chunk = (
                message if self.pending_tool_chunk is None else self.pending_tool_chunk + message
            )

        if (
            self.pending_tool_chunk is not None
            and message.response_metadata.get("finish_reason") == "tool_calls"
        ):
            events.extend(await self._flush_pending_tool_calls(session))

        content = _content_text(message.content)
        if content:
            self.assistant_content.append(content)
            events.append(
                await self._append_event(
                    session,
                    {
                        "type": "delta",
                        "messageId": self.run.assistant_message_id,
                        "text": content,
                    },
                )
            )
        return events

    async def _project_tool_message(
        self,
        session: AsyncSession,
        message: ToolMessage,
    ) -> list[dict[str, Any]]:
        events = await self._flush_pending_tool_calls(session)
        tool_call_id = message.tool_call_id
        invocation = self.tool_invocations.get(tool_call_id)
        if invocation is None:
            invocation = {
                "id": tool_call_id,
                "messageId": self.run.assistant_message_id,
                "toolName": message.name or "",
                "args": {},
                "status": "running",
            }
            self.tool_invocations[tool_call_id] = invocation
            self.tool_started_at[tool_call_id] = monotonic()
            await self._persist_tool_call(session, invocation)
            self.pending_tool_invocation_ids.add(tool_call_id)
            events.append(
                await self._append_event(
                    session,
                    {
                        "type": "tool_call",
                        "messageId": self.run.assistant_message_id,
                        "invocation": invocation,
                    },
                )
            )

        result = _content_text(message.content)
        completed_invocation = {
            **invocation,
            "latencyMs": max(
                0,
                int((monotonic() - self.tool_started_at.get(tool_call_id, monotonic())) * 1000),
            ),
        }
        if message.status == "error":
            completed_invocation.update({"error": result, "status": "error"})
        else:
            completed_invocation.update({"result": result, "status": "completed"})

        self.tool_invocations[tool_call_id] = completed_invocation
        await self._persist_tool_result(session, completed_invocation)
        self.pending_tool_invocation_ids.discard(tool_call_id)
        events.append(
            await self._append_event(
                session,
                {
                    "type": "tool_result",
                    "messageId": self.run.assistant_message_id,
                    "invocation": completed_invocation,
                },
            )
        )
        return events

    async def _flush_pending_tool_calls(
        self,
        session: AsyncSession,
    ) -> list[dict[str, Any]]:
        if self.pending_tool_chunk is None:
            return []

        raw_events, invocations, started_at = _tool_call_events(
            self.pending_tool_chunk,
            self.run.assistant_message_id,
        )
        self.pending_tool_chunk = None
        self.tool_invocations.update(invocations)
        self.tool_started_at.update(started_at)

        events: list[dict[str, Any]] = []
        for event in raw_events:
            invocation = event["invocation"]
            await self._persist_tool_call(session, invocation)
            self.pending_tool_invocation_ids.add(invocation["id"])
            events.append(await self._append_event(session, event))
        return events

    async def _append_event(
        self,
        session: AsyncSession,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        await append_run_event(session, self.run.id, event["type"], event)
        return event

    async def _update_assistant_message(
        self,
        session: AsyncSession,
        *,
        status: str,
    ) -> None:
        updated = await update_message(
            session=session,
            message_id=self.run.assistant_message_id,
            content="".join(self.assistant_content),
            reasoning="".join(self.assistant_reasoning),
            status=status,
        )
        if updated is None:
            raise RuntimeError(f"Assistant message not found: {self.run.assistant_message_id}")

    async def _persist_reasoning_part(
        self,
        session: AsyncSession,
        text: str,
    ) -> None:
        if (
            self.timeline_state.last_part_type == "reasoning"
            and self.timeline_state.last_part_id
        ):
            self.timeline_state.last_part_text += text
            await update_message_part_text(
                session=session,
                part_id=self.timeline_state.last_part_id,
                text=self.timeline_state.last_part_text,
            )
            return

        part = await create_message_part(
            session,
            MessagePart(
                id=str(uuid4()),
                message_id=self.run.assistant_message_id,
                type="reasoning",
                order_index=self.timeline_state.next_order_index,
                text=text,
                tool_invocation_id=None,
                created_at=self.now_factory(),
            ),
        )
        self.timeline_state.next_order_index += 1
        self.timeline_state.last_part_id = part.id
        self.timeline_state.last_part_type = "reasoning"
        self.timeline_state.last_part_text = text

    async def _persist_tool_call(
        self,
        session: AsyncSession,
        invocation: dict[str, Any],
    ) -> None:
        persisted = await create_tool_invocation(
            session,
            ToolInvocation(
                id=invocation["id"],
                message_id=invocation["messageId"],
                tool_name=invocation["toolName"],
                args=invocation.get("args") or {},
                result=None,
                error=None,
                latency_ms=None,
                status="running",
                created_at=self.now_factory(),
            ),
        )
        await create_message_part(
            session,
            MessagePart(
                id=str(uuid4()),
                message_id=persisted.message_id,
                type="tool",
                order_index=self.timeline_state.next_order_index,
                text="",
                tool_invocation_id=persisted.id,
                created_at=self.now_factory(),
            ),
        )
        self.timeline_state.next_order_index += 1
        self.timeline_state.last_part_id = None
        self.timeline_state.last_part_type = "tool"
        self.timeline_state.last_part_text = ""

    async def _persist_tool_result(
        self,
        session: AsyncSession,
        invocation: dict[str, Any],
    ) -> None:
        updated = await update_tool_invocation(
            session=session,
            invocation_id=invocation["id"],
            result=invocation.get("result"),
            error=invocation.get("error"),
            latency_ms=invocation.get("latencyMs"),
            status=invocation["status"],
        )
        if updated is None:
            raise RuntimeError(f"Tool invocation not found: {invocation['id']}")

    async def _mark_pending_tools_error(self, session: AsyncSession, error: str) -> None:
        for invocation_id in self.pending_tool_invocation_ids:
            await update_tool_invocation(
                session=session,
                invocation_id=invocation_id,
                result=None,
                error=error,
                latency_ms=None,
                status="error",
            )
        self.pending_tool_invocation_ids.clear()

    def _clear_lease(self) -> None:
        self.run.lease_owner = None
        self.run.lease_expires_at = None
        self.run.updated_at = self.now_factory()


async def project_interrupt(
    session: AsyncSession,
    run: AgentRun,
    interrupt: Interrupt,
    *,
    now: datetime,
    next_order_index: int | None = None,
) -> ApprovalProjectionResult:
    action_requests = _interrupt_action_requests(interrupt)
    existing = await get_approval_batch_by_interrupt_id(
        session,
        agent_run_id=run.id,
        interrupt_id=interrupt.id,
    )
    if existing is not None:
        return await _existing_approval_projection(session, existing)

    try:
        async with session.begin_nested():
            sequence = await next_approval_batch_sequence(session, agent_run_id=run.id)
            batch_id = f"approval-batch-{run.id}-{sequence}"
            expires_at = now + timedelta(minutes=30)
            batch = await create_approval_batch(
                session,
                ApprovalBatch(
                    id=batch_id,
                    agent_run_id=run.id,
                    assistant_message_id=run.assistant_message_id,
                    interrupt_id=interrupt.id,
                    sequence=sequence,
                    status="pending",
                    expires_at=expires_at,
                    resolution_source=None,
                    created_at=now,
                    resolved_at=None,
                ),
            )
    except IntegrityError:
        existing = await get_approval_batch_by_interrupt_id(
            session,
            agent_run_id=run.id,
            interrupt_id=interrupt.id,
        )
        if existing is None:
            raise
        return await _existing_approval_projection(session, existing)

    tool_invocations = await _pending_tool_invocations_for_interrupt(
        session,
        run=run,
        action_requests=action_requests,
    )

    requests: list[ApprovalRequest] = []
    for order_index, (action_request, invocation) in enumerate(
        zip(action_requests, tool_invocations, strict=True)
    ):
        invocation.status = "awaiting_approval"
        request = await create_approval_request(
            session,
            ApprovalRequest(
                id=f"{batch_id}-request-{order_index}",
                approval_batch_id=batch.id,
                tool_invocation_id=invocation.id,
                order_index=order_index,
                tool_name=str(action_request["name"]),
                args=dict(action_request.get("args") or {}),
                decision="pending",
                decided_at=None,
            ),
        )
        requests.append(request)

    part_order_index = (
        next_order_index
        if next_order_index is not None
        else await _next_message_part_order_index(session, run.assistant_message_id)
    )
    part = await create_message_part(
        session,
        MessagePart(
            id=f"{batch_id}-part",
            message_id=run.assistant_message_id,
            type="approval",
            order_index=part_order_index,
            text="",
            tool_invocation_id=None,
            approval_batch_id=batch.id,
            created_at=now,
        ),
    )
    run.status = "awaiting_approval"
    run.lease_owner = None
    run.lease_expires_at = None
    run.updated_at = now
    outbox = await create_outbox_event(
        session,
        OutboxEvent(
            id=f"{batch_id}-timeout",
            event_type="approval.timeout.schedule",
            aggregate_id=batch.id,
            payload={
                "batchId": batch.id,
                "runId": run.id,
                "expiresAt": _format_datetime(expires_at),
            },
            status="pending",
            attempt_count=0,
            available_at=now,
            published_at=None,
            last_error=None,
            created_at=now,
        ),
    )
    event = await append_run_event(
        session,
        run.id,
        "approval_required",
        {
            "type": "approval_required",
            "messageId": run.assistant_message_id,
            "part": _approval_part_payload(part, batch, requests),
        },
    )
    await session.flush()
    return ApprovalProjectionResult(
        batch=batch,
        requests=requests,
        part=part,
        event=event,
        outbox=outbox,
    )


async def project_stream_to_database(
    *,
    stream: AsyncIterator[object],
    run: AgentRun,
    session_factory: Callable[[], Any],
    now_factory: NowFactory = lambda: datetime.now(UTC),
    after_commit: Callable[[str], Awaitable[None]] | None = None,
    generated_title: str | Awaitable[str] | None = None,
) -> None:
    projection = StreamProjection(run=run, now_factory=now_factory)
    try:
        async for item in stream:
            if _stream_interrupt(item) is not None:
                await _project_and_commit(
                    session_factory=session_factory,
                    run=run,
                    projector=lambda session, attached_run, item=item: _project_item(
                        projection,
                        attached_run,
                        session,
                        item,
                    ),
                    after_commit=after_commit,
                )
                return
            await _project_and_commit(
                session_factory=session_factory,
                run=run,
                projector=lambda session, attached_run, item=item: _project_item(
                    projection,
                    attached_run,
                    session,
                    item,
                ),
                after_commit=after_commit,
            )
        title = await _resolve_generated_title(generated_title)
        if title is not None:
            await _project_and_commit(
                session_factory=session_factory,
                run=run,
                projector=lambda session, attached_run: _project_title(
                    projection,
                    attached_run,
                    session,
                    title,
                ),
                after_commit=after_commit,
            )
        await _project_and_commit(
            session_factory=session_factory,
            run=run,
            projector=lambda session, attached_run: _project_done(
                projection,
                attached_run,
                session,
            ),
            after_commit=after_commit,
        )
    except Exception as exc:
        await _project_and_commit(
            session_factory=session_factory,
            run=run,
            projector=lambda session, attached_run: _project_error(
                projection,
                attached_run,
                session,
                exc,
            ),
            after_commit=after_commit,
        )


async def _project_and_commit(
    *,
    session_factory: Callable[[], Any],
    run: AgentRun,
    projector: Callable[
        [AsyncSession, AgentRun],
        Awaitable[dict[str, Any] | list[dict[str, Any]]],
    ],
    after_commit: Callable[[str], Awaitable[None]] | None,
) -> None:
    async with session_factory() as session:
        try:
            attached_run = await session.get(AgentRun, run.id)
            if attached_run is None:
                raise RuntimeError(f"Agent run not found: {run.id}")
            result = await projector(session, attached_run)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    events = result if isinstance(result, list) else [result]
    if after_commit is not None:
        for event in events:
            if event:
                await after_commit(run.id)


async def _project_item(
    projection: StreamProjection,
    run: AgentRun,
    session: AsyncSession,
    item: object,
) -> list[dict[str, Any]]:
    projection.run = run
    return await projection.project_item(session, item)


async def _project_done(
    projection: StreamProjection,
    run: AgentRun,
    session: AsyncSession,
) -> dict[str, Any]:
    projection.run = run
    return await projection.project_done(session)


async def _project_error(
    projection: StreamProjection,
    run: AgentRun,
    session: AsyncSession,
    error: Exception,
) -> dict[str, Any]:
    projection.run = run
    return await projection.project_error(session, error)


async def _project_title(
    projection: StreamProjection,
    run: AgentRun,
    session: AsyncSession,
    title: str,
) -> dict[str, Any]:
    projection.run = run
    return await projection.project_title(session, title)


def _stream_interrupt(stream_item: object) -> Interrupt | None:
    payload = None
    if (
        isinstance(stream_item, tuple)
        and len(stream_item) == 2
        and stream_item[0] == "updates"
        and isinstance(stream_item[1], dict)
    ):
        payload = stream_item[1]
    elif isinstance(stream_item, dict):
        payload = stream_item

    if not isinstance(payload, dict):
        return None

    interrupts = payload.get("__interrupt__")
    if not interrupts:
        return None
    if isinstance(interrupts, Interrupt):
        return interrupts
    if isinstance(interrupts, (list, tuple)) and interrupts:
        first = interrupts[0]
        return first if isinstance(first, Interrupt) else None
    return None


def _interrupt_action_requests(interrupt: Interrupt) -> list[dict[str, Any]]:
    value = interrupt.value
    if isinstance(value, dict):
        action_requests = value.get("action_requests")
    else:
        action_requests = getattr(value, "action_requests", None)
    if not isinstance(action_requests, list) or not action_requests:
        raise RuntimeError(f"Interrupt has no action requests: {interrupt.id}")
    return [dict(action_request) for action_request in action_requests]


async def _pending_tool_invocations_for_interrupt(
    session: AsyncSession,
    *,
    run: AgentRun,
    action_requests: list[dict[str, Any]],
) -> list[ToolInvocation]:
    result = await session.execute(
        select(ToolInvocation)
        .join(
            MessagePart,
            MessagePart.tool_invocation_id == ToolInvocation.id,
        )
        .where(ToolInvocation.message_id == run.assistant_message_id)
        .where(ToolInvocation.status == "running")
        .order_by(MessagePart.order_index.asc())
    )
    available = list(result.scalars().all())
    matched: list[ToolInvocation] = []
    for action_request in action_requests:
        action_name = str(action_request["name"])
        action_args = dict(action_request.get("args") or {})
        match_index = next(
            (
                index
                for index, invocation in enumerate(available)
                if invocation.tool_name == action_name and invocation.args == action_args
            ),
            None,
        )
        if match_index is None:
            raise RuntimeError(
                "Interrupt action does not match a pending tool invocation: "
                f"{action_name} {action_args}"
            )
        matched.append(available.pop(match_index))
    return matched


async def _next_message_part_order_index(
    session: AsyncSession,
    message_id: str,
) -> int:
    result = await session.execute(
        select(MessagePart.order_index)
        .where(MessagePart.message_id == message_id)
        .order_by(MessagePart.order_index.desc())
        .limit(1)
    )
    current = result.scalar_one_or_none()
    return 0 if current is None else current + 1


async def _existing_approval_projection(
    session: AsyncSession,
    batch: ApprovalBatch,
) -> ApprovalProjectionResult:
    request_rows = await session.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.approval_batch_id == batch.id)
        .order_by(ApprovalRequest.order_index.asc())
    )
    requests = list(request_rows.scalars().all())
    part_rows = await session.execute(
        select(MessagePart).where(MessagePart.approval_batch_id == batch.id).limit(1)
    )
    part = part_rows.scalar_one()
    event_rows = await session.execute(
        select(AgentRunEvent)
        .where(AgentRunEvent.agent_run_id == batch.agent_run_id)
        .where(AgentRunEvent.event_type == "approval_required")
        .order_by(AgentRunEvent.id.desc())
    )
    event = next(
        (
            row
            for row in event_rows.scalars().all()
            if row.payload.get("part", {}).get("batch", {}).get("id") == batch.id
        ),
        None,
    )
    if event is None:
        raise RuntimeError(f"Approval event not found for batch: {batch.id}")
    outbox_rows = await session.execute(
        select(OutboxEvent)
        .where(OutboxEvent.aggregate_id == batch.id)
        .where(OutboxEvent.event_type == "approval.timeout.schedule")
        .limit(1)
    )
    outbox = outbox_rows.scalar_one()
    return ApprovalProjectionResult(
        batch=batch,
        requests=requests,
        part=part,
        event=event,
        outbox=outbox,
    )


def _approval_part_payload(
    part: MessagePart,
    batch: ApprovalBatch,
    requests: list[ApprovalRequest],
) -> dict[str, Any]:
    return {
        "id": part.id,
        "type": "approval",
        "orderIndex": part.order_index,
        "batch": {
            "id": batch.id,
            "status": batch.status,
            "expiresAt": _format_datetime(batch.expires_at),
            "requests": [
                {
                    "id": request.id,
                    "toolInvocationId": request.tool_invocation_id,
                    "toolName": request.tool_name,
                    "args": request.args,
                    "decision": request.decision,
                }
                for request in requests
            ],
        },
    }


async def _resolve_generated_title(
    generated_title: str | Awaitable[str] | None,
) -> str | None:
    if generated_title is None:
        return None
    try:
        if isawaitable(generated_title):
            return await generated_title
        return generated_title
    except Exception:
        return None
