from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    deepseek_timeout_seconds: float
    grpc_bind_addr: str


def load_settings() -> Settings:
    return Settings(
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        deepseek_timeout_seconds=float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60")),
        grpc_bind_addr=os.getenv("AGENT_GRPC_BIND_ADDR", "[::]:9010"),
    )
