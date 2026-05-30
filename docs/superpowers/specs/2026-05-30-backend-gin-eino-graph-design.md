# Backend Gin 与 Eino Graph 改造设计

## 目标

改造 backend，使 HTTP 层明确采用 Gin，Agent 层真正使用 Eino 作为编排框架。第一版实现必须保持现有聊天 API 协议稳定，同时为后续类似 LangGraph 的图配置能力预留运行时边界。

## 当前状态

- `backend/internal/api` 已经使用 Gin 处理路由和 JSON。
- `backend/internal/agent` 暴露了 `NewEinoAgent`，但当前只是包装手写的 DeepSeek/OpenAI-compatible streaming 循环，并没有真正使用 Eino。
- `backend/internal/chat` 依赖一个很小的 `Agent` 接口，并把 agent 事件转换成当前 SSE 协议。
- 本地复制过来的 `.env` 继续被 git ignore。backend 配置必须沿用现有变量名，尤其是 `BFF_HTTP_ADDR` 和 `DEEPSEEK_*`。

## 非目标

- 不修改前端依赖的 REST 或 SSE 协议。
- 不引入 `OPENAI_*` 配置别名。
- 本轮不实现完整 YAML/JSON graph DSL。
- 本轮不新增鉴权、RAG、部署能力或投资领域工作流。

## 推荐方案

HTTP 层使用 Gin，Agent runtime 使用 Eino 官方推荐的 Go builder 风格，并新增内部 `GraphSpec` 类型，作为未来支持类似 LangGraph 声明式配置的兼容层。

这是当前最短路径。Eino 官方文档的主路径是代码式编排，包括 ADK、`compose.NewGraph` 和组件 builder。后续如果需要声明式配置，可以先把 YAML/JSON 解析成同一个内部 `GraphSpec`，再通过同一套 builder 编译成 Eino runtime。

## 备选方案

### 只接入单个 Eino ChatModelAgent

用一个 Eino ChatModelAgent 和 tools 替换当前 DeepSeek 手写循环。

- 优点：实现最快。
- 缺点：对未来可配置 graph 工作流的边界较弱，后续大概率还要再拆一次。

### 先实现外部 YAML Graph

先定义类似 LangGraph 的 YAML/JSON schema，再映射到 Eino。

- 优点：一开始看起来最接近 LangGraph。
- 缺点：在真实工作流不足时过早固化 schema，并且偏离 Eino 官方代码优先的实践路径。

## 配置

backend 使用现有环境变量名：

- `BFF_HTTP_ADDR`：Gin server 监听地址，例如 `:8081`。
- `DATABASE_URL`：PostgreSQL 连接串。
- `DEEPSEEK_API_KEY`：DeepSeek API key。
- `DEEPSEEK_BASE_URL`：OpenAI-compatible DeepSeek base URL，默认 `https://api.deepseek.com`。
- `DEEPSEEK_MODEL`：模型名称，默认与本地配置保持一致。
- `DEEPSEEK_TIMEOUT_SECONDS`：模型 HTTP 调用超时。

`config.Load()` 应把 `BFF_HTTP_ADDR` 作为完整 server address 处理，不能再额外拼接冒号。模型超时应来自 `DEEPSEEK_TIMEOUT_SECONDS`；旧的 `HTTP_CLIENT_TIMEOUT_SECONDS` 应移除，除非明确需要作为向后兼容 fallback。

## 架构

### HTTP 层

`backend/internal/api` 继续作为唯一 HTTP adapter。它负责 Gin 路由注册、本地 CORS、请求校验、HTTP 错误映射和 SSE 写出。

对外 API 保持不变：

- `GET /api/health`
- `GET /api/conversations`
- `POST /api/conversations`
- `PATCH /api/conversations/:conversationId`
- `DELETE /api/conversations/:conversationId`
- `GET /api/conversations/:conversationId/messages`
- `PATCH /api/messages/:messageId`
- `POST /api/chat/stream`

### Chat 层

`backend/internal/chat` 继续作为会话持久化和 SSE 事件顺序的编排边界。它应继续依赖一个小的 agent interface，而不是直接 import Eino。

需要保持当前不变式：

- 持久化用户消息。
- 持久化 `streaming` 状态的 assistant 消息。
- 发送 `message_created`。
- 把 agent 事件流式转换成 `reasoning`、`delta`、`tool_call`、`tool_result`。
- 持久化最终 assistant content 和 reasoning。
- 按需发送 `title`。
- 发送 `done` 或 `error`。

### Agent 层

`backend/internal/agent` 改造成真正的 Eino runtime adapter。它应负责：

- 使用 DeepSeek 的 OpenAI-compatible API 创建 Eino OpenAI ChatModel。
- 绑定由现有 backend tools 转换得到的 Eino tools。
- 通过 Eino Go builder 或 ADK 构建第一版 runtime。
- 把 Eino stream message 和 tool event 转换成现有 `agent.Event` contract。
- 保留 `DEEPSEEK_API_KEY` 缺失时的确定性 fallback，保证本地测试和前端流程仍可运行。

导出的构造函数保持不变：

```go
func NewEinoAgent(cfg config.Config, registry tools.Registry) Agent
```

### Graph Runtime 边界

在 `backend/internal/agent` 下新增小的内部 graph package 或子模块，定义：

```go
type GraphSpec struct {
    Name       string
    Entrypoint string
    Nodes      []NodeSpec
    Edges      []EdgeSpec
    Model      ModelSpec
    Tools      []ToolSpec
}
```

第一版可以在 Go 代码里构建一个默认 graph。关键边界是：Eino runtime 由 `GraphSpec` 创建，而不是在请求处理逻辑里硬编码。

未来支持 YAML/JSON 时，只需要：

- 把配置文件解析成 `GraphSpec`。
- 校验 node name、tool name 和 edge。
- 通过同一套 Eino builder 编译 `GraphSpec`。

### Tool 层

现有 tools 继续作为业务行为来源：

- `web_search`
- `fetch_url`

它们应被包装成 Eino tools，同时保留：

- 现有输入字段名。
- 尽量保持现有输出结构。
- 现有私网 fetch 防护。
- 外部搜索未配置时的确定性提示。

## 数据流

1. Gin 接收 `POST /api/chat/stream`。
2. `chat.Service` 校验请求并持久化会话状态。
3. `chat.Service` 使用归一化后的消息历史调用 `agent.Agent` 接口。
4. Eino runtime 流式输出模型内容，并在模型请求时调用工具。
5. `agent` adapter 把 Eino 输出转换成当前 `agent.Event`。
6. `chat.Service` 持久化内容和 tool invocation，并写出当前 SSE event。
7. Gin SSE writer 把每个事件 flush 到前端。

## 错误处理

- 无效 JSON 和参数校验失败返回 `400`，响应体为 `{"message": "..."}`。
- conversation 或 message 不存在时返回 `404`。
- 未预期 backend 错误返回 `500`，不泄漏内部细节。
- Eino/model 错误转换成 stream `error` event，并把 assistant message 标记为 `error`。
- 请求取消时，用已收集的部分内容 finalize assistant message，然后退出，不做重试。
- `DEEPSEEK_API_KEY` 缺失时使用确定性 fallback，而不是启动失败。

## 测试

新增或更新以下聚焦测试：

- `config.Load()` 正确读取 `BFF_HTTP_ADDR` 和 `DEEPSEEK_TIMEOUT_SECONDS`。
- Gin router 的 health、参数校验和 stream handler 兼容性。
- `DEEPSEEK_API_KEY` 为空时 Eino agent 的 fallback 行为。
- `web_search` 和 `fetch_url` 的 Eino tool wrapper 行为。
- agent 发出 delta、reasoning、tool call、tool result 时，chat service 事件顺序保持不变。

自动化测试不应依赖真实 DeepSeek 外部调用。

## 验证

在 `backend/` 目录运行：

```bash
go test ./...
go build ./cmd/server
```

本地依赖就绪后做手动 smoke test：

```bash
go run ./cmd/server
curl http://localhost:8081/api/health
```

SSE smoke test 应返回 `message_created`、`delta` 或 fallback 内容、可选 tool events、可选 `title` 和 `done`。

## 已定决策

- 第一版 graph 是一个默认 chat-agent graph。
- 声明式 YAML/JSON 加载有意推迟，等出现第二个工作流、确实需要外部配置时再做。
- Eino API 精确版本在实现阶段根据当前 `go get` 解析结果固定；只有编译错误要求时才调整。
