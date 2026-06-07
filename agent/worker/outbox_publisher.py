from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from core.database import AsyncSessionLocal, engine
from core.rabbitmq import (
    RabbitMQBroker,
    connect_rabbitmq,
    declare_rabbitmq_topology,
    open_confirm_channel,
    route_for_outbox_event,
)
from model.outbox_event import OutboxEvent
from repository.outbox_event import (
    claim_pending_outbox_events,
    mark_outbox_event_published,
    mark_outbox_event_retryable,
)


class OutboxStore(Protocol):
    async def claim_pending(
        self,
        *,
        limit: int,
        now: datetime,
        lease_expires_at: datetime,
    ) -> Sequence[OutboxEvent]:
        raise NotImplementedError

    async def mark_published(
        self,
        *,
        event_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        raise NotImplementedError

    async def mark_retryable(
        self,
        *,
        event_id: str,
        error: str,
        available_at: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        raise NotImplementedError


class OutboxBroker(Protocol):
    async def publish_outbox_event(
        self,
        event: OutboxEvent,
        *,
        now: datetime,
        routing_key: str | None = None,
    ) -> None:
        raise NotImplementedError


@dataclass
class SqlAlchemyOutboxStore:
    async def claim_pending(
        self,
        *,
        limit: int,
        now: datetime,
        lease_expires_at: datetime,
    ) -> Sequence[OutboxEvent]:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                events = await claim_pending_outbox_events(
                    session,
                    limit=limit,
                    now=now,
                    lease_expires_at=lease_expires_at,
                )
            return events

    async def mark_published(
        self,
        *,
        event_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                return await mark_outbox_event_published(
                    session,
                    event_id=event_id,
                    now=now,
                    lease_expires_at=lease_expires_at,
                )

    async def mark_retryable(
        self,
        *,
        event_id: str,
        error: str,
        available_at: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                return await mark_outbox_event_retryable(
                    session,
                    event_id=event_id,
                    error=error,
                    available_at=available_at,
                    lease_expires_at=lease_expires_at,
                )


class OutboxPublisher:
    def __init__(
        self,
        *,
        store: OutboxStore,
        broker: OutboxBroker,
        now_factory: Callable[[], datetime] | None = None,
        batch_size: int = 25,
        lease_seconds: int = 30,
    ) -> None:
        self._store = store
        self._broker = broker
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds

    async def publish_pending_once(self) -> int:
        now = self._now_factory()
        events = await self._store.claim_pending(
            limit=self._batch_size,
            now=now,
            lease_expires_at=now + timedelta(seconds=self._lease_seconds),
        )
        for event in events:
            await self._publish_one(event)
        return len(events)

    async def _publish_one(self, event: OutboxEvent) -> None:
        now = self._now_factory()
        lease_expires_at = event.available_at
        route = route_for_outbox_event(event, now=now)
        try:
            await self._broker.publish_outbox_event(
                event,
                now=now,
                routing_key=route.routing_key,
            )
        except Exception as exc:
            await self._store.mark_retryable(
                event_id=event.id,
                error=str(exc),
                available_at=now + _retry_delay(event.attempt_count),
                lease_expires_at=lease_expires_at,
            )
            return
        await self._store.mark_published(
            event_id=event.id,
            now=now,
            lease_expires_at=lease_expires_at,
        )


async def run_publisher(*, poll_interval_seconds: float = 1.0) -> None:
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
        publisher = OutboxPublisher(
            store=SqlAlchemyOutboxStore(),
            broker=RabbitMQBroker(channel),
        )
        print("outbox publisher started", flush=True)
        while running:
            published = await publisher.publish_pending_once()
            if published == 0:
                await asyncio.sleep(poll_interval_seconds)
    finally:
        await connection.close()
        await engine.dispose()


def _retry_delay(attempt_count: int) -> timedelta:
    delay_seconds = min(60, 2 ** min(attempt_count, 6))
    return timedelta(seconds=delay_seconds)


def main() -> None:
    asyncio.run(run_publisher())


if __name__ == "__main__":
    main()
