# Claude Agent SDK New-Agent Compatibility Design

## Goal

新建一个独立的 Python agent 服务，使用 `claude-agent-sdk` 作为 runtime，并对齐当前前端聊天链路契约。

本次设计的核心目标是：

- 新服务对齐当前前端请求入口和字段定义。
- 新服务对齐当前前端依赖的 SSE 事件类型和字段定义。
- 新服务保留核心 chat 相关表语义，尤其是 `conversations`、`messages`，以及普通聊天链路需要的 `tool_invocations`、`message_parts`。
- 新服务不继承旧服务的复杂运行时能力，包括 `approval`、`interrupt resume`、`checkpoint`、`outbox worker`、`run event replay`。
- 新服务通过 `ANTHROPIC_*` 环境变量驱动 Anthropic-compatible provider。
- 新服务通过 `PostgreSQL` 实现官方 `SessionStore`，而不是依赖本地磁盘 session 持久化。

换句话说，这不是“复用现有 `agent/` 项目直接改造”，而是“新建独立服务，对齐现有外部契约”。

## Scope

本次设计仅覆盖新服务中的普通聊天链路能力：

- 继续使用当前 `/chat/stream` 入口。
- 继续接受当前 `ChatStreamRequest` 字段：
  `conversationId`、`message`、`generateTitle`、`parentMessageId`、`regenerateFromMessageId`。
- 继续输出以下事件：
  `message_created`、`reasoning`、`tool_call`、`tool_result`、`delta`、`title`、`done`、`error`。
- agent 会话持久化遵循 `claude-agent-sdk` 官方 session 机制，并使用 `PostgreSQL` 实现 `SessionStore`。
- assistant 消息仍需以 `streaming -> done/error` 的方式落库。
- `tool_invocations` 和 `message_parts` 仍需可用于消息历史接口。
- 会话标题生成仍保留。
- 多轮聊天上下文仍保留，但实现方式允许重写。

## Non-goals

本次替换明确不做以下内容：

- 在第一版中实现 `run_created`、`approval_required`、`approval_resolved` 事件链路。
- 实现 `resume_stream_chat` 的实际恢复能力。
- 实现 `submit_approval_decisions_stream` 的实际业务价值。
- 引入 `agent_runs` 作为普通聊天主状态机。
- 引入 worker claim、lease、outbox publish、checkpoint resume。
- 引入人工审批和超时审批。
- 复制“一个 conversation 同时只能有一个 active run”的旧运行时约束。
- 迁移历史数据。

旧服务可以继续保留，直到新服务功能对齐并切流。

## Current State

当前系统中，旧 `agent/` 服务的聊天链路由以下几部分组成：

- [agent/controller/chat.py](/Users/bytedance/Desktop/agent/ai-investment-assistant/agent/controller/chat.py)
  旧 `/chat/stream` 实际是先创建 `agent_run`，再转为 `stream_run_events()` 的 SSE 输出。
- [agent/schema/chat.py](/Users/bytedance/Desktop/agent/ai-investment-assistant/agent/schema/chat.py)
  前端依赖的聊天事件契约已经固定，新服务必须对齐这些字段。
- [agent/service/agent_factory.py](/Users/bytedance/Desktop/agent/ai-investment-assistant/agent/service/agent_factory.py)
  当前 runtime 基于 `create_agent()` 和 `LangChain/LangGraph`。
- [agent/service/chat.py](/Users/bytedance/Desktop/agent/ai-investment-assistant/agent/service/chat.py)
  旧服务已经具备一条不依赖 `run` 的直接流式事件生成逻辑，可作为新服务事件投影的参考，而不是直接复用实现。
- [agent/worker/run_executor.py](/Users/bytedance/Desktop/agent/ai-investment-assistant/agent/worker/run_executor.py)
  当前 worker 路径承载了 run claim、resume、checkpoint 和数据库投影。

核心问题不是“当前没有聊天接口”，而是旧服务主链路把普通聊天和复杂运行时绑死了。因此新服务应该直接绕开旧运行时架构，而不是在旧项目里继续演化。

## Recommended Approach

推荐做法是：

- 新建一个独立的 agent 服务目录和 FastAPI 应用。
- 新服务对齐前端面向的 schema 和 API path。
- 新服务把普通聊天主链路设计为“直接 SDK 流驱动 + 同步持久化”。
- `claude-agent-sdk` 成为新服务普通聊天的唯一 runtime。
- agent transcript 的持久化与恢复遵循官方 session / `SessionStore` 机制，且 `SessionStore` 后端使用 `PostgreSQL`。

即：~

1. 新服务提供兼容的 `/chat/stream`。
2. 新服务不创建 `agent_run`，也不依赖 `agent_run_event`。
3. 新服务使用 `claude-agent-sdk` 产生事件。
4. 新服务负责把 SDK 消息投影成当前前端期待的 `ChatStreamResponse`。
5. 新服务使用官方 session 持久化 agent transcript，并按兼容的数据模型投影 assistant、tool invocations、message parts。

这是当前约束下成本最低的路径，因为它保留了：

- 前端接口契约
- 前端事件字段
- 核心 chat 数据模型语义

同时避免把以下旧债务带进新服务：

- `agent_run`
- `approval`
- `resume`
- `outbox`
- `worker`

## Proposed Architecture

新架构是独立服务，不复用旧服务外壳。

### 1. Config Layer

职责：

- 启动时加载 `.env`。
- 使用 `ANTHROPIC_*` 读取 provider 配置。
- 为 `claude-agent-sdk` 提供统一配置来源。

主要配置：

- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_AUTH_TOKEN`
- `ANTHROPIC_MODEL`

约束：

- `DEEPSEEK_*`、`OPENAI_*` 不再作为 runtime 主配置来源。
- 若接入 DeepSeek，也通过 Anthropic-compatible 方式注入 `ANTHROPIC_*`。

### 2. Claude Runtime Adapter

职责：

- 封装 `claude-agent-sdk` 的 `ClaudeAgentOptions` 和客户端调用。
- 对外暴露统一的“给定 prompt，返回 SDK 消息流”的接口。
- 把 SDK 自身不稳定或版本敏感的字段隔离在 adapter 内。

建议配置：

- `allowed_tools` 固定为当前允许的内置工具集合。
- `include_partial_messages=True`
- `setting_sources=[]`
- `system_prompt` 保留最小且稳定的版本。
- `permission_mode` 使用一个固定无审批模式。

这里不再做多 runtime 工厂。新服务普通聊天只走 `claude-agent-sdk`。

### 3. Session Persistence Layer

职责：

- 直接采用 `claude-agent-sdk` 官方 session 持久化能力。
- 让 agent 的真实会话状态由 SDK session transcript 驱动。
- 使用 `PostgreSQL` 实现官方 `SessionStore` adapter。

官方能力要求：

- 每轮响应中可读取 `session_id`，后续通过 `resume=session_id` 继续会话。
- 官方允许通过 `SessionStore.append/load` 把 transcript 持久化到外部存储。
- 本项目选择 `PostgreSQL` 作为唯一的 session 外部存储实现。

设计约束：

- 新服务不自定义一套脱离官方接口的 agent runtime transcript 格式。
- 新服务不使用 `messages` 历史拼接来替代官方 session continuation。
- agent runtime 的 source of truth 是 `PostgreSQL` 中的官方 session transcript。
- `messages`、`tool_invocations`、`message_parts` 仍然只是前端兼容投影。

### 4. Stream Projection Layer

职责：

- 读取 SDK 消息。
- 映射成当前前端既有事件：
  `message_created`、`reasoning`、`tool_call`、`tool_result`、`delta`、`title`、`done`、`error`。
- 在投影过程中同步触发数据库持久化。

这一层是最关键的兼容层。

它的要求不是“让前端理解 SDK 消息”，而是“把 SDK 消息翻译成当前前端完全不需要改动的既有契约”。

### 5. Projection Persistence Layer

职责：

- 维护与旧服务兼容的核心模型。
- 将新的流式执行过程写入新服务自己的核心表。

保留的核心表：

- `conversations`
- `messages`
- `tool_invocations`
- `message_parts`

新增的 runtime 持久化表：

- `agent_sessions`
- `agent_session_entries`

保留这些表的原因：

- 前端历史消息接口已经依赖 `messages`。
- 当前消息历史结构已经支持 `toolInvocations` 和 `timelineParts`。
- 普通聊天保留 `reasoning/tool` 历史对 UI 和上下文构建都有价值。
- 这些表在新服务中是读模型和前端投影，不是 agent transcript 的主存储。

新增 runtime 表的原因：

- 官方 session 需要一个可恢复的 transcript 存储。
- `PostgreSQL` 存储可以满足多实例部署、可治理保留策略和后续对齐官方 `SessionStore` 接口。

新服务第一版不创建以下表：

- `agent_runs`
- `agent_run_events`
- `approval_batches`
- 其他围绕 `run/approval/outbox` 的运行时表

### 6. HTTP Layer

职责：

- 提供与旧服务兼容的 `/chat/stream` 路径。
- 保持请求和响应 schema 不变。
- 直接调用新聊天服务，不经过 `create_chat_run()` + `stream_run_events()`。

## API Design

### `POST /chat/stream`

保持请求体不变：

- `conversationId`
- `message`
- `generateTitle`
- `parentMessageId`
- `regenerateFromMessageId`

实现变更：

- 旧服务实现：
  创建 `agent_run`，提交事务，然后通过 `stream_run_events()` 输出持久化事件。
- 新服务实现：
  直接返回一个 `StreamingResponse`，内部消费 `claude-agent-sdk` 流，并实时产出兼容事件。

请求处理流程应变为：

1. 校验 conversation。
2. 持久化 user message。
3. 创建 assistant message，状态为 `streaming`。
4. 立即发送 `message_created`。
5. 查找该 conversation 绑定的 SDK `session_id`。
6. 通过 `PostgreSQL` `SessionStore` 读取该 session transcript。
7. 若存在 `session_id`，通过官方 `resume=session_id` 继续会话；否则启动新 session。
8. 调用 `claude-agent-sdk`。
9. 通过 `PostgreSQL` `SessionStore.append()` 持续写入 transcript。
10. 从本轮结果中读取 `session_id` 并更新 conversation 到 session 的映射。
11. 把 SDK 流翻译为既有事件并持续输出。
12. 流结束时更新 assistant message 为 `done`，必要时更新标题。
13. 若异常，更新 assistant message 为 `error` 并输出 `error`。

### `GET conversation messages`

保持当前历史消息接口结构不变。

要求：

- 返回 `messages`
- assistant message 中继续带 `toolInvocations`
- assistant message 中继续带 `timelineParts`
- `activeRun` 可以返回 `null`

因为已接受先废掉复杂运行时，所以 `activeRun` 在新服务普通聊天下不应再成为前端强依赖。

### `resume` / `approval` 相关接口

处理原则：

- 新服务可以暂时不实现这些接口。
- 如果网关或前端路由层要求它们存在，可返回明确的未实现或降级语义。
- 普通聊天路径不应再依赖这些接口。

## Event Contract Compatibility

普通聊天需要继续完整输出以下事件。

### `message_created`

保持当前 payload 结构：

- `type="message_created"`
- `message.id`
- `message.conversationId`
- `message.role`
- `message.content`
- `message.status`
- `message.createdAt`

### `reasoning`

保持当前 payload 结构：

- `type="reasoning"`
- `messageId`
- `text`

### `tool_call`

保持当前 payload 结构：

- `type="tool_call"`
- `messageId`
- `invocation`

其中 `invocation` 仍按当前 `ToolInvocation` schema 返回。

### `tool_result`

保持当前 payload 结构：

- `type="tool_result"`
- `messageId`
- `invocation`

### `delta`

保持当前 payload 结构：

- `type="delta"`
- `messageId`
- `text`

### `title`

保持当前 payload 结构：

- `type="title"`
- `conversationId`
- `title`

### `done`

保持当前 payload 结构：

- `type="done"`
- `messageId`

### `error`

保持当前 payload 结构：

- `type="error"`
- `messageId`
- `message`

### 不再作为普通聊天输出的事件

以下事件类型保留在 schema 中，但普通聊天不再产生：

- `run_created`
- `approval_required`
- `approval_resolved`

这样可以保持前端类型定义不破坏，同时让普通聊天链路回到最小必要集合。

## Runtime-to-Event Mapping

`claude-agent-sdk` 到当前事件协议的映射规则如下。

- assistant 文本增量映射为 `delta`
- thinking 增量映射为 `reasoning`
- tool use 块映射为 `tool_call`
- tool result 块映射为 `tool_result`
- 最终 assistant 完成映射为 `done`
- 异常映射为 `error`

需要特别注意两点：

1. `message_created` 不是 SDK 自带事件，而是服务端在 assistant message 落库后主动发送。
2. `title` 不应阻塞主回答链路，失败时直接回退或跳过。

## Persistence Design

新服务持久化分为两层，且主从关系必须明确。

### Layer 1: SDK Session Persistence

这是 agent runtime 的主持久化层，遵循官方实现。

规则：

- 新会话由 SDK 创建 session。
- 每轮请求都从 SDK 消息中读取 `session_id`。
- 后续同一 conversation 的请求优先用 `resume=session_id` 继续。
- session transcript 通过 `PostgreSQL` 版 `SessionStore` 持久化。
- 新服务不依赖本地磁盘保存 session。

结论：

- agent 的真实上下文连续性依赖 SDK session/resume。
- agent transcript 的主存储是 `PostgreSQL` 版 `SessionStore`。
- 新服务不再把 `messages` 历史拼接当作标准会话延续机制。

### `agent_sessions`

建议最小字段：

- `id`
- `conversation_id`
- `sdk_session_id`
- `created_at`
- `updated_at`

用途：

- 保存业务 conversation 与 SDK session 的映射。
- 作为 resume 入口的快速索引。

### `agent_session_entries`

建议最小字段：

- `id`
- `sdk_session_id`
- `sequence_no`
- `entry_payload`
- `created_at`

用途：

- 实现官方 `SessionStore.append/load` 所需的 transcript 存储。
- 保证同一 `sdk_session_id` 下 transcript 可按顺序恢复。

### Layer 2: Frontend Projection Persistence

这一层用于兼容现有前端和历史消息接口，不承担 runtime 真正状态恢复。

### `messages`

保留：

- user message 在流开始前落库
- assistant message 在流开始前以 `streaming` 落库
- assistant 完成后更新为 `done`
- assistant 异常时更新为 `error`

### `tool_invocations`

继续保留。

因为前端事件和历史消息都依赖它的形态：

- `tool_call` 事件需要 `invocation`
- `tool_result` 事件需要更新后的 `invocation`
- 历史消息需要 `toolInvocations`

### `message_parts`

继续保留。

因为当前 `timelineParts` 已经是前端历史消息的一部分，且 reasoning/tool timeline 对上下文重建有帮助。

### conversation to `session_id` mapping

新服务需要一层非常薄的映射，把业务 conversation 和 SDK session 关联起来。

要求：

- 一个 conversation 在普通聊天主分支上只维护一个当前 `session_id`。
- 第一轮完成后保存 `session_id`。
- 后续轮次用该 `session_id` 做官方 resume。
- 若未来要支持分支会话，再单独设计多 session 模型，不在第一版提前抽象。

该映射建议直接落在 `agent_sessions` 表中，而不是塞进 `conversations` 现有字段。

### `agent_runs` and Related Tables

新服务第一版不实现，也不依赖。

## Conversation Context

多轮上下文要保留，但实现可以重做。

建议做法：

- 以 `PostgreSQL` 版 `SessionStore` + SDK `resume` 作为主上下文机制。
- `messages` 历史只用于前端展示、标题生成兜底和必要的业务补偿。
- 只有在 session 缺失或损坏时，才考虑基于历史消息做受控降级。

第一版不做：

- 断点恢复
- 分支对话树
- 基于 `parentMessageId` / `regenerateFromMessageId` 的真正重生成功能

这两个字段在请求体中继续保留，但在第一版中可以显式忽略或只做最小兼容处理。

## Title Generation

标题生成功能继续保留，因为前端已依赖 `title` 事件。

建议策略：

- 当 `generateTitle=true` 时异步生成标题
- 标题生成失败时不影响主对话完成
- 标题更新成功后发 `title` 事件，并写回 `conversations.title`

这部分可以继续使用当前思路，但底层模型应切到新的 runtime 配置语义。

## Error Handling

新服务必须保证错误语义比旧服务更简单、更稳定。

要求：

- 缺少关键 `ANTHROPIC_*` 配置时，服务启动失败。
- SDK 初始化失败时，请求返回明确异常。
- 流式执行中出错时，assistant message 更新为 `error`。
- 若存在 partial content 和 reasoning，应尽量保留。
- 不允许因为标题生成失败而让整轮对话失败。
- 不允许普通聊天路径出现“等待 approval”或“resume required”的状态。
- `PostgreSQL` `SessionStore` 读写失败时，应返回明确错误或进入受控降级，不能静默切成另一套自定义 runtime 恢复逻辑。

## Migration Strategy

实施分三步进行。

### Step 1

新建服务骨架，引入 `claude-agent-sdk` runtime adapter，并完成 `.env` / `ANTHROPIC_*` 配置切换。

### Step 2

实现 `PostgreSQL` 版 `SessionStore`，并建立 conversation 到 `session_id` 的映射。

### Step 3

补齐历史消息投影、事件兼容和 session 恢复链路，验证前端无改动可用。

完成这三步后，新服务已经具备切流条件。旧服务中的 `approval/resume/run` 代码继续保留，直到后续统一清理。

## Testing

至少要覆盖以下测试。

### Runtime Tests

- `ANTHROPIC_*` 配置被正确加载。
- `ClaudeAgentOptions` 使用预期工具白名单和权限模式。
- 缺失关键配置时启动失败。
- `session_id` 能从 SDK 结果中提取并持久化。
- 后续请求能通过 `resume=session_id` 延续会话。
- `PostgreSQL` 版 `SessionStore` 可正确 `append/load`。

### Event Projection Tests

- assistant 创建后先输出 `message_created`
- SDK 文本增量映射为 `delta`
- SDK thinking 映射为 `reasoning`
- 工具调用映射为 `tool_call`
- 工具结果映射为 `tool_result`
- 正常完成输出 `done`
- 异常输出 `error`
- 标题生成成功时输出 `title`

### Persistence Tests

- user message 会落库
- assistant `streaming` message 会先落库
- 最终 assistant 更新为 `done`
- 异常 assistant 更新为 `error`
- `tool_invocations` 可正确创建和更新
- `message_parts` 保持正确顺序
- conversation 到 `session_id` 的映射正确
- `agent_session_entries` 可按顺序恢复 transcript

### Compatibility Tests

- `/chat/stream` 请求字段兼容现有前端
- SSE 事件字段兼容 `schema/chat.py`
- 历史消息接口依然返回 `toolInvocations` 和 `timelineParts`
- `activeRun` 可为空但前端链路不出错

## Open Decisions Already Resolved

以下约束已确认，不再在 implementation 阶段反复拉扯：

- 目标是新建独立服务，对齐后替换旧服务，而不是直接在旧 `agent` 项目内改造。
- 前端不改路径、不改字段定义。
- 普通聊天要继续保留 `message_created / reasoning / tool_call / tool_result / delta / title / done / error`。
- 核心 chat 表保留，但历史数据不需要迁移。
- `approval / interrupt resume / run event stream` 先废掉。
- provider 配置统一改为 `ANTHROPIC_*` 语义。
- agent 持久化遵循官方 session / `SessionStore` 机制，并用 `PostgreSQL` 实现。

## Success Criteria

替换完成后，满足以下条件即可判定成功：

- 现有前端无需改接口协议即可继续聊天。
- 新服务的 `/chat/stream` 不依赖 `agent_run` 主链路。
- 普通聊天事件与字段完全兼容当前 schema。
- 新服务通过 `PostgreSQL` 版官方 session 机制完成会话延续。
- 新服务的 `conversations`、`messages`、`tool_invocations`、`message_parts` 语义与旧服务兼容。
- 新服务普通聊天不进入 `approval/resume/checkpoint/outbox/worker` 状态机。
- 新服务底层 runtime 使用 `claude-agent-sdk`。
