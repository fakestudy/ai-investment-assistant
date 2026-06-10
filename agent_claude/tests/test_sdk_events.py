import unittest
from types import SimpleNamespace
from unittest.mock import patch

from claude_agent_sdk.types import ToolResultBlock, ToolUseBlock
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


class SdkEventsChatStreamTest(unittest.IsolatedAsyncioTestCase):
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
