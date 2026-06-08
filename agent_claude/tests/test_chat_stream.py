import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import model.conversation  # noqa: F401
from pydantic import TypeAdapter

from model.message import Message


class _FakeSession:
    def __init__(self) -> None:
        self.messages: dict[str, Message] = {}
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def add(self, row) -> None:
        if isinstance(row, Message):
            self.messages[row.id] = row
            return
        raise AssertionError(f"unexpected row type: {type(row)!r}")

    async def get(self, model, object_id: str):
        if model is Message:
            return self.messages.get(object_id)
        return None

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class _FakeSessionFactory:
    def __init__(self) -> None:
        self.session = _FakeSession()

    def __call__(self) -> _FakeSession:
        return self.session


def _decode_sse(frame: str) -> dict:
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    return json.loads(frame.removeprefix("data: ").strip())


class ChatStreamServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_stream_chat_yields_frontend_sse_and_persists_success(self) -> None:
        from schema.chat import ChatStreamEvent
        from service import chat as chat_service

        factory = _FakeSessionFactory()
        captured_resume: list[str | None] = []
        upserts: list[tuple[str, str]] = []

        async def fake_stream_query(*, prompt, session_store, resume):
            self.assertEqual(prompt, "hello")
            self.assertIsNotNone(session_store)
            captured_resume.append(resume)
            yield SimpleNamespace(
                session_id="sdk-session-new",
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "think "},
                },
            )
            yield SimpleNamespace(
                session_id="sdk-session-new",
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "answer"},
                },
            )
            yield SimpleNamespace(
                session_id="sdk-session-new",
                subtype="success",
                is_error=False,
            )

        async def fake_get_agent_session_by_conversation_id(session, conversation_id):
            self.assertEqual(conversation_id, "conversation-1")
            return SimpleNamespace(sdk_session_id="sdk-session-existing")

        async def fake_upsert_agent_session(session, *, conversation_id, sdk_session_id):
            upserts.append((conversation_id, sdk_session_id))

        with (
            patch.object(chat_service, "AsyncSessionLocal", factory),
            patch.object(chat_service, "stream_query", fake_stream_query),
            patch.object(
                chat_service,
                "get_agent_session_by_conversation_id",
                fake_get_agent_session_by_conversation_id,
            ),
            patch.object(chat_service, "upsert_agent_session", fake_upsert_agent_session),
        ):
            frames = [
                frame
                async for frame in chat_service.stream_chat(
                    conversation_id="conversation-1",
                    message="hello",
                )
            ]

        events = [_decode_sse(frame) for frame in frames]
        TypeAdapter(list[ChatStreamEvent]).validate_python(events)

        self.assertEqual(
            [event["type"] for event in events],
            ["message_created", "reasoning", "delta", "done"],
        )
        self.assertEqual(events[0]["message"]["conversationId"], "conversation-1")
        self.assertEqual(events[0]["message"]["role"], "assistant")
        self.assertEqual(events[0]["message"]["status"], "streaming")
        self.assertEqual(events[1]["text"], "think ")
        self.assertEqual(events[2]["text"], "answer")
        self.assertEqual(events[3]["messageId"], events[0]["message"]["id"])
        self.assertEqual(captured_resume, ["sdk-session-existing"])
        self.assertEqual(upserts, [("conversation-1", "sdk-session-new")])

        assistant = factory.session.messages[events[0]["message"]["id"]]
        self.assertEqual(assistant.content, "answer")
        self.assertEqual(assistant.reasoning, "think ")
        self.assertEqual(assistant.status, "done")

    async def test_stream_chat_marks_assistant_error_and_yields_error_event(self) -> None:
        from schema.chat import ChatStreamEvent
        from service import chat as chat_service

        factory = _FakeSessionFactory()

        async def fake_stream_query(*, prompt, session_store, resume):
            raise RuntimeError("sdk failed")
            yield

        async def fake_get_agent_session_by_conversation_id(session, conversation_id):
            return None

        async def fake_upsert_agent_session(session, *, conversation_id, sdk_session_id):
            raise AssertionError("should not upsert failed stream without session id")

        with (
            patch.object(chat_service, "AsyncSessionLocal", factory),
            patch.object(chat_service, "stream_query", fake_stream_query),
            patch.object(
                chat_service,
                "get_agent_session_by_conversation_id",
                fake_get_agent_session_by_conversation_id,
            ),
            patch.object(chat_service, "upsert_agent_session", fake_upsert_agent_session),
        ):
            frames = [
                frame
                async for frame in chat_service.stream_chat(
                    conversation_id="conversation-1",
                    message="hello",
                )
            ]

        events = [_decode_sse(frame) for frame in frames]
        TypeAdapter(list[ChatStreamEvent]).validate_python(events)

        self.assertEqual([event["type"] for event in events], ["message_created", "error"])
        self.assertEqual(events[1]["messageId"], events[0]["message"]["id"])
        self.assertEqual(events[1]["message"], "sdk failed")

        assistant = factory.session.messages[events[0]["message"]["id"]]
        self.assertEqual(assistant.status, "error")

    def test_controller_returns_text_event_stream_response(self) -> None:
        from controller.chat import run_stream_chat
        from schema.chat import StreamChatRequest
        from starlette.responses import StreamingResponse

        response = asyncio.run(
            run_stream_chat(
                StreamChatRequest(conversationId="conversation-1", message="hello")
            )
        )

        self.assertIsInstance(response, StreamingResponse)
        self.assertEqual(response.media_type, "text/event-stream")

    def test_stream_event_schema_keeps_tool_and_title_compatibility(self) -> None:
        from schema.chat import ChatStreamEvent

        adapter = TypeAdapter(ChatStreamEvent)

        tool_call = adapter.validate_python(
            {
                "type": "tool_call",
                "runId": "run-1",
                "messageId": "assistant-1",
                "invocation": {
                    "id": "tool-1",
                    "messageId": "assistant-1",
                    "toolName": "web_search",
                    "args": {"query": "AAPL"},
                    "status": "running",
                },
            }
        )
        title = adapter.validate_python(
            {
                "type": "title",
                "runId": "run-1",
                "conversationId": "conversation-1",
                "title": "Apple analysis",
            }
        )

        self.assertEqual(tool_call.type, "tool_call")
        self.assertEqual(title.type, "title")


if __name__ == "__main__":
    unittest.main()
