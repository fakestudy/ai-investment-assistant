package agent_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"ai-investment-assistant/backend/internal/agent"
	"ai-investment-assistant/backend/internal/config"
	"ai-investment-assistant/backend/internal/tools"
)

func TestNewEinoAgentWithoutKeyStreamsDeterministicFallback(t *testing.T) {
	agentUnderTest := agent.NewEinoAgent(config.Config{
		HTTPClientTimeout: time.Second,
	}, tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}))

	events, errs := agentUnderTest.Stream(context.Background(), []agent.Message{
		{Role: "user", Content: "Explain AI moats"},
	})

	collected := collectAgentEvents(t, events, errs)
	if len(collected) == 0 {
		t.Fatal("events len = 0, want deterministic fallback output")
	}
	if collected[0].Kind != "delta" {
		t.Fatalf("first event kind = %q, want delta", collected[0].Kind)
	}
	if !strings.Contains(collected[0].Text, "Explain AI moats") {
		t.Fatalf("fallback text = %q, want prompt echo for local development", collected[0].Text)
	}
}

func TestFallbackAgentRunsFetchURLTool(t *testing.T) {
	page := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("<html><title>Tool Page</title><body>Fetched body</body></html>"))
	}))
	defer page.Close()
	agentUnderTest := agent.NewEinoAgent(config.Config{
		HTTPClientTimeout: time.Second,
		FetchAllowPrivate: true,
	}, tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second, FetchAllowPrivate: true}))

	events, errs := agentUnderTest.Stream(context.Background(), []agent.Message{
		{Role: "user", Content: "fetch_url: " + page.URL},
	})
	collected := collectAgentEvents(t, events, errs)

	if len(collected) < 3 {
		t.Fatalf("events len = %d, want tool_call, tool_result, delta; events = %+v", len(collected), collected)
	}
	if collected[0].Kind != "tool_call" || collected[0].ToolName != "fetch_url" {
		t.Fatalf("first event = %+v, want fetch_url tool_call", collected[0])
	}
	if collected[1].Kind != "tool_result" || collected[1].ToolName != "fetch_url" {
		t.Fatalf("second event = %+v, want fetch_url tool_result", collected[1])
	}
	result, ok := collected[1].ToolResult.(map[string]any)
	if !ok {
		t.Fatalf("tool result type = %T, want map[string]any", collected[1].ToolResult)
	}
	if result["title"] != "Tool Page" {
		t.Fatalf("tool result title = %v, want Tool Page", result["title"])
	}
}

func collectAgentEvents(t *testing.T, events <-chan agent.Event, errs <-chan error) []agent.Event {
	t.Helper()

	var collected []agent.Event
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
			t.Fatalf("timed out collecting agent events; events = %+v", collected)
		}
	}
	return collected
}
