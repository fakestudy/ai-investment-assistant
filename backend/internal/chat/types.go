package chat

import (
	"encoding/json"

	"ai-investment-assistant/backend/internal/agent"
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

func (e StreamEvent) MarshalJSON() ([]byte, error) {
	if e.Type == "error" {
		return json.Marshal(struct {
			Type      string `json:"type"`
			MessageID string `json:"messageId,omitempty"`
			Message   string `json:"message,omitempty"`
		}{
			Type:      e.Type,
			MessageID: e.MessageID,
			Message:   e.Text,
		})
	}

	type streamEvent StreamEvent
	return json.Marshal(streamEvent(e))
}

type AgentMessage = agent.Message
type AgentEvent = agent.Event
type Agent = agent.Agent
