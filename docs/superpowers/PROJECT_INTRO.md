# AI 投资助手项目介绍

## 项目概述

AI 投资助手是一个可本地部署、AI 优先的美股研究工作台，面向需要持续跟踪美股标的、新闻事件和研究结论的个人研究场景。项目将行情数据、事件采集、AI 研究分析、上下文问答和通知推送整合到一个响应式 Web 工作台中，帮助用户围绕自选股快速形成结构化研究视图。

> 重要边界：本项目仅提供研究参考，不提供买入、卖出、加仓、减仓等交易指令；所有 AI 输出和研究卡片都必须展示免责声明。

## 核心能力

- **登录与访问控制**：支持邮箱/密码登录，并通过邮箱白名单限制可访问用户。
- **手动自选股管理**：用户可以添加、查看和移除关注的美股标的。
- **行情与公司信息**：展示报价、涨跌幅、K 线、公司信息，并标记数据来源和延迟状态。
- **新闻与事件采集**：支持轮询自选股相关新闻，并将原始事件标准化、去重、分类和优先级评分。
- **AI 研究卡片**：针对高优先级事件生成结构化研究卡片，包含观点倾向、置信度、摘要、关键论据、反方观点、观察指标、时间周期和来源。
- **上下文 AI 对话**：用户可以基于当前股票、事件或研究卡片进行非流式 AI 问答。
- **站内通知**：对重要研究事件生成站内通知。
- **Lark/飞书推送**：高优先级通知可通过 Lark webhook 推送到外部群聊或个人通道。
- **本地容器化部署**：通过 Docker Compose 一键启动 Web、BFF、后端服务、Agent Service 和 PostgreSQL。

## 产品形态

前端是一个响应式 AI 研究工作台：

- **桌面端**：采用三栏布局，左侧为 AI 对话，中间为股票详情与研究内容，右侧为自选股和通知。
- **移动端**：采用底部 Tab 布局，包含 `AI`、`股票`、`自选`、`消息` 四个入口。
- **研究展示**：每张研究卡片都显示免责声明、数据来源和关键观察指标，强调事实核验和研究用途。

## 技术架构

项目采用 monorepo 组织，整体由 `fronted`、`backend`、`agent`、PostgreSQL 和 Docker Compose 组成。三个项目的语言生态资源放在各自目录内：前端的 `package.json` 和 `pnpm-lock.yaml` 在 `fronted`，Go 的 `go.mod` 和 `go.sum` 在 `backend`，Python Agent 的项目配置在 `agent`。

```text
浏览器 Web 工作台（fronted / Next.js）
       │ HTTP
       ▼
Go HTTP BFF（backend）
       │ gRPC
       ├── User Service
       ├── Watchlist Service
       ├── Market Data Service
       ├── Event Service
       ├── Research Service
       ├── Notification Service
       └── Scheduler Worker
              │ gRPC
              ▼
Python LangGraph Agent Service（agent）
       │
       ▼
DeepSeek 兼容 Chat Completions

PostgreSQL 负责持久化用户、自选股、行情、事件、研究卡片、通知和聊天历史。
```

### 架构原则

- `fronted` 只通过 HTTP 调用 Go BFF，不直接访问内部服务。
- BFF 和 worker 通过 gRPC 调用内部业务服务。
- Go 后端只通过 protobuf 契约依赖 Python Agent Service。
- 根目录不维护 pnpm workspace 或跨项目依赖副本；项目依赖和锁文件随各自项目目录提交。
- 行情 provider 先实现 `mock`，保证本地开发和测试确定性；再接入 `alpha_vantage` 作为第一个真实数据 adapter。
- v1 暂不引入 Redis，优先用 PostgreSQL 跑通第一条可用链路。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| `fronted` | Next.js App Router、React、TypeScript、TanStack Query、Tailwind CSS、Recharts、pnpm |
| `backend` | Go 1.26、grpc-go、pgx、chi、JWT |
| `agent` | Python 3.12、LangGraph、LangChain、Pydantic |
| LLM Provider | DeepSeek 兼容 Chat Completions |
| 数据库 | PostgreSQL 16、Goose 风格 SQL migration |
| 契约与生成 | protobuf、gRPC、Buf |
| 部署 | Docker Compose |
| 测试 | Go test、pytest、Vitest、Playwright |

## 服务模块

- **fronted**：Next.js Web App，负责登录页、工作台布局、股票详情、研究卡片、AI 对话、自选股和通知展示。
- **backend / BFF**：提供 Web 所需 HTTP API，处理认证、DTO 聚合和内部 gRPC 编排。
- **User Service**：负责用户登录、白名单校验和 JWT 签发。
- **Watchlist Service**：负责自选股列表维护，并在添加标的前解析 symbol。
- **Market Data Service**：负责 symbol 解析、报价、K 线、公司信息和新闻数据。
- **Event Service**：负责原始新闻/事件入库、去重、标准化、分类和优先级评分。
- **Research Service**：调用 Agent Service 生成研究卡片，并进行合规校验和持久化。
- **Notification Service**：生成站内通知，并对高优先级内容触发 Lark/飞书推送。
- **Scheduler Worker**：周期性扫描自选股、拉取新闻、生成事件并触发研究流程。
- **agent / Agent Service**：基于 LangGraph/LangChain 生成事件分析、上下文问答和自选股摘要。

## 数据模型概览

PostgreSQL 持久化核心对象包括：

- 用户、邮箱白名单和会话；
- 市场标的、报价和 K 线；
- 自选股；
- 原始事件和标准化事件；
- AI 分析任务；
- 研究卡片和研究来源；
- 站内通知和 Lark/飞书推送配置；
- 聊天线程和聊天消息。

## 典型使用流程

1. 用户通过白名单邮箱和密码登录 Web 工作台。
2. 用户手动添加关注的美股标的，例如 `AAPL`。
3. 系统解析股票代码，展示报价、K 线、公司信息和相关新闻。
4. Scheduler Worker 周期性拉取自选股新闻并写入标准化事件。
5. 高优先级事件触发 Research Service 调用 Agent Service。
6. Agent Service 生成结构化研究卡片，并附带来源和免责声明。
7. Research Service 校验输出是否包含禁用交易指令，校验通过后保存研究卡片。
8. Notification Service 生成站内通知，并对高优先级内容推送到 Lark/飞书。
9. 用户可以围绕当前股票、事件或研究卡片继续向 AI 提问。

## 合规与安全边界

- AI 输出不得包含明确交易指令，如买入、卖出、加仓、减仓等。
- 每张研究卡片和每条 AI 回答必须包含“非投资建议，仅供研究参考”的免责声明。
- UI 必须展示数据来源、发布时间、provider 和行情延迟标记。
- 登录入口使用邮箱白名单限制访问范围。
- 公网部署前需要补齐邮箱验证、密码找回、登录限流、审计日志和密钥管理。

## 部署方式

v1 的第一条部署路径是本地 Docker Compose：

- `web` 暴露 Web 工作台，默认端口 `3000`；
- `bff` 暴露 HTTP API，默认端口 `8080`；
- Go gRPC 服务和 Python Agent Service 在内部网络中通信；
- PostgreSQL 作为唯一持久化依赖；
- DeepSeek 和 Alpha Vantage 通过环境变量配置 API key。

后续迁移到中国内地云服务器时，建议保持容器化部署路径，仅暴露 `web` 和 `bff`，内部服务放在私有网络，并逐步替换为托管 PostgreSQL、云密钥管理、结构化日志、指标、链路追踪和告警体系。

## 验证策略

项目计划覆盖多层测试：

- Go 服务单元测试与集成测试；
- Python Agent guardrail 测试；
- Web 组件测试；
- BFF API 测试；
- Playwright 端到端 smoke test；
- Docker Compose 本地启动验证。

最终完成状态要求：所有测试通过，`http://localhost:3000` 可访问工作台，`http://localhost:8080/healthz` 返回健康状态，端到端测试覆盖登录、添加 `AAPL`、展示研究界面和收到带免责声明的 AI 回答。
