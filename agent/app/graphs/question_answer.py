from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict


DISCLAIMER = "非投资建议，仅供研究参考"


class StreamingProvider(Protocol):
    def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        pass


@dataclass(frozen=True)
class QuestionInput:
    user_id: str
    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    content: str
    page_context: dict[str, str]


class QuestionState(TypedDict):
    request: QuestionInput
    messages: list[dict[str, str]]


def _build_system_prompt() -> str:
    return (
        "你是投资研究助手，只提供研究辅助。"
        "不要输出买入、卖出、加仓、减仓等直接交易指令。"
        "回答需要说明依据、风险和不确定性。"
        f"回答末尾必须包含：{DISCLAIMER}。"
    )


def _format_page_context(page_context: dict[str, str]) -> str:
    pairs = [
        f"route={page_context.get('route', '')}",
        f"symbol={page_context.get('symbol', '')}",
        f"event_id={page_context.get('event_id', '')}",
        f"research_card_id={page_context.get('research_card_id', '')}",
    ]
    return "页面上下文：" + "；".join(pairs)


class QuestionAnswerGraph:
    def __init__(self, provider: StreamingProvider) -> None:
        self.provider = provider
        builder: StateGraph[QuestionState] = StateGraph(QuestionState)
        builder.add_node("validate_input", self._validate_input)
        builder.add_node("build_messages", self._build_messages)
        builder.add_edge(START, "validate_input")
        builder.add_edge("validate_input", "build_messages")
        builder.add_edge("build_messages", END)
        self.graph = builder.compile()

    def _validate_input(self, state: QuestionState) -> QuestionState:
        content = state["request"].content.strip()
        if not content:
            raise ValueError("content is required")
        if len(content) > 4000:
            raise ValueError("content is too long")
        return state

    def _build_messages(self, state: QuestionState) -> QuestionState:
        request = state["request"]
        context = _format_page_context(request.page_context)
        state["messages"] = [
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": f"{context}\n\n问题：{request.content.strip()}"},
        ]
        return state

    async def stream(self, request: QuestionInput) -> AsyncIterator[str]:
        state = await self.graph.ainvoke({"request": request, "messages": []})
        collected: list[str] = []
        async for chunk in self.provider.stream_chat(state["messages"]):
            collected.append(chunk)
            yield chunk
        final_text = "".join(collected)
        if DISCLAIMER not in final_text:
            yield f"\n\n{DISCLAIMER}"
