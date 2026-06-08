import unittest
from datetime import UTC, datetime
from types import SimpleNamespace

from pydantic import TypeAdapter

from schema.chat import (
    ChatTimelinePart,
    ConversationMessagesResponse,
    ToolInvocation,
)
from service.history import project_conversation_messages


class HistoryProjectionTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
