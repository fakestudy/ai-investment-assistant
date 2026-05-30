package agent

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	"ai-investment-assistant/backend/internal/config"
	"ai-investment-assistant/backend/internal/tools"

	einomodel "github.com/cloudwego/eino/components/model"
	einotool "github.com/cloudwego/eino/components/tool"
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

func TestNewEinoRuntimeValidatesGraphSpecAndSelectsTools(t *testing.T) {
	t.Run("rejects unsupported model provider", func(t *testing.T) {
		spec := DefaultChatGraphSpec()
		spec.Model.Provider = "unsupported"

		_, err := NewEinoRuntime(context.Background(), config.Config{
			DeepSeekAPIKey:    "test-key",
			DeepSeekBaseURL:   "https://api.deepseek.com",
			DeepSeekModel:     "deepseek-v4-pro",
			HTTPClientTimeout: time.Second,
		}, tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}), spec)
		if err == nil || !strings.Contains(err.Error(), "unsupported model provider") {
			t.Fatalf("NewEinoRuntime() error = %v, want unsupported model provider", err)
		}
	})

	t.Run("keeps only tools declared by graph spec", func(t *testing.T) {
		spec := DefaultChatGraphSpec()
		spec.Tools = []ToolSpec{{Name: "web_search"}}

		runtime, err := NewEinoRuntime(context.Background(), config.Config{
			DeepSeekAPIKey:    "test-key",
			DeepSeekBaseURL:   "https://api.deepseek.com",
			DeepSeekModel:     "deepseek-v4-pro",
			HTTPClientTimeout: time.Second,
		}, tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}), spec)
		if err != nil {
			t.Fatalf("NewEinoRuntime() error = %v", err)
		}
		if len(runtime.tools) != 1 || runtime.tools["web_search"] == nil {
			t.Fatalf("runtime tools = %+v, want only web_search", runtime.tools)
		}
		if runtime.tools["fetch_url"] != nil {
			t.Fatalf("runtime tools include fetch_url, want GraphSpec selection to exclude it")
		}
	})

	t.Run("rejects graph tools missing from registry", func(t *testing.T) {
		spec := DefaultChatGraphSpec()
		spec.Tools = append(spec.Tools, ToolSpec{Name: "missing_tool"})

		_, err := NewEinoRuntime(context.Background(), config.Config{
			DeepSeekAPIKey:    "test-key",
			DeepSeekBaseURL:   "https://api.deepseek.com",
			DeepSeekModel:     "deepseek-v4-pro",
			HTTPClientTimeout: time.Second,
		}, tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}), spec)
		if err == nil || !strings.Contains(err.Error(), "missing_tool") {
			t.Fatalf("NewEinoRuntime() error = %v, want missing_tool validation error", err)
		}
	})
}

func TestValidateGraphSpecChecksEdgesConditionsAndNodeReferences(t *testing.T) {
	t.Run("rejects missing chat model to tools edge when tools are declared", func(t *testing.T) {
		spec := DefaultChatGraphSpec()
		spec.Edges = nil

		err := validateGraphSpec(spec)
		if err == nil || !strings.Contains(err.Error(), "chat_model -> tools") {
			t.Fatalf("validateGraphSpec() error = %v, want missing chat_model -> tools edge", err)
		}
	})

	t.Run("rejects unsupported tool edge condition", func(t *testing.T) {
		spec := DefaultChatGraphSpec()
		spec.Edges[0].Condition = "always"

		err := validateGraphSpec(spec)
		if err == nil || !strings.Contains(err.Error(), "model_requests_tool") {
			t.Fatalf("validateGraphSpec() error = %v, want model_requests_tool condition error", err)
		}
	})

	t.Run("rejects edge with unknown from node", func(t *testing.T) {
		spec := DefaultChatGraphSpec()
		spec.Edges = append(spec.Edges, EdgeSpec{From: "missing", To: "tools", Condition: "model_requests_tool"})

		err := validateGraphSpec(spec)
		if err == nil || !strings.Contains(err.Error(), "unknown from node") {
			t.Fatalf("validateGraphSpec() error = %v, want unknown from node error", err)
		}
	})

	t.Run("rejects edge with unknown to node", func(t *testing.T) {
		spec := DefaultChatGraphSpec()
		spec.Edges = append(spec.Edges, EdgeSpec{From: "chat_model", To: "missing", Condition: "model_requests_tool"})

		err := validateGraphSpec(spec)
		if err == nil || !strings.Contains(err.Error(), "unknown to node") {
			t.Fatalf("validateGraphSpec() error = %v, want unknown to node error", err)
		}
	})

	t.Run("rejects entrypoint not declared as node", func(t *testing.T) {
		spec := DefaultChatGraphSpec()
		spec.Entrypoint = "missing"

		err := validateGraphSpec(spec)
		if err == nil || !strings.Contains(err.Error(), "entrypoint") {
			t.Fatalf("validateGraphSpec() error = %v, want entrypoint node reference error", err)
		}
	})
}

func TestEinoRuntimeStreamsReasoningDeltaAndToolEvents(t *testing.T) {
	einoTools, err := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}).EinoTools(context.Background())
	if err != nil {
		t.Fatalf("EinoTools() error = %v", err)
	}

	runtime := &EinoRuntime{
		spec: DefaultChatGraphSpec(),
		model: &fakeStreamChatModel{streams: [][]*schema.Message{
			{
				{ReasoningContent: "thinking "},
				{Content: "Answer "},
			},
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
	if len(collected) != 2 {
		t.Fatalf("events len = %d, want reasoning, delta; events = %+v", len(collected), collected)
	}
	if collected[0].Kind != "reasoning" || collected[0].Text != "thinking " {
		t.Fatalf("first event = %+v, want reasoning", collected[0])
	}
	if collected[1].Kind != "delta" || collected[1].Text != "Answer " {
		t.Fatalf("second event = %+v, want delta", collected[1])
	}
}

func TestEinoRuntimeLoopsToolResultsBackToModelForFinalAnswer(t *testing.T) {
	einoTools, err := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}).EinoTools(context.Background())
	if err != nil {
		t.Fatalf("EinoTools() error = %v", err)
	}
	model := &fakeStreamChatModel{streams: [][]*schema.Message{
		{
			{ToolCalls: []schema.ToolCall{{
				ID:   "call_search",
				Type: "function",
				Function: schema.FunctionCall{
					Name:      "web_search",
					Arguments: `{"query":"AI moats"}`,
				},
			}}},
		},
		{
			{Content: "Final answer after search"},
		},
	}}
	runtime := &EinoRuntime{
		spec:  DefaultChatGraphSpec(),
		model: model,
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
	if len(collected) != 3 {
		t.Fatalf("events len = %d, want tool_call, tool_result, final delta; events = %+v", len(collected), collected)
	}
	if collected[0].Kind != "tool_call" || collected[0].ToolName != "web_search" || collected[0].ToolCallID != "call_search" {
		t.Fatalf("first event = %+v, want web_search tool_call", collected[0])
	}
	if collected[1].Kind != "tool_result" || collected[1].ToolName != "web_search" || collected[1].ToolCallID != "call_search" {
		t.Fatalf("second event = %+v, want web_search tool_result", collected[1])
	}
	if collected[1].ToolError != "" {
		t.Fatalf("tool error = %q, want empty", collected[1].ToolError)
	}
	if collected[2].Kind != "delta" || collected[2].Text != "Final answer after search" {
		t.Fatalf("third event = %+v, want final delta from second model round", collected[2])
	}
	if len(model.inputs) != 2 {
		t.Fatalf("model Stream calls = %d, want 2", len(model.inputs))
	}
	secondInput := model.inputs[1]
	if len(secondInput) != 3 {
		t.Fatalf("second model input len = %d, want user, assistant tool call, tool result; input = %+v", len(secondInput), secondInput)
	}
	if secondInput[1].Role != schema.Assistant || len(secondInput[1].ToolCalls) != 1 || secondInput[1].ToolCalls[0].ID != "call_search" {
		t.Fatalf("assistant tool call message = %+v, want call_search", secondInput[1])
	}
	if secondInput[2].Role != schema.Tool || secondInput[2].ToolCallID != "call_search" || secondInput[2].ToolName != "web_search" {
		t.Fatalf("tool result message = %+v, want web_search tool result", secondInput[2])
	}
	if !strings.Contains(secondInput[2].Content, "web_search is not configured") {
		t.Fatalf("tool result content = %q, want serialized tool output", secondInput[2].Content)
	}
}

func TestEinoRuntimeMergesFragmentedToolCallBeforeExecuting(t *testing.T) {
	einoTools, err := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}).EinoTools(context.Background())
	if err != nil {
		t.Fatalf("EinoTools() error = %v", err)
	}
	model := &fakeStreamChatModel{streams: [][]*schema.Message{
		{
			{ToolCalls: []schema.ToolCall{{
				Index: intPtr(0),
				ID:    "call_search",
				Type:  "function",
				Function: schema.FunctionCall{
					Name:      "web_search",
					Arguments: `{"query":`,
				},
			}}},
			{ToolCalls: []schema.ToolCall{{
				Index: intPtr(0),
				Function: schema.FunctionCall{
					Arguments: `"AI moats"}`,
				},
			}}},
		},
		{
			{Content: "Final answer after fragmented tool call"},
		},
	}}
	runtime := &EinoRuntime{
		spec:  DefaultChatGraphSpec(),
		model: model,
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
	if len(collected) != 3 {
		t.Fatalf("events len = %d, want one merged tool call, one result, final delta; events = %+v", len(collected), collected)
	}
	if collected[0].Kind != "tool_call" || collected[0].ToolCallID != "call_search" || collected[0].ToolName != "web_search" {
		t.Fatalf("first event = %+v, want merged web_search tool_call", collected[0])
	}
	if got := collected[0].ToolArgs["query"]; got != "AI moats" {
		t.Fatalf("tool args query = %v, want merged AI moats", got)
	}
	if collected[1].Kind != "tool_result" || collected[1].ToolError != "" {
		t.Fatalf("second event = %+v, want successful merged tool_result", collected[1])
	}
	if collected[2].Kind != "delta" || collected[2].Text != "Final answer after fragmented tool call" {
		t.Fatalf("third event = %+v, want final answer", collected[2])
	}
	if len(model.inputs) != 2 {
		t.Fatalf("model Stream calls = %d, want 2", len(model.inputs))
	}
	toolCalls := model.inputs[1][1].ToolCalls
	if len(toolCalls) != 1 || toolCalls[0].Function.Arguments != `{"query":"AI moats"}` {
		t.Fatalf("assistant tool calls = %+v, want single merged tool call", toolCalls)
	}
}

func TestEinoRuntimeFinalAnswerCanDependOnToolResultContent(t *testing.T) {
	einoTools, err := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}).EinoTools(context.Background())
	if err != nil {
		t.Fatalf("EinoTools() error = %v", err)
	}
	model := &fakeStreamChatModel{
		streamForInput: func(callIndex int, input []*schema.Message) ([]*schema.Message, error) {
			switch callIndex {
			case 0:
				return []*schema.Message{{
					ToolCalls: []schema.ToolCall{{
						ID:   "call_search",
						Type: "function",
						Function: schema.FunctionCall{
							Name:      "web_search",
							Arguments: `{"query":"AI moats"}`,
						},
					}},
				}}, nil
			case 1:
				toolResult := input[len(input)-1]
				if toolResult.Role != schema.Tool {
					return nil, fmt.Errorf("second call last message role = %s, want tool", toolResult.Role)
				}
				return []*schema.Message{{
					Content: "Final answer derived from tool result: " + toolResult.Content,
				}}, nil
			default:
				return nil, fmt.Errorf("unexpected Stream call %d", callIndex+1)
			}
		},
	}
	runtime := &EinoRuntime{
		spec:  DefaultChatGraphSpec(),
		model: model,
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
	if len(collected) != 3 {
		t.Fatalf("events len = %d, want tool_call, tool_result, final delta; events = %+v", len(collected), collected)
	}
	if collected[2].Kind != "delta" {
		t.Fatalf("third event = %+v, want final delta", collected[2])
	}
	if !strings.Contains(collected[2].Text, "AI moats") || !strings.Contains(collected[2].Text, "web_search is not configured") {
		t.Fatalf("final answer = %q, want content derived from tool result", collected[2].Text)
	}
}

func TestEinoRuntimeEmitsToolEventsBeforeLoopingForFinalAnswer(t *testing.T) {
	einoTools, err := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}).EinoTools(context.Background())
	if err != nil {
		t.Fatalf("EinoTools() error = %v", err)
	}

	runtime := &EinoRuntime{
		spec: DefaultChatGraphSpec(),
		model: &fakeStreamChatModel{streams: [][]*schema.Message{
			{
				{ToolCalls: []schema.ToolCall{{
					ID: "call_search",
					Function: schema.FunctionCall{
						Name:      "web_search",
						Arguments: `{"query":"AI moats"}`,
					},
				}}},
			},
			{
				{Content: "done"},
			},
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
	if len(collected) != 3 {
		t.Fatalf("events len = %d, want tool_call, tool_result, delta; events = %+v", len(collected), collected)
	}
	if collected[0].Kind != "tool_call" || collected[0].ToolName != "web_search" || collected[0].ToolCallID != "call_search" {
		t.Fatalf("first event = %+v, want web_search tool_call", collected[0])
	}
	if collected[1].Kind != "tool_result" || collected[1].ToolName != "web_search" || collected[1].ToolCallID != "call_search" {
		t.Fatalf("second event = %+v, want web_search tool_result", collected[1])
	}
	if collected[1].ToolError != "" {
		t.Fatalf("tool error = %q, want empty", collected[1].ToolError)
	}
	if collected[2].Kind != "delta" || collected[2].Text != "done" {
		t.Fatalf("third event = %+v, want final delta", collected[2])
	}
}

func TestEinoRuntimeChecksToolLoopLimitBeforeExecutingTools(t *testing.T) {
	model := &fakeStreamChatModel{streamForInput: func(callIndex int, input []*schema.Message) ([]*schema.Message, error) {
		return []*schema.Message{{
			ToolCalls: []schema.ToolCall{{
				ID:   fmt.Sprintf("call_%d", callIndex),
				Type: "function",
				Function: schema.FunctionCall{
					Name:      "count_tool",
					Arguments: `{"input":"value"}`,
				},
			}},
		}}, nil
	}}
	tool := &countingInvokableTool{name: "count_tool", result: "counted"}
	runtime := &EinoRuntime{
		spec:  DefaultChatGraphSpec(),
		model: model,
		tools: map[string]einotool.InvokableTool{"count_tool": tool},
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

	collected := collectRuntimeEventsAllowingError(t, events, errs)
	if tool.calls != maxEinoToolIterations {
		t.Fatalf("tool calls = %d, want %d; runtime must not execute tools after limit", tool.calls, maxEinoToolIterations)
	}
	if len(model.inputs) != maxEinoToolIterations+1 {
		t.Fatalf("model Stream calls = %d, want %d to observe over-limit tool request", len(model.inputs), maxEinoToolIterations+1)
	}
	toolCallEvents := 0
	toolResultEvents := 0
	for _, event := range collected.events {
		if event.Kind == "tool_call" {
			toolCallEvents++
		}
		if event.Kind == "tool_result" {
			toolResultEvents++
		}
	}
	if toolCallEvents != maxEinoToolIterations || toolResultEvents != maxEinoToolIterations {
		t.Fatalf("tool events = calls:%d results:%d, want %d each before limit; events = %+v", toolCallEvents, toolResultEvents, maxEinoToolIterations, collected.events)
	}
	if collected.err == nil || !strings.Contains(collected.err.Error(), "tool iteration limit") {
		t.Fatalf("runtime error = %v, want tool iteration limit", collected.err)
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
	streams        [][]*schema.Message
	inputs         [][]*schema.Message
	streamForInput func(callIndex int, input []*schema.Message) ([]*schema.Message, error)
	err            error
}

func (f *fakeStreamChatModel) Stream(ctx context.Context, input []*schema.Message, opts ...einomodel.Option) (*schema.StreamReader[*schema.Message], error) {
	if f.err != nil {
		return nil, f.err
	}
	if len(input) == 0 || input[0].Role != schema.User || input[0].Content != "hello" {
		return nil, errors.New("runtime did not pass user message to Eino model")
	}
	f.inputs = append(f.inputs, cloneSchemaMessages(input))
	callIndex := len(f.inputs) - 1
	if f.streamForInput != nil {
		chunks, err := f.streamForInput(callIndex, input)
		if err != nil {
			return nil, err
		}
		return schema.StreamReaderFromArray(chunks), nil
	}
	if callIndex >= len(f.streams) {
		return nil, fmt.Errorf("unexpected Stream call %d", callIndex+1)
	}
	return schema.StreamReaderFromArray(f.streams[callIndex]), nil
}

func intPtr(value int) *int {
	return &value
}

type countingInvokableTool struct {
	name   string
	result string
	calls  int
}

func (t *countingInvokableTool) Info(ctx context.Context) (*schema.ToolInfo, error) {
	return &schema.ToolInfo{Name: t.name, Desc: "counts invocations"}, nil
}

func (t *countingInvokableTool) InvokableRun(ctx context.Context, argumentsInJSON string, opts ...einotool.Option) (string, error) {
	t.calls++
	return t.result, nil
}

func cloneSchemaMessages(input []*schema.Message) []*schema.Message {
	out := make([]*schema.Message, 0, len(input))
	for _, message := range input {
		if message == nil {
			out = append(out, nil)
			continue
		}
		cloned := *message
		if message.ToolCalls != nil {
			cloned.ToolCalls = append([]schema.ToolCall(nil), message.ToolCalls...)
		}
		out = append(out, &cloned)
	}
	return out
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

type collectedRuntimeResult struct {
	events []Event
	err    error
}

func collectRuntimeEventsAllowingError(t *testing.T, events <-chan Event, errs <-chan error) collectedRuntimeResult {
	t.Helper()
	result := collectedRuntimeResult{}
	for events != nil || errs != nil {
		select {
		case event, ok := <-events:
			if !ok {
				events = nil
				continue
			}
			result.events = append(result.events, event)
		case err, ok := <-errs:
			if !ok {
				errs = nil
				continue
			}
			if err != nil {
				result.err = err
			}
		case <-time.After(time.Second):
			t.Fatalf("timed out collecting events: %+v", result.events)
		}
	}
	return result
}
