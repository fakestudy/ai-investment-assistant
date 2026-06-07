from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from inspect import isawaitable
from typing import Any, Literal

from langchain_core.messages import AIMessageChunk, ToolMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from model.agent_run import AgentRun
from model.message import Message
from repository.message import get_messages_by_conversation_id
from service.agent_factory import build_agent
from service.chat import _reasoning_text, _stream_message, get_conversation_title
from service.stream_projection import project_stream_to_database


@dataclass(frozen=True)
class AgentRunCommand:
    id: str
    run_id: str
    generate_title: bool = False

    @classmethod
    def from_payload(cls, command_id: str, payload: dict[str, Any]) -> "AgentRunCommand":
        return cls(
            id=command_id,
            run_id=str(payload["runId"]),
            generate_title=bool(payload.get("generateTitle", False)),
        )


@dataclass(frozen=True)
class ClaimResult:
    claimed: bool
    run: AgentRun | None = None
    action: Literal["execute", "ack", "retry"] = "retry"


class AgentRunCommandRetry(Exception):
    pass


MessageLoader = Callable[[str], list[dict[str, str]] | Awaitable[list[dict[str, str]]]]
CommitEvent = Callable[[str], Awaitable[None]]
NotifyRunEvents = Callable[[str], Awaitable[None]]
NowFactory = Callable[[], datetime]
TitleGenerator = Callable[[list[dict[str, str]]], str]


class RunExecutor:
    def __init__(
        self,
        *,
        agent: Any | None = None,
        session_factory: Callable[[], Any] | None = None,
        worker_id: str = "local-worker",
        lease_seconds: int = 60,
        load_messages: MessageLoader | None = None,
        commit_event: CommitEvent | None = None,
        notify_run_events: NotifyRunEvents | None = None,
        title_generator: TitleGenerator | None = None,
        now_factory: NowFactory = lambda: datetime.now(UTC),
    ) -> None:
        self.agent = agent or build_agent()
        self.session_factory = session_factory
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.load_messages = load_messages
        self.commit_event = commit_event
        self.notify_run_events = notify_run_events
        self.title_generator = title_generator or _default_title_generator
        self.now_factory = now_factory

    async def execute_start(self, command: AgentRunCommand) -> None:
        claim = await self._claim_start(command)
        if claim.action == "retry" and self.session_factory is not None:
            raise AgentRunCommandRetry(command.run_id)
        if claim.action == "ack" and self.session_factory is not None:
            return
        run = claim.run

        messages = await self._load_messages(command.run_id)
        title_task = self._start_title_generation(messages, command=command)
        stream = self.agent.astream(
            {"messages": messages},
            config={"configurable": {"thread_id": command.run_id}},
            stream_mode=["messages", "updates"],
        )

        if self.commit_event is not None:
            await self._project_with_injected_commit(
                command.run_id,
                stream,
                title_task=title_task,
            )
            return

        if self.session_factory is None or run is None:
            async for _ in stream:
                pass
            return

        await project_stream_to_database(
            stream=stream,
            run=run,
            session_factory=self.session_factory,
            now_factory=self.now_factory,
            after_commit=self.notify_run_events,
            generated_title=title_task,
        )

    def _start_title_generation(
        self,
        messages: list[dict[str, str]],
        *,
        command: AgentRunCommand,
    ) -> asyncio.Task[str] | None:
        if not command.generate_title:
            return None
        return asyncio.create_task(asyncio.to_thread(self.title_generator, messages))

    async def _claim_start(self, command: AgentRunCommand) -> ClaimResult:
        if self.session_factory is None:
            return ClaimResult(claimed=True, action="execute")

        async with self.session_factory() as session:
            try:
                result = await claim_start_command(
                    session,
                    command=command,
                    worker_id=self.worker_id,
                    lease_seconds=self.lease_seconds,
                    now=self.now_factory(),
                )
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

    async def _load_messages(self, run_id: str) -> list[dict[str, str]]:
        if self.load_messages is not None:
            result = self.load_messages(run_id)
            if isawaitable(result):
                return await result  # type: ignore[misc]
            return result

        if self.session_factory is None:
            return []

        async with self.session_factory() as session:
            return await load_run_messages(session, run_id=run_id)

    async def _project_with_injected_commit(
        self,
        run_id: str,
        stream: Any,
        *,
        title_task: Awaitable[str] | None,
    ) -> None:
        async for item in stream:
            event_types = projected_event_types(item)
            for event_type in event_types:
                await self.commit_event(event_type)
                if self.notify_run_events is not None:
                    await self.notify_run_events(run_id)
        if title_task is not None and await title_task:
            await self.commit_event("title")
            if self.notify_run_events is not None:
                await self.notify_run_events(run_id)


async def claim_start_command(
    session: AsyncSession,
    *,
    command: AgentRunCommand,
    worker_id: str,
    lease_seconds: int,
    now: datetime,
) -> ClaimResult:
    result = await session.execute(
        select(AgentRun).where(AgentRun.id == command.run_id).with_for_update()
    )
    run = result.scalar_one_or_none()
    if run is None:
        return ClaimResult(claimed=False, action="ack")

    if run.status == "queued":
        _claim_run(
            run,
            command=command,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            now=now,
        )
        return ClaimResult(claimed=True, run=run, action="execute")

    lease_valid = run.lease_expires_at is not None and run.lease_expires_at > now
    if run.active_command_id == command.id and lease_valid:
        return ClaimResult(claimed=False, run=run, action="ack")

    if run.status == "running" and not lease_valid:
        _claim_run(
            run,
            command=command,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            now=now,
        )
        return ClaimResult(claimed=True, run=run, action="execute")

    if run.active_command_id == command.id and run.status in {"completed", "failed"}:
        return ClaimResult(claimed=False, run=run, action="ack")

    return ClaimResult(claimed=False, run=run, action="retry")


async def load_run_messages(
    session: AsyncSession,
    *,
    run_id: str,
) -> list[dict[str, str]]:
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise RuntimeError(f"Agent run not found: {run_id}")

    messages = await get_messages_by_conversation_id(
        session,
        conversation_id=run.conversation_id,
    )
    return _build_agent_messages(messages, current_user_message_id=run.user_message_id)


def create_default_run_executor(
    *,
    agent: Any | None = None,
    worker_id: str = "local-worker",
    lease_seconds: int = 60,
) -> RunExecutor:
    return RunExecutor(
        agent=agent,
        session_factory=AsyncSessionLocal,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )


def projected_event_types(stream_item: object) -> list[str]:
    message = _stream_message(stream_item)
    if isinstance(message, AIMessageChunk):
        if getattr(message, "content", ""):
            return ["delta"]
        if (
            getattr(message, "tool_call_chunks", None)
            and message.response_metadata.get("finish_reason") == "tool_calls"
        ):
            return ["tool_call"]
        if _reasoning_text(message):
            return ["reasoning"]
    if isinstance(message, ToolMessage):
        return ["tool_result"]
    return []


def _default_title_generator(messages: list[dict[str, str]]) -> str:
    prompt = next(
        (
            message["content"]
            for message in reversed(messages)
            if message.get("role") == "user"
        ),
        "",
    )
    return get_conversation_title(prompt)


def _claim_run(
    run: AgentRun,
    *,
    command: AgentRunCommand,
    worker_id: str,
    lease_seconds: int,
    now: datetime,
) -> None:
    run.status = "running"
    run.active_command_id = command.id
    run.lease_owner = worker_id
    run.lease_expires_at = now + timedelta(seconds=lease_seconds)
    run.version += 1
    run.updated_at = now


def _build_agent_messages(
    messages: list[Message],
    *,
    current_user_message_id: str,
) -> list[dict[str, str]]:
    built: list[dict[str, str]] = []
    for message in messages:
        if message.id == current_user_message_id:
            built.append({"role": "user", "content": message.content})
            break
        if message.status == "done" and message.role in {"user", "assistant"}:
            built.append({"role": message.role, "content": message.content})
    return built
