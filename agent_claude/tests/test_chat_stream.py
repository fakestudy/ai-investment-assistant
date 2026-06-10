import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import model.conversation  # noqa: F401
from pydantic import TypeAdapter

from tests.chat_stream_test_helpers import (
    FakeChatStreamSessionFactory,
    decode_sse,
    fake_get_conversation_by_id,
)


_FakeSessionFactory = FakeChatStreamSessionFactory
_decode_sse = decode_sse
_fake_get_conversation_by_id = fake_get_conversation_by_id


class ChatStreamServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_stream_chat_yields_error_when_conversation_is_missing(self) -> None:
        from schema.chat import ChatStreamResponse
        from service import chat as chat_service

        factory = _FakeSessionFactory()

        async def fake_stream_query(*, prompt, session_store, resume):
            raise AssertionError("stream_query should not run for a missing conversation")
            yield

        with (
            patch.object(chat_service, "AsyncSessionLocal", factory),
            patch.object(
                chat_service,
                "get_conversation_by_id",
                _fake_get_conversation_by_id,
            ),
            patch.object(chat_service, "stream_query", fake_stream_query),
        ):
            events = [
                _decode_sse(frame)
                async for frame in chat_service.stream_chat(
                    conversation_id="missing-conversation",
                    message="hello",
                )
            ]

        TypeAdapter(list[ChatStreamResponse]).validate_python(events)
        self.assertEqual(events, [{"type": "error", "message": "Conversation not found"}])
        self.assertEqual(factory.session.messages, {})
        self.assertEqual(factory.session.commits, 0)

    async def test_stream_chat_yields_frontend_sse_and_persists_success(self) -> None:
        from schema.chat import ChatStreamResponse
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
            patch.object(
                chat_service,
                "get_conversation_by_id",
                _fake_get_conversation_by_id,
            ),
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
        TypeAdapter(list[ChatStreamResponse]).validate_python(events)

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
        from schema.chat import ChatStreamResponse
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
            patch.object(
                chat_service,
                "get_conversation_by_id",
                _fake_get_conversation_by_id,
            ),
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
        TypeAdapter(list[ChatStreamResponse]).validate_python(events)

        self.assertEqual([event["type"] for event in events], ["message_created", "error"])
        self.assertEqual(events[1]["messageId"], events[0]["message"]["id"])
        self.assertEqual(events[1]["message"], "sdk failed")

        assistant = factory.session.messages[events[0]["message"]["id"]]
        self.assertEqual(assistant.status, "error")

    async def test_stream_chat_upserts_session_after_session_id_then_exception(
        self,
    ) -> None:
        from schema.chat import ChatStreamResponse
        from service import chat as chat_service

        factory = _FakeSessionFactory()
        upserts: list[tuple[str, str]] = []

        async def fake_stream_query(*, prompt, session_store, resume):
            yield SimpleNamespace(session_id="sdk-session-before-error")
            raise RuntimeError("sdk disconnected")

        async def fake_get_agent_session_by_conversation_id(session, conversation_id):
            return None

        async def fake_upsert_agent_session(session, *, conversation_id, sdk_session_id):
            upserts.append((conversation_id, sdk_session_id))

        with (
            patch.object(chat_service, "AsyncSessionLocal", factory),
            patch.object(
                chat_service,
                "get_conversation_by_id",
                _fake_get_conversation_by_id,
            ),
            patch.object(chat_service, "stream_query", fake_stream_query),
            patch.object(
                chat_service,
                "get_agent_session_by_conversation_id",
                fake_get_agent_session_by_conversation_id,
            ),
            patch.object(chat_service, "upsert_agent_session", fake_upsert_agent_session),
        ):
            events = [
                _decode_sse(frame)
                async for frame in chat_service.stream_chat(
                    conversation_id="conversation-1",
                    message="hello",
                )
            ]

        TypeAdapter(list[ChatStreamResponse]).validate_python(events)
        self.assertEqual([event["type"] for event in events], ["message_created", "error"])
        self.assertEqual(events[1]["message"], "sdk disconnected")
        self.assertEqual(upserts, [("conversation-1", "sdk-session-before-error")])

        assistant = factory.session.messages[events[0]["message"]["id"]]
        self.assertEqual(assistant.status, "error")

    def test_controller_returns_text_event_stream_response(self) -> None:
        from controller.chat import run_stream_chat
        from main import app
        from schema.chat import StreamChatRequest
        from starlette.responses import StreamingResponse

        paths = {route.path for route in app.routes}
        self.assertIn("/api/chat/stream", paths)

        response = asyncio.run(
            run_stream_chat(
                StreamChatRequest(conversationId="conversation-1", message="hello")
            )
        )

        self.assertIsInstance(response, StreamingResponse)
        self.assertEqual(response.media_type, "text/event-stream")

    def test_chat_stream_response_accepts_ordinary_events_without_run_id(self) -> None:
        from schema.chat import ChatStreamResponse

        adapter = TypeAdapter(ChatStreamResponse)

        message_created = adapter.validate_python(
            {
                "type": "message_created",
                "message": {
                    "id": "assistant-1",
                    "conversationId": "conversation-1",
                    "role": "assistant",
                    "content": "",
                    "status": "streaming",
                    "createdAt": "2026-06-08T00:00:00Z",
                },
            }
        )

        tool_call = adapter.validate_python(
            {
                "type": "tool_call",
                "runId": "legacy-run-id",
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
                "conversationId": "conversation-1",
                "title": "Apple analysis",
            }
        )

        self.assertEqual(message_created.type, "message_created")
        self.assertEqual(tool_call.run_id, "legacy-run-id")
        self.assertEqual(tool_call.type, "tool_call")
        self.assertEqual(title.type, "title")
