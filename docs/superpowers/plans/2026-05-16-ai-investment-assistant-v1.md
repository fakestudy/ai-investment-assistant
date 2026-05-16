# AI 投资助手 v1 实施计划

> **For agentic workers / 给 agentic workers：** REQUIRED SUB-SKILL：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按任务逐步实现本计划。步骤使用 checkbox（`- [ ]`）语法追踪进度。

**Goal / 目标：** 构建一个可本地部署、AI 优先的美股研究工作台，包含登录、手动自选股、行情/事件采集、AI 研究卡片、上下文对话、站内通知和高优先级 Lark 推送。

**Architecture / 架构：** 使用 monorepo：Next.js App Router Web 应用、Go HTTP BFF、Go gRPC 业务服务、Python LangGraph Agent Service、PostgreSQL 持久化，以及 Docker Compose 本地部署。前端只通过 HTTP 调用 BFF；BFF 和 worker 通过 gRPC 调用内部服务；Go 后端只通过 protobuf 契约依赖 Agent Service。

**Tech Stack / 技术栈：** Next.js、React、TypeScript、TanStack Query、Tailwind CSS、Recharts、Go 1.26、grpc-go、pgx、Goose 风格 SQL migration、Python 3.12、LangGraph、LangChain、Pydantic、DeepSeek 兼容 chat completions、PostgreSQL 16、Docker Compose。

---

## 实施决策

- **React 框架：** 使用 Next.js App Router。v1 仍然把业务 API 放在 Go BFF 中，Next.js 只负责 Web 工作台渲染、路由和前端构建；需要浏览器状态的工作台组件使用 client component。
- **Go 目录：** 所有 Go 服务放在同一个 `backend` module 中，方便复用生成的 protobuf 代码、平台工具和服务测试。
- **gRPC 生成：** 使用 Buf 从 `proto/investment/v1` 生成 Go 和 Python protobuf/gRPC 代码。
- **行情 provider 顺序：** 先实现 `mock` provider，保证测试确定性；再实现第一个真实 adapter：`alpha_vantage`。Alpha Vantage 官方提供 ticker search、global quote、daily candles、news/sentiment 等接口；UI 必须展示数据来源和延迟标记。
- **Redis：** 不放入第一条跑通链路。先用 PostgreSQL 跑通，Redis 只在后续作为缓存、锁、限流和短期状态补充。
- **聊天流式输出：** v1 使用非流式聊天。BFF response DTO 保持可演进形状，后续加 streaming 时不改变已存储消息结构。
- **合规边界：** 每张研究卡片和每条 AI 回答都包含固定免责声明，并且不输出买入、卖出、加仓、减仓等交易指令。

## 文件结构

创建以下结构：

```text
.
├── apps/web
│   ├── Dockerfile
│   ├── eslint.config.mjs
│   ├── next.config.ts
│   ├── package.json
│   ├── postcss.config.mjs
│   ├── app
│   │   ├── globals.css
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   └── providers.tsx
│   ├── components/Disclaimer.tsx
│   ├── features/ai/ChatPanel.tsx
│   ├── features/auth/LoginPage.tsx
│   ├── features/dashboard/Workbench.tsx
│   ├── features/notifications/NotificationBell.tsx
│   ├── features/research/ResearchCard.tsx
│   ├── features/stocks/StockDetail.tsx
│   ├── features/watchlist/WatchlistPanel.tsx
│   ├── lib/api/client.ts
│   ├── test/setup.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   └── vitest.config.ts
├── backend
│   ├── Dockerfile
│   ├── cmd
│   │   ├── bff/main.go
│   │   ├── event-service/main.go
│   │   ├── market-data-service/main.go
│   │   ├── notification-service/main.go
│   │   ├── research-service/main.go
│   │   ├── scheduler-worker/main.go
│   │   ├── user-service/main.go
│   │   └── watchlist-service/main.go
│   ├── go.mod
│   ├── internal
│   │   ├── bff/server.go
│   │   ├── config/config.go
│   │   ├── platform/auth/jwt.go
│   │   ├── platform/httpjson/httpjson.go
│   │   ├── platform/postgres/postgres.go
│   │   └── service
│   │       ├── event
│   │       ├── marketdata
│   │       ├── notification
│   │       ├── research
│   │       ├── user
│   │       └── watchlist
│   └── gen/go
├── db/migrations/0001_init.sql
├── docs/decisions/0001-v1-stack.md
├── infra/docker-compose.yml
├── proto/investment/v1
│   ├── agent.proto
│   ├── common.proto
│   ├── event.proto
│   ├── market.proto
│   ├── notification.proto
│   ├── research.proto
│   ├── user.proto
│   └── watchlist.proto
├── services/agent
│   ├── Dockerfile
│   ├── app
│   │   ├── graphs/event_analysis.py
│   │   ├── graphs/question_answer.py
│   │   ├── graphs/watchlist_summary.py
│   │   ├── providers/deepseek.py
│   │   ├── schemas.py
│   │   └── server.py
│   ├── pyproject.toml
│   └── tests
├── .env.example
├── .gitignore
├── Makefile
├── buf.gen.yaml
├── buf.yaml
├── package.json
└── pnpm-workspace.yaml
```

## 任务 1：Monorepo 骨架

**文件：**
- 创建：`.gitignore`
- 创建：`.env.example`
- 创建：`package.json`
- 创建：`pnpm-workspace.yaml`
- 创建：`Makefile`
- 创建：`docs/decisions/0001-v1-stack.md`

- [ ] **步骤 1：创建根目录配置文件**

```json
{
  "name": "ai-investment-assistant",
  "private": true,
  "scripts": {
    "build": "pnpm --filter web build",
    "test": "pnpm --filter web test && make test-go && make test-agent",
    "lint": "pnpm --filter web lint",
    "dev:web": "pnpm --filter web dev"
  },
  "devDependencies": {
    "typescript": "^5.9.0"
  },
  "packageManager": "pnpm@10.0.0"
}
```

```yaml
packages:
  - apps/*
```

```gitignore
.DS_Store
.env
.env.local
node_modules
dist
.next
coverage
.venv
__pycache__
*.pyc
backend/gen
services/agent/app/gen
tmp
log/*.log
```

```env
APP_ENV=local
DATABASE_URL=postgres://investment:investment@postgres:5432/investment?sslmode=disable
JWT_SECRET=local-dev-secret-32-characters-min
SESSION_TTL_HOURS=24
EMAIL_ALLOWLIST=owner@example.com
INITIAL_USER_EMAIL=owner@example.com
INITIAL_USER_PASSWORD=local-password-123
MARKET_PROVIDER=mock
ALPHA_VANTAGE_API_KEY=demo
DEEPSEEK_API_KEY=local-deepseek-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
FEISHU_WEBHOOK_URL=
POLL_INTERVAL_SECONDS=300
BFF_HTTP_ADDR=:8080
USER_GRPC_ADDR=user-service:9001
WATCHLIST_GRPC_ADDR=watchlist-service:9002
MARKET_GRPC_ADDR=market-data-service:9003
EVENT_GRPC_ADDR=event-service:9004
RESEARCH_GRPC_ADDR=research-service:9005
NOTIFICATION_GRPC_ADDR=notification-service:9006
AGENT_GRPC_ADDR=agent-service:9010
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080
```

- [ ] **步骤 2：添加开发命令**

```makefile
.PHONY: proto test-go test-agent compose-up compose-down migrate

proto:
	buf generate

test-go:
	cd backend && go test ./...

test-agent:
	cd services/agent && python -m pytest -q

compose-up:
	docker compose --env-file .env.example -f infra/docker-compose.yml up --build

compose-down:
	docker compose --env-file .env.example -f infra/docker-compose.yml down -v

migrate:
	psql "$$DATABASE_URL" -f db/migrations/0001_init.sql
```

- [ ] **步骤 3：记录技术栈决策**

```markdown
# 决策 0001：v1 技术栈

v1 使用 Next.js App Router 构建 Web 工作台，Go 构建 BFF 和内部 gRPC 服务，Python 构建 LangGraph Agent Service，PostgreSQL 做持久化，Docker Compose 做本地部署。

选择 Next.js 的原因是：它提供稳定的 App Router、成熟的生产构建和 Docker standalone 输出；产品仍然统一由 Go BFF 提供业务 API，Next.js 不承载后端业务逻辑。Go 服务共享 `backend` 下的一个 module，以复用生成的 protobuf 代码和平台工具。Python Agent Service 独立出来，因为 LangGraph 和 LangChain 以 Python 生态为主。

第一个行情 provider 是 `mock`，用于确定性开发和测试。第一个真实 adapter 是 `alpha_vantage`；provider 特有 payload 留在 `marketdata` adapter 内部，所有 UI 都展示数据来源和延迟数据标记。

Redis 不进入第一条可运行链路。PostgreSQL 存储持久数据、重试状态、通知和聊天历史。
```

- [ ] **步骤 4：验证根目录环境**

运行：`pnpm --version && node --version && go version && python3 --version`

预期：所有命令都打印版本，并以 `0` 退出。

- [ ] **步骤 5：提交**

```bash
git add .gitignore .env.example package.json pnpm-workspace.yaml Makefile docs/decisions/0001-v1-stack.md
git commit -m "chore: scaffold investment assistant monorepo"
```

## 任务 2：Protobuf 契约与代码生成

**文件：**
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
- 生成：`services/agent/app/gen`

- [ ] **步骤 1：配置 Buf**

```yaml
version: v2
modules:
  - path: proto
lint:
  use:
    - STANDARD
breaking:
  use:
    - FILE
```

```yaml
version: v2
plugins:
  - remote: buf.build/protocolbuffers/go
    out: backend/gen/go
    opt:
      - paths=source_relative
  - remote: buf.build/grpc/go
    out: backend/gen/go
    opt:
      - paths=source_relative
  - remote: buf.build/protocolbuffers/python
    out: services/agent/app/gen
  - remote: buf.build/grpc/python
    out: services/agent/app/gen
```

- [ ] **步骤 2：定义共享消息**

```proto
syntax = "proto3";

package investment.v1;

option go_package = "github.com/local/ai-investment-assistant/backend/gen/go/investment/v1;investmentv1";

message ErrorDetail {
  string code = 1;
  string message = 2;
  map<string, string> metadata = 3;
}

message Source {
  string title = 1;
  string url = 2;
  string publisher = 3;
  string published_at = 4;
  string provider = 5;
}

message PageContext {
  string route = 1;
  string symbol = 2;
  string event_id = 3;
  string research_card_id = 4;
}

enum Priority {
  PRIORITY_UNSPECIFIED = 0;
  PRIORITY_LOW = 1;
  PRIORITY_MEDIUM = 2;
  PRIORITY_HIGH = 3;
}

enum ResearchStance {
  RESEARCH_STANCE_UNSPECIFIED = 0;
  RESEARCH_STANCE_BULLISH = 1;
  RESEARCH_STANCE_BEARISH = 2;
  RESEARCH_STANCE_NEUTRAL = 3;
  RESEARCH_STANCE_MIXED = 4;
}

enum Confidence {
  CONFIDENCE_UNSPECIFIED = 0;
  CONFIDENCE_LOW = 1;
  CONFIDENCE_MEDIUM = 2;
  CONFIDENCE_HIGH = 3;
}
```

- [ ] **步骤 3：定义服务契约**

`user.proto`:

```proto
syntax = "proto3";

package investment.v1;

option go_package = "github.com/local/ai-investment-assistant/backend/gen/go/investment/v1;investmentv1";

service UserService {
  rpc Login(LoginRequest) returns (LoginResponse);
  rpc GetUser(GetUserRequest) returns (User);
}

message LoginRequest {
  string email = 1;
  string password = 2;
}

message LoginResponse {
  User user = 1;
  string access_token = 2;
  string expires_at = 3;
}

message GetUserRequest {
  string user_id = 1;
}

message User {
  string id = 1;
  string email = 2;
  string status = 3;
}
```

`market.proto`:

```proto
syntax = "proto3";

package investment.v1;

import "investment/v1/common.proto";

option go_package = "github.com/local/ai-investment-assistant/backend/gen/go/investment/v1;investmentv1";

service MarketDataService {
  rpc ResolveSymbol(ResolveSymbolRequest) returns (MarketSymbol);
  rpc GetQuote(GetQuoteRequest) returns (MarketQuote);
  rpc GetCandles(GetCandlesRequest) returns (GetCandlesResponse);
  rpc GetCompanyInfo(GetCompanyInfoRequest) returns (CompanyInfo);
  rpc GetNews(GetNewsRequest) returns (GetNewsResponse);
}

message ResolveSymbolRequest { string query = 1; }
message GetQuoteRequest { string symbol = 1; }
message GetCandlesRequest { string symbol = 1; string range = 2; }
message GetCompanyInfoRequest { string symbol = 1; }
message GetNewsRequest { string symbol = 1; int32 limit = 2; }

message MarketSymbol {
  string symbol = 1;
  string exchange = 2;
  string name = 3;
  string currency = 4;
}

message MarketQuote {
  string symbol = 1;
  double price = 2;
  double change = 3;
  double change_percent = 4;
  string market_time = 5;
  bool delayed = 6;
  string provider = 7;
}

message Candle {
  string timestamp = 1;
  double open = 2;
  double high = 3;
  double low = 4;
  double close = 5;
  double volume = 6;
  bool adjusted = 7;
}

message GetCandlesResponse { repeated Candle candles = 1; string provider = 2; bool delayed = 3; }
message CompanyInfo { string symbol = 1; string name = 2; string exchange = 3; string currency = 4; string description = 5; }
message GetNewsResponse { repeated Source sources = 1; }
```

`watchlist.proto`:

```proto
syntax = "proto3";

package investment.v1;

import "investment/v1/market.proto";

option go_package = "github.com/local/ai-investment-assistant/backend/gen/go/investment/v1;investmentv1";

service WatchlistService {
  rpc ListWatchlist(ListWatchlistRequest) returns (ListWatchlistResponse);
  rpc AddWatchlistItem(AddWatchlistItemRequest) returns (WatchlistItem);
  rpc RemoveWatchlistItem(RemoveWatchlistItemRequest) returns (RemoveWatchlistItemResponse);
}

message ListWatchlistRequest { string user_id = 1; }
message AddWatchlistItemRequest { string user_id = 1; string query = 2; }
message RemoveWatchlistItemRequest { string user_id = 1; string symbol = 2; }
message RemoveWatchlistItemResponse { bool removed = 1; }

message WatchlistItem {
  string id = 1;
  string user_id = 2;
  MarketSymbol symbol = 3;
  int32 sort_order = 4;
  MarketQuote quote = 5;
}

message ListWatchlistResponse { repeated WatchlistItem items = 1; }
```

`event.proto`、`agent.proto`、`research.proto` 和 `notification.proto`：

```proto
syntax = "proto3";

package investment.v1;

import "investment/v1/common.proto";

option go_package = "github.com/local/ai-investment-assistant/backend/gen/go/investment/v1;investmentv1";

service EventService {
  rpc IngestRawEvent(IngestRawEventRequest) returns (NormalizedEvent);
  rpc ListEvents(ListEventsRequest) returns (ListEventsResponse);
}

message IngestRawEventRequest {
  string provider = 1;
  string provider_event_id = 2;
  string symbol = 3;
  string title = 4;
  string summary = 5;
  string url = 6;
  string published_at = 7;
  string raw_payload_json = 8;
}

message ListEventsRequest { string user_id = 1; string symbol = 2; int32 limit = 3; }
message ListEventsResponse { repeated NormalizedEvent events = 1; }

message NormalizedEvent {
  string id = 1;
  string symbol = 2;
  string title = 3;
  string summary = 4;
  string source = 5;
  string url = 6;
  string published_at = 7;
  string event_type = 8;
  Priority priority = 9;
}
```

```proto
syntax = "proto3";

package investment.v1;

import "investment/v1/common.proto";
import "investment/v1/event.proto";

option go_package = "github.com/local/ai-investment-assistant/backend/gen/go/investment/v1;investmentv1";

service AgentService {
  rpc AnalyzeEvent(AnalyzeEventRequest) returns (ResearchCardResult);
  rpc AnswerQuestion(AnswerQuestionRequest) returns (AnswerResult);
  rpc SummarizeWatchlist(SummarizeWatchlistRequest) returns (WatchlistSummaryResult);
}

message AnalyzeEventRequest {
  string user_id = 1;
  NormalizedEvent event = 2;
  repeated Source sources = 3;
}

message ResearchCardResult {
  string symbol = 1;
  string event_title = 2;
  ResearchStance stance = 3;
  Confidence confidence = 4;
  string summary = 5;
  repeated string key_points = 6;
  repeated string counter_points = 7;
  repeated string watch_indicators = 8;
  string time_horizon = 9;
  repeated Source sources = 10;
  string disclaimer = 11;
}

message AnswerQuestionRequest {
  string user_id = 1;
  string question = 2;
  PageContext page_context = 3;
  repeated string research_card_ids = 4;
}

message AnswerResult {
  string answer = 1;
  repeated Source sources = 2;
  string disclaimer = 3;
}

message SummarizeWatchlistRequest { string user_id = 1; repeated string symbols = 2; }
message WatchlistSummaryResult { string summary = 1; repeated string suggested_questions = 2; repeated string high_priority_symbols = 3; }
```

```proto
syntax = "proto3";

package investment.v1;

import "investment/v1/agent.proto";
import "investment/v1/common.proto";
import "investment/v1/event.proto";

option go_package = "github.com/local/ai-investment-assistant/backend/gen/go/investment/v1;investmentv1";

service ResearchService {
  rpc GenerateResearchCard(GenerateResearchCardRequest) returns (ResearchCard);
  rpc GetResearchCard(GetResearchCardRequest) returns (ResearchCard);
  rpc ListResearchCards(ListResearchCardsRequest) returns (ListResearchCardsResponse);
}

message GenerateResearchCardRequest { string user_id = 1; NormalizedEvent event = 2; }
message GetResearchCardRequest { string user_id = 1; string research_card_id = 2; }
message ListResearchCardsRequest { string user_id = 1; string symbol = 2; int32 limit = 3; }
message ListResearchCardsResponse { repeated ResearchCard cards = 1; }

message ResearchCard {
  string id = 1;
  string user_id = 2;
  string event_id = 3;
  ResearchCardResult content = 4;
  Priority priority = 5;
  string created_at = 6;
}
```

```proto
syntax = "proto3";

package investment.v1;

import "investment/v1/common.proto";

option go_package = "github.com/local/ai-investment-assistant/backend/gen/go/investment/v1;investmentv1";

service NotificationService {
  rpc CreateNotification(CreateNotificationRequest) returns (Notification);
  rpc ListNotifications(ListNotificationsRequest) returns (ListNotificationsResponse);
  rpc MarkNotificationRead(MarkNotificationReadRequest) returns (Notification);
}

message CreateNotificationRequest {
  string user_id = 1;
  string research_card_id = 2;
  string title = 3;
  string body = 4;
  Priority priority = 5;
  string detail_url = 6;
}

message Notification {
  string id = 1;
  string user_id = 2;
  string research_card_id = 3;
  string title = 4;
  string body = 5;
  Priority priority = 6;
  bool read = 7;
  string push_status = 8;
  string created_at = 9;
}

message ListNotificationsRequest { string user_id = 1; bool unread_only = 2; }
message ListNotificationsResponse { repeated Notification notifications = 1; }
message MarkNotificationReadRequest { string user_id = 1; string notification_id = 2; }
```

- [ ] **步骤 4：生成代码**

运行：`make proto`

预期：生成 `backend/gen/go/investment/v1/*.pb.go`、`backend/gen/go/investment/v1/*_grpc.pb.go`，以及 `services/agent/app/gen/investment/v1` 下的 Python 生成文件。

- [ ] **步骤 5：提交**

```bash
git add buf.yaml buf.gen.yaml proto backend/gen services/agent/app/gen
git commit -m "feat: define investment assistant grpc contracts"
```

## 任务 3：PostgreSQL Schema

**文件：**
- 创建：`db/migrations/0001_init.sql`

- [ ] **步骤 1：创建 migration**

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE user_status AS ENUM ('active', 'disabled');
CREATE TYPE priority_level AS ENUM ('low', 'medium', 'high');
CREATE TYPE task_status AS ENUM ('pending', 'running', 'succeeded', 'failed');
CREATE TYPE research_stance AS ENUM ('bullish', 'bearish', 'neutral', 'mixed');
CREATE TYPE confidence_level AS ENUM ('low', 'medium', 'high');
CREATE TYPE message_role AS ENUM ('user', 'assistant');

CREATE TABLE email_allowlist (
  email TEXT PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  status user_status NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  refresh_token_hash TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE market_symbols (
  symbol TEXT PRIMARY KEY,
  exchange TEXT NOT NULL,
  name TEXT NOT NULL,
  currency TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  provider TEXT NOT NULL,
  provider_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE watchlist_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL REFERENCES market_symbols(symbol),
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, symbol)
);

CREATE TABLE market_quotes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  symbol TEXT NOT NULL REFERENCES market_symbols(symbol),
  price NUMERIC(18, 6) NOT NULL,
  change NUMERIC(18, 6) NOT NULL,
  change_percent NUMERIC(12, 6) NOT NULL,
  market_time TIMESTAMPTZ NOT NULL,
  delayed BOOLEAN NOT NULL DEFAULT true,
  provider TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE market_candles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  symbol TEXT NOT NULL REFERENCES market_symbols(symbol),
  ts TIMESTAMPTZ NOT NULL,
  open NUMERIC(18, 6) NOT NULL,
  high NUMERIC(18, 6) NOT NULL,
  low NUMERIC(18, 6) NOT NULL,
  close NUMERIC(18, 6) NOT NULL,
  volume NUMERIC(24, 4) NOT NULL,
  adjusted BOOLEAN NOT NULL DEFAULT false,
  provider TEXT NOT NULL,
  UNIQUE (symbol, ts, provider)
);

CREATE TABLE raw_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider TEXT NOT NULL,
  provider_event_id TEXT NOT NULL,
  raw_payload JSONB NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider, provider_event_id)
);

CREATE TABLE normalized_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  raw_event_id UUID NOT NULL REFERENCES raw_events(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL REFERENCES market_symbols(symbol),
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  source TEXT NOT NULL,
  url TEXT NOT NULL,
  published_at TIMESTAMPTZ NOT NULL,
  event_type TEXT NOT NULL,
  priority priority_level NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (symbol, url, published_at)
);

CREATE TABLE analysis_tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES normalized_events(id) ON DELETE CASCADE,
  status task_status NOT NULL DEFAULT 'pending',
  retry_count INTEGER NOT NULL DEFAULT 0,
  error_message TEXT NOT NULL DEFAULT '',
  next_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE research_cards (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  event_id UUID NOT NULL REFERENCES normalized_events(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL REFERENCES market_symbols(symbol),
  stance research_stance NOT NULL,
  confidence confidence_level NOT NULL,
  summary TEXT NOT NULL,
  key_points JSONB NOT NULL,
  counter_points JSONB NOT NULL,
  watch_indicators JSONB NOT NULL,
  time_horizon TEXT NOT NULL,
  disclaimer TEXT NOT NULL,
  priority priority_level NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE research_sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  research_card_id UUID NOT NULL REFERENCES research_cards(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  publisher TEXT NOT NULL,
  published_at TIMESTAMPTZ NOT NULL,
  provider TEXT NOT NULL
);

CREATE TABLE notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  research_card_id UUID REFERENCES research_cards(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  priority priority_level NOT NULL,
  read_at TIMESTAMPTZ,
  detail_url TEXT NOT NULL,
  push_status TEXT NOT NULL DEFAULT 'not_required',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE feishu_push_configs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  webhook_url TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE chat_threads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  symbol TEXT REFERENCES market_symbols(symbol),
  title TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE chat_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  thread_id UUID NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
  role message_role NOT NULL,
  content TEXT NOT NULL,
  context_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_watchlist_user ON watchlist_items(user_id, sort_order);
CREATE INDEX idx_events_symbol_published ON normalized_events(symbol, published_at DESC);
CREATE INDEX idx_tasks_due ON analysis_tasks(status, next_run_at);
CREATE INDEX idx_research_user_symbol ON research_cards(user_id, symbol, created_at DESC);
CREATE INDEX idx_notifications_user_unread ON notifications(user_id, read_at, created_at DESC);
CREATE INDEX idx_chat_threads_user ON chat_threads(user_id, created_at DESC);
```

- [ ] **步骤 2：用 PostgreSQL 验证 schema**

运行：`docker run --rm -e POSTGRES_PASSWORD=investment -e POSTGRES_USER=investment -e POSTGRES_DB=investment -p 55432:5432 -d --name investment-postgres postgres:16`

运行：`psql "postgres://investment:investment@localhost:55432/investment?sslmode=disable" -f db/migrations/0001_init.sql`

预期：输出包含 `CREATE TABLE`，没有错误。

- [ ] **步骤 3：提交**

```bash
git add db/migrations/0001_init.sql
git commit -m "feat: add investment assistant database schema"
```

## 任务 4：Go 共享平台层

**文件：**
- 创建：`backend/go.mod`
- 创建：`backend/internal/config/config.go`
- 创建：`backend/internal/platform/postgres/postgres.go`
- 创建：`backend/internal/platform/auth/jwt.go`
- 创建：`backend/internal/platform/httpjson/httpjson.go`

- [ ] **步骤 1：创建 Go module**

```go
module github.com/local/ai-investment-assistant/backend

go 1.26

require (
	github.com/go-chi/chi/v5 v5.2.3
	github.com/golang-jwt/jwt/v5 v5.3.0
	github.com/google/uuid v1.6.0
	github.com/jackc/pgx/v5 v5.7.6
	github.com/stretchr/testify v1.11.1
	golang.org/x/crypto v0.43.0
	google.golang.org/grpc v1.76.0
	google.golang.org/protobuf v1.36.10
)
```

- [ ] **步骤 2：添加配置加载器**

```go
package config

import (
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	AppEnv             string
	DatabaseURL        string
	JWTSecret          string
	SessionTTL         time.Duration
	EmailAllowlist     []string
	InitialUserEmail   string
	InitialUserPass    string
	MarketProvider     string
	AlphaVantageAPIKey string
	FeishuWebhookURL   string
	PollInterval       time.Duration
	BFFHTTPAddr        string
	UserGRPCAddr       string
	WatchlistGRPCAddr  string
	MarketGRPCAddr     string
	EventGRPCAddr      string
	ResearchGRPCAddr   string
	NotificationGRPCAddr string
	AgentGRPCAddr      string
}

func Load() Config {
	return Config{
		AppEnv:             env("APP_ENV", "local"),
		DatabaseURL:        env("DATABASE_URL", "postgres://investment:investment@localhost:5432/investment?sslmode=disable"),
		JWTSecret:          env("JWT_SECRET", "local-dev-secret-32-characters-min"),
		SessionTTL:         time.Duration(envInt("SESSION_TTL_HOURS", 24)) * time.Hour,
		EmailAllowlist:     splitCSV(env("EMAIL_ALLOWLIST", "owner@example.com")),
		InitialUserEmail:   env("INITIAL_USER_EMAIL", "owner@example.com"),
		InitialUserPass:    env("INITIAL_USER_PASSWORD", "local-password-123"),
		MarketProvider:     env("MARKET_PROVIDER", "mock"),
		AlphaVantageAPIKey: env("ALPHA_VANTAGE_API_KEY", "demo"),
		FeishuWebhookURL:   env("FEISHU_WEBHOOK_URL", ""),
		PollInterval:       time.Duration(envInt("POLL_INTERVAL_SECONDS", 300)) * time.Second,
		BFFHTTPAddr:        env("BFF_HTTP_ADDR", ":8080"),
		UserGRPCAddr:       env("USER_GRPC_ADDR", "localhost:9001"),
		WatchlistGRPCAddr:  env("WATCHLIST_GRPC_ADDR", "localhost:9002"),
		MarketGRPCAddr:     env("MARKET_GRPC_ADDR", "localhost:9003"),
		EventGRPCAddr:      env("EVENT_GRPC_ADDR", "localhost:9004"),
		ResearchGRPCAddr:   env("RESEARCH_GRPC_ADDR", "localhost:9005"),
		NotificationGRPCAddr: env("NOTIFICATION_GRPC_ADDR", "localhost:9006"),
		AgentGRPCAddr:      env("AGENT_GRPC_ADDR", "localhost:9010"),
	}
}

func env(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func envInt(key string, fallback int) int {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(value)
	if err != nil {
		return fallback
	}
	return parsed
}

func splitCSV(value string) []string {
	parts := strings.Split(value, ",")
	out := make([]string, 0, len(parts))
	for _, part := range parts {
		trimmed := strings.TrimSpace(strings.ToLower(part))
		if trimmed != "" {
			out = append(out, trimmed)
		}
	}
	return out
}
```

- [ ] **步骤 3：添加 PostgreSQL 连接器**

```go
package postgres

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func Connect(ctx context.Context, databaseURL string) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, err
	}
	cfg.MaxConns = 8
	cfg.MinConns = 1
	cfg.MaxConnLifetime = time.Hour
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, err
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, err
	}
	return pool, nil
}
```

- [ ] **步骤 4：添加 JWT 工具**

```go
package auth

import (
	"errors"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

type Claims struct {
	UserID string `json:"user_id"`
	Email  string `json:"email"`
	jwt.RegisteredClaims
}

func Sign(secret, userID, email string, ttl time.Duration) (string, time.Time, error) {
	expiresAt := time.Now().UTC().Add(ttl)
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, Claims{
		UserID: userID,
		Email:  email,
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   userID,
			ExpiresAt: jwt.NewNumericDate(expiresAt),
			IssuedAt:  jwt.NewNumericDate(time.Now().UTC()),
		},
	})
	signed, err := token.SignedString([]byte(secret))
	return signed, expiresAt, err
}

func Verify(secret, tokenValue string) (*Claims, error) {
	token, err := jwt.ParseWithClaims(tokenValue, &Claims{}, func(token *jwt.Token) (any, error) {
		if token.Method != jwt.SigningMethodHS256 {
			return nil, errors.New("unexpected jwt signing method")
		}
		return []byte(secret), nil
	})
	if err != nil {
		return nil, err
	}
	claims, ok := token.Claims.(*Claims)
	if !ok || !token.Valid {
		return nil, errors.New("invalid jwt claims")
	}
	return claims, nil
}
```

- [ ] **步骤 5：添加 JSON 响应工具**

```go
package httpjson

import (
	"encoding/json"
	"net/http"
)

type ErrorResponse struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

func Write(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func Error(w http.ResponseWriter, status int, code string, message string) {
	Write(w, status, ErrorResponse{Code: code, Message: message})
}
```

- [ ] **步骤 6：运行共享 Go 测试**

运行：`cd backend && go test ./internal/...`

预期：以 `0` 退出。

- [ ] **步骤 7：提交**

```bash
git add backend/go.mod backend/go.sum backend/internal/config backend/internal/platform
git commit -m "feat: add go platform foundation"
```

## 任务 5：User Service 与 BFF 登录

**文件：**
- 创建：`backend/internal/service/user/repository.go`
- 创建：`backend/internal/service/user/service.go`
- 创建：`backend/internal/service/user/service_test.go`
- 创建：`backend/cmd/user-service/main.go`
- 创建：`backend/internal/bff/server.go`
- 创建：`backend/internal/bff/server_test.go`
- 创建：`backend/cmd/bff/main.go`

- [ ] **步骤 1：编写先失败的 User Service 测试**

```go
package user

import (
	"context"
	"testing"
	"time"

	"github.com/local/ai-investment-assistant/backend/internal/platform/auth"
	"github.com/stretchr/testify/require"
)

func TestLoginRejectsEmailOutsideAllowlist(t *testing.T) {
	svc := NewService(NewMemoryRepository(), "secret", time.Hour, []string{"owner@example.com"})
	_, err := svc.Login(context.Background(), "other@example.com", "pw")
	require.ErrorContains(t, err, "email is not allowed")
}

func TestLoginReturnsJWTForSeededUser(t *testing.T) {
	repo := NewMemoryRepository()
	require.NoError(t, repo.SeedUser(context.Background(), "owner@example.com", "local-password-123"))
	svc := NewService(repo, "secret-32-characters-minimum", time.Hour, []string{"owner@example.com"})

	resp, err := svc.Login(context.Background(), "owner@example.com", "local-password-123")
	require.NoError(t, err)
	require.Equal(t, "owner@example.com", resp.Email)
	require.NotEmpty(t, resp.AccessToken)
	claims, err := auth.Verify("secret-32-characters-minimum", resp.AccessToken)
	require.NoError(t, err)
	require.Equal(t, resp.UserID, claims.UserID)
}
```

- [ ] **步骤 2：实现 User Service 核心逻辑**

```go
package user

import (
	"context"
	"errors"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/local/ai-investment-assistant/backend/internal/platform/auth"
	"golang.org/x/crypto/bcrypt"
)

type LoginResult struct {
	UserID      string
	Email       string
	AccessToken string
	ExpiresAt   time.Time
}

type Repository interface {
	SeedUser(ctx context.Context, email, password string) error
	FindByEmail(ctx context.Context, email string) (StoredUser, error)
}

type StoredUser struct {
	ID           string
	Email        string
	PasswordHash string
	Status       string
}

type Service struct {
	repo      Repository
	jwtSecret string
	ttl       time.Duration
	allowlist map[string]struct{}
}

func NewService(repo Repository, jwtSecret string, ttl time.Duration, allowlist []string) *Service {
	allowed := make(map[string]struct{}, len(allowlist))
	for _, email := range allowlist {
		allowed[strings.ToLower(strings.TrimSpace(email))] = struct{}{}
	}
	return &Service{repo: repo, jwtSecret: jwtSecret, ttl: ttl, allowlist: allowed}
}

func (s *Service) Login(ctx context.Context, email, password string) (LoginResult, error) {
	normalized := strings.ToLower(strings.TrimSpace(email))
	if _, ok := s.allowlist[normalized]; !ok {
		return LoginResult{}, errors.New("email is not allowed")
	}
	user, err := s.repo.FindByEmail(ctx, normalized)
	if err != nil {
		return LoginResult{}, errors.New("invalid email or password")
	}
	if user.Status != "active" {
		return LoginResult{}, errors.New("user is disabled")
	}
	if err := bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(password)); err != nil {
		return LoginResult{}, errors.New("invalid email or password")
	}
	token, expiresAt, err := auth.Sign(s.jwtSecret, user.ID, user.Email, s.ttl)
	if err != nil {
		return LoginResult{}, err
	}
	return LoginResult{UserID: user.ID, Email: user.Email, AccessToken: token, ExpiresAt: expiresAt}, nil
}

type MemoryRepository struct {
	mu    sync.RWMutex
	users map[string]StoredUser
}

func NewMemoryRepository() *MemoryRepository {
	return &MemoryRepository{users: map[string]StoredUser{}}
}

func (r *MemoryRepository) SeedUser(ctx context.Context, email, password string) error {
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	normalized := strings.ToLower(strings.TrimSpace(email))
	r.users[normalized] = StoredUser{ID: uuid.NewString(), Email: normalized, PasswordHash: string(hash), Status: "active"}
	return nil
}

func (r *MemoryRepository) FindByEmail(ctx context.Context, email string) (StoredUser, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	user, ok := r.users[strings.ToLower(strings.TrimSpace(email))]
	if !ok {
		return StoredUser{}, errors.New("user not found")
	}
	return user, nil
}
```

- [ ] **步骤 3：实现 gRPC server 和 BFF 登录路由**

在 `cmd/user-service/main.go` 和 `internal/bff/server.go` 中使用生成的 protobuf 方法。BFF 路由形状如下：

```go
r.Post("/api/auth/login", s.handleLogin)
r.Get("/api/me", s.requireAuth(s.handleMe))
```

`handleLogin` 请求/响应：

```go
type loginRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

type loginResponse struct {
	User        userDTO `json:"user"`
	AccessToken string `json:"accessToken"`
	ExpiresAt   string `json:"expiresAt"`
}

type userDTO struct {
	ID    string `json:"id"`
	Email string `json:"email"`
}
```

- [ ] **步骤 4：运行登录测试**

运行：`cd backend && go test ./internal/service/user ./internal/bff`

预期：两个 package 都输出 `ok`。

- [ ] **步骤 5：提交**

```bash
git add backend/internal/service/user backend/cmd/user-service backend/internal/bff backend/cmd/bff
git commit -m "feat: add allowlisted email login"
```

## 任务 6：Market Data Service

**文件：**
- 创建：`backend/internal/service/marketdata/provider.go`
- 创建：`backend/internal/service/marketdata/mock_provider.go`
- 创建：`backend/internal/service/marketdata/alphavantage_provider.go`
- 创建：`backend/internal/service/marketdata/service.go`
- 创建：`backend/internal/service/marketdata/service_test.go`
- 创建：`backend/cmd/market-data-service/main.go`

- [ ] **步骤 1：编写 provider 契约和 mock 测试**

```go
package marketdata

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestMockProviderResolvesAndQuotesAAPL(t *testing.T) {
	provider := NewMockProvider()
	symbol, err := provider.ResolveSymbol(context.Background(), "aapl")
	require.NoError(t, err)
	require.Equal(t, "AAPL", symbol.Symbol)
	require.Equal(t, "NASDAQ", symbol.Exchange)

	quote, err := provider.GetQuote(context.Background(), "AAPL")
	require.NoError(t, err)
	require.True(t, quote.Delayed)
	require.Equal(t, "mock", quote.Provider)
}
```

- [ ] **步骤 2：实现 provider 类型**

```go
package marketdata

import "context"

type Symbol struct {
	Symbol      string
	Exchange    string
	Name        string
	Currency    string
	Description string
}

type Quote struct {
	Symbol        string
	Price         float64
	Change        float64
	ChangePercent float64
	MarketTime    string
	Delayed       bool
	Provider      string
}

type Candle struct {
	Timestamp string
	Open      float64
	High      float64
	Low       float64
	Close     float64
	Volume    float64
	Adjusted  bool
}

type NewsItem struct {
	Title       string
	URL         string
	Publisher   string
	PublishedAt string
	Provider    string
}

type Provider interface {
	ResolveSymbol(ctx context.Context, query string) (Symbol, error)
	GetQuote(ctx context.Context, symbol string) (Quote, error)
	GetCandles(ctx context.Context, symbol string, rangeName string) ([]Candle, error)
	GetCompanyInfo(ctx context.Context, symbol string) (Symbol, error)
	GetNews(ctx context.Context, symbol string, limit int) ([]NewsItem, error)
}
```

- [ ] **步骤 3：实现 mock provider**

```go
package marketdata

import (
	"context"
	"errors"
	"strings"
)

func NewMockProvider() Provider {
	return mockProvider{}
}

type mockProvider struct{}

func (mockProvider) ResolveSymbol(ctx context.Context, query string) (Symbol, error) {
	symbol := strings.ToUpper(strings.TrimSpace(query))
	if symbol == "" {
		return Symbol{}, errors.New("symbol query is empty")
	}
	names := map[string]string{"AAPL": "Apple Inc.", "MSFT": "Microsoft Corporation", "NVDA": "NVIDIA Corporation", "TSLA": "Tesla, Inc."}
	name := names[symbol]
	if name == "" {
		name = symbol + " Corporation"
	}
	return Symbol{Symbol: symbol, Exchange: "NASDAQ", Name: name, Currency: "USD", Description: "Mock company profile for local development."}, nil
}

func (mockProvider) GetQuote(ctx context.Context, symbol string) (Quote, error) {
	return Quote{Symbol: strings.ToUpper(symbol), Price: 203.41, Change: 2.14, ChangePercent: 1.06, MarketTime: "2026-05-15T20:00:00Z", Delayed: true, Provider: "mock"}, nil
}

func (mockProvider) GetCandles(ctx context.Context, symbol string, rangeName string) ([]Candle, error) {
	return []Candle{
		{Timestamp: "2026-05-13T20:00:00Z", Open: 198.1, High: 201.2, Low: 197.4, Close: 200.3, Volume: 53000000, Adjusted: false},
		{Timestamp: "2026-05-14T20:00:00Z", Open: 200.4, High: 203.0, Low: 199.9, Close: 201.2, Volume: 49000000, Adjusted: false},
		{Timestamp: "2026-05-15T20:00:00Z", Open: 201.6, High: 204.1, Low: 200.8, Close: 203.4, Volume: 51000000, Adjusted: false},
	}, nil
}

func (mockProvider) GetCompanyInfo(ctx context.Context, symbol string) (Symbol, error) {
	return mockProvider{}.ResolveSymbol(ctx, symbol)
}

func (mockProvider) GetNews(ctx context.Context, symbol string, limit int) ([]NewsItem, error) {
	if limit <= 0 {
		limit = 5
	}
	items := []NewsItem{{
		Title:       strings.ToUpper(symbol) + " reports stronger services revenue",
		URL:         "https://example.com/mock/" + strings.ToLower(symbol),
		Publisher:   "Mock News",
		PublishedAt: "2026-05-15T14:00:00Z",
		Provider:    "mock",
	}}
	if limit < len(items) {
		return items[:limit], nil
	}
	return items, nil
}
```

- [ ] **步骤 4：实现 Alpha Vantage adapter**

创建 `alphavantage_provider.go`：

```go
package marketdata

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

type AlphaVantageProvider struct {
	apiKey string
	client *http.Client
}

func NewAlphaVantageProvider(apiKey string) Provider {
	return &AlphaVantageProvider{apiKey: apiKey, client: &http.Client{Timeout: 8 * time.Second}}
}

func (p *AlphaVantageProvider) get(ctx context.Context, params url.Values, out any) error {
	params.Set("apikey", p.apiKey)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://www.alphavantage.co/query?"+params.Encode(), nil)
	if err != nil {
		return err
	}
	resp, err := p.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("alpha vantage status %d", resp.StatusCode)
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

func (p *AlphaVantageProvider) ResolveSymbol(ctx context.Context, query string) (Symbol, error) {
	var body struct {
		BestMatches []map[string]string `json:"bestMatches"`
	}
	if err := p.get(ctx, url.Values{"function": {"SYMBOL_SEARCH"}, "keywords": {query}}, &body); err != nil {
		return Symbol{}, err
	}
	if len(body.BestMatches) == 0 {
		return Symbol{}, errors.New("symbol not found")
	}
	match := body.BestMatches[0]
	return Symbol{Symbol: match["1. symbol"], Name: match["2. name"], Exchange: match["4. region"], Currency: match["8. currency"], Description: ""}, nil
}

func (p *AlphaVantageProvider) GetQuote(ctx context.Context, symbol string) (Quote, error) {
	var body struct {
		GlobalQuote map[string]string `json:"Global Quote"`
	}
	if err := p.get(ctx, url.Values{"function": {"GLOBAL_QUOTE"}, "symbol": {symbol}}, &body); err != nil {
		return Quote{}, err
	}
	q := body.GlobalQuote
	price, _ := strconv.ParseFloat(q["05. price"], 64)
	change, _ := strconv.ParseFloat(q["09. change"], 64)
	changePercent, _ := strconv.ParseFloat(strings.TrimSuffix(q["10. change percent"], "%"), 64)
	return Quote{Symbol: q["01. symbol"], Price: price, Change: change, ChangePercent: changePercent, MarketTime: q["07. latest trading day"] + "T20:00:00Z", Delayed: true, Provider: "alpha_vantage"}, nil
}

func (p *AlphaVantageProvider) GetCandles(ctx context.Context, symbol string, rangeName string) ([]Candle, error) {
	var body map[string]map[string]map[string]string
	if err := p.get(ctx, url.Values{"function": {"TIME_SERIES_DAILY"}, "symbol": {symbol}, "outputsize": {"compact"}}, &body); err != nil {
		return nil, err
	}
	series := body["Time Series (Daily)"]
	candles := make([]Candle, 0, len(series))
	for day, row := range series {
		open, _ := strconv.ParseFloat(row["1. open"], 64)
		high, _ := strconv.ParseFloat(row["2. high"], 64)
		low, _ := strconv.ParseFloat(row["3. low"], 64)
		closeValue, _ := strconv.ParseFloat(row["4. close"], 64)
		volume, _ := strconv.ParseFloat(row["5. volume"], 64)
		candles = append(candles, Candle{Timestamp: day + "T20:00:00Z", Open: open, High: high, Low: low, Close: closeValue, Volume: volume, Adjusted: false})
	}
	return candles, nil
}

func (p *AlphaVantageProvider) GetCompanyInfo(ctx context.Context, symbol string) (Symbol, error) {
	return p.ResolveSymbol(ctx, symbol)
}

func (p *AlphaVantageProvider) GetNews(ctx context.Context, symbol string, limit int) ([]NewsItem, error) {
	if limit <= 0 {
		limit = 10
	}
	var body struct {
		Feed []struct {
			Title       string `json:"title"`
			URL         string `json:"url"`
			Source      string `json:"source"`
			TimePublished string `json:"time_published"`
		} `json:"feed"`
	}
	if err := p.get(ctx, url.Values{"function": {"NEWS_SENTIMENT"}, "tickers": {symbol}, "limit": {strconv.Itoa(limit)}}, &body); err != nil {
		return nil, err
	}
	items := make([]NewsItem, 0, len(body.Feed))
	for _, item := range body.Feed {
		published := item.TimePublished
		if len(published) == 15 {
			published = published[0:4] + "-" + published[4:6] + "-" + published[6:8] + "T" + published[9:11] + ":" + published[11:13] + ":" + published[13:15] + "Z"
		}
		items = append(items, NewsItem{Title: item.Title, URL: item.URL, Publisher: item.Source, PublishedAt: published, Provider: "alpha_vantage"})
	}
	return items, nil
}
```

官方 API 参考：`https://www.alphavantage.co/documentation/`。

- [ ] **步骤 5：运行行情服务测试**

运行：`cd backend && go test ./internal/service/marketdata`

预期：mock provider 测试通过。Alpha Vantage 网络测试不放入默认测试套件。

- [ ] **步骤 6：提交**

```bash
git add backend/internal/service/marketdata backend/cmd/market-data-service
git commit -m "feat: add market data service providers"
```

## 任务 7：Watchlist Service

**文件：**
- 创建：`backend/internal/service/watchlist/repository.go`
- 创建：`backend/internal/service/watchlist/service.go`
- 创建：`backend/internal/service/watchlist/service_test.go`
- 创建：`backend/cmd/watchlist-service/main.go`

- [ ] **步骤 1：编写先失败的自选股测试**

```go
package watchlist

import (
	"context"
	"testing"

	"github.com/local/ai-investment-assistant/backend/internal/service/marketdata"
	"github.com/stretchr/testify/require"
)

func TestAddWatchlistItemResolvesSymbolBeforeSaving(t *testing.T) {
	repo := NewMemoryRepository()
	svc := NewService(repo, marketdata.NewMockProvider())

	item, err := svc.Add(context.Background(), "user-1", "aapl")
	require.NoError(t, err)
	require.Equal(t, "AAPL", item.Symbol.Symbol)

	items, err := svc.List(context.Background(), "user-1")
	require.NoError(t, err)
	require.Len(t, items, 1)
	require.Equal(t, "Apple Inc.", items[0].Symbol.Name)
}
```

- [ ] **步骤 2：实现服务**

```go
package watchlist

import (
	"context"
	"errors"
	"sync"

	"github.com/google/uuid"
	"github.com/local/ai-investment-assistant/backend/internal/service/marketdata"
)

type Item struct {
	ID        string
	UserID    string
	Symbol    marketdata.Symbol
	Quote     marketdata.Quote
	SortOrder int
}

type Repository interface {
	Save(ctx context.Context, item Item) (Item, error)
	List(ctx context.Context, userID string) ([]Item, error)
	Remove(ctx context.Context, userID, symbol string) (bool, error)
}

type Service struct {
	repo     Repository
	provider marketdata.Provider
}

func NewService(repo Repository, provider marketdata.Provider) *Service {
	return &Service{repo: repo, provider: provider}
}

func (s *Service) Add(ctx context.Context, userID, query string) (Item, error) {
	if userID == "" {
		return Item{}, errors.New("user id is required")
	}
	symbol, err := s.provider.ResolveSymbol(ctx, query)
	if err != nil {
		return Item{}, err
	}
	quote, err := s.provider.GetQuote(ctx, symbol.Symbol)
	if err != nil {
		return Item{}, err
	}
	existing, err := s.repo.List(ctx, userID)
	if err != nil {
		return Item{}, err
	}
	item := Item{ID: uuid.NewString(), UserID: userID, Symbol: symbol, Quote: quote, SortOrder: len(existing)}
	return s.repo.Save(ctx, item)
}

func (s *Service) List(ctx context.Context, userID string) ([]Item, error) {
	return s.repo.List(ctx, userID)
}

type MemoryRepository struct {
	mu    sync.RWMutex
	items map[string][]Item
}

func NewMemoryRepository() *MemoryRepository {
	return &MemoryRepository{items: map[string][]Item{}}
}

func (r *MemoryRepository) Save(ctx context.Context, item Item) (Item, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	for _, existing := range r.items[item.UserID] {
		if existing.Symbol.Symbol == item.Symbol.Symbol {
			return existing, nil
		}
	}
	r.items[item.UserID] = append(r.items[item.UserID], item)
	return item, nil
}

func (r *MemoryRepository) List(ctx context.Context, userID string) ([]Item, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return append([]Item(nil), r.items[userID]...), nil
}

func (r *MemoryRepository) Remove(ctx context.Context, userID, symbol string) (bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	items := r.items[userID]
	next := items[:0]
	removed := false
	for _, item := range items {
		if item.Symbol.Symbol == symbol {
			removed = true
			continue
		}
		next = append(next, item)
	}
	r.items[userID] = next
	return removed, nil
}
```

- [ ] **步骤 3：接入 gRPC 服务**

在 `cmd/watchlist-service/main.go` 中实现 `WatchlistServiceServer`，并将 `Item` 映射为生成的 protobuf `WatchlistItem`。真实服务模式注入 `MarketDataServiceClient`，本地单元测试使用 mock provider。

- [ ] **步骤 4：运行自选股测试**

运行：`cd backend && go test ./internal/service/watchlist`

预期：`PASS`。

- [ ] **步骤 5：提交**

```bash
git add backend/internal/service/watchlist backend/cmd/watchlist-service
git commit -m "feat: add watchlist service"
```

## 任务 8：Event Service 与 Scheduler Worker

**文件：**
- 创建：`backend/internal/service/event/service.go`
- 创建：`backend/internal/service/event/service_test.go`
- 创建：`backend/internal/service/scheduler/worker.go`
- 创建：`backend/internal/service/scheduler/worker_test.go`
- 创建：`backend/cmd/event-service/main.go`
- 创建：`backend/cmd/scheduler-worker/main.go`

- [ ] **步骤 1：编写事件标准化测试**

```go
package event

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestIngestDeduplicatesAndScoresHighPriority(t *testing.T) {
	repo := NewMemoryRepository()
	svc := NewService(repo)
	req := RawEvent{Provider: "mock", ProviderEventID: "mock-1", Symbol: "AAPL", Title: "AAPL earnings beat expectations", Summary: "Revenue and EPS came in above consensus.", URL: "https://example.com/aapl-earnings", PublishedAt: "2026-05-15T14:00:00Z", RawPayloadJSON: "{}"}

	first, err := svc.Ingest(context.Background(), req)
	require.NoError(t, err)
	second, err := svc.Ingest(context.Background(), req)
	require.NoError(t, err)
	require.Equal(t, first.ID, second.ID)
	require.Equal(t, "high", first.Priority)
}
```

- [ ] **步骤 2：实现事件服务**

```go
package event

import (
	"context"
	"strings"
	"sync"

	"github.com/google/uuid"
)

type RawEvent struct {
	Provider        string
	ProviderEventID string
	Symbol          string
	Title           string
	Summary         string
	URL             string
	PublishedAt     string
	RawPayloadJSON  string
}

type NormalizedEvent struct {
	ID          string
	Symbol      string
	Title       string
	Summary     string
	Source      string
	URL         string
	PublishedAt string
	EventType   string
	Priority    string
}

type Service struct{ repo *MemoryRepository }

func NewService(repo *MemoryRepository) *Service { return &Service{repo: repo} }

func (s *Service) Ingest(ctx context.Context, raw RawEvent) (NormalizedEvent, error) {
	key := raw.Provider + ":" + raw.ProviderEventID
	if existing, ok := s.repo.GetByKey(key); ok {
		return existing, nil
	}
	event := NormalizedEvent{
		ID: uuid.NewString(), Symbol: strings.ToUpper(raw.Symbol), Title: raw.Title, Summary: raw.Summary,
		Source: raw.Provider, URL: raw.URL, PublishedAt: raw.PublishedAt, EventType: classify(raw.Title, raw.Summary),
		Priority: score(raw.Title, raw.Summary),
	}
	s.repo.Save(key, event)
	return event, nil
}

func classify(title, summary string) string {
	text := strings.ToLower(title + " " + summary)
	if strings.Contains(text, "earnings") || strings.Contains(text, "revenue") || strings.Contains(text, "eps") {
		return "earnings"
	}
	if strings.Contains(text, "guidance") || strings.Contains(text, "forecast") {
		return "guidance"
	}
	return "news"
}

func score(title, summary string) string {
	text := strings.ToLower(title + " " + summary)
	for _, word := range []string{"earnings", "guidance", "sec", "lawsuit", "acquisition", "beat", "miss"} {
		if strings.Contains(text, word) {
			return "high"
		}
	}
	return "medium"
}

type MemoryRepository struct {
	mu     sync.RWMutex
	events map[string]NormalizedEvent
}

func NewMemoryRepository() *MemoryRepository { return &MemoryRepository{events: map[string]NormalizedEvent{}} }
func (r *MemoryRepository) GetByKey(key string) (NormalizedEvent, bool) { r.mu.RLock(); defer r.mu.RUnlock(); v, ok := r.events[key]; return v, ok }
func (r *MemoryRepository) Save(key string, event NormalizedEvent) { r.mu.Lock(); defer r.mu.Unlock(); r.events[key] = event }
```

- [ ] **步骤 3：实现 scheduler worker 循环**

`backend/cmd/scheduler-worker/main.go`:

```go
package main

import (
	"context"
	"log"
	"time"

	"github.com/local/ai-investment-assistant/backend/internal/config"
)

func main() {
	cfg := config.Load()
	ticker := time.NewTicker(cfg.PollInterval)
	defer ticker.Stop()
	log.Printf("scheduler worker started interval=%s", cfg.PollInterval)
	runOnce(context.Background())
	for range ticker.C {
		runOnce(context.Background())
	}
}

func runOnce(ctx context.Context) {
	log.Print("scheduler poll cycle started")
	log.Print("scheduler poll cycle completed")
}
```

- [ ] **步骤 4：实现 scheduler 服务流程**

`backend/internal/service/scheduler/worker.go`:

```go
package scheduler

import "context"

type WatchlistClient interface {
	ListSymbols(ctx context.Context) ([]string, error)
}

type MarketNewsClient interface {
	GetNews(ctx context.Context, symbol string, limit int) ([]NewsItem, error)
}

type EventClient interface {
	Ingest(ctx context.Context, input RawEventInput) (NormalizedEvent, error)
}

type ResearchClient interface {
	GenerateResearchCard(ctx context.Context, eventID string) error
}

type NewsItem struct {
	Provider    string
	ID          string
	Symbol      string
	Title       string
	Summary     string
	URL         string
	PublishedAt string
	RawJSON     string
}

type RawEventInput struct {
	Provider        string
	ProviderEventID string
	Symbol          string
	Title           string
	Summary         string
	URL             string
	PublishedAt     string
	RawPayloadJSON  string
}

type NormalizedEvent struct {
	ID       string
	Priority string
}

type Worker struct {
	watchlists WatchlistClient
	market     MarketNewsClient
	events     EventClient
	research   ResearchClient
}

func NewWorker(w WatchlistClient, m MarketNewsClient, e EventClient, r ResearchClient) *Worker {
	return &Worker{watchlists: w, market: m, events: e, research: r}
}

func (w *Worker) RunOnce(ctx context.Context) error {
	symbols, err := w.watchlists.ListSymbols(ctx)
	if err != nil {
		return err
	}
	for _, symbol := range symbols {
		news, err := w.market.GetNews(ctx, symbol, 10)
		if err != nil {
			return err
		}
		for _, item := range news {
			event, err := w.events.Ingest(ctx, RawEventInput{
				Provider: item.Provider, ProviderEventID: item.ID, Symbol: symbol, Title: item.Title,
				Summary: item.Summary, URL: item.URL, PublishedAt: item.PublishedAt, RawPayloadJSON: item.RawJSON,
			})
			if err != nil {
				return err
			}
			if event.Priority == "high" {
				if err := w.research.GenerateResearchCard(ctx, event.ID); err != nil {
					return err
				}
			}
		}
	}
	return nil
}
```

- [ ] **步骤 5：运行测试**

运行：`cd backend && go test ./internal/service/event ./internal/service/scheduler`

预期：`PASS`。

- [ ] **步骤 6：提交**

```bash
git add backend/internal/service/event backend/internal/service/scheduler backend/cmd/event-service backend/cmd/scheduler-worker
git commit -m "feat: add event ingestion and scheduler worker"
```

## 任务 9：Python Agent Service

**文件：**
- 创建：`services/agent/pyproject.toml`
- 创建：`services/agent/app/schemas.py`
- 创建：`services/agent/app/providers/deepseek.py`
- 创建：`services/agent/app/graphs/event_analysis.py`
- 创建：`services/agent/app/graphs/question_answer.py`
- 创建：`services/agent/app/graphs/watchlist_summary.py`
- 创建：`services/agent/app/server.py`
- 创建：`services/agent/tests/test_guardrails.py`

- [ ] **步骤 1：添加 Python package**

```toml
[project]
name = "ai-investment-agent"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "grpcio>=1.76.0",
  "grpcio-tools>=1.76.0",
  "langchain>=1.0.0",
  "langgraph>=1.0.0",
  "pydantic>=2.12.0",
  "httpx>=0.28.0"
]

[dependency-groups]
dev = ["pytest>=8.4.0"]

[build-system]
requires = ["hatchling>=1.27.0"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
pythonpath = ["."]
```

- [ ] **步骤 2：编写风控 guardrail 测试**

```python
from app.schemas import ResearchCard, guard_investment_language


def test_research_card_rejects_trade_instruction():
    card = ResearchCard(
        symbol="AAPL",
        event_title="AAPL earnings",
        stance="bullish",
        confidence="medium",
        summary="This is a research summary.",
        key_points=["Services revenue improved."],
        counter_points=["Valuation remains a risk."],
        watch_indicators=["Next quarter guidance"],
        time_horizon="1-3 months",
        sources=[],
        disclaimer="Not investment advice. For research only.",
    )
    assert guard_investment_language(card.model_dump()) == []

    unsafe = card.model_copy(update={"summary": "Buy AAPL now."})
    assert guard_investment_language(unsafe.model_dump()) == ["summary contains prohibited trading instruction: buy"]
```

- [ ] **步骤 3：实现 schema 和 guardrail**

```python
from typing import Literal

from pydantic import BaseModel, Field

PROHIBITED_TERMS = ["buy", "sell", "add position", "reduce position", "加仓", "减仓", "买入", "卖出"]
DISCLAIMER = "This content is not investment advice and is for research reference only."


class Source(BaseModel):
    title: str
    url: str
    publisher: str
    published_at: str
    provider: str


class ResearchCard(BaseModel):
    symbol: str
    event_title: str
    stance: Literal["bullish", "bearish", "neutral", "mixed"]
    confidence: Literal["low", "medium", "high"]
    summary: str
    key_points: list[str] = Field(min_length=1)
    counter_points: list[str] = Field(min_length=1)
    watch_indicators: list[str] = Field(min_length=1)
    time_horizon: str
    sources: list[Source]
    disclaimer: str = DISCLAIMER


class Answer(BaseModel):
    answer: str
    sources: list[Source]
    disclaimer: str = DISCLAIMER


def guard_investment_language(payload: dict) -> list[str]:
    findings: list[str] = []
    for field in ["summary", "answer"]:
        value = str(payload.get(field, "")).lower()
        for term in PROHIBITED_TERMS:
            if term.lower() in value:
                findings.append(f"{field} contains prohibited trading instruction: {term}")
    return findings
```

- [ ] **步骤 4：实现确定性 graph 输出和 DeepSeek provider**

```python
from app.schemas import DISCLAIMER, ResearchCard, Source, guard_investment_language


def analyze_event(event: dict, sources: list[dict]) -> ResearchCard:
    source_models = [Source(**source) for source in sources]
    card = ResearchCard(
        symbol=event["symbol"],
        event_title=event["title"],
        stance="mixed",
        confidence="medium",
        summary=f"{event['symbol']} has a notable event: {event['title']}. The near-term interpretation is mixed because confirmed facts and market expectations both matter.",
        key_points=[event["summary"]],
        counter_points=["The event may already be reflected in recent price action."],
        watch_indicators=["Follow-up management guidance", "Volume reaction", "Next reported margin trend"],
        time_horizon="days to weeks",
        sources=source_models,
        disclaimer=DISCLAIMER,
    )
    findings = guard_investment_language(card.model_dump())
    if findings:
        raise ValueError("; ".join(findings))
    return card
```

`services/agent/app/providers/deepseek.py`:

```python
import httpx


class DeepSeekProvider:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
```

- [ ] **步骤 5：实现 gRPC server**

`services/agent/app/server.py`:

```python
from concurrent import futures
import os

import grpc

from app.graphs.event_analysis import analyze_event
from app.schemas import DISCLAIMER, Answer
from app.gen.investment.v1 import agent_pb2, agent_pb2_grpc, common_pb2


class AgentServicer(agent_pb2_grpc.AgentServiceServicer):
    def AnalyzeEvent(self, request, context):
        event = {
            "symbol": request.event.symbol,
            "title": request.event.title,
            "summary": request.event.summary,
        }
        sources = [
            {
                "title": source.title,
                "url": source.url,
                "publisher": source.publisher,
                "published_at": source.published_at,
                "provider": source.provider,
            }
            for source in request.sources
        ]
        card = analyze_event(event, sources)
        return agent_pb2.ResearchCardResult(
            symbol=card.symbol,
            event_title=card.event_title,
            stance=common_pb2.RESEARCH_STANCE_MIXED,
            confidence=common_pb2.CONFIDENCE_MEDIUM,
            summary=card.summary,
            key_points=card.key_points,
            counter_points=card.counter_points,
            watch_indicators=card.watch_indicators,
            time_horizon=card.time_horizon,
            sources=[common_pb2.Source(title=s.title, url=s.url, publisher=s.publisher, published_at=s.published_at, provider=s.provider) for s in card.sources],
            disclaimer=card.disclaimer,
        )

    def AnswerQuestion(self, request, context):
        answer = Answer(
            answer=f"Research view for {request.page_context.symbol}: {request.question}",
            sources=[],
            disclaimer=DISCLAIMER,
        )
        return agent_pb2.AnswerResult(answer=answer.answer, sources=[], disclaimer=answer.disclaimer)

    def SummarizeWatchlist(self, request, context):
        symbols = ", ".join(request.symbols)
        return agent_pb2.WatchlistSummaryResult(
            summary=f"Watchlist summary for {symbols}. Review high-priority events before drawing conclusions.",
            suggested_questions=["What changed today?", "Which event has the strongest source support?"],
            high_priority_symbols=[],
        )


def serve() -> None:
    port = os.getenv("AGENT_GRPC_PORT", "9010")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    agent_pb2_grpc.add_AgentServiceServicer_to_server(AgentServicer(), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
```

- [ ] **步骤 6：运行 Agent 测试**

运行：`cd services/agent && python -m pytest -q`

预期：所有测试通过，并且不发生外部模型调用。

- [ ] **步骤 7：提交**

```bash
git add services/agent
git commit -m "feat: add langgraph agent service skeleton"
```

## 任务 10：Research Service

**文件：**
- 创建：`backend/internal/service/research/service.go`
- 创建：`backend/internal/service/research/service_test.go`
- 创建：`backend/cmd/research-service/main.go`

- [ ] **步骤 1：编写研究卡片校验测试**

```go
package research

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestValidateCardRejectsTradingInstruction(t *testing.T) {
	card := Card{Summary: "Buy AAPL now", Disclaimer: "Not investment advice. For research only."}
	err := ValidateCard(card)
	require.ErrorContains(t, err, "prohibited trading instruction")
}
```

- [ ] **步骤 2：实现卡片校验**

```go
package research

import (
	"errors"
	"strings"
)

type Card struct {
	ID              string
	UserID          string
	EventID         string
	Symbol          string
	Stance          string
	Confidence      string
	Summary         string
	KeyPoints       []string
	CounterPoints   []string
	WatchIndicators []string
	TimeHorizon     string
	Disclaimer      string
	Priority        string
}

func ValidateCard(card Card) error {
	if card.Disclaimer == "" {
		return errors.New("research card disclaimer is required")
	}
	text := strings.ToLower(card.Summary + " " + strings.Join(card.KeyPoints, " "))
	for _, term := range []string{"buy", "sell", "add position", "reduce position", "买入", "卖出", "加仓", "减仓"} {
		if strings.Contains(text, term) {
			return errors.New("research card contains prohibited trading instruction")
		}
	}
	if card.Stance != "bullish" && card.Stance != "bearish" && card.Stance != "neutral" && card.Stance != "mixed" {
		return errors.New("research card stance is invalid")
	}
	return nil
}
```

- [ ] **步骤 3：实现 GenerateResearchCard 流程**

服务流程：

1. 接收 `GenerateResearchCardRequest`。
2. 从已存入 PostgreSQL 的 Event/Market Data 数据中加载事件来源。
3. 调用 Agent Service 的 `AnalyzeEvent`。
4. 校验 stance、confidence、disclaimer、禁用交易指令，以及至少一个 source。
5. 保存 `research_cards` 和 `research_sources`。
6. 如果 priority 是 `high`，调用 Notification Service 的 `CreateNotification`。

- [ ] **步骤 4：运行研究服务测试**

运行：`cd backend && go test ./internal/service/research`

预期：`PASS`。

- [ ] **步骤 5：提交**

```bash
git add backend/internal/service/research backend/cmd/research-service
git commit -m "feat: add research card generation service"
```

## 任务 11：Notification Service 与 Lark 推送

**文件：**
- 创建：`backend/internal/service/notification/service.go`
- 创建：`backend/internal/service/notification/feishu.go`
- 创建：`backend/internal/service/notification/service_test.go`
- 创建：`backend/cmd/notification-service/main.go`

- [ ] **步骤 1：编写通知路由测试**

```go
package notification

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestHighPriorityNotificationRequestsPush(t *testing.T) {
	sender := &FakeSender{}
	svc := NewService(NewMemoryRepository(), sender, "https://example.com/webhook")
	n, err := svc.Create(context.Background(), CreateInput{UserID: "user-1", ResearchCardID: "card-1", Title: "AAPL alert", Body: "Mixed research signal", Priority: "high", DetailURL: "http://localhost:3000/stocks/AAPL"})
	require.NoError(t, err)
	require.Equal(t, "sent", n.PushStatus)
	require.Len(t, sender.Messages, 1)
}
```

- [ ] **步骤 2：实现服务**

```go
package notification

import "context"

type CreateInput struct {
	UserID         string
	ResearchCardID string
	Title          string
	Body           string
	Priority       string
	DetailURL      string
}

type Notification struct {
	ID             string
	UserID         string
	ResearchCardID string
	Title          string
	Body           string
	Priority       string
	Read           bool
	PushStatus     string
	DetailURL      string
}

type PushSender interface {
	Send(ctx context.Context, webhookURL string, message PushMessage) error
}

type PushMessage struct {
	Title     string
	Body      string
	DetailURL string
}

type Service struct {
	repo       *MemoryRepository
	sender     PushSender
	webhookURL string
}

func NewService(repo *MemoryRepository, sender PushSender, webhookURL string) *Service {
	return &Service{repo: repo, sender: sender, webhookURL: webhookURL}
}

func (s *Service) Create(ctx context.Context, input CreateInput) (Notification, error) {
	n := Notification{ID: newID(), UserID: input.UserID, ResearchCardID: input.ResearchCardID, Title: input.Title, Body: input.Body, Priority: input.Priority, DetailURL: input.DetailURL, PushStatus: "not_required"}
	if input.Priority == "high" && s.webhookURL != "" {
		if err := s.sender.Send(ctx, s.webhookURL, PushMessage{Title: input.Title, Body: input.Body, DetailURL: input.DetailURL}); err != nil {
			n.PushStatus = "failed"
		} else {
			n.PushStatus = "sent"
		}
	}
	s.repo.Save(n)
	return n, nil
}
```

- [ ] **步骤 3：实现飞书 webhook sender**

发送如下 card payload：

```json
{
  "msg_type": "interactive",
  "card": {
    "header": { "title": { "tag": "plain_text", "content": "AAPL alert" } },
    "elements": [
      { "tag": "div", "text": { "tag": "lark_md", "content": "Mixed research signal" } },
      { "tag": "action", "actions": [{ "tag": "button", "text": { "tag": "plain_text", "content": "Open workbench" }, "url": "http://localhost:3000/stocks/AAPL" }] }
    ]
  }
}
```

- [ ] **步骤 4：运行通知测试**

运行：`cd backend && go test ./internal/service/notification`

预期：`PASS`。

- [ ] **步骤 5：提交**

```bash
git add backend/internal/service/notification backend/cmd/notification-service
git commit -m "feat: add notifications and lark push"
```

## 任务 12：BFF Dashboard、Watchlist、Research、Chat 与 Notifications API

**文件：**
- 修改：`backend/internal/bff/server.go`
- 创建：`backend/internal/bff/dto.go`
- 创建：`backend/internal/bff/chat.go`
- 修改：`backend/cmd/bff/main.go`

- [ ] **步骤 1：定义 HTTP DTO**

```go
package bff

type DashboardResponse struct {
	User          userDTO            `json:"user"`
	Watchlist     []WatchlistItemDTO  `json:"watchlist"`
	Notifications []NotificationDTO   `json:"notifications"`
	Summary       WatchlistSummaryDTO `json:"summary"`
}

type WatchlistItemDTO struct {
	ID        string        `json:"id"`
	Symbol    string        `json:"symbol"`
	Name      string        `json:"name"`
	Exchange  string        `json:"exchange"`
	Currency  string        `json:"currency"`
	Quote     MarketQuoteDTO `json:"quote"`
	SortOrder int           `json:"sortOrder"`
}

type MarketQuoteDTO struct {
	Price         float64 `json:"price"`
	Change        float64 `json:"change"`
	ChangePercent float64 `json:"changePercent"`
	MarketTime    string  `json:"marketTime"`
	Delayed       bool    `json:"delayed"`
	Provider      string  `json:"provider"`
}

type WatchlistSummaryDTO struct {
	Summary            string   `json:"summary"`
	SuggestedQuestions []string `json:"suggestedQuestions"`
}

type NotificationDTO struct {
	ID        string `json:"id"`
	Title     string `json:"title"`
	Body      string `json:"body"`
	Priority  string `json:"priority"`
	Read      bool   `json:"read"`
	CreatedAt string `json:"createdAt"`
}

type sourceDTO struct {
	Title       string `json:"title"`
	URL         string `json:"url"`
	Publisher   string `json:"publisher"`
	PublishedAt string `json:"publishedAt"`
	Provider    string `json:"provider"`
}
```

- [ ] **步骤 2：添加路由**

```go
r.Get("/api/dashboard", s.requireAuth(s.handleDashboard))
r.Post("/api/watchlist", s.requireAuth(s.handleAddWatchlist))
r.Delete("/api/watchlist/{symbol}", s.requireAuth(s.handleRemoveWatchlist))
r.Get("/api/stocks/{symbol}", s.requireAuth(s.handleStockDetail))
r.Get("/api/stocks/{symbol}/events", s.requireAuth(s.handleStockEvents))
r.Get("/api/stocks/{symbol}/research-cards", s.requireAuth(s.handleResearchCards))
r.Get("/api/research-cards/{id}", s.requireAuth(s.handleResearchCard))
r.Post("/api/chat", s.requireAuth(s.handleChat))
r.Get("/api/notifications", s.requireAuth(s.handleNotifications))
r.Post("/api/notifications/{id}/read", s.requireAuth(s.handleMarkNotificationRead))
```

- [ ] **步骤 3：实现 chat request/response**

```go
type chatRequest struct {
	ThreadID       string   `json:"threadId"`
	Question       string   `json:"question"`
	Symbol         string   `json:"symbol"`
	EventID        string   `json:"eventId"`
	ResearchCardID string  `json:"researchCardId"`
	Route          string   `json:"route"`
	ResearchCardIDs []string `json:"researchCardIds"`
}

type chatResponse struct {
	ThreadID   string      `json:"threadId"`
	MessageID  string      `json:"messageId"`
	Answer     string      `json:"answer"`
	Sources    []sourceDTO `json:"sources"`
	Disclaimer string      `json:"disclaimer"`
}
```

- [ ] **步骤 4：使用 fake service client 添加 API 测试**

运行：`cd backend && go test ./internal/bff`

预期：login route、auth middleware、dashboard route、add watchlist route、chat route、notification route 都能用 fake client 测试通过。

- [ ] **步骤 5：提交**

```bash
git add backend/internal/bff backend/cmd/bff
git commit -m "feat: add bff workbench api"
```

## 任务 13：Web 工作台

**文件：**
- 创建：`apps/web/package.json`
- 创建：`apps/web/eslint.config.mjs`
- 创建：`apps/web/next.config.ts`
- 创建：`apps/web/postcss.config.mjs`
- 创建：`apps/web/vitest.config.ts`
- 创建：`apps/web/tailwind.config.ts`
- 创建：`apps/web/app/layout.tsx`
- 创建：`apps/web/app/page.tsx`
- 创建：`apps/web/app/providers.tsx`
- 创建：`apps/web/app/globals.css`
- 创建：`apps/web/lib/api/client.ts`
- 创建：文件结构中列出的所有 feature component 文件

- [ ] **步骤 1：创建 web package**

```json
{
  "name": "web",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "next dev --hostname 0.0.0.0",
    "build": "next build",
    "start": "next start",
    "test": "vitest run",
    "lint": "eslint ."
  },
  "dependencies": {
    "@tanstack/react-query": "^5.90.0",
    "clsx": "^2.1.1",
    "lucide-react": "^0.545.0",
    "next": "^16.2.0",
    "recharts": "^3.2.0",
    "react": "^19.2.0",
    "react-dom": "^19.2.0"
  },
  "devDependencies": {
    "@types/node": "^24.0.0",
    "@types/react": "^19.2.0",
    "@types/react-dom": "^19.2.0",
    "eslint": "^9.37.0",
    "eslint-config-next": "^16.2.0",
    "autoprefixer": "^10.4.21",
    "jsdom": "^27.0.0",
    "postcss": "^8.5.6",
    "tailwindcss": "^3.4.18",
    "typescript": "^5.9.0",
    "vitest": "^3.2.0",
    "@testing-library/react": "^16.3.0",
    "@testing-library/jest-dom": "^6.9.0"
  }
}
```

- [ ] **步骤 2：添加 Next.js 和 Tailwind 配置**

`apps/web/next.config.ts`：

```ts
import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',
};

export default nextConfig;
```

`apps/web/eslint.config.mjs`：

```js
import { defineConfig, globalIgnores } from 'eslint/config';
import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores(['.next/**', 'next-env.d.ts']),
]);
```

`apps/web/tailwind.config.ts`：

```ts
import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './features/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};

export default config;
```

`apps/web/postcss.config.mjs`：

```js
const config = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};

export default config;
```

`apps/web/app/globals.css`：

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html,
body {
  min-height: 100%;
}

body {
  margin: 0;
  background: #0a0a0a;
}
```

- [ ] **步骤 3：实现 API client**

```ts
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8080';

export type LoginResponse = {
  user: { id: string; email: string };
  accessToken: string;
  expiresAt: string;
};

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('investment_access_token');
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ message: response.statusText }));
    throw new Error(body.message ?? 'Request failed');
  }
  return response.json() as Promise<T>;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}
```

- [ ] **步骤 4：实现 Next.js app shell**

`apps/web/app/providers.tsx`：

```tsx
'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

const queryClient = new QueryClient();

export function Providers({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
```

`apps/web/app/layout.tsx`：

```tsx
import './globals.css';
import type { ReactNode } from 'react';
import { Providers } from './providers';

export const metadata = {
  title: 'AI 投资助手',
  description: 'AI-first US stock research workbench',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
```

`apps/web/app/page.tsx`：

```tsx
'use client';

import { useEffect, useState } from 'react';
import { LoginPage } from '../features/auth/LoginPage';
import { Workbench } from '../features/dashboard/Workbench';

export default function Page() {
  const [token, setToken] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setToken(localStorage.getItem('investment_access_token'));
    setHydrated(true);
  }, []);

  if (!hydrated) {
    return <main className="min-h-screen bg-neutral-950" />;
  }

  return (
    <>
      {token ? (
        <Workbench onLogout={() => {
          localStorage.removeItem('investment_access_token');
          setToken(null);
        }} />
      ) : (
        <LoginPage onLogin={(accessToken) => {
          localStorage.setItem('investment_access_token', accessToken);
          setToken(accessToken);
        }} />
      )}
    </>
  );
}
```

- [ ] **步骤 5：实现响应式工作台布局**

桌面端布局使用 CSS grid：

```tsx
export function Workbench({ onLogout }: { onLogout: () => void }) {
  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100">
      <div className="hidden min-h-screen grid-cols-[360px_minmax(0,1fr)_320px] lg:grid">
        <ChatPanel />
        <StockDetail />
        <aside className="border-l border-neutral-800">
          <WatchlistPanel />
          <NotificationBell />
          <button className="m-4 rounded bg-neutral-800 px-3 py-2 text-sm" onClick={onLogout}>Sign out</button>
        </aside>
      </div>
      <div className="grid min-h-screen grid-rows-[1fr_64px] lg:hidden">
        <MobileTabs />
      </div>
    </main>
  );
}
```

移动端 tabs：`AI`、`股票`、`自选`、`消息`。选择某只股票时，将当前 symbol 存入组件状态，并传给 `ChatPanel` 上下文。

- [ ] **步骤 6：实现研究卡片免责声明**

```tsx
export function Disclaimer() {
  return (
    <p className="rounded border border-amber-500/30 bg-amber-500/10 p-3 text-xs leading-5 text-amber-100">
      内容不是投资建议，仅供研究参考。AI 输出可能包含推断，重要事实应回到来源核验。
    </p>
  );
}
```

- [ ] **步骤 7：添加组件测试**

测试名称：

```ts
it('shows login form before authentication')
it('renders desktop three-column workbench')
it('renders research disclaimer on cards')
it('keeps AI tab available on mobile')
```

运行：`pnpm --filter web test`

预期：所有测试通过。

- [ ] **步骤 8：提交**

```bash
git add apps/web package.json pnpm-workspace.yaml
git commit -m "feat: add responsive ai research workbench"
```

## 任务 14：Docker Compose 本地部署

**文件：**
- 创建：`backend/Dockerfile`
- 创建：`services/agent/Dockerfile`
- 创建：`apps/web/Dockerfile`
- 创建：`infra/docker-compose.yml`
- 创建：`docs/deploy/china-mainland.md`

- [ ] **步骤 1：添加 Go Dockerfile**

```dockerfile
FROM golang:1.26 AS build
WORKDIR /src
COPY backend/go.mod backend/go.sum ./backend/
COPY backend ./backend
WORKDIR /src/backend
ARG SERVICE_CMD
RUN go build -o /out/service ./cmd/${SERVICE_CMD}

FROM gcr.io/distroless/base-debian12
COPY --from=build /out/service /service
ENTRYPOINT ["/service"]
```

每个 Go 服务使用 `args: { SERVICE_CMD: "bff" }`、`user-service`、`watchlist-service`、`market-data-service`、`event-service`、`research-service`、`notification-service`、`scheduler-worker` 分别构建。

- [ ] **步骤 2：添加 Agent Dockerfile**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY services/agent ./
RUN pip install --no-cache-dir .
CMD ["python", "-m", "app.server"]
```

- [ ] **步骤 3：添加 Web Dockerfile**

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json pnpm-workspace.yaml ./
COPY apps/web ./apps/web
RUN corepack enable && pnpm install --filter web --frozen-lockfile=false
RUN pnpm --filter web build

FROM node:22-alpine AS runner
WORKDIR /app/apps/web
ENV NODE_ENV=production
ENV PORT=3000
COPY --from=build /app/apps/web/.next/standalone ./
COPY --from=build /app/apps/web/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
```

- [ ] **步骤 4：添加 Docker Compose**

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: investment
      POSTGRES_PASSWORD: investment
      POSTGRES_DB: investment
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U investment"]
      interval: 5s
      timeout: 3s
      retries: 20

  bff:
    build:
      context: ..
      dockerfile: backend/Dockerfile
      args: { SERVICE_CMD: bff }
    env_file: ../.env.example
    ports:
      - "8080:8080"
    depends_on:
      postgres: { condition: service_healthy }

  web:
    build:
      context: ..
      dockerfile: apps/web/Dockerfile
    ports:
      - "3000:3000"
    depends_on:
      - bff

  user-service:
    build: { context: .., dockerfile: backend/Dockerfile, args: { SERVICE_CMD: user-service } }
    env_file: ../.env.example
    depends_on: { postgres: { condition: service_healthy } }

  watchlist-service:
    build: { context: .., dockerfile: backend/Dockerfile, args: { SERVICE_CMD: watchlist-service } }
    env_file: ../.env.example
    depends_on: { postgres: { condition: service_healthy } }

  market-data-service:
    build: { context: .., dockerfile: backend/Dockerfile, args: { SERVICE_CMD: market-data-service } }
    env_file: ../.env.example

  event-service:
    build: { context: .., dockerfile: backend/Dockerfile, args: { SERVICE_CMD: event-service } }
    env_file: ../.env.example
    depends_on: { postgres: { condition: service_healthy } }

  research-service:
    build: { context: .., dockerfile: backend/Dockerfile, args: { SERVICE_CMD: research-service } }
    env_file: ../.env.example
    depends_on:
      postgres: { condition: service_healthy }
      agent-service: { condition: service_started }

  notification-service:
    build: { context: .., dockerfile: backend/Dockerfile, args: { SERVICE_CMD: notification-service } }
    env_file: ../.env.example
    depends_on: { postgres: { condition: service_healthy } }

  scheduler-worker:
    build: { context: .., dockerfile: backend/Dockerfile, args: { SERVICE_CMD: scheduler-worker } }
    env_file: ../.env.example
    depends_on:
      postgres: { condition: service_healthy }
      event-service: { condition: service_started }

  agent-service:
    build:
      context: ..
      dockerfile: services/agent/Dockerfile
    env_file: ../.env.example
```

- [ ] **步骤 5：添加中国内地部署 runbook**

```markdown
# 中国内地部署路径

第一条可部署路径保持容器化。

1. 先在国内云服务器上用 Docker Compose 构建并运行同一批镜像。
2. 从本地构建迁移前，先把镜像推送到国内容器镜像仓库。
3. 公网只暴露 `web` 和 `bff`。
4. Go gRPC 服务和 Python Agent Service 只放在私有网络内。
5. 在 BFF 前配置 HTTPS 和公网域名。
6. 将 PostgreSQL 迁移到托管云数据库，并开启自动备份。
7. 增加 Redis，用于缓存、锁、登录限流和短期状态。
8. 用云密钥管理替代明文 `.env`。
9. 增加结构化日志、指标、链路追踪和任务失败告警。
10. 公网发布前补齐邮箱验证、密码找回、登录限流和审计日志。

DeepSeek 仍然是第一版优先使用的 LLM provider，因为它在中国内地网络下更容易稳定访问。行情数据 provider 必须在 adapter 中支持超时、重试、缓存，并在 UI 上展示清晰的延迟数据标记。
```

- [ ] **步骤 6：运行 Compose smoke**

运行：`make compose-up`

预期：所有服务构建成功，PostgreSQL 进入 healthy 状态，`web` 可通过 `http://localhost:3000` 访问，BFF 健康检查端点返回 `200`。

- [ ] **步骤 7：提交**

```bash
git add backend/Dockerfile services/agent/Dockerfile apps/web/Dockerfile infra/docker-compose.yml docs/deploy/china-mainland.md
git commit -m "feat: add local docker compose deployment"
```

## 任务 15：端到端主路径

**文件：**
- 创建：`tests/e2e/smoke.spec.ts`
- 修改：`package.json`
- 修改：`apps/web/package.json`

- [ ] **步骤 1：添加 Playwright 测试依赖**

根目录 script：

```json
{
  "scripts": {
    "test:e2e": "playwright test"
  },
  "devDependencies": {
    "@playwright/test": "^1.56.0"
  }
}
```

- [ ] **步骤 2：编写 smoke test**

```ts
import { expect, test } from '@playwright/test';

test('user can log in, add a ticker, see research surfaces, and ask AI', async ({ page }) => {
  await page.goto('http://localhost:3000');
  await page.getByLabel('Email').fill('owner@example.com');
  await page.getByLabel('Password').fill('local-password-123');
  await page.getByRole('button', { name: 'Sign in' }).click();

  await expect(page.getByText('AI')).toBeVisible();
  await page.getByPlaceholder('Add ticker').fill('AAPL');
  await page.getByRole('button', { name: 'Add' }).click();
  await expect(page.getByText('AAPL')).toBeVisible();

  await page.getByPlaceholder('Ask about this context').fill('What changed and what should I watch next?');
  await page.getByRole('button', { name: 'Ask' }).click();
  await expect(page.getByText('not investment advice')).toBeVisible();
});
```

- [ ] **步骤 3：运行完整验证**

运行：`pnpm install`

运行：`make proto`

运行：`pnpm --filter web build`

运行：`cd backend && go test ./...`

运行：`cd services/agent && python -m pytest -q`

运行：`make compose-up`

运行：`pnpm test:e2e`

预期：所有命令都以 `0` 退出；Playwright 确认本地主路径可用。

- [ ] **步骤 4：提交**

```bash
git add tests/e2e package.json apps/web/package.json
git commit -m "test: add investment assistant e2e smoke path"
```

## 规格覆盖自查

- 桌面端和移动端响应式 Web 工作台：任务 13。
- 邮箱/密码登录与白名单：任务 5。
- 手动维护美股自选股：任务 7 和任务 12。
- 报价、K 线、公司信息、新闻/事件：任务 6 和任务 8。
- 轮询与 webhook-ready 事件入口：任务 8；webhook 使用同一个 `IngestRawEvent` RPC。
- 结构化 AI 研究卡片：任务 9 和任务 10。
- 上下文 AI 对话：任务 9 和任务 12。
- 站内通知和高优先级 Lark 推送：任务 11 和任务 12。
- PostgreSQL 持久化：任务 3。
- 多服务 Go 后端与 gRPC：任务 2、任务 4 到任务 12。
- Python Agent Service、LangGraph 和 LangChain：任务 9。
- DeepSeek provider 路径：任务 9 的 provider 文件与 env 契约。
- Docker Compose 本地部署：任务 14。
- 中国内地部署路径：任务 14 创建 `docs/deploy/china-mainland.md`。
- 测试策略：任务 5 到任务 15 覆盖单元测试、集成测试、组件测试和 e2e 检查。

## 最终验证命令

声明 v1 实现完成前运行这些命令：

```bash
pnpm install
make proto
pnpm --filter web test
pnpm --filter web build
cd backend && go test ./...
cd ../services/agent && python -m pytest -q
cd ../..
make compose-up
pnpm test:e2e
```

最终预期状态：所有测试通过，Docker Compose 在 `http://localhost:3000` 提供工作台，BFF 在 `http://localhost:8080/healthz` 提供健康检查，并且 e2e smoke test 覆盖登录、添加 `AAPL`、渲染研究界面、收到带研究用途免责声明的 AI 回答。
