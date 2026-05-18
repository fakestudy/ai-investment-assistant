import pytest

from app.providers.deepseek import (
    DeepSeekAuthError,
    DeepSeekBadResponseError,
    DeepSeekProvider,
    parse_stream_line,
)


def test_parse_stream_line_extracts_delta_content():
    line = b'data: {"choices":[{"delta":{"content":"hello"}}]}'

    assert parse_stream_line(line) == "hello"


def test_parse_stream_line_returns_none_for_done():
    assert parse_stream_line(b"data: [DONE]") is None


def test_parse_stream_line_rejects_bad_payload():
    with pytest.raises(DeepSeekBadResponseError):
        parse_stream_line(b"data: not-json")


@pytest.mark.asyncio
async def test_stream_chat_requires_api_key():
    provider = DeepSeekProvider(
        api_key="",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        timeout_seconds=1,
    )

    with pytest.raises(DeepSeekAuthError):
        chunks = [chunk async for chunk in provider.stream_chat([])]
        assert chunks == []
