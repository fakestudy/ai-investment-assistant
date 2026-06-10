# AI 聊天助手方案归档（PLAN_CHAT.md）

> **状态：已归档，不再作为当前执行计划。**
>
> 这份文件原本描述“Go 单语言 + Eino + REST/SSE”的聊天助手路线。2026-06-09 已确认该路线不再继续：项目不再引入 Eino，Go 服务后续只做业务逻辑和 BFF，不做 Agent runtime。

---

## 当前执行方案

当前聊天基座由 `agent_claude` 承担：

```text
Browser -> Nginx(:3000) -> web(:3001) -> agent_claude(:8081) -> PostgreSQL
                                               |
                                               v
                                        Claude Agent SDK
```

- `agent_claude` 负责聊天 HTTP API、SSE、Claude Agent SDK runtime、SDK session 持久化、消息投影。
- `web` 保持 `/api/*` 调用路径，经 Nginx 代理到当前 Agent API。
- `backend/` 下的 Go 服务暂不参与当前启动链路。

当前事实以 [`ARCHITECTURE.md`](./ARCHITECTURE.md) 为准。

## 当前能力状态

已完成：

- 基础聊天：创建会话、发送消息、SSE 输出、reasoning/text/tool/title/done/error 投影。
- 工具权限收敛：默认工具 allowlist 不包含 `Task` / `Write` / `Edit` / `Bash` 等写操作；需要人工审批的工具通过 `AGENT_CLAUDE_APPROVAL_TOOLS` 从 allowlist 移出并进入 Claude SDK `can_use_tool` gate。
- 前端功能对齐：`activeRun`、stream resume、approval decision、cancel、edit user message、parent continuation、regenerate 都有 `agent_claude` 后端实现。
- 错误边界：run manager 对未预期异常写安全错误文案，服务端日志保留堆栈。
- 配置校验：构建 Claude runtime options 前校验 `ANTHROPIC_AUTH_TOKEN` 和 `ANTHROPIC_MODEL`。

暂不做：

- Go BFF/RPC：等第一个真实业务 API 需要 Go 承接时再设计。
- Eino：不再引入。
- crash-safe 的半轮 Agent 继续执行：当前只能 replay 已持久化 SSE 事件；未完成 run 的持久化恢复属于后续 Python Agent workflow/checkpoint 设计。

## 未来 Go BFF 方向

Go 服务后续只做确定性业务逻辑：

- API gateway / BFF
- 用户、权限、自选股、任务状态
- 投资数据源接入和缓存
- 报告、证据、业务审计查询
- 通过 RPC 调用 Python Agent

Go 不负责：

- Eino
- ReAct Agent runtime
- Claude Agent SDK runtime
- 模型调用编排
- Agent session / workflow 状态

## 被废弃的旧决策

以下旧结论不再执行：

| 旧决策 | 当前处理 |
| --- | --- |
| Go 单语言实现聊天助手 | 废弃，当前用 `agent_claude` |
| `cloudwego/eino` 作为 Agent 框架 | 废弃，不再引入 Eino |
| Go 输出 Agent streaming/tool events | 废弃，当前由 Python Agent 投影 SSE |
| 删除 Python / gRPC / proto 工具链 | 废弃，未来 Go BFF 仍会通过 RPC 调 Python Agent |
| 所有 API 一律走 Go | 当前不成立；未来 Go BFF 接管后再恢复 |

保留本文件只为了说明方案演进，避免后续误把旧 Go+Eino 计划当成当前目标。
