from __future__ import annotations

import asyncio
import json
import logging
import signal
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy.exc import SQLAlchemyError

from core.database import AsyncSessionLocal, engine
from core.rabbitmq import (
    AGENT_RUN_COMMANDS_QUEUE,
    APPROVAL_TIMEOUT_READY_QUEUE,
    APPROVAL_TIMEOUT_READY_ROUTING_KEY,
    APPROVAL_TIMEOUT_SCHEDULE_ROUTING_KEY,
    connect_rabbitmq,
    declare_rabbitmq_topology,
    open_confirm_channel,
)
from service.approval import expire_approval_batch
from worker.run_executor import (
    AgentRunCommand,
    AgentRunCommandRetry,
    RunExecutor,
    create_default_run_executor,
)

logger = logging.getLogger(__name__)

ExpireApprovalBatch = Callable[..., Awaitable[object]]
SessionFactory = Callable[[], Any]
NowFactory = Callable[[], datetime]


class IncomingCommandMessage(Protocol):
    message_id: str | None
    type: str | None
    body: bytes

    async def ack(self) -> None:
        raise NotImplementedError

    async def nack(self, *, requeue: bool = True) -> None:
        raise NotImplementedError


class CommandConsumer:
    def __init__(
        self,
        *,
        executor: RunExecutor,
        expire_approval_batch: ExpireApprovalBatch,
        session_factory: SessionFactory | None = None,
        now_factory: NowFactory | None = None,
    ) -> None:
        self._executor = executor
        self._expire_approval_batch = expire_approval_batch
        self._session_factory = session_factory
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    async def handle_message(self, message: IncomingCommandMessage) -> None:
        try:
            await self._dispatch(message)
        except _TemporaryConsumerError as exc:
            logger.info("temporary command failure: %s", exc)
            await message.nack(requeue=True)
            return
        except _PoisonMessageError as exc:
            logger.info("poison command message acked: %s", exc)
            await message.ack()
            return
        except _NackWithoutRequeue:
            await message.nack(requeue=False)
            return
        await message.ack()

    async def _dispatch(self, message: IncomingCommandMessage) -> None:
        message_type = message.type
        payload = _decode_payload(message.body)
        message_id = message.message_id or ""
        try:
            if message_type == "agent.run.start":
                await self._executor.execute_start(
                    AgentRunCommand.from_payload(message_id, payload)
                )
                return
            if message_type == "agent.run.resume":
                await self._executor.execute_resume(
                    AgentRunCommand.from_payload(message_id, payload)
                )
                return
            if message_type in {
                APPROVAL_TIMEOUT_READY_ROUTING_KEY,
                APPROVAL_TIMEOUT_SCHEDULE_ROUTING_KEY,
            }:
                result = await self._handle_timeout_ready(payload)
                if getattr(result, "action", None) == "rescheduled":
                    raise _NackWithoutRequeue
                return
        except AgentRunCommandRetry as exc:
            raise _TemporaryConsumerError(str(exc)) from exc
        except (ConnectionError, OSError, SQLAlchemyError) as exc:
            raise _TemporaryConsumerError(str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise _PoisonMessageError(str(exc)) from exc
        raise _PoisonMessageError(f"unsupported command type: {message_type}")

    async def _handle_timeout_ready(self, payload: dict[str, Any]) -> object:
        batch_id = payload["batchId"]
        now = self._now_factory()
        if self._session_factory is None:
            return await self._expire_approval_batch(None, batch_id, now=now)

        session_context = self._session_factory()
        if not hasattr(session_context, "__aenter__"):
            return await self._expire_approval_batch(session_context, batch_id, now=now)

        async with session_context as session:
            try:
                result = await self._expire_approval_batch(session, batch_id, now=now)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise


async def run_consumer() -> None:
    connection = await connect_rabbitmq()
    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        channel = await open_confirm_channel(connection)
        await declare_rabbitmq_topology(channel)
        await channel.set_qos(prefetch_count=10)
        consumer = CommandConsumer(
            executor=create_default_run_executor(),
            expire_approval_batch=expire_approval_batch,
            session_factory=AsyncSessionLocal,
        )
        run_queue = await channel.get_queue(AGENT_RUN_COMMANDS_QUEUE)
        timeout_queue = await channel.get_queue(APPROVAL_TIMEOUT_READY_QUEUE)
        await run_queue.consume(_consumer_callback(consumer))
        await timeout_queue.consume(_consumer_callback(consumer))
        print("agent command consumer started", flush=True)
        while running:
            await asyncio.sleep(1)
    finally:
        await connection.close()
        await engine.dispose()


def _consumer_callback(
    consumer: CommandConsumer,
) -> Callable[[AbstractIncomingMessage], Awaitable[None]]:
    async def callback(message: AbstractIncomingMessage) -> None:
        await consumer.handle_message(message)

    return callback


def _decode_payload(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _PoisonMessageError(str(exc)) from exc
    if not isinstance(payload, dict):
        raise _PoisonMessageError("payload must be a JSON object")
    return payload


class _TemporaryConsumerError(Exception):
    pass


class _PoisonMessageError(Exception):
    pass


class _NackWithoutRequeue(Exception):
    pass


def main() -> None:
    asyncio.run(run_consumer())


if __name__ == "__main__":
    main()
