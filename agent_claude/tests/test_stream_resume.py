import json
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient


def request_payload(req):
    if hasattr(req, "model_dump"):
        return req.model_dump(by_alias=True)
    if isinstance(req, dict):
        return req
    return vars(req)


class StreamResumeApiTest(unittest.TestCase):
    def test_resume_stream_replays_events_after_cursor(self) -> None:
        from main import app

        captured_requests = []

        async def fake_resume_chat_stream(req):
            captured_requests.append(req)
            yield (
                'id: 13\ndata: {"type":"delta","runId":"run-1",'
                '"messageId":"assistant-1","text":"hello"}\n\n'
            )

        with patch(
            "controller.chat.resume_chat_stream",
            fake_resume_chat_stream,
            create=True,
        ):
            response = TestClient(app).post(
                "/api/chat/stream/resume",
                json={"runId": "run-1", "afterEventId": 12},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        payload = request_payload(captured_requests[0])
        self.assertEqual(payload["runId"], "run-1")
        self.assertEqual(payload["afterEventId"], 12)
        self.assertIn("id: 13", response.text)
        self.assertIn('"delta"', response.text)


class _FakeSession:
    def __init__(self) -> None:
        self.conversations = {"conversation-1": object()}
        self.messages = []
        self.runs = []
        self.commits = 0
        self.operations = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self) -> None:
        self.commits += 1
        self.operations.append("commit")


class _FakeSessionFactory:
    def __init__(self) -> None:
        self.session = _FakeSession()

    def __call__(self) -> _FakeSession:
        return self.session


class _ClosedTask:
    def add_done_callback(self, callback) -> None:
        callback(self)


def _decode_sse(frame: str) -> tuple[int, dict[str, Any]]:
    lines = frame.splitlines()
    event_id = int(
        next(line.removeprefix("id: ") for line in lines if line.startswith("id: "))
    )
    payload = json.loads(
        next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
    )
    return event_id, payload


class RunManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_chat_run_creates_run_created_then_message_created_events(
        self,
    ) -> None:
        from schema.chat import StreamChatRequest
        from service import run_events
        from service.run_manager import RunManagerDependencies, start_chat_run

        factory = _FakeSessionFactory()
        persisted_events = []

        async def fake_get_conversation_by_id(session, conversation_id):
            return session.conversations.get(conversation_id)

        async def fake_create_message(session, message):
            session.messages.append(message)
            return message

        async def fake_create_run(session, *, run):
            session.runs.append(run)
            return run

        async def fake_append_run_event(
            *,
            run_id,
            conversation_id,
            message_id,
            event,
        ):
            payload = event.model_dump(by_alias=True, exclude_none=True)
            payload["runId"] = run_id
            row = SimpleNamespace(
                id=len(persisted_events) + 1,
                run_id=run_id,
                conversation_id=conversation_id,
                message_id=message_id,
                event_type=payload["type"],
                payload=payload,
            )
            persisted_events.append(row)
            return row.id

        async def fake_stream_run_events(run_id, after_event_id):
            for event in persisted_events:
                if event.run_id == run_id and event.id > after_event_id:
                    yield run_events.format_persisted_event(event)

        def fake_create_task(coro):
            coro.close()
            return _ClosedTask()

        deps = RunManagerDependencies(
            async_session_factory=factory,
            get_conversation_by_id=fake_get_conversation_by_id,
            create_message=fake_create_message,
            create_run=fake_create_run,
            append_run_event=fake_append_run_event,
            stream_run_events=fake_stream_run_events,
            create_task=fake_create_task,
        )

        stream = start_chat_run(
            StreamChatRequest(conversationId="conversation-1", message="hello"),
            dependencies=deps,
        )
        run_created_frame = await anext(stream)
        message_created_frame = await anext(stream)
        await stream.aclose()

        run_event_id, run_payload = _decode_sse(run_created_frame)
        message_event_id, message_payload = _decode_sse(message_created_frame)
        self.assertEqual(run_event_id, 1)
        self.assertEqual(run_payload["type"], "run_created")
        self.assertEqual(run_payload["runId"], factory.session.runs[0].id)
        self.assertEqual(run_payload["assistantMessageId"], factory.session.messages[1].id)
        self.assertEqual(message_event_id, 2)
        self.assertEqual(message_payload["type"], "message_created")
        self.assertEqual(message_payload["runId"], factory.session.runs[0].id)
        self.assertEqual(message_payload["message"]["id"], factory.session.messages[1].id)
        self.assertEqual(
            [message.role for message in factory.session.messages],
            ["user", "assistant"],
        )
        self.assertEqual(factory.session.messages[1].status, "streaming")
        self.assertEqual(factory.session.runs[0].status, "running")
        self.assertEqual(factory.session.commits, 1)

    async def test_execute_run_commits_terminal_status_and_event_before_notify(
        self,
    ) -> None:
        from schema.chat import StreamChatRequest
        from service.run_manager import (
            RunManagerDependencies,
            _PreparedRun,
            _execute_run,
        )

        factory = _FakeSessionFactory()
        notifications = []

        async def fake_stream_executor(**kwargs):
            yield 'data: {"type":"done","messageId":"assistant-1"}\n\n'

        async def fake_update_run_status(session, *, run_id, status, error=None):
            session.operations.append(f"status:{status}")
            return SimpleNamespace(id=run_id, status=status, error=error)

        async def fake_append_run_event_row(session, *, event):
            event.id = 1
            session.operations.append(f"event:{event.event_type}")
            return event

        deps = RunManagerDependencies(
            async_session_factory=factory,
            update_run_status=fake_update_run_status,
            append_run_event_row=fake_append_run_event_row,
            stream_executor=fake_stream_executor,
            notify_run_event=lambda run_id, event_id: notifications.append(
                f"notify:{run_id}:{event_id}"
            ),
        )

        await _execute_run(
            _PreparedRun(
                run_id="run-1",
                conversation_id="conversation-1",
                assistant_message_id="assistant-1",
            ),
            StreamChatRequest(conversationId="conversation-1", message="hello"),
            deps,
        )

        self.assertEqual(
            factory.session.operations,
            ["status:completed", "event:done", "commit"],
        )
        self.assertEqual(notifications, ["notify:run-1:1"])

    async def test_execute_run_appends_done_when_executor_has_no_terminal_event(
        self,
    ) -> None:
        from schema.chat import StreamChatRequest
        from service.run_manager import (
            RunManagerDependencies,
            _PreparedRun,
            _execute_run,
        )

        factory = _FakeSessionFactory()
        appended_event_types = []

        async def fake_stream_executor(**kwargs):
            if False:
                yield ""

        async def fake_update_run_status(session, *, run_id, status, error=None):
            session.operations.append(f"status:{status}")
            return SimpleNamespace(id=run_id, status=status, error=error)

        async def fake_append_run_event_row(session, *, event):
            event.id = 1
            appended_event_types.append(event.event_type)
            return event

        deps = RunManagerDependencies(
            async_session_factory=factory,
            update_run_status=fake_update_run_status,
            append_run_event_row=fake_append_run_event_row,
            stream_executor=fake_stream_executor,
            notify_run_event=lambda run_id, event_id: None,
        )

        await _execute_run(
            _PreparedRun(
                run_id="run-1",
                conversation_id="conversation-1",
                assistant_message_id="assistant-1",
            ),
            StreamChatRequest(conversationId="conversation-1", message="hello"),
            deps,
        )

        self.assertEqual(factory.session.operations, ["status:completed", "commit"])
        self.assertEqual(appended_event_types, ["done"])


if __name__ == "__main__":
    unittest.main()
