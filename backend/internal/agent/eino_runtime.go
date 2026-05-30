package agent

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"time"

	"ai-investment-assistant/backend/internal/config"
	"ai-investment-assistant/backend/internal/tools"

	openai "github.com/cloudwego/eino-ext/components/model/openai"
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
	if strings.TrimSpace(cfg.DeepSeekAPIKey) == "" {
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
	reader, err := r.model.Stream(ctx, toEinoMessages(messages))
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
		if chunk.ReasoningContent != "" {
			if !send(ctx, events, Event{Kind: "reasoning", Text: chunk.ReasoningContent}) {
				return ctx.Err()
			}
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
	args := parseToolArgs(call.Function.Arguments)
	toolCallID := call.ID
	if toolCallID == "" {
		toolCallID = name
	}
	if !send(ctx, events, Event{Kind: "tool_call", ToolCallID: toolCallID, ToolName: name, ToolArgs: args}) {
		return ctx.Err()
	}

	tool, ok := r.tools[name]
	if !ok {
		return sendToolResult(ctx, events, Event{
			Kind:       "tool_result",
			ToolCallID: toolCallID,
			ToolName:   name,
			ToolArgs:   args,
			ToolError:  "unknown tool " + name,
		})
	}
	start := time.Now()
	result, err := tool.InvokableRun(ctx, call.Function.Arguments)
	event := Event{
		Kind:       "tool_result",
		ToolCallID: toolCallID,
		ToolName:   name,
		ToolArgs:   args,
		ToolResult: result,
		LatencyMS:  time.Since(start).Milliseconds(),
	}
	if err != nil {
		event.ToolError = err.Error()
	}
	return sendToolResult(ctx, events, event)
}

func parseToolArgs(raw string) map[string]any {
	args := map[string]any{}
	if strings.TrimSpace(raw) == "" {
		return args
	}
	if err := json.Unmarshal([]byte(raw), &args); err != nil {
		return map[string]any{}
	}
	return args
}

func sendToolResult(ctx context.Context, events chan<- Event, event Event) error {
	if !send(ctx, events, event) {
		return ctx.Err()
	}
	return nil
}
