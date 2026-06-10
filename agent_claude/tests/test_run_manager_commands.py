import unittest
from datetime import UTC, datetime
from types import SimpleNamespace

from model.message import Message
from schema.chat import StreamChatRequest
from tests.chat_stream_test_helpers import FakeChatStreamSessionFactory


class RunManagerCommandTest(unittest.IsolatedAsyncioTestCase):
    async def test_execute_run_handles_get_balance_command_without_agent_stream(
        self,
    ) -> None:
        from service.run_manager import (
            RunManagerDependencies,
            _PreparedRun,
            _execute_run,
        )

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
        appended_events = []
        terminal_rows = []

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

        async def fake_stream_executor(**kwargs):
            raise AssertionError("agent stream should not run for /get-balance")
            if False:
                yield ""

        async def fake_append_run_event(
            *,
            run_id,
            conversation_id,
            message_id,
            event,
        ):
            payload = event.model_dump(by_alias=True, exclude_none=True)
            payload["runId"] = run_id
            appended_events.append(payload)
            return len(appended_events)

        async def fake_update_run_status(session, *, run_id, status, error=None):
            return SimpleNamespace(id=run_id, status=status, error=error)

        async def fake_append_run_event_row(session, *, event):
            event.id = len(appended_events) + len(terminal_rows) + 1
            terminal_rows.append(event)
            return event

        deps = RunManagerDependencies(
            async_session_factory=factory,
            stream_executor=fake_stream_executor,
            fetch_deepseek_balance=fake_fetch_balance,
            append_run_event=fake_append_run_event,
            update_run_status=fake_update_run_status,
            append_run_event_row=fake_append_run_event_row,
            notify_run_event=lambda run_id, event_id: None,
        )

        await _execute_run(
            _PreparedRun(
                run_id="run-1",
                conversation_id="conversation-1",
                assistant_message_id="assistant-1",
            ),
            StreamChatRequest(conversationId="conversation-1", message="/get-balance"),
            deps,
        )

        self.assertEqual(
            [event["type"] for event in appended_events],
            ["tool_call", "tool_result", "delta"],
        )
        self.assertEqual(terminal_rows[0].event_type, "done")
        self.assertIn("DeepSeek 账户余额", factory.session.messages["assistant-1"].content)


if __name__ == "__main__":
    unittest.main()
