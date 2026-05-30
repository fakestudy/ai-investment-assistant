package chat

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"ai-investment-assistant/backend/internal/conversation"
	"ai-investment-assistant/backend/internal/store"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

var testDBSequence uint64

func TestServiceStreamsAgentOutputAndPersistsMessages(t *testing.T) {
	ctx := context.Background()
	conversations := newTestConversationService(t)
	created, err := conversations.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	svc := NewService(conversations, fakeAgent{
		events: []AgentEvent{
			{Kind: "reasoning", Text: "checking context"},
			{Kind: "delta", Text: "Hello"},
			{Kind: "delta", Text: " investor"},
		},
	})

	events, err := svc.Stream(ctx, StreamChatRequest{
		ConversationID: created.ID,
		Message:        "Explain AI moats",
	})
	if err != nil {
		t.Fatalf("Stream() error = %v", err)
	}
	collected := collectEvents(t, events)

	assertEventTypes(t, collected, []string{"message_created", "reasoning", "delta", "delta", "title", "done"})
	if collected[0].Message == nil {
		t.Fatal("message_created event Message = nil, want assistant message")
	}
	assistantID := collected[0].Message.ID
	if collected[0].Message.Status != "streaming" {
		t.Fatalf("assistant status at creation = %q, want streaming", collected[0].Message.Status)
	}
	if collected[2].MessageID != assistantID || collected[2].Text != "Hello" {
		t.Fatalf("first delta = %+v, want assistant id %q and text Hello", collected[2], assistantID)
	}
	if collected[4].ConversationID != created.ID || collected[4].Title != "Explain AI moats" {
		t.Fatalf("title event = %+v, want conversation title from prompt", collected[4])
	}

	messages, err := conversations.ListMessages(ctx, created.ID)
	if err != nil {
		t.Fatalf("ListMessages() error = %v", err)
	}
	if len(messages) != 2 {
		t.Fatalf("ListMessages() len = %d, want 2", len(messages))
	}
	if messages[0].Role != "user" || messages[0].Content != "Explain AI moats" || messages[0].Status != "idle" {
		t.Fatalf("user message = %+v, want idle persisted prompt", messages[0])
	}
	if messages[1].ID != assistantID || messages[1].Content != "Hello investor" || messages[1].Reasoning != "checking context" || messages[1].Status != "done" {
		t.Fatalf("assistant message = %+v, want done streamed output", messages[1])
	}
	conversationRow := mustFindConversation(t, ctx, conversations, created.ID)
	if conversationRow.Title != "Explain AI moats" {
		t.Fatalf("conversation title = %q, want generated title", conversationRow.Title)
	}
}

func TestServiceEmitsErrorAndMarksAssistantMessageOnAgentFailure(t *testing.T) {
	ctx := context.Background()
	conversations := newTestConversationService(t)
	created, err := conversations.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	svc := NewService(conversations, fakeAgent{
		err: errors.New("agent unavailable"),
	})

	events, err := svc.Stream(ctx, StreamChatRequest{
		ConversationID: created.ID,
		Message:        "Will this fail?",
	})
	if err != nil {
		t.Fatalf("Stream() setup error = %v", err)
	}
	collected := collectEvents(t, events)

	assertEventTypes(t, collected, []string{"message_created", "error"})
	if collected[1].Text != "agent unavailable" {
		t.Fatalf("error event text = %q, want agent unavailable", collected[1].Text)
	}

	messages, err := conversations.ListMessages(ctx, created.ID)
	if err != nil {
		t.Fatalf("ListMessages() error = %v", err)
	}
	if len(messages) != 2 {
		t.Fatalf("ListMessages() len = %d, want 2", len(messages))
	}
	if messages[1].Status != "error" {
		t.Fatalf("assistant status = %q, want error", messages[1].Status)
	}
}

func TestServiceMapsAgentToolEventsToStreamInvocations(t *testing.T) {
	ctx := context.Background()
	conversations := newTestConversationService(t)
	created, err := conversations.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	svc := NewService(conversations, fakeAgent{
		events: []AgentEvent{
			{Kind: "tool_call", ToolCallID: "call-search-1", ToolName: "web_search", ToolArgs: map[string]any{"query": "AI moats"}},
			{Kind: "tool_result", ToolCallID: "call-search-1", ToolName: "web_search", ToolArgs: map[string]any{"query": "AI moats"}, ToolResult: map[string]any{"configured": false}, LatencyMS: 12},
			{Kind: "delta", Text: "Search unavailable."},
		},
	})

	events, err := svc.Stream(ctx, StreamChatRequest{
		ConversationID: created.ID,
		Message:        "web_search: AI moats",
	})
	if err != nil {
		t.Fatalf("Stream() error = %v", err)
	}
	collected := collectEvents(t, events)

	assertEventTypes(t, collected, []string{"message_created", "tool_call", "tool_result", "delta", "title", "done"})
	if collected[1].Invocation == nil || collected[1].Invocation.ToolName != "web_search" || collected[1].Invocation.Status != "running" {
		t.Fatalf("tool_call invocation = %+v, want running web_search", collected[1].Invocation)
	}
	if string(collected[1].Invocation.Args) != `{"query":"AI moats"}` {
		t.Fatalf("tool_call args = %s, want query JSON", collected[1].Invocation.Args)
	}
	if collected[2].Invocation == nil || collected[2].Invocation.ID != collected[1].Invocation.ID || collected[2].Invocation.Status != "completed" || collected[2].Invocation.LatencyMS != 12 {
		t.Fatalf("tool_result invocation = %+v, want same id completed result with latency; tool_call = %+v", collected[2].Invocation, collected[1].Invocation)
	}
	if string(collected[2].Invocation.Result) != `{"configured":false}` {
		t.Fatalf("tool_result result = %s, want result JSON", collected[2].Invocation.Result)
	}
	messages, err := conversations.ListMessages(ctx, created.ID)
	if err != nil {
		t.Fatalf("ListMessages() error = %v", err)
	}
	if len(messages) != 2 {
		t.Fatalf("ListMessages() len = %d, want user and assistant", len(messages))
	}
	if len(messages[1].ToolInvocations) != 1 {
		t.Fatalf("assistant tool invocations len = %d, want single updated tool invocation", len(messages[1].ToolInvocations))
	}
	if messages[1].ToolInvocations[0].ID != collected[1].Invocation.ID || messages[1].ToolInvocations[0].ToolName != "web_search" || messages[1].ToolInvocations[0].Status != "completed" {
		t.Fatalf("persisted invocation = %+v, want same id completed web_search", messages[1].ToolInvocations[0])
	}
}

func TestServiceMarksToolResultErrorsWithoutChangingInvocationID(t *testing.T) {
	ctx := context.Background()
	conversations := newTestConversationService(t)
	created, err := conversations.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	svc := NewService(conversations, fakeAgent{
		events: []AgentEvent{
			{Kind: "tool_call", ToolCallID: "call-fetch-1", ToolName: "fetch_url", ToolArgs: map[string]any{"url": "https://example.com"}},
			{Kind: "tool_result", ToolCallID: "call-fetch-1", ToolName: "fetch_url", ToolArgs: map[string]any{"url": "https://example.com"}, ToolError: "network denied", LatencyMS: 7},
		},
	})

	events, err := svc.Stream(ctx, StreamChatRequest{
		ConversationID: created.ID,
		Message:        "fetch_url: https://example.com",
	})
	if err != nil {
		t.Fatalf("Stream() error = %v", err)
	}
	collected := collectEvents(t, events)

	assertEventTypes(t, collected, []string{"message_created", "tool_call", "tool_result", "title", "done"})
	if collected[2].Invocation == nil || collected[2].Invocation.ID != collected[1].Invocation.ID || collected[2].Invocation.Status != "error" || collected[2].Invocation.Error != "network denied" {
		t.Fatalf("tool_result invocation = %+v, want same id error result; tool_call = %+v", collected[2].Invocation, collected[1].Invocation)
	}
	messages, err := conversations.ListMessages(ctx, created.ID)
	if err != nil {
		t.Fatalf("ListMessages() error = %v", err)
	}
	if len(messages[1].ToolInvocations) != 1 || messages[1].ToolInvocations[0].ID != collected[1].Invocation.ID || messages[1].ToolInvocations[0].Status != "error" {
		t.Fatalf("persisted invocations = %+v, want one error invocation with tool_call id", messages[1].ToolInvocations)
	}
}

func TestServicePersistsPartialAssistantWhenClientCancels(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	conversations := newTestConversationService(t)
	created, err := conversations.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	svc := NewService(conversations, fakeAgent{
		events: []AgentEvent{
			{Kind: "delta", Text: "partial"},
			{Kind: "delta", Text: " ignored"},
		},
	})

	events, err := svc.Stream(ctx, StreamChatRequest{
		ConversationID: created.ID,
		Message:        "Cancel after first chunk",
	})
	if err != nil {
		t.Fatalf("Stream() error = %v", err)
	}
	first := <-events
	if first.Type != "message_created" {
		t.Fatalf("first event type = %q, want message_created", first.Type)
	}
	second := <-events
	if second.Type != "delta" || second.Text != "partial" {
		t.Fatalf("second event = %+v, want first delta", second)
	}
	cancel()
	waitForClosedEvents(t, events)

	messages, err := conversations.ListMessages(context.Background(), created.ID)
	if err != nil {
		t.Fatalf("ListMessages() error = %v", err)
	}
	if len(messages) != 2 {
		t.Fatalf("ListMessages() len = %d, want 2", len(messages))
	}
	if messages[1].Content != "partial" {
		t.Fatalf("assistant content after cancellation = %q, want partial", messages[1].Content)
	}
	if messages[1].Status == "streaming" {
		t.Fatalf("assistant status after cancellation = %q, want non-streaming terminal status", messages[1].Status)
	}
}

func TestServiceDoesNotPersistDeltaBlockedByClientCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	conversations := newTestConversationService(t)
	created, err := conversations.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	agent := newTwoStepAgent(
		AgentEvent{Kind: "delta", Text: "sent"},
		AgentEvent{Kind: "delta", Text: " unsent"},
	)
	svc := NewService(conversations, agent)

	events, err := svc.Stream(ctx, StreamChatRequest{
		ConversationID: created.ID,
		Message:        "Cancel while second delta is blocked",
	})
	if err != nil {
		t.Fatalf("Stream() error = %v", err)
	}
	first := <-events
	if first.Type != "message_created" {
		t.Fatalf("first event type = %q, want message_created", first.Type)
	}
	firstDelta := <-events
	if firstDelta.Type != "delta" || firstDelta.Text != "sent" {
		t.Fatalf("first delta = %+v, want sent delta", firstDelta)
	}

	agent.releaseSecond()
	waitForSignal(t, agent.secondDelivered, "second agent event to be received by service")
	cancel()
	waitForClosedEvents(t, events)

	messages, err := conversations.ListMessages(context.Background(), created.ID)
	if err != nil {
		t.Fatalf("ListMessages() error = %v", err)
	}
	if len(messages) != 2 {
		t.Fatalf("ListMessages() len = %d, want 2", len(messages))
	}
	if messages[1].Content != "sent" {
		t.Fatalf("assistant content after blocked cancellation = %q, want only successfully sent delta", messages[1].Content)
	}
	if strings.Contains(messages[1].Content, "unsent") {
		t.Fatalf("assistant content after blocked cancellation = %q, must not include unsent delta", messages[1].Content)
	}
}

func TestServiceReadsAgentErrorsWithoutWaitingForEventsToClose(t *testing.T) {
	ctx := context.Background()
	conversations := newTestConversationService(t)
	created, err := conversations.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	svc := NewService(conversations, nonClosingErrorAgent{err: errors.New("rate limited")})

	events, err := svc.Stream(ctx, StreamChatRequest{
		ConversationID: created.ID,
		Message:        "Trigger immediate error",
	})
	if err != nil {
		t.Fatalf("Stream() setup error = %v", err)
	}

	collected := collectEventsWithin(t, events, 500*time.Millisecond)
	assertEventTypes(t, collected, []string{"message_created", "error"})
	if collected[1].Text != "rate limited" {
		t.Fatalf("error event text = %q, want rate limited", collected[1].Text)
	}
}

func TestServiceWaitsForFinalAgentErrorAfterEventsClose(t *testing.T) {
	ctx := context.Background()
	conversations := newTestConversationService(t)
	created, err := conversations.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	agent := newDelayedFinalErrorAgent(errors.New("final stream error"))
	svc := NewService(conversations, agent)

	events, err := svc.Stream(ctx, StreamChatRequest{
		ConversationID: created.ID,
		Message:        "Trigger delayed final error",
	})
	if err != nil {
		t.Fatalf("Stream() setup error = %v", err)
	}

	first := <-events
	if first.Type != "message_created" {
		t.Fatalf("first event type = %q, want message_created", first.Type)
	}
	waitForSignal(t, agent.eventsClosed, "agent events to close")
	assertNoEventBeforeFinalError(t, events)
	agent.releaseError()

	collected := append([]StreamEvent{first}, collectEventsWithin(t, events, 500*time.Millisecond)...)
	assertEventTypes(t, collected, []string{"message_created", "error"})
	if collected[1].Text != "final stream error" {
		t.Fatalf("error event text = %q, want final stream error", collected[1].Text)
	}

	messages, err := conversations.ListMessages(ctx, created.ID)
	if err != nil {
		t.Fatalf("ListMessages() error = %v", err)
	}
	if len(messages) != 2 {
		t.Fatalf("ListMessages() len = %d, want 2", len(messages))
	}
	if messages[1].Status != "error" {
		t.Fatalf("assistant status = %q, want error", messages[1].Status)
	}
}

func TestServiceRegeneratesFromMessageWithEmptyPrompt(t *testing.T) {
	ctx := context.Background()
	conversations := newTestConversationService(t)
	created, err := conversations.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	userMessage, err := conversations.CreateMessage(ctx, conversation.CreateMessageInput{
		ConversationID: created.ID,
		Role:           "user",
		Content:        "Original question",
		Status:         "idle",
	})
	if err != nil {
		t.Fatalf("CreateMessage() user error = %v", err)
	}
	oldAssistant, err := conversations.CreateMessage(ctx, conversation.CreateMessageInput{
		ConversationID: created.ID,
		Role:           "assistant",
		Content:        "Old answer",
		Status:         "done",
	})
	if err != nil {
		t.Fatalf("CreateMessage() assistant error = %v", err)
	}
	agent := &capturingAgent{events: []AgentEvent{{Kind: "delta", Text: "New answer"}}}
	svc := NewService(conversations, agent)

	events, err := svc.Stream(ctx, StreamChatRequest{
		ConversationID:          created.ID,
		RegenerateFromMessageID: oldAssistant.ID,
	})
	if err != nil {
		t.Fatalf("Stream() error = %v", err)
	}
	collected := collectEvents(t, events)

	assertEventTypes(t, collected, []string{"message_created", "delta", "title", "done"})
	if len(agent.messages) != 1 || agent.messages[0].Role != "user" || agent.messages[0].Content != userMessage.Content {
		t.Fatalf("agent messages = %+v, want history ending at original user message %q", agent.messages, userMessage.Content)
	}
	messages, err := conversations.ListMessages(ctx, created.ID)
	if err != nil {
		t.Fatalf("ListMessages() error = %v", err)
	}
	if len(messages) != 3 {
		t.Fatalf("ListMessages() len = %d, want existing user, old assistant, regenerated assistant", len(messages))
	}
	if messages[2].Role != "assistant" || messages[2].Content != "New answer" {
		t.Fatalf("regenerated assistant message = %+v, want new assistant answer", messages[2])
	}
}

func TestServiceUsesParentMessageWithoutCreatingDuplicateUser(t *testing.T) {
	ctx := context.Background()
	conversations := newTestConversationService(t)
	created, err := conversations.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	parent, err := conversations.CreateMessage(ctx, conversation.CreateMessageInput{
		ConversationID: created.ID,
		Role:           "user",
		Content:        "Already persisted prompt",
		Status:         "idle",
	})
	if err != nil {
		t.Fatalf("CreateMessage() parent error = %v", err)
	}
	svc := NewService(conversations, fakeAgent{events: []AgentEvent{{Kind: "delta", Text: "Answer"}}})

	events, err := svc.Stream(ctx, StreamChatRequest{
		ConversationID:  created.ID,
		Message:         parent.Content,
		ParentMessageID: parent.ID,
	})
	if err != nil {
		t.Fatalf("Stream() error = %v", err)
	}
	_ = collectEvents(t, events)

	messages, err := conversations.ListMessages(ctx, created.ID)
	if err != nil {
		t.Fatalf("ListMessages() error = %v", err)
	}
	if len(messages) != 2 {
		t.Fatalf("ListMessages() len = %d, want parent user plus assistant without duplicate user; messages = %+v", len(messages), messages)
	}
	if messages[0].ID != parent.ID || messages[1].Role != "assistant" {
		t.Fatalf("messages = %+v, want original parent followed by assistant", messages)
	}
}

func TestServiceSendsConversationHistoryToAgentForNewPrompt(t *testing.T) {
	ctx := context.Background()
	conversations := newTestConversationService(t)
	created, err := conversations.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	if _, err := conversations.CreateMessage(ctx, conversation.CreateMessageInput{
		ConversationID: created.ID,
		Role:           "user",
		Content:        "First question",
		Status:         "idle",
	}); err != nil {
		t.Fatalf("CreateMessage() first user error = %v", err)
	}
	if _, err := conversations.CreateMessage(ctx, conversation.CreateMessageInput{
		ConversationID: created.ID,
		Role:           "assistant",
		Content:        "First answer",
		Status:         "done",
	}); err != nil {
		t.Fatalf("CreateMessage() first assistant error = %v", err)
	}
	agent := &capturingAgent{events: []AgentEvent{{Kind: "delta", Text: "Second answer"}}}
	svc := NewService(conversations, agent)

	events, err := svc.Stream(ctx, StreamChatRequest{
		ConversationID: created.ID,
		Message:        "Second question",
	})
	if err != nil {
		t.Fatalf("Stream() error = %v", err)
	}
	_ = collectEvents(t, events)

	want := []AgentMessage{
		{Role: "user", Content: "First question"},
		{Role: "assistant", Content: "First answer"},
		{Role: "user", Content: "Second question"},
	}
	if !agentMessagesEqual(agent.messages, want) {
		t.Fatalf("agent messages = %+v, want %+v", agent.messages, want)
	}
}

func TestServiceSendsHistoryThroughEditedParentMessageToAgent(t *testing.T) {
	ctx := context.Background()
	conversations := newTestConversationService(t)
	created, err := conversations.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	if _, err := conversations.CreateMessage(ctx, conversation.CreateMessageInput{
		ConversationID: created.ID,
		Role:           "user",
		Content:        "Original setup",
		Status:         "idle",
	}); err != nil {
		t.Fatalf("CreateMessage() setup user error = %v", err)
	}
	if _, err := conversations.CreateMessage(ctx, conversation.CreateMessageInput{
		ConversationID: created.ID,
		Role:           "assistant",
		Content:        "Original answer",
		Status:         "done",
	}); err != nil {
		t.Fatalf("CreateMessage() setup assistant error = %v", err)
	}
	parent, err := conversations.CreateMessage(ctx, conversation.CreateMessageInput{
		ConversationID: created.ID,
		Role:           "user",
		Content:        "Edited follow-up",
		Status:         "idle",
	})
	if err != nil {
		t.Fatalf("CreateMessage() parent user error = %v", err)
	}
	agent := &capturingAgent{events: []AgentEvent{{Kind: "delta", Text: "Edited answer"}}}
	svc := NewService(conversations, agent)

	events, err := svc.Stream(ctx, StreamChatRequest{
		ConversationID:  created.ID,
		ParentMessageID: parent.ID,
		Message:         parent.Content,
	})
	if err != nil {
		t.Fatalf("Stream() error = %v", err)
	}
	_ = collectEvents(t, events)

	want := []AgentMessage{
		{Role: "user", Content: "Original setup"},
		{Role: "assistant", Content: "Original answer"},
		{Role: "user", Content: "Edited follow-up"},
	}
	if !agentMessagesEqual(agent.messages, want) {
		t.Fatalf("agent messages = %+v, want %+v", agent.messages, want)
	}
}

func TestServiceValidatesStreamRequest(t *testing.T) {
	svc := NewService(newTestConversationService(t), fakeAgent{})

	cases := []StreamChatRequest{
		{ConversationID: "", Message: "hello"},
		{ConversationID: "conversation-id", Message: "   "},
	}
	for _, tc := range cases {
		if _, err := svc.Stream(context.Background(), tc); err == nil {
			t.Fatalf("Stream(%+v) error = nil, want validation error", tc)
		}
	}
}

type fakeAgent struct {
	events []AgentEvent
	err    error
}

func (f fakeAgent) Stream(ctx context.Context, messages []AgentMessage) (<-chan AgentEvent, <-chan error) {
	events := make(chan AgentEvent)
	errs := make(chan error, 1)
	go func() {
		defer close(events)
		defer close(errs)
		for _, event := range f.events {
			select {
			case <-ctx.Done():
				errs <- ctx.Err()
				return
			case events <- event:
			}
		}
		if f.err != nil {
			errs <- f.err
		}
	}()
	return events, errs
}

type nonClosingErrorAgent struct {
	err error
}

func (a nonClosingErrorAgent) Stream(ctx context.Context, messages []AgentMessage) (<-chan AgentEvent, <-chan error) {
	events := make(chan AgentEvent)
	errs := make(chan error, 1)
	errs <- a.err
	return events, errs
}

type delayedFinalErrorAgent struct {
	err          error
	eventsClosed chan struct{}
	release      chan struct{}
}

func newDelayedFinalErrorAgent(err error) *delayedFinalErrorAgent {
	return &delayedFinalErrorAgent{
		err:          err,
		eventsClosed: make(chan struct{}),
		release:      make(chan struct{}),
	}
}

func (a *delayedFinalErrorAgent) Stream(ctx context.Context, messages []AgentMessage) (<-chan AgentEvent, <-chan error) {
	events := make(chan AgentEvent)
	errs := make(chan error, 1)
	go func() {
		close(events)
		close(a.eventsClosed)
		select {
		case <-ctx.Done():
			errs <- ctx.Err()
		case <-a.release:
			errs <- a.err
		}
		close(errs)
	}()
	return events, errs
}

func (a *delayedFinalErrorAgent) releaseError() {
	close(a.release)
}

type twoStepAgent struct {
	first           AgentEvent
	second          AgentEvent
	release         chan struct{}
	secondDelivered chan struct{}
}

func newTwoStepAgent(first AgentEvent, second AgentEvent) *twoStepAgent {
	return &twoStepAgent{
		first:           first,
		second:          second,
		release:         make(chan struct{}),
		secondDelivered: make(chan struct{}),
	}
}

func (a *twoStepAgent) Stream(ctx context.Context, messages []AgentMessage) (<-chan AgentEvent, <-chan error) {
	events := make(chan AgentEvent)
	errs := make(chan error)
	go func() {
		defer close(events)
		defer close(errs)
		select {
		case <-ctx.Done():
			errs <- ctx.Err()
			return
		case events <- a.first:
		}
		select {
		case <-ctx.Done():
			errs <- ctx.Err()
			return
		case <-a.release:
		}
		events <- a.second
		close(a.secondDelivered)
		<-ctx.Done()
		errs <- ctx.Err()
	}()
	return events, errs
}

func (a *twoStepAgent) releaseSecond() {
	close(a.release)
}

type capturingAgent struct {
	events   []AgentEvent
	messages []AgentMessage
}

func (a *capturingAgent) Stream(ctx context.Context, messages []AgentMessage) (<-chan AgentEvent, <-chan error) {
	a.messages = append([]AgentMessage(nil), messages...)
	return fakeAgent{events: a.events}.Stream(ctx, messages)
}

func collectEvents(t *testing.T, events <-chan StreamEvent) []StreamEvent {
	t.Helper()

	var collected []StreamEvent
	for event := range events {
		collected = append(collected, event)
	}
	return collected
}

func collectEventsWithin(t *testing.T, events <-chan StreamEvent, timeout time.Duration) []StreamEvent {
	t.Helper()

	timer := time.NewTimer(timeout)
	defer timer.Stop()
	var collected []StreamEvent
	for {
		select {
		case event, ok := <-events:
			if !ok {
				return collected
			}
			collected = append(collected, event)
		case <-timer.C:
			t.Fatalf("timed out collecting stream events; collected = %+v", collected)
			return nil
		}
	}
}

func waitForClosedEvents(t *testing.T, events <-chan StreamEvent) {
	t.Helper()

	timer := time.NewTimer(500 * time.Millisecond)
	defer timer.Stop()
	for {
		select {
		case _, ok := <-events:
			if !ok {
				return
			}
		case <-timer.C:
			t.Fatal("timed out waiting for stream events to close after cancellation")
		}
	}
}

func waitForSignal(t *testing.T, signal <-chan struct{}, label string) {
	t.Helper()

	timer := time.NewTimer(500 * time.Millisecond)
	defer timer.Stop()
	select {
	case <-signal:
	case <-timer.C:
		t.Fatalf("timed out waiting for %s", label)
	}
}

func assertNoEventBeforeFinalError(t *testing.T, events <-chan StreamEvent) {
	t.Helper()

	timer := time.NewTimer(25 * time.Millisecond)
	defer timer.Stop()
	select {
	case event, ok := <-events:
		if !ok {
			t.Fatal("stream closed before final agent error")
		}
		t.Fatalf("received event before final agent error: %+v", event)
	case <-timer.C:
	}
}

func assertEventTypes(t *testing.T, events []StreamEvent, want []string) {
	t.Helper()

	if len(events) != len(want) {
		t.Fatalf("events len = %d, want %d; events = %+v", len(events), len(want), events)
	}
	for i, event := range events {
		if event.Type != want[i] {
			t.Fatalf("events[%d].Type = %q, want %q; events = %+v", i, event.Type, want[i], events)
		}
	}
}

func agentMessagesEqual(got []AgentMessage, want []AgentMessage) bool {
	if len(got) != len(want) {
		return false
	}
	for i := range want {
		if got[i] != want[i] {
			return false
		}
	}
	return true
}

func newTestConversationService(t *testing.T) *conversation.Service {
	t.Helper()

	sequence := atomic.AddUint64(&testDBSequence, 1)
	dbName := strings.NewReplacer("/", "_", " ", "_").Replace(t.Name())
	db, err := gorm.Open(sqlite.Open(fmt.Sprintf("file:%s_%d?mode=memory&cache=shared&_foreign_keys=on", dbName, sequence)), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Silent),
	})
	if err != nil {
		t.Fatalf("open test DB error = %v", err)
	}
	if err := store.AutoMigrate(t.Context(), db); err != nil {
		t.Fatalf("AutoMigrate() error = %v", err)
	}
	return conversation.NewService(db)
}

func mustFindConversation(t *testing.T, ctx context.Context, svc *conversation.Service, id string) conversation.ChatConversation {
	t.Helper()

	conversations, err := svc.ListConversations(ctx)
	if err != nil {
		t.Fatalf("ListConversations() error = %v", err)
	}
	for _, item := range conversations {
		if item.ID == id {
			return item
		}
	}
	t.Fatalf("conversation %q not found", id)
	return conversation.ChatConversation{}
}
