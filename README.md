# AI Investment Assistant

一个端到端的 AI 投资研究助手项目：通过对话式界面驱动 LLM Agent，对美股 / 港股标的进行深度分析、监控自选股动态。

当前实现阶段先跑通聊天与 Agent 基座：`web` 通过 Nginx 直接访问 `agent_claude`。`backend/` 下的 Go 服务暂不参与本地启动链路，仅作为后续业务 BFF 保留；未来 Go 只承载业务逻辑、数据源、权限、任务编排等确定性能力，并通过 RPC 调用 Python Agent。

技术栈：

- **前端**：Next.js 16 + React 19 + Tailwind v4 + Zustand + shadcn/ui
- **当前 Agent API**：`agent_claude`，FastAPI + SQLAlchemy + Alembic + PostgreSQL + Claude Agent SDK
- **未来业务 BFF**：Go 1.25+，Gin + GORM + PostgreSQL，通过 RPC 调 Python Agent；不承载 Eino / Agent runtime
- **数据库**：PostgreSQL 16
- **基础设施**：Docker / Docker Compose，`mise` 管理多语言工具链

当前架构见 [docs/project/ARCHITECTURE.md](docs/project/ARCHITECTURE.md)，长期目标见 [docs/project/PLAN.md](docs/project/PLAN.md)。

## 前置依赖

> **平台说明**：本项目的自动化脚本（`Makefile` / `scripts/*.sh`）均基于 bash，并依赖 `lsof`、`nohup`、POSIX 进程组与信号等 Unix 语义；`skills/` 目录通过软链共享。原生 Windows (`cmd` / `PowerShell`) 无法直接运行。**Windows 用户请在 WSL2 (Ubuntu 22.04+) 内执行所有命令**，并使用 Docker Desktop 的 WSL2 后端。

下列工具必须由你自行在宿主机安装（脚本只会检测、不会自动安装）：

| 类别 | 工具 | 版本要求 | 说明 |
| --- | --- | --- | --- |
| 系统工具 | git / make / bash | - | macOS / Linux 默认带 |
| 容器 | Docker Desktop | 任意近版 | 需要 `docker compose` v2 |
| 工具链管理 | [mise](https://mise.jdx.dev/) | 任意近版 | 用于锁定 Node / Go / buf 版本 |
| 包管理器 | pnpm | 10.32.1 | 前端依赖管理 |

工具链版本由 [mise.toml](mise.toml) 锁定：

- Node 22.22.2
- Go 1.26.2（脚本要求 ≥ 1.25）
- buf 1.69.0

安装好 `mise` 后，在仓库根目录执行 `mise install` 即可一次性同步上述版本。`pnpm` 需通过 `corepack` 或 `npm i -g pnpm@10.32.1` 单独安装。

## 项目启动

### 1. 准备环境变量

```bash
cp .env.example .env
```

按需填入下列关键变量（其他保留默认即可）：

- `ANTHROPIC_BASE_URL`：Anthropic-compatible API base URL，可留空使用默认 provider
- `ANTHROPIC_AUTH_TOKEN`：Claude Agent SDK 使用的鉴权 token
- `ANTHROPIC_MODEL`：Claude Agent SDK 使用的模型名
- `AGENT_CLAUDE_APPROVAL_TOOLS`：需要进入人工审批 gate 的 Claude 工具名，逗号分隔；默认空值表示基础审批表和接口可用，但不暂停任何默认只读工具
- `BFF_HTTP_ADDR`：当前复用为 `agent_claude` FastAPI 监听地址，例如 `:8081`；变量名保留是为了兼容现有脚本，未来 Go BFF 接管后再恢复其字面含义
- `DATABASE_URL`：默认指向 docker-compose 内的 postgres
- `JWT_SECRET`、`INITIAL_USER_*`：本地登录鉴权使用

完整变量表见 [.env.example](.env.example)。

### 2. 检测开发环境

```bash
make check-dev
```

该命令会调用 [scripts/check-dev.sh](scripts/check-dev.sh)，检查系统工具、工具链版本、`.env` 完整性以及 3000 / 3001 / 8081 / 5432 端口占用情况。出现 `✗` 时请先修复再继续。

### 3. 启动 / 停止本地开发环境

统一通过 Makefile 提供的命令操作，不需要手动逐个起前后端。

```bash
make dev-start   # 启动本地开发环境 (postgres + nginx + pgweb + agent_claude api + web)
make dev-stop    # 停止本地开发环境
```

底层分别由 [scripts/dev-start.sh](scripts/dev-start.sh) 与 [scripts/dev-stop.sh](scripts/dev-stop.sh) 实现。

启动后默认端口：

- Nginx 统一入口：3000 — <http://localhost:3000>
- 前端 Web：3001 — <http://localhost:3001>
- 当前 Agent API：8081 — `agent_claude` FastAPI
- pgweb：8082 — <http://localhost:8082>
- Postgres：5432

## 常用命令

```bash
make help          # 查看 Makefile 提供的命令
make check-dev     # 开发环境体检
make dev-start     # 启动本地开发环境
make dev-stop      # 停止本地开发环境
mise install       # 同步 mise.toml 锁定的工具链版本
mise run doctor    # 打印当前 node / pnpm / go / python / buf 版本
```

## 验证命令

```bash
make test-dev-config

cd agent_claude
mise exec -- uv run python -m unittest discover -s tests -p 'test_*.py' -v

cd ../web
pnpm dlx tsx --test features/chat/api.test.ts features/chat/store.test.ts features/chat/chat-event-reducer.test.ts
pnpm lint
```

`pnpm lint` 当前会报告若干既有 `<img>` performance warnings；没有 error 时命令返回成功。

## 协作规范

- **请勿手动提交代码**：所有 `git commit` / `git push` 操作交由 agent 完成。需要提交时直接告诉 agent「提交代码」即可，避免提交信息风格不一致或漏掉规范化校验。

## 目录概览

- [agent_claude/](agent_claude) — 当前 Agent API 服务，入口 `main.py`
- [backend/](backend) — 未来 Go 业务 BFF，当前不在 `make dev-start` 默认链路中
- [web/](web) — Next.js 前端
- [docs/](docs) — 项目规划与设计文档
- [scripts/](scripts) — 运维 / 检测脚本
- [skills/](skills) — Code agent 共享 skills（详见 [AGENTS.md](AGENTS.md)）
