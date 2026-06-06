import asyncio
import json
import os
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from langchain_deepseek import ChatDeepSeek
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import delete, select

from core.database import AsyncSessionLocal, engine
from model.conversation import Conversation
from model.message import Message
from schema.chat import ChatStreamRequest, ChatStreamResponse
from service.chat import (
    format_sse_data,
    get_agent,
    get_model,
    get_conversation_title,
    iter_chat_events,
    iter_chat_events_with_persistence,
)


class FakeAgent:
    def __init__(self, chunks: list[tuple[object, dict[str, object]]]) -> None:
        self.chunks = chunks
        self.stream_kwargs: dict[str, object] | None = None

    def stream(self, **kwargs: object):
        self.stream_kwargs = kwargs
        return iter(self.chunks)


class StaticModel:
    def __init__(self, response: AIMessage | Exception) -> None:
        self.response = response

    def invoke(self, _: object) -> AIMessage:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class TrackingSession:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    async def commit(self) -> None:
        self.events.append(f"commit:{self.name}")

    async def rollback(self) -> None:
        self.events.append(f"rollback:{self.name}")


class TrackingSessionContext:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events
        self.session = TrackingSession(name, events)

    async def __aenter__(self) -> TrackingSession:
        self.events.append(f"enter:{self.name}")
        return self.session

    async def __aexit__(self, *_: object) -> None:
        self.events.append(f"exit:{self.name}")


class TrackingSessionFactory:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.count = 0

    def __call__(self) -> TrackingSessionContext:
        self.count += 1
        return TrackingSessionContext(f"session-{self.count}", self.events)


class InspectingAgent(FakeAgent):
    def __init__(
        self,
        chunks: list[tuple[object, dict[str, object]]],
        events: list[str],
    ) -> None:
        super().__init__(chunks)
        self.events = events

    def stream(self, **kwargs: object):
        self.events.append("stream:start")
        return super().stream(**kwargs)


class FormatSSEDataTest(unittest.TestCase):
    def test_wraps_chunk_as_sse_data_frame(self) -> None:
        payload = format_sse_data({"message": "hello"})

        self.assertEqual(
            payload,
            f"data: {json.dumps({'message': 'hello'}, ensure_ascii=False)}\n\n",
        )


class ChatModelTest(unittest.TestCase):
    def test_uses_deepseek_adapter_that_preserves_reasoning_chunks(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "test-key",
                "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                "DEEPSEEK_MODEL": "deepseek-v4-pro",
            },
        ):
            model = get_model()

        self.assertIsInstance(model, ChatDeepSeek)
        self.assertEqual(model.model_name, "deepseek-v4-pro")

    def test_registers_deepseek_balance_tool_for_agent_calls(self) -> None:
        with (
            patch("service.chat.get_model", return_value=object()) as get_model_mock,
            patch("service.chat.create_agent", return_value=object()) as create_agent_mock,
        ):
            get_agent()

        get_model_mock.assert_called_once_with()
        tools = create_agent_mock.call_args.kwargs["tools"]
        self.assertEqual(
            [tool.name if hasattr(tool, "name") else tool.__name__ for tool in tools],
            ["get_weather", "get_deepseek_balance"],
        )
        self.assertIn(
            "Only call get_deepseek_balance",
            create_agent_mock.call_args.kwargs["system_prompt"],
        )


class ChatStreamResponseTest(unittest.TestCase):
    def test_request_accepts_frontend_fields(self) -> None:
        request = ChatStreamRequest.model_validate(
            {
                "conversationId": "conversation-1",
                "message": "北京今天天气怎么样？",
                "generateTitle": True,
            }
        )

        self.assertEqual(request.conversation_id, "conversation-1")
        self.assertTrue(request.generate_title)

    def test_validates_frontend_stream_event_contract(self) -> None:
        adapter = TypeAdapter(ChatStreamResponse)
        events = [
            {
                "type": "message_created",
                "message": {
                    "id": "assistant-1",
                    "conversationId": "conversation-1",
                    "role": "assistant",
                    "content": "",
                    "status": "streaming",
                    "createdAt": "2026-06-05T12:00:00Z",
                },
            },
            {"type": "delta", "messageId": "assistant-1", "text": "answer"},
            {"type": "reasoning", "messageId": "assistant-1", "text": "think"},
            {
                "type": "tool_call",
                "messageId": "assistant-1",
                "invocation": {
                    "id": "tool-1",
                    "messageId": "assistant-1",
                    "toolName": "get_weather",
                    "args": {"city": "Shanghai"},
                    "status": "running",
                },
            },
            {
                "type": "tool_result",
                "messageId": "assistant-1",
                "invocation": {
                    "id": "tool-1",
                    "messageId": "assistant-1",
                    "toolName": "get_weather",
                    "args": {"city": "Shanghai"},
                    "result": {"weather": "sunny"},
                    "latencyMs": 10,
                    "status": "completed",
                },
            },
            {
                "type": "title",
                "conversationId": "conversation-1",
                "title": "Shanghai weather",
            },
            {"type": "done", "messageId": "assistant-1"},
            {
                "type": "error",
                "messageId": "assistant-1",
                "message": "model unavailable",
            },
        ]

        serialized = [
            adapter.dump_python(
                adapter.validate_python(event),
                by_alias=True,
                exclude_none=True,
            )
            for event in events
        ]

        self.assertEqual(serialized, events)

    def test_rejects_removed_python_only_event_names(self) -> None:
        adapter = TypeAdapter(ChatStreamResponse)

        with self.assertRaises(ValidationError):
            adapter.validate_python(
                {"type": "output_delta", "data": {"content": "answer"}}
            )


class ChatEventStreamTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        asyncio.run(engine.dispose())

    def test_persists_user_and_final_assistant_message_after_stream_done(self) -> None:
        asyncio.run(self._test_persists_user_and_final_assistant_message_after_stream_done())

    def test_sends_full_history_before_current_message_to_agent(self) -> None:
        asyncio.run(self._test_sends_full_history_before_current_message_to_agent())

    def test_releases_database_session_before_model_streaming(self) -> None:
        asyncio.run(self._test_releases_database_session_before_model_streaming())

    async def _test_releases_database_session_before_model_streaming(self) -> None:
        events: list[str] = []
        request = ChatStreamRequest.model_validate(
            {
                "conversationId": "conversation-session-release",
                "message": "你好",
            }
        )
        agent = InspectingAgent(
            [(AIMessageChunk(content="回答"), {"langgraph_node": "model"})],
            events,
        )

        with (
            patch(
                "service.chat.get_messages_by_conversation_id",
                new=AsyncMock(return_value=[]),
            ),
            patch("service.chat.create_message", new=AsyncMock()),
        ):
            streamed_events = [
                event
                async for event in iter_chat_events_with_persistence(
                    request,
                    session_factory=TrackingSessionFactory(events),
                    agent=agent,
                    message_id_factory=lambda: "assistant-session-release",
                    now_factory=lambda: datetime(2026, 6, 5, 12, 1, tzinfo=UTC),
                )
            ]

        self.assertEqual(
            streamed_events[-1],
            {"type": "done", "messageId": "assistant-session-release"},
        )
        self.assertEqual(
            events,
            [
                "enter:session-1",
                "commit:session-1",
                "exit:session-1",
                "stream:start",
                "enter:session-2",
                "commit:session-2",
                "exit:session-2",
            ],
        )

    async def _test_sends_full_history_before_current_message_to_agent(self) -> None:
        conversation_id = "conversation-stream-history"
        agent = FakeAgent([])
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(Message).where(Message.conversation_id == conversation_id)
            )
            await session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            )
            await session.commit()

            await session.merge(
                Conversation(
                    id=conversation_id,
                    title="History",
                    created_at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
                )
            )
            session.add_all(
                [
                    Message(
                        id="history-user",
                        conversation_id=conversation_id,
                        role="user",
                        content="之前的问题",
                        reasoning="",
                        status="done",
                        created_at=datetime(2026, 6, 5, 12, 1, tzinfo=UTC),
                    ),
                    Message(
                        id="history-assistant",
                        conversation_id=conversation_id,
                        role="assistant",
                        content="之前的回答",
                        reasoning="历史推理不进入上下文",
                        status="done",
                        created_at=datetime(2026, 6, 5, 12, 2, tzinfo=UTC),
                    ),
                ]
            )
            await session.commit()

            request = ChatStreamRequest.model_validate(
                {
                    "conversationId": conversation_id,
                    "message": "继续说",
                }
            )

            events = [
                event
                async for event in iter_chat_events_with_persistence(
                    request,
                    session_factory=AsyncSessionLocal,
                    agent=agent,
                    message_id_factory=lambda: "assistant-with-history",
                    now_factory=lambda: datetime(2026, 6, 5, 12, 3, tzinfo=UTC),
                )
            ]

            self.assertEqual(events[-1], {"type": "done", "messageId": "assistant-with-history"})
            self.assertEqual(
                agent.stream_kwargs,
                {
                    "input": {
                        "messages": [
                            {"role": "user", "content": "之前的问题"},
                            {"role": "assistant", "content": "之前的回答"},
                            {"role": "user", "content": "继续说"},
                        ]
                    },
                    "stream_mode": "messages",
                },
            )

            await session.execute(
                delete(Message).where(Message.conversation_id == conversation_id)
            )
            await session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            )
            await session.commit()

    async def _test_persists_user_and_final_assistant_message_after_stream_done(
        self,
    ) -> None:
        conversation_id = "conversation-stream-persistence"
        async with AsyncSessionLocal() as session:
            await session.merge(
                Conversation(
                    id=conversation_id,
                    title="Stream persistence",
                    created_at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
                )
            )
            await session.commit()

            request = ChatStreamRequest.model_validate(
                {
                    "conversationId": conversation_id,
                    "message": "你好",
                }
            )
            chunks = [
                (
                    AIMessageChunk(
                        content="",
                        additional_kwargs={"reasoning_content": "先思考。"},
                    ),
                    {"langgraph_node": "model"},
                ),
                (AIMessageChunk(content="你好"), {"langgraph_node": "model"}),
                (AIMessageChunk(content="！"), {"langgraph_node": "model"}),
            ]

            events = [
                event
                async for event in iter_chat_events_with_persistence(
                    request,
                    session_factory=AsyncSessionLocal,
                    agent=FakeAgent(chunks),
                    message_id_factory=lambda: "assistant-persisted",
                    now_factory=lambda: datetime(2026, 6, 5, 12, 1, tzinfo=UTC),
                )
            ]

            rows = await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc(), Message.role.desc())
            )
            messages = rows.scalars().all()

            self.assertEqual(events[-1], {"type": "done", "messageId": "assistant-persisted"})
            self.assertEqual([message.role for message in messages], ["user", "assistant"])
            self.assertEqual(messages[0].content, "你好")
            self.assertEqual(messages[0].status, "done")
            self.assertEqual(messages[1].id, "assistant-persisted")
            self.assertEqual(messages[1].content, "你好！")
            self.assertEqual(messages[1].reasoning, "先思考。")
            self.assertEqual(messages[1].status, "done")

            await session.execute(
                delete(Message).where(Message.conversation_id == conversation_id)
            )
            await session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            )
            await session.commit()

    def test_converts_langchain_stream_to_frontend_event_order(self) -> None:
        chunks = [
            (
                AIMessageChunk(
                    content="",
                    additional_kwargs={"reasoning_content": "先查询天气。"},
                ),
                {"langgraph_node": "model"},
            ),
            (
                AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": "get_weather",
                            "args": "",
                            "id": "call-weather-1",
                            "index": 0,
                            "type": "tool_call_chunk",
                        }
                    ],
                ),
                {"langgraph_node": "model"},
            ),
            (
                AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": None,
                            "args": '{"city":',
                            "id": None,
                            "index": 0,
                            "type": "tool_call_chunk",
                        }
                    ],
                ),
                {"langgraph_node": "model"},
            ),
            (
                AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": None,
                            "args": '"北京"}',
                            "id": None,
                            "index": 0,
                            "type": "tool_call_chunk",
                        }
                    ],
                ),
                {"langgraph_node": "model"},
            ),
            (
                AIMessageChunk(
                    content="",
                    response_metadata={"finish_reason": "tool_calls"},
                ),
                {"langgraph_node": "model"},
            ),
            (
                ToolMessage(
                    content="北京今天晴天",
                    name="get_weather",
                    tool_call_id="call-weather-1",
                ),
                {"langgraph_node": "tools"},
            ),
            (
                AIMessageChunk(content="北京今天"),
                {"langgraph_node": "model"},
            ),
            (
                AIMessageChunk(content="是晴天。"),
                {"langgraph_node": "model"},
            ),
        ]
        request = ChatStreamRequest.model_validate(
            {
                "conversationId": "conversation-1",
                "message": "北京今天天气怎么样？",
                "generateTitle": True,
            }
        )

        events = list(
            iter_chat_events(
                request,
                agent=FakeAgent(chunks),
                title_generator=lambda _: "北京今日天气",
                message_id_factory=lambda: "assistant-1",
                now_factory=lambda: datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
            )
        )

        self.assertEqual(
            [event["type"] for event in events],
            [
                "message_created",
                "reasoning",
                "tool_call",
                "tool_result",
                "delta",
                "delta",
                "title",
                "done",
            ],
        )
        self.assertEqual(
            events[0],
            {
                "type": "message_created",
                "message": {
                    "id": "assistant-1",
                    "conversationId": "conversation-1",
                    "role": "assistant",
                    "content": "",
                    "status": "streaming",
                    "createdAt": "2026-06-05T12:00:00Z",
                },
            },
        )
        self.assertEqual(events[1]["messageId"], "assistant-1")
        self.assertEqual(events[1]["text"], "先查询天气。")
        self.assertEqual(
            events[2]["invocation"],
            {
                "id": "call-weather-1",
                "messageId": "assistant-1",
                "toolName": "get_weather",
                "args": {"city": "北京"},
                "status": "running",
            },
        )
        self.assertEqual(events[3]["invocation"]["id"], "call-weather-1")
        self.assertEqual(events[3]["invocation"]["result"], "北京今天晴天")
        self.assertEqual(events[3]["invocation"]["status"], "completed")
        self.assertIsInstance(events[3]["invocation"]["latencyMs"], int)
        self.assertEqual(
            events[-2],
            {
                "type": "title",
                "conversationId": "conversation-1",
                "title": "北京今日天气",
            },
        )
        self.assertEqual(
            events[-1],
            {"type": "done", "messageId": "assistant-1"},
        )

    def test_does_not_query_deepseek_balance_for_every_chat(self) -> None:
        request = ChatStreamRequest.model_validate(
            {
                "conversationId": "conversation-1",
                "message": "你好",
            }
        )
        with (
            patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=True),
            patch("provider.deepseek.urlopen") as urlopen_mock,
        ):
            events = list(
                iter_chat_events(
                    request,
                    agent=FakeAgent([]),
                    message_id_factory=lambda: "assistant-1",
                    now_factory=lambda: datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
                )
            )

        self.assertEqual(
            [event["type"] for event in events],
            ["message_created", "done"],
        )
        urlopen_mock.assert_not_called()

    def test_finishes_without_balance_delta_when_no_balance_tool_is_called(self) -> None:
        request = ChatStreamRequest.model_validate(
            {
                "conversationId": "conversation-1",
                "message": "你好",
            }
        )

        events = list(
            iter_chat_events(
                request,
                agent=FakeAgent([]),
                message_id_factory=lambda: "assistant-1",
                now_factory=lambda: datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
            )
        )

        self.assertEqual(
            [event["type"] for event in events],
            ["message_created", "done"],
        )


class ConversationTitleTest(unittest.TestCase):
    def test_normalizes_model_title(self) -> None:
        title = get_conversation_title(
            "北京今天天气怎么样？",
            model=StaticModel(AIMessage(content='  "北京今日天气"  \n额外说明')),
        )

        self.assertEqual(title, "北京今日天气")

    def test_falls_back_to_trimmed_prompt_when_model_fails(self) -> None:
        prompt = "这是一段很长的会话内容" * 10

        title = get_conversation_title(
            prompt,
            model=StaticModel(RuntimeError("model unavailable")),
        )

        self.assertEqual(title, prompt[:60])


if __name__ == "__main__":
    unittest.main()
