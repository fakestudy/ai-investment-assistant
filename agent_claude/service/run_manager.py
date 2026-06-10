from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from core.config import get_settings
from core.database import AsyncSessionLocal
from model.agent_run import AgentRun
from model.message import Message
from repository.agent_session import delete_agent_session_by_conversation_id
from repository.agent_run import create_run, request_cancel, update_run_status
from repository.agent_run_event import (
    append_run_event as append_run_event_row,
    list_run_events_after,
)
from repository.conversation import get_conversation_by_id
from repository.message import (
    create_message,
    delete_messages_after_seq,
    get_message_in_conversation,
    get_messages_by_conversation_id,
    get_previous_user_message_before_seq,
)
from schema.chat import (
    ChatStreamEvent,
    ChatStreamEventAdapter,
    DoneEvent,
    ErrorEvent,
    MessageCreatedEvent,
    RunCreatedEvent,
    StreamChatRequest,
)
from service import (
    approval_gate,
    chat_commands,
    chat_stream,
    run_events,
    stream_persistence,
)
from service.deepseek_balance import fetch_deepseek_balance
from service.sse import to_sse


StreamExecutor = Callable[..., AsyncIterator[str]]
TaskFactory = Callable[[Awaitable[None]], asyncio.Task[None]]

SAFE_RUN_ERROR_MESSAGE = "Agent run failed. Check server logs for details."
logger = logging.getLogger(__name__)

_tasks_by_run_id: dict[str, asyncio.Task[None]] = {}
_run_id_by_assistant_message_id: dict[str, str] = {}


@dataclass(frozen=True)
class RunManagerDependencies:
    async_session_factory: Any = AsyncSessionLocal
    get_conversation_by_id: Any = get_conversation_by_id
    create_message: Any = create_message
    get_message_in_conversation: Any = get_message_in_conversation
    get_previous_user_message_before_seq: Any = get_previous_user_message_before_seq
    get_messages_by_conversation_id: Any = get_messages_by_conversation_id
    delete_messages_after_seq: Any = delete_messages_after_seq
    delete_agent_session_by_conversation_id: Any = delete_agent_session_by_conversation_id
    create_run: Any = create_run
    request_cancel: Any = request_cancel
    update_run_status: Any = update_run_status
    append_run_event_row: Any = append_run_event_row
    list_run_events_after: Any = list_run_events_after
    append_run_event: Any = run_events.append_run_event
    stream_run_events: Any = run_events.stream_run_events
    stream_executor: StreamExecutor = chat_stream.stream_chat
    fetch_deepseek_balance: Any = fetch_deepseek_balance
    create_task: TaskFactory = asyncio.create_task
    notify_run_event: Any = run_events.notify_run_event


def start_chat_run(
    req: StreamChatRequest,
    *,
    dependencies: RunManagerDependencies | None = None,
) -> AsyncIterator[str]:
    deps = dependencies or RunManagerDependencies()
    return _start_and_stream(req, deps)


async def _start_and_stream(
    req: StreamChatRequest,
    deps: RunManagerDependencies,
) -> AsyncIterator[str]:
    prepared = await _prepare_run(req, deps)
    if isinstance(prepared, _PrepareError):
        yield to_sse(
            ErrorEvent(
                type="error",
                message_id=None,
                message=prepared.message,
            )
        )
        return

    task = deps.create_task(_execute_run(prepared, req, deps))
    _register_run_task(prepared, task)

    async for frame in deps.stream_run_events(
        prepared.run_id,
        0,
    ):
        yield frame


@dataclass(frozen=True)
class _PreparedRun:
    run_id: str
    conversation_id: str
    assistant_message_id: str
    executor_message: str = ""
    executor_prompt: str | None = None
    resume_sdk_session: bool = True


@dataclass(frozen=True)
class _PrepareError:
    message: str


async def _prepare_run(
    req: StreamChatRequest,
    deps: RunManagerDependencies,
) -> _PreparedRun | _PrepareError:
    now = datetime.now(UTC)
    assistant_message = Message(
        id=str(uuid4()),
        conversation_id=req.conversation_id,
        role="assistant",
        content="",
        reasoning="",
        status="streaming",
        created_at=now,
    )
    run = AgentRun(
        id=str(uuid4()),
        conversation_id=req.conversation_id,
        assistant_message_id=assistant_message.id,
        status="running",
        created_at=now,
        updated_at=now,
    )

    async with deps.async_session_factory() as session:
        conversation = await deps.get_conversation_by_id(
            session,
            req.conversation_id,
        )
        if conversation is None:
            return _PrepareError("Conversation not found")

        if req.parent_message_id and req.regenerate_from_message_id:
            return _PrepareError(
                "Specify only one of parentMessageId or regenerateFromMessageId"
            )

        executor_message = req.message
        executor_prompt: str | None = None
        resume_sdk_session = True

        if req.parent_message_id:
            parent_message = await deps.get_message_in_conversation(
                session,
                conversation_id=req.conversation_id,
                message_id=req.parent_message_id,
            )
            if parent_message is None:
                return _PrepareError("Parent message not found")
            if parent_message.role != "user":
                return _PrepareError("parentMessageId must reference a user message")

            previous_messages = await _get_messages_before_seq(
                session,
                deps,
                conversation_id=req.conversation_id,
                seq=parent_message.seq,
            )
            await deps.delete_messages_after_seq(
                session,
                conversation_id=req.conversation_id,
                seq=parent_message.seq,
            )
            await deps.delete_agent_session_by_conversation_id(
                session,
                req.conversation_id,
            )
            executor_message = parent_message.content
            executor_prompt = _build_branch_restart_prompt(
                previous_messages,
                current_user_request=parent_message.content,
            )
            resume_sdk_session = False
        elif req.regenerate_from_message_id:
            target_message = await deps.get_message_in_conversation(
                session,
                conversation_id=req.conversation_id,
                message_id=req.regenerate_from_message_id,
            )
            if target_message is None:
                return _PrepareError("Message to regenerate was not found")
            if target_message.role != "assistant":
                return _PrepareError(
                    "regenerateFromMessageId must reference an assistant message"
                )

            previous_user_message = await deps.get_previous_user_message_before_seq(
                session,
                conversation_id=req.conversation_id,
                seq=target_message.seq,
            )
            if previous_user_message is None:
                return _PrepareError("No previous user message found for regeneration")

            previous_messages = await _get_messages_before_seq(
                session,
                deps,
                conversation_id=req.conversation_id,
                seq=previous_user_message.seq,
            )
            await deps.delete_messages_after_seq(
                session,
                conversation_id=req.conversation_id,
                seq=target_message.seq - 1,
            )
            await deps.delete_agent_session_by_conversation_id(
                session,
                req.conversation_id,
            )
            executor_message = previous_user_message.content
            executor_prompt = _build_branch_restart_prompt(
                previous_messages,
                current_user_request=previous_user_message.content,
            )
            resume_sdk_session = False
        else:
            user_message = Message(
                id=str(uuid4()),
                conversation_id=req.conversation_id,
                role="user",
                content=req.message,
                reasoning="",
                status="done",
                created_at=now,
            )
            await deps.create_message(session, user_message)

        assistant_message = await deps.create_message(session, assistant_message)
        await deps.create_run(session, run=run)
        await session.commit()

    await deps.append_run_event(
        run_id=run.id,
        conversation_id=req.conversation_id,
        message_id=assistant_message.id,
        event=RunCreatedEvent(
            type="run_created",
            run_id=run.id,
            conversation_id=req.conversation_id,
            assistant_message_id=assistant_message.id,
            status="running",
        ),
    )
    await deps.append_run_event(
        run_id=run.id,
        conversation_id=req.conversation_id,
        message_id=assistant_message.id,
        event=MessageCreatedEvent(
            type="message_created",
            run_id=run.id,
            message=stream_persistence.project_stream_message(assistant_message),
        ),
    )
    return _PreparedRun(
        run_id=run.id,
        conversation_id=req.conversation_id,
        assistant_message_id=assistant_message.id,
        executor_message=executor_message,
        executor_prompt=executor_prompt,
        resume_sdk_session=resume_sdk_session,
    )


def _register_run_task(
    prepared: _PreparedRun,
    task: asyncio.Task[None],
) -> None:
    _tasks_by_run_id[prepared.run_id] = task
    _run_id_by_assistant_message_id[prepared.assistant_message_id] = prepared.run_id

    def cleanup(_task: asyncio.Task[None]) -> None:
        _tasks_by_run_id.pop(prepared.run_id, None)
        if (
            _run_id_by_assistant_message_id.get(prepared.assistant_message_id)
            == prepared.run_id
        ):
            _run_id_by_assistant_message_id.pop(prepared.assistant_message_id, None)

    task.add_done_callback(cleanup)


async def cancel_run_by_assistant_message_id(
    message_id: str,
    *,
    dependencies: RunManagerDependencies | None = None,
) -> AgentRun | None:
    deps = dependencies or RunManagerDependencies()

    async with deps.async_session_factory() as session:
        run = await deps.request_cancel(
            session,
            assistant_message_id=message_id,
        )
        if run is None:
            return None

        task = _tasks_by_run_id.get(run.id)
        if task is not None and not task.done():
            task.cancel()

        await _persist_cancelled_assistant_message(
            session,
            run=run,
            message_id=message_id,
            deps=deps,
        )
        await deps.update_run_status(
            session,
            run_id=run.id,
            status="completed",
        )
        row = run_events.build_run_event_row(
            run_id=run.id,
            conversation_id=run.conversation_id,
            message_id=message_id,
            event=DoneEvent(
                type="done",
                run_id=run.id,
                message_id=message_id,
            ),
        )
        persisted = await deps.append_run_event_row(session, event=row)
        persisted_event_id = int(persisted.id)
        await session.commit()

    deps.notify_run_event(run.id, persisted_event_id)
    return run


async def _persist_cancelled_assistant_message(
    session: Any,
    *,
    run: AgentRun,
    message_id: str,
    deps: RunManagerDependencies,
) -> None:
    message = await session.get(Message, message_id)
    if message is None:
        raise LookupError(f"Message not found: {message_id}")
    events = await deps.list_run_events_after(
        session,
        run_id=run.id,
        after_event_id=0,
    )
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    for event in events:
        payload = getattr(event, "payload", {}) or {}
        if payload.get("messageId") != message_id:
            continue
        event_type = payload.get("type") or getattr(event, "event_type", None)
        if event_type == "delta":
            content_parts.append(payload.get("text", ""))
        elif event_type == "reasoning":
            reasoning_parts.append(payload.get("text", ""))
    if content_parts:
        message.content = "".join(content_parts)
    if reasoning_parts:
        message.reasoning = "".join(reasoning_parts)
    message.status = "done"


async def _get_messages_before_seq(
    session: Any,
    deps: RunManagerDependencies,
    *,
    conversation_id: str,
    seq: int,
) -> list[Message]:
    messages = await deps.get_messages_by_conversation_id(session, conversation_id)
    return [
        message
        for message in sorted(messages, key=lambda row: row.seq)
        if message.conversation_id == conversation_id and message.seq < seq
    ]


def _build_branch_restart_prompt(
    previous_messages: list[Message],
    *,
    current_user_request: str,
) -> str:
    lines: list[str] = []
    for message in sorted(previous_messages, key=lambda row: row.seq):
        if message.role == "user":
            role = "User"
        elif message.role == "assistant":
            role = "Assistant"
        else:
            continue
        if message.content:
            lines.append(f"{role}: {message.content}")

    current_section = f"Current user request:\n{current_user_request}"
    if not lines:
        return current_section
    return "Previous conversation:\n" + "\n".join(lines) + "\n\n" + current_section


async def _execute_run(
    prepared: _PreparedRun,
    req: StreamChatRequest,
    deps: RunManagerDependencies,
) -> None:
    if chat_commands.is_get_balance_command(prepared.executor_message or req.message):
        await _execute_get_balance_command(prepared, deps)
        return

    settings = get_settings()
    can_use_tool = approval_gate.build_can_use_tool(
        approval_gate.RunApprovalContext(
            run_id=prepared.run_id,
            conversation_id=prepared.conversation_id,
            message_id=prepared.assistant_message_id,
            approval_required_tools=settings.approval_required_tools,
        )
    )
    try:
        async for frame in deps.stream_executor(
            conversation_id=req.conversation_id,
            message=prepared.executor_message or req.message,
            generate_title=req.generate_title,
            parent_message_id=req.parent_message_id,
            regenerate_from_message_id=req.regenerate_from_message_id,
            precreated_assistant_message_id=prepared.assistant_message_id,
            create_user_message=False,
            emit_message_created=False,
            executor_prompt=prepared.executor_prompt,
            resume_sdk_session=prepared.resume_sdk_session,
            can_use_tool=can_use_tool,
        ):
            event = _event_from_sse(frame, run_id=prepared.run_id)
            if event.type == "done":
                await _append_terminal_event_and_set_status(
                    prepared,
                    deps,
                    event,
                    status="completed",
                )
                return
            if event.type == "error":
                await _append_terminal_event_and_set_status(
                    prepared,
                    deps,
                    event,
                    status="failed",
                    error=getattr(event, "message", None),
                )
                return
            await deps.append_run_event(
                run_id=prepared.run_id,
                conversation_id=prepared.conversation_id,
                message_id=_event_message_id(event) or prepared.assistant_message_id,
                event=event,
            )
        await _append_terminal_event_and_set_status(
            prepared,
            deps,
            DoneEvent(
                type="done",
                run_id=prepared.run_id,
                message_id=prepared.assistant_message_id,
            ),
            status="completed",
        )
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("Agent run failed")
        event = ErrorEvent(
            type="error",
            run_id=prepared.run_id,
            message_id=prepared.assistant_message_id,
            message=SAFE_RUN_ERROR_MESSAGE,
        )
        await _append_terminal_event_and_set_status(
            prepared,
            deps,
            event,
            status="failed",
            error=event.message,
            message_status="error",
        )


async def _execute_get_balance_command(
    prepared: _PreparedRun,
    deps: RunManagerDependencies,
) -> None:
    async for event in chat_commands.stream_get_balance_command(
        message_id=prepared.assistant_message_id,
        fetch_balance=deps.fetch_deepseek_balance,
        async_session_factory=deps.async_session_factory,
    ):
        if event.type == "done":
            await _append_terminal_event_and_set_status(
                prepared,
                deps,
                event,
                status="completed",
            )
            return
        await deps.append_run_event(
            run_id=prepared.run_id,
            conversation_id=prepared.conversation_id,
            message_id=_event_message_id(event) or prepared.assistant_message_id,
            event=event,
        )


async def _append_terminal_event_and_set_status(
    prepared: _PreparedRun,
    deps: RunManagerDependencies,
    event: ChatStreamEvent,
    *,
    status: str,
    error: str | None = None,
    message_status: str | None = None,
) -> None:
    async with deps.async_session_factory() as session:
        if message_status is not None:
            message = await session.get(Message, prepared.assistant_message_id)
            if message is not None:
                message.status = message_status
        await deps.update_run_status(
            session,
            run_id=prepared.run_id,
            status=status,
            error=error,
        )
        row = run_events.build_run_event_row(
            run_id=prepared.run_id,
            conversation_id=prepared.conversation_id,
            message_id=_event_message_id(event) or prepared.assistant_message_id,
            event=event,
        )
        persisted = await deps.append_run_event_row(session, event=row)
        await session.commit()
    deps.notify_run_event(prepared.run_id, int(persisted.id))


def _event_from_sse(frame: str, *, run_id: str) -> ChatStreamEvent:
    data_lines = [
        line.removeprefix("data: ")
        for line in frame.splitlines()
        if line.startswith("data: ")
    ]
    if not data_lines:
        raise ValueError("SSE frame does not contain data")
    payload = json.loads("\n".join(data_lines))
    payload.setdefault("runId", run_id)
    event = ChatStreamEventAdapter.validate_python(payload)
    if getattr(event, "run_id", None) is None:
        return event.model_copy(update={"run_id": run_id})
    return event


def _event_message_id(event: ChatStreamEvent) -> str | None:
    message_id = getattr(event, "message_id", None)
    if message_id is not None:
        return message_id
    message = getattr(event, "message", None)
    if message is not None:
        return getattr(message, "id", None)
    return None
