# AI Chat Streaming Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 跑通第一条真实 AI 对话流式纵向链路：`fronted` 通过 SSE 调 Go BFF，BFF 通过 gRPC server-streaming 调 Python Agent，Agent 使用 LangGraph 编排并调用 DeepSeek streaming API。

**Architecture:** 浏览器只使用 HTTP/SSE；Go BFF 负责鉴权、HTTP/SSE、gRPC 客户端和消息持久化边界；Python Agent 负责 LangGraph 编排、DeepSeek provider 和输出 guardrail。第一阶段不接入行情、研究卡片、Feishu 推送或 resume。

**Tech Stack:** Next.js App Router、React、TypeScript、`@microsoft/fetch-event-source`、Vitest、Go 1.26、chi、grpc-go、Buf、Python 3.12、grpcio、LangGraph、httpx、pytest、DeepSeek chat completions streaming。

---

## Scope Check

本计划只实现 `docs/superpowers/specs/2026-05-17-ai-chat-streaming-flow-design.md` 中的第一阶段 AI 对话流。它包含前端流式对话、BFF SSE endpoint、Agent gRPC streaming、LangGraph 问答 graph、DeepSeek streaming provider 和最小持久化边界。

本计划不实现登录页面、自选股、行情、研究卡片、通知、Lark 推送、聊天 resume、多 Agent 协作或 chunk 级数据库写入。

## File Structure

创建和修改以下文件：

```text
.
├── proto/investment/v1/agent.proto
├── buf.yaml
├── buf.gen.yaml
├── backend
│   ├── go.mod
│   ├── cmd/bff/main.go
│   ├── internal/bff/chat_stream.go
│   ├── internal/bff/chat_stream_test.go
│   ├── internal/bff/server.go
│   ├── internal/bff/server_test.go
│   └── gen/go
├── agent
│   ├── pyproject.toml
│   ├── app/config.py
│   ├── app/graphs/question_answer.py
│   ├── app/providers/deepseek.py
│   ├── app/server.py
│   ├── app/gen
│   └── tests
│       ├── test_deepseek_provider.py
│       ├── test_question_answer_graph.py
│       └── test_server_stream.py
├── fronted
│   ├── app/page.tsx
│   └── features/ai
│       ├── ChatPanel.tsx
│       ├── ChatPanel.test.tsx
│       ├── chat-event-parser.ts
│       ├── chat-event-parser.test.ts
│       ├── chat-stream-client.ts
│       ├── types.ts
│       └── useChatStream.ts
├── .env.example
└── Makefile
```

Boundary decisions:

- `proto/investment/v1/agent.proto` 是 Go/Python 之间唯一共享的 Agent 契约。
- `agent/app/providers/deepseek.py` 只处理 DeepSeek HTTP streaming payload，不知道 gRPC。
- `agent/app/graphs/question_answer.py` 只处理 graph 输入、上下文、消息构造、guardrail 和流式文本事件。
- `agent/app/server.py` 只处理 gRPC request/response 转换。
- `backend/internal/bff/chat_stream.go` 只处理 HTTP/SSE、用户消息保存边界、gRPC stream 读取和错误转换。
- `fronted/features/ai/chat-stream-client.ts` 只处理 POST SSE 请求。
- `fronted/features/ai/chat-event-parser.ts` 只处理 SSE data 解析。
- `fronted/features/ai/useChatStream.ts` 只处理 UI message state、AbortController 和生命周期。
- `fronted/features/ai/ChatPanel.tsx` 只处理渲染和用户交互。

## Task 1: Protobuf Streaming Contract

**Files:**
- Create: `proto/investment/v1/agent.proto`
- Create: `buf.yaml`
- Create: `buf.gen.yaml`
- Modify: `Makefile`
- Generated: `backend/gen/go`
- Generated: `agent/app/gen`

- [ ] **Step 1: Write the contract first**

Create `proto/investment/v1/agent.proto`:

```proto
syntax = "proto3";

package investment.v1;

option go_package = "github.com/bytedance/ai-investment-assistant/backend/gen/go/investment/v1;investmentv1";

service AgentService {
  rpc StreamAnswerQuestion(StreamAnswerQuestionRequest) returns (stream AnswerChunk);
}

message StreamAnswerQuestionRequest {
  string user_id = 1;
  string conversation_id = 2;
  string user_message_id = 3;
  string assistant_message_id = 4;
  string content = 5;
  PageContext page_context = 6;
}

message PageContext {
  string route = 1;
  string symbol = 2;
  string event_id = 3;
  string research_card_id = 4;
}

message AnswerChunk {
  string conversation_id = 1;
  string assistant_message_id = 2;
  AnswerChunkType type = 3;
  string content = 4;
  string finish_reason = 5;
  string error_code = 6;
  string error_message = 7;
}

enum AnswerChunkType {
  ANSWER_CHUNK_TYPE_UNSPECIFIED = 0;
  ANSWER_CHUNK_TYPE_METADATA = 1;
  ANSWER_CHUNK_TYPE_DELTA = 2;
  ANSWER_CHUNK_TYPE_DONE = 3;
  ANSWER_CHUNK_TYPE_ERROR = 4;
}
```

- [ ] **Step 2: Add Buf config**

Create `buf.yaml`:

```yaml
version: v2
modules:
  - path: proto
lint:
  use:
    - STANDARD
breaking:
  use:
    - FILE
```

Create `buf.gen.yaml`:

```yaml
version: v2
plugins:
  - remote: buf.build/protocolbuffers/go
    out: backend/gen/go
    opt:
      - paths=source_relative
  - remote: buf.build/grpc/go
    out: backend/gen/go
    opt:
      - paths=source_relative
  - remote: buf.build/protocolbuffers/python
    out: agent/app/gen
  - remote: buf.build/grpc/python
    out: agent/app/gen
```

- [ ] **Step 3: Add proto command**

Modify `Makefile` so it contains this target without removing existing unrelated targets:

```makefile
.PHONY: proto
proto:
	buf generate
```

- [ ] **Step 4: Generate code**

Run:

```bash
make proto
```

Expected:

```text
buf generate
```

Generated files include:

```text
backend/gen/go/investment/v1/agent.pb.go
backend/gen/go/investment/v1/agent_grpc.pb.go
agent/app/gen/investment/v1/agent_pb2.py
agent/app/gen/investment/v1/agent_pb2_grpc.py
```

- [ ] **Step 5: Commit**

```bash
git add proto buf.yaml buf.gen.yaml backend/gen agent/app/gen Makefile
git commit -m "feat: define agent streaming contract"
```

## Task 2: Python Agent Project Skeleton

**Files:**
- Create: `agent/pyproject.toml`
- Create: `agent/app/config.py`
- Create: `agent/app/providers/deepseek.py`
- Create: `agent/tests/test_deepseek_provider.py`

- [ ] **Step 1: Create Python project config**

Create `agent/pyproject.toml`:

```toml
[project]
name = "ai-investment-agent"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "grpcio>=1.76.0",
  "grpcio-tools>=1.76.0",
  "httpx>=0.28.1",
  "langgraph>=1.0.4",
  "pydantic>=2.12.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=9.0.0",
  "pytest-asyncio>=1.3.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = [".", "app/gen"]
testpaths = ["tests"]
```

- [ ] **Step 2: Add config**

Create `agent/app/config.py`:

```python
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
```

- [ ] **Step 3: Write failing provider tests**

Create `agent/tests/test_deepseek_provider.py`:

```python
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
```

- [ ] **Step 4: Verify tests fail**

Run:

```bash
cd agent && python -m pytest tests/test_deepseek_provider.py -q
```

Expected: FAIL because `app.providers.deepseek` does not exist.

- [ ] **Step 5: Implement DeepSeek provider**

Create `agent/app/providers/deepseek.py`:

```python
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
```

- [ ] **Step 6: Verify provider tests pass**

Run:

```bash
cd agent && python -m pytest tests/test_deepseek_provider.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 7: Commit**

```bash
git add agent/pyproject.toml agent/app/config.py agent/app/providers/deepseek.py agent/tests/test_deepseek_provider.py
git commit -m "feat: add deepseek streaming provider"
```

## Task 3: LangGraph Question Answer Graph

**Files:**
- Create: `agent/app/graphs/question_answer.py`
- Create: `agent/tests/test_question_answer_graph.py`

- [ ] **Step 1: Write failing graph tests**

Create `agent/tests/test_question_answer_graph.py`:

```python
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
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
cd agent && python -m pytest tests/test_question_answer_graph.py -q
```

Expected: FAIL because `app.graphs.question_answer` does not exist.

- [ ] **Step 3: Implement graph**

Create `agent/app/graphs/question_answer.py`:

```python
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
```

- [ ] **Step 4: Verify graph tests pass**

Run:

```bash
cd agent && python -m pytest tests/test_question_answer_graph.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add agent/app/graphs/question_answer.py agent/tests/test_question_answer_graph.py
git commit -m "feat: add langgraph question answer stream"
```

## Task 4: Agent gRPC Streaming Server

**Files:**
- Create: `agent/app/server.py`
- Create: `agent/tests/test_server_stream.py`

- [ ] **Step 1: Write failing server conversion test**

Create `agent/tests/test_server_stream.py`:

```python
from collections.abc import AsyncIterator

import pytest

from app.server import AgentServicer
from investment.v1 import agent_pb2


class FakeGraph:
    async def stream(self, request) -> AsyncIterator[str]:
        yield "first "
        yield "second"


@pytest.mark.asyncio
async def test_stream_answer_question_returns_metadata_delta_done():
    servicer = AgentServicer(graph=FakeGraph())
    request = agent_pb2.StreamAnswerQuestionRequest(
        user_id="user-1",
        conversation_id="conversation-1",
        user_message_id="message-user-1",
        assistant_message_id="message-assistant-1",
        content="hello",
        page_context=agent_pb2.PageContext(route="/", symbol="AAPL"),
    )

    chunks = [chunk async for chunk in servicer.StreamAnswerQuestion(request, None)]

    assert [chunk.type for chunk in chunks] == [
        agent_pb2.ANSWER_CHUNK_TYPE_METADATA,
        agent_pb2.ANSWER_CHUNK_TYPE_DELTA,
        agent_pb2.ANSWER_CHUNK_TYPE_DELTA,
        agent_pb2.ANSWER_CHUNK_TYPE_DONE,
    ]
    assert chunks[1].content == "first "
    assert chunks[2].content == "second"
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
cd agent && python -m pytest tests/test_server_stream.py -q
```

Expected: FAIL because `app.server` does not exist.

- [ ] **Step 3: Implement server conversion**

Create `agent/app/server.py`:

```python
from collections.abc import AsyncIterator
import asyncio

import grpc

from app.config import load_settings
from app.graphs.question_answer import QuestionAnswerGraph, QuestionInput
from app.providers.deepseek import DeepSeekError, DeepSeekProvider
from investment.v1 import agent_pb2, agent_pb2_grpc


def _page_context_to_dict(page_context: agent_pb2.PageContext) -> dict[str, str]:
    return {
        "route": page_context.route,
        "symbol": page_context.symbol,
        "event_id": page_context.event_id,
        "research_card_id": page_context.research_card_id,
    }


class AgentServicer(agent_pb2_grpc.AgentServiceServicer):
    def __init__(self, graph: QuestionAnswerGraph) -> None:
        self.graph = graph

    async def StreamAnswerQuestion(
        self,
        request: agent_pb2.StreamAnswerQuestionRequest,
        context: grpc.aio.ServicerContext | None,
    ) -> AsyncIterator[agent_pb2.AnswerChunk]:
        yield agent_pb2.AnswerChunk(
            conversation_id=request.conversation_id,
            assistant_message_id=request.assistant_message_id,
            type=agent_pb2.ANSWER_CHUNK_TYPE_METADATA,
        )

        graph_input = QuestionInput(
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            user_message_id=request.user_message_id,
            assistant_message_id=request.assistant_message_id,
            content=request.content,
            page_context=_page_context_to_dict(request.page_context),
        )

        try:
            async for content in self.graph.stream(graph_input):
                yield agent_pb2.AnswerChunk(
                    conversation_id=request.conversation_id,
                    assistant_message_id=request.assistant_message_id,
                    type=agent_pb2.ANSWER_CHUNK_TYPE_DELTA,
                    content=content,
                )
            yield agent_pb2.AnswerChunk(
                conversation_id=request.conversation_id,
                assistant_message_id=request.assistant_message_id,
                type=agent_pb2.ANSWER_CHUNK_TYPE_DONE,
                finish_reason="stop",
            )
        except DeepSeekError as exc:
            yield agent_pb2.AnswerChunk(
                conversation_id=request.conversation_id,
                assistant_message_id=request.assistant_message_id,
                type=agent_pb2.ANSWER_CHUNK_TYPE_ERROR,
                error_code=exc.code,
                error_message=str(exc),
            )
        except ValueError as exc:
            yield agent_pb2.AnswerChunk(
                conversation_id=request.conversation_id,
                assistant_message_id=request.assistant_message_id,
                type=agent_pb2.ANSWER_CHUNK_TYPE_ERROR,
                error_code="INVALID_ARGUMENT",
                error_message=str(exc),
            )


async def serve() -> None:
    settings = load_settings()
    provider = DeepSeekProvider(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        timeout_seconds=settings.deepseek_timeout_seconds,
    )
    graph = QuestionAnswerGraph(provider=provider)
    server = grpc.aio.server()
    agent_pb2_grpc.add_AgentServiceServicer_to_server(AgentServicer(graph=graph), server)
    server.add_insecure_port(settings.grpc_bind_addr)
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
```

- [ ] **Step 4: Verify Agent tests pass**

Run:

```bash
cd agent && python -m pytest -q
```

Expected:

```text
7 passed
```

- [ ] **Step 5: Commit**

```bash
git add agent/app/server.py agent/tests/test_server_stream.py
git commit -m "feat: add agent grpc streaming server"
```

## Task 5: Go BFF SSE Endpoint With Fake Agent Stream

**Files:**
- Create: `backend/go.mod`
- Generated: `backend/go.sum`
- Create: `backend/internal/bff/chat_stream.go`
- Create: `backend/internal/bff/chat_stream_test.go`
- Create: `backend/internal/bff/server.go`
- Create: `backend/internal/bff/server_test.go`
- Create: `backend/cmd/bff/main.go`

- [ ] **Step 1: Create Go module**

Create `backend/go.mod`:

```go
module github.com/bytedance/ai-investment-assistant/backend

go 1.26

require (
	github.com/go-chi/chi/v5 v5.2.3
	google.golang.org/grpc v1.77.0
)
```

- [ ] **Step 2: Write failing SSE encoder tests**

Create `backend/internal/bff/chat_stream_test.go`:

```go
package bff

import (
	"strings"
	"testing"
)

func TestEncodeSSE(t *testing.T) {
	got := encodeSSE("delta", `{"content":"hello"}`)
	want := "event: delta\ndata: {\"content\":\"hello\"}\n\n"
	if got != want {
		t.Fatalf("encodeSSE() = %q, want %q", got, want)
	}
}

func TestValidateChatRequestRejectsEmptyContent(t *testing.T) {
	err := validateChatRequest(chatStreamRequest{Content: strings.Repeat(" ", 3)})
	if err == nil || err.Error() != "content is required" {
		t.Fatalf("expected content is required, got %v", err)
	}
}
```

- [ ] **Step 3: Verify tests fail**

Run:

```bash
cd backend && go test ./internal/bff -run 'TestEncodeSSE|TestValidateChatRequestRejectsEmptyContent'
```

Expected: FAIL because `encodeSSE`, `validateChatRequest`, and `chatStreamRequest` do not exist.

- [ ] **Step 4: Implement chat stream handler core**

Create `backend/internal/bff/chat_stream.go`:

```go
package bff

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
)

type PageContext struct {
	Route          string `json:"route"`
	Symbol         string `json:"symbol"`
	EventID        string `json:"eventId"`
	ResearchCardID string `json:"researchCardId"`
}

type chatStreamRequest struct {
	ConversationID string      `json:"conversationId"`
	Content        string      `json:"content"`
	PageContext    PageContext `json:"pageContext"`
}

type AgentChunkType string

const (
	AgentChunkMetadata AgentChunkType = "metadata"
	AgentChunkDelta    AgentChunkType = "delta"
	AgentChunkDone     AgentChunkType = "done"
	AgentChunkError    AgentChunkType = "error"
)

type AgentChunk struct {
	Type               AgentChunkType
	ConversationID     string
	UserMessageID      string
	AssistantMessageID string
	Content            string
	FinishReason       string
	ErrorCode          string
	ErrorMessage       string
}

type AgentStreamClient interface {
	StreamAnswer(ctx context.Context, req AgentStreamRequest) (<-chan AgentChunk, error)
}

type AgentStreamRequest struct {
	UserID             string
	ConversationID     string
	UserMessageID      string
	AssistantMessageID string
	Content            string
	PageContext        PageContext
}

func validateChatRequest(req chatStreamRequest) error {
	content := strings.TrimSpace(req.Content)
	if content == "" {
		return errors.New("content is required")
	}
	if len([]rune(content)) > 4000 {
		return errors.New("content is too long")
	}
	return nil
}

func encodeSSE(event string, data string) string {
	return fmt.Sprintf("event: %s\ndata: %s\n\n", event, data)
}

func chunkToSSE(chunk AgentChunk) (string, error) {
	switch chunk.Type {
	case AgentChunkMetadata:
		payload := map[string]string{
			"conversationId":     chunk.ConversationID,
			"userMessageId":      chunk.UserMessageID,
			"assistantMessageId": chunk.AssistantMessageID,
		}
		data, err := json.Marshal(payload)
		if err != nil {
			return "", err
		}
		return encodeSSE("metadata", string(data)), nil
	case AgentChunkDelta:
		data, err := json.Marshal(map[string]string{"content": chunk.Content})
		if err != nil {
			return "", err
		}
		return encodeSSE("delta", string(data)), nil
	case AgentChunkDone:
		data, err := json.Marshal(map[string]string{"finishReason": chunk.FinishReason})
		if err != nil {
			return "", err
		}
		return encodeSSE("done", string(data)), nil
	case AgentChunkError:
		data, err := json.Marshal(map[string]string{
			"code":    chunk.ErrorCode,
			"message": chunk.ErrorMessage,
		})
		if err != nil {
			return "", err
		}
		return encodeSSE("error", string(data)), nil
	default:
		return "", fmt.Errorf("unsupported chunk type %q", chunk.Type)
	}
}

func decodeChatStreamRequest(r *http.Request) (chatStreamRequest, error) {
	var req chatStreamRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		return chatStreamRequest{}, err
	}
	return req, validateChatRequest(req)
}
```

- [ ] **Step 5: Verify core tests pass**

Run:

```bash
cd backend && go test ./internal/bff -run 'TestEncodeSSE|TestValidateChatRequestRejectsEmptyContent'
```

Expected:

```text
ok  	github.com/bytedance/ai-investment-assistant/backend/internal/bff
```

- [ ] **Step 6: Write failing HTTP route test**

Create `backend/internal/bff/server_test.go`:

```go
package bff

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

type fakeAgentStreamClient struct{}

func (fakeAgentStreamClient) StreamAnswer(ctx context.Context, req AgentStreamRequest) (<-chan AgentChunk, error) {
	ch := make(chan AgentChunk, 4)
	ch <- AgentChunk{
		Type:               AgentChunkMetadata,
		ConversationID:     req.ConversationID,
		UserMessageID:      req.UserMessageID,
		AssistantMessageID: req.AssistantMessageID,
	}
	ch <- AgentChunk{Type: AgentChunkDelta, Content: "hello "}
	ch <- AgentChunk{Type: AgentChunkDelta, Content: "world"}
	ch <- AgentChunk{Type: AgentChunkDone, FinishReason: "stop"}
	close(ch)
	return ch, nil
}

func TestChatStreamRouteReturnsSSE(t *testing.T) {
	server := NewServer(fakeAgentStreamClient{})
	body := `{"content":"hello","pageContext":{"route":"/","symbol":"AAPL","eventId":"","researchCardId":""}}`
	req := httptest.NewRequest(http.MethodPost, "/api/chat/stream", strings.NewReader(body))
	req.Header.Set("Authorization", "Bearer local-dev")
	rec := httptest.NewRecorder()

	server.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	if got := rec.Header().Get("Content-Type"); got != "text/event-stream" {
		t.Fatalf("Content-Type = %q, want text/event-stream", got)
	}
	bodyText := rec.Body.String()
	for _, want := range []string{"event: metadata", "event: delta", "hello ", "world", "event: done"} {
		if !strings.Contains(bodyText, want) {
			t.Fatalf("body missing %q: %s", want, bodyText)
		}
	}
}
```

- [ ] **Step 7: Verify route test fails**

Run:

```bash
cd backend && go test ./internal/bff -run TestChatStreamRouteReturnsSSE
```

Expected: FAIL because `NewServer` does not exist.

- [ ] **Step 8: Implement server route**

Create `backend/internal/bff/server.go`:

```go
package bff

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
)

type Server struct {
	router chi.Router
	agent  AgentStreamClient
}

func NewServer(agent AgentStreamClient) *Server {
	s := &Server{router: chi.NewRouter(), agent: agent}
	s.router.Post("/api/chat/stream", s.handleChatStream)
	s.router.Get("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	return s
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.router.ServeHTTP(w, r)
}

func (s *Server) handleChatStream(w http.ResponseWriter, r *http.Request) {
	if r.Header.Get("Authorization") == "" {
		writeJSONError(w, http.StatusUnauthorized, "UNAUTHORIZED", "authorization is required")
		return
	}

	req, err := decodeChatStreamRequest(r)
	if err != nil {
		writeJSONError(w, http.StatusBadRequest, "INVALID_REQUEST", err.Error())
		return
	}

	conversationID := req.ConversationID
	if conversationID == "" {
		conversationID = newID("conversation")
	}
	userMessageID := newID("message-user")
	assistantMessageID := newID("message-assistant")

	stream, err := s.agent.StreamAnswer(r.Context(), AgentStreamRequest{
		UserID:             "local-user",
		ConversationID:     conversationID,
		UserMessageID:      userMessageID,
		AssistantMessageID: assistantMessageID,
		Content:            req.Content,
		PageContext:        req.PageContext,
	})
	if err != nil {
		writeJSONError(w, http.StatusBadGateway, "AGENT_UNAVAILABLE", err.Error())
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	flusher, _ := w.(http.Flusher)

	for chunk := range stream {
		if chunk.Type == AgentChunkMetadata {
			chunk.ConversationID = conversationID
			chunk.UserMessageID = userMessageID
			chunk.AssistantMessageID = assistantMessageID
		}
		event, err := chunkToSSE(chunk)
		if err != nil {
			event = encodeSSE("error", `{"code":"SSE_ENCODE_FAILED","message":"failed to encode stream event"}`)
		}
		_, _ = w.Write([]byte(event))
		if flusher != nil {
			flusher.Flush()
		}
	}
}

func writeJSONError(w http.ResponseWriter, status int, code string, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"code": code, "message": message})
}

func newID(prefix string) string {
	var bytes [8]byte
	_, err := rand.Read(bytes[:])
	if err != nil {
		return prefix + "-0000000000000000"
	}
	return prefix + "-" + hex.EncodeToString(bytes[:])
}
```

Create `backend/cmd/bff/main.go`:

```go
package main

import (
	"context"
	"log"
	"net/http"

	"github.com/bytedance/ai-investment-assistant/backend/internal/bff"
)

type localAgent struct{}

func (localAgent) StreamAnswer(ctx context.Context, req bff.AgentStreamRequest) (<-chan bff.AgentChunk, error) {
	ch := make(chan bff.AgentChunk, 4)
	go func() {
		defer close(ch)
		ch <- bff.AgentChunk{Type: bff.AgentChunkMetadata}
		ch <- bff.AgentChunk{Type: bff.AgentChunkDelta, Content: "这是本地 BFF fake Agent 输出。"}
		ch <- bff.AgentChunk{Type: bff.AgentChunkDelta, Content: "真实 Agent 接入会在后续任务替换。"}
		ch <- bff.AgentChunk{Type: bff.AgentChunkDone, FinishReason: "stop"}
	}()
	return ch, nil
}

func main() {
	server := bff.NewServer(localAgent{})
	log.Println("BFF listening on :8080")
	if err := http.ListenAndServe(":8080", server); err != nil {
		log.Fatal(err)
	}
}
```

- [ ] **Step 9: Tidy Go dependencies**

Run:

```bash
cd backend && go mod tidy
```

Expected: `backend/go.sum` is created or updated, and the command exits with code `0`.

- [ ] **Step 10: Verify BFF tests pass**

Run:

```bash
cd backend && go test ./internal/bff
```

Expected:

```text
ok  	github.com/bytedance/ai-investment-assistant/backend/internal/bff
```

- [ ] **Step 11: Commit**

```bash
git add backend
git commit -m "feat: add bff sse chat endpoint"
```

## Task 6: Frontend Stream Parser, Client, and Hook

**Files:**
- Create: `fronted/features/ai/types.ts`
- Create: `fronted/features/ai/chat-event-parser.ts`
- Create: `fronted/features/ai/chat-event-parser.test.ts`
- Create: `fronted/features/ai/chat-stream-client.ts`
- Create: `fronted/features/ai/useChatStream.ts`

- [ ] **Step 1: Write failing event parser tests**

Create `fronted/features/ai/chat-event-parser.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { parseChatStreamEvent } from "./chat-event-parser";

describe("parseChatStreamEvent", () => {
  it("parses metadata events", () => {
    expect(
      parseChatStreamEvent("metadata", {
        conversationId: "conversation-1",
        userMessageId: "message-user-1",
        assistantMessageId: "message-assistant-1",
      }),
    ).toEqual({
      type: "metadata",
      conversationId: "conversation-1",
      userMessageId: "message-user-1",
      assistantMessageId: "message-assistant-1",
    });
  });

  it("parses delta events", () => {
    expect(parseChatStreamEvent("delta", { content: "hello" })).toEqual({
      type: "delta",
      content: "hello",
    });
  });

  it("parses error events", () => {
    expect(
      parseChatStreamEvent("error", {
        code: "AGENT_UNAVAILABLE",
        message: "Agent service is unavailable",
      }),
    ).toEqual({
      type: "error",
      code: "AGENT_UNAVAILABLE",
      message: "Agent service is unavailable",
    });
  });
});
```

- [ ] **Step 2: Verify parser tests fail**

Run:

```bash
cd fronted && pnpm test -- features/ai/chat-event-parser.test.ts
```

Expected: FAIL because `chat-event-parser.ts` does not exist.

- [ ] **Step 3: Implement types and parser**

Create `fronted/features/ai/types.ts`:

```typescript
export type MessageStatus =
  | "pending"
  | "streaming"
  | "completed"
  | "error"
  | "aborted";

export type ChatRole = "user" | "assistant";

export type PageContext = {
  route: string;
  symbol: string;
  eventId: string;
  researchCardId: string;
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  status: MessageStatus;
};

export type ChatStreamRequest = {
  conversationId: string;
  content: string;
  pageContext: PageContext;
};

export type ChatStreamEvent =
  | {
      type: "metadata";
      conversationId: string;
      userMessageId: string;
      assistantMessageId: string;
    }
  | { type: "delta"; content: string }
  | { type: "done"; finishReason: string }
  | { type: "error"; code: string; message: string };
```

Create `fronted/features/ai/chat-event-parser.ts`:

```typescript
import type { ChatStreamEvent } from "./types";

type EventPayload = Record<string, unknown>;

function readString(payload: EventPayload, key: string): string {
  const value = payload[key];
  return typeof value === "string" ? value : "";
}

export function parseChatStreamEvent(
  eventName: string,
  payload: EventPayload,
): ChatStreamEvent {
  if (eventName === "metadata") {
    return {
      type: "metadata",
      conversationId: readString(payload, "conversationId"),
      userMessageId: readString(payload, "userMessageId"),
      assistantMessageId: readString(payload, "assistantMessageId"),
    };
  }
  if (eventName === "delta") {
    return { type: "delta", content: readString(payload, "content") };
  }
  if (eventName === "done") {
    return { type: "done", finishReason: readString(payload, "finishReason") };
  }
  if (eventName === "error") {
    return {
      type: "error",
      code: readString(payload, "code"),
      message: readString(payload, "message"),
    };
  }
  return {
    type: "error",
    code: "UNKNOWN_STREAM_EVENT",
    message: `Unknown stream event: ${eventName}`,
  };
}
```

- [ ] **Step 4: Verify parser tests pass**

Run:

```bash
cd fronted && pnpm test -- features/ai/chat-event-parser.test.ts
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Implement stream client**

Create `fronted/features/ai/chat-stream-client.ts`:

```typescript
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { parseChatStreamEvent } from "./chat-event-parser";
import type { ChatStreamEvent, ChatStreamRequest } from "./types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";

export type StartChatStreamOptions = {
  request: ChatStreamRequest;
  token: string;
  signal: AbortSignal;
  onEvent: (event: ChatStreamEvent) => void;
};

export async function startChatStream({
  request,
  token,
  signal,
  onEvent,
}: StartChatStreamOptions): Promise<void> {
  await fetchEventSource(`${API_BASE_URL}/api/chat/stream`, {
    method: "POST",
    headers: {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(request),
    signal,
    onmessage(message) {
      const payload =
        message.data.trim() === "" ? {} : (JSON.parse(message.data) as Record<string, unknown>);
      onEvent(parseChatStreamEvent(message.event, payload));
    },
  });
}
```

- [ ] **Step 6: Implement hook**

Create `fronted/features/ai/useChatStream.ts`:

```typescript
"use client";

import { useRef, useState } from "react";
import { startChatStream } from "./chat-stream-client";
import type { ChatMessage, ChatStreamEvent, PageContext } from "./types";

function localID(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

export function useChatStream() {
  const [conversationId, setConversationId] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const handleEvent = (event: ChatStreamEvent) => {
    if (event.type === "metadata") {
      setConversationId(event.conversationId);
      setMessages((current) =>
        current.map((message) =>
          message.id === "assistant-pending"
            ? { ...message, id: event.assistantMessageId, status: "streaming" }
            : message,
        ),
      );
      return;
    }
    if (event.type === "delta") {
      setMessages((current) =>
        current.map((message) =>
          message.role === "assistant" && message.status === "streaming"
            ? { ...message, content: message.content + event.content }
            : message,
        ),
      );
      return;
    }
    if (event.type === "done") {
      setMessages((current) =>
        current.map((message) =>
          message.role === "assistant" && message.status === "streaming"
            ? { ...message, status: "completed" }
            : message,
        ),
      );
      abortRef.current = null;
      return;
    }
    setMessages((current) =>
      current.map((message) =>
        message.role === "assistant" && message.status === "streaming"
          ? {
              ...message,
              status: "error",
              content: message.content || event.message,
            }
          : message,
      ),
    );
    abortRef.current = null;
  };

  const sendMessage = async (content: string, pageContext: PageContext) => {
    if (abortRef.current) {
      throw new Error("当前回答仍在生成，请先停止。");
    }
    const trimmed = content.trim();
    if (!trimmed) {
      throw new Error("请输入问题。");
    }

    const controller = new AbortController();
    abortRef.current = controller;
    setMessages((current) => [
      ...current,
      {
        id: localID("message-user"),
        role: "user",
        content: trimmed,
        status: "completed",
      },
      {
        id: "assistant-pending",
        role: "assistant",
        content: "",
        status: "pending",
      },
    ]);

    await startChatStream({
      request: { conversationId, content: trimmed, pageContext },
      token: "local-dev",
      signal: controller.signal,
      onEvent: handleEvent,
    });
  };

  const stop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setMessages((current) =>
      current.map((message) =>
        message.role === "assistant" && ["pending", "streaming"].includes(message.status)
          ? { ...message, status: "aborted" }
          : message,
      ),
    );
  };

  return { conversationId, messages, sendMessage, stop };
}
```

- [ ] **Step 7: Verify frontend parser and typecheck**

Run:

```bash
cd fronted && pnpm test -- features/ai/chat-event-parser.test.ts && pnpm typecheck
```

Expected:

```text
1 passed
```

`pnpm typecheck` exits with code `0`.

- [ ] **Step 8: Commit**

```bash
git add fronted/features/ai
git commit -m "feat: add frontend chat stream client"
```

## Task 7: ChatPanel UI Integration

**Files:**
- Create: `fronted/features/ai/ChatPanel.tsx`
- Create: `fronted/features/ai/ChatPanel.test.tsx`
- Modify: `fronted/app/page.tsx`

- [ ] **Step 1: Write failing ChatPanel render test**

Create `fronted/features/ai/ChatPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ChatPanel } from "./ChatPanel";

describe("ChatPanel", () => {
  it("renders input and action buttons", () => {
    render(<ChatPanel />);

    expect(
      screen.getByPlaceholderText("输入你想追问的股票或事件"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "停止回答" })).toBeInTheDocument();
  });

  it("lets the user type a question", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.type(
      screen.getByPlaceholderText("输入你想追问的股票或事件"),
      "帮我分析 AAPL 风险",
    );

    expect(screen.getByDisplayValue("帮我分析 AAPL 风险")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Verify ChatPanel tests fail**

Run:

```bash
cd fronted && pnpm test -- features/ai/ChatPanel.test.tsx
```

Expected: FAIL because `ChatPanel.tsx` does not exist.

- [ ] **Step 3: Implement ChatPanel**

Create `fronted/features/ai/ChatPanel.tsx`:

```tsx
"use client";

import { Send, Square } from "lucide-react";
import { useState } from "react";
import { useChatStream } from "./useChatStream";

export function ChatPanel() {
  const [input, setInput] = useState("");
  const { messages, sendMessage, stop } = useChatStream();
  const [error, setError] = useState("");

  const onSubmit = async () => {
    setError("");
    try {
      await sendMessage(input, {
        route: "/",
        symbol: "AAPL",
        eventId: "",
        researchCardId: "",
      });
      setInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送失败");
    }
  };

  return (
    <section className="flex min-h-[560px] flex-col rounded-lg border border-zinc-200 bg-white">
      <div className="border-b border-zinc-200 px-4 py-3">
        <div className="text-sm font-medium text-zinc-900">AI 对话</div>
      </div>
      <div className="flex flex-1 flex-col gap-3 p-4">
        {messages.length === 0 ? (
          <div className="max-w-[85%] rounded-lg bg-zinc-100 px-3 py-2 text-sm leading-6 text-zinc-700">
            今天可以先从自选股风险、财报变化或宏观事件切入。
          </div>
        ) : (
          messages.map((message) => (
            <div
              className={
                message.role === "user"
                  ? "ml-auto max-w-[85%] rounded-lg bg-emerald-700 px-3 py-2 text-sm leading-6 text-white"
                  : "max-w-[85%] rounded-lg bg-zinc-100 px-3 py-2 text-sm leading-6 text-zinc-700"
              }
              key={message.id}
            >
              {message.content || (message.status === "pending" ? "正在连接 Agent..." : "")}
            </div>
          ))
        )}
        {error ? <p className="text-sm text-rose-700">{error}</p> : null}
        <div className="mt-auto rounded-lg border border-zinc-200 bg-zinc-50 p-2">
          <textarea
            className="min-h-24 w-full resize-none bg-transparent p-2 text-sm outline-none placeholder:text-zinc-400"
            onChange={(event) => setInput(event.target.value)}
            placeholder="输入你想追问的股票或事件"
            value={input}
          />
          <div className="flex items-center justify-between border-t border-zinc-200 px-2 pt-2">
            <button
              aria-label="停止回答"
              className="inline-flex size-8 items-center justify-center rounded-md text-zinc-500 hover:bg-zinc-100"
              onClick={stop}
              type="button"
            >
              <Square className="size-4" aria-hidden="true" />
            </button>
            <button
              className="inline-flex items-center gap-2 rounded-md bg-emerald-700 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-800"
              onClick={onSubmit}
              type="button"
            >
              <Send className="size-4" aria-hidden="true" />
              发送
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Replace static chat panel in page**

Modify `fronted/app/page.tsx`:

```typescript
import { ChatPanel } from "@/features/ai/ChatPanel";
```

Replace the existing static left-column AI chat `<section>` with:

```tsx
<ChatPanel />
```

Do not change the center research area or right watchlist area in this task.

- [ ] **Step 5: Verify frontend**

Run:

```bash
cd fronted && pnpm check
```

Expected:

```text
Test Files  3 passed
```

`lint`, `typecheck`, and `build` exit with code `0`.

- [ ] **Step 6: Commit**

```bash
git add fronted/app/page.tsx fronted/features/ai
git commit -m "feat: wire chat panel shell"
```

## Task 8: Replace BFF Fake Agent With gRPC Client

**Files:**
- Modify: `backend/internal/bff/chat_stream.go`
- Create: `backend/internal/bff/agent_grpc_client.go`
- Create: `backend/internal/bff/agent_grpc_client_test.go`
- Modify: `backend/cmd/bff/main.go`

- [ ] **Step 1: Write failing chunk mapping test**

Create `backend/internal/bff/agent_grpc_client_test.go`:

```go
package bff

import (
	"testing"

	investmentv1 "github.com/bytedance/ai-investment-assistant/backend/gen/go/investment/v1"
)

func TestProtoChunkToAgentChunkMapsDelta(t *testing.T) {
	got := protoChunkToAgentChunk(&investmentv1.AnswerChunk{
		Type:    investmentv1.AnswerChunkType_ANSWER_CHUNK_TYPE_DELTA,
		Content: "hello",
	})

	if got.Type != AgentChunkDelta || got.Content != "hello" {
		t.Fatalf("unexpected mapped chunk: %#v", got)
	}
}
```

- [ ] **Step 2: Verify test fails**

Run:

```bash
cd backend && go test ./internal/bff -run TestProtoChunkToAgentChunkMapsDelta
```

Expected: FAIL because `protoChunkToAgentChunk` does not exist.

- [ ] **Step 3: Implement gRPC client adapter**

Create `backend/internal/bff/agent_grpc_client.go`:

```go
package bff

import (
	"context"
	"io"

	investmentv1 "github.com/bytedance/ai-investment-assistant/backend/gen/go/investment/v1"
	"google.golang.org/grpc"
)

type AgentGRPCClient struct {
	client investmentv1.AgentServiceClient
}

func NewAgentGRPCClient(conn grpc.ClientConnInterface) *AgentGRPCClient {
	return &AgentGRPCClient{client: investmentv1.NewAgentServiceClient(conn)}
}

func (c *AgentGRPCClient) StreamAnswer(ctx context.Context, req AgentStreamRequest) (<-chan AgentChunk, error) {
	stream, err := c.client.StreamAnswerQuestion(ctx, &investmentv1.StreamAnswerQuestionRequest{
		UserId:             req.UserID,
		ConversationId:     req.ConversationID,
		UserMessageId:      req.UserMessageID,
		AssistantMessageId: req.AssistantMessageID,
		Content:            req.Content,
		PageContext: &investmentv1.PageContext{
			Route:          req.PageContext.Route,
			Symbol:         req.PageContext.Symbol,
			EventId:        req.PageContext.EventID,
			ResearchCardId: req.PageContext.ResearchCardID,
		},
	})
	if err != nil {
		return nil, err
	}

	out := make(chan AgentChunk)
	go func() {
		defer close(out)
		for {
			chunk, err := stream.Recv()
			if err == io.EOF {
				return
			}
			if err != nil {
				out <- AgentChunk{
					Type:         AgentChunkError,
					ErrorCode:    "AGENT_STREAM_INTERRUPTED",
					ErrorMessage: err.Error(),
				}
				return
			}
			out <- protoChunkToAgentChunk(chunk)
		}
	}()
	return out, nil
}

func protoChunkToAgentChunk(chunk *investmentv1.AnswerChunk) AgentChunk {
	switch chunk.Type {
	case investmentv1.AnswerChunkType_ANSWER_CHUNK_TYPE_METADATA:
		return AgentChunk{Type: AgentChunkMetadata}
	case investmentv1.AnswerChunkType_ANSWER_CHUNK_TYPE_DELTA:
		return AgentChunk{Type: AgentChunkDelta, Content: chunk.Content}
	case investmentv1.AnswerChunkType_ANSWER_CHUNK_TYPE_DONE:
		return AgentChunk{Type: AgentChunkDone, FinishReason: chunk.FinishReason}
	case investmentv1.AnswerChunkType_ANSWER_CHUNK_TYPE_ERROR:
		return AgentChunk{
			Type:         AgentChunkError,
			ErrorCode:    chunk.ErrorCode,
			ErrorMessage: chunk.ErrorMessage,
		}
	default:
		return AgentChunk{
			Type:         AgentChunkError,
			ErrorCode:    "UNKNOWN_AGENT_CHUNK",
			ErrorMessage: "unknown agent chunk type",
		}
	}
}
```

Modify `backend/cmd/bff/main.go` to dial Agent:

```go
package main

import (
	"log"
	"net/http"
	"os"

	"github.com/bytedance/ai-investment-assistant/backend/internal/bff"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

func main() {
	agentAddr := os.Getenv("AGENT_GRPC_ADDR")
	if agentAddr == "" {
		agentAddr = "127.0.0.1:9010"
	}
	conn, err := grpc.NewClient(agentAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Fatal(err)
	}
	defer conn.Close()

	server := bff.NewServer(bff.NewAgentGRPCClient(conn))
	log.Println("BFF listening on :8080")
	if err := http.ListenAndServe(":8080", server); err != nil {
		log.Fatal(err)
	}
}
```

- [ ] **Step 4: Verify backend**

Run:

```bash
cd backend && go test ./...
```

Expected:

```text
ok  	github.com/bytedance/ai-investment-assistant/backend/internal/bff
```

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: connect bff to agent grpc stream"
```

## Task 9: Environment and End-to-End Smoke Commands

**Files:**
- Modify: `.env.example`
- Modify: `Makefile`

- [ ] **Step 1: Update env example**

Modify `.env.example` so it includes these values:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080
AGENT_GRPC_ADDR=127.0.0.1:9010
AGENT_GRPC_BIND_ADDR=127.0.0.1:9010
DEEPSEEK_API_KEY=local-deepseek-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_TIMEOUT_SECONDS=60
```

- [ ] **Step 2: Add focused verification targets**

Modify `Makefile` so it contains these targets without deleting existing targets:

```makefile
.PHONY: test-agent test-backend test-fronted check-chat-slice

test-agent:
	cd agent && python -m pytest -q

test-backend:
	cd backend && go test ./...

test-fronted:
	cd fronted && pnpm check

check-chat-slice: proto test-agent test-backend test-fronted
```

- [ ] **Step 3: Verify all automated checks**

Run:

```bash
make check-chat-slice
```

Expected:

```text
buf generate
cd agent && python -m pytest -q
cd backend && go test ./...
cd fronted && pnpm check
```

All commands exit with code `0`.

- [ ] **Step 4: Manual smoke test with real services**

Terminal 1:

```bash
cd agent
DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" python -m app.server
```

Expected:

```text
Agent gRPC server listening on 127.0.0.1:9010
```

Terminal 2:

```bash
cd backend
AGENT_GRPC_ADDR=127.0.0.1:9010 go run ./cmd/bff
```

Expected:

```text
BFF listening on :8080
```

Terminal 3:

```bash
cd fronted
pnpm dev
```

Expected:

```text
Local: http://localhost:3000
```

Open `http://localhost:3000`, ask:

```text
帮我分析一下 AAPL 最近需要关注什么风险
```

Expected: UI displays streaming text chunks and the final answer contains `非投资建议，仅供研究参考`.

- [ ] **Step 5: Commit**

```bash
git add .env.example Makefile
git commit -m "chore: add chat slice verification commands"
```

## Self-Review Checklist

- Spec coverage:
  - Frontend SSE request: Task 6 and Task 7.
  - BFF `POST /api/chat/stream`: Task 5 and Task 8.
  - gRPC server-streaming: Task 1, Task 4, and Task 8.
  - LangGraph graph: Task 3.
  - DeepSeek `stream: true`: Task 2.
  - Message lifecycle `pending` / `streaming` / `completed` / `error` / `aborted`: Task 6 and Task 7.
  - Guardrail disclaimer: Task 3.
  - Verification: Task 9.

- Placeholder scan:
  - This plan uses concrete file paths, code snippets, commands, and expected outputs.
  - Generated protobuf files are produced by `make proto`, not hand-written.
  - Real DeepSeek key remains environment-provided and is never committed.

- Type consistency:
  - Frontend request uses `conversationId`, `content`, and `pageContext`.
  - BFF JSON request maps `eventId` and `researchCardId` to Go fields `EventID` and `ResearchCardID`.
  - Protobuf uses `event_id` and `research_card_id`.
  - SSE uses `metadata`, `delta`, `done`, and `error`.
  - gRPC uses `ANSWER_CHUNK_TYPE_METADATA`, `ANSWER_CHUNK_TYPE_DELTA`, `ANSWER_CHUNK_TYPE_DONE`, and `ANSWER_CHUNK_TYPE_ERROR`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-18-ai-chat-streaming-flow.md`. Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.

2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.

Recommended choice: **Subagent-Driven** for Tasks 1-8, because protobuf, Agent, BFF, and frontend are separate write scopes.
