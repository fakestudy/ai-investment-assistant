from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from model.agent_run import AgentRun
from model.message import Message
from model.outbox_event import OutboxEvent
from repository.agent_run import create_agent_run, get_active_run_by_conversation_id
from repository.message import create_message
from repository.outbox_event import create_outbox_event
from schema.chat import ChatStreamRequest
from service.run_events import append_run_event


class ConversationRunConflict(Exception):
    pass


class OutboxRepository(Protocol):
    async def create(
        self,
        session: AsyncSession,
        outbox_event: OutboxEvent,
    ) -> OutboxEvent:
        pass


@dataclass(frozen=True)
class ChatRunCreation:
    user_message: Message
    assistant_message: Message
    run: AgentRun
    outbox: OutboxEvent


class _DefaultOutboxRepository:
    async def create(
        self,
        session: AsyncSession,
        outbox_event: OutboxEvent,
    ) -> OutboxEvent:
        return await create_outbox_event(session, outbox_event)


async def create_chat_run(
    session: AsyncSession,
    request: ChatStreamRequest,
    *,
    id_factory: Callable[[], str] = lambda: str(uuid4()),
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC),
    outbox_repository: OutboxRepository | None = None,
) -> ChatRunCreation:
    active_run = await get_active_run_by_conversation_id(
        session,
        conversation_id=request.conversation_id,
    )
    if active_run is not None:
        raise ConversationRunConflict(request.conversation_id)

    now = now_factory()
    user_message_id = id_factory()
    assistant_message_id = id_factory()
    run_id = id_factory()
    outbox_id = id_factory()

    user_message = Message(
        id=user_message_id,
        conversation_id=request.conversation_id,
        role="user",
        content=request.message,
        reasoning="",
        status="done",
        created_at=now,
    )
    assistant_message = Message(
        id=assistant_message_id,
        conversation_id=request.conversation_id,
        role="assistant",
        content="",
        reasoning="",
        status="streaming",
        created_at=now,
    )
    run = AgentRun(
        id=run_id,
        conversation_id=request.conversation_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        status="queued",
        version=0,
        lease_owner=None,
        lease_expires_at=None,
        active_command_id=None,
        error=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )
    outbox = OutboxEvent(
        id=outbox_id,
        event_type="agent.run.start",
        aggregate_id=run_id,
        payload=_start_command_payload(run_id, generate_title=request.generate_title),
        status="pending",
        attempt_count=0,
        available_at=now,
        published_at=None,
        last_error=None,
        created_at=now,
    )

    try:
        await create_message(session, user_message)
        await create_message(session, assistant_message)
        await create_agent_run(session, run)
        outbox_repo = outbox_repository or _DefaultOutboxRepository()
        persisted_outbox = await outbox_repo.create(session, outbox)
        await append_run_event(
            session,
            run_id,
            "run_created",
            {
                "type": "run_created",
                "runId": run_id,
                "status": "queued",
                "assistantMessageId": assistant_message_id,
            },
        )
        await append_run_event(
            session,
            run_id,
            "message_created",
            {
                "type": "message_created",
                "message": {
                    "id": assistant_message.id,
                    "conversationId": assistant_message.conversation_id,
                    "role": assistant_message.role,
                    "content": assistant_message.content,
                    "status": assistant_message.status,
                    "createdAt": assistant_message.created_at.astimezone(UTC)
                    .isoformat()
                    .replace("+00:00", "Z"),
                },
            },
        )
    except IntegrityError as exc:
        if "uq_agent_runs_active_conversation" in str(exc.orig):
            raise ConversationRunConflict(request.conversation_id) from exc
        raise

    return ChatRunCreation(
        user_message=user_message,
        assistant_message=assistant_message,
        run=run,
        outbox=persisted_outbox,
    )


def _start_command_payload(run_id: str, *, generate_title: bool) -> dict[str, object]:
    payload: dict[str, object] = {"runId": run_id}
    if generate_title:
        payload["generateTitle"] = True
    return payload
