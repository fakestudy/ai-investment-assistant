# AI 对话流式纵向链路设计方案

## 1. 目标

本方案把 AI 投资助手 v1 的第一阶段拆小为一条可独立交付的 AI 对话纵向链路：

```text
fronted ChatPanel
  -> Go BFF POST /api/chat/stream
  -> Python Agent gRPC StreamAnswerQuestion
  -> LangGraph question_answer graph
  -> DeepSeek chat/completions stream
  -> Agent gRPC AnswerChunk stream
  -> BFF SSE stream
  -> ChatPanel append delta
```

第一阶段的成功标准是：用户在前端输入问题后，浏览器通过 SSE 持续收到回答片段；Go BFF 只负责 HTTP、鉴权、协议转换和持久化边界；Python Agent 使用 LangGraph 编排问答流程，并通过 DeepSeek API 的 `stream: true` 能力产生真实模型输出。

## 2. 范围

### 包含

- 前端 AI 对话面板，支持提交问题、展示用户消息、展示助手流式回答、停止当前回答、错误态和重试入口。
- 前端到 BFF 使用 `POST /api/chat/stream`，响应为 `text/event-stream`。
- BFF 到 Agent 使用 gRPC server-streaming。
- Agent 使用 LangGraph 实现 `question_answer` graph。
- Agent 内部调用 DeepSeek `POST /chat/completions`，请求体设置 `stream: true`。
- 对话请求携带最小页面上下文：`route`、`symbol`、`event_id`、`research_card_id`。
- BFF 持久化用户消息和最终助手消息；不做 chunk 级持久化。
- 每次回答都带“非投资建议，仅供研究参考”的合规边界。

### 不包含

- 聊天 resume。
- WebSocket。
- 多 Agent 协作。
- 工具调用和行情实时检索。
- 研究卡片生成。
- Feishu/Lark 推送。
- chunk 级数据库写入。
- 多会话并发编辑同一条 assistant message 的冲突处理。

## 3. 方案选择

采用 **SSE + gRPC server-streaming + LangGraph + DeepSeek streaming**。

这个方案保留三个边界：

- 浏览器只理解 HTTP/SSE，不直接接触 gRPC。
- Go BFF 只依赖 protobuf 契约，不依赖 Python Agent 内部实现。
- Python Agent 的 LangGraph graph 可以独立调整节点、prompt、模型 provider 和输出约束。

不采用 BFF 直接 HTTP 调 Python Agent 的方案，因为它会绕开本项目学习 gRPC 服务边界的目标。不采用 WebSocket，因为第一阶段只有单向 assistant token stream，SSE 更简单。也不做 chunk 级持久化，因为第一阶段的核心风险在协议链路和模型流式输出，不在恢复能力。

## 4. 前端协议

### Request

`fronted` 调用：

```http
POST /api/chat/stream
Authorization: Bearer <access_token>
Content-Type: application/json
Accept: text/event-stream
```

请求体：

```json
{
  "conversationId": "optional-existing-thread-id",
  "content": "帮我分析一下 AAPL 最近的风险",
  "pageContext": {
    "route": "/",
    "symbol": "AAPL",
    "eventId": "",
    "researchCardId": ""
  }
}
```

`conversationId` 为空时，BFF 创建新 thread。`pageContext` 字段允许为空字符串，但字段名固定，避免前后端对上下文形状产生分歧。

### SSE Events

BFF 返回以下事件：

```text
event: metadata
data: {"conversationId":"11111111-1111-4111-8111-111111111111","userMessageId":"22222222-2222-4222-8222-222222222222","assistantMessageId":"33333333-3333-4333-8333-333333333333"}

event: delta
data: {"content":"AAPL "}

event: delta
data: {"content":"当前需要关注收入增长、毛利率和市场风险。"}

event: done
data: {"finishReason":"stop"}
```

错误事件：

```text
event: error
data: {"code":"AGENT_UNAVAILABLE","message":"Agent service is unavailable"}
```

前端只 append `delta.content`，不把 delta 当作完整快照。消息生命周期为：

- `pending`：用户消息已提交，等待 `metadata`。
- `streaming`：已收到 `metadata`，正在 append delta。
- `completed`：收到 `done`。
- `error`：收到 `error` 或连接失败。
- `aborted`：用户主动停止请求。

## 5. gRPC 契约

新增或调整 `proto/investment/v1/agent.proto`：

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

BFF 在调用 Agent 前生成 `conversation_id`、`user_message_id` 和 `assistant_message_id`，这样前端第一包 `metadata` 可以立即获得稳定 ID。Agent 必须原样回传这些 ID。

## 6. BFF 设计

BFF 负责：

- 校验 `Authorization`。
- 校验 `content` 非空且不超过 4000 个 Unicode 字符。
- 创建或读取 `chat_threads`。
- 写入用户消息。
- 创建 assistant message 占位记录，状态为 `streaming`。
- 调用 Agent `StreamAnswerQuestion`。
- 把 gRPC chunk 转换成 SSE event。
- 在内存中累计 assistant 内容。
- 收到 `DONE` 后，将 assistant message 更新为 `completed` 和完整内容。
- 用户中止连接时，取消 gRPC context，并把 assistant message 标记为 `aborted`。
- Agent 或 DeepSeek 失败时，把 assistant message 标记为 `error`。

BFF 不做 prompt 拼装，不直接调用 DeepSeek，不理解 LangGraph 节点，也不把内部 gRPC error 原样暴露给前端。

## 7. Agent 设计

Agent 使用 Python gRPC async server 暴露 `StreamAnswerQuestion`。gRPC handler 只做协议层工作：

- 把 protobuf request 转为 graph input。
- 调用 `question_answer` graph 的 async streaming 接口。
- 把 graph stream 事件转换为 `AnswerChunk`。
- 捕获 DeepSeek、LangGraph 和输入错误，转换为 `ANSWER_CHUNK_TYPE_ERROR`。

LangGraph graph 节点：

```text
validate_input
  -> build_context
  -> build_messages
  -> deepseek_stream
  -> finalize_answer
```

节点职责：

- `validate_input`：检查问题为空、超过 4000 个 Unicode 字符、明显越界交易指令等输入问题。
- `build_context`：把 `page_context` 转成模型可理解的上下文；第一阶段不查行情和研究卡片数据库，只写入“当前页面上下文”。
- `build_messages`：构造 DeepSeek messages，包含系统约束、用户问题和上下文。
- `deepseek_stream`：调用 DeepSeek streaming API，将 `delta.content` 转成 graph custom stream。
- `finalize_answer`：汇总完整回答，确保免责声明存在。

如果 DeepSeek chunk 内没有 `delta.content`，Agent 忽略该 chunk。收到 DeepSeek `data: [DONE]` 后，Agent 发送 `ANSWER_CHUNK_TYPE_DONE`。

## 8. DeepSeek Provider

Agent 内部封装 `DeepSeekProvider.stream_chat(messages)`：

```python
class DeepSeekProvider:
    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        async for content in self._stream_deepseek_deltas(messages):
            yield content
```

Provider 读取环境变量：

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`
- `DEEPSEEK_TIMEOUT_SECONDS`

第一阶段默认使用 `DEEPSEEK_MODEL=deepseek-v4-flash`。如果现有环境样例仍是旧的 `deepseek-chat`，实现本切片时一并同步为 `deepseek-v4-flash`。

请求形状：

```json
{
  "model": "deepseek-v4-flash",
  "messages": [
    {"role": "system", "content": "你是投资研究助手，只提供研究辅助，不提供交易指令。"},
    {"role": "user", "content": "页面上下文：symbol=AAPL。问题：帮我分析一下 AAPL 最近的风险。"}
  ],
  "stream": true,
  "temperature": 0.2
}
```

Provider 只返回普通文本 delta，不向上泄漏 DeepSeek 原始 payload。原始错误被映射成内部错误码：

- `DEEPSEEK_AUTH_FAILED`
- `DEEPSEEK_RATE_LIMITED`
- `DEEPSEEK_TIMEOUT`
- `DEEPSEEK_STREAM_INTERRUPTED`
- `DEEPSEEK_BAD_RESPONSE`

## 9. 前端状态和交互

`ChatPanel` 拆成三层：

- `chatStreamClient`：封装 `@microsoft/fetch-event-source`，只处理 HTTP/SSE。
- `chatEventParser`：把 SSE event data 转成内部事件。
- `useChatStream`：管理当前请求、AbortController、消息 append 和状态切换。

第一阶段只支持一个活跃 stream。用户再次发送问题时，如果已有 stream 未结束，前端先提示停止当前回答，避免多个 assistant message 同时写入一个面板。

停止按钮调用 `AbortController.abort()`。前端将消息状态改为 `aborted`，BFF 在连接断开后取消 gRPC context。

## 10. 错误处理

错误分层：

- 前端输入错误：在提交前提示，不发请求。
- BFF 校验错误：返回普通 JSON error，不进入 SSE。
- Agent 启动失败：BFF 返回 `error` SSE event。
- DeepSeek 中途失败：Agent 发送 `ERROR` chunk，BFF 转为 `error` SSE event。
- 用户主动停止：前端标记 `aborted`，BFF 标记 assistant message 为 `aborted`。

如果 SSE 连接已经开始，BFF 不再改 HTTP status，而是通过 `event: error` 表达失败。

## 11. 合规和输出边界

系统提示必须要求：

- 只提供研究辅助。
- 不输出买入、卖出、加仓、减仓等直接交易指令。
- 回答中说明依据、风险和不确定性。
- 回答末尾包含“非投资建议，仅供研究参考”。

Agent 的 `finalize_answer` 对完整回答做一次兜底检查。如果没有免责声明，则追加固定免责声明。第一阶段不做复杂内容安全分类，但禁止交易指令词的 guardrail 要进入单元测试。

## 12. 验证策略

### Agent

- 测试 `DeepSeekProvider` 能解析 streaming payload 中的 `delta.content`。
- 测试 `[DONE]` 后结束。
- 测试 DeepSeek 错误映射。
- 测试 `question_answer` graph 输出包含免责声明。
- 测试包含直接交易指令的问题不会诱导输出交易指令。

### Backend

- 测试 `POST /api/chat/stream` 要求登录态。
- 测试空问题被拒绝。
- 用 fake Agent stream 测试 BFF 能输出 `metadata`、多个 `delta`、`done`。
- 测试 fake Agent error 被转换成 SSE `error`。
- 测试客户端断开会取消 gRPC context。

### Frontend

- 测试发送问题后创建用户消息和 assistant 占位消息。
- 测试 `delta` 被 append 到 assistant message。
- 测试 `done` 后状态为 `completed`。
- 测试 `error` 后状态为 `error`。
- 测试停止按钮触发 abort。

### 手工验收

本地启动 `fronted`、`backend`、`agent` 后，输入“帮我分析一下 AAPL 最近需要关注什么风险”，页面应在不刷新、不等待完整回答结束的情况下持续显示 DeepSeek 返回的文本片段，最终回答包含免责声明。

## 13. 与后续切片的关系

后续能力按以下顺序叠加，不改变本方案的核心协议：

1. 聊天历史列表和历史消息加载。
2. 将 `page_context.symbol` 连接到真实自选股和股票详情。
3. 将 `research_card_id` 连接到研究卡片上下文。
4. 增加 LangGraph tool 节点，允许 Agent 查询行情、事件和研究卡片。
5. 增加 resume，使用同一套 `metadata`、`delta`、`done`、`error` SSE event。

## 14. 参考

- DeepSeek API `Create Chat Completion`：`https://api-docs.deepseek.com/api/create-chat-completion`
- LangGraph Python streaming：`https://docs.langchain.com/oss/python/langgraph/streaming`
