package agent

import (
	"context"
	"fmt"
	"strings"

	"github.com/cloudwego/eino/schema"
)

const currentTimeToolName = "current_time"

var currentTimeTriggerTerms = []string{
	"今天",
	"今日",
	"现在",
	"当前",
	"最新",
	"实时",
	"截至目前",
	"此刻",
	"today",
	"now",
	"current",
	"latest",
	"real-time",
	"realtime",
	"as of now",
}

func shouldInjectCurrentTime(messages []Message) bool {
	for i := len(messages) - 1; i >= 0; i-- {
		if strings.TrimSpace(messages[i].Role) != "user" {
			continue
		}
		content := strings.ToLower(messages[i].Content)
		for _, term := range currentTimeTriggerTerms {
			if strings.Contains(content, term) {
				return true
			}
		}
		return false
	}
	return false
}

func (r *EinoRuntime) currentTimeContextMessage(ctx context.Context, events chan<- Event) (*schema.Message, error) {
	if _, ok := r.tools[currentTimeToolName]; !ok {
		return nil, nil
	}
	result, err := r.executeToolCall(ctx, events, schema.ToolCall{
		ID:   "preflight_current_time",
		Type: "function",
		Function: schema.FunctionCall{
			Name:      currentTimeToolName,
			Arguments: `{}`,
		},
	})
	if err != nil {
		return nil, err
	}
	return &schema.Message{
		Role: schema.System,
		Content: fmt.Sprintf(
			"current_time tool result: %s\nUse this as the authoritative current date, time, and timezone before answering time-sensitive questions.",
			result.Content,
		),
	}, nil
}
