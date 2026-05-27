# Codex Tool Mapping

skills 使用 Claude Code 的 tool 名称。当你在 skill 中遇到这些名称时，请使用你所在平台的等价工具：

| Skill references | Codex equivalent |
|-----------------|------------------|
| `Task` tool（dispatch subagent） | `spawn_agent`（见 [Subagent dispatch requires multi-agent support](#subagent-dispatch-requires-multi-agent-support)） |
| 多个 `Task` 调用（并行） | 多个 `spawn_agent` 调用 |
| Task 返回结果 | `wait_agent` |
| Task 自动完成 | 使用 `close_agent` 释放 slot |
| `TodoWrite`（task tracking） | `update_plan` |
| `Skill` tool（invoke a skill） | skills 原生加载 —— 直接遵循指令 |
| `Read`、`Write`、`Edit`（文件） | 使用你原生的文件工具 |
| `Bash`（运行命令） | 使用你原生的 shell 工具 |

## Subagent dispatch requires multi-agent support

把下面内容加入你的 Codex 配置（`~/.codex/config.toml`）：

```toml
[features]
multi_agent = true
```

这会为 `dispatching-parallel-agents` 和 `subagent-driven-development` 之类的 skills 启用 `spawn_agent`、`wait_agent` 和 `close_agent`。

Legacy note: 在 `rust-v0.115.0` 之前的 Codex 构建中，spawned-agent 的等待接口暴露为 `wait`。当前 Codex 对 spawned agents 使用 `wait_agent`。现在的 `wait` 名称属于 code-mode 的 `exec/wait`，它通过 `cell_id` 恢复一个 yielded exec cell；它不是 spawned-agent 的结果工具。

## Environment Detection

会创建 worktrees 或收尾分支的 skills，在继续之前应使用只读 git 命令检测其环境：

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
BRANCH=$(git branch --show-current)
```

- `GIT_DIR != GIT_COMMON` → 已经处于 linked worktree 中（跳过创建）
- `BRANCH` 为空 → detached HEAD（无法从 sandbox 中执行 branch/push/PR）

关于各个 skill 如何使用这些信号，请参见 `using-git-worktrees` 的 Step 0 和 `finishing-a-development-branch` 的 Step 1。

## Codex App Finishing

当 sandbox 阻止 branch/push 操作时（也就是处于 detached HEAD 且位于外部管理的 worktree 中），agent 会提交所有工作，并告知用户使用 App 的原生控制：

- **“Create branch”** —— 为分支命名，然后通过 App UI 执行 commit/push/PR
- **“Hand off to local”** —— 将工作转移到用户本地 checkout

agent 仍然可以运行测试、stage 文件，并输出建议的 branch 名称、commit message 和 PR description 供用户复制。
