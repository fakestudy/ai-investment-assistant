import os
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, query
from claude_agent_sdk.types import (
    AssistantMessage,
    CanUseTool,
    Message,
    ResultMessage,
    SessionStore,
    TextBlock,
)

from core.config import get_settings, validate_runtime_settings


BUILTIN_TOOLS = [
    "Read",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
]


SYSTEM_PROMPT = (
    "You are an AI investment assistant. Answer clearly and use tools only when "
    "they are needed to satisfy the user's request."
)

TITLE_SYSTEM_PROMPT = (
    "You generate concise chat titles. Summarize the user's intent; do not copy "
    "the full user message verbatim. Return only the title, with no explanation. "
    "Use the user's language when possible. Keep Chinese titles under 14 "
    "characters and English titles under 8 words."
)

TITLE_AGENT_NAME = "title-generator"


def _anthropic_env() -> dict[str, str]:
    settings = get_settings()
    env: dict[str, str] = {
        name: value
        for name, value in os.environ.items()
        if name.startswith("ANTHROPIC_")
    }
    if settings.anthropic_base_url:
        env["ANTHROPIC_BASE_URL"] = settings.anthropic_base_url
    if settings.anthropic_auth_token:
        env["ANTHROPIC_AUTH_TOKEN"] = settings.anthropic_auth_token
        env["ANTHROPIC_API_KEY"] = settings.anthropic_auth_token
    if settings.anthropic_model:
        env["ANTHROPIC_MODEL"] = settings.anthropic_model
    return env


def build_options(
    *,
    session_store: SessionStore,
    resume: str | None = None,
    can_use_tool: CanUseTool | None = None,
) -> ClaudeAgentOptions:
    settings = get_settings()
    validate_runtime_settings(settings)
    approval_required_tools = set(settings.approval_required_tools)
    return ClaudeAgentOptions(
        allowed_tools=[
            tool for tool in BUILTIN_TOOLS if tool not in approval_required_tools
        ],
        include_partial_messages=True,
        permission_mode="default",
        setting_sources=[],
        system_prompt=SYSTEM_PROMPT,
        model=settings.anthropic_model or None,
        resume=resume,
        session_store=session_store,
        env=_anthropic_env(),
        can_use_tool=can_use_tool,
    )


async def _prompt_stream(prompt: str) -> AsyncIterator[dict[str, Any]]:
    yield {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": prompt},
        "parent_tool_use_id": None,
    }


def stream_query(
    *,
    prompt: str,
    session_store: SessionStore,
    resume: str | None = None,
    can_use_tool: CanUseTool | None = None,
) -> AsyncIterator[Message]:
    sdk_prompt: str | AsyncIterable[dict[str, Any]]
    if can_use_tool is None:
        sdk_prompt = prompt
    else:
        sdk_prompt = _prompt_stream(prompt)

    return query(
        prompt=sdk_prompt,
        options=build_options(
            session_store=session_store,
            resume=resume,
            can_use_tool=can_use_tool,
        ),
    )


def _normalize_title(raw_title: str, *, source_prompt: str) -> str | None:
    title = " ".join(raw_title.strip().split())
    if not title:
        return None
    title = title.strip("\"'`“”‘’")
    source = " ".join(source_prompt.strip().split())
    if not title or (len(source) > 20 and title == source):
        return None
    return title[:60]


async def generate_title(prompt: str) -> str | None:
    settings = get_settings()
    validate_runtime_settings(settings)
    assistant_chunks: list[str] = []
    result_chunks: list[str] = []
    async for message in query(
        prompt=(
            f"Use the {TITLE_AGENT_NAME} agent to generate a concise chat title "
            "for this user message. Return only the title produced by the agent.\n\n"
            f"User message:\n{prompt}"
        ),
        options=ClaudeAgentOptions(
            tools=["Agent"],
            allowed_tools=["Agent"],
            permission_mode="dontAsk",
            setting_sources=[],
            system_prompt=TITLE_SYSTEM_PROMPT,
            model=settings.anthropic_model or None,
            env=_anthropic_env(),
            max_turns=3,
            agents={
                TITLE_AGENT_NAME: AgentDefinition(
                    description="Generates concise chat titles from a user message",
                    prompt=TITLE_SYSTEM_PROMPT,
                    tools=[],
                    model="inherit",
                    maxTurns=1,
                    permissionMode="dontAsk",
                )
            },
        ),
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    assistant_chunks.append(block.text)
        elif isinstance(message, ResultMessage) and message.result:
            result_chunks.append(message.result)

    return _normalize_title(
        " ".join(assistant_chunks or result_chunks),
        source_prompt=prompt,
    )
