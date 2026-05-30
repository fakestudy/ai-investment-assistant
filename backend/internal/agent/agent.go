package agent

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	"ai-investment-assistant/backend/internal/config"
	"ai-investment-assistant/backend/internal/tools"
)

type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type Event struct {
	Kind       string
	Text       string
	ToolCallID string
	ToolName   string
	ToolArgs   map[string]any
	ToolResult any
	ToolError  string
	LatencyMS  int64
}

type Agent interface {
	Stream(ctx context.Context, messages []Message) (<-chan Event, <-chan error)
}

type EinoAgent struct {
	cfg       config.Config
	registry  tools.Registry
	runtimeMu sync.Mutex
	runtime   *EinoRuntime
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
		runtime, err := a.runtimeForStream(ctx)
		if err != nil {
			errs <- err
			return
		}
		if err := runtime.Stream(ctx, messages, events); err != nil {
			errs <- err
		}
	}()
	return events, errs
}

func (a *EinoAgent) runtimeForStream(ctx context.Context) (*EinoRuntime, error) {
	a.runtimeMu.Lock()
	defer a.runtimeMu.Unlock()
	if a.runtime != nil {
		return a.runtime, nil
	}
	runtime, err := NewEinoRuntime(ctx, a.cfg, a.registry, DefaultChatGraphSpec())
	if err != nil {
		return nil, err
	}
	a.runtime = runtime
	return runtime, nil
}

func (a *EinoAgent) streamFallback(ctx context.Context, messages []Message, events chan<- Event, errs chan<- error) {
	prompt := lastUserContent(messages)
	if name, args, ok := fallbackToolCall(prompt); ok {
		toolCallID := "fallback_" + name
		if !send(ctx, events, Event{Kind: "tool_call", ToolCallID: toolCallID, ToolName: name, ToolArgs: args}) {
			errs <- ctx.Err()
			return
		}
		start := time.Now()
		result, err := a.registry.Execute(ctx, name, args)
		latency := time.Since(start).Milliseconds()
		resultEvent := Event{Kind: "tool_result", ToolCallID: toolCallID, ToolName: name, ToolArgs: args, ToolResult: result, LatencyMS: latency}
		if err != nil {
			resultEvent.ToolError = err.Error()
		}
		if !send(ctx, events, resultEvent) {
			errs <- ctx.Err()
			return
		}
		if err != nil {
			return
		}
		if !send(ctx, events, Event{Kind: "delta", Text: fmt.Sprintf("Fetched %s.", args["url"])}) {
			errs <- ctx.Err()
		}
		return
	}
	if !send(ctx, events, Event{Kind: "delta", Text: prompt}) {
		errs <- ctx.Err()
	}
}

func fallbackToolCall(prompt string) (string, map[string]any, bool) {
	trimmed := strings.TrimSpace(prompt)
	lower := strings.ToLower(trimmed)
	if strings.HasPrefix(lower, "fetch_url:") {
		rawURL := strings.TrimSpace(trimmed[len("fetch_url:"):])
		return "fetch_url", map[string]any{"url": rawURL}, rawURL != ""
	}
	if strings.HasPrefix(lower, "web_search:") {
		query := strings.TrimSpace(trimmed[len("web_search:"):])
		return "web_search", map[string]any{"query": query}, query != ""
	}
	return "", nil, false
}

func lastUserContent(messages []Message) string {
	for i := len(messages) - 1; i >= 0; i-- {
		if messages[i].Role == "user" {
			return messages[i].Content
		}
	}
	if len(messages) == 0 {
		return ""
	}
	return messages[len(messages)-1].Content
}

func send(ctx context.Context, events chan<- Event, event Event) bool {
	select {
	case <-ctx.Done():
		return false
	case events <- event:
		return true
	}
}
