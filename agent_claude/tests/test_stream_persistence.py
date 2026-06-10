import asyncio
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from claude_agent_sdk.types import ToolResultBlock, ToolUseBlock
import model.conversation  # noqa: F401
from model.conversation import Conversation
from model.tool_invocation import ToolInvocation
from pydantic import TypeAdapter

from tests.chat_stream_test_helpers import (
    FakeChatStreamSessionFactory,
    decode_sse,
    fake_get_conversation_by_id,
)


_FakeSessionFactory = FakeChatStreamSessionFactory
_decode_sse = decode_sse
_fake_get_conversation_by_id = fake_get_conversation_by_id


class StreamPersistenceChatStreamTest(unittest.IsolatedAsyncioTestCase):
    async def test_stream_chat_projects_tool_call_and_result_from_sdk_events(self) -> None:
        from schema.chat import ChatStreamResponse
        from service import chat as chat_service

        factory = _FakeSessionFactory()

        async def fake_stream_query(*, prompt, session_store, resume):
            yield SimpleNamespace(
                event=SimpleNamespace(
                    type="content_block_start",
                    content_block=ToolUseBlock(
                        id="sdk-tool-1",
                        name="get_quote",
                        input={"symbol": "AAPL"},
                    ),
                ),
            )
            yield SimpleNamespace(
                event=SimpleNamespace(
                    type="content_block_start",
                    content_block=ToolResultBlock(
                        tool_use_id="sdk-tool-1",
                        content='{"price": 100}',
                        is_error=False,
                    ),
                ),
            )

        async def fake_get_agent_session_by_conversation_id(session, conversation_id):
            return None

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
        ):
            events = [
                _decode_sse(frame)
                async for frame in chat_service.stream_chat(
                    conversation_id="conversation-1",
                    message="quote aapl",
                )
            ]

        TypeAdapter(list[ChatStreamResponse]).validate_python(events)
        self.assertEqual(
            [event["type"] for event in events],
            ["message_created", "tool_call", "tool_result", "done"],
        )
        assistant_id = events[0]["message"]["id"]
        self.assertEqual(events[1]["messageId"], assistant_id)
        self.assertEqual(events[1]["invocation"]["id"], "sdk-tool-1")
        self.assertEqual(events[1]["invocation"]["messageId"], assistant_id)
        self.assertEqual(events[1]["invocation"]["toolName"], "get_quote")
        self.assertEqual(events[1]["invocation"]["args"], {"symbol": "AAPL"})
        self.assertEqual(events[1]["invocation"]["status"], "running")
        self.assertEqual(events[2]["invocation"]["result"], {"price": 100})
        self.assertEqual(events[2]["invocation"]["status"], "completed")
        self.assertIsInstance(events[2]["invocation"]["latencyMs"], int)

        invocations = factory.session.messages["_tool_invocations"]
        parts = factory.session.messages["_message_parts"]
        self.assertEqual(invocations["sdk-tool-1"].result, {"price": 100})
        self.assertEqual(invocations["sdk-tool-1"].status, "completed")
        self.assertEqual(len(parts), 1)
        part = next(iter(parts.values()))
        self.assertEqual(part.type, "tool")
        self.assertEqual(part.order_index, 0)
        self.assertEqual(part.tool_invocation_id, "sdk-tool-1")

    async def test_stream_chat_persists_tool_result_error_status(self) -> None:
        from schema.chat import ChatStreamResponse
        from service import chat as chat_service

        factory = _FakeSessionFactory()

        async def fake_stream_query(*, prompt, session_store, resume):
            yield SimpleNamespace(
                event=SimpleNamespace(
                    type="content_block_start",
                    content_block=ToolUseBlock(
                        id="sdk-tool-1",
                        name="get_quote",
                        input={"symbol": "AAPL"},
                    ),
                ),
            )
            yield SimpleNamespace(
                event=SimpleNamespace(
                    type="content_block_start",
                    content_block=ToolResultBlock(
                        tool_use_id="sdk-tool-1",
                        content="permission denied",
                        is_error=True,
                    ),
                ),
            )

        async def fake_get_agent_session_by_conversation_id(session, conversation_id):
            return None

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
        ):
            events = [
                _decode_sse(frame)
                async for frame in chat_service.stream_chat(
                    conversation_id="conversation-1",
                    message="quote aapl",
                )
            ]

        TypeAdapter(list[ChatStreamResponse]).validate_python(events)
        self.assertEqual(
            [event["type"] for event in events],
            ["message_created", "tool_call", "tool_result", "done"],
        )
        self.assertEqual(events[2]["invocation"]["status"], "error")
        self.assertEqual(events[2]["invocation"]["error"], "permission denied")
        invocation = factory.session.messages["_tool_invocations"]["sdk-tool-1"]
        self.assertEqual(invocation.status, "error")
        self.assertEqual(invocation.error, "permission denied")
        self.assertIsNone(invocation.result)

    async def test_stream_chat_preserves_reasoning_timeline_around_tool_events(self) -> None:
        from schema.chat import ChatStreamResponse
        from service import chat as chat_service

        factory = _FakeSessionFactory()

        async def fake_stream_query(*, prompt, session_store, resume):
            yield SimpleNamespace(
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "before "},
                },
            )
            yield SimpleNamespace(
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "tool"},
                },
            )
            yield SimpleNamespace(
                event=SimpleNamespace(
                    type="content_block_start",
                    content_block=ToolUseBlock(
                        id="sdk-tool-1",
                        name="get_quote",
                        input={"symbol": "AAPL"},
                    ),
                ),
            )
            yield SimpleNamespace(
                event=SimpleNamespace(
                    type="content_block_start",
                    content_block=ToolResultBlock(
                        tool_use_id="sdk-tool-1",
                        content='{"price": 100}',
                        is_error=False,
                    ),
                ),
            )
            yield SimpleNamespace(
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "after tool"},
                },
            )

        async def fake_get_agent_session_by_conversation_id(session, conversation_id):
            return None

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
        ):
            events = [
                _decode_sse(frame)
                async for frame in chat_service.stream_chat(
                    conversation_id="conversation-1",
                    message="quote aapl",
                )
            ]

        TypeAdapter(list[ChatStreamResponse]).validate_python(events)
        self.assertEqual(
            [event["type"] for event in events],
            [
                "message_created",
                "reasoning",
                "reasoning",
                "tool_call",
                "tool_result",
                "reasoning",
                "done",
            ],
        )

        parts = sorted(
            factory.session.messages["_message_parts"].values(),
            key=lambda part: part.order_index,
        )
        self.assertEqual([part.type for part in parts], ["reasoning", "tool", "reasoning"])
        self.assertEqual([part.order_index for part in parts], [0, 1, 2])
        self.assertEqual(parts[0].text, "before tool")
        self.assertEqual(parts[1].tool_invocation_id, "sdk-tool-1")
        self.assertEqual(parts[2].text, "after tool")

    async def test_stream_chat_splits_reasoning_when_tool_result_has_no_tool_call_event(
        self,
    ) -> None:
        from schema.chat import ChatStreamResponse
        from service import chat as chat_service

        factory = _FakeSessionFactory()
        factory.session.messages.setdefault("_tool_invocations", {})[
            "sdk-tool-1"
        ] = ToolInvocation(
            id="sdk-tool-1",
            message_id="assistant-placeholder",
            tool_name="get_quote",
            args={"symbol": "AAPL"},
            result=None,
            error=None,
            latency_ms=None,
            status="running",
            created_at=datetime(2026, 6, 8, 4, 0, tzinfo=UTC),
        )

        async def fake_stream_query(*, prompt, session_store, resume):
            yield SimpleNamespace(
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "before"},
                },
            )
            yield SimpleNamespace(
                event=SimpleNamespace(
                    type="content_block_start",
                    content_block=ToolResultBlock(
                        tool_use_id="sdk-tool-1",
                        content='{"price": 100}',
                        is_error=False,
                    ),
                ),
            )
            yield SimpleNamespace(
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "after"},
                },
            )

        async def fake_get_agent_session_by_conversation_id(session, conversation_id):
            return None

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
        ):
            events = [
                _decode_sse(frame)
                async for frame in chat_service.stream_chat(
                    conversation_id="conversation-1",
                    message="quote aapl",
                )
            ]

        TypeAdapter(list[ChatStreamResponse]).validate_python(events)
        self.assertEqual(
            [event["type"] for event in events],
            ["message_created", "reasoning", "tool_result", "reasoning", "done"],
        )
        parts = sorted(
            factory.session.messages["_message_parts"].values(),
            key=lambda part: part.order_index,
        )
        self.assertEqual([part.type for part in parts], ["reasoning", "reasoning"])
        self.assertEqual([part.text for part in parts], ["before", "after"])

    async def test_stream_chat_emits_generated_title_before_main_answer_finishes(
        self,
    ) -> None:
        from service import chat_stream

        factory = _FakeSessionFactory()
        release_answer = asyncio.Event()
        title_called = asyncio.Event()

        async def fake_stream_query(*, prompt, session_store, resume):
            await release_answer.wait()
            yield SimpleNamespace(
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "answer"},
                },
            )

        async def fake_get_agent_session_by_conversation_id(session, conversation_id):
            return None

        async def fake_update_conversation_title(session, *, conversation_id, title):
            conversation = factory.session.conversations[conversation_id]
            conversation.title = title
            return conversation

        async def fake_generate_title(prompt):
            self.assertEqual(prompt, "Analyze Apple investment risks")
            title_called.set()
            return "Apple investment risks"

        stream = chat_stream.stream_chat(
            conversation_id="conversation-1",
            message="Analyze Apple investment risks",
            generate_title=True,
            dependencies=chat_stream.ChatStreamDependencies(
                async_session_factory=factory,
                get_conversation_by_id=_fake_get_conversation_by_id,
                get_agent_session_by_conversation_id=(
                    fake_get_agent_session_by_conversation_id
                ),
                stream_query=fake_stream_query,
                update_conversation_title=fake_update_conversation_title,
                generate_title=fake_generate_title,
            ),
        )

        first_event = _decode_sse(await anext(stream))
        second_event = _decode_sse(await asyncio.wait_for(anext(stream), timeout=1))

        self.assertEqual(first_event["type"], "message_created")
        self.assertEqual(second_event["type"], "title")
        self.assertEqual(second_event["title"], "Apple investment risks")
        self.assertTrue(title_called.is_set())
        self.assertEqual(
            factory.session.conversations["conversation-1"].title,
            "Apple investment risks",
        )

        release_answer.set()
        rest_events = [_decode_sse(frame) async for frame in stream]

        self.assertEqual([event["type"] for event in rest_events], ["delta", "done"])

    async def test_stream_chat_does_not_fallback_to_prompt_when_title_generation_fails(
        self,
    ) -> None:
        from service import chat_stream

        factory = _FakeSessionFactory()
        persisted_titles: list[str] = []

        async def fake_stream_query(*, prompt, session_store, resume):
            yield SimpleNamespace(
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "answer"},
                },
            )

        async def fake_get_agent_session_by_conversation_id(session, conversation_id):
            return None

        async def fake_update_conversation_title(session, *, conversation_id, title):
            persisted_titles.append(title)
            conversation = factory.session.conversations[conversation_id]
            conversation.title = title
            return conversation

        async def fake_generate_title(prompt):
            raise RuntimeError("title model unavailable")

        with patch("service.chat_stream.logger.exception") as logged:
            events = [
                _decode_sse(frame)
                async for frame in chat_stream.stream_chat(
                    conversation_id="conversation-1",
                    message="Please analyze Apple investment risks in detail",
                    generate_title=True,
                    dependencies=chat_stream.ChatStreamDependencies(
                        async_session_factory=factory,
                        get_conversation_by_id=_fake_get_conversation_by_id,
                        get_agent_session_by_conversation_id=(
                            fake_get_agent_session_by_conversation_id
                        ),
                        stream_query=fake_stream_query,
                        update_conversation_title=fake_update_conversation_title,
                        generate_title=fake_generate_title,
                    ),
                )
            ]

        self.assertEqual([event["type"] for event in events], ["message_created", "delta", "done"])
        self.assertEqual(persisted_titles, [])
        logged.assert_called_once()

    async def test_stream_chat_generates_title_event_and_updates_conversation(self) -> None:
        from schema.chat import ChatStreamResponse
        from service import chat as chat_service

        factory = _FakeSessionFactory()
        conversation = Conversation(
            id="conversation-1",
            title="New Chat",
            created_at=datetime(2026, 6, 8, 4, 0, tzinfo=UTC),
            updated_at=datetime(2026, 6, 8, 4, 0, tzinfo=UTC),
        )

        async def fake_stream_query(*, prompt, session_store, resume):
            yield SimpleNamespace(
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "answer"},
                },
            )

        async def fake_get_agent_session_by_conversation_id(session, conversation_id):
            return None

        async def fake_update_conversation_title(session, *, conversation_id, title):
            self.assertEqual(conversation_id, "conversation-1")
            conversation.title = title
            return conversation

        async def fake_generate_title(prompt):
            self.assertEqual(prompt, "请分析苹果公司最近的投资价值，并给出关键风险。")
            return "苹果投资价值与风险"

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
            patch.object(
                chat_service,
                "update_conversation_title",
                fake_update_conversation_title,
            ),
            patch.object(
                chat_service,
                "generate_conversation_title",
                fake_generate_title,
            ),
        ):
            events = [
                _decode_sse(frame)
                async for frame in chat_service.stream_chat(
                    conversation_id="conversation-1",
                    message="请分析苹果公司最近的投资价值，并给出关键风险。",
                    generate_title=True,
                )
            ]

        TypeAdapter(list[ChatStreamResponse]).validate_python(events)
        self.assertEqual(
            [event["type"] for event in events],
            ["message_created", "title", "delta", "done"],
        )
        self.assertEqual(events[1]["conversationId"], "conversation-1")
        self.assertEqual(events[1]["title"], "苹果投资价值与风险")
        self.assertEqual(conversation.title, "苹果投资价值与风险")
