from contextlib import asynccontextmanager
import unittest
from unittest.mock import patch, sentinel

from service import agent_factory
from service.agent_factory import build_agent, build_hitl_interrupt_config


class AgentFactoryTest(unittest.TestCase):
    def test_only_weather_requires_approve_or_reject(self) -> None:
        config = build_hitl_interrupt_config()

        self.assertEqual(
            config,
            {"get_weather": {"allowed_decisions": ["approve", "reject"]}},
        )
        self.assertNotIn("get_deepseek_balance", config)

    def test_agent_receives_postgres_checkpointer(self) -> None:
        fake_model = object()

        with (
            patch(
                "service.agent_factory.create_agent",
                return_value=sentinel.agent,
            ) as create_agent_mock,
            patch("service.agent_factory.HumanInTheLoopMiddleware") as hitl_mock,
            patch("service.agent_factory.PIIMiddleware"),
        ):
            agent = build_agent(
                checkpointer=sentinel.checkpointer,
                model=fake_model,
            )

        self.assertIs(agent, sentinel.agent)
        self.assertIs(
            create_agent_mock.call_args.kwargs["checkpointer"],
            sentinel.checkpointer,
        )
        self.assertIs(create_agent_mock.call_args.kwargs["model"], fake_model)
        hitl_mock.assert_called_once_with(
            interrupt_on={"get_weather": {"allowed_decisions": ["approve", "reject"]}},
        )

    def test_chat_service_does_not_export_model_factory(self) -> None:
        from service import chat

        self.assertFalse(hasattr(chat, "get_model"))


class AgentLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_open_agent_opens_checkpointer_and_injects_it(self) -> None:
        events: list[str] = []

        @asynccontextmanager
        async def fake_open_checkpointer(database_url: str):
            events.append(f"open:{database_url}")
            try:
                yield sentinel.checkpointer
            finally:
                events.append("close")

        with (
            patch(
                "service.agent_factory.open_checkpointer",
                fake_open_checkpointer,
            ),
            patch(
                "service.agent_factory.build_agent",
                return_value=sentinel.agent,
            ) as build_agent_mock,
        ):
            async with agent_factory.open_agent(
                "postgresql+psycopg://user:pass@localhost/db",
                model=sentinel.model,
            ) as agent:
                self.assertIs(agent, sentinel.agent)

        build_agent_mock.assert_called_once_with(
            checkpointer=sentinel.checkpointer,
            model=sentinel.model,
        )
        self.assertEqual(
            events,
            ["open:postgresql+psycopg://user:pass@localhost/db", "close"],
        )


if __name__ == "__main__":
    unittest.main()
