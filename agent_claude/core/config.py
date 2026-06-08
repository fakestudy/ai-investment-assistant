import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str
    anthropic_base_url: str
    anthropic_auth_token: str
    anthropic_model: str


def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/agent_claude",
        ),
        anthropic_base_url=os.environ.get("ANTHROPIC_BASE_URL", ""),
        anthropic_auth_token=os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", ""),
    )
