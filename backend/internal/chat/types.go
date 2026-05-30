package chat

import (
	"context"

	"ai-investment-assistant/backend/internal/conversation"
)

type ChatMessage = conversation.ChatMessage
type ToolInvocation = conversation.ToolInvocation

type StreamChatRequest struct {
	ConversationID          string `json:"conversationId"`
	Message                 string `json:"message"`
	ParentMessageID         string `json:"parentMessageId,omitempty"`
	RegenerateFromMessageID string `json:"regenerateFromMessageId,omitempty"`
}

type StreamEvent struct {
	Type           string          `json:"type"`
	Message        *ChatMessage    `json:"message,omitempty"`
	MessageID      string          `json:"messageId,omitempty"`
	Text           string          `json:"text,omitempty"`
	Invocation     *ToolInvocation `json:"invocation,omitempty"`
	ConversationID string          `json:"conversationId,omitempty"`
	Title          string          `json:"title,omitempty"`
}

type AgentMessage struct {
	Role    string
	Content string
}

type AgentEvent struct {
	Kind       string
	Text       string
	Invocation *ToolInvocation
}

type Agent interface {
	Stream(ctx context.Context, messages []AgentMessage) (<-chan AgentEvent, <-chan error)
}
