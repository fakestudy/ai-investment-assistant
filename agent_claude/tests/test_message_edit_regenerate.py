import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from model.message import Message


def _message(
    *,
    message_id: str,
    conversation_id: str = "conversation-1",
    seq: int,
    role: str,
    content: str,
    status: str = "done",
) -> Message:
    return Message(
        id=message_id,
        seq=seq,
        conversation_id=conversation_id,
        role=role,
        content=content,
        reasoning="",
        status=status,
        created_at=datetime(2026, 6, 9, 0, seq, tzinfo=UTC),
    )


class _ControllerSession:
    def __init__(self) -> None:
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self) -> None:
        self.commits += 1


class _ControllerSessionFactory:
    def __init__(self, session: _ControllerSession) -> None:
        self.session = session

    def __call__(self):
        return self.session


class MessageEditApiTest(unittest.TestCase):
    def test_patch_message_returns_edited_user_message(self) -> None:
        from main import app
        from unittest.mock import patch

        session = _ControllerSession()

        async def fake_edit_user_message(db_session, *, message_id: str, content: str):
            self.assertIs(db_session, session)
            return _message(
                message_id=message_id,
                seq=1,
                role="user",
                content=content,
            )

        with (
            patch("controller.chat.AsyncSessionLocal", _ControllerSessionFactory(session)),
            patch(
                "controller.chat.message_repository.edit_user_message",
                fake_edit_user_message,
            ),
        ):
            response = TestClient(app).patch(
                "/api/messages/user-1",
                json={"content": "updated question"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.commits, 1)
        self.assertEqual(
            response.json(),
            {
                "id": "user-1",
                "conversationId": "conversation-1",
                "role": "user",
                "content": "updated question",
                "toolInvocations": [],
                "timelineParts": [],
                "status": "done",
                "createdAt": "2026-06-09T00:01:00Z",
            },
        )

    def test_patch_message_rejects_blank_content(self) -> None:
        from main import app

        response = TestClient(app).patch(
            "/api/messages/user-1",
            json={"content": "   \n\t"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Message content cannot be blank"})

    def test_patch_message_rejects_non_user_message(self) -> None:
        from main import app
        from unittest.mock import patch

        session = _ControllerSession()

        async def fake_edit_user_message(db_session, *, message_id: str, content: str):
            raise ValueError("Only user messages can be edited")

        with (
            patch("controller.chat.AsyncSessionLocal", _ControllerSessionFactory(session)),
            patch(
                "controller.chat.message_repository.edit_user_message",
                fake_edit_user_message,
            ),
        ):
            response = TestClient(app).patch(
                "/api/messages/assistant-1",
                json={"content": "updated"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Only user messages can be edited"})
        self.assertEqual(session.commits, 0)

    def test_patch_message_returns_404_when_missing(self) -> None:
        from main import app
        from unittest.mock import patch

        session = _ControllerSession()

        async def fake_edit_user_message(db_session, *, message_id: str, content: str):
            raise LookupError("Message not found")

        with (
            patch("controller.chat.AsyncSessionLocal", _ControllerSessionFactory(session)),
            patch(
                "controller.chat.message_repository.edit_user_message",
                fake_edit_user_message,
            ),
        ):
            response = TestClient(app).patch(
                "/api/messages/missing-message",
                json={"content": "updated"},
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Message not found"})
        self.assertEqual(session.commits, 0)


class _RunSession:
    def __init__(self, messages: list[Message]) -> None:
        self.conversations = {"conversation-1": object()}
        self.messages = list(messages)
        self.created_messages: list[Message] = []
        self.runs = []
        self.deleted_after: list[tuple[str, int]] = []
        self.invalidated_sessions: list[str] = []
        self.commits = 0
        self.operations: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self) -> None:
        self.commits += 1
        self.operations.append("commit")


class _RunSessionFactory:
    def __init__(self, session: _RunSession) -> None:
        self.session = session

    def __call__(self) -> _RunSession:
        return self.session


def _run_dependencies(session: _RunSession, stream_executor):
    from service.run_manager import RunManagerDependencies

    async def fake_get_conversation_by_id(db_session, conversation_id):
        return db_session.conversations.get(conversation_id)

    async def fake_create_message(db_session, message):
        if getattr(message, "seq", None) is None:
            message.seq = max((row.seq for row in db_session.messages), default=0) + 1
        db_session.messages.append(message)
        db_session.created_messages.append(message)
        return message

    async def fake_create_run(db_session, *, run):
        db_session.runs.append(run)
        return run

    async def fake_append_run_event(**kwargs):
        return 1

    async def fake_get_message_in_conversation(
        db_session,
        *,
        conversation_id: str,
        message_id: str,
    ):
        return next(
            (
                row
                for row in db_session.messages
                if row.conversation_id == conversation_id and row.id == message_id
            ),
            None,
        )

    async def fake_get_previous_user_message_before_seq(
        db_session,
        *,
        conversation_id: str,
        seq: int,
    ):
        users = [
            row
            for row in db_session.messages
            if row.conversation_id == conversation_id
            and row.role == "user"
            and row.seq < seq
        ]
        return max(users, key=lambda row: row.seq, default=None)

    async def fake_get_messages_by_conversation_id(db_session, conversation_id: str):
        return sorted(
            [
                row
                for row in db_session.messages
                if row.conversation_id == conversation_id
            ],
            key=lambda row: row.seq,
        )

    async def fake_delete_messages_after_seq(
        db_session,
        *,
        conversation_id: str,
        seq: int,
    ):
        db_session.deleted_after.append((conversation_id, seq))
        db_session.messages = [
            row
            for row in db_session.messages
            if row.conversation_id != conversation_id or row.seq <= seq
        ]

    async def fake_delete_agent_session_by_conversation_id(
        db_session,
        conversation_id: str,
    ):
        db_session.invalidated_sessions.append(conversation_id)

    async def fake_update_run_status(db_session, *, run_id, status, error=None):
        db_session.operations.append(f"status:{status}")
        return SimpleNamespace(id=run_id, status=status, error=error)

    async def fake_append_run_event_row(db_session, *, event):
        event.id = 1
        db_session.operations.append(f"event:{event.event_type}")
        return event

    return RunManagerDependencies(
        async_session_factory=_RunSessionFactory(session),
        get_conversation_by_id=fake_get_conversation_by_id,
        create_message=fake_create_message,
        create_run=fake_create_run,
        append_run_event=fake_append_run_event,
        get_message_in_conversation=fake_get_message_in_conversation,
        get_previous_user_message_before_seq=fake_get_previous_user_message_before_seq,
        get_messages_by_conversation_id=fake_get_messages_by_conversation_id,
        delete_messages_after_seq=fake_delete_messages_after_seq,
        delete_agent_session_by_conversation_id=(
            fake_delete_agent_session_by_conversation_id
        ),
        update_run_status=fake_update_run_status,
        append_run_event_row=fake_append_run_event_row,
        stream_executor=stream_executor,
        notify_run_event=lambda run_id, event_id: None,
    )


class RunManagerBranchTest(unittest.IsolatedAsyncioTestCase):
    async def test_parent_continuation_reuses_parent_user_and_restarts_branch(
        self,
    ) -> None:
        from schema.chat import StreamChatRequest
        from service.run_manager import _execute_run, _prepare_run

        session = _RunSession(
            [
                _message(
                    message_id="user-1",
                    seq=1,
                    role="user",
                    content="first question",
                ),
                _message(
                    message_id="assistant-1",
                    seq=2,
                    role="assistant",
                    content="first answer",
                ),
                _message(
                    message_id="user-2",
                    seq=3,
                    role="user",
                    content="edited parent",
                ),
                _message(
                    message_id="assistant-2",
                    seq=4,
                    role="assistant",
                    content="stale answer",
                ),
                _message(
                    message_id="user-3",
                    seq=5,
                    role="user",
                    content="stale follow-up",
                ),
            ]
        )
        captured_executor_kwargs: dict[str, Any] = {}

        async def fake_stream_executor(**kwargs):
            captured_executor_kwargs.update(kwargs)
            yield 'data: {"type":"done","messageId":"assistant-new"}\n\n'

        deps = _run_dependencies(session, fake_stream_executor)
        req = StreamChatRequest(
            conversationId="conversation-1",
            message="request body must not be used",
            parentMessageId="user-2",
        )

        prepared = await _prepare_run(req, deps)
        await _execute_run(prepared, req, deps)

        self.assertEqual([row.role for row in session.created_messages], ["assistant"])
        self.assertEqual(session.deleted_after, [("conversation-1", 3)])
        self.assertEqual(session.invalidated_sessions, ["conversation-1"])
        self.assertNotIn("assistant-2", [row.id for row in session.messages])
        self.assertNotIn("user-3", [row.id for row in session.messages])
        self.assertEqual(captured_executor_kwargs["message"], "edited parent")
        self.assertEqual(
            captured_executor_kwargs["executor_prompt"],
            (
                "Previous conversation:\n"
                "User: first question\n"
                "Assistant: first answer\n\n"
                "Current user request:\n"
                "edited parent"
            ),
        )
        self.assertFalse(captured_executor_kwargs["resume_sdk_session"])
        self.assertFalse(captured_executor_kwargs["create_user_message"])

    async def test_regenerate_reuses_previous_user_and_restarts_branch(self) -> None:
        from schema.chat import StreamChatRequest
        from service.run_manager import _execute_run, _prepare_run

        session = _RunSession(
            [
                _message(
                    message_id="user-1",
                    seq=1,
                    role="user",
                    content="first question",
                ),
                _message(
                    message_id="assistant-1",
                    seq=2,
                    role="assistant",
                    content="first answer",
                ),
                _message(
                    message_id="user-2",
                    seq=3,
                    role="user",
                    content="retry this",
                ),
                _message(
                    message_id="assistant-2",
                    seq=4,
                    role="assistant",
                    content="bad answer",
                ),
                _message(
                    message_id="assistant-3",
                    seq=5,
                    role="assistant",
                    content="stale later answer",
                ),
            ]
        )
        captured_executor_kwargs: dict[str, Any] = {}

        async def fake_stream_executor(**kwargs):
            captured_executor_kwargs.update(kwargs)
            yield 'data: {"type":"done","messageId":"assistant-new"}\n\n'

        deps = _run_dependencies(session, fake_stream_executor)
        req = StreamChatRequest(
            conversationId="conversation-1",
            message="",
            regenerateFromMessageId="assistant-2",
        )

        prepared = await _prepare_run(req, deps)
        await _execute_run(prepared, req, deps)

        self.assertEqual([row.role for row in session.created_messages], ["assistant"])
        self.assertEqual(session.deleted_after, [("conversation-1", 3)])
        self.assertEqual(session.invalidated_sessions, ["conversation-1"])
        self.assertNotIn("assistant-2", [row.id for row in session.messages])
        self.assertNotIn("assistant-3", [row.id for row in session.messages])
        self.assertEqual(captured_executor_kwargs["message"], "retry this")
        self.assertEqual(
            captured_executor_kwargs["executor_prompt"],
            (
                "Previous conversation:\n"
                "User: first question\n"
                "Assistant: first answer\n\n"
                "Current user request:\n"
                "retry this"
            ),
        )
        self.assertFalse(captured_executor_kwargs["resume_sdk_session"])
        self.assertFalse(captured_executor_kwargs["create_user_message"])


class _ChatStreamSession:
    def __init__(self) -> None:
        self.conversation = object()
        self.message = _message(
            message_id="assistant-1",
            seq=1,
            role="assistant",
            content="",
            status="streaming",
        )
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, model, object_id):
        if model is Message and object_id == self.message.id:
            return self.message
        return None

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1


class _ChatStreamSessionFactory:
    def __init__(self, session: _ChatStreamSession) -> None:
        self.session = session

    def __call__(self) -> _ChatStreamSession:
        return self.session


def _decode_sse(frame: str) -> dict[str, Any]:
    return json.loads(frame.removeprefix("data: ").strip())


class ChatStreamBranchRestartTest(unittest.IsolatedAsyncioTestCase):
    async def test_branch_restart_uses_executor_prompt_and_does_not_resume_sdk_session(
        self,
    ) -> None:
        from service import chat_stream
        from service.chat_stream import ChatStreamDependencies

        session = _ChatStreamSession()
        captured_stream_query: dict[str, Any] = {}

        async def fake_get_conversation_by_id(db_session, conversation_id):
            return db_session.conversation

        async def fake_get_agent_session_by_conversation_id(db_session, conversation_id):
            raise AssertionError("branch restart must not load old SDK session")

        async def fake_stream_query(*, prompt, session_store, resume):
            captured_stream_query["prompt"] = prompt
            captured_stream_query["resume"] = resume
            if False:
                yield None

        async def fake_upsert_agent_session(*args, **kwargs):
            raise AssertionError("no SDK session id was emitted")

        deps = ChatStreamDependencies(
            async_session_factory=_ChatStreamSessionFactory(session),
            get_conversation_by_id=fake_get_conversation_by_id,
            get_agent_session_by_conversation_id=fake_get_agent_session_by_conversation_id,
            upsert_agent_session=fake_upsert_agent_session,
            stream_query=fake_stream_query,
            update_conversation_title=lambda *args, **kwargs: None,
        )

        events = [
            _decode_sse(frame)
            async for frame in chat_stream.stream_chat(
                conversation_id="conversation-1",
                message="current request",
                precreated_assistant_message_id="assistant-1",
                create_user_message=False,
                emit_message_created=False,
                executor_prompt=(
                    "Previous conversation:\n"
                    "User: earlier\n"
                    "Assistant: answer\n\n"
                    "Current user request:\n"
                    "current request"
                ),
                resume_sdk_session=False,
                dependencies=deps,
            )
        ]

        self.assertEqual(
            captured_stream_query,
            {
                "prompt": (
                    "Previous conversation:\n"
                    "User: earlier\n"
                    "Assistant: answer\n\n"
                    "Current user request:\n"
                    "current request"
                ),
                "resume": None,
            },
        )
        self.assertEqual(events, [{"type": "done", "messageId": "assistant-1"}])
        self.assertEqual(session.message.status, "done")


if __name__ == "__main__":
    unittest.main()
