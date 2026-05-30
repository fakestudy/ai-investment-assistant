package chat

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync/atomic"
	"testing"

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
	if messages[0].Role != "user" || messages[0].Content != "Explain AI moats" || messages[0].Status != "complete" {
		t.Fatalf("user message = %+v, want complete persisted prompt", messages[0])
	}
	if messages[1].ID != assistantID || messages[1].Content != "Hello investor" || messages[1].Reasoning != "checking context" || messages[1].Status != "complete" {
		t.Fatalf("assistant message = %+v, want completed streamed output", messages[1])
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

func collectEvents(t *testing.T, events <-chan StreamEvent) []StreamEvent {
	t.Helper()

	var collected []StreamEvent
	for event := range events {
		collected = append(collected, event)
	}
	return collected
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
