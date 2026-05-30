package agent

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"

	"ai-investment-assistant/backend/internal/config"
	"ai-investment-assistant/backend/internal/tools"
)

type Message struct {
	Role    string
	Content string
}

type Event struct {
	Kind       string
	Text       string
	ToolName   string
	ToolArgs   map[string]any
	ToolResult any
	ToolError  string
	LatencyMS  int64
}

type Agent interface {
	Stream(ctx context.Context, messages []Message) (<-chan Event, <-chan error)
}

type DeepSeekAgent struct {
	cfg    config.Config
	tools  tools.Registry
	client tools.HTTPDoer
}

func NewEinoAgent(cfg config.Config, registry tools.Registry) Agent {
	return NewDeepSeekAgent(cfg, registry)
}

func NewDeepSeekAgent(cfg config.Config, registry tools.Registry) Agent {
	timeout := cfg.HTTPClientTimeout
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	return &DeepSeekAgent{
		cfg:    cfg,
		tools:  registry,
		client: &http.Client{Timeout: timeout},
	}
}

func (a *DeepSeekAgent) Stream(ctx context.Context, messages []Message) (<-chan Event, <-chan error) {
	events := make(chan Event)
	errs := make(chan error, 1)
	go func() {
		defer close(events)
		defer close(errs)
		if strings.TrimSpace(a.cfg.DeepSeekAPIKey) == "" {
			a.streamFallback(ctx, messages, events, errs)
			return
		}
		if err := a.streamDeepSeek(ctx, messages, events); err != nil {
			errs <- err
		}
	}()
	return events, errs
}

func (a *DeepSeekAgent) streamFallback(ctx context.Context, messages []Message, events chan<- Event, errs chan<- error) {
	prompt := lastUserContent(messages)
	if name, args, ok := fallbackToolCall(prompt); ok {
		if !send(ctx, events, Event{Kind: "tool_call", ToolName: name, ToolArgs: args}) {
			errs <- ctx.Err()
			return
		}
		start := time.Now()
		result, err := a.tools.Execute(ctx, name, args)
		latency := time.Since(start).Milliseconds()
		resultEvent := Event{Kind: "tool_result", ToolName: name, ToolArgs: args, ToolResult: result, LatencyMS: latency}
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

func (a *DeepSeekAgent) streamDeepSeek(ctx context.Context, messages []Message, events chan<- Event) error {
	endpoint, err := deepSeekEndpoint(a.cfg.DeepSeekBaseURL)
	if err != nil {
		return err
	}
	body := map[string]any{
		"model":    a.cfg.DeepSeekModel,
		"stream":   true,
		"messages": messages,
		"tools":    toolDefinitions(),
	}
	payload, err := json.Marshal(body)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(payload))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+a.cfg.DeepSeekAPIKey)
	req.Header.Set("Content-Type", "application/json")
	resp, err := a.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("deepseek status %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	return a.parseOpenAICompatibleStream(ctx, resp.Body, events)
}

func (a *DeepSeekAgent) parseOpenAICompatibleStream(ctx context.Context, body io.Reader, events chan<- Event) error {
	scanner := bufio.NewScanner(body)
	scanner.Buffer(make([]byte, 1024), 1024*1024)
	pendingTools := map[int]*pendingToolCall{}
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, ":") {
			continue
		}
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if data == "[DONE]" {
			return a.executePendingToolCalls(ctx, pendingTools, events)
		}
		var chunk streamChunk
		if err := json.Unmarshal([]byte(data), &chunk); err != nil {
			return err
		}
		for _, choice := range chunk.Choices {
			if choice.Delta.ReasoningContent != "" {
				if !send(ctx, events, Event{Kind: "reasoning", Text: choice.Delta.ReasoningContent}) {
					return ctx.Err()
				}
			}
			if choice.Delta.Content != "" {
				if !send(ctx, events, Event{Kind: "delta", Text: choice.Delta.Content}) {
					return ctx.Err()
				}
			}
			for _, toolCall := range choice.Delta.ToolCalls {
				pending := pendingTools[toolCall.Index]
				if pending == nil {
					pending = &pendingToolCall{}
					pendingTools[toolCall.Index] = pending
				}
				if toolCall.Function.Name != "" {
					pending.name = toolCall.Function.Name
				}
				pending.arguments += toolCall.Function.Arguments
			}
		}
	}
	if err := scanner.Err(); err != nil {
		return err
	}
	return a.executePendingToolCalls(ctx, pendingTools, events)
}

type streamChunk struct {
	Choices []struct {
		Delta struct {
			Content          string `json:"content"`
			ReasoningContent string `json:"reasoning_content"`
			ToolCalls        []struct {
				Index    int    `json:"index"`
				Type     string `json:"type"`
				Function struct {
					Name      string `json:"name"`
					Arguments string `json:"arguments"`
				} `json:"function"`
			} `json:"tool_calls"`
		} `json:"delta"`
		FinishReason string `json:"finish_reason"`
	} `json:"choices"`
}

type pendingToolCall struct {
	name      string
	arguments string
}

func (a *DeepSeekAgent) executePendingToolCalls(ctx context.Context, pendingTools map[int]*pendingToolCall, events chan<- Event) error {
	if len(pendingTools) == 0 {
		return nil
	}
	indexes := make([]int, 0, len(pendingTools))
	for index := range pendingTools {
		indexes = append(indexes, index)
	}
	sort.Ints(indexes)
	for _, index := range indexes {
		pending := pendingTools[index]
		if pending == nil || pending.name == "" {
			continue
		}
		args := map[string]any{}
		if strings.TrimSpace(pending.arguments) != "" {
			if err := json.Unmarshal([]byte(pending.arguments), &args); err != nil {
				if !send(ctx, events, Event{Kind: "tool_result", ToolName: pending.name, ToolError: err.Error()}) {
					return ctx.Err()
				}
				continue
			}
		}
		if !send(ctx, events, Event{Kind: "tool_call", ToolName: pending.name, ToolArgs: args}) {
			return ctx.Err()
		}
		start := time.Now()
		result, err := a.tools.Execute(ctx, pending.name, args)
		resultEvent := Event{
			Kind:       "tool_result",
			ToolName:   pending.name,
			ToolArgs:   args,
			ToolResult: result,
			LatencyMS:  time.Since(start).Milliseconds(),
		}
		if err != nil {
			resultEvent.ToolError = err.Error()
		}
		if !send(ctx, events, resultEvent) {
			return ctx.Err()
		}
	}
	return nil
}

func toolDefinitions() []map[string]any {
	return []map[string]any{
		{
			"type": "function",
			"function": map[string]any{
				"name":        "web_search",
				"description": "Search the web for current information.",
				"parameters": map[string]any{
					"type": "object",
					"properties": map[string]any{
						"query": map[string]any{"type": "string"},
					},
					"required": []string{"query"},
				},
			},
		},
		{
			"type": "function",
			"function": map[string]any{
				"name":        "fetch_url",
				"description": "Fetch a URL and extract visible title and text.",
				"parameters": map[string]any{
					"type": "object",
					"properties": map[string]any{
						"url": map[string]any{"type": "string"},
					},
					"required": []string{"url"},
				},
			},
		},
	}
}

func deepSeekEndpoint(base string) (string, error) {
	if strings.TrimSpace(base) == "" {
		base = "https://api.deepseek.com"
	}
	parsed, err := url.Parse(base)
	if err != nil {
		return "", err
	}
	if parsed.Scheme == "" || parsed.Host == "" {
		return "", errors.New("DeepSeekBaseURL must be an absolute URL")
	}
	parsed.Path = strings.TrimRight(parsed.Path, "/") + "/chat/completions"
	return parsed.String(), nil
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
