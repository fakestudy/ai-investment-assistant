import os
from collections.abc import AsyncIterator

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import Message, SessionStore

from core.config import get_settings


BUILTIN_TOOLS = [
    "Task",
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
]


SYSTEM_PROMPT = (
    "You are an AI investment assistant. Answer clearly and use tools only when "
    "they are needed to satisfy the user's request."
)


def _anthropic_env() -> dict[str, str]:
    settings = get_settings()
    env: dict[str, str] = {}
    if settings.anthropic_base_url:
        env["ANTHROPIC_BASE_URL"] = settings.anthropic_base_url
    if settings.anthropic_auth_token:
        env["ANTHROPIC_AUTH_TOKEN"] = settings.anthropic_auth_token
        env["ANTHROPIC_API_KEY"] = settings.anthropic_auth_token

    for name in (
        "ANTHROPIC_SMALL_FAST_MODEL",
        "ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION",
        "ANTHROPIC_VERTEX_PROJECT_ID",
        "ANTHROPIC_VERTEX_REGION",
    ):
        value = os.environ.get(name)
        if value:
            env[name] = value
    return env


def build_options(
    *,
    session_store: SessionStore,
    resume: str | None = None,
) -> ClaudeAgentOptions:
    settings = get_settings()
    return ClaudeAgentOptions(
        allowed_tools=BUILTIN_TOOLS,
        include_partial_messages=True,
        permission_mode="acceptEdits",
        setting_sources=[],
        system_prompt=SYSTEM_PROMPT,
        model=settings.anthropic_model or None,
        resume=resume,
        session_store=session_store,
        env=_anthropic_env(),
    )


def stream_query(
    *,
    prompt: str,
    session_store: SessionStore,
    resume: str | None = None,
) -> AsyncIterator[Message]:
    return query(
        prompt=prompt,
        options=build_options(session_store=session_store, resume=resume),
    )
