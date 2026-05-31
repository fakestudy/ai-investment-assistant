# AI Investment Assistant

一个端到端的 AI 投资研究助手项目：通过对话式界面驱动 LLM Agent，对美股 / 港股标的进行深度分析、监控自选股动态。当前阶段聚焦于跑通完整链路（前端 ↔ BFF ↔ Agent ↔ 数据源）。

技术栈：

- **前端**：Next.js 16 + React 19 + Tailwind v4 + Zustand + shadcn/ui
- **后端 BFF**：Go 1.25+，Gin 路由，GORM + PostgreSQL，SSE 流式输出
- **Agent**：基于 Eino 编排，通过 DeepSeek OpenAI-compatible ChatModel 调用 LLM
- **数据库**：PostgreSQL 16
- **基础设施**：Docker / Docker Compose，`mise` 管理多语言工具链

详细架构与决策见 [docs/project/PLAN.md](file:///Users/bytedance/Desktop/ai-investment-assistant/docs/project/PLAN.md)。

## 前置依赖

> **平台说明**：本项目的自动化脚本（`Makefile` / `scripts/*.sh`）均基于 bash，并依赖 `lsof`、`nohup`、POSIX 进程组与信号等 Unix 语义；`skills/` 目录通过软链共享。原生 Windows (`cmd` / `PowerShell`) 无法直接运行。**Windows 用户请在 WSL2 (Ubuntu 22.04+) 内执行所有命令**，并使用 Docker Desktop 的 WSL2 后端。

下列工具必须由你自行在宿主机安装（脚本只会检测、不会自动安装）：

| 类别 | 工具 | 版本要求 | 说明 |
| --- | --- | --- | --- |
| 系统工具 | git / make / bash | - | macOS / Linux 默认带 |
| 容器 | Docker Desktop | 任意近版 | 需要 `docker compose` v2 |
| 工具链管理 | [mise](https://mise.jdx.dev/) | 任意近版 | 用于锁定 Node / Go / buf 版本 |
| 包管理器 | pnpm | 10.32.1 | 前端依赖管理 |

工具链版本由 [mise.toml](file:///Users/bytedance/Desktop/ai-investment-assistant/mise.toml) 锁定：

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

- `BFF_HTTP_ADDR`：backend Gin HTTP 监听地址，例如 `:8081`
- `DEEPSEEK_API_KEY`：DeepSeek API key；配置后 Agent 通过 Eino OpenAI-compatible ChatModel 调用 DeepSeek，未配置时使用本地 fallback
- `DEEPSEEK_BASE_URL`：DeepSeek OpenAI-compatible base URL，默认 `https://api.deepseek.com`
- `DEEPSEEK_MODEL`：DeepSeek 模型名
- `DEEPSEEK_TIMEOUT_SECONDS`：DeepSeek HTTP 调用超时
- `DATABASE_URL`：默认指向 docker-compose 内的 postgres
- `JWT_SECRET`、`INITIAL_USER_*`：本地登录鉴权使用

完整变量表见 [.env.example](file:///Users/bytedance/Desktop/ai-investment-assistant/.env.example)。

### 2. 检测开发环境

```bash
make check-dev
```

该命令会调用 [scripts/check-dev.sh](file:///Users/bytedance/Desktop/ai-investment-assistant/scripts/check-dev.sh)，检查系统工具、工具链版本、`.env` 完整性以及 3000 / 3001 / 8081 / 5432 端口占用情况。出现 `✗` 时请先修复再继续。

### 3. 启动 / 停止本地开发环境

统一通过 Makefile 提供的命令操作，不需要手动逐个起前后端。

```bash
make dev-start   # 启动本地开发环境 (postgres + nginx + backend + web)
make dev-end     # 停止本地开发环境
```

底层分别由 [scripts/dev-start.sh](file:///Users/bytedance/Desktop/ai-investment-assistant/scripts/dev-start.sh) 与 [scripts/dev-end.sh](file:///Users/bytedance/Desktop/ai-investment-assistant/scripts/dev-end.sh) 实现。

启动后默认端口：

- Nginx 统一入口：3000 — <http://localhost:3000>
- 前端 Web：3001 — <http://localhost:3001>
- 后端 BFF：8081
- Postgres：5432

## 常用命令

```bash
make help          # 查看 Makefile 提供的命令
make check-dev     # 开发环境体检
make dev-start     # 启动本地开发环境
make dev-end       # 停止本地开发环境
mise install       # 同步 mise.toml 锁定的工具链版本
mise run doctor    # 打印当前 node / pnpm / go / python / buf 版本
```

## 协作规范

- **请勿手动提交代码**：所有 `git commit` / `git push` 操作交由 agent 完成。需要提交时直接告诉 agent「提交代码」即可，避免提交信息风格不一致或漏掉规范化校验。

## 目录概览

- [backend/](file:///Users/bytedance/Desktop/ai-investment-assistant/backend) — Go BFF 服务，入口 `cmd/server/main.go`
- [web/](file:///Users/bytedance/Desktop/ai-investment-assistant/web) — Next.js 前端
- [docs/](file:///Users/bytedance/Desktop/ai-investment-assistant/docs) — 项目规划与设计文档
- [scripts/](file:///Users/bytedance/Desktop/ai-investment-assistant/scripts) — 运维 / 检测脚本
- [skills/](file:///Users/bytedance/Desktop/ai-investment-assistant/skills) — Code agent 共享 skills（详见 [AGENTS.md](file:///Users/bytedance/Desktop/ai-investment-assistant/AGENTS.md)）
