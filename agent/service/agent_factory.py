import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, PIIMiddleware
from langchain_deepseek import ChatDeepSeek

from agent_tools.deepseek import get_deepseek_balance
from agent_tools.get_weather import get_weather
from core.checkpointer import open_checkpointer
from schema.context import Context


SYSTEM_PROMPT = (
    "You are a helpful assistant. "
    "Only call get_deepseek_balance when the user explicitly asks about "
    "DeepSeek balance, account balance, remaining quota, or costs. "
    "Do not query balance during ordinary conversations."
)


def get_model() -> ChatDeepSeek:
    return ChatDeepSeek(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        reasoning_effort="max",
        extra_body={"thinking": {"type": "enabled"}},
    )


def build_hitl_interrupt_config() -> dict[str, dict[str, list[str]]]:
    return {"get_weather": {"allowed_decisions": ["approve", "reject"]}}


def build_agent(*, checkpointer: Any | None = None, model: Any | None = None) -> Any:
    return create_agent(
        context_schema=Context,
        model=model or get_model(),
        tools=[get_weather, get_deepseek_balance],
        middleware=[
            HumanInTheLoopMiddleware(interrupt_on=build_hitl_interrupt_config()),
            PIIMiddleware(
                pii_type="email",
                strategy="redact",
                apply_to_input=True,
            ),
            PIIMiddleware(
                pii_type="credit_card",
                strategy="mask",
                apply_to_input=True,
            ),
            PIIMiddleware(
                pii_type="mac_address",
                strategy="block",
                apply_to_input=True,
                apply_to_output=True,
            ),
            PIIMiddleware(
                pii_type="ip",
                strategy="redact",
                apply_to_input=True,
            ),
        ],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )


@asynccontextmanager
async def open_agent(
    database_url: str,
    *,
    model: Any | None = None,
) -> AsyncIterator[Any]:
    async with open_checkpointer(database_url) as checkpointer:
        yield build_agent(checkpointer=checkpointer, model=model)
