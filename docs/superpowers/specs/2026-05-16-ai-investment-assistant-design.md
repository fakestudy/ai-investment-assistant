# AI Investment Assistant v1 Design

## 1. Goal

AI Investment Assistant is a personal US-stock research workspace. It helps one user track a manual watchlist, understand important market and company events, inspect stock price trends, and ask follow-up questions through an AI-first interface.

The product is for research support only. It can provide a bullish, bearish, neutral, or mixed research stance with confidence, evidence, risks, and watch indicators. It must not provide direct buy, sell, add, or reduce-position instructions.

## 2. v1 Scope

### In Scope

- Responsive web workspace for desktop and mobile.
- Email + password login with an email allowlist.
- Manual US stock watchlist management.
- Stock quote, candle, and basic company information display.
- Selected market/news/company events from polling and webhook ingestion.
- Structured AI research cards for important events.
- AI chat that can answer questions with current stock, event, and research-card context.
- In-app notifications and high-priority Feishu/Lark push notifications.
- PostgreSQL persistence.
- Multi-service backend using gRPC between services.
- Python Agent Service implemented with LangGraph and LangChain.
- DeepSeek as the first LLM provider.
- Local Docker Compose deployment first, with a path to mainland China cloud deployment.

### Out of Scope

- Brokerage account connection.
- Real portfolio or position import.
- Order placement or trading execution.
- Direct trading advice.
- Multi-user team permission models.
- SaaS subscription and billing.
- Email verification code, password reset, and full login risk control.
- Production-grade compliance review.

## 3. Product Experience

### Desktop Layout

Desktop uses a three-column AI-first workspace:

- Left: AI chat panel. This is the primary entry point. It shows the current context, supports new conversations, and lets the user ask about the selected stock, event, or research card.
- Center: main research workspace. It shows the selected stock detail, price summary, chart, key indicators, event stream, research cards, and card details.
- Right: watchlist and alert panel. It shows manually added symbols, price movement, unread high-priority alerts, and a ticker add/search entry.

Opening the app should feel like entering an agent-anchored workspace rather than a traditional quote board. The AI panel can start with a daily watchlist summary and suggested follow-up questions.

### Mobile Layout

Mobile does not preserve the three-column layout. It uses a tabbed experience:

- AI
- Stock
- Watchlist
- Messages

When the user opens a stock, event, or research card, the AI entry remains easy to reach and should carry the current context into the chat.

## 4. Core User Flows

### Login

1. User enters email and password.
2. BFF calls User Service.
3. User Service checks the email allowlist and password hash.
4. BFF receives a session/JWT and returns the authenticated state to the frontend.

Email is the unique user identity. v1 does not implement email verification, but cloud deployment must add email verification, password reset, login rate limiting, and audit logs before public exposure.

### Add Watchlist Symbol

1. User searches or enters a US ticker.
2. BFF calls Watchlist Service.
3. Watchlist Service calls Market Data Service to resolve and normalize the symbol.
4. Watchlist Service saves the watchlist item and a stock metadata snapshot.

### Event Ingestion and Research Card Generation

1. Scheduler polls market data, news, and company-related sources for watchlist symbols.
2. Data-source webhooks, when available, enter through the same ingestion boundary.
3. Event Service normalizes, deduplicates, scores, and stores events.
4. Important events create analysis tasks.
5. Research Service calls Python Agent Service through gRPC.
6. Agent Service runs the LangGraph workflow and returns a structured research card.
7. Research Service validates and stores the card.
8. Notification Service creates in-app notifications and sends Feishu/Lark messages for high-priority cards.

### Contextual AI Chat

1. User asks a question in the left AI panel.
2. BFF sends the question plus user, symbol, event, page, and card context.
3. Agent Service retrieves relevant context and generates a sourced answer.
4. Chat messages are saved and remain tied to the user and stock context.

## 5. Architecture

### Runtime Topology

- Web frontend: React responsive web app.
- BFF / API Gateway: Go HTTP service for frontend APIs.
- User Service: Go gRPC service.
- Watchlist Service: Go gRPC service.
- Market Data Service: Go gRPC service.
- Event Service: Go gRPC service.
- Research Service: Go gRPC service.
- Notification Service: Go gRPC service.
- Scheduler Worker: Go background worker.
- Agent Service: Python gRPC service using LangGraph and LangChain.
- Database: PostgreSQL.
- Optional cache/coordination: Redis.

The frontend only calls the BFF over HTTP. It does not call gRPC directly. The BFF handles authentication, frontend DTO shaping, aggregation, and permission checks. Internal backend communication uses gRPC and protobuf.

### Service Responsibilities

#### BFF / API Gateway

- Exposes frontend HTTP APIs.
- Validates authentication state.
- Aggregates service responses for UI pages.
- Converts internal errors into frontend-safe responses.
- Avoids owning domain logic that belongs in internal services.

#### User Service

- Manages users, email allowlist, password hash, login, and sessions/JWT.
- Treats email as the unique identity.
- Does not send email verification codes in v1.

#### Watchlist Service

- Manages user watchlist items.
- Adds and removes symbols.
- Stores normalized symbol metadata for user watchlists.
- Calls Market Data Service to resolve symbols instead of trusting raw input.

#### Market Data Service

- Owns market-data provider integrations.
- Provides normalized symbol, quote, candle, and news APIs.
- Starts with free or low-cost providers.
- Keeps provider-specific payloads behind provider adapters.
- Supports later migration to paid APIs without changing business services.

#### Event Service

- Receives polling and webhook events.
- Stores raw payloads.
- Normalizes events into a stable internal model.
- Deduplicates repeated events.
- Scores event importance.
- Creates analysis tasks for important events.

#### Research Service

- Owns research-card lifecycle.
- Calls Agent Service for event analysis.
- Validates structured Agent output.
- Stores research cards and sources.
- Coordinates notification creation for high-priority cards.

#### Notification Service

- Owns in-app notifications and Feishu/Lark push delivery.
- Stores read/unread status and push status.
- Sends only high-priority external notifications.
- Keeps external push failures observable and retryable.

#### Scheduler Worker

- Runs polling jobs.
- Calls gRPC services instead of writing directly to another service's tables.
- Handles retry and backoff for collection tasks.

#### Agent Service

- Exposes gRPC methods for event analysis, question answering, and watchlist summary.
- Uses LangGraph as the workflow engine.
- Uses LangChain for model wrappers, tools, prompt handling, retrieval, and structured output.
- Calls DeepSeek through an LLM provider abstraction.

## 6. gRPC Boundary

v1 should define protobuf contracts for internal services. The most important contract boundary is between Go services and the Python Agent Service.

Example Agent RPCs:

- `AnalyzeEvent(AnalyzeEventRequest) returns (ResearchCardResult)`
- `AnswerQuestion(AnswerQuestionRequest) returns (AnswerResult)`
- `SummarizeWatchlist(SummarizeWatchlistRequest) returns (WatchlistSummaryResult)`

The Go backend must not depend on LangGraph internals. It only depends on protobuf contracts. Python can change graph nodes, prompts, tools, and model-provider implementations without breaking Go as long as the RPC schema remains stable.

The broader service graph should also use gRPC for learning backend service patterns. Services should define explicit request/response messages, status codes, deadlines, retry expectations, and error details.

## 7. Data Model

Core PostgreSQL tables:

- `users`: email, password hash, status, timestamps.
- `email_allowlist`: allowed email addresses.
- `sessions`: refresh tokens or session records if JWT refresh is persisted.
- `watchlist_items`: user, symbol, exchange, name, currency, sort order.
- `market_symbols`: normalized stock master data.
- `market_quotes`: quote snapshots.
- `market_candles`: historical or intraday candles.
- `raw_events`: source name, source event id, raw payload, received time.
- `normalized_events`: stable event model with symbol links, title, summary, source, published time, event type, and importance.
- `analysis_tasks`: event analysis status, retry count, error details.
- `research_cards`: structured AI research output.
- `research_sources`: source links and source metadata for each research card.
- `notifications`: in-app notification records, priority, read status.
- `feishu_push_configs`: Feishu/Lark webhook or bot configuration.
- `chat_threads`: user and optional symbol context.
- `chat_messages`: user and assistant messages with context references.

External provider raw payloads should be preserved for debugging and replay. Business logic should consume normalized models rather than provider-specific payloads.

## 8. Data Source Strategy

v1 uses free or low-cost market/news sources first, but the system must be designed with replaceable providers.

Provider abstractions:

- `MarketDataProvider`: symbol resolution, quotes, candles, company metadata.
- `NewsProvider`: news and company events.
- `WebhookProvider`: optional provider-specific webhook normalization.

Normalized fields should include:

- Symbol: symbol, name, exchange, currency.
- Candle: open, high, low, close, volume, timestamp, adjusted flag.
- Quote: price, change, change percent, market time, delay indicator.
- News/event: title, summary, source, published time, related symbols, URL, importance.

Known migration risks:

- Split, dividend, and adjusted-price semantics.
- Symbol format differences such as `BRK.B` versus `BRK-B`.
- Delayed versus real-time data labeling.
- News licensing limits.
- Free-provider rate limits and instability.

The UI and database should expose data delay and source metadata where relevant.

## 9. Agent Design With LangGraph

LangGraph is the main orchestration layer. LangChain supplies model integration, tools, prompts, retrieval, and structured-output utilities.

### Graphs

#### EventAnalysisGraph

Purpose: convert important events into structured research cards.

Flow:

1. `validate_event`
2. `load_context`
3. `retrieve_sources`
4. `rank_sources`
5. `reason_with_llm`
6. `schema_validate`
7. `risk_guardrail`
8. `output_card`

#### QuestionAnswerGraph

Purpose: answer user questions with current stock, page, event, and research-card context.

Flow:

1. `normalize_question`
2. `load_page_context`
3. `retrieve_related_cards`
4. `answer_with_sources`
5. `guardrail`
6. `output_answer`

#### WatchlistSummaryGraph

Purpose: produce a daily or on-demand summary of the user's watchlist.

Flow:

1. `load_watchlist`
2. `collect_recent_events`
3. `group_by_symbol`
4. `summarize`
5. `rank_notifications`

#### EventRankGraph

Purpose: improve event importance ranking. This can be deferred if v1 starts with rule-based scoring.

### Agent State

Agent state should be explicitly typed and include:

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

### Research Card Schema

Research cards should be structured:

- `symbol`
- `event_title`
- `stance`: bullish, bearish, neutral, or mixed.
- `confidence`: low, medium, or high.
- `summary`
- `key_points`
- `counter_points`
- `watch_indicators`
- `time_horizon`
- `sources`
- `disclaimer`

All important claims should reference sources. If the model is making an inference, the output should mark it as an inference rather than a confirmed fact.

## 10. Risk and Compliance Guardrails

Allowed:

- Explain what happened.
- Explain possible impact paths.
- Provide bullish, bearish, neutral, or mixed research stance.
- Provide confidence, risks, and follow-up indicators.
- Compare different interpretations.

Disallowed:

- Direct buy, sell, add, or reduce-position commands.
- Guaranteed return claims.
- Unsupported factual claims.
- Pretending delayed data is real-time.
- Hiding uncertainty.

The UI should show a clear research disclaimer on AI answers and research cards: this is not investment advice and is for research reference only.

## 11. Feishu/Lark Push

Feishu/Lark is the first external notification channel. It is only for high-priority reminders. The in-app notification center remains the complete source of record.

Push message content:

- Symbol and company name.
- Event title.
- AI one-line summary.
- Stance.
- Confidence.
- Key risk.
- Link to workspace detail page.

Each push should link to a stored `notification_id` and `research_card_id`. Push state should be persisted for retry, debugging, and duplicate prevention.

## 12. Local Deployment

v1 local deployment uses Docker Compose.

Services:

- `web`
- `bff`
- `user-service`
- `watchlist-service`
- `market-data-service`
- `event-service`
- `research-service`
- `notification-service`
- `scheduler-worker`
- `agent-service`
- `postgres`
- optional `redis`

Each service should have its own Dockerfile, health check, configuration, and logs. Configuration is injected through `.env`, including:

- DeepSeek API key.
- Feishu webhook or bot config.
- Database connection.
- Email allowlist.
- Password/session secrets.
- Data-source provider config.
- Polling intervals.

## 13. Mainland China Cloud Deployment Path

The first deployable path should remain container-based.

Recommended evolution:

1. Start with a mainland cloud VM running Docker Compose.
2. Move images to a mainland-accessible container registry.
3. Expose only the BFF and web service publicly.
4. Keep gRPC services on private networking.
5. Put HTTPS and domain routing in front of the BFF.
6. Move PostgreSQL to a managed cloud database with backups.
7. Add Redis for cache, locks, rate limiting, and short-lived state.
8. Add secret management instead of plain `.env`.
9. Add observability: structured logs, metrics, traces, and task failure alerts.

China-specific concerns:

- Prefer DeepSeek or another mainland-accessible LLM provider.
- Financial data providers may be unstable from mainland networks; provider adapters need timeouts, retries, caching, and proxy support.
- Feishu push must be reachable from the cloud environment.
- Dependency and image pulls should use mainland mirrors or registries.
- Public deployment must add email verification, password reset, login rate limiting, and audit logs.

## 14. Testing Strategy

Frontend:

- Component tests for main panels and research-card rendering.
- Responsive layout tests for desktop and mobile.
- Basic end-to-end tests for login, watchlist, stock detail, and AI chat entry.

BFF:

- HTTP API integration tests.
- Authentication and permission tests.
- Error mapping tests.

Go gRPC services:

- Proto contract tests.
- Service unit tests.
- Repository tests.
- gRPC deadline and error-detail tests.

Python Agent:

- LangGraph node unit tests.
- Golden cases for event analysis and question answering.
- Structured output schema validation tests.
- Guardrail tests for disallowed trading-advice prompts.
- Mock DeepSeek provider tests.

Data providers:

- Mock provider tests.
- Real provider smoke tests.
- Rate-limit and failure fallback tests.

End to end:

- Docker Compose starts all services.
- User logs in.
- User adds a ticker.
- Scheduler ingests an event.
- Research card is generated.
- In-app notification is created.
- Feishu push is mocked or sent in a controlled test mode.

## 15. Implementation Order

1. Repository and monorepo skeleton.
2. Proto definitions and code generation.
3. PostgreSQL schema migrations.
4. User Service and BFF login.
5. Watchlist Service and symbol resolution.
6. Market Data Service with mock provider, then first real free/low-cost provider.
7. Event Service ingestion with polling path.
8. Research Service and Python Agent gRPC skeleton.
9. LangGraph EventAnalysisGraph with DeepSeek provider.
10. Research-card persistence and display.
11. AI chat flow with context.
12. Notification Service and in-app notifications.
13. Feishu/Lark push.
14. Webhook ingestion.
15. Docker Compose hardening and full e2e smoke test.

## 16. Open Decisions

The following decisions are intentionally deferred to implementation planning:

- Exact frontend framework choice within React, such as Vite or Next.js.
- Exact Go gRPC framework and code-generation layout.
- First free or low-cost market/news provider.
- Whether Redis is included in v1 or added after the first working flow.
- Whether chat streaming is required in the first implementation milestone.

These decisions do not change the approved product and architecture boundary.
