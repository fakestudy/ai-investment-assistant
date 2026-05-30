package agent_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
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

func TestDeepSeekCompatibleStreamParsesReasoningAndDelta(t *testing.T) {
	var sawAuthorization bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/chat/completions" {
			t.Fatalf("path = %q, want /chat/completions", r.URL.Path)
		}
		sawAuthorization = r.Header.Get("Authorization") == "Bearer test-key"
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatalf("decode request body error = %v", err)
		}
		if body["model"] != "deepseek-chat" || body["stream"] != true {
			t.Fatalf("request body = %+v, want model and stream=true", body)
		}
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("data: {\"choices\":[{\"delta\":{\"reasoning_content\":\"thinking \",\"content\":\"Hello\"}}]}\n\n"))
		_, _ = w.Write([]byte("data: {\"choices\":[{\"delta\":{\"content\":\" investor\"}}]}\n\n"))
		_, _ = w.Write([]byte("data: [DONE]\n\n"))
	}))
	defer server.Close()

	agentUnderTest := agent.NewEinoAgent(config.Config{
		DeepSeekAPIKey:    "test-key",
		DeepSeekBaseURL:   server.URL,
		DeepSeekModel:     "deepseek-chat",
		HTTPClientTimeout: time.Second,
	}, tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}))

	events, errs := agentUnderTest.Stream(context.Background(), []agent.Message{
		{Role: "user", Content: "hello"},
	})
	collected := collectAgentEvents(t, events, errs)

	if !sawAuthorization {
		t.Fatal("Authorization header missing, want Bearer test-key")
	}
	if len(collected) != 3 {
		t.Fatalf("events len = %d, want 3; events = %+v", len(collected), collected)
	}
	if collected[0].Kind != "reasoning" || collected[0].Text != "thinking " {
		t.Fatalf("first event = %+v, want reasoning", collected[0])
	}
	if collected[1].Kind != "delta" || collected[1].Text != "Hello" {
		t.Fatalf("second event = %+v, want first delta", collected[1])
	}
	if collected[2].Kind != "delta" || collected[2].Text != " investor" {
		t.Fatalf("third event = %+v, want second delta", collected[2])
	}
}

func TestDeepSeekCompatibleStreamExecutesToolCalls(t *testing.T) {
	page := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("<html><title>DeepSeek Tool Page</title><body>Tool body</body></html>"))
	}))
	defer page.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"type\":\"function\",\"function\":{\"name\":\"fetch_url\",\"arguments\":\"{\\\"url\\\":\"}}]}}]}\n\n"))
		_, _ = w.Write([]byte("data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"function\":{\"arguments\":" + strconv.Quote(strconv.Quote(page.URL)+"}") + "}}]},\"finish_reason\":\"tool_calls\"}]}\n\n"))
		_, _ = w.Write([]byte("data: [DONE]\n\n"))
	}))
	defer server.Close()
	agentUnderTest := agent.NewEinoAgent(config.Config{
		DeepSeekAPIKey:    "test-key",
		DeepSeekBaseURL:   server.URL,
		DeepSeekModel:     "deepseek-chat",
		HTTPClientTimeout: time.Second,
	}, tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}))

	events, errs := agentUnderTest.Stream(context.Background(), []agent.Message{
		{Role: "user", Content: "fetch page"},
	})
	collected := collectAgentEvents(t, events, errs)

	if len(collected) != 2 {
		t.Fatalf("events len = %d, want tool_call and tool_result; events = %+v", len(collected), collected)
	}
	if collected[0].Kind != "tool_call" || collected[0].ToolName != "fetch_url" {
		t.Fatalf("first event = %+v, want fetch_url tool_call", collected[0])
	}
	if collected[1].Kind != "tool_result" || collected[1].ToolError != "" {
		t.Fatalf("second event = %+v, want successful tool_result", collected[1])
	}
	result, ok := collected[1].ToolResult.(map[string]any)
	if !ok {
		t.Fatalf("tool result type = %T, want map[string]any", collected[1].ToolResult)
	}
	if result["title"] != "DeepSeek Tool Page" {
		t.Fatalf("tool result title = %v, want DeepSeek Tool Page", result["title"])
	}
}

func TestFallbackAgentRunsFetchURLTool(t *testing.T) {
	page := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("<html><title>Tool Page</title><body>Fetched body</body></html>"))
	}))
	defer page.Close()
	agentUnderTest := agent.NewEinoAgent(config.Config{
		HTTPClientTimeout: time.Second,
	}, tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}))

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
