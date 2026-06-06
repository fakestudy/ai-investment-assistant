import asyncio
import unittest
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from core.database import AsyncSessionLocal, engine
from main import create_app
from model.agent_run import AgentRun
from model.agent_run_event import AgentRunEvent
from model.conversation import Conversation
from model.message import Message
from repository.agent_run_event import list_run_events_after
from service import run_events
from service.run_events import (
    format_persisted_sse,
    stream_run_events,
)


class RunEventStreamTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        asyncio.run(engine.dispose())

    def test_append_event_assigns_monotonic_ids(self) -> None:
        asyncio.run(self._test_append_event_assigns_monotonic_ids())

    def test_replay_returns_only_events_after_cursor(self) -> None:
        asyncio.run(self._test_replay_returns_only_events_after_cursor())

    def test_sse_frame_contains_id_and_run_id(self) -> None:
        event = AgentRunEvent(
            id=42,
            agent_run_id="run-1",
            event_type="done",
            payload={"type": "done", "messageId": "assistant-1"},
            created_at=datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
        )

        frame = format_persisted_sse(event)

        self.assertTrue(frame.startswith("id: 42\n"))
        self.assertIn('"runId":"run-1"', frame)
        self.assertIn('"type":"done"', frame)

    def test_stream_stops_after_stable_boundary_event(self) -> None:
        asyncio.run(self._test_stream_stops_after_stable_boundary_event())

    def test_resume_after_cursor_beyond_stable_boundary_ends(self) -> None:
        asyncio.run(self._test_resume_after_cursor_beyond_stable_boundary_ends())

    def test_stream_uses_injected_stable_boundary_checker(self) -> None:
        asyncio.run(self._test_stream_uses_injected_stable_boundary_checker())

    def test_stream_emits_heartbeat_while_waiting_for_events(self) -> None:
        asyncio.run(self._test_stream_emits_heartbeat_while_waiting_for_events())

    def test_waiter_ignores_other_run_notifications_until_current_run(self) -> None:
        asyncio.run(
            self._test_waiter_ignores_other_run_notifications_until_current_run()
        )

    def test_waiter_returns_false_after_only_other_run_notifications(self) -> None:
        asyncio.run(
            self._test_waiter_returns_false_after_only_other_run_notifications()
        )

    def test_append_event_persists_payload_with_run_id(self) -> None:
        asyncio.run(self._test_append_event_persists_payload_with_run_id())

    def test_resume_route_replays_existing_events_without_creating_run(self) -> None:
        asyncio.run(self._test_resume_route_replays_existing_events_without_creating_run())

    async def _test_append_event_assigns_monotonic_ids(self) -> None:
        run_id = "run-event-monotonic"
        await self._reset_run(run_id)
        await self._create_run(run_id)

        async with AsyncSessionLocal() as session:
            first = await self._append_run_event(
                session,
                run_id,
                "run_created",
                {"type": "run_created", "status": "queued"},
            )
            second = await self._append_run_event(
                session,
                run_id,
                "message_created",
                {"type": "message_created", "message": {"id": "assistant-monotonic"}},
            )
            await session.commit()

        self.assertGreater(second.id, first.id)
        await self._reset_run(run_id)

    async def _test_replay_returns_only_events_after_cursor(self) -> None:
        run_id = "run-event-replay"
        await self._reset_run(run_id)
        await self._create_run(run_id)

        async with AsyncSessionLocal() as session:
            first = await self._append_run_event(
                session,
                run_id,
                "run_created",
                {"type": "run_created", "status": "queued"},
            )
            second = await self._append_run_event(
                session,
                run_id,
                "done",
                {"type": "done", "messageId": "assistant-replay"},
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            events = await list_run_events_after(
                session,
                run_id=run_id,
                after_event_id=first.id,
            )

        self.assertEqual([event.id for event in events], [second.id])
        await self._reset_run(run_id)

    async def _test_stream_stops_after_stable_boundary_event(self) -> None:
        run_id = "run-event-stable-boundary"
        await self._reset_run(run_id)
        await self._create_run(run_id)

        async with AsyncSessionLocal() as session:
            first = await self._append_run_event(
                session,
                run_id,
                "delta",
                {"type": "delta", "messageId": "assistant-stable", "text": "hello"},
            )
            second = await self._append_run_event(
                session,
                run_id,
                "done",
                {"type": "done", "messageId": "assistant-stable"},
            )
            await self._append_run_event(
                session,
                run_id,
                "delta",
                {"type": "delta", "messageId": "assistant-stable", "text": "late"},
            )
            await session.commit()

        frames = [frame async for frame in stream_run_events(run_id, after_event_id=0)]

        self.assertEqual(len(frames), 2)
        self.assertIn(f"id: {first.id}\n", frames[0])
        self.assertIn(f"id: {second.id}\n", frames[1])
        self.assertIn('"type":"done"', frames[1])
        await self._reset_run(run_id)

    async def _test_resume_after_cursor_beyond_stable_boundary_ends(self) -> None:
        run_id = "run-event-resume-after-stable"
        await self._reset_run(run_id)
        await self._create_run(run_id)

        async with AsyncSessionLocal() as session:
            stable = await self._append_run_event(
                session,
                run_id,
                "done",
                {"type": "done", "messageId": "assistant-resume-after-stable"},
            )
            await session.commit()

        waiter_calls = 0

        async def fail_if_waiting(_: str, __: float) -> bool:
            nonlocal waiter_calls
            waiter_calls += 1
            return False

        frames = [
            frame
            async for frame in stream_run_events(
                run_id,
                after_event_id=stable.id + 1,
                wait_for_new_events=True,
                notification_waiter=fail_if_waiting,
                heartbeat_seconds=0.01,
                max_idle_cycles=1,
            )
        ]

        self.assertEqual(frames, [])
        self.assertEqual(waiter_calls, 0)
        await self._reset_run(run_id)

    async def _test_stream_uses_injected_stable_boundary_checker(self) -> None:
        checker_calls = []
        waiter_calls = 0

        async def empty_loader(_: str, __: int) -> list[AgentRunEvent]:
            return []

        async def stable_checker(run_id: str, event_id: int) -> bool:
            checker_calls.append((run_id, event_id))
            return True

        async def fail_if_waiting(_: str, __: float) -> bool:
            nonlocal waiter_calls
            waiter_calls += 1
            return False

        frames = [
            frame
            async for frame in stream_run_events(
                "run-event-injected-stable-checker",
                after_event_id=42,
                wait_for_new_events=True,
                event_loader=empty_loader,
                notification_waiter=fail_if_waiting,
                stable_boundary_checker=stable_checker,
                heartbeat_seconds=0.01,
                max_idle_cycles=1,
            )
        ]

        self.assertEqual(frames, [])
        self.assertEqual(checker_calls, [("run-event-injected-stable-checker", 42)])
        self.assertEqual(waiter_calls, 0)

    async def _test_stream_emits_heartbeat_while_waiting_for_events(self) -> None:
        async def empty_loader(_: str, __: int) -> list[AgentRunEvent]:
            return []

        async def timeout_waiter(_: str, __: float) -> bool:
            return False

        frames = [
            frame
            async for frame in stream_run_events(
                "run-event-heartbeat",
                after_event_id=0,
                wait_for_new_events=True,
                event_loader=empty_loader,
                notification_waiter=timeout_waiter,
                heartbeat_seconds=0.01,
                max_idle_cycles=1,
            )
        ]

        self.assertEqual(frames, [": heartbeat\n\n"])

    async def _test_waiter_ignores_other_run_notifications_until_current_run(self) -> None:
        self.assertTrue(hasattr(run_events, "wait_for_matching_run_notification"))
        result = await run_events.wait_for_matching_run_notification(
            "current-run",
            self._notification_payloads(["other-run", "current-run"]),
        )

        self.assertTrue(result)

    async def _test_waiter_returns_false_after_only_other_run_notifications(self) -> None:
        self.assertTrue(hasattr(run_events, "wait_for_matching_run_notification"))
        result = await run_events.wait_for_matching_run_notification(
            "current-run",
            self._notification_payloads(["other-run", "another-run"]),
        )

        self.assertFalse(result)

    async def _test_append_event_persists_payload_with_run_id(self) -> None:
        run_id = "run-event-payload-run-id"
        await self._reset_run(run_id)
        await self._create_run(run_id)

        async with AsyncSessionLocal() as session:
            event = await self._append_run_event(
                session,
                run_id,
                "delta",
                {"type": "delta", "messageId": "assistant-payload", "text": "hello"},
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            persisted = await session.get(AgentRunEvent, event.id)

        assert persisted is not None
        self.assertIn("runId", persisted.payload)
        self.assertEqual(persisted.payload["runId"], run_id)
        await self._reset_run(run_id)

    async def _test_resume_route_replays_existing_events_without_creating_run(self) -> None:
        run_id = "run-event-resume-route"
        await self._reset_run(run_id)
        await self._create_run(run_id)

        async with AsyncSessionLocal() as session:
            first = await self._append_run_event(
                session,
                run_id,
                "run_created",
                {"type": "run_created", "status": "queued"},
            )
            second = await self._append_run_event(
                session,
                run_id,
                "done",
                {"type": "done", "messageId": "assistant-resume-route"},
            )
            await session.commit()

        before_count = await self._count_runs()
        client = TestClient(create_app())
        response = client.post(
            "/api/chat/stream/resume",
            json={"runId": run_id, "afterEventId": first.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(f"id: {second.id}\n", response.text)
        self.assertNotIn(f"id: {first.id}\n", response.text)
        self.assertEqual(await self._count_runs(), before_count)
        await self._reset_run(run_id)

    async def _create_run(self, run_id: str) -> None:
        now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
        conversation_id = f"conversation-{run_id}"
        user_message_id = f"user-{run_id}"
        assistant_message_id = f"assistant-{run_id}"

        async with AsyncSessionLocal() as session:
            session.add(
                Conversation(
                    id=conversation_id,
                    title="Run event stream",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                Message(
                    id=user_message_id,
                    conversation_id=conversation_id,
                    role="user",
                    content="hello",
                    reasoning="",
                    status="done",
                    created_at=now,
                )
            )
            session.add(
                Message(
                    id=assistant_message_id,
                    conversation_id=conversation_id,
                    role="assistant",
                    content="",
                    reasoning="",
                    status="streaming",
                    created_at=now,
                )
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            session.add(
                AgentRun(
                    id=run_id,
                    conversation_id=conversation_id,
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
            )
            await session.commit()

    async def _append_run_event(
        self,
        session,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> AgentRunEvent:
        self.assertTrue(hasattr(run_events, "append_run_event"))
        return await run_events.append_run_event(session, run_id, event_type, payload)

    async def _reset_run(self, run_id: str) -> None:
        conversation_id = f"conversation-{run_id}"
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(AgentRunEvent).where(AgentRunEvent.agent_run_id == run_id)
            )
            await session.execute(delete(AgentRun).where(AgentRun.id == run_id))
            await session.execute(
                delete(Message).where(Message.conversation_id == conversation_id)
            )
            await session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            )
            await session.commit()

    async def _count_runs(self) -> int:
        async with AsyncSessionLocal() as session:
            return await session.scalar(select(func.count()).select_from(AgentRun)) or 0

    async def _notification_payloads(self, payloads: list[str]):
        for payload in payloads:
            yield payload


if __name__ == "__main__":
    unittest.main()
