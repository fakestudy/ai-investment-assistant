# Gemini CLI Tool Mapping

skills 使用 Claude Code 的 tool 名称。当你在 skill 中遇到这些名称时，请使用你所在平台的等价工具：

| Skill references | Gemini CLI equivalent |
|-----------------|----------------------|
| `Read`（文件读取） | `read_file` |
| `Write`（文件创建） | `write_file` |
| `Edit`（文件编辑） | `replace` |
| `Bash`（运行命令） | `run_shell_command` |
| `Grep`（搜索文件内容） | `grep_search` |
| `Glob`（按名称搜索文件） | `glob` |
| `TodoWrite`（task tracking） | `write_todos` |
| `Skill` tool（invoke a skill） | `activate_skill` |
| `WebSearch` | `google_web_search` |
| `WebFetch` | `web_fetch` |
| `Task` tool（dispatch subagent） | `@agent-name`（见 [Subagent support](#subagent-support)） |

## Subagent support

Gemini CLI 通过 `@` 语法原生支持 subagent。对任意任务都可以使用内置的 `@generalist` agent —— 它能访问所有工具，并会遵循你提供的 prompt。

当某个 skill 要求派发一个具名 agent type 时，请使用 `@generalist`，并传入该 skill 的 prompt template 填充后的完整 prompt：

| Skill instruction | Gemini CLI equivalent |
|-------------------|----------------------|
| `Task tool (superpowers:implementer)` | `@generalist` + 填好的 `implementer-prompt.md` 模板 |
| `Task tool (superpowers:spec-reviewer)` | `@generalist` + 填好的 `spec-reviewer-prompt.md` 模板 |
| `Task tool (superpowers:code-reviewer)` | `@code-reviewer`（内置 agent）或 `@generalist` + 填好的 review prompt |
| `Task tool (superpowers:code-quality-reviewer)` | `@generalist` + 填好的 `code-quality-reviewer-prompt.md` 模板 |
| `Task tool (general-purpose)` with inline prompt | `@generalist` + 你的内联 prompt |

### Prompt filling

skills 会提供带占位符的 prompt 模板，比如 `{WHAT_WAS_IMPLEMENTED}` 或 `[FULL TEXT of task]`。请填完所有占位符，并把完整 prompt 作为消息发送给 `@generalist`。模板本身已经包含 agent 的角色、review criteria 和预期输出格式 —— `@generalist` 会遵循它。

### Parallel dispatch

Gemini CLI 支持并行派发 subagent。当某个 skill 要求并行派发多个彼此独立的 subagent 任务时，请在同一个 prompt 中一起请求所有这些 `@generalist` 或具名 subagent 任务。存在依赖关系的任务仍需串行，但不要只是为了维持更简单的历史而把独立任务也串行化。

## Additional Gemini CLI tools

这些工具在 Gemini CLI 中可用，但在 Claude Code 中没有等价物：

| Tool | Purpose |
|------|---------|
| `list_directory` | 列出文件和子目录 |
| `save_memory` | 跨会话将事实持久化到 GEMINI.md |
| `ask_user` | 向用户请求结构化输入 |
| `tracker_create_task` | 丰富的任务管理（创建、更新、列出、可视化） |
| `enter_plan_mode` / `exit_plan_mode` | 在修改前切换到只读研究模式 |
