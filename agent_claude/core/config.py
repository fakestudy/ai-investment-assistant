import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str
    anthropic_base_url: str
    anthropic_auth_token: str
    anthropic_model: str
    approval_required_tools: tuple[str, ...] = ()


def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/agent_claude",
        ),
        anthropic_base_url=os.environ.get("ANTHROPIC_BASE_URL", ""),
        anthropic_auth_token=os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", ""),
        approval_required_tools=_parse_csv_tuple(
            os.environ.get("AGENT_CLAUDE_APPROVAL_TOOLS", "")
        ),
    )


def validate_runtime_settings(settings: Settings | None = None) -> None:
    runtime_settings = settings or get_settings()
    if not runtime_settings.anthropic_auth_token:
        raise RuntimeError("ANTHROPIC_AUTH_TOKEN is required")
    if not runtime_settings.anthropic_model:
        raise RuntimeError("ANTHROPIC_MODEL is required")


def _parse_csv_tuple(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())
