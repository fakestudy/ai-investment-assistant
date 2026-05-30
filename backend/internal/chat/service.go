package chat

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"time"
	"unicode/utf8"

	agentpkg "ai-investment-assistant/backend/internal/agent"
	"ai-investment-assistant/backend/internal/config"
	"ai-investment-assistant/backend/internal/conversation"
	"ai-investment-assistant/backend/internal/tools"
	"github.com/google/uuid"
)

type Service struct {
	conversations *conversation.Service
	agent         Agent
}

type ValidationError struct {
	Message string
}

func (e ValidationError) Error() string {
	return e.Message
}

func NewService(conversations *conversation.Service, agent Agent) *Service {
	if agent == nil {
		cfg := config.Config{}
		agent = agentpkg.NewEinoAgent(cfg, tools.NewRegistry(cfg))
	}
	return &Service{
		conversations: conversations,
		agent:         agent,
	}
}

func (s *Service) Stream(ctx context.Context, request StreamChatRequest) (<-chan StreamEvent, error) {
	conversationID := strings.TrimSpace(request.ConversationID)
	messageText := strings.TrimSpace(request.Message)
	if conversationID == "" {
		return nil, ValidationError{Message: "conversationId is required"}
	}
	if messageText == "" && strings.TrimSpace(request.RegenerateFromMessageID) == "" {
		return nil, ValidationError{Message: "message is required"}
	}

	prompt, shouldCreateUser, err := s.resolvePrompt(ctx, conversationID, messageText, request)
	if err != nil {
		return nil, err
	}
	if shouldCreateUser {
		if _, err := s.conversations.CreateMessage(ctx, conversation.CreateMessageInput{
			ConversationID: conversationID,
			Role:           "user",
			Content:        prompt,
			Status:         "complete",
		}); err != nil {
			return nil, err
		}
	}
	assistant, err := s.conversations.CreateMessage(ctx, conversation.CreateMessageInput{
		ConversationID: conversationID,
		Role:           "assistant",
		Status:         "streaming",
	})
	if err != nil {
		return nil, err
	}

	output := make(chan StreamEvent)
	go s.runStream(ctx, conversationID, prompt, assistant, output)
	return output, nil
}

func (s *Service) resolvePrompt(ctx context.Context, conversationID string, messageText string, request StreamChatRequest) (string, bool, error) {
	if parentID := strings.TrimSpace(request.ParentMessageID); parentID != "" {
		parent, err := s.findMessage(ctx, conversationID, parentID)
		if err != nil {
			return "", false, err
		}
		if messageText != "" {
			return messageText, false, nil
		}
		return parent.Content, false, nil
	}

	if regenerateID := strings.TrimSpace(request.RegenerateFromMessageID); regenerateID != "" {
		message, err := s.findMessage(ctx, conversationID, regenerateID)
		if err != nil {
			return "", false, err
		}
		if messageText != "" {
			return messageText, false, nil
		}
		prompt := message.Content
		if message.Role == "assistant" {
			if previous, ok := s.previousUserMessage(ctx, conversationID, message.ID); ok {
				prompt = previous.Content
			}
		}
		return prompt, false, nil
	}

	return messageText, true, nil
}

func (s *Service) findMessage(ctx context.Context, conversationID string, messageID string) (conversation.ChatMessage, error) {
	messages, err := s.conversations.ListMessages(ctx, conversationID)
	if err != nil {
		return conversation.ChatMessage{}, err
	}
	for _, message := range messages {
		if message.ID == messageID {
			return message, nil
		}
	}
	return conversation.ChatMessage{}, conversation.ErrNotFound
}

func (s *Service) previousUserMessage(ctx context.Context, conversationID string, beforeMessageID string) (conversation.ChatMessage, bool) {
	messages, err := s.conversations.ListMessages(ctx, conversationID)
	if err != nil {
		return conversation.ChatMessage{}, false
	}
	var previous conversation.ChatMessage
	for _, message := range messages {
		if message.ID == beforeMessageID {
			return previous, previous.ID != ""
		}
		if message.Role == "user" {
			previous = message
		}
	}
	return conversation.ChatMessage{}, false
}

func (s *Service) runStream(ctx context.Context, conversationID string, prompt string, assistant conversation.ChatMessage, output chan<- StreamEvent) {
	defer close(output)

	if !sendEvent(ctx, output, StreamEvent{Type: "message_created", Message: &assistant}) {
		s.finalizeCanceled(ctx, assistant.ID, "", "")
		return
	}

	agentEvents, agentErrors := s.agent.Stream(ctx, []AgentMessage{{Role: "user", Content: prompt}})
	var content strings.Builder
	var reasoning strings.Builder
	for agentEvents != nil || agentErrors != nil {
		select {
		case <-ctx.Done():
			s.finalizeCanceled(ctx, assistant.ID, content.String(), reasoning.String())
			return
		case err, ok := <-agentErrors:
			if ok && err != nil {
				s.finalizeError(ctx, assistant.ID, content.String(), reasoning.String(), err)
				_ = sendEvent(ctx, output, StreamEvent{Type: "error", MessageID: assistant.ID, Text: err.Error()})
				return
			}
			if !ok {
				agentErrors = nil
			}
		case event, ok := <-agentEvents:
			if !ok {
				agentEvents = nil
				continue
			}
			if !s.handleAgentEvent(ctx, output, assistant.ID, event, &content, &reasoning) {
				s.finalizeCanceled(ctx, assistant.ID, content.String(), reasoning.String())
				return
			}
		}
	}

	if _, err := s.conversations.UpdateMessage(context.WithoutCancel(ctx), assistant.ID, conversation.UpdateMessageInput{
		Content:   content.String(),
		Reasoning: reasoning.String(),
		Status:    "complete",
	}); err != nil {
		_ = sendEvent(ctx, output, StreamEvent{Type: "error", MessageID: assistant.ID, Text: err.Error()})
		return
	}

	if title, ok := s.renameDefaultConversation(context.WithoutCancel(ctx), conversationID, prompt); ok {
		if !sendEvent(ctx, output, StreamEvent{Type: "title", ConversationID: conversationID, Title: title}) {
			return
		}
	}
	_ = sendEvent(ctx, output, StreamEvent{Type: "done", MessageID: assistant.ID})
}

func (s *Service) handleAgentEvent(ctx context.Context, output chan<- StreamEvent, assistantID string, event AgentEvent, content *strings.Builder, reasoning *strings.Builder) bool {
	switch event.Kind {
	case "reasoning":
		if !sendEvent(ctx, output, StreamEvent{Type: "reasoning", MessageID: assistantID, Text: event.Text}) {
			return false
		}
		reasoning.WriteString(event.Text)
		return true
	case "tool_call":
		invocation := invocationFromAgentEvent(assistantID, event, "running")
		return sendEvent(ctx, output, StreamEvent{Type: "tool_call", MessageID: assistantID, Invocation: &invocation})
	case "tool_result":
		status := "complete"
		if event.ToolError != "" {
			status = "error"
		}
		invocation := invocationFromAgentEvent(assistantID, event, status)
		return sendEvent(ctx, output, StreamEvent{Type: "tool_result", MessageID: assistantID, Invocation: &invocation})
	default:
		if !sendEvent(ctx, output, StreamEvent{Type: "delta", MessageID: assistantID, Text: event.Text}) {
			return false
		}
		content.WriteString(event.Text)
		return true
	}
}

func invocationFromAgentEvent(assistantID string, event AgentEvent, status string) ToolInvocation {
	return ToolInvocation{
		ID:        uuid.NewString(),
		MessageID: assistantID,
		ToolName:  event.ToolName,
		Args:      mustJSON(event.ToolArgs),
		Result:    mustJSON(event.ToolResult),
		Error:     event.ToolError,
		LatencyMS: event.LatencyMS,
		Status:    status,
		CreatedAt: time.Now(),
	}
}

func mustJSON(value any) json.RawMessage {
	if value == nil {
		return nil
	}
	raw, err := json.Marshal(value)
	if err != nil {
		return json.RawMessage(`null`)
	}
	return raw
}

func (s *Service) finalizeCanceled(ctx context.Context, assistantID string, content string, reasoning string) {
	_, _ = s.conversations.UpdateMessage(context.WithoutCancel(ctx), assistantID, conversation.UpdateMessageInput{
		Content:   content,
		Reasoning: reasoning,
		Status:    "cancelled",
	})
}

func (s *Service) finalizeError(ctx context.Context, assistantID string, content string, reasoning string, err error) {
	_, _ = s.conversations.UpdateMessage(context.WithoutCancel(ctx), assistantID, conversation.UpdateMessageInput{
		Content:   content,
		Reasoning: reasoning,
		Status:    "error",
	})
}

func (s *Service) renameDefaultConversation(ctx context.Context, conversationID string, prompt string) (string, bool) {
	conversations, err := s.conversations.ListConversations(ctx)
	if err != nil {
		return "", false
	}
	for _, item := range conversations {
		if item.ID != conversationID {
			continue
		}
		if item.Title != "New chat" {
			return "", false
		}
		title := trimTitle(prompt)
		if _, err := s.conversations.RenameConversation(ctx, conversationID, title); err != nil {
			return "", false
		}
		return title, true
	}
	return "", false
}

func trimTitle(prompt string) string {
	title := strings.TrimSpace(prompt)
	const maxRunes = 60
	if utf8.RuneCountInString(title) <= maxRunes {
		return title
	}
	runes := []rune(title)
	return string(runes[:maxRunes])
}

func sendEvent(ctx context.Context, output chan<- StreamEvent, event StreamEvent) bool {
	select {
	case <-ctx.Done():
		return false
	case output <- event:
		return true
	}
}

func IsValidation(err error) bool {
	var validation ValidationError
	return errors.As(err, &validation)
}

func ValidationMessage(err error) string {
	var validation ValidationError
	if errors.As(err, &validation) {
		return validation.Message
	}
	return "invalid request"
}
