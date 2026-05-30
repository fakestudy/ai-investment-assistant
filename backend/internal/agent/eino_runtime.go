package agent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
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

const maxEinoToolIterations = 3

func NewEinoRuntime(ctx context.Context, cfg config.Config, registry tools.Registry, spec GraphSpec) (*EinoRuntime, error) {
	if strings.TrimSpace(cfg.DeepSeekAPIKey) == "" {
		return nil, errors.New("DEEPSEEK_API_KEY is required for Eino runtime")
	}
	if err := validateGraphSpec(spec); err != nil {
		return nil, err
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
		toolMap[info.Name] = item
	}
	toolInfos, selectedTools, err := selectGraphTools(toolMap, spec.Tools)
	if err != nil {
		return nil, err
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
		tools: selectedTools,
	}, nil
}

func (r *EinoRuntime) Stream(ctx context.Context, messages []Message, events chan<- Event) error {
	history := toEinoMessages(messages)
	for iteration := 0; iteration <= maxEinoToolIterations; iteration++ {
		assistantMessage, err := r.streamModelRound(ctx, history, events)
		if err != nil {
			return err
		}
		if assistantMessage == nil || len(assistantMessage.ToolCalls) == 0 {
			return nil
		}
		if iteration >= maxEinoToolIterations {
			return errors.New("eino tool iteration limit exceeded")
		}
		toolMessages, err := r.executeToolCalls(ctx, events, assistantMessage.ToolCalls)
		if err != nil {
			return err
		}
		history = append(history, assistantMessage)
		history = append(history, toolMessages...)
	}
	return nil
}

func (r *EinoRuntime) streamModelRound(ctx context.Context, messages []*schema.Message, events chan<- Event) (*schema.Message, error) {
	reader, err := r.model.Stream(ctx, messages)
	if err != nil {
		return nil, err
	}
	defer reader.Close()

	chunks := make([]*schema.Message, 0)
	for {
		chunk, err := reader.Recv()
		if errors.Is(err, io.EOF) {
			if len(chunks) == 0 {
				return nil, nil
			}
			assistant, err := schema.ConcatMessages(chunks)
			if err != nil {
				return nil, err
			}
			if assistant.Role == "" {
				assistant.Role = schema.Assistant
			}
			return assistant, nil
		}
		if err != nil {
			return nil, err
		}
		if chunk == nil {
			continue
		}
		chunks = append(chunks, chunk)
		if chunk.ReasoningContent != "" {
			if !send(ctx, events, Event{Kind: "reasoning", Text: chunk.ReasoningContent}) {
				return nil, ctx.Err()
			}
		}
		if chunk.Content != "" {
			if !send(ctx, events, Event{Kind: "delta", Text: chunk.Content}) {
				return nil, ctx.Err()
			}
		}
	}
}

func (r *EinoRuntime) executeToolCalls(ctx context.Context, events chan<- Event, calls []schema.ToolCall) ([]*schema.Message, error) {
	toolMessages := make([]*schema.Message, 0, len(calls))
	for _, call := range calls {
		message, err := r.executeToolCall(ctx, events, call)
		if err != nil {
			return nil, err
		}
		toolMessages = append(toolMessages, message)
	}
	return toolMessages, nil
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

func (r *EinoRuntime) executeToolCall(ctx context.Context, events chan<- Event, call schema.ToolCall) (*schema.Message, error) {
	name := call.Function.Name
	args := parseToolArgs(call.Function.Arguments)
	toolCallID := call.ID
	if toolCallID == "" {
		toolCallID = name
	}
	if !send(ctx, events, Event{Kind: "tool_call", ToolCallID: toolCallID, ToolName: name, ToolArgs: args}) {
		return nil, ctx.Err()
	}

	tool, ok := r.tools[name]
	if !ok {
		message := "unknown tool " + name
		err := sendToolResult(ctx, events, Event{
			Kind:       "tool_result",
			ToolCallID: toolCallID,
			ToolName:   name,
			ToolArgs:   args,
			ToolError:  message,
		})
		if err != nil {
			return nil, err
		}
		return toolResultMessage(toolCallID, name, message), nil
	}
	start := time.Now()
	result, err := tool.InvokableRun(ctx, call.Function.Arguments)
	content := toolResultContent(result)
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
		content = err.Error()
	}
	if err := sendToolResult(ctx, events, event); err != nil {
		return nil, err
	}
	return toolResultMessage(toolCallID, name, content), nil
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

func validateGraphSpec(spec GraphSpec) error {
	if spec.Entrypoint != "chat_model" {
		return fmt.Errorf("unsupported graph entrypoint %q", spec.Entrypoint)
	}
	if spec.Model.Provider != "deepseek_openai_compatible" {
		return fmt.Errorf("unsupported model provider %q", spec.Model.Provider)
	}
	if !hasNode(spec.Nodes, "chat_model", "chat_model") {
		return errors.New("graph spec must include chat_model node")
	}
	if len(spec.Tools) > 0 && !hasNode(spec.Nodes, "tools", "tools") {
		return errors.New("graph spec must include tools node when tools are declared")
	}
	nodes := make(map[string]NodeSpec, len(spec.Nodes))
	for _, node := range spec.Nodes {
		if strings.TrimSpace(node.Name) == "" {
			return errors.New("graph node name must not be empty")
		}
		nodes[node.Name] = node
	}
	if _, ok := nodes[spec.Entrypoint]; !ok {
		return fmt.Errorf("graph entrypoint %q does not reference a declared node", spec.Entrypoint)
	}
	hasToolEdge := false
	for _, edge := range spec.Edges {
		if _, ok := nodes[edge.From]; !ok {
			return fmt.Errorf("graph edge references unknown from node %q", edge.From)
		}
		if _, ok := nodes[edge.To]; !ok {
			return fmt.Errorf("graph edge references unknown to node %q", edge.To)
		}
		if edge.From == "chat_model" && edge.To == "tools" {
			if edge.Condition != "model_requests_tool" {
				return fmt.Errorf("chat_model -> tools edge condition must be model_requests_tool, got %q", edge.Condition)
			}
			hasToolEdge = true
		} else if edge.Condition != "" {
			return fmt.Errorf("unsupported graph edge condition %q", edge.Condition)
		}
	}
	if len(spec.Tools) > 0 && !hasToolEdge {
		return errors.New("graph spec must include chat_model -> tools edge when tools are declared")
	}
	return nil
}

func hasNode(nodes []NodeSpec, name string, kind string) bool {
	for _, node := range nodes {
		if node.Name == name && node.Kind == kind {
			return true
		}
	}
	return false
}

func selectGraphTools(available map[string]einotool.InvokableTool, specs []ToolSpec) ([]*schema.ToolInfo, map[string]einotool.InvokableTool, error) {
	toolInfos := make([]*schema.ToolInfo, 0, len(specs))
	selected := make(map[string]einotool.InvokableTool, len(specs))
	for _, spec := range specs {
		name := strings.TrimSpace(spec.Name)
		if name == "" {
			return nil, nil, errors.New("graph tool name must not be empty")
		}
		tool, ok := available[name]
		if !ok {
			return nil, nil, fmt.Errorf("graph tool %q is not registered", name)
		}
		info, err := tool.Info(context.Background())
		if err != nil {
			return nil, nil, err
		}
		toolInfos = append(toolInfos, info)
		selected[name] = tool
	}
	return toolInfos, selected, nil
}

func toolResultMessage(toolCallID string, toolName string, content string) *schema.Message {
	return &schema.Message{
		Role:       schema.Tool,
		Content:    content,
		ToolCallID: toolCallID,
		ToolName:   toolName,
	}
}

func toolResultContent(result any) string {
	if value, ok := result.(string); ok {
		return value
	}
	raw, err := json.Marshal(result)
	if err != nil {
		return "null"
	}
	return string(raw)
}
