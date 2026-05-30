# AI 聊天助手 · 12 周执行计划（PLAN_CHAT.md）

> 本文档由一次完整的"决策树拷问"沉淀而来。
> 本期（12 周）仅聚焦「通用 AI 聊天助手」；原 `PLAN.md` 描述的「投资助手」愿景作为远期目标保留，本期暂不实现。
> 12 周内，所有"想换方向 / 换栈"的冲动都先来这里查一遍——决策已锁，不再讨论。

---

## 0. 个人背景与目标

- **背景**：4 年前端经验；后端学过基础语法，了解 SQL/NoSQL/ORM/Docker 但无生产实操；公司全栈项目可参与（前端 React + 后端 Go + MySQL + 内部框架）。
- **可投入时间**：工作日 9:00-12:00（自由的个人项目时段，共 15h/周）+ 周末 8h × 2（共 16h/周）= **31h/周**。
- **学习动机**：
  - **B（转型全栈/AI 工程师）** + **C（副业/独立开发者）**
  - **C 优先**：先做出能跑的端到端产品；产品倒逼补 B（系统后端能力）。
- **本期定位**：聊天助手是「未来投资助手」的工程基座。把通用对话链路、Agent skills 注入、多会话持久化、Go 工程化跑通；任何投资域内容（财报、持仓、SEC、PDF 解析）都不进本期范围。

---

## 1. 战略决策摘要（19 项，已锁）

| # | 决策项 | 结论 |
|---|--------|------|
| 1 | 项目身份 | 通用 AI 聊天助手（未来投资助手的 v0） |
| 2 | 12 周范围 | **专注聊天助手**，投资业务不写进本期 |
| 3 | 后端语言 | **Go 单语言**，无 Python 层 |
| 4 | Agent 框架 | **cloudwego/eino** |
| 5 | Eino 使用深度 | **ReAct Agent + ToolNode**（skills/tool calling 注入） |
| 6 | 演示 skills（v0.1） | `web_search` + `fetch_url` 两个工具 |
| 7 | LLM 服务商 | **DeepSeek**（已购 key），第二个模型留到 W11 之后再考虑 |
| 8 | 前端 | **保留现有 Next.js + ai-elements**（已搭好，不重启） |
| 9 | Go HTTP 框架 | **Gin** |
| 10 | 前后端协议 | **REST（JSON）+ SSE（聊天流式）**，无 gRPC |
| 11 | 数据库 | **纯 PostgreSQL**（v0.2 接 RAG 时再加 pgvector extension） |
| 12 | 用户系统 | v0.1 **不做**，单机/单用户 |
| 13 | v0.1 范围 | 多会话 + 流式 + Markdown/Code + 思考过程 + 2 个工具；**不做**文件上传、不做模型切换 UI |
| 14 | W4 末检查点 | 多会话 + Agent 调通 1 个工具（web_search） |
| 15 | MVP 节点 | **W6 末**（六周 MVP，比传统四周宽一些） |
| 16 | RAG | W11-W12 跑通最小链路作为加分项，不做生产级 |
| 17 | 仓库结构 | **Monorepo**：`backend/`（Go） + `web/`（Next.js，已存在） |
| 18 | 部署 | v0.x **本地**，不上线 |
| 19 | 旧 PLAN.md | 保留作为远期投资助手蓝图，本期不动它 |

---

## 2. 技术栈（锁定，不再讨论）

```
前端:        Next.js (React) + ai-elements + shadcn/ui   <-- 已搭好
后端:        Go + Gin
ORM:         GORM
数据库:      PostgreSQL（镜像建议 postgres:16）
Agent 框架:  cloudwego/eino
LLM:         DeepSeek（首选）
通信:        REST JSON + SSE（text/event-stream）
容器化:      Docker + Docker Compose
部署:        本地，不上线
```

**与原 PLAN 的关键差异**：
- 删除 Python / LangGraph / gRPC / proto 工具链
- pgvector 推迟，先不引入
- Agent 编排从 LangGraph（Python） 换为 Eino（Go）

---

## 3. 项目架构

### 3.1 服务划分

```
[Next.js 前端] ──HTTP/SSE──▶ [Go 服务（Gin + Eino Agent）]
        │                          │
        │                          ▼
        │                   [PostgreSQL]
        │
        └─ 仅 SSR + 客户端壳，所有 API 一律走 Go
```

- **Go 服务**：API 网关、会话与消息持久化、Eino Agent 编排、工具实现、外部数据源（v0.1 仅 web_search / fetch_url）。
- **前端**：Next.js 仅作 SSR + 客户端壳，**不在 Next.js 写后端逻辑**；通过 fetch + EventSource/ReadableStream 消费 Go 的 SSE。

### 3.2 后端分层（建议，落地时按需调整）

```
backend/
├── cmd/server/main.go          # 入口
├── internal/
│   ├── api/                    # Gin handler & SSE writer
│   ├── agent/                  # Eino Agent 装配与运行
│   ├── tools/                  # ToolNode 实现（web_search、fetch_url）
│   ├── llm/                    # ChatModel 工厂（DeepSeek 适配）
│   ├── store/                  # GORM models + repository
│   ├── conversation/           # 会话/消息领域服务
│   └── config/                 # 配置加载
├── migrations/                 # SQL 迁移
└── go.mod
```

> 这是建议骨架，Day 1 不必一次到位；W3-W4 第二次重写时再向这个形态收敛。

### 3.3 数据库表（v0.1 草案）

仅作起点，落地时按实际需要演进：

- `conversations`：id / title / created_at / updated_at
- `messages`：id / conversation_id / role(user/assistant/tool) / content / tool_calls(jsonb) / reasoning(text 可空) / created_at
- `tool_invocations`：id / message_id / tool_name / args(jsonb) / result(jsonb) / latency_ms / status

**未来留位（不在 v0.1 实现）**：`users`、`attachments`、`embeddings`。

### 3.4 Agent 与工具

- **运行时**：Eino 的 ReAct Agent（参考 `flow/agent/react`，以官方仓库最新 API 为准）。
- **工具注册**：
  - `web_search(query, top_k)`：调用 Tavily / Brave Search 免费档；返回标题 + URL + 摘要。
  - `fetch_url(url)`：抓取网页正文，做基础正文抽取（可选 readability 库），返回纯文本。
- **流式策略**：把 Eino 的 stream 输出转写为 SSE 事件流，事件类型至少包含：
  - `delta`（assistant 文本增量）
  - `reasoning`（思考过程增量，模型支持时透传）
  - `tool_call`（工具调用开始）
  - `tool_result`（工具结果）
  - `done` / `error`

> Eino API 细节（`compose.NewChain` / `compose.ToolsNode` / `react.NewAgent` 等具体名字与签名）以官方仓库当前版本为准；下笔编码时务必先读源码与示例，不要凭记忆写。

---

## 4. 12 周里程碑

| 阶段 | 周次 | 核心目标 | 可见产出 |
|------|------|----------|----------|
| **地基期** | W1-W2 | 项目骨架 + DeepSeek 直连 + 最小 SSE 跑通 | `docker compose up` 起 PG + backend + web；浏览器问"你好"，SSE 流式返回 DeepSeek 文本 |
| **MVP 期 (前半)** | W3-W4 | Eino Agent + 1 个工具 + 多会话持久化 | **W4 末检查点**：能新建/切换会话；问"今天纳指多少点"会触发 web_search 并返回带引用的回答 |
| **MVP 期 (后半)** | W5-W6 | 第二个工具 fetch_url + 思考过程展示 + 错误/重试/取消 + Markdown/Code 体验打磨 | **W6 末 MVP**：完整 ChatGPT 雏形（无文件上传 / 无模型切换） |
| **能力期** | W7-W8 | Agent 高阶（多步推理、tool 失败重试、stream 中间事件）+ prompt 模板系统（系统 prompt / 角色） | 同代码可切换"通用助手 / 编程助手 / 翻译"等不同角色 |
| **工程化期** | W9-W10 | 可观测性（结构化日志 + 调用链）+ 评测脚本（自动跑一组 case 集）+ Go 代码风格重构 | 一次提交可跑评测脚本输出"指标对比"；后端代码按 internal 分层收敛 |
| **产品化期** | W11-W12 | 界面打磨 + RAG 入门 demo（pgvector + 单文档问答） + 体验回归 | 一个**自己每天会用**的本地 AI 聊天助手；RAG 能跑最简链路（不上生产） |

每两周一次复盘：跑了什么、卡了什么、`BLOCKED.md` 还剩什么、是否调整下两周。

---

## 5. Day 1 行动清单

**目标**：跑通最小骨架——`docker compose up` 一起起 Postgres + backend + web，所有服务健康。

1. 在仓库根新建 `backend/`，`go mod init` + 加入 Gin、GORM、pgx 驱动、Eino。
2. `docker-compose.yml` 编排：`postgres:16` + `backend`（host build 或挂载）+ `web`（开发模式可先在本地直接 `pnpm dev`，不一定塞进 compose）。
3. `backend/cmd/server/main.go` 起 `/api/health`，连一次 PG 验证连通。
4. 在 `web/` 中加一个最简页面，调 `/api/health` 把结果显示出来。
5. 写一个最小的 `/api/chat` 测试端点：**直接调 DeepSeek**（先不上 Eino），把 token 流以 SSE 发给前端；前端用 ai-elements 的 `Conversation/Message` 渲染。

**Day 1 严禁**：不碰 Eino Agent、不碰多会话表结构、不碰工具实现。**地基不稳前不上业务。**

---

## 6. Week 1 周计划（5 × 3h + 2 × 8h ≈ 31h）

| 时间 | 任务 |
|------|------|
| 周一 9-12 | Day 1 骨架（见第 5 节） |
| 周二 9-12 | PG schema 第一版：`conversations` + `messages`；GORM model + 简单 list/create endpoint |
| 周三 9-12 | 把 Day 1 的 `/api/chat` 接 PG：消息落库 + 历史读回；前端会话只显示一条 |
| 周四 9-12 | SSE 通道完善：失败重连、客户端中断、`done`/`error` 事件；用 ai-elements 的 streaming 体验对齐 |
| 周五 9-12 | 引入 Eino：把直连 DeepSeek 改成走 Eino 的 ChatModel；**还不接 Agent/Tool**，仅替换底层 |
| 周末 16h | 多会话前端壳：会话列表、新建/切换；后端补会话 CRUD；周日 14-18 buffer 处理 `BLOCKED.md` |

**Week 1 完成标志**：`docker compose up` → 浏览器打开 → 新建会话 → 输入消息 → SSE 流式返回 → 关闭页面再打开历史还在。**链路长度优先于质量。**

---

## 7. 防卡死机制

### 7.1 单 bug 2h 止损规则
- 任何 bug 卡超 2h 必须切换任务。
- 把现象、假设、已尝试方法写入 `BLOCKED.md`。
- 杜绝"再花 30 分钟就能解决"循环。

### 7.2 周日 14:00-18:00 buffer
- 专门处理 `BLOCKED.md`。
- 解决的转入 `LEARNED.md`（未来面试讲故事的素材库）。
- 没问题就用来做"复述测试"或回顾重构。

### 7.3 每两周复盘
- 里程碑对齐 → `BLOCKED.md` 清理 → 下两周微调。

### 7.4 心理预案
- **W3-W4** 把 Eino Agent + SSE + 多会话三件并起来时容易乱套——预期内，遇到就拆开单跑、最小复现。
- **W5-W6 体验打磨期容易"看着没产出"**——其实最值钱，别因为缺新功能就跳走。
- **W8-W9 容易出现"项目迷茫期"**——demo 能跑了但不惊艳。**不要换项目**，去补 Eino 高阶用法和 Go 工程化。
- **12 周内严禁技术栈替换冲动**：不换 Hertz / Rust / 其他 Agent 框架；不重新引入 Python。

---

## 8. AI 协作规则（简版）

| 档位 | 模块举例 | 怎么写 |
|------|---------|--------|
| **A 档（核心，纯手写）** | Eino Agent 装配、SSE 事件协议设计、Tool 接口与错误处理风格、PG schema 演进 | 自己手写，AI 只能问概念 |
| **B 档（重要，AI 起草 + 逐行重写）** | Gin handler、GORM model、tool 实现、prompt 模板、评测脚本 | AI 起草，自己重写一遍，禁止粘贴 |
| **C 档（样板，AI 直接生成）** | docker-compose、Next.js 页面骨架、CRUD 第一版、单测样板、**前端全部代码（已 4 年经验）** | AI 直接写，跑通即可 |

铁律：
1. 每个后端模块**第一次**写时强制 A/B 档；前端例外。
2. **debug 不许全交给 AI**：自己看 5-10 分钟形成假设，再带假设去问。
3. **每周日做"复述测试"**：随机挑本周一个后端模块，关掉 AI 重写一遍。
4. AI 是 rubber duck + 文档检索器，不是代码生产者。
5. **L1 决策层 100% 自己**，L2 实现层按学习目标分档，L3 样板层放心给 AI。

---

## 9. 风险清单与对策

| 风险 | 何时出现 | 对策 |
|------|----------|------|
| Eino 文档/示例覆盖不全 | 全程 | 直接读 `cloudwego/eino` 仓库源码与 examples；遇坑写入 `LEARNED.md` |
| SSE 在反向代理 / 浏览器边缘 case 行为怪 | W2-W4 | 自己手写最小 SSE demo 对照验证；不要用任何"魔法封装" |
| ReAct Agent 死循环（反复调同一工具） | W3-W6 | Agent 加最大步数限制；工具结果带显式终止信号；流式输出兜底超时 |
| DeepSeek API 限流 / 偶发错误 | 全程 | 实现统一的重试 + 指数退避；前端把错误事件透出来不要静默 |
| `web_search` 免费档配额耗尽 | W3 起 | 接两家备选（Tavily/Brave），加本地缓存表 `tool_invocations` 复用同 query |
| `fetch_url` 抓到 JS 渲染页面 | W5 | v0.1 只做静态 HTML 抽取；动态页直接放弃，回写 tool_result 错误 |
| 多会话表结构后期反复改 | W3-W6 | 用 migration 工具（如 goose / atlas）从 Day 1 引入，避免手工 ALTER |
| 公司项目占用工作日时间 | 不定期 | 工作日 9-12 是私人时段（已确认）；公司任务排到下午 |
| 中途想换技术栈 / 换项目 | W4-W9 | 翻本文档第 1/7 节——已锁，不讨论 |
| AI 写代码"看得懂但不会写" | 全程 | 周日复述测试；遵守第 8 节 |

---

## 10. 合规与免责声明

- 本工具仅供个人学习与个人使用，不对外提供服务。
- LLM 输出可能存在事实性错误与幻觉，任何关键结论需人工核对。
- 引入第三方搜索 / 抓取 API 前，先阅读其 ToS 与配额政策，避免商用前未读条款。
- 抓取网页（`fetch_url`）须遵守 robots.txt 与目标站点条款。

---

## 11. 决策变更记录

> 如确实需要变更某项决策，必须在此处记录"原决策 / 新决策 / 变更原因 / 变更日期"。
> 仅作记录用途，**不豁免锁定原则**——只有出现重大现实变化才考虑变更。

| 日期 | 项目 | 原决策 | 新决策 | 原因 |
|------|------|--------|--------|------|
| - | - | - | - | - |

---

**本文档锁定日期**：项目启动日（写入 Day 1 提交）。
**下一次允许复审**：第 6 周 MVP 节点。
