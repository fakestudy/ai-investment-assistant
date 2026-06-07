import asyncio
import unittest
from datetime import UTC, datetime

from sqlalchemy import delete, select

from core.database import AsyncSessionLocal, engine
from model.agent_run import AgentRun
from model.agent_run_event import AgentRunEvent
from model.conversation import Conversation
from model.message import Message
from model.outbox_event import OutboxEvent
from schema.chat import ChatStreamRequest
from service.chat_run import ConversationRunConflict, create_chat_run
from service.run_events import stream_run_events


class IdFactory:
    def __init__(self, ids: list[str]) -> None:
        self.ids = ids
        self.index = 0

    def __call__(self) -> str:
        value = self.ids[self.index]
        self.index += 1
        return value


class ChatRunServiceTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        asyncio.run(engine.dispose())

    def test_create_run_commits_messages_run_and_outbox_together(self) -> None:
        asyncio.run(self._test_create_run_commits_messages_run_and_outbox_together())

    def test_second_active_run_in_same_conversation_conflicts(self) -> None:
        asyncio.run(self._test_second_active_run_in_same_conversation_conflicts())

    def test_outbox_failure_rolls_back_messages_and_run(self) -> None:
        asyncio.run(self._test_outbox_failure_rolls_back_messages_and_run())

    def test_create_run_persists_and_streams_initial_run_events(self) -> None:
        asyncio.run(self._test_create_run_persists_and_streams_initial_run_events())

    def test_create_run_includes_generate_title_in_start_outbox_payload(self) -> None:
        asyncio.run(
            self._test_create_run_includes_generate_title_in_start_outbox_payload()
        )

    async def _test_create_run_commits_messages_run_and_outbox_together(self) -> None:
        conversation_id = "conversation-chat-run-create"
        await self._reset_conversation(conversation_id)
        now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)

        async with AsyncSessionLocal() as session:
            session.add(
                Conversation(
                    id=conversation_id,
                    title="Run creation",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

            request = ChatStreamRequest.model_validate(
                {"conversationId": conversation_id, "message": "启动分析"}
            )
            result = await create_chat_run(
                session,
                request,
                id_factory=IdFactory(
                    ["user-message-1", "assistant-message-1", "run-1", "outbox-1"]
                ),
                now_factory=lambda: now,
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            user_message = await session.get(Message, "user-message-1")
            assistant_message = await session.get(Message, "assistant-message-1")
            run = await session.get(AgentRun, "run-1")
            outbox = await session.get(OutboxEvent, "outbox-1")

            self.assertIsNotNone(user_message)
            self.assertIsNotNone(assistant_message)
            self.assertIsNotNone(run)
            self.assertIsNotNone(outbox)
            assert user_message is not None
            assert assistant_message is not None
            assert run is not None
            assert outbox is not None
            self.assertEqual(user_message.content, "启动分析")
            self.assertEqual(user_message.status, "done")
            self.assertEqual(assistant_message.status, "streaming")
            self.assertEqual(run.status, "queued")
            self.assertEqual(run.version, 0)
            self.assertEqual(run.user_message_id, "user-message-1")
            self.assertEqual(run.assistant_message_id, "assistant-message-1")
            self.assertEqual(outbox.event_type, "agent.run.start")
            self.assertEqual(outbox.aggregate_id, result.run.id)
            self.assertEqual(outbox.payload, {"runId": result.run.id})
            self.assertEqual(outbox.status, "pending")
            self.assertEqual(outbox.attempt_count, 0)
            self.assertEqual(result.run.id, "run-1")
            self.assertEqual(result.outbox.id, "outbox-1")

        await self._reset_conversation(conversation_id)

    async def _test_create_run_includes_generate_title_in_start_outbox_payload(
        self,
    ) -> None:
        conversation_id = "conversation-chat-run-generate-title-outbox"
        await self._reset_conversation(conversation_id)
        now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)

        async with AsyncSessionLocal() as session:
            session.add(
                Conversation(
                    id=conversation_id,
                    title="Run title outbox",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

            result = await create_chat_run(
                session,
                ChatStreamRequest.model_validate(
                    {
                        "conversationId": conversation_id,
                        "message": "启动分析",
                        "generateTitle": True,
                    }
                ),
                id_factory=IdFactory(
                    [
                        "user-message-title-outbox",
                        "assistant-message-title-outbox",
                        "run-title-outbox",
                        "outbox-title-outbox",
                    ]
                ),
                now_factory=lambda: now,
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            outbox = await session.get(OutboxEvent, result.outbox.id)

        self.assertIsNotNone(outbox)
        assert outbox is not None
        self.assertEqual(
            outbox.payload,
            {"runId": result.run.id, "generateTitle": True},
        )
        await self._reset_conversation(conversation_id)

    async def _test_create_run_persists_and_streams_initial_run_events(self) -> None:
        conversation_id = "conversation-chat-run-created-event"
        await self._reset_conversation(conversation_id)
        now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)

        async with AsyncSessionLocal() as session:
            session.add(
                Conversation(
                    id=conversation_id,
                    title="Run created event",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

            result = await create_chat_run(
                session,
                ChatStreamRequest.model_validate(
                    {"conversationId": conversation_id, "message": "启动分析"}
                ),
                id_factory=IdFactory(
                    [
                        "user-message-run-created-event",
                        "assistant-message-run-created-event",
                        "run-created-event",
                        "outbox-run-created-event",
                    ]
                ),
                now_factory=lambda: now,
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            events = (
                await session.execute(
                    select(AgentRunEvent)
                    .where(AgentRunEvent.agent_run_id == result.run.id)
                    .order_by(AgentRunEvent.id)
                )
            ).scalars().all()
            self.assertEqual(
                [event.event_type for event in events],
                ["run_created", "message_created"],
            )
            self.assertEqual(
                events[0].payload,
                {
                    "type": "run_created",
                    "runId": result.run.id,
                    "status": "queued",
                    "assistantMessageId": result.run.assistant_message_id,
                },
            )
            self.assertEqual(
                events[1].payload,
                {
                    "type": "message_created",
                    "runId": result.run.id,
                    "message": {
                        "id": result.run.assistant_message_id,
                        "conversationId": conversation_id,
                        "role": "assistant",
                        "content": "",
                        "status": "streaming",
                        "createdAt": "2026-06-06T12:00:00Z",
                    },
                },
            )

        frames = [
            frame
            async for frame in stream_run_events(result.run.id, after_event_id=0)
        ]
        self.assertEqual(len(frames), 2)
        self.assertTrue(frames[0].startswith("id: "))
        self.assertIn('"type":"run_created"', frames[0])
        self.assertIn('"runId":"run-created-event"', frames[0])
        self.assertIn('"assistantMessageId":"assistant-message-run-created-event"', frames[0])
        self.assertIn('"type":"message_created"', frames[1])
        self.assertIn('"id":"assistant-message-run-created-event"', frames[1])
        self.assertIn('"conversationId":"conversation-chat-run-created-event"', frames[1])

        await self._reset_conversation(conversation_id)

    async def _test_second_active_run_in_same_conversation_conflicts(self) -> None:
        conversation_id = "conversation-chat-run-conflict"
        await self._reset_conversation(conversation_id)
        now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)

        async with AsyncSessionLocal() as session:
            session.add(
                Conversation(
                    id=conversation_id,
                    title="Run conflict",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

            request = ChatStreamRequest.model_validate(
                {"conversationId": conversation_id, "message": "第一次"}
            )
            await create_chat_run(
                session,
                request,
                id_factory=IdFactory(
                    [
                        "user-message-conflict-1",
                        "assistant-message-conflict-1",
                        "run-conflict-1",
                        "outbox-conflict-1",
                    ]
                ),
                now_factory=lambda: now,
            )
            await session.commit()

            with self.assertRaises(ConversationRunConflict):
                await create_chat_run(
                    session,
                    ChatStreamRequest.model_validate(
                        {"conversationId": conversation_id, "message": "第二次"}
                    ),
                    id_factory=IdFactory(
                        [
                            "user-message-conflict-2",
                            "assistant-message-conflict-2",
                            "run-conflict-2",
                            "outbox-conflict-2",
                        ]
                    ),
                    now_factory=lambda: now,
                )
            await session.rollback()

        await self._reset_conversation(conversation_id)

    async def _test_outbox_failure_rolls_back_messages_and_run(self) -> None:
        conversation_id = "conversation-chat-run-rollback"
        await self._reset_conversation(conversation_id)
        now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)

        async with AsyncSessionLocal() as session:
            session.add(
                Conversation(
                    id=conversation_id,
                    title="Run rollback",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

            request = ChatStreamRequest.model_validate(
                {"conversationId": conversation_id, "message": "需要回滚"}
            )
            with self.assertRaisesRegex(RuntimeError, "outbox flush failed"):
                await create_chat_run(
                    session,
                    request,
                    id_factory=IdFactory(
                        [
                            "user-message-rollback",
                            "assistant-message-rollback",
                            "run-rollback",
                            "outbox-rollback",
                        ]
                    ),
                    now_factory=lambda: now,
                    outbox_repository=FailingOutboxRepository(),
                )
            await session.rollback()

        async with AsyncSessionLocal() as session:
            messages = (
                await session.execute(
                    select(Message).where(Message.conversation_id == conversation_id)
                )
            ).scalars().all()
            run = await session.get(AgentRun, "run-rollback")
            outbox = await session.get(OutboxEvent, "outbox-rollback")

            self.assertEqual(messages, [])
            self.assertIsNone(run)
            self.assertIsNone(outbox)

        await self._reset_conversation(conversation_id)

    async def _reset_conversation(self, conversation_id: str) -> None:
        async with AsyncSessionLocal() as session:
            run_ids = (
                await session.execute(
                    select(AgentRun.id).where(
                        AgentRun.conversation_id == conversation_id
                    )
                )
            ).scalars().all()
            if run_ids:
                await session.execute(
                    delete(AgentRunEvent).where(AgentRunEvent.agent_run_id.in_(run_ids))
                )
                await session.execute(
                    delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(run_ids))
                )
            await session.execute(
                delete(Message).where(Message.conversation_id == conversation_id)
            )
            await session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            )
            await session.commit()


class FailingOutboxRepository:
    async def create(self, _: object, __: OutboxEvent) -> OutboxEvent:
        raise RuntimeError("outbox flush failed")


if __name__ == "__main__":
    unittest.main()
