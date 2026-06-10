import asyncio
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient


class CancelStreamApiTest(unittest.TestCase):
    def test_cancel_stream_route_returns_no_content(self) -> None:
        from main import app

        cancelled_messages = []

        async def fake_cancel_run_by_assistant_message_id(message_id: str) -> None:
            cancelled_messages.append(message_id)

        with patch(
            "controller.chat.run_manager.cancel_run_by_assistant_message_id",
            fake_cancel_run_by_assistant_message_id,
        ):
            response = TestClient(app).post(
                "/api/chat/streams/cancel/assistant-1",
            )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(cancelled_messages, ["assistant-1"])


class _CancelSession:
    def __init__(self, *, run=None, message=None) -> None:
        self.run = run
        self.message = message
        self.commits = 0
        self.operations: list[str] = []
        self.events = []
        self.persisted_run_events = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, model, object_id):
        from model.message import Message

        if model is Message and self.message is not None and object_id == self.message.id:
            return self.message
        return None

    async def commit(self) -> None:
        self.commits += 1
        self.operations.append("commit")


class _CancelSessionFactory:
    def __init__(self, session: _CancelSession) -> None:
        self.session = session

    def __call__(self) -> _CancelSession:
        return self.session


class _LiveTask:
    def __init__(self) -> None:
        self.cancelled = False
        self.done_callbacks = []

    def done(self) -> bool:
        return False

    def cancel(self) -> None:
        self.cancelled = True

    def add_done_callback(self, callback) -> None:
        self.done_callbacks.append(callback)

    def finish(self) -> None:
        for callback in list(self.done_callbacks):
            callback(self)


class _ClosedTask:
    def __init__(self) -> None:
        self.done_callbacks = []

    def done(self) -> bool:
        return True

    def cancel(self) -> None:
        raise AssertionError("closed task should not be cancelled")

    def add_done_callback(self, callback) -> None:
        self.done_callbacks.append(callback)


class RunManagerCancelTest(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        from service import run_manager

        run_manager._tasks_by_run_id.clear()
        run_manager._run_id_by_assistant_message_id.clear()

    async def test_cancel_marks_run_done_and_cancels_live_task(self) -> None:
        from service import run_manager
        from service.run_manager import RunManagerDependencies

        now = datetime(2026, 6, 9, 10, 0, tzinfo=UTC)
        run = SimpleNamespace(
            id="run-1",
            conversation_id="conversation-1",
            assistant_message_id="assistant-1",
            status="running",
            cancel_requested_at=None,
            completed_at=None,
            updated_at=now,
        )
        message = SimpleNamespace(
            id="assistant-1",
            content="already persisted partial",
            reasoning="already persisted reasoning",
            status="streaming",
        )
        session = _CancelSession(run=run, message=message)
        task = _LiveTask()
        notifications = []

        async def fake_request_cancel(db_session, *, assistant_message_id: str):
            self.assertIs(db_session, session)
            self.assertEqual(assistant_message_id, "assistant-1")
            db_session.operations.append("request_cancel")
            run.cancel_requested_at = now
            return run

        async def fake_update_run_status(db_session, *, run_id, status, error=None):
            self.assertIs(db_session, session)
            self.assertEqual(run_id, "run-1")
            self.assertIsNone(error)
            db_session.operations.append(f"status:{status}")
            run.status = status
            run.completed_at = now
            return run

        async def fake_append_run_event_row(db_session, *, event):
            self.assertIs(db_session, session)
            event.id = 7
            db_session.events.append(event)
            db_session.operations.append(f"event:{event.event_type}")
            return event

        async def fake_list_run_events_after(db_session, *, run_id, after_event_id):
            self.assertIs(db_session, session)
            self.assertEqual(run_id, "run-1")
            self.assertEqual(after_event_id, 0)
            db_session.operations.append("load_events")
            return db_session.persisted_run_events

        run_manager._tasks_by_run_id["run-1"] = task
        run_manager._run_id_by_assistant_message_id["assistant-1"] = "run-1"
        deps = RunManagerDependencies(
            async_session_factory=_CancelSessionFactory(session),
            request_cancel=fake_request_cancel,
            update_run_status=fake_update_run_status,
            append_run_event_row=fake_append_run_event_row,
            list_run_events_after=fake_list_run_events_after,
            notify_run_event=lambda run_id, event_id: notifications.append(
                (run_id, event_id)
            ),
        )

        result = await run_manager.cancel_run_by_assistant_message_id(
            "assistant-1",
            dependencies=deps,
        )

        self.assertIs(result, run)
        self.assertTrue(task.cancelled)
        self.assertEqual(message.status, "done")
        self.assertEqual(message.content, "already persisted partial")
        self.assertEqual(message.reasoning, "already persisted reasoning")
        self.assertEqual(run.status, "completed")
        self.assertEqual(
            session.operations,
            ["request_cancel", "load_events", "status:completed", "event:done", "commit"],
        )
        self.assertEqual(session.events[0].event_type, "done")
        self.assertEqual(session.events[0].payload["runId"], "run-1")
        self.assertEqual(session.events[0].payload["messageId"], "assistant-1")
        self.assertEqual(notifications, [("run-1", 7)])

    async def test_cancel_persists_partial_text_from_run_events(self) -> None:
        from service import run_manager
        from service.run_manager import RunManagerDependencies

        now = datetime(2026, 6, 9, 10, 0, tzinfo=UTC)
        run = SimpleNamespace(
            id="run-1",
            conversation_id="conversation-1",
            assistant_message_id="assistant-1",
            status="running",
            cancel_requested_at=None,
            completed_at=None,
            updated_at=now,
        )
        message = SimpleNamespace(
            id="assistant-1",
            content="",
            reasoning="",
            status="streaming",
        )
        session = _CancelSession(run=run, message=message)
        session.persisted_run_events = [
            SimpleNamespace(
                id=1,
                event_type="delta",
                payload={
                    "type": "delta",
                    "runId": "run-1",
                    "messageId": "assistant-1",
                    "text": "hello ",
                },
            ),
            SimpleNamespace(
                id=2,
                event_type="reasoning",
                payload={
                    "type": "reasoning",
                    "runId": "run-1",
                    "messageId": "assistant-1",
                    "text": "think ",
                },
            ),
            SimpleNamespace(
                id=3,
                event_type="delta",
                payload={
                    "type": "delta",
                    "runId": "run-1",
                    "messageId": "assistant-1",
                    "text": "world",
                },
            ),
            SimpleNamespace(
                id=4,
                event_type="delta",
                payload={
                    "type": "delta",
                    "runId": "run-1",
                    "messageId": "other-message",
                    "text": "ignored",
                },
            ),
        ]

        async def fake_request_cancel(db_session, *, assistant_message_id: str):
            return run

        async def fake_update_run_status(db_session, *, run_id, status, error=None):
            run.status = status
            return run

        async def fake_append_run_event_row(db_session, *, event):
            event.id = 8
            return event

        async def fake_list_run_events_after(db_session, *, run_id, after_event_id):
            return db_session.persisted_run_events

        deps = RunManagerDependencies(
            async_session_factory=_CancelSessionFactory(session),
            request_cancel=fake_request_cancel,
            update_run_status=fake_update_run_status,
            append_run_event_row=fake_append_run_event_row,
            list_run_events_after=fake_list_run_events_after,
            notify_run_event=lambda run_id, event_id: None,
        )

        await run_manager.cancel_run_by_assistant_message_id(
            "assistant-1",
            dependencies=deps,
        )

        self.assertEqual(message.content, "hello world")
        self.assertEqual(message.reasoning, "think ")
        self.assertEqual(message.status, "done")

    async def test_cancel_is_idempotent_when_no_active_run_exists(self) -> None:
        from service import run_manager
        from service.run_manager import RunManagerDependencies

        session = _CancelSession()
        task = _LiveTask()

        async def fake_request_cancel(db_session, *, assistant_message_id: str):
            db_session.operations.append("request_cancel")
            return None

        run_manager._tasks_by_run_id["run-1"] = task
        run_manager._run_id_by_assistant_message_id["assistant-1"] = "run-1"
        deps = RunManagerDependencies(
            async_session_factory=_CancelSessionFactory(session),
            request_cancel=fake_request_cancel,
            notify_run_event=lambda run_id, event_id: None,
        )

        result = await run_manager.cancel_run_by_assistant_message_id(
            "assistant-1",
            dependencies=deps,
        )

        self.assertIsNone(result)
        self.assertFalse(task.cancelled)
        self.assertEqual(session.operations, ["request_cancel"])
        self.assertEqual(session.commits, 0)

    async def test_start_chat_run_registers_and_cleans_task_mappings(self) -> None:
        from schema.chat import StreamChatRequest
        from service import run_manager
        from service.run_manager import RunManagerDependencies, start_chat_run

        session = _CancelSession()
        session.conversations = {"conversation-1": object()}
        session.messages = []
        session.runs = []
        task = _LiveTask()

        async def fake_get_conversation_by_id(db_session, conversation_id):
            return db_session.conversations.get(conversation_id)

        async def fake_create_message(db_session, message):
            db_session.messages.append(message)
            return message

        async def fake_create_run(db_session, *, run):
            db_session.runs.append(run)
            return run

        async def fake_append_run_event(**kwargs):
            return 1

        async def fake_stream_run_events(run_id, after_event_id):
            yield "data: {}\n\n"

        def fake_create_task(coro):
            coro.close()
            return task

        deps = RunManagerDependencies(
            async_session_factory=_CancelSessionFactory(session),
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
        await anext(stream)
        await stream.aclose()

        run_id = session.runs[0].id
        assistant_message_id = session.messages[1].id
        self.assertIs(run_manager._tasks_by_run_id[run_id], task)
        self.assertEqual(
            run_manager._run_id_by_assistant_message_id[assistant_message_id],
            run_id,
        )

        task.finish()

        self.assertNotIn(run_id, run_manager._tasks_by_run_id)
        self.assertNotIn(
            assistant_message_id,
            run_manager._run_id_by_assistant_message_id,
        )

    async def test_execute_run_cancelled_error_does_not_append_error(self) -> None:
        from schema.chat import StreamChatRequest
        from service.run_manager import (
            RunManagerDependencies,
            _PreparedRun,
            _execute_run,
        )

        session = _CancelSession()

        async def fake_stream_executor(**kwargs):
            raise asyncio.CancelledError()
            if False:
                yield ""

        async def fake_update_run_status(db_session, *, run_id, status, error=None):
            db_session.operations.append(f"status:{status}")
            return SimpleNamespace(id=run_id, status=status, error=error)

        async def fake_append_run_event_row(db_session, *, event):
            event.id = 1
            db_session.operations.append(f"event:{event.event_type}")
            return event

        deps = RunManagerDependencies(
            async_session_factory=_CancelSessionFactory(session),
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

        self.assertEqual(session.operations, [])


if __name__ == "__main__":
    unittest.main()
