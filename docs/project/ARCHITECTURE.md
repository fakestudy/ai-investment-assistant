# AI Investment Assistant Architecture

本文档是当前仓库的架构事实入口。其他计划文档可以记录历史决策和学习路线，但当前运行链路与未来职责边界以本文档为准。

---

## 1. 当前运行链路

当前本地开发通过 `make dev-start` 启动：

```text
Browser
  -> Nginx container (:3000)
  -> Next.js web (:3001)
  -> agent_claude FastAPI (:8081)
  -> PostgreSQL (:5432)
```

当前 Agent runtime：

```text
agent_claude
  -> Claude Agent SDK
  -> PostgreSQL SessionStore
  -> agent_runs / agent_run_events / approval_batches / approval_requests
  -> conversations / messages / tool_invocations / message_parts 投影表
```

当前关键点：

- `web` 调用 `/api/*`。
- Nginx 把 `/api/*` 代理到 `agent_claude`。
- `agent_claude` 负责聊天 API、SSE、Claude Agent SDK、session 持久化、run/event/approval 状态和前端消息投影。
- `backend/` Go 服务当前不在 `make dev-start` 链路中。
- `BFF_HTTP_ADDR` 当前复用为 `agent_claude` HTTP 地址；变量名保留是为了兼容脚本。

当前聊天能力已经覆盖前端暴露的运行态接口：

- `activeRun` 来自 `agent_runs`，不是固定空值。
- `/api/chat/stream/resume` 按 `runId + afterEventId` replay `agent_run_events` 并继续订阅 live run。
- `/api/chat/approval/decisions/{batchId}` 写入审批决策，追加 `approval_resolved`，并唤醒等待中的 Claude SDK permission hook。
- `/api/messages/{messageId}` 只允许编辑 user message。
- `/api/chat/streams/{messageId}/cancel` 会取消 live task、持久化 partial assistant message，并关闭 active run。
- `parentMessageId` / `regenerateFromMessageId` 会截断分支、失效旧 Claude SDK session，并用剩余历史构造新 prompt。

---

## 2. 存储边界

当前有两类存储，职责不同：

```text
Claude SDK SessionStore
  = Agent transcript / SDK resume 语义

agent_runs + agent_run_events
  = 前端 run 状态 / SSE replay / activeRun 投影

messages + message_parts + tool_invocations
  = 前端历史消息和工具事件投影
```

这些表不是彼此替代关系：

- `SessionStore` 服务 Claude SDK 多轮上下文，不保证前端可以按事件 ID replay。
- `agent_run_events` 服务前端刷新、断线重连和 SSE cursor，不等于 Agent checkpoint。
- `messages` / `message_parts` / `tool_invocations` 是 UI 历史投影，不应被当成 Agent runtime 的完整执行状态。

服务进程重启后，已落库的 SSE 事件可以 replay；未完成的 in-flight run 不能从半轮 Claude SDK 输出中间继续执行，应标记为失败或通过 regenerate 重新发起。真正 crash-safe 的 Agent resume 需要后续 Python Agent workflow/checkpoint 设计，不是 Go BFF 的职责。

---

## 3. 目标架构

后续目标是引入 Go BFF，但 Go 只做业务逻辑，不做 Agent runtime：

```text
Browser
  -> Nginx
  -> Next.js web
  -> Go business BFF
  -> RPC
  -> Python Agent service
```

数据与状态：

```text
Go business BFF -> PostgreSQL business tables
Python Agent    -> Agent runtime/session/checkpoint storage
```

Go BFF 的职责：

- API gateway / BFF
- 用户、权限、自选股、任务状态
- 投资数据源接入、缓存和清洗
- 报告、证据链、业务审计查询
- 面向前端的稳定 REST/SSE API
- 通过 RPC 调用 Python Agent

Python Agent 的职责：

- LLM / Agent runtime
- 工具执行和工具事件投影
- Agent session / workflow / checkpoint
- 模型输出流式事件
- Agent 执行恢复语义

---

## 4. 明确不做

当前和未来都不把 Go 作为 Agent runtime：

- 不引入 Eino。
- 不在 Go 内实现 ReAct Agent。
- 不让 Go 直接管理 Claude Agent SDK session。
- 不把 `messages` / `tool_invocations` 这类业务投影表当成 Agent runtime checkpoint。

如未来需要复杂 workflow，优先在 Python Agent 侧解决，再通过 RPC 暴露给 Go BFF。

---

## 5. 前端协议边界

当前前端使用项目自定义 JSON SSE：

- `run_created`
- `message_created`
- `reasoning`
- `delta`
- `tool_call`
- `tool_result`
- `approval_required`
- `approval_resolved`
- `title`
- `done`
- `error`

未来 Go BFF 接管 `/api/*` 时，优先保持这个前端事件契约不变。若要迁移到其他协议，必须作为单独协议迁移处理，不要在 Go BFF 接入时顺手改掉。

---

## 6. 迁移顺序

建议迁移顺序：

1. 稳定当前 `web -> agent_claude` 聊天基座。
2. 明确 Go BFF 第一批业务边界，例如用户、自选股、数据源缓存或报告列表。
3. 设计 Go BFF 到 Python Agent 的最小 RPC contract。
4. 让 Go BFF 接管 `/api/*` 的一小段非 Agent 业务接口。
5. 最后再把聊天入口从直连 `agent_claude` 切到 Go BFF 转发 / 编排。

不要先做大而全的 proto 或双端重写。RPC contract 应该由真实业务用例倒逼出来。
