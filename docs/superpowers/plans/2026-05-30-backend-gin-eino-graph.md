# Backend Gin 与 Eino Graph 改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 backend 改造成明确的 Gin HTTP 服务，并把 Agent 层从手写 DeepSeek streaming/tool loop 替换为真正基于 Eino ChatModel/Tool/Graph seam 的运行时。

**Architecture:** HTTP 层继续由 `backend/internal/api` 的 Gin router 承担，前端 REST/SSE 协议不变。`backend/internal/chat` 继续只依赖 `agent.Agent` 接口，`backend/internal/agent` 内部新增 `GraphSpec` 和 Eino runtime，把 DeepSeek OpenAI-compatible 配置、Eino OpenAI ChatModel、Eino tool wrapper 编译成默认 chat-agent graph。第一版不实现 YAML/JSON 加载，但 runtime 必须从 `GraphSpec` 创建，为后续类 LangGraph 声明式配置预留入口。

**Tech Stack:** Go 1.25、Gin、GORM、PostgreSQL、SSE、`github.com/cloudwego/eino`、`github.com/cloudwego/eino-ext/components/model/openai`、DeepSeek OpenAI-compatible API。

---

## 文件结构

- Modify: `backend/internal/config/config.go`：对齐 `.env`，使用 `BFF_HTTP_ADDR` 和 `DEEPSEEK_TIMEOUT_SECONDS`。
- Modify: `backend/internal/config/config_test.go`：覆盖配置读取和旧变量不再作为主路径。
- Modify: `backend/cmd/server/main.go`：`http.Server.Addr` 直接使用完整地址。
- Modify: `backend/cmd/server/main_test.go`：验证 `:8081` / `:9090` 地址不被重复拼接冒号。
- Modify: `backend/go.mod`、`backend/go.sum`：加入 Eino 和 Eino OpenAI model 依赖。
- Create: `backend/internal/agent/graph_spec.go`：定义 `GraphSpec`、`NodeSpec`、`EdgeSpec`、`ModelSpec`、`ToolSpec` 和默认 graph。
- Create: `backend/internal/agent/graph_spec_test.go`：验证默认 graph 的 entrypoint、model、tool 和 edge。
- Create: `backend/internal/tools/eino.go`：把现有 `tools.Registry` 包装为 Eino `tool.InvokableTool`。
- Create: `backend/internal/tools/eino_test.go`：验证 Eino tool wrapper 的 schema、调用结果和错误语义。
- Modify: `backend/internal/agent/agent.go`：保留 `Agent` 接口和 fallback，删除手写 DeepSeek HTTP streaming 主路径，改为调用 Eino runtime。
- Create: `backend/internal/agent/eino_runtime.go`：创建 Eino OpenAI ChatModel、绑定 tools、执行默认 graph/runtime。
- Create: `backend/internal/agent/eino_runtime_test.go`：用 fake Eino model 验证事件转换、tool call、tool result 和 fallback，不依赖真实 DeepSeek。
- Modify: `backend/internal/agent/agent_test.go`：删除对手写 DeepSeek parser 的耦合测试，保留外部可观察的 `Agent` 行为测试。
- Modify: `backend/internal/chat/service_test.go`：保持现有 fake agent 测试，确认 SSE 事件顺序不变。

---

## Task 1: 修正 `.env` 配置和 Gin server 地址

**Files:**
- Modify: `backend/internal/config/config.go`
- Modify: `backend/internal/config/config_test.go`
- Modify: `backend/cmd/server/main.go`
- Modify: `backend/cmd/server/main_test.go`

- [ ] **Step 1: 写失败测试，锁定 `BFF_HTTP_ADDR` 和 `DEEPSEEK_TIMEOUT_SECONDS`**

在 `backend/internal/config/config_test.go` 中把 `PORT` 改成 `BFF_HTTP_ADDR`，把 `HTTP_CLIENT_TIMEOUT_SECONDS` 改成 `DEEPSEEK_TIMEOUT_SECONDS`：

```go
func TestLoadUsesDefaults(t *testing.T) {
	t.Setenv("BFF_HTTP_ADDR", "")
	t.Setenv("DATABASE_URL", "")
	t.Setenv("DEEPSEEK_API_KEY", "")
	t.Setenv("DEEPSEEK_BASE_URL", "")
	t.Setenv("DEEPSEEK_MODEL", "")
	t.Setenv("DEEPSEEK_TIMEOUT_SECONDS", "")
	t.Setenv("SEARCH_API_KEY", "")
	t.Setenv("SEARCH_BASE_URL", "")
	t.Setenv("FETCH_ALLOW_PRIVATE", "")

	cfg := Load()

	if cfg.HTTPAddr != ":8081" {
		t.Fatalf("HTTPAddr = %q, want %q", cfg.HTTPAddr, ":8081")
	}
	if cfg.DatabaseURL != "postgres://investment:investment@postgres:5432/investment?sslmode=disable" {
		t.Fatalf("DatabaseURL = %q", cfg.DatabaseURL)
	}
	if cfg.DeepSeekBaseURL != "https://api.deepseek.com" {
		t.Fatalf("DeepSeekBaseURL = %q", cfg.DeepSeekBaseURL)
	}
	if cfg.DeepSeekModel != "deepseek-v4-pro" {
		t.Fatalf("DeepSeekModel = %q", cfg.DeepSeekModel)
	}
	if cfg.HTTPClientTimeout != 60*time.Second {
		t.Fatalf("HTTPClientTimeout = %s, want %s", cfg.HTTPClientTimeout, 60*time.Second)
	}
}

func TestLoadUsesEnvironmentOverrides(t *testing.T) {
	t.Setenv("BFF_HTTP_ADDR", ":9090")
	t.Setenv("DATABASE_URL", "postgres://example")
	t.Setenv("DEEPSEEK_API_KEY", "deepseek-key")
	t.Setenv("DEEPSEEK_BASE_URL", "https://example.com")
	t.Setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
	t.Setenv("DEEPSEEK_TIMEOUT_SECONDS", "7")
	t.Setenv("SEARCH_API_KEY", "search-key")
	t.Setenv("SEARCH_BASE_URL", "https://search.example.com")
	t.Setenv("FETCH_ALLOW_PRIVATE", "true")

	cfg := Load()

	if cfg.HTTPAddr != ":9090" {
		t.Fatalf("HTTPAddr = %q, want %q", cfg.HTTPAddr, ":9090")
	}
	if cfg.DatabaseURL != "postgres://example" {
		t.Fatalf("DatabaseURL = %q", cfg.DatabaseURL)
	}
	if cfg.DeepSeekAPIKey != "deepseek-key" {
		t.Fatalf("DeepSeekAPIKey = %q", cfg.DeepSeekAPIKey)
	}
	if cfg.DeepSeekBaseURL != "https://example.com" {
		t.Fatalf("DeepSeekBaseURL = %q", cfg.DeepSeekBaseURL)
	}
	if cfg.DeepSeekModel != "deepseek-v4-pro" {
		t.Fatalf("DeepSeekModel = %q", cfg.DeepSeekModel)
	}
	if cfg.HTTPClientTimeout != 7*time.Second {
		t.Fatalf("HTTPClientTimeout = %s, want %s", cfg.HTTPClientTimeout, 7*time.Second)
	}
	if cfg.SearchAPIKey != "search-key" {
		t.Fatalf("SearchAPIKey = %q", cfg.SearchAPIKey)
	}
	if cfg.SearchBaseURL != "https://search.example.com" {
		t.Fatalf("SearchBaseURL = %q", cfg.SearchBaseURL)
	}
	if !cfg.FetchAllowPrivate {
		t.Fatal("FetchAllowPrivate = false, want true")
	}
}
```

- [ ] **Step 2: 运行配置测试，确认先失败**

Run:

```bash
cd backend
go test ./internal/config -v
```

Expected: FAIL，错误包含 `cfg.HTTPAddr undefined` 或 timeout 仍读取旧变量。

- [ ] **Step 3: 修改配置结构和 loader**

把 `backend/internal/config/config.go` 中的 `Port` 改为 `HTTPAddr`：

```go
type Config struct {
	HTTPAddr          string
	DatabaseURL       string
	DeepSeekAPIKey    string
	DeepSeekBaseURL   string
	DeepSeekModel     string
	SearchAPIKey      string
	SearchBaseURL     string
	FetchAllowPrivate bool
	HTTPClientTimeout time.Duration
}

func Load() Config {
	return Config{
		HTTPAddr:          getEnv("BFF_HTTP_ADDR", ":8081"),
		DatabaseURL:       getEnv("DATABASE_URL", "postgres://investment:investment@postgres:5432/investment?sslmode=disable"),
		DeepSeekAPIKey:    os.Getenv("DEEPSEEK_API_KEY"),
		DeepSeekBaseURL:   getEnv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
		DeepSeekModel:     getEnv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
		SearchAPIKey:      os.Getenv("SEARCH_API_KEY"),
		SearchBaseURL:     os.Getenv("SEARCH_BASE_URL"),
		FetchAllowPrivate: getEnvBool("FETCH_ALLOW_PRIVATE", false),
		HTTPClientTimeout: time.Duration(getEnvInt("DEEPSEEK_TIMEOUT_SECONDS", 60)) * time.Second,
	}
}
```

- [ ] **Step 4: 修改 server 地址拼接**

把 `backend/cmd/server/main.go` 中日志和 `newHTTPServer` 改成直接使用 `cfg.HTTPAddr`：

```go
func main() {
	cfg := config.Load()
	log.Printf("backend chat api listening on %s", cfg.HTTPAddr)

	db, err := store.OpenPostgres(context.Background(), cfg.DatabaseURL)
	if err != nil {
		log.Fatalf("open database: %v", err)
	}

	conversationService := conversation.NewService(db)
	toolRegistry := tools.NewRegistry(cfg)
	chatService := chat.NewService(conversationService, agent.NewEinoAgent(cfg, toolRegistry))
	router := api.NewRouter(conversationService, chatService)
	if err := newHTTPServer(cfg, router).ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("run server: %v", err)
	}
}

func newHTTPServer(cfg config.Config, handler http.Handler) *http.Server {
	return &http.Server{
		Addr:              cfg.HTTPAddr,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      0,
		IdleTimeout:       120 * time.Second,
	}
}
```

- [ ] **Step 5: 更新 server 测试**

把 `backend/cmd/server/main_test.go` 的构造改成：

```go
server := newHTTPServer(config.Config{HTTPAddr: ":9090"}, http.NewServeMux())

if server.Addr != ":9090" {
	t.Fatalf("Addr = %q, want :9090", server.Addr)
}
```

- [ ] **Step 6: 运行测试**

Run:

```bash
cd backend
go test ./internal/config ./cmd/server -v
```

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add backend/internal/config/config.go backend/internal/config/config_test.go backend/cmd/server/main.go backend/cmd/server/main_test.go
git commit -m "fix(backend): 对齐本地环境变量配置"
```

---

## Task 2: 引入 Eino 依赖并保持可编译

**Files:**
- Modify: `backend/go.mod`
- Modify: `backend/go.sum`

- [ ] **Step 1: 添加依赖**

Run:

```bash
cd backend
go get github.com/cloudwego/eino@latest
go get github.com/cloudwego/eino-ext/components/model/openai@latest
go mod tidy
```

Expected: `go.mod` 出现 `github.com/cloudwego/eino` 和 `github.com/cloudwego/eino-ext/components/model/openai` 相关依赖。

- [ ] **Step 2: 确认解析版本**

Run:

```bash
cd backend
go list -m github.com/cloudwego/eino github.com/cloudwego/eino-ext/components/model/openai
```

Expected: 输出两个模块及版本号，版本号由 Go module resolver 固定到 `go.mod` / `go.sum`。

- [ ] **Step 3: 运行现有测试**

Run:

```bash
cd backend
go test ./...
```

Expected: PASS。此任务只引依赖，不改业务行为。

- [ ] **Step 4: 提交**

```bash
git add backend/go.mod backend/go.sum
git commit -m "chore(backend): 引入 Eino 依赖"
```

---

## Task 3: 增加 `GraphSpec` 运行时边界

**Files:**
- Create: `backend/internal/agent/graph_spec.go`
- Create: `backend/internal/agent/graph_spec_test.go`

- [ ] **Step 1: 写 `GraphSpec` 测试**

创建 `backend/internal/agent/graph_spec_test.go`：

```go
package agent

import "testing"

func TestDefaultChatGraphSpec(t *testing.T) {
	spec := DefaultChatGraphSpec()

	if spec.Name != "default_chat_agent" {
		t.Fatalf("Name = %q, want default_chat_agent", spec.Name)
	}
	if spec.Entrypoint != "chat_model" {
		t.Fatalf("Entrypoint = %q, want chat_model", spec.Entrypoint)
	}
	if spec.Model.Provider != "deepseek_openai_compatible" {
		t.Fatalf("Model.Provider = %q", spec.Model.Provider)
	}
	if len(spec.Tools) != 2 {
		t.Fatalf("Tools len = %d, want 2", len(spec.Tools))
	}
	if spec.Tools[0].Name != "web_search" || spec.Tools[1].Name != "fetch_url" {
		t.Fatalf("Tools = %+v, want web_search and fetch_url", spec.Tools)
	}
	if len(spec.Edges) != 1 {
		t.Fatalf("Edges len = %d, want 1", len(spec.Edges))
	}
	if spec.Edges[0].From != "chat_model" || spec.Edges[0].To != "tools" {
		t.Fatalf("Edge = %+v, want chat_model -> tools", spec.Edges[0])
	}
}
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd backend
go test ./internal/agent -run TestDefaultChatGraphSpec -v
```

Expected: FAIL，错误包含 `undefined: DefaultChatGraphSpec`。

- [ ] **Step 3: 实现 `GraphSpec`**

创建 `backend/internal/agent/graph_spec.go`：

```go
package agent

type GraphSpec struct {
	Name       string
	Entrypoint string
	Nodes      []NodeSpec
	Edges      []EdgeSpec
	Model      ModelSpec
	Tools      []ToolSpec
}

type NodeSpec struct {
	Name string
	Kind string
}

type EdgeSpec struct {
	From      string
	To        string
	Condition string
}

type ModelSpec struct {
	Provider string
}

type ToolSpec struct {
	Name string
}

func DefaultChatGraphSpec() GraphSpec {
	return GraphSpec{
		Name:       "default_chat_agent",
		Entrypoint: "chat_model",
		Nodes: []NodeSpec{
			{Name: "chat_model", Kind: "chat_model"},
			{Name: "tools", Kind: "tools"},
		},
		Edges: []EdgeSpec{
			{From: "chat_model", To: "tools", Condition: "model_requests_tool"},
		},
		Model: ModelSpec{Provider: "deepseek_openai_compatible"},
		Tools: []ToolSpec{
			{Name: "web_search"},
			{Name: "fetch_url"},
		},
	}
}
```

- [ ] **Step 4: 运行 agent 测试**

Run:

```bash
cd backend
go test ./internal/agent -run TestDefaultChatGraphSpec -v
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/internal/agent/graph_spec.go backend/internal/agent/graph_spec_test.go
git commit -m "feat(backend): 增加 Eino GraphSpec 边界"
```

---

## Task 4: 把现有 tools 包装为 Eino tools

**Files:**
- Create: `backend/internal/tools/eino.go`
- Create: `backend/internal/tools/eino_test.go`

- [ ] **Step 1: 写 Eino tool wrapper 测试**

创建 `backend/internal/tools/eino_test.go`：

```go
package tools_test

import (
	"context"
	"strings"
	"testing"
	"time"

	"ai-investment-assistant/backend/internal/config"
	"ai-investment-assistant/backend/internal/tools"
)

func TestRegistryBuildsEinoTools(t *testing.T) {
	registry := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second})

	einoTools, err := registry.EinoTools(context.Background())
	if err != nil {
		t.Fatalf("EinoTools() error = %v", err)
	}
	if len(einoTools) != 2 {
		t.Fatalf("EinoTools len = %d, want 2", len(einoTools))
	}
	names := map[string]bool{}
	for _, item := range einoTools {
		info, err := item.Info(context.Background())
		if err != nil {
			t.Fatalf("Info() error = %v", err)
		}
		names[info.Name] = true
	}
	if !names["web_search"] || !names["fetch_url"] {
		t.Fatalf("tool names = %+v, want web_search and fetch_url", names)
	}
}

func TestEinoWebSearchToolUsesExistingRegistryBehavior(t *testing.T) {
	registry := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second})
	einoTools, err := registry.EinoTools(context.Background())
	if err != nil {
		t.Fatalf("EinoTools() error = %v", err)
	}
	webSearch := requireEinoTool(t, einoTools, "web_search")

	output, err := webSearch.InvokableRun(context.Background(), `{"query":"AI moats"}`)
	if err != nil {
		t.Fatalf("InvokableRun(web_search) error = %v", err)
	}
	if !strings.Contains(output, `"configured":false`) {
		t.Fatalf("output = %s, want configured=false", output)
	}
}

func requireEinoTool(t *testing.T, items []tools.EinoInvokableTool, name string) tools.EinoInvokableTool {
	t.Helper()
	for _, item := range items {
		info, err := item.Info(context.Background())
		if err != nil {
			t.Fatalf("Info() error = %v", err)
		}
		if info.Name == name {
			return item
		}
	}
	t.Fatalf("tool %q not found", name)
	return nil
}
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd backend
go test ./internal/tools -run Eino -v
```

Expected: FAIL，错误包含 `registry.EinoTools undefined`。

- [ ] **Step 3: 实现 Eino tool wrapper**

创建 `backend/internal/tools/eino.go`：

```go
package tools

import (
	"context"

	einotool "github.com/cloudwego/eino/components/tool"
	toolutils "github.com/cloudwego/eino/components/tool/utils"
)

type EinoInvokableTool = einotool.InvokableTool

type webSearchInput struct {
	Query string `json:"query" jsonschema:"description=Search query for current market or company information,required"`
}

type fetchURLInput struct {
	URL string `json:"url" jsonschema:"description=HTTP or HTTPS URL to fetch,required"`
}

func (r Registry) EinoTools(ctx context.Context) ([]EinoInvokableTool, error) {
	webSearch, err := toolutils.InferTool(
		"web_search",
		"Search the web for current information.",
		func(ctx context.Context, input webSearchInput) (map[string]any, error) {
			return r.Execute(ctx, "web_search", map[string]any{"query": input.Query})
		},
	)
	if err != nil {
		return nil, err
	}

	fetchURL, err := toolutils.InferTool(
		"fetch_url",
		"Fetch an HTTP or HTTPS URL and extract visible title and text.",
		func(ctx context.Context, input fetchURLInput) (map[string]any, error) {
			return r.Execute(ctx, "fetch_url", map[string]any{"url": input.URL})
		},
	)
	if err != nil {
		return nil, err
	}

	return []EinoInvokableTool{webSearch, fetchURL}, nil
}
```

- [ ] **Step 4: 运行 tools 测试**

Run:

```bash
cd backend
go test ./internal/tools -v
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/internal/tools/eino.go backend/internal/tools/eino_test.go
git commit -m "feat(backend): 将工具包装为 Eino Tool"
```

---

## Task 5: 新增 Eino runtime 并替换手写 DeepSeek 主路径

**Files:**
- Modify: `backend/internal/agent/agent.go`
- Create: `backend/internal/agent/eino_runtime.go`
- Create: `backend/internal/agent/eino_runtime_test.go`

- [ ] **Step 1: 写 runtime fallback 测试**

创建 `backend/internal/agent/eino_runtime_test.go`，先覆盖不需要真实 DeepSeek 的 fallback：

```go
package agent

import (
	"context"
	"strings"
	"testing"
	"time"

	"ai-investment-assistant/backend/internal/config"
	"ai-investment-assistant/backend/internal/tools"
)

func TestNewEinoRuntimeWithoutAPIKeyUsesFallback(t *testing.T) {
	agentUnderTest := NewEinoAgent(config.Config{
		HTTPAddr:          ":8081",
		HTTPClientTimeout: time.Second,
	}, tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}))

	events, errs := agentUnderTest.Stream(context.Background(), []Message{
		{Role: "user", Content: "Explain AI moats"},
	})
	collected := collectRuntimeEvents(t, events, errs)

	if len(collected) == 0 {
		t.Fatal("events len = 0, want fallback delta")
	}
	if collected[0].Kind != "delta" {
		t.Fatalf("first event kind = %q, want delta", collected[0].Kind)
	}
	if !strings.Contains(collected[0].Text, "Explain AI moats") {
		t.Fatalf("fallback text = %q, want prompt echo", collected[0].Text)
	}
}

func collectRuntimeEvents(t *testing.T, events <-chan Event, errs <-chan error) []Event {
	t.Helper()
	var collected []Event
	for events != nil || errs != nil {
		select {
		case event, ok := <-events:
			if !ok {
				events = nil
				continue
			}
			collected = append(collected, event)
		case err, ok := <-errs:
			if !ok {
				errs = nil
				continue
			}
			if err != nil {
				t.Fatalf("agent error = %v", err)
			}
		case <-time.After(time.Second):
			t.Fatalf("timed out collecting events: %+v", collected)
		}
	}
	return collected
}
```

- [ ] **Step 2: 写 runtime 构建测试**

在同一文件追加：

```go
func TestBuildEinoRuntimeRequiresDeepSeekConfig(t *testing.T) {
	_, err := NewEinoRuntime(context.Background(), config.Config{
		DeepSeekAPIKey:    "test-key",
		DeepSeekBaseURL:   "https://api.deepseek.com",
		DeepSeekModel:     "deepseek-v4-pro",
		HTTPClientTimeout: time.Second,
	}, tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}), DefaultChatGraphSpec())
	if err != nil {
		t.Fatalf("NewEinoRuntime() error = %v", err)
	}
}
```

- [ ] **Step 3: 运行测试确认失败**

Run:

```bash
cd backend
go test ./internal/agent -run 'TestNewEinoRuntime|TestBuildEinoRuntime' -v
```

Expected: FAIL，错误包含 `undefined: NewEinoRuntime` 或旧 `Config` 字段不匹配。

- [ ] **Step 4: 实现 Eino runtime 构造**

创建 `backend/internal/agent/eino_runtime.go`：

```go
package agent

import (
	"context"
	"errors"
	"io"
	"time"

	"ai-investment-assistant/backend/internal/config"
	"ai-investment-assistant/backend/internal/tools"

	"github.com/cloudwego/eino-ext/components/model/openai"
	einomodel "github.com/cloudwego/eino/components/model"
	einotool "github.com/cloudwego/eino/components/tool"
	"github.com/cloudwego/eino/schema"
)

type streamChatModel interface {
	Stream(ctx context.Context, input []*schema.Message, opts ...einomodel.Option) (*schema.StreamReader[*schema.Message], error)
}

type EinoRuntime struct {
	spec  GraphSpec
	model streamChatModel
	tools map[string]einotool.InvokableTool
}

func NewEinoRuntime(ctx context.Context, cfg config.Config, registry tools.Registry, spec GraphSpec) (*EinoRuntime, error) {
	if cfg.DeepSeekAPIKey == "" {
		return nil, errors.New("DEEPSEEK_API_KEY is required for Eino runtime")
	}
	timeout := cfg.HTTPClientTimeout
	if timeout <= 0 {
		timeout = 60 * time.Second
	}
	einoTools, err := registry.EinoTools(ctx)
	if err != nil {
		return nil, err
	}
	toolInfos := make([]*schema.ToolInfo, 0, len(einoTools))
	toolMap := make(map[string]einotool.InvokableTool, len(einoTools))
	for _, item := range einoTools {
		info, err := item.Info(ctx)
		if err != nil {
			return nil, err
		}
		toolInfos = append(toolInfos, info)
		toolMap[info.Name] = item
	}
	chatModel, err := openai.NewChatModel(ctx, &openai.ChatModelConfig{
		APIKey:          cfg.DeepSeekAPIKey,
		BaseURL:         cfg.DeepSeekBaseURL,
		Model:           cfg.DeepSeekModel,
		Timeout:         timeout,
		ReasoningEffort: openai.ReasoningEffortLevelHigh,
		ExtraFields: map[string]any{
			"thinking": map[string]any{"type": "enabled"},
		},
	})
	if err != nil {
		return nil, err
	}
	boundModel, err := chatModel.WithTools(toolInfos)
	if err != nil {
		return nil, err
	}
	return &EinoRuntime{
		spec:  spec,
		model: boundModel,
		tools: toolMap,
	}, nil
}

func (r *EinoRuntime) Stream(ctx context.Context, messages []Message, events chan<- Event) error {
	input := toEinoMessages(messages)
	reader, err := r.model.Stream(ctx, input)
	if err != nil {
		return err
	}
	defer reader.Close()
	for {
		chunk, err := reader.Recv()
		if errors.Is(err, io.EOF) {
			return nil
		}
		if err != nil {
			return err
		}
		if chunk == nil {
			continue
		}
		if chunk.Content != "" {
			if !send(ctx, events, Event{Kind: "delta", Text: chunk.Content}) {
				return ctx.Err()
			}
		}
		for _, call := range chunk.ToolCalls {
			if err := r.executeToolCall(ctx, events, call); err != nil {
				return err
			}
		}
	}
}

func toEinoMessages(messages []Message) []*schema.Message {
	out := make([]*schema.Message, 0, len(messages))
	for _, message := range messages {
		out = append(out, &schema.Message{
			Role:    schema.RoleType(message.Role),
			Content: message.Content,
		})
	}
	return out
}

func (r *EinoRuntime) executeToolCall(ctx context.Context, events chan<- Event, call schema.ToolCall) error {
	name := call.Function.Name
	args := call.Function.Arguments
	toolCallID := call.ID
	if toolCallID == "" {
		toolCallID = name
	}
	if !send(ctx, events, Event{Kind: "tool_call", ToolCallID: toolCallID, ToolName: name, ToolArgs: map[string]any{}}) {
		return ctx.Err()
	}
	tool, ok := r.tools[name]
	if !ok {
		if !send(ctx, events, Event{Kind: "tool_result", ToolCallID: toolCallID, ToolName: name, ToolError: "unknown tool " + name}) {
			return ctx.Err()
		}
		return nil
	}
	start := time.Now()
	result, err := tool.InvokableRun(ctx, args)
	event := Event{
		Kind:       "tool_result",
		ToolCallID: toolCallID,
		ToolName:   name,
		ToolResult: result,
		LatencyMS:  time.Since(start).Milliseconds(),
	}
	if err != nil {
		event.ToolError = err.Error()
	}
	if !send(ctx, events, event) {
		return ctx.Err()
	}
	return nil
}
```

- [ ] **Step 5: 改造 `NewEinoAgent` 使用 runtime**

在 `backend/internal/agent/agent.go` 中把当前 `DeepSeekAgent` 主路径改成：

```go
type EinoAgent struct {
	cfg      config.Config
	registry tools.Registry
	runtime  *EinoRuntime
}

func NewEinoAgent(cfg config.Config, registry tools.Registry) Agent {
	return &EinoAgent{cfg: cfg, registry: registry}
}

func (a *EinoAgent) Stream(ctx context.Context, messages []Message) (<-chan Event, <-chan error) {
	events := make(chan Event)
	errs := make(chan error, 1)
	go func() {
		defer close(events)
		defer close(errs)
		if strings.TrimSpace(a.cfg.DeepSeekAPIKey) == "" {
			a.streamFallback(ctx, messages, events, errs)
			return
		}
		runtime := a.runtime
		if runtime == nil {
			created, err := NewEinoRuntime(ctx, a.cfg, a.registry, DefaultChatGraphSpec())
			if err != nil {
				errs <- err
				return
			}
			runtime = created
		}
		if err := runtime.Stream(ctx, messages, events); err != nil {
			errs <- err
		}
	}()
	return events, errs
}
```

保留现有 `Message`、`Event`、`Agent`、`streamFallback`、`fallbackToolCall`、`lastUserContent`、`send`、`mustJSONString` 等无需 Eino 的 helper。删除或迁移当前手写 DeepSeek HTTP 请求、SSE parser、pending tool call loop 的主路径代码。

- [ ] **Step 6: 运行 agent 测试**

Run:

```bash
cd backend
go test ./internal/agent -v
```

Expected: 只保留的外部行为测试 PASS；删除的手写 parser 测试不再运行。

- [ ] **Step 7: 提交**

```bash
git add backend/internal/agent/agent.go backend/internal/agent/eino_runtime.go backend/internal/agent/eino_runtime_test.go backend/internal/agent/agent_test.go
git commit -m "feat(backend): 使用 Eino Runtime 驱动 Agent"
```

---

## Task 6: 验证 Chat/SSE 协议兼容

**Files:**
- Modify: `backend/internal/chat/service_test.go`
- Modify only if needed: `backend/internal/chat/service.go`

- [ ] **Step 1: 运行现有 chat 测试**

Run:

```bash
cd backend
go test ./internal/chat -v
```

Expected: PASS。`chat.Service` 只依赖 `agent.Agent` 接口，Eino 改造不应要求这里大改。

- [ ] **Step 2: 如失败，锁定失败事件顺序**

如果失败，只允许围绕现有事件协议修正，不能改变前端 SSE 字段。保留以下断言：

```go
assertEventTypes(t, collected, []string{"message_created", "reasoning", "delta", "delta", "title", "done"})
assertEventTypes(t, collected, []string{"message_created", "tool_call", "tool_result", "delta", "title", "done"})
assertEventTypes(t, collected, []string{"message_created", "error"})
```

- [ ] **Step 3: 运行 api stream 测试**

Run:

```bash
cd backend
go test ./internal/api -run 'Stream|Health|Validation' -v
```

Expected: PASS。Gin router 和 SSE writer 协议不变。

- [ ] **Step 4: 提交**

如果没有代码变化，跳过提交。如果修复了 chat/api 兼容性：

```bash
git add backend/internal/chat/service.go backend/internal/chat/service_test.go backend/internal/api/router.go backend/internal/api/router_test.go
git commit -m "fix(backend): 保持 Eino 改造后的 SSE 协议兼容"
```

---

## Task 7: 全量验证和文档收尾

**Files:**
- Modify if needed: `README.md`
- Modify if needed: `docs/superpowers/specs/2026-05-30-backend-gin-eino-graph-design.md`

- [ ] **Step 1: 全量测试**

Run:

```bash
cd backend
go test ./...
```

Expected: PASS。

- [ ] **Step 2: 构建 server**

Run:

```bash
cd backend
go build ./cmd/server
```

Expected: PASS，生成 `server` 二进制或完成构建无错误。

- [ ] **Step 3: 检查配置文档是否需要更新**

读取 `README.md` 的环境变量段落，确保关键变量与实现一致：

```md
- `BFF_HTTP_ADDR`：backend Gin HTTP 监听地址，例如 `:8081`
- `DEEPSEEK_API_KEY`：DeepSeek API key，配置后 Agent 通过 Eino OpenAI-compatible ChatModel 调用 DeepSeek
- `DEEPSEEK_BASE_URL`：DeepSeek OpenAI-compatible base URL
- `DEEPSEEK_MODEL`：DeepSeek 模型名
- `DEEPSEEK_TIMEOUT_SECONDS`：DeepSeek HTTP 调用超时
- `DATABASE_URL`：默认指向 docker-compose 内的 postgres
```

- [ ] **Step 4: 手动 smoke test**

启动本地依赖后运行：

```bash
cd backend
go run ./cmd/server
```

另一个终端运行：

```bash
curl http://localhost:8081/api/health
```

Expected:

```json
{"status":"ok"}
```

- [ ] **Step 5: 手动 SSE fallback smoke test**

如果没有配置 `DEEPSEEK_API_KEY`，创建会话后运行：

```bash
curl -N \
  -H 'Content-Type: application/json' \
  -X POST http://localhost:8081/api/chat/stream \
  -d '{"conversationId":"<created-id>","message":"Explain AI moats"}'
```

Expected: 响应包含 `message_created`、至少一个 `delta`、可选 `title`、`done`。

- [ ] **Step 6: 提交收尾文档**

如果 README 或 spec 有更新：

```bash
git add README.md docs/superpowers/specs/2026-05-30-backend-gin-eino-graph-design.md
git commit -m "docs(backend): 更新 Eino 后端配置说明"
```

---

## Self-Review

- Spec coverage: 覆盖 Gin HTTP 地址、`.env` 变量、Eino OpenAI-compatible DeepSeek ChatModel、Eino tool wrapper、GraphSpec seam、SSE 协议保持不变、测试和验证。
- Placeholder scan: 没有 `TBD`、`TODO`、`implement later`、`fill in details`。
- Type consistency: 计划统一使用 `config.Config.HTTPAddr`、`GraphSpec`、`DefaultChatGraphSpec()`、`NewEinoRuntime()`、`Registry.EinoTools()`、`agent.Agent`。
- Scope control: 不实现 YAML/JSON graph 加载、不新增前端协议、不新增认证/RAG/部署能力。
