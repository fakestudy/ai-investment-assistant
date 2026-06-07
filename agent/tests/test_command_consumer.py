import asyncio
import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from worker.command_consumer import CommandConsumer
from worker.run_executor import AgentRunCommandRetry


class FakeExecutor:
    def __init__(self) -> None:
        self.start_commands: list[Any] = []
        self.resume_commands: list[Any] = []
        self.raise_on_start: Exception | None = None

    async def execute_start(self, command: Any) -> None:
        if self.raise_on_start is not None:
            raise self.raise_on_start
        self.start_commands.append(command)

    async def execute_resume(self, command: Any) -> None:
        self.resume_commands.append(command)


class FakeIncomingMessage:
    def __init__(
        self,
        *,
        message_id: str = "message-1",
        message_type: str,
        payload: dict[str, Any] | bytes,
    ) -> None:
        self.message_id = message_id
        self.type = message_type
        self.body = (
            payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        )
        self.acks = 0
        self.nacks: list[bool] = []

    async def ack(self) -> None:
        self.acks += 1

    async def nack(self, *, requeue: bool = True) -> None:
        self.nacks.append(requeue)


class CommandConsumerTest(unittest.TestCase):
    def test_start_command_acks_only_after_handler_success(self) -> None:
        asyncio.run(self._test_start_command_acks_only_after_handler_success())

    def test_temporary_handler_error_nacks_with_requeue(self) -> None:
        asyncio.run(self._test_temporary_handler_error_nacks_with_requeue())

    def test_bad_payload_is_acked_as_poison_message(self) -> None:
        asyncio.run(self._test_bad_payload_is_acked_as_poison_message())

    def test_timeout_ready_expires_batch_and_acks(self) -> None:
        asyncio.run(self._test_timeout_ready_expires_batch_and_acks())

    def test_dead_lettered_timeout_schedule_is_consumed_from_ready_queue(self) -> None:
        asyncio.run(
            self._test_dead_lettered_timeout_schedule_is_consumed_from_ready_queue()
        )

    def test_timeout_ready_reschedule_nacks_without_requeue(self) -> None:
        asyncio.run(self._test_timeout_ready_reschedule_nacks_without_requeue())

    async def _test_start_command_acks_only_after_handler_success(self) -> None:
        executor = FakeExecutor()
        consumer = CommandConsumer(
            executor=executor,
            expire_approval_batch=self._unused_timeout_handler,
            now_factory=lambda: datetime(2026, 6, 7, 10, 0, tzinfo=UTC),
        )
        message = FakeIncomingMessage(
            message_id="cmd-start-1",
            message_type="agent.run.start",
            payload={"runId": "run-1", "generateTitle": True},
        )

        await consumer.handle_message(message)

        self.assertEqual([command.id for command in executor.start_commands], ["cmd-start-1"])
        self.assertEqual(executor.start_commands[0].run_id, "run-1")
        self.assertTrue(executor.start_commands[0].generate_title)
        self.assertEqual(message.acks, 1)
        self.assertEqual(message.nacks, [])

    async def _test_temporary_handler_error_nacks_with_requeue(self) -> None:
        executor = FakeExecutor()
        executor.raise_on_start = AgentRunCommandRetry("run-retry")
        consumer = CommandConsumer(
            executor=executor,
            expire_approval_batch=self._unused_timeout_handler,
            now_factory=lambda: datetime(2026, 6, 7, 10, 0, tzinfo=UTC),
        )
        message = FakeIncomingMessage(
            message_id="cmd-retry",
            message_type="agent.run.start",
            payload={"runId": "run-retry"},
        )

        await consumer.handle_message(message)

        self.assertEqual(message.acks, 0)
        self.assertEqual(message.nacks, [True])

    async def _test_bad_payload_is_acked_as_poison_message(self) -> None:
        consumer = CommandConsumer(
            executor=FakeExecutor(),
            expire_approval_batch=self._unused_timeout_handler,
            now_factory=lambda: datetime(2026, 6, 7, 10, 0, tzinfo=UTC),
        )
        message = FakeIncomingMessage(
            message_id="cmd-bad",
            message_type="agent.run.start",
            payload={"missingRunId": "run-1"},
        )

        await consumer.handle_message(message)

        self.assertEqual(message.acks, 1)
        self.assertEqual(message.nacks, [])

    async def _test_timeout_ready_expires_batch_and_acks(self) -> None:
        calls: list[SimpleNamespace] = []

        async def expire(session: object, batch_id: str, *, now: datetime) -> None:
            calls.append(SimpleNamespace(session=session, batch_id=batch_id, now=now))

        now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
        consumer = CommandConsumer(
            executor=FakeExecutor(),
            expire_approval_batch=expire,
            session_factory=lambda: "session",
            now_factory=lambda: now,
        )
        message = FakeIncomingMessage(
            message_id="timeout-1",
            message_type="approval.timeout.ready",
            payload={"batchId": "batch-1", "expiresAt": "2026-06-07T10:00:00Z"},
        )

        await consumer.handle_message(message)

        self.assertEqual([(call.session, call.batch_id, call.now) for call in calls], [("session", "batch-1", now)])
        self.assertEqual(message.acks, 1)
        self.assertEqual(message.nacks, [])

    async def _test_dead_lettered_timeout_schedule_is_consumed_from_ready_queue(
        self,
    ) -> None:
        calls: list[str] = []

        async def expire(session: object, batch_id: str, *, now: datetime) -> None:
            calls.append(batch_id)

        consumer = CommandConsumer(
            executor=FakeExecutor(),
            expire_approval_batch=expire,
            session_factory=lambda: "session",
            now_factory=lambda: datetime(2026, 6, 7, 10, 0, tzinfo=UTC),
        )
        message = FakeIncomingMessage(
            message_id="timeout-dead-lettered",
            message_type="approval.timeout.schedule",
            payload={"batchId": "batch-dead-lettered", "expiresAt": "2026-06-07T10:00:00Z"},
        )

        await consumer.handle_message(message)

        self.assertEqual(calls, ["batch-dead-lettered"])
        self.assertEqual(message.acks, 1)
        self.assertEqual(message.nacks, [])

    async def _test_timeout_ready_reschedule_nacks_without_requeue(self) -> None:
        async def reschedule(session: object, batch_id: str, *, now: datetime) -> object:
            return SimpleNamespace(action="rescheduled")

        now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
        consumer = CommandConsumer(
            executor=FakeExecutor(),
            expire_approval_batch=reschedule,
            session_factory=lambda: "session",
            now_factory=lambda: now,
        )
        message = FakeIncomingMessage(
            message_id="timeout-early",
            message_type="approval.timeout.ready",
            payload={"batchId": "batch-early", "expiresAt": "2026-06-07T10:30:00Z"},
        )

        await consumer.handle_message(message)

        self.assertEqual(message.acks, 0)
        self.assertEqual(message.nacks, [False])

    async def _unused_timeout_handler(
        self,
        session: object,
        batch_id: str,
        *,
        now: datetime,
    ) -> None:
        raise AssertionError("timeout handler should not be called")


if __name__ == "__main__":
    unittest.main()
