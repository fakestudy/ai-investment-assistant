# Copilot CLI Tool Mapping

skills 使用 Claude Code 的 tool 名称。当你在 skill 中遇到这些名称时，请使用你所在平台的等价工具：

| Skill references | Copilot CLI equivalent |
|-----------------|----------------------|
| `Read`（文件读取） | `view` |
| `Write`（文件创建） | `create` |
| `Edit`（文件编辑） | `edit` |
| `Bash`（运行命令） | `bash` |
| `Grep`（搜索文件内容） | `grep` |
| `Glob`（按名称搜索文件） | `glob` |
| `Skill` tool（invoke a skill） | `skill` |
| `WebFetch` | `web_fetch` |
| `Task` tool（dispatch subagent） | `task`，`agent_type: "general-purpose"` 或 `"explore"` |
| 多个 `Task` 调用（并行） | 多个 `task` 调用 |
| Task 状态/输出 | `read_agent`、`list_agents` |
| `TodoWrite`（task tracking） | `sql` + 内置 `todos` 表 |
| `WebSearch` | 没有等价工具 —— 使用搜索引擎 URL 配合 `web_fetch` |
| `EnterPlanMode` / `ExitPlanMode` | 没有等价工具 —— 留在主会话中 |

## Async shell sessions

Copilot CLI 支持持久化的异步 shell session，这在 Claude Code 中没有直接对应物：

| Tool | Purpose |
|------|---------|
| `bash` with `async: true` | 在后台启动一个长时间运行的命令 |
| `write_bash` | 向运行中的异步 session 发送输入 |
| `read_bash` | 读取异步 session 输出 |
| `stop_bash` | 终止异步 session |
| `list_bash` | 列出所有活跃 shell session |

## Additional Copilot CLI tools

| Tool | Purpose |
|------|---------|
| `store_memory` | 为未来会话持久化代码库事实 |
| `report_intent` | 更新 UI 状态栏中的当前意图 |
| `sql` | 查询会话的 SQLite 数据库（todos、metadata） |
| `fetch_copilot_cli_documentation` | 查询 Copilot CLI 文档 |
| GitHub MCP tools（`github-mcp-server-*`） | 原生 GitHub API 访问（issues、PRs、code search） |
