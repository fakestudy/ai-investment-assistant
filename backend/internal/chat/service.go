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
	streams       *streamManager
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
		streams:       newStreamManager(),
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

	prompt, shouldCreateUser, historyThroughID, err := s.resolvePrompt(ctx, conversationID, messageText, request)
	if err != nil {
		return nil, err
	}
	if shouldCreateUser {
		createdUser, err := s.conversations.CreateMessage(ctx, conversation.CreateMessageInput{
			ConversationID: conversationID,
			Role:           "user",
			Content:        prompt,
			Status:         "idle",
		})
		if err != nil {
			return nil, err
		}
		historyThroughID = createdUser.ID
	}
	agentMessages, err := s.agentMessages(ctx, conversationID, historyThroughID, prompt)
	if err != nil {
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

	streamCtx, cancel := context.WithCancel(context.Background())
	stream := s.streams.start(assistant.ID, cancel)
	go s.runStream(streamCtx, conversationID, prompt, agentMessages, assistant, stream)
	return s.streams.subscribe(ctx, assistant.ID)
}

func (s *Service) ResumeStream(ctx context.Context, assistantMessageID string) (<-chan StreamEvent, error) {
	messageID := strings.TrimSpace(assistantMessageID)
	if messageID == "" {
		return nil, ValidationError{Message: "messageId is required"}
	}
	return s.streams.subscribe(ctx, messageID)
}

func (s *Service) CancelStream(ctx context.Context, assistantMessageID string) error {
	messageID := strings.TrimSpace(assistantMessageID)
	if messageID == "" {
		return ValidationError{Message: "messageId is required"}
	}
	return s.streams.cancel(messageID)
}

func (s *Service) resolvePrompt(ctx context.Context, conversationID string, messageText string, request StreamChatRequest) (string, bool, string, error) {
	if parentID := strings.TrimSpace(request.ParentMessageID); parentID != "" {
		parent, err := s.findMessage(ctx, conversationID, parentID)
		if err != nil {
			return "", false, "", err
		}
		if messageText != "" {
			return messageText, false, parent.ID, nil
		}
		return parent.Content, false, parent.ID, nil
	}

	if regenerateID := strings.TrimSpace(request.RegenerateFromMessageID); regenerateID != "" {
		message, err := s.findMessage(ctx, conversationID, regenerateID)
		if err != nil {
			return "", false, "", err
		}
		if messageText != "" {
			if message.Role == "assistant" {
				if previous, ok := s.previousUserMessage(ctx, conversationID, message.ID); ok {
					return messageText, false, previous.ID, nil
				}
			}
			return messageText, false, message.ID, nil
		}
		prompt := message.Content
		historyThroughID := message.ID
		if message.Role == "assistant" {
			if previous, ok := s.previousUserMessage(ctx, conversationID, message.ID); ok {
				prompt = previous.Content
				historyThroughID = previous.ID
			}
		}
		return prompt, false, historyThroughID, nil
	}

	return messageText, true, "", nil
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

func (s *Service) agentMessages(ctx context.Context, conversationID string, throughMessageID string, prompt string) ([]AgentMessage, error) {
	messages, err := s.conversations.ListMessages(ctx, conversationID)
	if err != nil {
		return nil, err
	}
	history := make([]AgentMessage, 0, len(messages))
	foundLimit := throughMessageID == ""
	for _, message := range messages {
		if message.Role == "user" || message.Role == "assistant" {
			if strings.TrimSpace(message.Content) != "" {
				history = append(history, AgentMessage{Role: message.Role, Content: message.Content})
			}
		}
		if throughMessageID != "" && message.ID == throughMessageID {
			foundLimit = true
			break
		}
	}
	if len(history) > 0 && prompt != "" && history[len(history)-1].Role == "user" {
		history[len(history)-1].Content = prompt
	}
	if !foundLimit || len(history) == 0 {
		return []AgentMessage{{Role: "user", Content: prompt}}, nil
	}
	return history, nil
}

func (s *Service) runStream(ctx context.Context, conversationID string, prompt string, agentMessages []AgentMessage, assistant conversation.ChatMessage, stream *activeStream) {
	defer s.streams.finish(assistant.ID, stream)

	if ctx.Err() != nil {
		s.finalizeCanceled(ctx, assistant.ID, "", "")
		return
	}
	stream.publish(StreamEvent{Type: "message_created", Message: &assistant})

	agentEvents, agentErrors := s.agent.Stream(ctx, agentMessages)
	var content strings.Builder
	var reasoning strings.Builder
	toolInvocations := map[string]ToolInvocation{}
	timelineState := messageTimelineState{}
	for agentEvents != nil || agentErrors != nil {
		select {
		case <-ctx.Done():
			s.finalizeCanceled(ctx, assistant.ID, content.String(), reasoning.String())
			stream.publish(StreamEvent{Type: "done", MessageID: assistant.ID})
			return
		case err, ok := <-agentErrors:
			if ok && err != nil {
				if ctx.Err() != nil {
					s.finalizeCanceled(ctx, assistant.ID, content.String(), reasoning.String())
					stream.publish(StreamEvent{Type: "done", MessageID: assistant.ID})
					return
				}
				s.finalizeError(ctx, assistant.ID, content.String(), reasoning.String(), err)
				stream.publish(StreamEvent{Type: "error", MessageID: assistant.ID, Text: err.Error()})
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
			if !s.handleAgentEvent(ctx, stream, assistant.ID, event, &content, &reasoning, toolInvocations, &timelineState) {
				s.finalizeCanceled(ctx, assistant.ID, content.String(), reasoning.String())
				stream.publish(StreamEvent{Type: "done", MessageID: assistant.ID})
				return
			}
		}
	}

	if _, err := s.conversations.UpdateMessage(context.WithoutCancel(ctx), assistant.ID, conversation.UpdateMessageInput{
		Content:   content.String(),
		Reasoning: reasoning.String(),
		Status:    "done",
	}); err != nil {
		stream.publish(StreamEvent{Type: "error", MessageID: assistant.ID, Text: err.Error()})
		return
	}

	if title, ok := s.renameDefaultConversation(context.WithoutCancel(ctx), conversationID, prompt); ok {
		stream.publish(StreamEvent{Type: "title", ConversationID: conversationID, Title: title})
	}
	stream.publish(StreamEvent{Type: "done", MessageID: assistant.ID})
}

type messageTimelineState struct {
	nextOrderIndex int
	lastPartID     string
	lastPartType   string
	lastPartText   string
}

func (s *Service) handleAgentEvent(ctx context.Context, stream *activeStream, assistantID string, event AgentEvent, content *strings.Builder, reasoning *strings.Builder, toolInvocations map[string]ToolInvocation, timelineState *messageTimelineState) bool {
	if ctx.Err() != nil {
		return false
	}

	switch event.Kind {
	case "reasoning":
		stream.publish(StreamEvent{Type: "reasoning", MessageID: assistantID, Text: event.Text})
		reasoning.WriteString(event.Text)
		s.appendReasoningPart(ctx, assistantID, event.Text, timelineState)
		return true
	case "tool_call":
		invocation := invocationFromAgentEvent(assistantID, event, "running")
		if persisted, err := s.conversations.CreateToolInvocation(context.WithoutCancel(ctx), conversation.CreateToolInvocationInput{
			MessageID: assistantID,
			ToolName:  invocation.ToolName,
			Args:      invocation.Args,
			Result:    invocation.Result,
			Error:     invocation.Error,
			LatencyMS: invocation.LatencyMS,
			Status:    invocation.Status,
		}); err == nil {
			invocation = persisted
		}
		toolInvocations[toolInvocationKey(event)] = invocation
		s.appendToolPart(ctx, assistantID, invocation.ID, timelineState)
		stream.publish(StreamEvent{Type: "tool_call", MessageID: assistantID, Invocation: &invocation})
		return true
	case "tool_result":
		status := "completed"
		if event.ToolError != "" {
			status = "error"
		}
		invocation := invocationFromAgentEvent(assistantID, event, status)
		if previous, ok := toolInvocations[toolInvocationKey(event)]; ok {
			invocation.ID = previous.ID
			invocation.CreatedAt = previous.CreatedAt
			if persisted, err := s.conversations.UpdateToolInvocation(context.WithoutCancel(ctx), previous.ID, conversation.UpdateToolInvocationInput{
				Args:      invocation.Args,
				Result:    invocation.Result,
				Error:     invocation.Error,
				LatencyMS: invocation.LatencyMS,
				Status:    invocation.Status,
			}); err == nil {
				invocation = persisted
			}
		} else if persisted, err := s.conversations.CreateToolInvocation(context.WithoutCancel(ctx), conversation.CreateToolInvocationInput{
			MessageID: assistantID,
			ToolName:  invocation.ToolName,
			Args:      invocation.Args,
			Result:    invocation.Result,
			Error:     invocation.Error,
			LatencyMS: invocation.LatencyMS,
			Status:    invocation.Status,
		}); err == nil {
			invocation = persisted
		}
		stream.publish(StreamEvent{Type: "tool_result", MessageID: assistantID, Invocation: &invocation})
		return true
	default:
		stream.publish(StreamEvent{Type: "delta", MessageID: assistantID, Text: event.Text})
		content.WriteString(event.Text)
		return true
	}
}

func (s *Service) appendReasoningPart(ctx context.Context, assistantID string, text string, timelineState *messageTimelineState) {
	if timelineState == nil || text == "" {
		return
	}
	if timelineState.lastPartType == "reasoning" && timelineState.lastPartID != "" {
		timelineState.lastPartText += text
		if updated, err := s.conversations.UpdateMessagePart(context.WithoutCancel(ctx), timelineState.lastPartID, conversation.UpdateMessagePartInput{
			Text: timelineState.lastPartText,
		}); err == nil {
			timelineState.lastPartText = updated.Text
		}
		return
	}
	part, err := s.conversations.CreateMessagePart(context.WithoutCancel(ctx), conversation.CreateMessagePartInput{
		MessageID:  assistantID,
		Type:       "reasoning",
		OrderIndex: timelineState.nextOrderIndex,
		Text:       text,
	})
	if err != nil {
		return
	}
	timelineState.nextOrderIndex++
	timelineState.lastPartID = part.ID
	timelineState.lastPartType = part.Type
	timelineState.lastPartText = part.Text
}

func (s *Service) appendToolPart(ctx context.Context, assistantID string, toolInvocationID string, timelineState *messageTimelineState) {
	if timelineState == nil || toolInvocationID == "" {
		return
	}
	part, err := s.conversations.CreateMessagePart(context.WithoutCancel(ctx), conversation.CreateMessagePartInput{
		MessageID:        assistantID,
		Type:             "tool",
		OrderIndex:       timelineState.nextOrderIndex,
		ToolInvocationID: toolInvocationID,
	})
	if err != nil {
		return
	}
	timelineState.nextOrderIndex++
	timelineState.lastPartID = part.ID
	timelineState.lastPartType = part.Type
	timelineState.lastPartText = part.Text
}

func toolInvocationKey(event AgentEvent) string {
	if strings.TrimSpace(event.ToolCallID) != "" {
		return event.ToolCallID
	}
	return event.ToolName + ":" + string(mustJSON(event.ToolArgs))
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
		Status:    "done",
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
