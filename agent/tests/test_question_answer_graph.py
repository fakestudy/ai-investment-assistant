from collections.abc import AsyncIterator

import pytest

from app.graphs.question_answer import (
    DISCLAIMER,
    QuestionAnswerGraph,
    QuestionInput,
)


class FakeProvider:
    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        assert messages[0]["role"] == "system"
        assert "非投资建议" in messages[0]["content"]
        assert messages[-1]["role"] == "user"
        yield "AAPL "
        yield "需要关注收入增长。"


@pytest.mark.asyncio
async def test_graph_streams_provider_content_and_appends_disclaimer():
    graph = QuestionAnswerGraph(provider=FakeProvider())
    request = QuestionInput(
        user_id="user-1",
        conversation_id="conversation-1",
        user_message_id="message-user-1",
        assistant_message_id="message-assistant-1",
        content="帮我分析 AAPL 风险",
        page_context={"route": "/", "symbol": "AAPL", "event_id": "", "research_card_id": ""},
    )

    chunks = [chunk async for chunk in graph.stream(request)]

    assert chunks == ["AAPL ", "需要关注收入增长。", f"\n\n{DISCLAIMER}"]


@pytest.mark.asyncio
async def test_graph_rejects_empty_content():
    graph = QuestionAnswerGraph(provider=FakeProvider())
    request = QuestionInput(
        user_id="user-1",
        conversation_id="conversation-1",
        user_message_id="message-user-1",
        assistant_message_id="message-assistant-1",
        content=" ",
        page_context={"route": "/", "symbol": "", "event_id": "", "research_card_id": ""},
    )

    with pytest.raises(ValueError, match="content is required"):
        chunks = [chunk async for chunk in graph.stream(request)]
        assert chunks == []
