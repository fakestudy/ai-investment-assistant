package conversation

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"ai-investment-assistant/backend/internal/store"
	"gorm.io/datatypes"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

var testDBSequence uint64

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

func TestServiceUpdatesConversationTimestampWhenCreatingAndEditingMessage(t *testing.T) {
	ctx := context.Background()
	svc, db := newTestServiceWithDB(t)

	conversation, err := svc.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	oldTimestamp := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	if err := db.WithContext(ctx).Model(&store.Conversation{}).
		Where("id = ?", conversation.ID).
		Update("updated_at", oldTimestamp).Error; err != nil {
		t.Fatalf("set old conversation timestamp error = %v", err)
	}

	message, err := svc.CreateMessage(ctx, CreateMessageInput{
		ConversationID: conversation.ID,
		Role:           "user",
		Content:        "Question",
		Status:         "complete",
	})
	if err != nil {
		t.Fatalf("CreateMessage() error = %v", err)
	}
	afterCreate := mustGetConversation(t, ctx, svc, conversation.ID)
	if !afterCreate.UpdatedAt.After(oldTimestamp) {
		t.Fatalf("conversation UpdatedAt after CreateMessage = %s, want after %s", afterCreate.UpdatedAt, oldTimestamp)
	}

	if err := db.WithContext(ctx).Model(&store.Conversation{}).
		Where("id = ?", conversation.ID).
		Update("updated_at", oldTimestamp).Error; err != nil {
		t.Fatalf("reset old conversation timestamp error = %v", err)
	}
	if _, err := svc.EditMessage(ctx, message.ID, "Revised question"); err != nil {
		t.Fatalf("EditMessage() error = %v", err)
	}
	afterEdit := mustGetConversation(t, ctx, svc, conversation.ID)
	if !afterEdit.UpdatedAt.After(oldTimestamp) {
		t.Fatalf("conversation UpdatedAt after EditMessage = %s, want after %s", afterEdit.UpdatedAt, oldTimestamp)
	}
}

func TestServiceDeletesToolInvocationsWhenDeletingConversation(t *testing.T) {
	ctx := context.Background()
	svc, db := newTestServiceWithDB(t)

	conversation, err := svc.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	message, err := svc.CreateMessage(ctx, CreateMessageInput{
		ConversationID: conversation.ID,
		Role:           "assistant",
		Content:        "Answer",
		Status:         "complete",
	})
	if err != nil {
		t.Fatalf("CreateMessage() error = %v", err)
	}
	if err := db.WithContext(ctx).Create(&store.ToolInvocation{
		ID:        "tool-delete-conversation",
		MessageID: message.ID,
		ToolName:  "web_search",
		Args:      datatypes.JSON([]byte(`{"query":"market"}`)),
		Result:    datatypes.JSON([]byte(`{"items":[]}`)),
		Status:    "complete",
	}).Error; err != nil {
		t.Fatalf("Create tool invocation error = %v", err)
	}

	if err := svc.DeleteConversation(ctx, conversation.ID); err != nil {
		t.Fatalf("DeleteConversation() error = %v", err)
	}

	var count int64
	if err := db.WithContext(ctx).Model(&store.ToolInvocation{}).Count(&count).Error; err != nil {
		t.Fatalf("count tool invocations error = %v", err)
	}
	if count != 0 {
		t.Fatalf("tool invocation count after DeleteConversation = %d, want 0", count)
	}
}

func TestServiceTruncatesFollowingMessagesAndToolsWithSameCreatedAt(t *testing.T) {
	ctx := context.Background()
	svc, db := newTestServiceWithDB(t)

	conversation, err := svc.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	createdAt := time.Date(2026, 5, 30, 12, 0, 0, 0, time.UTC)
	messages := []store.Message{
		{ID: "m01", ConversationID: conversation.ID, Role: "user", Content: "First", Status: "complete", CreatedAt: createdAt},
		{ID: "m02", ConversationID: conversation.ID, Role: "assistant", Content: "Second", Status: "complete", CreatedAt: createdAt},
		{ID: "m03", ConversationID: conversation.ID, Role: "user", Content: "Third", Status: "complete", CreatedAt: createdAt},
	}
	if err := db.WithContext(ctx).Create(&messages).Error; err != nil {
		t.Fatalf("Create messages error = %v", err)
	}
	if err := db.WithContext(ctx).Create(&store.ToolInvocation{
		ID:        "tool-truncated-message",
		MessageID: "m03",
		ToolName:  "fetch_url",
		Args:      datatypes.JSON([]byte(`{"url":"https://example.com"}`)),
		Status:    "complete",
	}).Error; err != nil {
		t.Fatalf("Create tool invocation error = %v", err)
	}

	if _, err := svc.EditMessage(ctx, "m02", "Second revised"); err != nil {
		t.Fatalf("EditMessage() error = %v", err)
	}

	remaining, err := svc.ListMessages(ctx, conversation.ID)
	if err != nil {
		t.Fatalf("ListMessages() error = %v", err)
	}
	if len(remaining) != 2 {
		t.Fatalf("ListMessages() len = %d, want 2", len(remaining))
	}
	if remaining[0].ID != "m01" || remaining[1].ID != "m02" {
		t.Fatalf("remaining message order = [%s %s], want [m01 m02]", remaining[0].ID, remaining[1].ID)
	}

	var count int64
	if err := db.WithContext(ctx).Model(&store.ToolInvocation{}).Where("message_id = ?", "m03").Count(&count).Error; err != nil {
		t.Fatalf("count tool invocations error = %v", err)
	}
	if count != 0 {
		t.Fatalf("truncated message tool invocation count = %d, want 0", count)
	}
}

func TestServicePreventsOrphanMessagesAndToolInvocations(t *testing.T) {
	ctx := context.Background()
	svc, db := newTestServiceWithDB(t)

	if _, err := svc.CreateMessage(ctx, CreateMessageInput{
		ConversationID: "missing-conversation",
		Role:           "user",
		Content:        "Orphan message",
		Status:         "complete",
	}); err == nil {
		t.Fatal("CreateMessage() error = nil, want error for missing conversation")
	}

	err := db.WithContext(ctx).Create(&store.ToolInvocation{
		ID:        "orphan-tool",
		MessageID: "missing-message",
		ToolName:  "web_search",
		Status:    "complete",
	}).Error
	if err == nil {
		t.Fatal("Create orphan tool invocation error = nil, want foreign key error")
	}
}

func TestSQLiteTestDBIsIsolatedForRepeatedSetupInSameTest(t *testing.T) {
	ctx := context.Background()
	firstService, _ := newTestServiceWithDB(t)
	if _, err := firstService.CreateConversation(ctx); err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}

	secondService, _ := newTestServiceWithDB(t)
	conversations, err := secondService.ListConversations(ctx)
	if err != nil {
		t.Fatalf("ListConversations() error = %v", err)
	}
	if len(conversations) != 0 {
		t.Fatalf("second test DB conversation count = %d, want 0", len(conversations))
	}
}

func TestServiceListMessagesIncludesToolInvocations(t *testing.T) {
	ctx := context.Background()
	svc, db := newTestServiceWithDB(t)

	conversation, err := svc.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	message, err := svc.CreateMessage(ctx, CreateMessageInput{
		ConversationID: conversation.ID,
		Role:           "assistant",
		Content:        "Answer with tool",
		Status:         "complete",
	})
	if err != nil {
		t.Fatalf("CreateMessage() error = %v", err)
	}
	if err := db.WithContext(ctx).Create(&store.ToolInvocation{
		ID:        "tool-list-messages",
		MessageID: message.ID,
		ToolName:  "web_search",
		Args:      datatypes.JSON([]byte(`{"query":"AI stocks"}`)),
		Result:    datatypes.JSON([]byte(`{"items":[{"title":"Result"}]}`)),
		Error:     "",
		LatencyMS: 123,
		Status:    "complete",
	}).Error; err != nil {
		t.Fatalf("Create tool invocation error = %v", err)
	}

	messages, err := svc.ListMessages(ctx, conversation.ID)
	if err != nil {
		t.Fatalf("ListMessages() error = %v", err)
	}
	if len(messages) != 1 {
		t.Fatalf("ListMessages() len = %d, want 1", len(messages))
	}
	if len(messages[0].ToolInvocations) != 1 {
		t.Fatalf("ToolInvocations len = %d, want 1", len(messages[0].ToolInvocations))
	}
	invocation := messages[0].ToolInvocations[0]
	if invocation.ID != "tool-list-messages" {
		t.Fatalf("ToolInvocation.ID = %q, want %q", invocation.ID, "tool-list-messages")
	}
	if invocation.MessageID != message.ID {
		t.Fatalf("ToolInvocation.MessageID = %q, want %q", invocation.MessageID, message.ID)
	}
	if invocation.ToolName != "web_search" {
		t.Fatalf("ToolInvocation.ToolName = %q, want %q", invocation.ToolName, "web_search")
	}
	if string(invocation.Args) != `{"query":"AI stocks"}` {
		t.Fatalf("ToolInvocation.Args = %s", invocation.Args)
	}
	if string(invocation.Result) != `{"items":[{"title":"Result"}]}` {
		t.Fatalf("ToolInvocation.Result = %s", invocation.Result)
	}
	if invocation.LatencyMS != 123 {
		t.Fatalf("ToolInvocation.LatencyMS = %d, want 123", invocation.LatencyMS)
	}
	if invocation.Status != "completed" {
		t.Fatalf("ToolInvocation.Status = %q, want %q", invocation.Status, "completed")
	}

	payload, err := json.Marshal(messages[0])
	if err != nil {
		t.Fatalf("json.Marshal(message) error = %v", err)
	}
	wantJSON := `"args":{"query":"AI stocks"}`
	if !strings.Contains(string(payload), wantJSON) {
		t.Fatalf("marshaled message = %s, want args as JSON object containing %s", payload, wantJSON)
	}
	wantJSON = `"result":{"items":[{"title":"Result"}]}`
	if !strings.Contains(string(payload), wantJSON) {
		t.Fatalf("marshaled message = %s, want result as JSON object containing %s", payload, wantJSON)
	}
}

func newTestService(t *testing.T) *Service {
	t.Helper()

	svc, _ := newTestServiceWithDB(t)
	return svc
}

func newTestServiceWithDB(t *testing.T) (*Service, *gorm.DB) {
	t.Helper()

	sequence := atomic.AddUint64(&testDBSequence, 1)
	dbName := strings.NewReplacer("/", "_", " ", "_").Replace(t.Name())
	db, err := openSQLiteTestDB(t.Context(), fmt.Sprintf("file:%s_%d?mode=memory&cache=shared&_foreign_keys=on", dbName, sequence))
	if err != nil {
		t.Fatalf("openSQLiteTestDB() error = %v", err)
	}

	return NewService(db), db
}

func openSQLiteTestDB(ctx context.Context, dsn string) (*gorm.DB, error) {
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Silent),
	})
	if err != nil {
		return nil, err
	}
	if err := store.AutoMigrate(ctx, db); err != nil {
		return nil, err
	}
	return db, nil
}

func mustGetConversation(t *testing.T, ctx context.Context, svc *Service, id string) ChatConversation {
	t.Helper()

	conversations, err := svc.ListConversations(ctx)
	if err != nil {
		t.Fatalf("ListConversations() error = %v", err)
	}
	for _, conversation := range conversations {
		if conversation.ID == id {
			return conversation
		}
	}
	t.Fatalf("conversation %q not found", id)
	return ChatConversation{}
}
