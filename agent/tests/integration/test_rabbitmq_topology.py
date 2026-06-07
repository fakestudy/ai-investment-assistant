import asyncio
import os
import unittest
from datetime import UTC, datetime

from aio_pika.abc import AbstractQueue
from aio_pika import DeliveryMode, Message, connect_robust

from core.rabbitmq import (
    AGENT_COMMANDS_EXCHANGE,
    AGENT_RUN_COMMANDS_QUEUE,
    APPROVAL_TIMEOUT_DELAY_QUEUE,
    APPROVAL_TIMEOUT_EXCHANGE,
    APPROVAL_TIMEOUT_READY_QUEUE,
    APPROVAL_TIMEOUT_READY_ROUTING_KEY,
    APPROVAL_TIMEOUT_SCHEDULE_ROUTING_KEY,
    RabbitMQBroker,
    declare_rabbitmq_topology,
)
from model.outbox_event import OutboxEvent


RABBITMQ_URL = os.getenv(
    "RABBITMQ_URL",
    "amqp://investment:investment@localhost:5672/",
)


class RabbitMQTopologyTest(unittest.TestCase):
    def test_agent_run_commands_are_bound_to_command_queue(self) -> None:
        asyncio.run(self._test_agent_run_commands_are_bound_to_command_queue())

    def test_timeout_delay_dead_letters_to_ready_queue(self) -> None:
        asyncio.run(self._test_timeout_delay_dead_letters_to_ready_queue())

    def test_broker_publishes_persistent_json_message(self) -> None:
        asyncio.run(self._test_broker_publishes_persistent_json_message())

    async def _test_agent_run_commands_are_bound_to_command_queue(self) -> None:
        connection = await connect_robust(RABBITMQ_URL)
        try:
            channel = await connection.channel(publisher_confirms=True)
            await declare_rabbitmq_topology(channel)
            queue = await channel.get_queue(AGENT_RUN_COMMANDS_QUEUE)
            await queue.purge()
            exchange = await channel.get_exchange(AGENT_COMMANDS_EXCHANGE)

            await exchange.publish(
                Message(
                    b'{"runId":"run-1"}',
                    message_id="topology-agent-run",
                    delivery_mode=DeliveryMode.PERSISTENT,
                    content_type="application/json",
                    type="agent.run.start",
                ),
                routing_key="agent.run.start",
            )

            incoming = await _wait_for_message(queue)
            async with incoming.process():
                self.assertEqual(incoming.message_id, "topology-agent-run")
        finally:
            await connection.close()

    async def _test_timeout_delay_dead_letters_to_ready_queue(self) -> None:
        connection = await connect_robust(RABBITMQ_URL)
        try:
            channel = await connection.channel(publisher_confirms=True)
            await _delete_timeout_queues(channel)
            await declare_rabbitmq_topology(channel, approval_timeout_ttl_ms=100)
            ready_queue = await channel.get_queue(APPROVAL_TIMEOUT_READY_QUEUE)
            await ready_queue.purge()
            exchange = await channel.get_exchange(APPROVAL_TIMEOUT_EXCHANGE)

            await exchange.publish(
                Message(
                    b'{"batchId":"batch-1"}',
                    message_id="topology-timeout-delay",
                    delivery_mode=DeliveryMode.PERSISTENT,
                    content_type="application/json",
                    type="approval.timeout.schedule",
                    expiration=100,
                ),
                routing_key=APPROVAL_TIMEOUT_SCHEDULE_ROUTING_KEY,
            )

            incoming = await _wait_for_message(ready_queue, timeout_seconds=5)
            async with incoming.process():
                self.assertEqual(incoming.message_id, "topology-timeout-delay")
        finally:
            cleanup_channel = await connection.channel(publisher_confirms=True)
            await _delete_timeout_queues(cleanup_channel)
            await declare_rabbitmq_topology(cleanup_channel)
            await connection.close()

    async def _test_broker_publishes_persistent_json_message(self) -> None:
        connection = await connect_robust(RABBITMQ_URL)
        try:
            channel = await connection.channel(publisher_confirms=True)
            await declare_rabbitmq_topology(channel)
            queue = await channel.get_queue(AGENT_RUN_COMMANDS_QUEUE)
            await queue.purge()
            broker = RabbitMQBroker(channel)
            now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)

            await broker.publish_outbox_event(
                OutboxEvent(
                    id="topology-broker-message",
                    event_type="agent.run.resume",
                    aggregate_id="run-1",
                    payload={"runId": "run-1"},
                    status="publishing",
                    attempt_count=0,
                    available_at=now,
                    published_at=None,
                    last_error=None,
                    created_at=now,
                ),
                now=now,
            )

            incoming = await _wait_for_message(queue)
            async with incoming.process():
                self.assertEqual(incoming.body, b'{"runId":"run-1"}')
                self.assertEqual(incoming.message_id, "topology-broker-message")
                self.assertEqual(incoming.delivery_mode, DeliveryMode.PERSISTENT)
                self.assertEqual(incoming.content_type, "application/json")
                self.assertEqual(incoming.type, "agent.run.resume")
        finally:
            await connection.close()


async def _wait_for_message(
    queue: AbstractQueue,
    *,
    timeout_seconds: float = 3,
):
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        incoming = await queue.get(timeout=1, fail=False)
        if incoming is not None:
            return incoming
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"queue {queue.name} did not receive a message")
        await asyncio.sleep(0.1)


async def _delete_timeout_queues(channel) -> None:
    for queue_name in (APPROVAL_TIMEOUT_DELAY_QUEUE, APPROVAL_TIMEOUT_READY_QUEUE):
        try:
            await channel.queue_delete(queue_name)
        except Exception:
            pass
