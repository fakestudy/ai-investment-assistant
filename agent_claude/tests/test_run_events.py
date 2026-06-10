import asyncio
import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from schema.chat import ChatStreamEventAdapter, DeltaEvent
from service import run_events


def _decode_sse(frame: str) -> tuple[int, dict[str, Any]]:
    lines = frame.splitlines()
    event_id = next(
        int(line.removeprefix("id: "))
        for line in lines
        if line.startswith("id: ")
    )
    payload = json.loads(
        next(
            line.removeprefix("data: ")
            for line in lines
            if line.startswith("data: ")
        )
    )
    return event_id, payload


class _FakeStore:
    def __init__(self) -> None:
        self.next_event_id = 0
        self.events: dict[int, Any] = {}
        self.runs: dict[str, Any] = {
            "run-1": SimpleNamespace(
                id="run-1",
                status="running",
                last_event_id=None,
            )
        }

    async def append_event(self, event: Any) -> Any:
        self.next_event_id += 1
        event.id = self.next_event_id
        event.created_at = datetime.now(UTC)
        self.events[event.id] = event
        self.runs[event.run_id].last_event_id = event.id
        return event

    async def list_all_events(self, run_id: str, after_event_id: int) -> list[Any]:
        return [
            event
            for event in self.events.values()
            if event.run_id == run_id
        ]

    async def list_events_after(self, run_id: str, after_event_id: int) -> list[Any]:
        return [
            event
            for event in sorted(self.events.values(), key=lambda row: row.id)
            if event.run_id == run_id and event.id > after_event_id
        ]

    async def load_event_by_id(self, event_id: int) -> Any | None:
        return self.events.get(event_id)

    async def load_run_by_id(self, run_id: str) -> Any | None:
        return self.runs.get(run_id)


class RunEventsServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        run_events.clear_subscribers()

    async def test_append_event_returns_int_event_id_and_notifies_subscriber(self) -> None:
        store = _FakeStore()
        live_events = run_events.subscribe_to_live_events(
            "run-1",
            after_event_id=0,
            event_by_id_loader=store.load_event_by_id,
        )
        live_frame = asyncio.create_task(anext(live_events))
        await asyncio.sleep(0)

        event_id = await run_events.append_run_event(
            run_id="run-1",
            conversation_id="conversation-1",
            message_id="assistant-1",
            event=DeltaEvent(
                type="delta",
                runId="run-1",
                messageId="assistant-1",
                text="hello",
            ),
            appender=store.append_event,
        )

        frame = await asyncio.wait_for(live_frame, timeout=1)
        await live_events.aclose()

        persisted_id, payload = _decode_sse(frame)
        self.assertIsInstance(event_id, int)
        self.assertEqual(event_id, persisted_id)
        self.assertEqual(payload["type"], "delta")
        self.assertEqual(payload["runId"], "run-1")

    async def test_format_persisted_event_emits_id_and_parseable_payload(self) -> None:
        row = SimpleNamespace(
            id=42,
            payload={
                "type": "delta",
                "runId": "run-1",
                "messageId": "assistant-1",
                "text": "hello",
            },
        )

        frame = run_events.format_persisted_event(row)

        event_id, payload = _decode_sse(frame)
        self.assertEqual(event_id, 42)
        parsed = ChatStreamEventAdapter.validate_python(payload)
        self.assertEqual(parsed.type, "delta")
        self.assertEqual(parsed.run_id, "run-1")

    async def test_replay_events_after_skips_older_events(self) -> None:
        store = _FakeStore()
        for text in ("old", "newer", "newest"):
            await run_events.append_run_event(
                run_id="run-1",
                conversation_id="conversation-1",
                message_id="assistant-1",
                event=DeltaEvent(
                    type="delta",
                    runId="run-1",
                    messageId="assistant-1",
                    text=text,
                ),
                appender=store.append_event,
            )

        frames = [
            frame
            async for frame in run_events.replay_events_after(
                "run-1",
                1,
                event_loader=store.list_all_events,
            )
        ]

        decoded = [_decode_sse(frame) for frame in frames]
        self.assertEqual([event_id for event_id, _payload in decoded], [2, 3])
        self.assertEqual([payload["text"] for _event_id, payload in decoded], ["newer", "newest"])

    async def test_stream_run_events_replays_then_receives_live_append_and_ends_when_terminal(
        self,
    ) -> None:
        store = _FakeStore()
        await run_events.append_run_event(
            run_id="run-1",
            conversation_id="conversation-1",
            message_id="assistant-1",
            event=DeltaEvent(
                type="delta",
                runId="run-1",
                messageId="assistant-1",
                text="replay",
            ),
            appender=store.append_event,
        )

        stream = run_events.stream_run_events(
            "run-1",
            0,
            event_loader=store.list_events_after,
            event_by_id_loader=store.load_event_by_id,
            run_loader=store.load_run_by_id,
            poll_interval_seconds=0.01,
        )

        replay_frame = await asyncio.wait_for(anext(stream), timeout=1)
        next_live_frame = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)

        await run_events.append_run_event(
            run_id="run-1",
            conversation_id="conversation-1",
            message_id="assistant-1",
            event=DeltaEvent(
                type="delta",
                runId="run-1",
                messageId="assistant-1",
                text="live",
            ),
            appender=store.append_event,
        )
        live_frame = await asyncio.wait_for(next_live_frame, timeout=1)

        store.runs["run-1"].status = "completed"
        with self.assertRaises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), timeout=1)

        replay_id, replay_payload = _decode_sse(replay_frame)
        live_id, live_payload = _decode_sse(live_frame)
        self.assertEqual((replay_id, replay_payload["text"]), (1, "replay"))
        self.assertEqual((live_id, live_payload["text"]), (2, "live"))

    async def test_stream_run_events_polls_persisted_events_when_notification_is_missed(
        self,
    ) -> None:
        store = _FakeStore()
        stream = run_events.stream_run_events(
            "run-1",
            0,
            event_loader=store.list_events_after,
            event_by_id_loader=store.load_event_by_id,
            run_loader=store.load_run_by_id,
            poll_interval_seconds=0.01,
        )
        next_frame = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)

        event = SimpleNamespace(
            id=1,
            run_id="run-1",
            conversation_id="conversation-1",
            message_id="assistant-1",
            event_type="delta",
            payload={
                "type": "delta",
                "runId": "run-1",
                "messageId": "assistant-1",
                "text": "persisted-without-notify",
            },
            created_at=datetime.now(UTC),
        )
        store.events[event.id] = event
        store.runs["run-1"].last_event_id = event.id
        store.runs["run-1"].status = "completed"

        frame = await asyncio.wait_for(next_frame, timeout=1)
        with self.assertRaises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), timeout=1)

        event_id, payload = _decode_sse(frame)
        self.assertEqual(event_id, 1)
        self.assertEqual(payload["text"], "persisted-without-notify")

    async def test_stream_run_events_does_not_skip_missed_lower_id_event_on_later_wakeup(
        self,
    ) -> None:
        store = _FakeStore()
        stream = run_events.stream_run_events(
            "run-1",
            0,
            event_loader=store.list_events_after,
            event_by_id_loader=store.load_event_by_id,
            run_loader=store.load_run_by_id,
            poll_interval_seconds=1,
        )
        first_frame_task = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)

        missed_event = SimpleNamespace(
            id=1,
            run_id="run-1",
            conversation_id="conversation-1",
            message_id="assistant-1",
            event_type="delta",
            payload={
                "type": "delta",
                "runId": "run-1",
                "messageId": "assistant-1",
                "text": "missed",
            },
            created_at=datetime.now(UTC),
        )
        store.events[missed_event.id] = missed_event
        store.next_event_id = missed_event.id
        store.runs["run-1"].last_event_id = missed_event.id

        later_event_id = await run_events.append_run_event(
            run_id="run-1",
            conversation_id="conversation-1",
            message_id="assistant-1",
            event=DeltaEvent(
                type="delta",
                runId="run-1",
                messageId="assistant-1",
                text="later",
            ),
            appender=store.append_event,
        )
        self.assertEqual(later_event_id, 2)

        first_frame = await asyncio.wait_for(first_frame_task, timeout=1)
        second_frame = await asyncio.wait_for(anext(stream), timeout=1)
        store.runs["run-1"].status = "completed"
        with self.assertRaises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), timeout=1)

        first_id, first_payload = _decode_sse(first_frame)
        second_id, second_payload = _decode_sse(second_frame)
        self.assertEqual((first_id, first_payload["text"]), (1, "missed"))
        self.assertEqual((second_id, second_payload["text"]), (2, "later"))


if __name__ == "__main__":
    unittest.main()
