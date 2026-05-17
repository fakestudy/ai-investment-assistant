# AI 投资助手分步学习实施计划

> **For agentic workers / 给 agentic workers：** REQUIRED SUB-SKILL：使用 superpowers:executing-plans 按切片逐步实现。每个切片完成后先停下来复盘，再决定是否进入下一步。

**Goal / 目标：** 把 AI 投资助手 v1 拆成一组可以逐步理解、逐步实现、逐步验证的小切片。

**Architecture / 架构：** 保持三个项目边界：`fronted` 是 Next.js 前端项目，`backend` 是 Go 后端项目，`agent` 是 Python Agent 项目。每个切片只引入下一条链路真正需要的最小代码，优先跑通一个可验证的纵向路径，再扩展能力。

**Tech Stack / 技术栈：** Next.js、React、TypeScript、pnpm、Go、gRPC、PostgreSQL、Python、LangGraph/LangChain、Docker Compose。

---

## 使用方式

这份计划是学习路线，不替代完整实施计划。完整代码级步骤仍以 `docs/superpowers/plans/2026-05-16-ai-investment-assistant-v1.md` 为准。

执行节奏：

1. 一次只做一个切片。
2. 每个切片完成后运行对应验证命令。
3. 验证通过后提交一次 commit。
4. 提交后用 5 分钟回答该切片的复盘问题。
5. 能解释清楚这一层的输入、输出、依赖，再进入下一切片。

## 切片总览

| 切片 | 目标 | 完成后你应该理解 |
| --- | --- | --- |
| 0 | 项目边界确认 | 为什么分成 `fronted`、`backend`、`agent` |
| 1 | 三项目空骨架 | 每个项目自己的依赖和启动方式 |
| 2 | Protobuf 契约 | 为什么先定义跨服务接口 |
| 3 | 数据库 schema | 核心业务对象如何落库 |
| 4 | Go 平台层 | 配置、JWT、HTTP JSON、PostgreSQL 连接如何复用 |
| 5 | 登录纵向链路 | 前端如何通过 BFF 访问 User Service |
| 6 | 前端 shell | Next.js 如何承载登录态和工作台布局 |
| 7 | 行情 mock provider | 如何先用可控数据开发业务 |
| 8 | 自选股链路 | symbol 解析、保存、展示如何串起来 |
| 9 | Dashboard 聚合 | BFF 为什么负责页面 DTO 聚合 |
| 10 | 事件采集 | raw event 和 normalized event 的区别 |
| 11 | Agent 最小闭环 | Python Agent 如何输出结构化结果和 guardrail |
| 12 | 研究卡片 | Event 到 Research Card 的完整 AI 分析链路 |
| 13 | 上下文对话 | page context 如何进入 AI 问答 |
| 14 | 通知和 Lark | 站内通知与外部推送如何分层 |
| 15 | 本地部署和 e2e | Docker Compose 如何证明系统主路径可用 |

## 切片 0：项目边界确认

**目标：** 明确本项目不是一个根 pnpm workspace，而是三个独立项目加一层仓库级编排。

**涉及文件：**

- 阅读：`docs/superpowers/specs/2026-05-16-ai-investment-assistant-design.md`
- 阅读：`docs/superpowers/plans/2026-05-16-ai-investment-assistant-v1.md`
- 阅读：`docs/decisions/0001-v1-stack.md`

**执行步骤：**

- [ ] 阅读设计文档的“项目边界和资源归属”。
- [ ] 阅读完整实施计划顶部的“实施决策”。
- [ ] 确认根目录没有 `package.json` 和 `pnpm-workspace.yaml`。
- [ ] 运行：`git status --short`

**完成标准：**

- 你能解释：为什么 `fronted/package.json` 不应该放在根目录。
- 你能解释：为什么 Go 多服务仍放在一个 `backend` module 内。
- 你能解释：为什么 Python Agent 独立为 `agent` 项目。

**提交：**

如果本切片只阅读和确认，不需要提交。

## 切片 1：三项目空骨架

**目标：** 先创建三个项目的最小可运行骨架，不引入业务逻辑。

**涉及文件：**

- 创建：`fronted/package.json`
- 创建：`fronted/pnpm-lock.yaml`
- 创建：`fronted/app/page.tsx`
- 创建：`backend/go.mod`
- 创建：`backend/cmd/bff/main.go`
- 创建：`agent/pyproject.toml`
- 创建：`agent/app/server.py`
- 修改：`Makefile`

**执行步骤：**

- [ ] 创建 `fronted`，让 `cd fronted && pnpm install` 能生成 `pnpm-lock.yaml`。
- [ ] 创建最小 Next.js 页面，只显示产品名和“非投资建议，仅供研究参考”。
- [ ] 创建 `backend/go.mod` 和一个只返回 `/healthz` 的 BFF。
- [ ] 创建 `agent/pyproject.toml` 和一个能启动但暂不暴露业务能力的 Python package。
- [ ] 运行：`cd fronted && pnpm build`
- [ ] 运行：`cd backend && go test ./...`
- [ ] 运行：`cd agent && python -m pytest -q`

**完成标准：**

- 三个目录都能独立安装或测试。
- 你能说清楚：前端、Go 后端、Python Agent 的启动入口分别在哪里。

**提交：**

```bash
git add fronted backend agent Makefile
git commit -m "chore: scaffold three project skeletons"
```

## 切片 2：Protobuf 契约

**目标：** 先定义跨服务接口，再写服务实现。

**涉及文件：**

- 创建：`buf.yaml`
- 创建：`buf.gen.yaml`
- 创建：`proto/investment/v1/common.proto`
- 创建：`proto/investment/v1/user.proto`
- 创建：`proto/investment/v1/market.proto`
- 创建：`proto/investment/v1/watchlist.proto`
- 创建：`proto/investment/v1/event.proto`
- 创建：`proto/investment/v1/agent.proto`
- 创建：`proto/investment/v1/research.proto`
- 创建：`proto/investment/v1/notification.proto`
- 生成：`backend/gen/go`
- 生成：`agent/app/gen`

**执行步骤：**

- [ ] 先只写 `common.proto`、`user.proto`、`agent.proto`，理解基础类型和服务定义。
- [ ] 运行：`make proto`
- [ ] 确认 Go 生成代码进入 `backend/gen/go`。
- [ ] 确认 Python 生成代码进入 `agent/app/gen`。
- [ ] 再补齐 market、watchlist、event、research、notification proto。
- [ ] 再次运行：`make proto`

**完成标准：**

- 你能解释：BFF 为什么不直接 import Python Agent 内部代码。
- 你能解释：protobuf schema 稳定后，Go 和 Python 如何各自生成代码。

**提交：**

```bash
git add buf.yaml buf.gen.yaml proto backend/gen agent/app/gen
git commit -m "feat: define grpc contracts"
```

## 切片 3：数据库 Schema

**目标：** 把核心业务对象先落成 PostgreSQL 表，形成后续服务共同的数据语言。

**涉及文件：**

- 创建：`backend/db/migrations/0001_init.sql`
- 修改：`Makefile`

**执行步骤：**

- [ ] 创建用户、白名单、session 相关表。
- [ ] 创建自选股、symbol、quote、candle 相关表。
- [ ] 创建 raw event、normalized event、analysis task 相关表。
- [ ] 创建 research card、source、notification、chat 相关表。
- [ ] 运行本地 PostgreSQL 容器。
- [ ] 运行：`psql "postgres://investment:investment@localhost:55432/investment?sslmode=disable" -f backend/db/migrations/0001_init.sql`

**完成标准：**

- migration 可以从空库一次执行成功。
- 你能解释：为什么要同时保存 `raw_events` 和 `normalized_events`。
- 你能解释：为什么 `research_sources` 和 `research_cards` 分表。

**提交：**

```bash
git add backend/db/migrations/0001_init.sql Makefile
git commit -m "feat: add database schema"
```

## 切片 4：Go 共享平台层

**目标：** 在写业务服务前，先抽出 Go 服务都要用的基础设施。

**涉及文件：**

- 创建：`backend/internal/config/config.go`
- 创建：`backend/internal/platform/postgres/postgres.go`
- 创建：`backend/internal/platform/auth/jwt.go`
- 创建：`backend/internal/platform/httpjson/httpjson.go`

**执行步骤：**

- [ ] 写配置读取，覆盖 DB、JWT、服务地址和 provider 配置。
- [ ] 写 PostgreSQL 连接 helper。
- [ ] 写 JWT 签发和校验 helper。
- [ ] 写 HTTP JSON 响应和错误 helper。
- [ ] 运行：`cd backend && go test ./internal/...`

**完成标准：**

- BFF 和后续 gRPC 服务不需要各自重复读环境变量。
- 你能解释：平台层和业务层的区别。

**提交：**

```bash
git add backend/internal/config backend/internal/platform
git commit -m "feat: add backend platform layer"
```

## 切片 5：登录纵向链路

**目标：** 跑通第一个端到端业务能力：邮箱密码登录。

**涉及文件：**

- 创建：`backend/internal/service/user`
- 创建：`backend/cmd/user-service/main.go`
- 创建或修改：`backend/internal/bff`
- 创建或修改：`backend/cmd/bff/main.go`

**执行步骤：**

- [ ] User Service 校验邮箱白名单。
- [ ] User Service 校验密码 hash。
- [ ] BFF 暴露 `POST /api/auth/login`。
- [ ] BFF 调 User Service 后返回 access token。
- [ ] 运行：`cd backend && go test ./internal/service/user ./internal/bff`
- [ ] 用 curl 调 BFF 登录接口。

**完成标准：**

- 你能画出：Browser -> BFF -> User Service -> DB 的调用链。
- 你能解释：为什么登录入口是 HTTP，但内部服务是 gRPC。

**提交：**

```bash
git add backend/internal/service/user backend/cmd/user-service backend/internal/bff backend/cmd/bff
git commit -m "feat: add login vertical slice"
```

## 切片 6：前端登录和工作台 Shell

**目标：** 让用户能看到登录页，登录后进入空工作台。

**涉及文件：**

- 创建：`fronted/app/layout.tsx`
- 创建：`fronted/app/page.tsx`
- 创建：`fronted/app/providers.tsx`
- 创建：`fronted/features/auth/LoginPage.tsx`
- 创建：`fronted/features/dashboard/Workbench.tsx`
- 创建：`fronted/lib/api/client.ts`

**执行步骤：**

- [ ] 实现 `apiFetch`，统一加 Authorization header。
- [ ] 实现登录表单。
- [ ] 登录成功后把 token 保存到 localStorage。
- [ ] 实现桌面三栏空 shell 和移动端 tab shell。
- [ ] 运行：`cd fronted && pnpm test`
- [ ] 运行：`cd fronted && pnpm build`

**完成标准：**

- 登录前只看到登录页。
- 登录后进入工作台 shell。
- 你能解释：前端保存 token 的位置，以及后续请求如何带上 token。

**提交：**

```bash
git add fronted
git commit -m "feat: add login and workbench shell"
```

## 切片 7：行情 Mock Provider

**目标：** 在不依赖真实外部行情源的情况下，先开发稳定的行情能力。

**涉及文件：**

- 创建：`backend/internal/service/marketdata/provider.go`
- 创建：`backend/internal/service/marketdata/mock_provider.go`
- 创建：`backend/internal/service/marketdata/service.go`
- 创建：`backend/cmd/market-data-service/main.go`

**执行步骤：**

- [ ] 定义 `MarketDataProvider` interface。
- [ ] 实现 `mock` provider，固定返回 `AAPL`、报价和 K 线。
- [ ] Market Data Service 暴露 symbol 解析、quote、candles。
- [ ] 运行：`cd backend && go test ./internal/service/marketdata`

**完成标准：**

- 不需要外部 API key 也能拿到确定性行情数据。
- 你能解释：为什么真实 provider 要放到 adapter 后面。

**提交：**

```bash
git add backend/internal/service/marketdata backend/cmd/market-data-service
git commit -m "feat: add mock market data provider"
```

## 切片 8：自选股链路

**目标：** 跑通添加自选股、读取自选股的主路径。

**涉及文件：**

- 创建：`backend/internal/service/watchlist`
- 创建：`backend/cmd/watchlist-service/main.go`
- 修改：`backend/internal/bff`
- 修改：`fronted/features/watchlist/WatchlistPanel.tsx`

**执行步骤：**

- [ ] Watchlist Service 调 Market Data Service 解析 symbol。
- [ ] Watchlist Service 保存用户自选股。
- [ ] BFF 暴露添加和删除自选股 API。
- [ ] 前端右侧栏支持输入 ticker 并提交。
- [ ] 运行：`cd backend && go test ./internal/service/watchlist ./internal/bff`
- [ ] 运行：`cd fronted && pnpm test`

**完成标准：**

- 登录后能添加 `AAPL`。
- 页面能看到自选股条目。
- 你能解释：为什么 Watchlist Service 不直接信任用户输入的 ticker。

**提交：**

```bash
git add backend/internal/service/watchlist backend/cmd/watchlist-service backend/internal/bff fronted
git commit -m "feat: add watchlist vertical slice"
```

## 切片 9：Dashboard 聚合

**目标：** 让 BFF 返回一个适合工作台首屏使用的聚合 DTO。

**涉及文件：**

- 修改：`backend/internal/bff/dto.go`
- 修改：`backend/internal/bff/server.go`
- 修改：`fronted/features/dashboard/Workbench.tsx`
- 修改：`fronted/features/stocks/StockDetail.tsx`

**执行步骤：**

- [ ] BFF 新增 `GET /api/dashboard`。
- [ ] Dashboard DTO 包含 user、watchlist、notifications、summary。
- [ ] 前端 Workbench 使用 TanStack Query 拉 dashboard。
- [ ] StockDetail 显示当前 symbol 的报价摘要。
- [ ] 运行：`cd backend && go test ./internal/bff`
- [ ] 运行：`cd fronted && pnpm test`

**完成标准：**

- 前端不需要同时请求很多内部服务。
- 你能解释：BFF 聚合 DTO 和内部 gRPC response 的区别。

**提交：**

```bash
git add backend/internal/bff fronted
git commit -m "feat: add dashboard aggregation"
```

## 切片 10：事件采集

**目标：** 先用 mock 新闻事件跑通 raw event -> normalized event。

**涉及文件：**

- 创建：`backend/internal/service/event`
- 创建：`backend/internal/service/scheduler`
- 创建：`backend/cmd/event-service/main.go`
- 创建：`backend/cmd/scheduler-worker/main.go`

**执行步骤：**

- [ ] Event Service 写入 raw event。
- [ ] Event Service 标准化为 normalized event。
- [ ] 添加去重逻辑。
- [ ] 添加简单规则评分，先不调用 Agent。
- [ ] Scheduler Worker 从 Market Data mock news 拉事件。
- [ ] 运行：`cd backend && go test ./internal/service/event ./internal/service/scheduler`

**完成标准：**

- 同一 provider event 不会重复入库。
- 你能解释：事件重要性评分为什么可以先用规则。

**提交：**

```bash
git add backend/internal/service/event backend/internal/service/scheduler backend/cmd/event-service backend/cmd/scheduler-worker
git commit -m "feat: add event ingestion slice"
```

## 切片 11：Agent 最小闭环

**目标：** 让 Python Agent 能接收事件并返回符合 schema 的研究结果。

**涉及文件：**

- 创建：`agent/app/schemas.py`
- 创建：`agent/app/graphs/event_analysis.py`
- 创建：`agent/app/graphs/question_answer.py`
- 创建：`agent/app/providers/deepseek.py`
- 创建：`agent/app/server.py`
- 创建：`agent/tests/test_guardrails.py`

**执行步骤：**

- [ ] 用 Pydantic 定义 ResearchCard 输出 schema。
- [ ] 写 guardrail，禁止买入、卖出、加仓、减仓等指令。
- [ ] EventAnalysisGraph 先返回 deterministic mock 分析结果。
- [ ] DeepSeek provider 先封装接口，但测试中不发真实请求。
- [ ] gRPC server 暴露 AnalyzeEvent、AnswerQuestion。
- [ ] 运行：`cd agent && python -m pytest -q`

**完成标准：**

- Agent 测试不依赖真实模型。
- 你能解释：LangGraph workflow 和 LLM provider 的边界。
- 你能解释：为什么 guardrail 在 Agent 和 Research Service 都要考虑。

**提交：**

```bash
git add agent
git commit -m "feat: add agent analysis slice"
```

## 切片 12：研究卡片链路

**目标：** 跑通 normalized event -> Agent -> research card -> 前端展示。

**涉及文件：**

- 创建：`backend/internal/service/research`
- 创建：`backend/cmd/research-service/main.go`
- 修改：`backend/internal/bff`
- 创建或修改：`fronted/features/research/ResearchCard.tsx`

**执行步骤：**

- [ ] Research Service 调 Agent Service 的 `AnalyzeEvent`。
- [ ] 校验 Agent 返回内容包含免责声明。
- [ ] 保存 research card 和 sources。
- [ ] BFF 暴露 research card 列表和详情 API。
- [ ] 前端显示 stance、confidence、summary、key points、sources、disclaimer。
- [ ] 运行：`cd backend && go test ./internal/service/research ./internal/bff`
- [ ] 运行：`cd fronted && pnpm test`

**完成标准：**

- 一条高优先级事件能生成一张研究卡片。
- 你能解释：Research Service 为什么要校验 Agent 输出，而不是直接信任模型。

**提交：**

```bash
git add backend/internal/service/research backend/cmd/research-service backend/internal/bff fronted
git commit -m "feat: add research card slice"
```

## 切片 13：上下文 AI 对话

**目标：** 让用户能基于当前页面上下文追问。

**涉及文件：**

- 修改：`agent/app/graphs/question_answer.py`
- 修改：`backend/internal/bff/chat.go`
- 创建或修改：`fronted/features/ai/ChatPanel.tsx`

**执行步骤：**

- [ ] 定义前端发送的 page context：route、symbol、eventId、researchCardId。
- [ ] BFF 将 page context 转成 Agent `AnswerQuestionRequest`。
- [ ] Agent 返回带 disclaimer 的回答。
- [ ] 前端 ChatPanel 显示用户问题和助手回答。
- [ ] 运行：`cd agent && python -m pytest -q`
- [ ] 运行：`cd backend && go test ./internal/bff`
- [ ] 运行：`cd fronted && pnpm test`

**完成标准：**

- 用户在股票详情或研究卡片页面追问时，问题会带上当前上下文。
- 你能解释：page context 和聊天 thread 的区别。

**提交：**

```bash
git add agent backend/internal/bff fronted
git commit -m "feat: add contextual chat slice"
```

## 切片 14：通知和 Lark 推送

**目标：** 先保证站内通知完整，再把高优先级通知推到 Lark。

**涉及文件：**

- 创建：`backend/internal/service/notification`
- 创建：`backend/cmd/notification-service/main.go`
- 修改：`backend/internal/service/research`
- 修改：`backend/internal/bff`
- 创建或修改：`fronted/features/notifications/NotificationBell.tsx`

**执行步骤：**

- [ ] Notification Service 创建站内通知。
- [ ] 保存 read/unread 状态。
- [ ] 保存 Lark push status。
- [ ] 高优先级 research card 触发 Lark webhook。
- [ ] BFF 暴露通知列表和标记已读 API。
- [ ] 前端显示未读高优先级提醒。
- [ ] 运行：`cd backend && go test ./internal/service/notification ./internal/service/research ./internal/bff`
- [ ] 运行：`cd fronted && pnpm test`

**完成标准：**

- 外部推送失败不会丢失站内通知。
- 你能解释：为什么站内通知是完整记录源，Lark 只是外部渠道。

**提交：**

```bash
git add backend/internal/service/notification backend/cmd/notification-service backend/internal/service/research backend/internal/bff fronted
git commit -m "feat: add notification slice"
```

## 切片 15：本地部署和 E2E

**目标：** 用 Docker Compose 和 Playwright 证明主路径可用。

**涉及文件：**

- 创建：`backend/Dockerfile`
- 创建：`fronted/Dockerfile`
- 创建：`agent/Dockerfile`
- 创建：`infra/docker-compose.yml`
- 创建：`fronted/playwright.config.ts`
- 创建：`fronted/tests/e2e/smoke.spec.ts`
- 创建：`docs/deploy/china-mainland.md`

**执行步骤：**

- [ ] backend Dockerfile 支持用 `SERVICE_CMD` 构建不同 Go 服务。
- [ ] fronted Dockerfile 从 `fronted/package.json` 和 `fronted/pnpm-lock.yaml` 安装依赖。
- [ ] agent Dockerfile 只复制 `agent` 项目。
- [ ] docker-compose 启动 postgres、web、bff、Go gRPC 服务和 agent-service。
- [ ] Playwright smoke 覆盖登录、添加 `AAPL`、看到研究界面、发起 AI 追问。
- [ ] 运行：`make compose-up`
- [ ] 运行：`cd fronted && pnpm test:e2e`

**完成标准：**

- `http://localhost:3000` 可以访问工作台。
- `http://localhost:8080/healthz` 返回健康状态。
- e2e smoke test 覆盖主路径。
- 你能解释：Docker Compose 内部服务名如何对应 `.env.example` 中的地址。

**提交：**

```bash
git add backend/Dockerfile fronted/Dockerfile agent/Dockerfile infra/docker-compose.yml fronted/playwright.config.ts fronted/tests/e2e docs/deploy/china-mainland.md
git commit -m "test: add local deployment smoke path"
```

## 每个切片的复盘问题

每完成一个切片，回答这四个问题：

1. 这个切片新增了哪条能力？
2. 输入是什么，输出是什么？
3. 它依赖前面哪个切片？
4. 如果它坏了，我应该先看哪个测试或哪个日志？

如果这四个问题答不清楚，先不要进入下一切片。
