package agent

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"ai-investment-assistant/backend/internal/config"
	"ai-investment-assistant/backend/internal/tools"

	einomodel "github.com/cloudwego/eino/components/model"
	"github.com/cloudwego/eino/schema"
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

func TestEinoRuntimeStreamsReasoningDeltaAndToolEvents(t *testing.T) {
	einoTools, err := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}).EinoTools(context.Background())
	if err != nil {
		t.Fatalf("EinoTools() error = %v", err)
	}

	runtime := &EinoRuntime{
		spec: DefaultChatGraphSpec(),
		model: fakeStreamChatModel{chunks: []*schema.Message{
			{ReasoningContent: "thinking "},
			{Content: "Answer "},
			{ToolCalls: []schema.ToolCall{{
				ID: "call_search",
				Function: schema.FunctionCall{
					Name:      "web_search",
					Arguments: `{"query":"AI moats"}`,
				},
			}}},
			{Content: "done"},
		}},
		tools: runtimeToolMap(t, einoTools),
	}

	events := make(chan Event)
	errs := make(chan error, 1)
	go func() {
		defer close(events)
		defer close(errs)
		if err := runtime.Stream(context.Background(), []Message{{Role: "user", Content: "hello"}}, events); err != nil {
			errs <- err
		}
	}()

	collected := collectRuntimeEvents(t, events, errs)
	if len(collected) != 5 {
		t.Fatalf("events len = %d, want reasoning, delta, tool_call, tool_result, delta; events = %+v", len(collected), collected)
	}
	if collected[0].Kind != "reasoning" || collected[0].Text != "thinking " {
		t.Fatalf("first event = %+v, want reasoning", collected[0])
	}
	if collected[1].Kind != "delta" || collected[1].Text != "Answer " {
		t.Fatalf("second event = %+v, want delta", collected[1])
	}
	if collected[2].Kind != "tool_call" || collected[2].ToolName != "web_search" || collected[2].ToolCallID != "call_search" {
		t.Fatalf("third event = %+v, want web_search tool_call", collected[2])
	}
	if collected[3].Kind != "tool_result" || collected[3].ToolName != "web_search" || collected[3].ToolCallID != "call_search" {
		t.Fatalf("fourth event = %+v, want web_search tool_result", collected[3])
	}
	if collected[3].ToolError != "" {
		t.Fatalf("tool error = %q, want empty", collected[3].ToolError)
	}
	if collected[4].Kind != "delta" || collected[4].Text != "done" {
		t.Fatalf("fifth event = %+v, want final delta", collected[4])
	}
}

func runtimeToolMap(t *testing.T, einoTools []tools.EinoInvokableTool) map[string]tools.EinoInvokableTool {
	t.Helper()
	toolMap := make(map[string]tools.EinoInvokableTool, len(einoTools))
	for _, item := range einoTools {
		info, err := item.Info(context.Background())
		if err != nil {
			t.Fatalf("Info() error = %v", err)
		}
		toolMap[info.Name] = item
	}
	return toolMap
}

type fakeStreamChatModel struct {
	chunks []*schema.Message
	err    error
}

func (f fakeStreamChatModel) Stream(ctx context.Context, input []*schema.Message, opts ...einomodel.Option) (*schema.StreamReader[*schema.Message], error) {
	if f.err != nil {
		return nil, f.err
	}
	if len(input) != 1 || input[0].Role != schema.User || input[0].Content != "hello" {
		return nil, errors.New("runtime did not pass user message to Eino model")
	}
	return schema.StreamReaderFromArray(f.chunks), nil
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
