# AI 投资助手 v1 设计方案

## 1. 目标

AI 投资助手是一个个人美股研究工作台。它帮助用户围绕手动维护的自选股，跟踪重要市场和公司事件，查看股票走势，并通过 AI 对话继续追问。

这个产品只提供研究辅助，不提供交易指令。AI 可以给出看多、看空、中性或混合的研究倾向，并说明置信度、依据、风险和后续观察指标；但不能直接给出买入、卖出、加仓、减仓等操作建议。

## 2. v1 范围

### 包含

- 桌面端和移动端响应式 Web 工作台，前端框架固定使用 Next.js App Router。
- 邮箱 + 密码登录，并通过邮箱白名单限制可登录用户。
- 手动维护美股自选股。
- 展示股票报价、K 线和基础公司信息。
- 支持通过轮询和 webhook 接入行情、新闻和公司事件。
- 针对重要事件生成结构化 AI 研究卡片。
- 支持基于当前股票、事件、研究卡片上下文的 AI 对话追问。
- 站内消息通知，以及高优先级消息的飞书/Lark 推送。
- 使用 PostgreSQL 持久化数据。
- 后端采用多服务架构，服务间通过 gRPC 通信。
- Python Agent Service 使用 LangGraph 和 LangChain 开发。
- 第一版 LLM Provider 使用 DeepSeek。
- 第一阶段使用本地 Docker Compose 部署，并保留后续中国内地云服务部署路径。

### 不包含

- 券商账户连接。
- 真实持仓或仓位导入。
- 下单和交易执行。
- 直接交易建议。
- 多人团队权限模型。
- SaaS 订阅和计费。
- 邮箱验证码、密码找回和完整登录风控。
- 生产级合规审查。

## 3. 产品体验

### 桌面端布局

桌面端采用三栏 AI 优先工作台：

- 左侧：AI 对话栏。这是产品第一入口。它展示当前上下文，支持新建对话，并允许用户围绕当前股票、事件或研究卡片追问。
- 中间：主研究区。它展示当前选中股票的详情、价格摘要、走势图、关键指标、事件流、研究卡片列表和卡片详情。
- 右侧：自选股和提醒栏。它展示手动添加的股票、涨跌变化、未读高优先级提醒，以及添加/搜索 ticker 的入口。

打开应用时，体验应更像进入一个由 AI 驱动的投资研究工作台，而不是传统行情面板。左侧 AI 可以先给出今日自选股摘要和推荐追问问题。

### 移动端布局

移动端不保留三栏结构，而是使用 Tab 化体验：

- AI
- 股票
- 自选
- 消息

当用户打开某只股票、某个事件或某张研究卡片时，AI 入口仍然应该容易触达，并自动带入当前上下文。

## 4. 核心用户流程

### 登录

1. 用户输入邮箱和密码。
2. BFF 调用 User Service。
3. User Service 校验邮箱白名单和密码 hash。
4. BFF 拿到 session/JWT 后，把登录态返回给前端。

邮箱是用户唯一身份。v1 不实现邮箱验证码；但在公网或云部署前，必须补充邮箱验证、密码找回、登录限流和审计日志。

### 添加自选股

1. 用户搜索或输入美股 ticker。
2. BFF 调用 Watchlist Service。
3. Watchlist Service 调用 Market Data Service 解析并标准化股票代码。
4. Watchlist Service 保存自选股条目和股票基础信息快照。

### 事件采集与研究卡片生成

1. Scheduler 定时轮询用户自选股相关的行情、新闻和公司事件。
2. 如果数据源支持 webhook，也通过同一事件入口接入。
3. Event Service 对事件进行标准化、去重、评分和入库。
4. 重要事件创建分析任务。
5. Research Service 通过 gRPC 调用 Python Agent Service。
6. Agent Service 执行 LangGraph 工作流，并返回结构化研究卡片。
7. Research Service 校验并保存研究卡片。
8. Notification Service 创建站内消息，并对高优先级卡片发送飞书/Lark 推送。

### 上下文 AI 对话

1. 用户在左侧 AI 对话栏提问。
2. BFF 将问题和用户、股票、事件、页面、研究卡片上下文一起发送给 Agent Service。
3. Agent Service 检索相关上下文，生成带来源的回答。
4. 对话消息被保存，并归属于用户和对应股票上下文。

## 5. 系统架构

### 运行拓扑

- `fronted`：Next.js App Router + React 响应式 Web 应用。
- `backend`：Go 项目，包含 BFF / API Gateway、内部 gRPC 服务和后台 worker。
- User Service：Go gRPC 服务。
- Watchlist Service：Go gRPC 服务。
- Market Data Service：Go gRPC 服务。
- Event Service：Go gRPC 服务。
- Research Service：Go gRPC 服务。
- Notification Service：Go gRPC 服务。
- Scheduler Worker：Go 后台任务进程。
- `agent`：Python gRPC 服务，内部使用 LangGraph 和 LangChain。
- Database：PostgreSQL。
- 可选缓存/协调组件：Redis。

前端只通过 HTTP 调用 BFF，不直接调用 gRPC。BFF 负责认证、前端 DTO 聚合、权限校验和错误转换。后端内部服务通过 gRPC 和 protobuf 通信。

### 项目边界和资源归属

v1 按三个可独立理解的项目组织代码：

- `fronted`：前端项目。Next.js、React、TypeScript、Tailwind、测试配置、`package.json`、`pnpm-lock.yaml` 和前端 Dockerfile 都放在该目录内。
- `backend`：Go 后端项目。BFF、Go gRPC 服务、scheduler worker、数据库 migration、Go protobuf 生成代码、`go.mod`、`go.sum` 和后端 Dockerfile 都放在该目录内。
- `agent`：Python Agent 项目。LangGraph/LangChain workflow、DeepSeek provider、Python protobuf 生成代码、测试、Python 项目配置和 Agent Dockerfile 都放在该目录内。

仓库根目录只保留跨项目文档、共享 protobuf 源文件、部署编排、环境样例和少量 orchestration 命令，不维护前端或后端语言生态的依赖副本。各项目的依赖锁文件随项目目录提交，避免根目录 workspace 配置隐式拥有子项目资源。

### 服务职责

#### BFF / API Gateway

- 对前端暴露 HTTP API。
- 校验登录态。
- 聚合多个内部服务的结果，组装前端页面需要的数据。
- 将内部错误转换成前端可理解的错误响应。
- 避免承载属于业务服务的领域逻辑。

#### User Service

- 管理用户、邮箱白名单、密码 hash、登录和 session/JWT。
- 将邮箱作为唯一身份。
- v1 不发送邮箱验证码。

#### Watchlist Service

- 管理用户自选股。
- 添加和删除股票。
- 保存自选股对应的标准化股票信息。
- 调用 Market Data Service 解析 symbol，而不是直接信任用户输入。

#### Market Data Service

- 负责行情数据 provider 集成。
- 提供股票解析、报价、K 线和新闻 API。
- v1 从免费或低成本数据源开始。
- 将 provider 特有的数据格式隔离在 adapter 内部。
- 支持后续切换到付费数据 API，而不影响业务服务。

#### Event Service

- 接收轮询和 webhook 产生的事件。
- 保存外部数据源原始 payload。
- 将事件标准化为稳定的内部模型。
- 对重复事件去重。
- 对事件重要性打分。
- 为重要事件创建分析任务。

#### Research Service

- 管理研究卡片生命周期。
- 调用 Agent Service 完成事件分析。
- 校验 Agent 返回的结构化结果。
- 保存研究卡片和引用来源。
- 对高优先级研究卡片协调创建通知。

#### Notification Service

- 管理站内消息和飞书/Lark 推送。
- 保存已读/未读状态和推送状态。
- 只对高优先级内容发送外部通知。
- 让外部推送失败可观察、可重试。

#### Scheduler Worker

- 执行轮询任务。
- 通过 gRPC 调用服务，不直接跨服务写表。
- 处理采集任务的重试和退避。

#### Agent Service

- 暴露事件分析、问答、自选股摘要等 gRPC 方法。
- 使用 LangGraph 作为工作流编排引擎。
- 使用 LangChain 处理模型封装、工具、Prompt、检索和结构化输出。
- 通过 LLM Provider 抽象调用 DeepSeek。

## 6. gRPC 边界

v1 应为内部服务定义 protobuf 契约。最关键的边界是 Go 后端服务与 Python Agent Service 之间的 RPC 契约。

Agent RPC 示例：

- `AnalyzeEvent(AnalyzeEventRequest) returns (ResearchCardResult)`
- `AnswerQuestion(AnswerQuestionRequest) returns (AnswerResult)`
- `SummarizeWatchlist(SummarizeWatchlistRequest) returns (WatchlistSummaryResult)`

Go 后端不能依赖 LangGraph 内部实现，只依赖 protobuf 契约。Python 侧可以持续调整 graph 节点、Prompt、工具和模型 provider，只要 RPC schema 稳定，就不会破坏 Go 服务。

更大的后端服务图也使用 gRPC，以便学习标准后端服务范式。每个服务都应定义清晰的 request/response、状态码、deadline、重试预期和错误详情。

## 7. 数据模型

核心 PostgreSQL 表：

- `users`：邮箱、密码 hash、状态、时间戳。
- `email_allowlist`：允许登录的邮箱。
- `sessions`：如果持久化 JWT refresh token，则保存 session 或 refresh token 记录。
- `watchlist_items`：用户、symbol、交易所、名称、币种、排序。
- `market_symbols`：标准化股票主数据。
- `market_quotes`：报价快照。
- `market_candles`：历史或日内 K 线。
- `raw_events`：来源名称、来源事件 ID、原始 payload、接收时间。
- `normalized_events`：稳定的事件模型，包含关联 symbol、标题、摘要、来源、发布时间、事件类型和重要性。
- `analysis_tasks`：事件分析任务状态、重试次数、错误信息。
- `research_cards`：结构化 AI 研究输出。
- `research_sources`：每张研究卡片对应的来源链接和来源元数据。
- `notifications`：站内消息、优先级、已读状态。
- `feishu_push_configs`：飞书/Lark webhook 或机器人配置。
- `chat_threads`：用户和可选股票上下文。
- `chat_messages`：用户和助手消息，以及上下文引用。

外部数据源的原始 payload 要保留，方便调试和回放。业务逻辑只消费标准化模型，不直接依赖 provider 特有结构。

## 8. 数据源策略

v1 优先使用免费或低成本行情/新闻数据源，但系统必须从一开始就支持 provider 可替换。

Provider 抽象：

- `MarketDataProvider`：股票解析、报价、K 线、公司基础信息。
- `NewsProvider`：新闻和公司事件。
- `WebhookProvider`：可选的数据源 webhook 标准化。

标准化字段包括：

- 股票：symbol、名称、交易所、币种。
- K 线：open、high、low、close、volume、timestamp、是否复权。
- 报价：价格、涨跌额、涨跌幅、市场时间、延迟标记。
- 新闻/事件：标题、摘要、来源、发布时间、关联股票、URL、重要性。

后续迁移风险：

- 拆股、分红和复权口径。
- symbol 格式差异，例如 `BRK.B` 与 `BRK-B`。
- 延迟数据和实时数据的标记。
- 新闻授权限制。
- 免费源限流和稳定性。

UI 和数据库需要在必要场景下展示数据延迟和来源信息。

## 9. 基于 LangGraph 的 Agent 设计

LangGraph 是主要编排层。LangChain 提供模型接入、工具、Prompt、检索和结构化输出能力。

### Graph

#### EventAnalysisGraph

目的：将重要事件转化为结构化研究卡片。

流程：

1. `validate_event`
2. `load_context`
3. `retrieve_sources`
4. `rank_sources`
5. `reason_with_llm`
6. `schema_validate`
7. `risk_guardrail`
8. `output_card`

#### QuestionAnswerGraph

目的：基于当前股票、页面、事件和研究卡片上下文回答用户问题。

流程：

1. `normalize_question`
2. `load_page_context`
3. `retrieve_related_cards`
4. `answer_with_sources`
5. `guardrail`
6. `output_answer`

#### WatchlistSummaryGraph

目的：生成用户自选股的日常或按需摘要。

流程：

1. `load_watchlist`
2. `collect_recent_events`
3. `group_by_symbol`
4. `summarize`
5. `rank_notifications`

#### EventRankGraph

目的：提升事件重要性排序能力。如果 v1 先使用规则评分，这个 graph 可以延后实现。

### Agent State

Agent state 应显式定义类型，包含：

- `user_id`
- `symbol`
- `event`
- `market_context`
- `news_sources`
- `historical_cards`
- `question`
- `page_context`
- `risk_flags`
- `llm_output`
- `validated_card`
- `answer`
- `errors`

### 研究卡片 Schema

研究卡片应结构化保存：

- `symbol`
- `event_title`
- `stance`：bullish、bearish、neutral 或 mixed。
- `confidence`：low、medium 或 high。
- `summary`
- `key_points`
- `counter_points`
- `watch_indicators`
- `time_horizon`
- `sources`
- `disclaimer`

所有重要判断都应尽量绑定来源。如果模型是在推断，而不是陈述已确认事实，输出中必须明确标记为推断。

## 10. 风控和合规边界

允许：

- 解释发生了什么。
- 解释可能的影响路径。
- 给出看多、看空、中性或混合的研究倾向。
- 给出置信度、风险点和后续观察指标。
- 比较不同解读方式。

不允许：

- 直接给出买入、卖出、加仓、减仓指令。
- 承诺确定性收益。
- 给出没有来源支撑的事实判断。
- 将延迟数据伪装成实时数据。
- 隐藏不确定性。

UI 需要在 AI 回答和研究卡片上展示清晰免责声明：内容不是投资建议，仅供研究参考。

## 11. 飞书/Lark 推送

飞书/Lark 是第一版外部通知渠道，只用于高优先级提醒。站内通知中心仍然是完整的消息记录来源。

推送内容包括：

- 股票代码和公司名。
- 事件标题。
- AI 一句话摘要。
- 研究倾向。
- 置信度。
- 关键风险。
- 工作台详情页链接。

每条推送都应关联已落库的 `notification_id` 和 `research_card_id`。推送状态需要持久化，用于重试、排查和防止重复发送。

## 12. 本地部署

v1 本地部署使用 Docker Compose。

服务包括：

- `web`，由 `fronted` 目录构建
- `bff`
- `user-service`
- `watchlist-service`
- `market-data-service`
- `event-service`
- `research-service`
- `notification-service`
- `scheduler-worker`
- `agent-service`，由 `agent` 目录构建
- `postgres`
- 可选 `redis`

每个服务应有独立 Dockerfile、健康检查、配置和日志。配置通过 `.env` 注入，包括：

- DeepSeek API Key。
- 飞书 webhook 或机器人配置。
- 数据库连接。
- 邮箱白名单。
- 密码/session secret。
- 数据源 provider 配置。
- 轮询间隔。

## 13. 中国内地云服务部署路径

第一条可部署路径仍然保持容器化。

推荐演进路线：

1. 先在国内云服务器上用 Docker Compose 部署。
2. 将镜像迁移到中国内地可稳定访问的容器镜像仓库。
3. 只对公网暴露 Web 和 BFF。
4. gRPC 服务只在内网访问。
5. 在 BFF 前配置域名和 HTTPS。
6. 将 PostgreSQL 迁移到云数据库，并开启备份。
7. 增加 Redis，用于缓存、锁、限流和短期状态。
8. 使用密钥管理替代明文 `.env`。
9. 增加可观测性：结构化日志、指标、链路追踪和任务失败告警。

中国内地环境需要特别注意：

- 优先使用 DeepSeek 或其他中国内地网络可稳定访问的模型服务。
- 金融数据源在内地网络下可能不稳定，provider adapter 需要支持超时、重试、缓存和代理。
- 云服务需要能访问飞书开放平台或机器人 webhook。
- 依赖安装和镜像拉取应使用内地镜像源或私有镜像仓库。
- 公网部署前必须补齐邮箱验证、密码找回、登录限流和审计日志。

## 14. 测试策略

前端：

- 主面板和研究卡片渲染组件测试。
- 桌面端和移动端响应式布局测试。
- 登录、自选股、股票详情、AI 对话入口的基础端到端测试。

BFF：

- HTTP API 集成测试。
- 认证和权限测试。
- 错误映射测试。

Go gRPC 服务：

- Proto 契约测试。
- Service 单元测试。
- Repository 测试。
- gRPC deadline 和错误详情测试。

Python Agent：

- LangGraph 节点单元测试。
- 事件分析和问答 golden case。
- 结构化输出 schema 校验测试。
- 禁止交易建议的 guardrail 测试。
- Mock DeepSeek Provider 测试。

数据源：

- Mock provider 测试。
- 真实 provider smoke test。
- 限流和失败降级测试。

端到端：

- Docker Compose 启动全部服务。
- 用户登录。
- 用户添加 ticker。
- Scheduler 采集事件。
- 生成研究卡片。
- 创建站内通知。
- 在受控测试模式下 mock 或发送飞书推送。

## 15. 实现顺序

1. 仓库和 monorepo 骨架。
2. Proto 定义和代码生成。
3. PostgreSQL schema migration。
4. User Service 和 BFF 登录。
5. Watchlist Service 和 symbol 解析。
6. Market Data Service，先实现 mock provider，再接第一个真实免费/低成本 provider。
7. Event Service 轮询事件接入。
8. Research Service 和 Python Agent gRPC 骨架。
9. 基于 DeepSeek Provider 的 LangGraph EventAnalysisGraph。
10. 研究卡片持久化和前端展示。
11. 带上下文的 AI 对话。
12. Notification Service 和站内消息。
13. 飞书/Lark 推送。
14. Webhook 事件接入。
15. Docker Compose 加固和完整 e2e smoke test。

## 16. 待实施计划阶段确认的决策

以下决策推迟到 implementation plan 阶段确认：

- Go gRPC 框架和代码生成目录结构。
- 第一个免费或低成本行情/新闻数据源。
- Redis 是否进入 v1，还是在首条主链路跑通后加入。
- 第一阶段是否需要聊天流式输出。

这些决策不会改变已经确认的产品边界和架构边界。
