# AI 投资助手 · 学习与执行总纲（PLAN.md）

> 本文档由一次完整的"决策树拷问"沉淀而来。  
> 所有决策都不是"标准答案"，而是基于本人真实背景、动机、约束、技术偏好做的对齐结果。  
> 12 周内，所有"想换方向 / 换栈 / 换项目"的冲动，都先来这里查一遍——决策已锁，不再讨论。

---

## 0. 个人背景与目标

- **背景**：4 年前端经验；后端只学过基础语法，了解 SQL/NoSQL/ORM/Docker 但无实操；公司全栈项目可参与（前端 React + 后端 Go + MySQL + 内部框架）。
- **可投入时间**：工作日 9:00-12:00（完全自由的个人项目时段，共 15h/周）+ 周末 8h × 2（共 16h/周）= **31h/周**。
- **学习动机**：
  - **B（转型全栈/AI 工程师）** + **C（副业/独立开发者）**
  - **C 优先**：先做出能跑的端到端产品；产品倒逼补 B（系统后端能力）。

---

## 1. 战略决策摘要（20 项，已锁）

| # | 决策项 | 结论 |
|---|--------|------|
| 1 | 学习动机 | B（转型全栈/AI 工程师）+ C（副业/独立开发者） |
| 2 | 优先级 | **C 优先**（先做产品），产品倒逼补 B |
| 3 | 项目策略 | 双轨：公司 Go 项目当"问题图鉴"，个人项目端到端主导 |
| 4 | 后端语言架构 | **Go（业务+数据）+ Python（Agent 工作流）**，gRPC 通信 |
| 5 | Python Agent 粒度 | 中等（持有 LangGraph 状态，所有持久化通过 RPC 回调 Go） |
| 6 | 第一个项目 | **AI 投资助手** |
| 7 | 范围切法 | v0.1 单公司深度分析 → v0.2 自选股监控 |
| 8 | 持仓覆盖 | v0.1 先做 1-2 家走深，再扩展到 6 家 |
| 9 | 市场范围 | 美股 4（苹果/拼多多/联合健康/阿里 ADR）+ 港股 2（腾讯/泡泡玛特） |
| 10 | 起步公司 | **苹果（SEC 路径）+ 腾讯（港交所 PDF 路径）** |
| 11 | 分析深度 | v0.1 整体分析（公司层面），分部分析放 v0.3 |
| 12 | v0.1 宽度 | 双家起步，被迫做数据源接口抽象 |
| 13 | 节奏预期 | **第 4 周末必须出 demo**，先链路通再优化 |
| 14 | 学习时段 | 工作日 9-12 点 + 周末 8h × 2 = 31h/周 |
| 15 | 工作日时段属性 | 完全自由用于个人项目 |
| 16 | 技术栈策略 | 锁死大方向 |
| 17 | 前端 + 通信 | Next.js 保留 + gRPC day 1 就上 |
| 18 | 时间分配 | **B 项目驱动派**：项目 55% / Agent 20% / 通用基础 15% / Go 工程化 10% |
| 19 | 防卡死机制 | A（2h 止损）+ B（周日下午 buffer） |
| 20 | 免费数据栈 | 锁死（SEC + 披露易 + akshare + yfinance + Finnhub + RSS） |

---

## 2. 技术栈（锁定，不再讨论）

```
前端:        Next.js (React)
Go 框架:     Gin
ORM:         GORM
数据库:      PostgreSQL + pgvector (镜像建议: pgvector/pgvector:pg16)
Python 服务: 纯 gRPC server（grpcio + grpcio-tools，不引入 FastAPI/HTTP 框架）
Agent 编排:  LangGraph
通信:        gRPC（Day 1 就上，使用 protobuf）
容器化:      Docker + Docker Compose
部署:        v0.x 本地，不上线
LLM:         自定（OpenAI / Anthropic / DeepSeek 任选，建议从便宜的模型开始）
```

**MySQL 改为 PostgreSQL 的关键原因**：pgvector 让"关系数据 + 向量数据"在同一个数据库里，部署复杂度大幅下降。

---

## 3. 项目架构

### 3.1 服务划分

```
[Next.js 前端] ──HTTP──▶ [Go 服务（业务+数据）] ──gRPC──▶ [Python Agent 服务（LangGraph）]
                                  │                              │
                                  ▼                              │
                          [PostgreSQL+pgvector]  ◀── gRPC 回调 ──┘
```

- **Go 服务**：API 网关、用户/自选股/缓存数据持久化、所有外部数据源接入（SEC/披露易/yfinance/akshare/Finnhub）。
- **Python 服务**：薄层 Agent 服务，**持有 LangGraph 运行时状态**（短期记忆、checkpoint），但所有需要持久化的数据（聊天归档、向量、原始财报）都通过 gRPC 回调 Go 来读写。
- **前端**：Next.js 仅作 SSR + 客户端壳，**所有 API 一律走 Go**，绝不在 Next.js 写后端逻辑。

### 3.2 数据源接口抽象（核心训练点）

从 Day 1 起，Go 端必须有：

```go
type DataSource interface {
    FetchLatestFilings(ctx context.Context, symbol string) (*Filings, error)
    // 其余方法在第 5-6 周接入腾讯 PDF 时主动重构
}
```

第 5-6 周接入腾讯港股 PDF 时，会主动重构这个 interface——这是 Go 工程化的核心训练场景。

### 3.3 持仓清单（v0.1 配置在数据库里，不要硬编码）

| 公司 | 代码 | 上市地 | 数据源 |
|------|------|--------|--------|
| 苹果 | AAPL | 美股 | SEC EDGAR |
| 拼多多 | PDD | 美股 | SEC EDGAR (20-F) |
| 联合健康 | UNH | 美股 | SEC EDGAR |
| 阿里 | BABA | 美股（ADR）| SEC EDGAR（**走美股**，规避港股 PDF）|
| 腾讯 | 0700.HK | 港股 | 港交所披露易 PDF |
| 泡泡玛特 | 9992.HK | 港股 | 港交所披露易 PDF |

---

## 4. 免费数据栈（锁定）

| 数据类型 | 美股（4 家） | 港股（2 家） |
|----------|-------------|-------------|
| 财报原文 | **SEC EDGAR API** | 港交所披露易爬虫 |
| 行情 | yfinance / Finnhub 免费档 | akshare（覆盖港股大盘股 OK） |
| 公告 | SEC Filings RSS | 披露易 + 公司 IR RSS |
| 新闻 | Finnhub News + Google News RSS | akshare 港股新闻 + Google News RSS |
| 政策 | Fed RSS | 证监会 + 发改委 + 工信部 RSS |
| 研报评级 | **不做**（v0.1 不碰，避免合规风险与同质化） |

**关键提醒**：
1. SEC EDGAR rate limit 是 10 req/s，需要在 User-Agent 加邮箱标识。
2. **Day 1 就要设计本地缓存层**（`raw_filings` 表），Agent 永远从本地读。
3. 数据源生态变化快，落地前自己验证最新状态。

---

## 5. 12 周里程碑

| 阶段 | 周次 | 核心目标 | 可见产出 |
|------|------|----------|----------|
| **地基期** | W1-W2 | 项目骨架 + 数据源 interface 抽象 + Hello World 全链路 | `docker compose up` 起 4 件套，最小 gRPC 调用跑通 |
| **拼装期** | W3-W4 | 苹果 SEC 数据 → LangGraph 分析 → 报告输出 | **W4 末苹果第一份 AI 分析报告**（粗糙但端到端跑通） |
| **重构期** | W5-W6 | 加腾讯港股 PDF 路径，主动重构 DataSource interface | 苹果 + 腾讯两家都能输出报告 |
| **能力期** | W7-W8 | 行业模板 + LangGraph 多 Agent 协作 + 评测机制 | 同代码跑出"科技/互联网/医疗/消费"多种行业风格 |
| **扩展期** | W9-W10 | 扩展到 6 家全覆盖 + 阿里走 BABA SEC 路径 | 6 家持仓全部能出报告 |
| **优化期** | W11-W12 | 报告质量优化 + 前端 demo + v0.2 自选股监控雏形 | 一份**真的会用来辅助投资决策**的工具 |

每两周一次复盘：跑了什么、卡了什么、`BLOCKED.md` 还剩什么、是否调整下两周。

---

## 6. 时间分配（B 项目驱动派 · 已按"知识点都见过"的实际起点校准）

| 维度 | 占比 | 时间/周 | 内容 |
|------|------|---------|------|
| 项目实战 | **55%** | 17h | 写代码、debug、跑链路 |
| Agent / LangGraph | **20%** | 6.2h | state / checkpoint / 工具调用 / 多 Agent / 投资分析 prompt |
| 后端通用基础 | **15%** | 4.65h | gRPC 实操 + pgvector + Docker Compose 多服务编排 |
| Go 工程化 | **10%** | 3.1h | 读优秀开源项目（如 go-clean-arch、Hertz、Kratos）学风格 |

**Go 砍到 10% 的理由**：你已了解语法，剩下的是"模式"，公司项目（Go 后端）等于免费多了 40h/周隐性 Go 学习场景。

---

## 7. 项目目录结构（建议）

```
ai-investment-assistant/
├── backend/             # Go 服务（Gin + GORM + gRPC server）
│   ├── go.mod
│   └── ...
├── agent/               # Python 服务（FastAPI + LangGraph + gRPC client/server）
│   └── ...
├── web/                 # Next.js
├── proto/               # .proto 定义（双端 codegen）
├── docker-compose.yml   # postgres + backend + agent + web
├── PLAN.md              # 本文件（决策与计划主图）
├── BLOCKED.md           # 卡住的问题（2h 止损后写入这里）
├── LEARNED.md           # 已解决问题/笔记（面试故事素材库）
├── AI_USAGE.md          # AI 协作规则（见第 9 节）
└── README.md
```

---

## 8. 防卡死机制

### 8.1 单 bug 2h 止损规则
- 任何 bug 卡超 2h 必须切换任务。
- 把现象、假设、已尝试方法写入 `BLOCKED.md`。
- 杜绝"再花 30 分钟就能解决"循环。

### 8.2 周日 14:00-18:00 buffer
- 专门处理 `BLOCKED.md`。
- 解决的转入 `LEARNED.md`（这是未来面试讲故事的素材库）。
- 没问题就用来做"复述测试"（见第 9 节）或回顾重构。

### 8.3 每两周复盘
- 里程碑对齐 → 配比微调 → `BLOCKED.md` 清理。

### 8.4 心理预案
- **W5-W6（PDF 解析）会非常痛苦**——预期内，不是你的问题。
- **W8-W9 容易出现"项目迷茫期"**——demo 能跑了但不惊艳。**不要换项目**，去补 LangGraph 高阶用法和 Go 工程化。
- **12 周内严禁技术栈替换冲动**：不换 Rust / Bun / Effect / 其他 Agent 框架。

---

## 9. AI 协作规则（详见 `AI_USAGE.md`）

### 9.1 三档分级

| 档位 | 模块举例 | 怎么写 |
|------|---------|--------|
| **A 档（核心，纯手写）** | DataSource interface、LangGraph state 设计、Go 错误处理风格、gRPC service 定义 | **自己手写**，AI 只能问概念 |
| **B 档（重要，AI 起草 + 逐行重写）** | Gin handler、GORM model、PDF 解析、prompt 设计、报告模板 | **AI 起草，你重写一遍**，禁止粘贴 |
| **C 档（样板，AI 直接生成）** | docker-compose、Next.js 页面骨架、CRUD 第一版、单测样板、proto 首版、**前端全部代码（已 4 年经验，不再是学习目标）** | **AI 直接写**，跑通即可 |

### 9.2 五条铁律

1. 每个模块**第一次**写时强制 A/B 档，建立肌肉记忆后才允许 C 档（**前端除外，已 4 年经验，全部交给 AI**）。
2. **debug 不许全交给 AI**：自己看 5-10 分钟形成假设，再带假设去问 AI。
3. **每周日做"复述测试"**：随机挑本周一个模块，关掉 AI 重写一遍。
4. **AI 是 rubber duck + 文档检索器**，不是代码生产者。
5. **L1 决策层 100% 自己**，L2 实现层按学习目标分档，L3 样板层放心给 AI。

### 9.3 12 周 AI 强度曲线

| 阶段 | 强度 | 原因 |
|------|------|------|
| W1-W2 地基期 | **低** | 建立肌肉记忆，骨架必须自己懂 |
| W3-W4 拼装期 | **中** | 进度压力大，AI 帮过 boilerplate |
| W5-W6 重构期 | **低** | 重构是核心学习场景 |
| W7-W8 能力期 | **中** | LangGraph 高阶 + 行业模板，AI 帮试错 |
| W9-W10 扩展期 | **高** | 同质化扩展（剩 4 家），AI 加速合理 |
| W11-W12 优化期 | **中** | 决策为主，AI 执行 |

---

## 10. Day 1 行动清单

**目标**：跑通最小的"hello world × 4 件套"——`docker compose up` 一起起 Postgres / Go / Python / Next.js，所有服务都健康。

1. `docker-compose.yml` 起 Postgres（`pgvector/pgvector:pg16`）。
2. Go：`go mod init`，加 Gin，跑 `/health`。
3. Python：用 `uv` 或 `poetry`，加 FastAPI，跑 `/health`。
4. `proto/agent.proto` 定义最简 RPC（`Ping`），双端 codegen。
5. Next.js `create-next-app`，写一个调 Go `/health` 的页面。
6. **全部 docker-compose up 一起跑通**（不要单独跑）。

**Day 1 严禁做的事**：不碰 SEC API、不碰 LangGraph、不碰真实业务模型。地基不稳前不上业务。

---

## 11. Week 1 周计划（5×3h + 2×8h = 31h）

| 时间 | 任务 |
|------|------|
| 周一 9-12 | Day 1 骨架（见第 10 节） |
| 周二 9-12 | Postgres：设计 `watchlist`（自选股配置）+ `raw_filings`（缓存表）；GORM model + 简单 CRUD endpoint |
| 周三 9-12 | gRPC 双向跑通：Go ↔ Python 互相调一次，确认 codegen 流程 |
| 周四 9-12 | 写 **DataSource interface** 第一版 + 实现一个 mock 数据源 |
| 周五 9-12 | mock 数据从 Go 经 gRPC → Python → LangGraph 最小图（一个 LLM 节点）→ 输出"假报告" |
| 周末 16h | SEC EDGAR API 实操：拉到苹果最新 10-Q 元数据 + 任一财务字段，落进 `raw_filings`；周日 14-18 buffer |

**Week 1 完成标志**：终端 `docker compose up` → 浏览器打开 Next.js 页面 → 点按钮 → Go → gRPC → Python → LLM → 返回 → 页面显示"hello world 级 Apple 分析"。**链路长度优先于质量**。

---

## 12. 风险清单与对策

| 风险 | 何时出现 | 对策 |
|------|----------|------|
| 数据源 rate limit / 反爬 | W3 起 | Day 1 建本地缓存层；遵守官方限速 |
| PDF 解析（腾讯/泡泡玛特）卡死 | W5-W6 | 预期内，提前心理准备；2h 止损 + buffer |
| LangGraph state 设计错误导致回滚 | W4 起 | 第 4 周末第一份报告"粗糙"是预期 |
| 公司项目占用工作日时间 | 不定期 | 工作日 9-12 是私人时段（已确认）；公司任务排到下午 |
| 持仓变化（卖了某只票） | 不定期 | `watchlist` 是数据库配置，非硬编码 |
| 中途想换技术栈 | W4-W8 | 翻本文档第 1/2 节——已锁，不讨论 |
| 中途想换项目 | W8-W9 迷茫期 | 翻本文档第 8.4 节——不要换 |
| AI 写代码"看得懂但不会写" | 全程 | 周日复述测试；遵守第 9 节五条铁律 |

---

## 13. 合规与免责声明

- 本工具**仅供个人投资决策辅助使用**，不对外提供服务；如未来上线给他人用，需先评估投资咨询牌照与合规要求。
- LLM 输出可能有数字错误、单位错误、事实幻觉，**任何金额、比率、结论必须人工核对原始财报**。
- 工具的定位是 **"辅助分析"**，不是 **"替你做决策"**。
- 数据源 ToS 必须遵守，禁止商用前未读条款。

---

## 14. 决策变更记录

> 如确实需要变更某项决策，必须在此处记录"原决策 / 新决策 / 变更原因 / 变更日期"。  
> 仅作记录用途，**不豁免锁定原则**——只有出现重大现实变化（如持仓清空、公司项目切走）才考虑变更。

| 日期 | 项目 | 原决策 | 新决策 | 原因 |
|------|------|--------|--------|------|
| - | - | - | - | - |

---

**本文档锁定日期**：项目启动日（写入 Day 1 提交）。  
**下一次允许复审**：第 6 周复盘节点。
