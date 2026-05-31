package agent

import (
	"context"
	"sync"

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

func send(ctx context.Context, events chan<- Event, event Event) bool {
	select {
	case <-ctx.Done():
		return false
	case events <- event:
		return true
	}
}
