import asyncio
import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from claude_agent_sdk.types import ToolResultBlock, ToolUseBlock
import model.conversation  # noqa: F401
from model.message_part import MessagePart
from pydantic import TypeAdapter

from model.conversation import Conversation
from model.message import Message
from model.tool_invocation import ToolInvocation


class _FakeSession:
    def __init__(self) -> None:
        self.messages: dict[str, Message] = {}
        now = datetime(2026, 6, 8, 4, 0, tzinfo=UTC)
        self.conversations: dict[str, Conversation] = {
            "conversation-1": Conversation(
                id="conversation-1",
                title="Conversation",
                created_at=now,
                updated_at=now,
            ),
            "conversation-title": Conversation(
                id="conversation-title",
                title="Conversation",
                created_at=now,
                updated_at=now,
            ),
        }
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def add(self, row) -> None:
        if isinstance(row, Conversation):
            self.conversations[row.id] = row
            return
        if isinstance(row, Message):
            self.messages[row.id] = row
            return
        if isinstance(row, ToolInvocation):
            self.messages.setdefault("_tool_invocations", {})[row.id] = row
            return
        if isinstance(row, MessagePart):
            self.messages.setdefault("_message_parts", {})[row.id] = row
            return
        raise AssertionError(f"unexpected row type: {type(row)!r}")

    async def get(self, model, object_id: str):
        if model is Conversation:
            return self.conversations.get(object_id)
        if model is Message:
            return self.messages.get(object_id)
        if model is ToolInvocation:
            return self.messages.get("_tool_invocations", {}).get(object_id)
        if model is MessagePart:
            return self.messages.get("_message_parts", {}).get(object_id)
        return None

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


async def _fake_get_conversation_by_id(session: _FakeSession, conversation_id: str):
    return await session.get(Conversation, conversation_id)


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

    async def test_stream_chat_projects_empty_args_tool_call_without_json_delta(
        self,
    ) -> None:
        from schema.chat import ChatStreamResponse
        from service import chat as chat_service

        factory = _FakeSessionFactory()

        async def fake_stream_query(*, prompt, session_store, resume):
            yield SimpleNamespace(
                event=SimpleNamespace(
                    type="content_block_start",
                    content_block=ToolUseBlock(
                        id="sdk-tool-1",
                        name="get_portfolio_summary",
                        input={},
                    ),
                ),
            )
            yield SimpleNamespace(
                event=SimpleNamespace(
                    type="content_block_start",
                    content_block=ToolResultBlock(
                        tool_use_id="sdk-tool-1",
                        content='{"summary": "ok"}',
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
                    message="summarize portfolio",
                )
            ]

        TypeAdapter(list[ChatStreamResponse]).validate_python(events)
        self.assertEqual(
            [event["type"] for event in events],
            ["message_created", "tool_call", "tool_result", "done"],
        )
        self.assertEqual(events[1]["invocation"]["id"], "sdk-tool-1")
        self.assertEqual(
            events[1]["invocation"]["toolName"],
            "get_portfolio_summary",
        )
        self.assertEqual(events[1]["invocation"]["args"], {})
        self.assertEqual(
            events[2]["invocation"]["toolName"],
            "get_portfolio_summary",
        )
        self.assertEqual(events[2]["invocation"]["args"], {})
        self.assertEqual(events[2]["invocation"]["result"], {"summary": "ok"})

        invocation = factory.session.messages["_tool_invocations"]["sdk-tool-1"]
        self.assertEqual(invocation.tool_name, "get_portfolio_summary")
        self.assertEqual(invocation.args, {})
        self.assertEqual(invocation.result, {"summary": "ok"})

    async def test_stream_chat_projects_text_tool_result_blocks_from_sdk_events(self) -> None:
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
                        content=[{"type": "text", "text": '{"price": 100}'}],
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
        self.assertEqual(events[2]["invocation"]["result"], {"price": 100})
        self.assertEqual(
            factory.session.messages["_tool_invocations"]["sdk-tool-1"].result,
            {"price": 100},
        )

    async def test_stream_chat_deduplicates_partial_tool_use_against_final_message(
        self,
    ) -> None:
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
                type="assistant",
                content=[
                    ToolUseBlock(
                        id="sdk-tool-1",
                        name="get_quote",
                        input={"symbol": "AAPL"},
                    )
                ],
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
            ["message_created", "tool_call", "done"],
        )
        self.assertEqual(events[1]["invocation"]["id"], "sdk-tool-1")
        self.assertEqual(len(factory.session.messages["_tool_invocations"]), 1)
        self.assertEqual(len(factory.session.messages["_message_parts"]), 1)

    async def test_stream_chat_accumulates_input_json_delta_before_tool_call(
        self,
    ) -> None:
        from schema.chat import ChatStreamResponse
        from service import chat as chat_service

        factory = _FakeSessionFactory()

        async def fake_stream_query(*, prompt, session_store, resume):
            yield SimpleNamespace(
                event={
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "sdk-tool-1",
                        "name": "get_quote",
                        "input": {},
                    },
                },
            )
            yield SimpleNamespace(
                event={
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": '{"symbol"'},
                },
            )
            yield SimpleNamespace(
                event={
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": ': "AAPL"}'},
                },
            )
            yield SimpleNamespace(
                event={
                    "type": "content_block_stop",
                    "index": 0,
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
            ["message_created", "tool_call", "done"],
        )
        self.assertEqual(events[1]["invocation"]["args"], {"symbol": "AAPL"})
        self.assertEqual(
            factory.session.messages["_tool_invocations"]["sdk-tool-1"].args,
            {"symbol": "AAPL"},
        )

    async def test_stream_chat_creates_fallback_invocation_for_orphan_tool_result(
        self,
    ) -> None:
        from schema.chat import ChatStreamResponse
        from service import chat as chat_service

        factory = _FakeSessionFactory()

        async def fake_stream_query(*, prompt, session_store, resume):
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
            ["message_created", "tool_result", "done"],
        )
        self.assertEqual(events[1]["invocation"]["id"], "sdk-tool-1")
        self.assertEqual(events[1]["invocation"]["toolName"], "unknown")
        self.assertEqual(events[1]["invocation"]["args"], {})
        self.assertEqual(events[1]["invocation"]["result"], {"price": 100})
        self.assertEqual(events[1]["invocation"]["status"], "completed")
        parts = factory.session.messages["_message_parts"]
        self.assertEqual(len(parts), 1)
        self.assertEqual(next(iter(parts.values())).tool_invocation_id, "sdk-tool-1")

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
            ["message_created", "delta", "title", "done"],
        )
        self.assertEqual(events[2]["conversationId"], "conversation-1")
        self.assertEqual(events[2]["title"], "请分析苹果公司最近的投资价值，并给出关键风险。")
        self.assertEqual(conversation.title, "请分析苹果公司最近的投资价值，并给出关键风险。")

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

    async def test_stream_chat_maps_sdk_result_error_to_error_event(self) -> None:
        from schema.chat import ChatStreamResponse
        from service import chat as chat_service

        factory = _FakeSessionFactory()
        upserts: list[tuple[str, str]] = []

        async def fake_stream_query(*, prompt, session_store, resume):
            yield SimpleNamespace(
                session_id="sdk-session-error",
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "partial"},
                },
            )
            yield SimpleNamespace(
                session_id="sdk-session-error",
                subtype="error",
                is_error=True,
                errors=[{"message": "quota exceeded"}],
            )

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
            ["message_created", "delta", "error"],
        )
        self.assertEqual(events[2]["messageId"], events[0]["message"]["id"])
        self.assertEqual(events[2]["message"], "quota exceeded")
        self.assertEqual(upserts, [("conversation-1", "sdk-session-error")])

        assistant = factory.session.messages[events[0]["message"]["id"]]
        self.assertEqual(assistant.content, "partial")
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

    async def test_stream_chat_does_not_repeat_final_assistant_text_after_partial(
        self,
    ) -> None:
        from schema.chat import ChatStreamResponse
        from service import chat as chat_service

        factory = _FakeSessionFactory()

        async def fake_stream_query(*, prompt, session_store, resume):
            yield SimpleNamespace(
                type="stream_event",
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "answer"},
                },
            )
            yield SimpleNamespace(
                type="assistant",
                content=[SimpleNamespace(text="answer")],
            )

        async def fake_get_agent_session_by_conversation_id(session, conversation_id):
            return None

        async def fake_upsert_agent_session(session, *, conversation_id, sdk_session_id):
            raise AssertionError("should not upsert without session id")

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
        self.assertEqual(
            [event for event in events if event["type"] == "delta"],
            [{"type": "delta", "messageId": events[0]["message"]["id"], "text": "answer"}],
        )
        assistant = factory.session.messages[events[0]["message"]["id"]]
        self.assertEqual(assistant.content, "answer")

    async def test_stream_chat_does_not_repeat_final_assistant_thinking_after_partial(
        self,
    ) -> None:
        from schema.chat import ChatStreamResponse
        from service import chat as chat_service

        factory = _FakeSessionFactory()

        async def fake_stream_query(*, prompt, session_store, resume):
            yield SimpleNamespace(
                type="stream_event",
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "think"},
                },
            )
            yield SimpleNamespace(
                type="assistant",
                content=[SimpleNamespace(thinking="think")],
            )

        async def fake_get_agent_session_by_conversation_id(session, conversation_id):
            return None

        async def fake_upsert_agent_session(session, *, conversation_id, sdk_session_id):
            raise AssertionError("should not upsert without session id")

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
        self.assertEqual(
            [event for event in events if event["type"] == "reasoning"],
            [
                {
                    "type": "reasoning",
                    "messageId": events[0]["message"]["id"],
                    "text": "think",
                }
            ],
        )
        assistant = factory.session.messages[events[0]["message"]["id"]]
        self.assertEqual(assistant.reasoning, "think")


if __name__ == "__main__":
    unittest.main()
