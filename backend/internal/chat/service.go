package chat

import (
	"context"
	"errors"
	"strings"
	"unicode/utf8"

	"ai-investment-assistant/backend/internal/conversation"
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
		agent = EchoAgent{}
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
	if messageText == "" {
		return nil, ValidationError{Message: "message is required"}
	}

	if _, err := s.conversations.CreateMessage(ctx, conversation.CreateMessageInput{
		ConversationID: conversationID,
		Role:           "user",
		Content:        messageText,
		Status:         "complete",
	}); err != nil {
		return nil, err
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
	go s.runStream(ctx, conversationID, messageText, assistant, output)
	return output, nil
}

func (s *Service) runStream(ctx context.Context, conversationID string, prompt string, assistant conversation.ChatMessage, output chan<- StreamEvent) {
	defer close(output)

	if !sendEvent(ctx, output, StreamEvent{Type: "message_created", Message: &assistant}) {
		return
	}

	agentEvents, agentErrors := s.agent.Stream(ctx, []AgentMessage{{Role: "user", Content: prompt}})
	var content strings.Builder
	var reasoning strings.Builder
	for event := range agentEvents {
		switch event.Kind {
		case "reasoning":
			reasoning.WriteString(event.Text)
			if !sendEvent(ctx, output, StreamEvent{Type: "reasoning", MessageID: assistant.ID, Text: event.Text}) {
				return
			}
		case "tool_call":
			if !sendEvent(ctx, output, StreamEvent{Type: "tool_call", MessageID: assistant.ID, Invocation: event.Invocation}) {
				return
			}
		case "tool_result":
			if !sendEvent(ctx, output, StreamEvent{Type: "tool_result", MessageID: assistant.ID, Invocation: event.Invocation}) {
				return
			}
		default:
			content.WriteString(event.Text)
			if !sendEvent(ctx, output, StreamEvent{Type: "delta", MessageID: assistant.ID, Text: event.Text}) {
				return
			}
		}
	}

	if err := firstAgentError(agentErrors); err != nil {
		_, _ = s.conversations.UpdateMessage(ctx, assistant.ID, conversation.UpdateMessageInput{
			Content:   content.String(),
			Reasoning: reasoning.String(),
			Status:    "error",
		})
		_ = sendEvent(ctx, output, StreamEvent{Type: "error", MessageID: assistant.ID, Text: err.Error()})
		return
	}

	if _, err := s.conversations.UpdateMessage(ctx, assistant.ID, conversation.UpdateMessageInput{
		Content:   content.String(),
		Reasoning: reasoning.String(),
		Status:    "complete",
	}); err != nil {
		_ = sendEvent(ctx, output, StreamEvent{Type: "error", MessageID: assistant.ID, Text: err.Error()})
		return
	}

	if title, ok := s.renameDefaultConversation(ctx, conversationID, prompt); ok {
		if !sendEvent(ctx, output, StreamEvent{Type: "title", ConversationID: conversationID, Title: title}) {
			return
		}
	}
	_ = sendEvent(ctx, output, StreamEvent{Type: "done", MessageID: assistant.ID})
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

func firstAgentError(errors <-chan error) error {
	for err := range errors {
		if err != nil {
			return err
		}
	}
	return nil
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

type EchoAgent struct{}

func (EchoAgent) Stream(ctx context.Context, messages []AgentMessage) (<-chan AgentEvent, <-chan error) {
	events := make(chan AgentEvent)
	errs := make(chan error)
	go func() {
		defer close(events)
		defer close(errs)
		text := ""
		if len(messages) > 0 {
			text = messages[len(messages)-1].Content
		}
		select {
		case <-ctx.Done():
			errs <- ctx.Err()
		case events <- AgentEvent{Kind: "delta", Text: text}:
		}
	}()
	return events, errs
}
