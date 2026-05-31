# Current Time Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a no-argument `current_time` tool to the backend Agent so the model can retrieve the current `Asia/Shanghai` time.

**Architecture:** Extend the existing `tools.Registry` rather than adding a second tool system. Expose the registry tool through `Registry.EinoTools()` and enable it through `DefaultChatGraphSpec()` so the Eino runtime binds it with the existing tool loop.

**Tech Stack:** Go, Gin backend, existing `tools.Registry`, CloudWeGo Eino `toolutils.InferTool`, Go unit tests.

---

### Task 1: Registry Tool

**Files:**
- Modify: `backend/internal/tools/tools_test.go`
- Modify: `backend/internal/tools/tools.go`

- [ ] **Step 1: Write the failing registry test**

Add this test to `backend/internal/tools/tools_test.go`:

```go
func TestCurrentTimeUsesShanghaiTimezone(t *testing.T) {
	registry := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second})

	result, err := registry.Execute(context.Background(), "current_time", map[string]any{})
	if err != nil {
		t.Fatalf("Execute(current_time) error = %v", err)
	}

	if result["timezone"] != "Asia/Shanghai" {
		t.Fatalf("timezone = %v, want Asia/Shanghai", result["timezone"])
	}
	if _, ok := result["unix"].(int64); !ok {
		t.Fatalf("unix = %T, want int64", result["unix"])
	}
	if !strings.Contains(result["iso8601"].(string), "+08:00") {
		t.Fatalf("iso8601 = %q, want +08:00 offset", result["iso8601"])
	}
	if len(result["date"].(string)) != len("2006-01-02") {
		t.Fatalf("date = %q, want YYYY-MM-DD", result["date"])
	}
	if len(result["time"].(string)) != len("15:04:05") {
		t.Fatalf("time = %q, want HH:mm:ss", result["time"])
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./backend/internal/tools -run TestCurrentTimeUsesShanghaiTimezone -count=1`

Expected: FAIL with `unknown tool "current_time"`.

- [ ] **Step 3: Add the minimal tool implementation**

In `backend/internal/tools/tools.go`, add `"current_time": newCurrentTimeTool()` to `NewRegistry()` and define:

```go
func newCurrentTimeTool() Tool {
	return func(ctx context.Context, args map[string]any) (map[string]any, error) {
		location, err := time.LoadLocation("Asia/Shanghai")
		if err != nil {
			return nil, err
		}
		now := time.Now().In(location)
		return map[string]any{
			"timezone": "Asia/Shanghai",
			"unix":     now.Unix(),
			"iso8601":  now.Format(time.RFC3339),
			"date":     now.Format("2006-01-02"),
			"time":     now.Format("15:04:05"),
		}, nil
	}
}
```

- [ ] **Step 4: Run registry test**

Run: `go test ./backend/internal/tools -run TestCurrentTimeUsesShanghaiTimezone -count=1`

Expected: PASS.

### Task 2: Eino Exposure

**Files:**
- Modify: `backend/internal/tools/eino_test.go`
- Modify: `backend/internal/tools/eino.go`

- [ ] **Step 1: Update Eino tool construction test**

Change `TestRegistryBuildsEinoTools` so it expects 3 tools and includes `current_time`:

```go
if len(einoTools) != 3 {
	t.Fatalf("EinoTools len = %d, want 3", len(einoTools))
}
```

```go
if !names["web_search"] || !names["fetch_url"] || !names["current_time"] {
	t.Fatalf("tool names = %+v, want web_search, fetch_url, and current_time", names)
}
```

- [ ] **Step 2: Add Eino invocation test**

Add this test to `backend/internal/tools/eino_test.go`:

```go
func TestEinoCurrentTimeToolUsesExistingRegistryBehavior(t *testing.T) {
	registry := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second})
	einoTools, err := registry.EinoTools(context.Background())
	if err != nil {
		t.Fatalf("EinoTools() error = %v", err)
	}
	currentTime := requireEinoTool(t, einoTools, "current_time")

	output, err := currentTime.InvokableRun(context.Background(), `{}`)
	if err != nil {
		t.Fatalf("InvokableRun(current_time) error = %v", err)
	}
	if !strings.Contains(output, `"timezone":"Asia/Shanghai"`) {
		t.Fatalf("output = %s, want Asia/Shanghai timezone", output)
	}
}
```

- [ ] **Step 3: Run Eino tests to verify failure**

Run: `go test ./backend/internal/tools -run 'TestRegistryBuildsEinoTools|TestEinoCurrentTimeToolUsesExistingRegistryBehavior' -count=1`

Expected: FAIL because `current_time` is not exposed by `EinoTools()`.

- [ ] **Step 4: Expose current_time through Eino**

In `backend/internal/tools/eino.go`, add:

```go
type currentTimeInput struct{}
```

Then create the Eino tool:

```go
currentTime, err := toolutils.InferTool(
	"current_time",
	"Get the current date and time in Asia/Shanghai timezone.",
	func(ctx context.Context, input currentTimeInput) (map[string]any, error) {
		return r.Execute(ctx, "current_time", map[string]any{})
	},
)
if err != nil {
	return nil, err
}
```

Return it with the existing tools:

```go
return []EinoInvokableTool{webSearch, fetchURL, currentTime}, nil
```

- [ ] **Step 5: Run Eino tests**

Run: `go test ./backend/internal/tools -count=1`

Expected: PASS.

### Task 3: Default Agent Binding

**Files:**
- Modify: `backend/internal/agent/graph_spec_test.go`
- Modify: `backend/internal/agent/graph_spec.go`

- [ ] **Step 1: Update graph spec test**

Change `TestDefaultChatGraphSpec` so it expects 3 tools and the third is `current_time`:

```go
if len(spec.Tools) != 3 {
	t.Fatalf("Tools len = %d, want 3", len(spec.Tools))
}
if spec.Tools[0].Name != "web_search" || spec.Tools[1].Name != "fetch_url" || spec.Tools[2].Name != "current_time" {
	t.Fatalf("Tools = %+v, want web_search, fetch_url, and current_time", spec.Tools)
}
```

- [ ] **Step 2: Run graph spec test to verify failure**

Run: `go test ./backend/internal/agent -run TestDefaultChatGraphSpec -count=1`

Expected: FAIL because the default graph spec only declares 2 tools.

- [ ] **Step 3: Enable current_time in default graph spec**

In `backend/internal/agent/graph_spec.go`, append:

```go
{Name: "current_time"},
```

to `DefaultChatGraphSpec().Tools`.

- [ ] **Step 4: Run agent tests**

Run: `go test ./backend/internal/agent -count=1`

Expected: PASS.

### Task 4: Verification

**Files:**
- Verify: backend Go packages

- [ ] **Step 1: Run focused backend tests**

Run: `go test ./backend/internal/tools ./backend/internal/agent -count=1`

Expected: PASS.

- [ ] **Step 2: Run diagnostics**

Use IDE diagnostics for the edited Go files.

Expected: no new diagnostics in `tools.go`, `eino.go`, or `graph_spec.go`.
