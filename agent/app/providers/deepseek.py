from collections.abc import AsyncIterator
import json
from typing import Any

import httpx


class DeepSeekError(Exception):
    code = "DEEPSEEK_ERROR"


class DeepSeekAuthError(DeepSeekError):
    code = "DEEPSEEK_AUTH_FAILED"


class DeepSeekRateLimitError(DeepSeekError):
    code = "DEEPSEEK_RATE_LIMITED"


class DeepSeekTimeoutError(DeepSeekError):
    code = "DEEPSEEK_TIMEOUT"


class DeepSeekStreamInterruptedError(DeepSeekError):
    code = "DEEPSEEK_STREAM_INTERRUPTED"


class DeepSeekBadResponseError(DeepSeekError):
    code = "DEEPSEEK_BAD_RESPONSE"


def parse_stream_line(line: bytes) -> str | None:
    text = line.decode("utf-8").strip()
    if not text:
        return None
    if not text.startswith("data: "):
        return None
    payload = text.removeprefix("data: ").strip()
    if payload == "[DONE]":
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise DeepSeekBadResponseError("DeepSeek returned invalid stream JSON") from exc

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first_choice: Any = choices[0]
    if not isinstance(first_choice, dict):
        return None
    delta = first_choice.get("delta")
    if not isinstance(delta, dict):
        return None
    content = delta.get("content")
    if not isinstance(content, str):
        return None
    return content


class DeepSeekProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        if not self.api_key:
            raise DeepSeekAuthError("DEEPSEEK_API_KEY is required")

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        timeout = httpx.Timeout(self.timeout_seconds)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status_code in {401, 403}:
                        raise DeepSeekAuthError("DeepSeek authentication failed")
                    if response.status_code == 429:
                        raise DeepSeekRateLimitError("DeepSeek rate limit exceeded")
                    if response.status_code >= 400:
                        raise DeepSeekBadResponseError(
                            f"DeepSeek returned status {response.status_code}"
                        )
                    async for line in response.aiter_lines():
                        content = parse_stream_line(line.encode("utf-8"))
                        if content:
                            yield content
        except httpx.TimeoutException as exc:
            raise DeepSeekTimeoutError("DeepSeek request timed out") from exc
        except httpx.TransportError as exc:
            raise DeepSeekStreamInterruptedError("DeepSeek stream interrupted") from exc
