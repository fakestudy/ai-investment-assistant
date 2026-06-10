import os
from typing import cast
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    SessionStore,
    TextBlock,
)

from core.config import Settings
from service.runtime import _anthropic_env, build_options, generate_title, stream_query


def _settings(
    *,
    token: str = "test-token",
    model: str = "claude-test",
    approval_required_tools: tuple[str, ...] = (),
) -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        anthropic_base_url="https://anthropic.example",
        anthropic_auth_token=token,
        anthropic_model=model,
        approval_required_tools=approval_required_tools,
    )


class RuntimeEnvTest(unittest.TestCase):
    def test_build_options_uses_read_only_tool_allowlist_by_default(self) -> None:
        with patch("service.runtime.get_settings", return_value=_settings()):
            options = build_options(session_store=cast(SessionStore, object()))

        self.assertEqual(
            set(options.allowed_tools),
            {"Read", "Glob", "Grep", "WebSearch", "WebFetch"},
        )
        self.assertEqual(options.permission_mode, "default")

    def test_build_options_removes_approval_required_tools_and_attaches_hook(
        self,
    ) -> None:
        async def fake_can_use_tool(tool_name, tool_input, context):
            return None

        with patch(
            "service.runtime.get_settings",
            return_value=_settings(approval_required_tools=("WebFetch", "Grep")),
        ):
            options = build_options(
                session_store=cast(SessionStore, object()),
                can_use_tool=fake_can_use_tool,
            )

        self.assertEqual(set(options.allowed_tools), {"Read", "Glob", "WebSearch"})
        self.assertIs(options.can_use_tool, fake_can_use_tool)
        self.assertEqual(options.permission_mode, "default")

    def test_build_options_keeps_control_channel_open_for_approval_hook(
        self,
    ) -> None:
        async def fake_can_use_tool(tool_name, tool_input, context):
            return None

        with patch(
            "service.runtime.get_settings",
            return_value=_settings(approval_required_tools=("WebSearch",)),
        ):
            options = build_options(
                session_store=cast(SessionStore, object()),
                can_use_tool=fake_can_use_tool,
            )

        self.assertIsNotNone(options.hooks)
        self.assertIn("PreToolUse", options.hooks or {})
        matchers = (options.hooks or {})["PreToolUse"]
        self.assertEqual(len(matchers), 1)
        self.assertEqual(matchers[0].matcher, "__agent_claude_approval_keepalive__")
        self.assertEqual(len(matchers[0].hooks), 1)

    def test_settings_parses_approval_required_tools(self) -> None:
        from core.config import get_settings

        with patch.dict(
            os.environ,
            {
                "AGENT_CLAUDE_APPROVAL_TOOLS": " WebFetch, Grep,,Read ",
            },
            clear=True,
        ):
            settings = get_settings()

        self.assertEqual(
            settings.approval_required_tools,
            ("WebFetch", "Grep", "Read"),
        )

    def test_validate_runtime_settings_requires_auth_token_and_model(self) -> None:
        from core.config import validate_runtime_settings

        with patch("core.config.get_settings", return_value=_settings(token="")):
            with self.assertRaisesRegex(RuntimeError, "ANTHROPIC_AUTH_TOKEN"):
                validate_runtime_settings()

        with patch("core.config.get_settings", return_value=_settings(model="")):
            with self.assertRaisesRegex(RuntimeError, "ANTHROPIC_MODEL"):
                validate_runtime_settings()

    def test_anthropic_env_forwards_all_anthropic_vars_and_maps_auth_token(self) -> None:
        patched_env = {
            "ANTHROPIC_AUTH_TOKEN": "settings-token",
            "ANTHROPIC_BASE_URL": "https://settings.example",
            "ANTHROPIC_MODEL": "claude-settings",
            "ANTHROPIC_CUSTOM_HEADER": "custom-value",
            "ANTHROPIC_API_KEY": "ambient-token",
            "UNRELATED": "ignored",
        }

        with patch.dict(os.environ, patched_env, clear=True):
            env = _anthropic_env()

        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "settings-token")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "settings-token")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://settings.example")
        self.assertEqual(env["ANTHROPIC_MODEL"], "claude-settings")
        self.assertEqual(env["ANTHROPIC_CUSTOM_HEADER"], "custom-value")
        self.assertNotIn("UNRELATED", env)


class RuntimeStreamQueryTest(unittest.IsolatedAsyncioTestCase):
    async def test_stream_query_uses_async_prompt_when_can_use_tool_is_set(
        self,
    ) -> None:
        async def fake_can_use_tool(tool_name, tool_input, context):
            return None

        async def empty_messages():
            if False:
                yield object()

        captured = {}

        def fake_query(*, prompt, options):
            captured["prompt"] = prompt
            captured["can_use_tool"] = options.can_use_tool
            return empty_messages()

        with (
            patch("service.runtime.get_settings", return_value=_settings()),
            patch("service.runtime.query", fake_query),
        ):
            async for _ in stream_query(
                prompt="hello",
                session_store=cast(SessionStore, object()),
                can_use_tool=fake_can_use_tool,
            ):
                pass

        self.assertIs(captured["can_use_tool"], fake_can_use_tool)
        self.assertNotIsInstance(captured["prompt"], str)

        events = []
        async for event in captured["prompt"]:
            events.append(event)

        self.assertEqual(
            events,
            [
                {
                    "type": "user",
                    "session_id": "",
                    "message": {"role": "user", "content": "hello"},
                    "parent_tool_use_id": None,
                }
            ],
        )

    async def test_generate_title_uses_sdk_title_subagent(self) -> None:
        async def fake_messages():
            yield AssistantMessage(
                content=[TextBlock(text='"Apple risk review"')],
                model="claude-test",
            )

        captured = {}

        def fake_query(*, prompt, options):
            captured["prompt"] = prompt
            captured["options"] = options
            return fake_messages()

        with (
            patch("service.runtime.get_settings", return_value=_settings()),
            patch("service.runtime.query", fake_query),
        ):
            title = await generate_title("Analyze Apple investment risks")

        options = captured["options"]
        self.assertEqual(title, "Apple risk review")
        self.assertIn("Analyze Apple investment risks", captured["prompt"])
        self.assertIn("title-generator", options.agents)
        self.assertEqual(options.tools, ["Agent"])
        self.assertEqual(options.allowed_tools, ["Agent"])
        self.assertEqual(options.permission_mode, "dontAsk")
        self.assertEqual(options.max_turns, 3)

    async def test_generate_title_returns_none_when_agent_produces_no_title(
        self,
    ) -> None:
        async def fake_messages():
            if False:
                yield object()

        def fake_query(*, prompt, options):
            return fake_messages()

        with (
            patch("service.runtime.get_settings", return_value=_settings()),
            patch("service.runtime.query", fake_query),
        ):
            title = await generate_title(
                "Please analyze Apple investment risks in detail"
            )

        self.assertIsNone(title)

    async def test_generate_title_deduplicates_assistant_text_and_result(
        self,
    ) -> None:
        async def fake_messages():
            yield AssistantMessage(
                content=[TextBlock(text="多城市天气查询")],
                model="claude-test",
            )
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="session-1",
                result="多城市天气查询",
            )

        def fake_query(*, prompt, options):
            return fake_messages()

        with (
            patch("service.runtime.get_settings", return_value=_settings()),
            patch("service.runtime.query", fake_query),
        ):
            title = await generate_title("查询北京和上海天气")

        self.assertEqual(title, "多城市天气查询")


class RunManagerSafeErrorBoundaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_execute_run_hides_unexpected_exception_and_marks_message_error(
        self,
    ) -> None:
        from model.message import Message
        from schema.chat import StreamChatRequest
        from service.run_manager import (
            RunManagerDependencies,
            _PreparedRun,
            _execute_run,
        )

        message = SimpleNamespace(id="assistant-1", status="streaming")
        session = _RuntimeSession(message)
        notifications: list[tuple[str, int]] = []

        async def fake_stream_executor(**kwargs):
            raise RuntimeError("provider secret leaked")
            if False:
                yield ""

        async def fake_update_run_status(db_session, *, run_id, status, error=None):
            db_session.operations.append((run_id, status, error))
            return SimpleNamespace(id=run_id, status=status, error=error)

        async def fake_append_run_event_row(db_session, *, event):
            event.id = 7
            db_session.appended_events.append(event)
            return event

        deps = RunManagerDependencies(
            async_session_factory=_RuntimeSessionFactory(session),
            update_run_status=fake_update_run_status,
            append_run_event_row=fake_append_run_event_row,
            stream_executor=fake_stream_executor,
            notify_run_event=lambda run_id, event_id: notifications.append(
                (run_id, event_id)
            ),
        )

        with patch("service.run_manager.logger.exception") as logged:
            await _execute_run(
                _PreparedRun(
                    run_id="run-1",
                    conversation_id="conversation-1",
                    assistant_message_id="assistant-1",
                ),
                StreamChatRequest(conversationId="conversation-1", message="hello"),
                deps,
            )

        self.assertEqual(message.status, "error")
        self.assertEqual(
            session.operations,
            [("run-1", "failed", "Agent run failed. Check server logs for details.")],
        )
        self.assertEqual(session.commits, 1)
        self.assertEqual(notifications, [("run-1", 7)])
        event = session.appended_events[0]
        self.assertEqual(event.event_type, "error")
        self.assertEqual(
            event.payload["message"],
            "Agent run failed. Check server logs for details.",
        )
        self.assertNotIn("provider secret leaked", event.payload["message"])
        logged.assert_called_once()


class _RuntimeSession:
    def __init__(self, message) -> None:
        self.message = message
        self.operations = []
        self.appended_events = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, model, object_id):
        from model.message import Message

        if model is Message and object_id == self.message.id:
            return self.message
        return None

    async def commit(self) -> None:
        self.commits += 1


class _RuntimeSessionFactory:
    def __init__(self, session: _RuntimeSession) -> None:
        self.session = session

    def __call__(self) -> _RuntimeSession:
        return self.session


if __name__ == "__main__":
    unittest.main()
