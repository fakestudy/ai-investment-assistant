import unittest
from datetime import UTC, datetime

from model.message import Message
from tests.chat_stream_test_helpers import FakeChatStreamSessionFactory


class ChatCommandsTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_balance_command_streams_tool_result_delta_and_done(self) -> None:
        from service.chat_commands import stream_get_balance_command

        factory = FakeChatStreamSessionFactory()
        factory.session.add(
            Message(
                id="assistant-1",
                conversation_id="conversation-1",
                role="assistant",
                content="",
                reasoning="",
                status="streaming",
                created_at=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
            )
        )

        async def fake_fetch_balance():
            return {
                "is_available": True,
                "balance_infos": [
                    {
                        "currency": "CNY",
                        "total_balance": "110.00",
                        "granted_balance": "10.00",
                        "topped_up_balance": "100.00",
                    }
                ],
            }

        events = [
            event.model_dump(by_alias=True, exclude_none=True)
            async for event in stream_get_balance_command(
                message_id="assistant-1",
                fetch_balance=fake_fetch_balance,
                async_session_factory=factory,
                now_factory=lambda: datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
            )
        ]

        self.assertEqual(
            [event["type"] for event in events],
            ["tool_call", "tool_result", "delta", "done"],
        )
        self.assertEqual(events[0]["invocation"]["toolName"], "get_deepseek_balance")
        self.assertEqual(events[0]["invocation"]["status"], "running")
        self.assertEqual(events[1]["invocation"]["status"], "completed")
        self.assertEqual(
            events[1]["invocation"]["result"]["balance_infos"][0]["total_balance"],
            "110.00",
        )
        self.assertIn("| CNY | 110.00 | 10.00 | 100.00 |", events[2]["text"])
        self.assertEqual(events[3]["messageId"], "assistant-1")

        assistant = factory.session.messages["assistant-1"]
        self.assertEqual(assistant.status, "done")
        self.assertEqual(assistant.content, events[2]["text"])
        parts = list(factory.session.messages["_message_parts"].values())
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].type, "tool")
        self.assertEqual(parts[0].order_index, 0)

    def test_exact_get_balance_command_is_supported(self) -> None:
        from service.chat_commands import is_get_balance_command

        self.assertTrue(is_get_balance_command(" /get-balance "))
        self.assertFalse(is_get_balance_command("/get-balance now"))
        self.assertFalse(is_get_balance_command("get-balance"))


if __name__ == "__main__":
    unittest.main()
