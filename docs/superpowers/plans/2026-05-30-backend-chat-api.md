# Backend Chat API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Go backend required by the ChatGPT-like frontend plan: conversation CRUD, message persistence, SSE chat streaming, DeepSeek/Eino Agent integration, and `web_search` / `fetch_url` tool events.

**Architecture:** Add a new `backend/` Go service using Gin for HTTP, GORM for PostgreSQL persistence, and a small agent boundary that can run DeepSeek-compatible streaming with Eino/tool hooks. The API layer stays aligned with `web/features/chat/api.ts`; the chat layer owns SSE event ordering and persistence consistency.

**Tech Stack:** Go 1.25+, Gin, GORM, PostgreSQL/pgx, UUID, native `net/http`, Server-Sent Events, optional Eino adapter under `internal/agent`.

---

## File Structure

- `backend/go.mod`: Go module definition and dependencies.
- `backend/cmd/server/main.go`: service entrypoint.
- `backend/internal/config/config.go`: environment configuration.
- `backend/internal/store/models.go`: GORM models for conversations, messages, and tool invocations.
- `backend/internal/store/store.go`: database connection and AutoMigrate.
- `backend/internal/conversation/service.go`: conversation and message business logic.
- `backend/internal/chat/types.go`: frontend-compatible API and SSE DTOs.
- `backend/internal/chat/service.go`: chat stream orchestration.
- `backend/internal/agent/agent.go`: agent interface, DeepSeek/Eino-ready implementation, and fallback streaming.
- `backend/internal/tools/tools.go`: `web_search` and `fetch_url` tool implementations.
- `backend/internal/api/router.go`: Gin router and handlers.
- `backend/internal/api/sse.go`: SSE writer helper.
- `backend/internal/chat/service_test.go`: stream orchestration tests.
- `backend/internal/conversation/service_test.go`: CRUD and edit tests.

---

## Task 1: Initialize Backend Module

**Files:**
- Create: `backend/go.mod`
- Create: `backend/cmd/server/main.go`
- Create: `backend/internal/config/config.go`

- [ ] **Step 1: Create Go module**

Run:

```bash
cd /Users/bytedance/Desktop/ai-investment-assistant/.worktrees/backend-chat-api
mkdir -p backend/cmd/server backend/internal/config
cd backend
go mod init ai-investment-assistant/backend
go get github.com/gin-gonic/gin gorm.io/gorm gorm.io/driver/postgres github.com/google/uuid
```

Expected: `backend/go.mod` exists and `go get` exits with code `0`.

- [ ] **Step 2: Add config loader**

Create `backend/internal/config/config.go`:

```go
package config

import (
	"os"
	"strconv"
	"time"
)

type Config struct {
	Port              string
	DatabaseURL       string
	DeepSeekAPIKey    string
	DeepSeekBaseURL   string
	DeepSeekModel     string
	SearchAPIKey      string
	HTTPClientTimeout time.Duration
}

func Load() Config {
	return Config{
		Port:              getEnv("PORT", "8080"),
		DatabaseURL:       getEnv("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/ai_assistant?sslmode=disable"),
		DeepSeekAPIKey:    os.Getenv("DEEPSEEK_API_KEY"),
		DeepSeekBaseURL:   getEnv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
		DeepSeekModel:     getEnv("DEEPSEEK_MODEL", "deepseek-chat"),
		SearchAPIKey:      os.Getenv("SEARCH_API_KEY"),
		HTTPClientTimeout: time.Duration(getEnvInt("HTTP_CLIENT_TIMEOUT_SECONDS", 30)) * time.Second,
	}
}

func getEnv(key string, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func getEnvInt(key string, fallback int) int {
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
```

- [ ] **Step 3: Add entrypoint skeleton**

Create `backend/cmd/server/main.go`:

```go
package main

import (
	"log"

	"ai-investment-assistant/backend/internal/config"
)

func main() {
	cfg := config.Load()
	log.Printf("backend chat api listening on :%s", cfg.Port)
}
```

- [ ] **Step 4: Verify compile**

Run:

```bash
cd backend
go test ./...
```

Expected: exits with code `0`.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(backend): 初始化聊天后端 Go 模块"
```

---

## Task 2: Add Persistence Layer

**Files:**
- Create: `backend/internal/store/models.go`
- Create: `backend/internal/store/store.go`
- Create: `backend/internal/conversation/service.go`
- Create: `backend/internal/conversation/service_test.go`

- [ ] **Step 1: Write CRUD tests**

Create tests covering:

```go
func TestServiceCreatesAndRenamesConversation(t *testing.T)
func TestServiceDeletesConversation(t *testing.T)
func TestServiceEditsMessageAndDeletesFollowingMessages(t *testing.T)
```

Use SQLite only if a test-only driver is added; otherwise test repository-independent service helpers. Expected initial result: tests fail because service types do not exist.

- [ ] **Step 2: Implement models**

Models must include:

```go
type Conversation struct {
	ID        string `gorm:"primaryKey"`
	Title     string
	CreatedAt time.Time
	UpdatedAt time.Time
}

type Message struct {
	ID             string `gorm:"primaryKey"`
	ConversationID string `gorm:"index"`
	Role           string
	Content        string
	Reasoning      string
	Status         string
	CreatedAt      time.Time
}

type ToolInvocation struct {
	ID        string `gorm:"primaryKey"`
	MessageID string `gorm:"index"`
	ToolName  string
	Args      datatypes.JSON
	Result    datatypes.JSON
	Error     string
	LatencyMS int64
	Status    string
	CreatedAt time.Time
}
```

- [ ] **Step 3: Implement service**

Implement:

```go
ListConversations(ctx context.Context) ([]ChatConversation, error)
CreateConversation(ctx context.Context) (ChatConversation, error)
RenameConversation(ctx context.Context, id string, title string) (ChatConversation, error)
DeleteConversation(ctx context.Context, id string) error
ListMessages(ctx context.Context, conversationID string) ([]ChatMessage, error)
EditMessage(ctx context.Context, messageID string, content string) (ChatMessage, error)
```

- [ ] **Step 4: Verify persistence tests**

Run:

```bash
cd backend
go test ./internal/conversation -v
```

Expected: exits with code `0`.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(backend): 添加会话消息持久化"
```

---

## Task 3: Add REST API and Health Route

**Files:**
- Create: `backend/internal/api/router.go`
- Modify: `backend/cmd/server/main.go`

- [ ] **Step 1: Implement frontend-compatible routes**

Routes:

```txt
GET    /api/health
GET    /api/conversations
POST   /api/conversations
PATCH  /api/conversations/:conversationId
DELETE /api/conversations/:conversationId
GET    /api/conversations/:conversationId/messages
PATCH  /api/messages/:messageId
```

Request/response JSON field names must use camelCase: `createdAt`, `updatedAt`, `conversationId`, `messageId`, `toolInvocations`, `latencyMs`.

- [ ] **Step 2: Implement error responses**

Use:

```json
{"message":"human-readable error"}
```

Return `400` for invalid JSON or empty title/content, `404` for missing rows, and `500` for unexpected errors.

- [ ] **Step 3: Wire server**

`main.go` must connect DB, run migrations, create services, register router, and call `router.Run(":"+cfg.Port)`.

- [ ] **Step 4: Verify compile**

Run:

```bash
cd backend
go test ./...
go test ./... -run TestDoesNotExist
```

Expected: both commands exit with code `0`.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(backend): 暴露聊天 REST 接口"
```

---

## Task 4: Add SSE Chat Streaming

**Files:**
- Create: `backend/internal/chat/types.go`
- Create: `backend/internal/chat/service.go`
- Create: `backend/internal/api/sse.go`
- Modify: `backend/internal/api/router.go`
- Create: `backend/internal/chat/service_test.go`

- [ ] **Step 1: Define protocol DTOs**

Define:

```go
type StreamChatRequest struct {
	ConversationID           string `json:"conversationId"`
	Message                  string `json:"message"`
	ParentMessageID          string `json:"parentMessageId,omitempty"`
	RegenerateFromMessageID  string `json:"regenerateFromMessageId,omitempty"`
}

type StreamEvent struct {
	Type           string           `json:"type"`
	Message        *ChatMessage      `json:"message,omitempty"`
	MessageID      string           `json:"messageId,omitempty"`
	Text           string           `json:"text,omitempty"`
	Invocation     *ToolInvocation  `json:"invocation,omitempty"`
	ConversationID string           `json:"conversationId,omitempty"`
	Title          string           `json:"title,omitempty"`
}
```

- [ ] **Step 2: Implement SSE writer**

Write each event as:

```txt
data: {"type":"delta","messageId":"...","text":"..."}

```

Flush after every event. Stop cleanly when `request.Context()` is canceled.

- [ ] **Step 3: Implement chat orchestration**

`POST /api/chat/stream` must:

1. Validate `conversationId` and non-empty `message`.
2. Persist the user message.
3. Persist an assistant message with `status=streaming`.
4. Emit `message_created`.
5. Stream agent events into `delta`, `reasoning`, `tool_call`, `tool_result`.
6. Append final assistant content/reasoning to DB.
7. Emit `title` when conversation title is still `New chat`.
8. Emit `done`.
9. Emit `error` and mark assistant message `error` on failure.

- [ ] **Step 4: Verify stream tests**

Run:

```bash
cd backend
go test ./internal/chat -v
go test ./...
```

Expected: exits with code `0`.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(backend): 添加聊天 SSE 流"
```

---

## Task 5: Add Agent, DeepSeek, and Tools

**Files:**
- Create: `backend/internal/agent/agent.go`
- Create: `backend/internal/tools/tools.go`
- Modify: `backend/internal/chat/service.go`

- [ ] **Step 1: Define agent boundary**

Define an interface that chat service consumes:

```go
type Event struct {
	Kind       string
	Text       string
	ToolName   string
	ToolArgs   map[string]any
	ToolResult any
	ToolError  string
	LatencyMS  int64
}

type Agent interface {
	Stream(ctx context.Context, messages []Message) (<-chan Event, <-chan error)
}
```

- [ ] **Step 2: Implement tools**

`web_search`:

- If `SEARCH_API_KEY` is empty, return a deterministic result explaining search is not configured.
- If configured, use a simple HTTP client adapter that can later be pointed to Tavily/Brave.

`fetch_url`:

- Validate `http://` or `https://`.
- Fetch with timeout.
- Strip scripts/styles with a small HTML text extractor.
- Return `url`, `title` if found, and text summary.

- [ ] **Step 3: Implement DeepSeek-compatible streaming**

Use `POST {DEEPSEEK_BASE_URL}/chat/completions` with `stream=true`, `Authorization: Bearer <DEEPSEEK_API_KEY>`, and OpenAI-compatible streaming parsing. If `DEEPSEEK_API_KEY` is empty, use a deterministic local stream so frontend and tests can run without secrets.

- [ ] **Step 4: Add Eino integration seam**

Keep a dedicated constructor named:

```go
func NewEinoAgent(cfg config.Config, tools tools.Registry) Agent
```

It may wrap the DeepSeek-compatible implementation first, but the package boundary and tool event contract must be ready for Eino ReAct replacement without changing `chat.Service`.

- [ ] **Step 5: Verify agent tests**

Run:

```bash
cd backend
go test ./internal/agent ./internal/tools -v
go test ./...
```

Expected: exits with code `0`.

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "feat(backend): 接入聊天 Agent 与工具"
```

---

## Task 6: Final Verification

**Files:**
- Modify only files under `backend/` if verification finds issues.

- [ ] **Step 1: Run full backend verification**

```bash
cd backend
go test ./...
go build ./cmd/server
```

Expected: both commands exit with code `0`.

- [ ] **Step 2: Manual API smoke test**

With PostgreSQL running and `DATABASE_URL` configured:

```bash
cd backend
go run ./cmd/server
```

Then in another shell:

```bash
curl http://localhost:8080/api/health
curl -X POST http://localhost:8080/api/conversations
```

Expected: health returns `{"status":"ok"}` and conversation creation returns an object with `id`, `title`, `createdAt`, and `updatedAt`.

- [ ] **Step 3: Manual SSE smoke test**

```bash
curl -N \
  -H 'Content-Type: application/json' \
  -X POST http://localhost:8080/api/chat/stream \
  -d '{"conversationId":"<created-id>","message":"你好"}'
```

Expected: response contains `message_created`, one or more `delta`, optional tool events, optional `title`, and `done`.

- [ ] **Step 4: Commit final fixes**

Only if fixes were needed:

```bash
git add backend
git commit -m "fix(backend): 修正聊天后端验收问题"
```

---

## Self-Review

- Spec coverage: covers REST routes, SSE event protocol, persistence, title update, DeepSeek-compatible streaming, and `web_search` / `fetch_url` tool event output.
- Scope control: does not add login, upload, model UI, investment business, RAG, or deployment.
- Type consistency: response DTOs use frontend camelCase names; internal models may use Go field names.
- Risk note: the Eino constructor is intentionally isolated so current code can compile while preserving a replacement seam for exact Eino ReAct APIs.
