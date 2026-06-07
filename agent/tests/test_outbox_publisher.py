import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import delete

from core.database import AsyncSessionLocal, engine
from model.outbox_event import OutboxEvent
from repository.outbox_event import (
    mark_outbox_event_published,
    mark_outbox_event_retryable,
)
from worker.outbox_publisher import OutboxPublisher


class FakeOutboxStore:
    def __init__(self, events: list[OutboxEvent]) -> None:
        self.events = {event.id: event for event in events}
        self.race_before_mark_published = None
        self.race_before_mark_retryable = None

    async def claim_pending(
        self,
        *,
        limit: int,
        now: datetime,
        lease_expires_at: datetime,
    ) -> list[OutboxEvent]:
        claimed: list[OutboxEvent] = []
        for event in self.events.values():
            if event.status == "pending" and event.available_at <= now:
                event.status = "publishing"
                event.available_at = lease_expires_at
                claimed.append(event)
            elif event.status == "publishing" and event.available_at <= now:
                event.available_at = lease_expires_at
                claimed.append(event)
            if len(claimed) == limit:
                break
        return claimed

    async def mark_published(
        self,
        *,
        event_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        if self.race_before_mark_published is not None:
            self.race_before_mark_published()
        event = self.events[event_id]
        if event.status != "publishing" or event.available_at != lease_expires_at:
            return False
        event.status = "published"
        event.published_at = now
        event.last_error = None
        return True

    async def mark_retryable(
        self,
        *,
        event_id: str,
        error: str,
        available_at: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        if self.race_before_mark_retryable is not None:
            self.race_before_mark_retryable()
        event = self.events[event_id]
        if event.status != "publishing" or event.available_at != lease_expires_at:
            return False
        event.status = "pending"
        event.attempt_count += 1
        event.available_at = available_at
        event.last_error = error
        return True


class FakeBroker:
    def __init__(self) -> None:
        self.raise_on_publish: Exception | None = None
        self.published: list[SimpleNamespace] = []
        self.confirmed_message_id: str | None = None

    async def publish_outbox_event(
        self,
        event: OutboxEvent,
        *,
        now: datetime,
        routing_key: str | None = None,
    ) -> None:
        if self.raise_on_publish is not None:
            raise self.raise_on_publish
        self.confirmed_message_id = event.id
        self.published.append(
            SimpleNamespace(
                message_id=event.id,
                event_type=event.event_type,
                payload=event.payload,
                routing_key=routing_key or event.event_type,
                now=now,
            )
        )


class OutboxPublisherTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        asyncio.run(engine.dispose())

    def test_marks_published_only_after_broker_confirm(self) -> None:
        asyncio.run(self._test_marks_published_only_after_broker_confirm())

    def test_publish_failure_keeps_event_retryable(self) -> None:
        asyncio.run(self._test_publish_failure_keeps_event_retryable())

    def test_expired_timeout_command_routes_directly_to_ready_queue(self) -> None:
        asyncio.run(
            self._test_expired_timeout_command_routes_directly_to_ready_queue()
        )

    def test_crash_after_claim_is_recovered_after_lease_expires(self) -> None:
        asyncio.run(self._test_crash_after_claim_is_recovered_after_lease_expires())

    def test_stale_failure_does_not_overwrite_newer_published_state(self) -> None:
        asyncio.run(
            self._test_stale_failure_does_not_overwrite_newer_published_state()
        )

    def test_stale_success_does_not_overwrite_newer_publishing_lease(self) -> None:
        asyncio.run(
            self._test_stale_success_does_not_overwrite_newer_publishing_lease()
        )

    def test_db_stale_success_does_not_overwrite_newer_publishing_lease(self) -> None:
        asyncio.run(
            self._test_db_stale_success_does_not_overwrite_newer_publishing_lease()
        )

    def test_db_stale_failure_does_not_overwrite_newer_published_state(self) -> None:
        asyncio.run(
            self._test_db_stale_failure_does_not_overwrite_newer_published_state()
        )

    async def _test_marks_published_only_after_broker_confirm(self) -> None:
        now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
        outbox = self._event(
            event_id="outbox-start-1",
            event_type="agent.run.start",
            now=now,
        )
        store = FakeOutboxStore([outbox])
        broker = FakeBroker()
        publisher = OutboxPublisher(
            store=store,
            broker=broker,
            now_factory=lambda: now,
        )

        await publisher.publish_pending_once()

        refreshed = store.events[outbox.id]
        self.assertEqual(broker.confirmed_message_id, outbox.id)
        self.assertEqual(refreshed.status, "published")
        self.assertEqual(refreshed.published_at, now)

    async def _test_publish_failure_keeps_event_retryable(self) -> None:
        now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
        outbox = self._event(
            event_id="outbox-start-retry",
            event_type="agent.run.start",
            now=now,
        )
        store = FakeOutboxStore([outbox])
        broker = FakeBroker()
        broker.raise_on_publish = RuntimeError("down")
        publisher = OutboxPublisher(
            store=store,
            broker=broker,
            now_factory=lambda: now,
        )

        await publisher.publish_pending_once()

        refreshed = store.events[outbox.id]
        self.assertEqual(refreshed.status, "pending")
        self.assertEqual(refreshed.attempt_count, 1)
        self.assertEqual(refreshed.last_error, "down")
        self.assertEqual(refreshed.available_at, now + timedelta(seconds=1))

    async def _test_expired_timeout_command_routes_directly_to_ready_queue(
        self,
    ) -> None:
        from core.rabbitmq import APPROVAL_TIMEOUT_READY_ROUTING_KEY

        now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
        outbox = self._event(
            event_id="outbox-timeout-expired",
            event_type="approval.timeout.schedule",
            now=now,
            payload={"batchId": "batch-1", "expiresAt": "2026-06-07T09:59:59Z"},
        )
        store = FakeOutboxStore([outbox])
        broker = FakeBroker()
        publisher = OutboxPublisher(
            store=store,
            broker=broker,
            now_factory=lambda: now,
        )

        await publisher.publish_pending_once()

        self.assertEqual(
            broker.published[0].routing_key,
            APPROVAL_TIMEOUT_READY_ROUTING_KEY,
        )

    async def _test_crash_after_claim_is_recovered_after_lease_expires(self) -> None:
        crashed_at = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
        recovered_at = crashed_at + timedelta(seconds=31)
        outbox = self._event(
            event_id="outbox-crash-after-claim",
            event_type="agent.run.start",
            now=crashed_at,
        )
        outbox.status = "publishing"
        outbox.available_at = crashed_at + timedelta(seconds=30)
        store = FakeOutboxStore([outbox])
        broker = FakeBroker()
        publisher = OutboxPublisher(
            store=store,
            broker=broker,
            now_factory=lambda: recovered_at,
        )

        await publisher.publish_pending_once()

        refreshed = store.events[outbox.id]
        self.assertEqual(broker.confirmed_message_id, outbox.id)
        self.assertEqual(refreshed.status, "published")
        self.assertEqual(refreshed.published_at, recovered_at)

    async def _test_stale_failure_does_not_overwrite_newer_published_state(
        self,
    ) -> None:
        old_holder_now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
        newer_published_at = old_holder_now + timedelta(seconds=31)
        outbox = self._event(
            event_id="outbox-stale-failure",
            event_type="agent.run.start",
            now=old_holder_now,
        )
        store = FakeOutboxStore([outbox])
        broker = FakeBroker()
        broker.raise_on_publish = RuntimeError("old holder publish failed")
        publisher = OutboxPublisher(
            store=store,
            broker=broker,
            now_factory=lambda: old_holder_now,
        )

        def publish_by_newer_holder() -> None:
            current = store.events[outbox.id]
            current.status = "published"
            current.published_at = newer_published_at
            current.available_at = newer_published_at + timedelta(seconds=30)
            current.last_error = None

        store.race_before_mark_retryable = publish_by_newer_holder

        await publisher.publish_pending_once()

        refreshed = store.events[outbox.id]
        self.assertEqual(refreshed.status, "published")
        self.assertEqual(refreshed.published_at, newer_published_at)
        self.assertIsNone(refreshed.last_error)

    async def _test_stale_success_does_not_overwrite_newer_publishing_lease(
        self,
    ) -> None:
        old_holder_now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
        newer_lease_expires_at = old_holder_now + timedelta(seconds=61)
        outbox = self._event(
            event_id="outbox-stale-success",
            event_type="agent.run.start",
            now=old_holder_now,
        )
        store = FakeOutboxStore([outbox])
        broker = FakeBroker()
        publisher = OutboxPublisher(
            store=store,
            broker=broker,
            now_factory=lambda: old_holder_now,
        )

        def reclaim_by_newer_holder() -> None:
            current = store.events[outbox.id]
            current.status = "publishing"
            current.available_at = newer_lease_expires_at
            current.published_at = None

        store.race_before_mark_published = reclaim_by_newer_holder

        await publisher.publish_pending_once()

        refreshed = store.events[outbox.id]
        self.assertEqual(refreshed.status, "publishing")
        self.assertEqual(refreshed.available_at, newer_lease_expires_at)
        self.assertIsNone(refreshed.published_at)

    async def _test_db_stale_success_does_not_overwrite_newer_publishing_lease(
        self,
    ) -> None:
        event_id = "outbox-db-stale-success"
        old_holder_now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
        old_lease_expires_at = old_holder_now + timedelta(seconds=30)
        newer_lease_expires_at = old_holder_now + timedelta(seconds=61)
        await self._reset_outbox_event(event_id)

        async with AsyncSessionLocal() as setup_session:
            setup_session.add(
                self._event(
                    event_id=event_id,
                    event_type="agent.run.start",
                    now=old_holder_now,
                )
            )
            await setup_session.commit()

        async with AsyncSessionLocal() as stale_session:
            stale_event = await stale_session.get(OutboxEvent, event_id)
            assert stale_event is not None
            stale_event.status = "publishing"
            stale_event.available_at = old_lease_expires_at
            await stale_session.commit()

            async with AsyncSessionLocal() as newer_session:
                newer_event = await newer_session.get(OutboxEvent, event_id)
                assert newer_event is not None
                newer_event.status = "publishing"
                newer_event.available_at = newer_lease_expires_at
                newer_event.published_at = None
                await newer_session.commit()

            await mark_outbox_event_published(
                stale_session,
                event_id=event_id,
                now=old_holder_now,
                lease_expires_at=old_lease_expires_at,
            )
            await stale_session.commit()

        async with AsyncSessionLocal() as verify_session:
            refreshed = await verify_session.get(OutboxEvent, event_id)
            assert refreshed is not None
            self.assertEqual(refreshed.status, "publishing")
            self.assertEqual(refreshed.available_at, newer_lease_expires_at)
            self.assertIsNone(refreshed.published_at)

        await self._reset_outbox_event(event_id)

    async def _test_db_stale_failure_does_not_overwrite_newer_published_state(
        self,
    ) -> None:
        event_id = "outbox-db-stale-failure"
        old_holder_now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
        old_lease_expires_at = old_holder_now + timedelta(seconds=30)
        newer_published_at = old_holder_now + timedelta(seconds=31)
        await self._reset_outbox_event(event_id)

        async with AsyncSessionLocal() as setup_session:
            setup_session.add(
                self._event(
                    event_id=event_id,
                    event_type="agent.run.start",
                    now=old_holder_now,
                )
            )
            await setup_session.commit()

        async with AsyncSessionLocal() as stale_session:
            stale_event = await stale_session.get(OutboxEvent, event_id)
            assert stale_event is not None
            stale_event.status = "publishing"
            stale_event.available_at = old_lease_expires_at
            await stale_session.commit()

            async with AsyncSessionLocal() as newer_session:
                newer_event = await newer_session.get(OutboxEvent, event_id)
                assert newer_event is not None
                newer_event.status = "published"
                newer_event.published_at = newer_published_at
                newer_event.available_at = newer_published_at + timedelta(seconds=30)
                newer_event.last_error = None
                await newer_session.commit()

            await mark_outbox_event_retryable(
                stale_session,
                event_id=event_id,
                error="old holder failed",
                available_at=old_holder_now + timedelta(seconds=1),
                lease_expires_at=old_lease_expires_at,
            )
            await stale_session.commit()

        async with AsyncSessionLocal() as verify_session:
            refreshed = await verify_session.get(OutboxEvent, event_id)
            assert refreshed is not None
            self.assertEqual(refreshed.status, "published")
            self.assertEqual(refreshed.published_at, newer_published_at)
            self.assertIsNone(refreshed.last_error)

        await self._reset_outbox_event(event_id)

    def _event(
        self,
        *,
        event_id: str,
        event_type: str,
        now: datetime,
        payload: dict[str, object] | None = None,
    ) -> OutboxEvent:
        return OutboxEvent(
            id=event_id,
            event_type=event_type,
            aggregate_id="aggregate-1",
            payload=payload or {"runId": "run-1"},
            status="pending",
            attempt_count=0,
            available_at=now,
            published_at=None,
            last_error=None,
            created_at=now,
        )

    async def _reset_outbox_event(self, event_id: str) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(OutboxEvent).where(OutboxEvent.id == event_id))
            await session.commit()
