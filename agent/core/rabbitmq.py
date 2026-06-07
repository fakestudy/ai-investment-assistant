from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aio_pika import DeliveryMode, ExchangeType, Message, connect_robust
from aio_pika.abc import AbstractChannel, AbstractRobustConnection

from model.outbox_event import OutboxEvent


AGENT_COMMANDS_EXCHANGE = "agent.commands"
AGENT_RUN_COMMANDS_QUEUE = "agent.run.commands"
AGENT_RUN_START_ROUTING_KEY = "agent.run.start"
AGENT_RUN_RESUME_ROUTING_KEY = "agent.run.resume"

APPROVAL_TIMEOUT_EXCHANGE = "approval.timeout"
APPROVAL_TIMEOUT_DELAY_QUEUE = "approval.timeout.delay"
APPROVAL_TIMEOUT_READY_QUEUE = "approval.timeout.ready"
APPROVAL_TIMEOUT_SCHEDULE_ROUTING_KEY = "approval.timeout.schedule"
APPROVAL_TIMEOUT_READY_ROUTING_KEY = "approval.timeout.ready"
APPROVAL_TIMEOUT_TTL_MS = 30 * 60 * 1000


@dataclass(frozen=True)
class RabbitMQRoute:
    exchange_name: str
    routing_key: str


async def connect_rabbitmq(url: str | None = None) -> AbstractRobustConnection:
    rabbitmq_url = url or os.getenv(
        "RABBITMQ_URL",
        "amqp://investment:investment@localhost:5672/",
    )
    return await connect_robust(rabbitmq_url)


async def open_confirm_channel(connection: AbstractRobustConnection) -> AbstractChannel:
    return await connection.channel(publisher_confirms=True)


async def declare_rabbitmq_topology(
    channel: AbstractChannel,
    *,
    approval_timeout_ttl_ms: int = APPROVAL_TIMEOUT_TTL_MS,
) -> None:
    agent_exchange = await channel.declare_exchange(
        AGENT_COMMANDS_EXCHANGE,
        ExchangeType.TOPIC,
        durable=True,
    )
    agent_queue = await channel.declare_queue(
        AGENT_RUN_COMMANDS_QUEUE,
        durable=True,
        arguments={"x-queue-type": "quorum"},
    )
    await agent_queue.bind(agent_exchange, routing_key=AGENT_RUN_START_ROUTING_KEY)
    await agent_queue.bind(agent_exchange, routing_key=AGENT_RUN_RESUME_ROUTING_KEY)

    timeout_exchange = await channel.declare_exchange(
        APPROVAL_TIMEOUT_EXCHANGE,
        ExchangeType.DIRECT,
        durable=True,
    )
    timeout_delay_queue = await channel.declare_queue(
        APPROVAL_TIMEOUT_DELAY_QUEUE,
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-message-ttl": approval_timeout_ttl_ms,
            "x-dead-letter-exchange": APPROVAL_TIMEOUT_EXCHANGE,
            "x-dead-letter-routing-key": APPROVAL_TIMEOUT_READY_ROUTING_KEY,
        },
    )
    await timeout_delay_queue.bind(
        timeout_exchange,
        routing_key=APPROVAL_TIMEOUT_SCHEDULE_ROUTING_KEY,
    )
    timeout_ready_queue = await channel.declare_queue(
        APPROVAL_TIMEOUT_READY_QUEUE,
        durable=True,
        arguments={"x-queue-type": "quorum"},
    )
    await timeout_ready_queue.bind(
        timeout_exchange,
        routing_key=APPROVAL_TIMEOUT_READY_ROUTING_KEY,
    )


def build_outbox_message(event: OutboxEvent) -> Message:
    return Message(
        body=json.dumps(event.payload, separators=(",", ":")).encode(),
        message_id=event.id,
        delivery_mode=DeliveryMode.PERSISTENT,
        content_type="application/json",
        type=event.event_type,
    )


def route_for_outbox_event(event: OutboxEvent, *, now: datetime) -> RabbitMQRoute:
    if event.event_type in {AGENT_RUN_START_ROUTING_KEY, AGENT_RUN_RESUME_ROUTING_KEY}:
        return RabbitMQRoute(
            exchange_name=AGENT_COMMANDS_EXCHANGE,
            routing_key=event.event_type,
        )
    if event.event_type == APPROVAL_TIMEOUT_SCHEDULE_ROUTING_KEY:
        routing_key = (
            APPROVAL_TIMEOUT_READY_ROUTING_KEY
            if _timeout_already_expired(event.payload, now)
            else APPROVAL_TIMEOUT_SCHEDULE_ROUTING_KEY
        )
        return RabbitMQRoute(
            exchange_name=APPROVAL_TIMEOUT_EXCHANGE,
            routing_key=routing_key,
        )
    if event.event_type == APPROVAL_TIMEOUT_READY_ROUTING_KEY:
        return RabbitMQRoute(
            exchange_name=APPROVAL_TIMEOUT_EXCHANGE,
            routing_key=APPROVAL_TIMEOUT_READY_ROUTING_KEY,
        )
    raise ValueError(f"unsupported outbox event type: {event.event_type}")


class RabbitMQBroker:
    def __init__(self, channel: AbstractChannel) -> None:
        self._channel = channel

    async def publish_outbox_event(
        self,
        event: OutboxEvent,
        *,
        now: datetime,
        routing_key: str | None = None,
    ) -> None:
        route = route_for_outbox_event(event, now=now)
        exchange = await self._channel.get_exchange(route.exchange_name)
        await exchange.publish(
            build_outbox_message(event),
            routing_key=routing_key or route.routing_key,
        )


def _timeout_already_expired(payload: dict[str, Any], now: datetime) -> bool:
    expires_at_value = payload.get("expiresAt")
    if not isinstance(expires_at_value, str):
        return False
    expires_at = datetime.fromisoformat(expires_at_value.replace("Z", "+00:00"))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= now
