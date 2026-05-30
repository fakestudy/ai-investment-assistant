package conversation

import (
	"context"
	"testing"

	"ai-investment-assistant/backend/internal/store"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func TestServiceCreatesAndRenamesConversation(t *testing.T) {
	ctx := context.Background()
	svc := newTestService(t)

	created, err := svc.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	if created.ID == "" {
		t.Fatal("CreateConversation() returned empty ID")
	}
	if created.Title != "New chat" {
		t.Fatalf("CreateConversation() title = %q, want %q", created.Title, "New chat")
	}
	if created.CreatedAt.IsZero() || created.UpdatedAt.IsZero() {
		t.Fatalf("CreateConversation() timestamps must be set: %+v", created)
	}

	renamed, err := svc.RenameConversation(ctx, created.ID, "Investment thesis")
	if err != nil {
		t.Fatalf("RenameConversation() error = %v", err)
	}
	if renamed.Title != "Investment thesis" {
		t.Fatalf("RenameConversation() title = %q, want %q", renamed.Title, "Investment thesis")
	}
	if renamed.ID != created.ID {
		t.Fatalf("RenameConversation() ID = %q, want %q", renamed.ID, created.ID)
	}

	conversations, err := svc.ListConversations(ctx)
	if err != nil {
		t.Fatalf("ListConversations() error = %v", err)
	}
	if len(conversations) != 1 {
		t.Fatalf("ListConversations() len = %d, want 1", len(conversations))
	}
	if conversations[0].Title != "Investment thesis" {
		t.Fatalf("ListConversations()[0].Title = %q", conversations[0].Title)
	}
}

func TestServiceDeletesConversation(t *testing.T) {
	ctx := context.Background()
	svc := newTestService(t)

	first, err := svc.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() first error = %v", err)
	}
	second, err := svc.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() second error = %v", err)
	}

	if err := svc.DeleteConversation(ctx, first.ID); err != nil {
		t.Fatalf("DeleteConversation() error = %v", err)
	}

	conversations, err := svc.ListConversations(ctx)
	if err != nil {
		t.Fatalf("ListConversations() error = %v", err)
	}
	if len(conversations) != 1 {
		t.Fatalf("ListConversations() len = %d, want 1", len(conversations))
	}
	if conversations[0].ID != second.ID {
		t.Fatalf("remaining conversation ID = %q, want %q", conversations[0].ID, second.ID)
	}
}

func TestServiceEditsMessageAndDeletesFollowingMessages(t *testing.T) {
	ctx := context.Background()
	svc := newTestService(t)

	conversation, err := svc.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	first, err := svc.CreateMessage(ctx, CreateMessageInput{
		ConversationID: conversation.ID,
		Role:           "user",
		Content:        "Initial question",
		Status:         "complete",
	})
	if err != nil {
		t.Fatalf("CreateMessage() first error = %v", err)
	}
	if _, err := svc.CreateMessage(ctx, CreateMessageInput{
		ConversationID: conversation.ID,
		Role:           "assistant",
		Content:        "Initial answer",
		Status:         "complete",
	}); err != nil {
		t.Fatalf("CreateMessage() second error = %v", err)
	}

	edited, err := svc.EditMessage(ctx, first.ID, "Revised question")
	if err != nil {
		t.Fatalf("EditMessage() error = %v", err)
	}
	if edited.Content != "Revised question" {
		t.Fatalf("EditMessage() content = %q, want %q", edited.Content, "Revised question")
	}

	messages, err := svc.ListMessages(ctx, conversation.ID)
	if err != nil {
		t.Fatalf("ListMessages() error = %v", err)
	}
	if len(messages) != 1 {
		t.Fatalf("ListMessages() len = %d, want 1", len(messages))
	}
	if messages[0].ID != first.ID {
		t.Fatalf("remaining message ID = %q, want %q", messages[0].ID, first.ID)
	}
	if messages[0].Content != "Revised question" {
		t.Fatalf("remaining message content = %q", messages[0].Content)
	}
}

func newTestService(t *testing.T) *Service {
	t.Helper()

	db, err := openSQLiteTestDB(t.Context(), ":memory:")
	if err != nil {
		t.Fatalf("openSQLiteTestDB() error = %v", err)
	}

	return NewService(db)
}

func openSQLiteTestDB(ctx context.Context, dsn string) (*gorm.DB, error) {
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{})
	if err != nil {
		return nil, err
	}
	if err := store.AutoMigrate(ctx, db); err != nil {
		return nil, err
	}
	return db, nil
}
