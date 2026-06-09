import asyncio
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from repository.message import update_message
from repository.message_part import update_message_part_text
from repository.tool_invocation import update_tool_invocation
from schema.chat import (
    ChatTimelinePart,
    ConversationMessagesResponse,
    ToolInvocation,
)
from service.history import project_conversation_messages


class FakeSession:
    def __init__(self, objects: dict[object, object]) -> None:
        self._objects = objects
        self.flushed = False

    async def get(self, model: object, object_id: str) -> object | None:
        return self._objects.get((model, object_id))

    async def flush(self) -> None:
        self.flushed = True


class HistoryProjectionTest(unittest.TestCase):
    def test_app_registers_frontend_compatible_messages_route(self) -> None:
        from main import app

        paths = {route.path for route in app.routes}

        self.assertIn("/api/conversation/messages/{conversation_id}", paths)

    def test_history_route_returns_projected_messages(self) -> None:
        from main import app

        class FakeSessionContext:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        async def fake_get_messages(session, *, conversation_id: str):
            return ConversationMessagesResponse(
                messages=[
                    {
                        "id": "assistant-1",
                        "conversationId": conversation_id,
                        "role": "assistant",
                        "content": "hello",
                        "status": "done",
                        "createdAt": "2026-06-08T04:00:00Z",
                    }
                ],
            )

        with (
            patch("controller.chat.AsyncSessionLocal", lambda: FakeSessionContext()),
            patch("service.history.get_conversation_messages", fake_get_messages),
        ):
            response = TestClient(app).get("/api/conversation/messages/conversation-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "messages": [
                    {
                        "id": "assistant-1",
                        "conversationId": "conversation-1",
                        "role": "assistant",
                        "content": "hello",
                        "toolInvocations": [],
                        "timelineParts": [],
                        "status": "done",
                        "createdAt": "2026-06-08T04:00:00Z",
                    }
                ],
            },
        )

    def test_update_message_updates_projection_fields(self) -> None:
        from model.message import Message

        message = SimpleNamespace(content="", reasoning="", status="streaming")
        session = FakeSession({(Message, "message-1"): message})

        async def run() -> None:
            await update_message(
                session,
                message_id="message-1",
                content="回答内容",
                reasoning="推理内容",
                status="done",
            )

        asyncio.run(run())

        self.assertEqual(message.content, "回答内容")
        self.assertEqual(message.reasoning, "推理内容")
        self.assertEqual(message.status, "done")
        self.assertTrue(session.flushed)

    def test_update_message_raises_when_not_found(self) -> None:
        session = FakeSession({})

        async def run() -> None:
            await update_message(
                session,
                message_id="missing-message",
                content="回答内容",
                reasoning="推理内容",
                status="done",
            )

        with self.assertRaises(LookupError):
            asyncio.run(run())
        self.assertFalse(session.flushed)

    def test_update_tool_invocation_updates_result_error_latency_and_status(self) -> None:
        from model.tool_invocation import ToolInvocation

        invocation = SimpleNamespace(
            result=None,
            error=None,
            latency_ms=None,
            status="running",
        )
        session = FakeSession({(ToolInvocation, "tool-1"): invocation})

        async def run() -> None:
            await update_tool_invocation(
                session,
                invocation_id="tool-1",
                result={"price": 100},
                error="",
                latency_ms=12,
                status="completed",
            )

        asyncio.run(run())

        self.assertEqual(invocation.result, {"price": 100})
        self.assertEqual(invocation.error, "")
        self.assertEqual(invocation.latency_ms, 12)
        self.assertEqual(invocation.status, "completed")
        self.assertTrue(session.flushed)

    def test_update_tool_invocation_preserves_unpassed_fields(self) -> None:
        from model.tool_invocation import ToolInvocation

        invocation = SimpleNamespace(
            result={"price": 100},
            error="timeout",
            latency_ms=99,
            status="running",
        )
        session = FakeSession({(ToolInvocation, "tool-1"): invocation})

        async def run() -> None:
            await update_tool_invocation(
                session,
                invocation_id="tool-1",
                status="completed",
            )

        asyncio.run(run())

        self.assertEqual(invocation.result, {"price": 100})
        self.assertEqual(invocation.error, "timeout")
        self.assertEqual(invocation.latency_ms, 99)
        self.assertEqual(invocation.status, "completed")
        self.assertTrue(session.flushed)

    def test_update_tool_invocation_can_clear_result_and_error(self) -> None:
        from model.tool_invocation import ToolInvocation

        invocation = SimpleNamespace(
            result={"price": 100},
            error="timeout",
            latency_ms=99,
            status="running",
        )
        session = FakeSession({(ToolInvocation, "tool-1"): invocation})

        async def run() -> None:
            await update_tool_invocation(
                session,
                invocation_id="tool-1",
                result=None,
                error=None,
                status="completed",
            )

        asyncio.run(run())

        self.assertIsNone(invocation.result)
        self.assertIsNone(invocation.error)
        self.assertEqual(invocation.latency_ms, 99)
        self.assertEqual(invocation.status, "completed")
        self.assertTrue(session.flushed)

    def test_update_tool_invocation_raises_when_not_found(self) -> None:
        session = FakeSession({})

        async def run() -> None:
            await update_tool_invocation(
                session,
                invocation_id="missing-tool",
                status="completed",
            )

        with self.assertRaises(LookupError):
            asyncio.run(run())
        self.assertFalse(session.flushed)

    def test_update_message_part_text_updates_text(self) -> None:
        from model.message_part import MessagePart

        message_part = SimpleNamespace(text="")
        session = FakeSession({(MessagePart, "part-1"): message_part})

        async def run() -> None:
            await update_message_part_text(
                session,
                part_id="part-1",
                text="增量文本",
            )

        asyncio.run(run())

        self.assertEqual(message_part.text, "增量文本")
        self.assertTrue(session.flushed)

    def test_update_message_part_text_raises_when_not_found(self) -> None:
        session = FakeSession({})

        async def run() -> None:
            await update_message_part_text(
                session,
                part_id="missing-part",
                text="增量文本",
            )

        with self.assertRaises(LookupError):
            asyncio.run(run())
        self.assertFalse(session.flushed)

    def test_schema_serializes_frontend_history_aliases(self) -> None:
        response = ConversationMessagesResponse(
            messages=[
                {
                    "id": "message-1",
                    "conversation_id": "conversation-1",
                    "role": "assistant",
                    "content": "结果如下。",
                    "reasoning": "先调用工具。",
                    "tool_invocations": [
                        ToolInvocation(
                            id="tool-1",
                            message_id="message-1",
                            tool_name="get_quote",
                            args={"symbol": "AAPL"},
                            result={"price": 100},
                            error=None,
                            latency_ms=12,
                            status="completed",
                            created_at="2026-06-08T04:00:00Z",
                        )
                    ],
                    "timeline_parts": [
                        {
                            "id": "part-1",
                            "type": "reasoning",
                            "order_index": 0,
                            "text": "先调用工具。",
                        },
                        {
                            "id": "part-2",
                            "type": "tool",
                            "order_index": 1,
                            "invocation": {
                                "id": "tool-1",
                                "message_id": "message-1",
                                "tool_name": "get_quote",
                                "args": {"symbol": "AAPL"},
                                "status": "completed",
                            },
                        },
                    ],
                    "status": "done",
                    "created_at": "2026-06-08T04:00:00Z",
                }
            ],
            active_run=None,
        )

        payload = response.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(set(payload), {"messages"})
        message = payload["messages"][0]
        self.assertEqual(message["conversationId"], "conversation-1")
        self.assertEqual(message["toolInvocations"][0]["messageId"], "message-1")
        self.assertEqual(message["toolInvocations"][0]["toolName"], "get_quote")
        self.assertEqual(message["timelineParts"][0]["orderIndex"], 0)
        self.assertEqual(message["timelineParts"][1]["invocation"]["toolName"], "get_quote")
        self.assertNotIn("activeRun", payload)

    def test_schema_accepts_frontend_alias_payloads(self) -> None:
        parsed = ConversationMessagesResponse.model_validate(
            {
                "messages": [
                    {
                        "id": "message-1",
                        "conversationId": "conversation-1",
                        "role": "assistant",
                        "content": "",
                        "toolInvocations": [
                            {
                                "id": "tool-1",
                                "messageId": "message-1",
                                "toolName": "get_quote",
                                "args": {},
                                "status": "running",
                            }
                        ],
                        "timelineParts": [
                            {
                                "id": "part-1",
                                "type": "tool",
                                "orderIndex": 0,
                                "invocation": {
                                    "id": "tool-1",
                                    "messageId": "message-1",
                                    "toolName": "get_quote",
                                    "args": {},
                                    "status": "running",
                                },
                            }
                        ],
                        "createdAt": "2026-06-08T04:00:00Z",
                    }
                ],
                "activeRun": None,
            }
        )

        self.assertIsNone(parsed.active_run)
        self.assertEqual(parsed.messages[0].conversation_id, "conversation-1")
        self.assertEqual(parsed.messages[0].tool_invocations[0].tool_name, "get_quote")
        self.assertEqual(parsed.messages[0].timeline_parts[0].order_index, 0)

    def test_timeline_part_discriminator_accepts_reasoning_and_tool(self) -> None:
        adapter = TypeAdapter(ChatTimelinePart)

        reasoning = adapter.validate_python(
            {"id": "part-1", "type": "reasoning", "orderIndex": 0, "text": "think"}
        )
        tool = adapter.validate_python(
            {
                "id": "part-2",
                "type": "tool",
                "orderIndex": 1,
                "invocation": {
                    "id": "tool-1",
                    "messageId": "message-1",
                    "toolName": "get_quote",
                    "args": {},
                    "status": "completed",
                },
            }
        )

        self.assertEqual(reasoning.type, "reasoning")
        self.assertEqual(tool.invocation.tool_name, "get_quote")

    def test_projects_messages_with_tool_invocations_and_timeline_parts(self) -> None:
        created_at = datetime(2026, 6, 8, 4, 0, tzinfo=UTC)
        invocation = SimpleNamespace(
            id="tool-1",
            message_id="assistant-1",
            tool_name="get_quote",
            args={"symbol": "AAPL"},
            result={"price": 100},
            error=None,
            latency_ms=12,
            status="completed",
            created_at=created_at,
        )
        message = SimpleNamespace(
            id="assistant-1",
            conversation_id="conversation-1",
            role="assistant",
            content="AAPL is 100.",
            reasoning="Need quote.",
            status="done",
            created_at=created_at,
            tool_invocations=[invocation],
            timeline_parts=[
                SimpleNamespace(
                    id="part-tool",
                    type="tool",
                    order_index=1,
                    text="",
                    tool_invocation_id="tool-1",
                ),
                SimpleNamespace(
                    id="part-reasoning",
                    type="reasoning",
                    order_index=0,
                    text="Need quote.",
                    tool_invocation_id=None,
                ),
            ],
        )

        response = project_conversation_messages([message])
        payload = response.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(payload["messages"][0]["createdAt"], "2026-06-08T04:00:00Z")
        self.assertEqual(payload["messages"][0]["toolInvocations"][0]["createdAt"], "2026-06-08T04:00:00Z")
        self.assertEqual(
            [part["type"] for part in payload["messages"][0]["timelineParts"]],
            ["reasoning", "tool"],
        )
        self.assertEqual(
            payload["messages"][0]["timelineParts"][1]["invocation"]["id"],
            "tool-1",
        )
        self.assertNotIn("activeRun", payload)

    def test_projection_skips_tool_parts_without_matching_invocation(self) -> None:
        message = SimpleNamespace(
            id="assistant-1",
            conversation_id="conversation-1",
            role="assistant",
            content="",
            reasoning="",
            status="done",
            created_at=datetime(2026, 6, 8, 4, 0, tzinfo=UTC),
            tool_invocations=[],
            timeline_parts=[
                SimpleNamespace(
                    id="part-orphan-tool",
                    type="tool",
                    order_index=0,
                    text="",
                    tool_invocation_id="missing-tool",
                ),
                SimpleNamespace(
                    id="part-reasoning",
                    type="reasoning",
                    order_index=1,
                    text="still ok",
                    tool_invocation_id=None,
                ),
            ],
        )

        response = project_conversation_messages([message])
        parts = response.model_dump(by_alias=True, exclude_none=True)["messages"][0][
            "timelineParts"
        ]

        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]["type"], "reasoning")

    def test_projection_skips_unknown_and_approval_timeline_part_types(self) -> None:
        message = SimpleNamespace(
            id="assistant-1",
            conversation_id="conversation-1",
            role="assistant",
            content="",
            reasoning="",
            status="done",
            created_at=datetime(2026, 6, 8, 4, 0, tzinfo=UTC),
            tool_invocations=[],
            timeline_parts=[
                SimpleNamespace(
                    id="part-reasoning",
                    type="reasoning",
                    order_index=0,
                    text="kept",
                    tool_invocation_id=None,
                ),
                SimpleNamespace(
                    id="part-approval",
                    type="approval",
                    order_index=1,
                    text="should skip",
                    tool_invocation_id=None,
                ),
                SimpleNamespace(
                    id="part-unknown",
                    type="custom",
                    order_index=2,
                    text="should skip",
                    tool_invocation_id=None,
                ),
            ],
        )

        response = project_conversation_messages([message])
        parts = response.model_dump(by_alias=True, exclude_none=True)["messages"][0][
            "timelineParts"
        ]

        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]["id"], "part-reasoning")
        self.assertEqual(parts[0]["type"], "reasoning")


if __name__ == "__main__":
    unittest.main()
