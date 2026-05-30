# Backend Gin and Eino Graph Design

## Goal

Refactor the backend so the HTTP layer is explicitly Gin-based and the agent layer uses Eino as the real orchestration framework. The first implementation must keep the current chat API contract stable while making the agent runtime ready for future LangGraph-like graph configuration.

## Current State

- `backend/internal/api` already uses Gin for routes and JSON handling.
- `backend/internal/agent` exposes `NewEinoAgent`, but it currently wraps a hand-written DeepSeek/OpenAI-compatible streaming loop rather than Eino.
- `backend/internal/chat` depends on a small `Agent` interface and converts agent events into the current SSE protocol.
- The copied local `.env` remains ignored by git. Backend configuration must follow the existing variable names, especially `BFF_HTTP_ADDR` and `DEEPSEEK_*`.

## Non-Goals

- Do not change the frontend-facing REST or SSE protocol.
- Do not introduce `OPENAI_*` aliases.
- Do not build a full YAML/JSON graph DSL in this iteration.
- Do not add authentication, RAG, deployment, or investment-domain workflows in this iteration.

## Recommended Approach

Use Gin for HTTP, Eino's official Go builder style for the agent runtime, and an internal `GraphSpec` type as the compatibility seam for future LangGraph-like configuration.

This is the shortest path because Eino's documented workflow is code-first composition through ADK, `compose.NewGraph`, and component builders. A declarative config layer can be added later by parsing YAML/JSON into the same internal `GraphSpec` and compiling it through the same builder.

## Alternatives Considered

### Single Eino ChatModelAgent Only

Replace the current DeepSeek loop with one Eino ChatModelAgent and tools.

- Pros: fastest implementation.
- Cons: weak boundary for future configurable graph workflows; likely requires another refactor.

### External YAML Graph First

Define a LangGraph-like YAML/JSON schema first, then map it into Eino.

- Pros: looks closest to LangGraph immediately.
- Cons: locks schema before real workflows exist and diverges from Eino's code-first official path.

## Configuration

The backend uses the existing environment variable names:

- `BFF_HTTP_ADDR`: Gin server bind address, for example `:8081`.
- `DATABASE_URL`: PostgreSQL connection string.
- `DEEPSEEK_API_KEY`: DeepSeek API key.
- `DEEPSEEK_BASE_URL`: OpenAI-compatible DeepSeek base URL, default `https://api.deepseek.com`.
- `DEEPSEEK_MODEL`: model name, default aligned with local config.
- `DEEPSEEK_TIMEOUT_SECONDS`: model HTTP timeout.

`config.Load()` should normalize `BFF_HTTP_ADDR` as a full server address instead of appending another colon. The model timeout should come from `DEEPSEEK_TIMEOUT_SECONDS`; any old `HTTP_CLIENT_TIMEOUT_SECONDS` usage should be removed or kept only as an explicit backward-compatible fallback if needed.

## Architecture

### HTTP Layer

`backend/internal/api` remains the only HTTP adapter. It owns Gin route registration, local CORS, request validation, HTTP error mapping, and SSE writing.

The public API remains:

- `GET /api/health`
- `GET /api/conversations`
- `POST /api/conversations`
- `PATCH /api/conversations/:conversationId`
- `DELETE /api/conversations/:conversationId`
- `GET /api/conversations/:conversationId/messages`
- `PATCH /api/messages/:messageId`
- `POST /api/chat/stream`

### Chat Layer

`backend/internal/chat` remains the orchestration boundary for conversation persistence and SSE event ordering. It should continue to depend on a small agent interface rather than importing Eino directly.

This preserves the current invariant:

- Persist user message.
- Persist assistant message with `streaming` status.
- Emit `message_created`.
- Stream agent events as `reasoning`, `delta`, `tool_call`, and `tool_result`.
- Persist final assistant content and reasoning.
- Emit optional `title`.
- Emit `done` or `error`.

### Agent Layer

`backend/internal/agent` becomes a real Eino runtime adapter. It should:

- Create an Eino OpenAI ChatModel using DeepSeek's OpenAI-compatible API.
- Bind Eino tools converted from existing backend tools.
- Build the first runtime through Eino's Go builder or ADK.
- Convert Eino stream messages and tool events into the existing `agent.Event` contract.
- Keep deterministic fallback behavior for missing `DEEPSEEK_API_KEY` so local tests and frontend flows still work.

The exported constructor remains:

```go
func NewEinoAgent(cfg config.Config, registry tools.Registry) Agent
```

### Graph Runtime Seam

Introduce a small internal graph package or submodule under `backend/internal/agent` that defines:

```go
type GraphSpec struct {
    Name       string
    Entrypoint string
    Nodes      []NodeSpec
    Edges      []EdgeSpec
    Model      ModelSpec
    Tools      []ToolSpec
}
```

The first implementation may build one default graph in Go code. The important boundary is that the Eino runtime is created from `GraphSpec`, not hard-coded directly inside request handling.

Future YAML/JSON support should only need:

- Parse config file into `GraphSpec`.
- Validate node names, tool names, and edges.
- Compile `GraphSpec` through the same Eino builder.

### Tool Layer

Existing tools remain the source of business behavior:

- `web_search`
- `fetch_url`

They should be wrapped as Eino tools while preserving:

- Existing input names.
- Existing output shape where practical.
- Existing private-network fetch protections.
- Existing deterministic messages when external search is not configured.

## Data Flow

1. Gin receives `POST /api/chat/stream`.
2. `chat.Service` validates the request and persists conversation state.
3. `chat.Service` calls the `agent.Agent` interface with normalized message history.
4. Eino runtime streams model output and invokes tools when requested by the model.
5. `agent` adapter converts Eino output into current `agent.Event` values.
6. `chat.Service` persists content/tool invocations and writes current SSE events.
7. Gin SSE writer flushes each event to the frontend.

## Error Handling

- Invalid JSON and validation failures return `400` with `{"message": "..."}`
- Missing conversation or message rows return `404`.
- Unexpected backend errors return `500` without leaking internal details.
- Eino/model errors become stream `error` events and mark the assistant message `error`.
- Request cancellation finalizes the assistant message with collected partial content and exits without retrying.
- Missing `DEEPSEEK_API_KEY` uses deterministic fallback instead of failing startup.

## Testing

Add or update focused tests for:

- `config.Load()` reading `BFF_HTTP_ADDR` and `DEEPSEEK_TIMEOUT_SECONDS`.
- Gin router health, validation, and stream handler compatibility.
- Eino agent fallback behavior when `DEEPSEEK_API_KEY` is empty.
- Tool wrapper behavior for `web_search` and `fetch_url`.
- Chat service event ordering remains unchanged when agent emits deltas, reasoning, tool calls, and tool results.

External DeepSeek calls should not be required for automated tests.

## Verification

Run from `backend/`:

```bash
go test ./...
go build ./cmd/server
```

Manual smoke test with local dependencies:

```bash
go run ./cmd/server
curl http://localhost:8081/api/health
```

SSE smoke test should return `message_created`, `delta` or fallback content, optional tool events, optional `title`, and `done`.

## Open Decisions

- The first graph will be a single default chat-agent graph.
- Declarative YAML/JSON loading is intentionally deferred until there is a second workflow that justifies external configuration.
- The exact Eino API version should be pinned during implementation based on the current `go get` resolution and adjusted only if compile errors require it.
