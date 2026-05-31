package conversation

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"ai-investment-assistant/backend/internal/store"
	"github.com/google/uuid"
	"gorm.io/datatypes"
	"gorm.io/gorm"
)

const defaultConversationTitle = "New chat"

var ErrNotFound = gorm.ErrRecordNotFound

type Service struct {
	db *gorm.DB
}

type ChatConversation struct {
	ID        string    `json:"id"`
	Title     string    `json:"title"`
	CreatedAt time.Time `json:"createdAt"`
	UpdatedAt time.Time `json:"updatedAt"`
}

type ChatMessage struct {
	ID              string           `json:"id"`
	ConversationID  string           `json:"conversationId"`
	Role            string           `json:"role"`
	Content         string           `json:"content"`
	Reasoning       string           `json:"reasoning,omitempty"`
	Status          string           `json:"status"`
	CreatedAt       time.Time        `json:"createdAt"`
	ToolInvocations []ToolInvocation `json:"toolInvocations,omitempty"`
	TimelineParts   []MessagePart    `json:"timelineParts,omitempty"`
}

type ToolInvocation struct {
	ID        string          `json:"id"`
	MessageID string          `json:"messageId"`
	ToolName  string          `json:"toolName"`
	Args      json.RawMessage `json:"args,omitempty"`
	Result    json.RawMessage `json:"result,omitempty"`
	Error     string          `json:"error,omitempty"`
	LatencyMS int64           `json:"latencyMs"`
	Status    string          `json:"status"`
	CreatedAt time.Time       `json:"createdAt"`
}

type MessagePart struct {
	ID         string          `json:"id"`
	MessageID  string          `json:"messageId"`
	Type       string          `json:"type"`
	OrderIndex int             `json:"orderIndex"`
	Text       string          `json:"text,omitempty"`
	Invocation *ToolInvocation `json:"invocation,omitempty"`
	CreatedAt  time.Time       `json:"createdAt"`
}

type CreateMessageInput struct {
	ConversationID string
	Role           string
	Content        string
	Reasoning      string
	Status         string
}

type UpdateMessageInput struct {
	Content   string
	Reasoning string
	Status    string
}

type CreateToolInvocationInput struct {
	ID        string
	MessageID string
	ToolName  string
	Args      json.RawMessage
	Result    json.RawMessage
	Error     string
	LatencyMS int64
	Status    string
}

type UpdateToolInvocationInput struct {
	Args      json.RawMessage
	Result    json.RawMessage
	Error     string
	LatencyMS int64
	Status    string
}

type CreateMessagePartInput struct {
	MessageID        string
	Type             string
	OrderIndex       int
	Text             string
	ToolInvocationID string
}

type UpdateMessagePartInput struct {
	Text string
}

func NewService(db *gorm.DB) *Service {
	return &Service{db: db}
}

func (s *Service) ListConversations(ctx context.Context) ([]ChatConversation, error) {
	var rows []store.Conversation
	if err := s.db.WithContext(ctx).Order("updated_at desc, id asc").Find(&rows).Error; err != nil {
		return nil, err
	}

	conversations := make([]ChatConversation, 0, len(rows))
	for _, row := range rows {
		conversations = append(conversations, conversationDTO(row))
	}
	return conversations, nil
}

func (s *Service) CreateConversation(ctx context.Context) (ChatConversation, error) {
	row := store.Conversation{
		ID:    uuid.NewString(),
		Title: defaultConversationTitle,
	}
	if err := s.db.WithContext(ctx).Create(&row).Error; err != nil {
		return ChatConversation{}, err
	}
	return conversationDTO(row), nil
}

func (s *Service) RenameConversation(ctx context.Context, id string, title string) (ChatConversation, error) {
	var row store.Conversation
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := tx.First(&row, "id = ?", id).Error; err != nil {
			return err
		}
		row.Title = strings.TrimSpace(title)
		return tx.Save(&row).Error
	})
	if err != nil {
		return ChatConversation{}, err
	}
	return conversationDTO(row), nil
}

func (s *Service) DeleteConversation(ctx context.Context, id string) error {
	return s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		messageIDs := tx.Model(&store.Message{}).Select("id").Where("conversation_id = ?", id)
		if err := tx.Where("message_id IN (?)", messageIDs).Delete(&store.MessagePart{}).Error; err != nil {
			return err
		}
		if err := tx.Where("message_id IN (?)", messageIDs).Delete(&store.ToolInvocation{}).Error; err != nil {
			return err
		}
		if err := tx.Where("conversation_id = ?", id).Delete(&store.Message{}).Error; err != nil {
			return err
		}
		result := tx.Delete(&store.Conversation{}, "id = ?", id)
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			return gorm.ErrRecordNotFound
		}
		return nil
	})
}

func (s *Service) ListMessages(ctx context.Context, conversationID string) ([]ChatMessage, error) {
	var rows []store.Message
	if err := s.db.WithContext(ctx).
		Preload("ToolInvocations", func(db *gorm.DB) *gorm.DB {
			return db.Order("created_at asc, id asc")
		}).
		Preload("Parts", func(db *gorm.DB) *gorm.DB {
			return db.Order("order_index asc, id asc")
		}).
		Preload("Parts.ToolInvocation").
		Where("conversation_id = ?", conversationID).
		Order("created_at asc, id asc").
		Find(&rows).Error; err != nil {
		return nil, err
	}

	messages := make([]ChatMessage, 0, len(rows))
	for _, row := range rows {
		messages = append(messages, messageDTO(row))
	}
	return messages, nil
}

func (s *Service) CreateMessage(ctx context.Context, input CreateMessageInput) (ChatMessage, error) {
	row := store.Message{
		ID:             uuid.NewString(),
		ConversationID: input.ConversationID,
		Role:           input.Role,
		Content:        input.Content,
		Reasoning:      input.Reasoning,
		Status:         normalizeMessageStatus(input.Role, input.Status),
	}

	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		result := tx.Model(&store.Conversation{}).
			Where("id = ?", input.ConversationID).
			Update("updated_at", time.Now())
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			return gorm.ErrRecordNotFound
		}
		return tx.Create(&row).Error
	})
	if err != nil {
		return ChatMessage{}, err
	}
	return messageDTO(row), nil
}

func (s *Service) UpdateMessage(ctx context.Context, messageID string, input UpdateMessageInput) (ChatMessage, error) {
	var row store.Message
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := tx.First(&row, "id = ?", messageID).Error; err != nil {
			return err
		}
		row.Content = input.Content
		row.Reasoning = input.Reasoning
		if input.Status != "" {
			row.Status = normalizeMessageStatus(row.Role, input.Status)
		}
		if err := tx.Save(&row).Error; err != nil {
			return err
		}
		return tx.Model(&store.Conversation{}).
			Where("id = ?", row.ConversationID).
			Update("updated_at", time.Now()).Error
	})
	if err != nil {
		return ChatMessage{}, err
	}
	return messageDTO(row), nil
}

func (s *Service) CreateToolInvocation(ctx context.Context, input CreateToolInvocationInput) (ToolInvocation, error) {
	id := strings.TrimSpace(input.ID)
	if id == "" {
		id = uuid.NewString()
	}
	row := store.ToolInvocation{
		ID:        id,
		MessageID: input.MessageID,
		ToolName:  input.ToolName,
		Args:      datatypes.JSON(input.Args),
		Result:    datatypes.JSON(input.Result),
		Error:     input.Error,
		LatencyMS: input.LatencyMS,
		Status:    normalizeToolInvocationStatus(input.Status),
	}
	if err := s.db.WithContext(ctx).Create(&row).Error; err != nil {
		return ToolInvocation{}, err
	}
	return toolInvocationDTO(row), nil
}

func (s *Service) UpdateToolInvocation(ctx context.Context, invocationID string, input UpdateToolInvocationInput) (ToolInvocation, error) {
	var row store.ToolInvocation
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := tx.First(&row, "id = ?", invocationID).Error; err != nil {
			return err
		}
		row.Args = datatypes.JSON(input.Args)
		row.Result = datatypes.JSON(input.Result)
		row.Error = input.Error
		row.LatencyMS = input.LatencyMS
		if input.Status != "" {
			row.Status = normalizeToolInvocationStatus(input.Status)
		}
		return tx.Save(&row).Error
	})
	if err != nil {
		return ToolInvocation{}, err
	}
	return toolInvocationDTO(row), nil
}

func (s *Service) CreateMessagePart(ctx context.Context, input CreateMessagePartInput) (MessagePart, error) {
	row := store.MessagePart{
		ID:         uuid.NewString(),
		MessageID:  input.MessageID,
		Type:       input.Type,
		OrderIndex: input.OrderIndex,
		Text:       input.Text,
	}
	if strings.TrimSpace(input.ToolInvocationID) != "" {
		toolInvocationID := input.ToolInvocationID
		row.ToolInvocationID = &toolInvocationID
	}
	if err := s.db.WithContext(ctx).Create(&row).Error; err != nil {
		return MessagePart{}, err
	}
	return messagePartDTO(row), nil
}

func (s *Service) UpdateMessagePart(ctx context.Context, partID string, input UpdateMessagePartInput) (MessagePart, error) {
	var row store.MessagePart
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := tx.First(&row, "id = ?", partID).Error; err != nil {
			return err
		}
		row.Text = input.Text
		return tx.Save(&row).Error
	})
	if err != nil {
		return MessagePart{}, err
	}
	return messagePartDTO(row), nil
}

func (s *Service) EditMessage(ctx context.Context, messageID string, content string) (ChatMessage, error) {
	var row store.Message
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := tx.First(&row, "id = ?", messageID).Error; err != nil {
			return err
		}
		row.Content = content
		if err := tx.Save(&row).Error; err != nil {
			return err
		}
		followingMessages := tx.Model(&store.Message{}).
			Select("id").
			Where("conversation_id = ? AND (created_at > ? OR (created_at = ? AND id > ?))", row.ConversationID, row.CreatedAt, row.CreatedAt, row.ID)
		if err := tx.Where("message_id IN (?)", followingMessages).Delete(&store.MessagePart{}).Error; err != nil {
			return err
		}
		if err := tx.Where("message_id IN (?)", followingMessages).Delete(&store.ToolInvocation{}).Error; err != nil {
			return err
		}
		if err := tx.Where("conversation_id = ? AND (created_at > ? OR (created_at = ? AND id > ?))", row.ConversationID, row.CreatedAt, row.CreatedAt, row.ID).
			Delete(&store.Message{}).Error; err != nil {
			return err
		}
		return tx.Model(&store.Conversation{}).
			Where("id = ?", row.ConversationID).
			Update("updated_at", time.Now()).Error
	})
	if err != nil {
		return ChatMessage{}, err
	}
	return messageDTO(row), nil
}

func IsNotFound(err error) bool {
	return errors.Is(err, gorm.ErrRecordNotFound)
}

func normalizeMessageStatus(role string, status string) string {
	switch strings.TrimSpace(status) {
	case "", "idle":
		return "idle"
	case "streaming":
		return "streaming"
	case "done":
		return "done"
	case "error":
		return "error"
	case "complete":
		if role == "assistant" {
			return "done"
		}
		return "idle"
	case "cancelled":
		return "done"
	default:
		return status
	}
}

func normalizeToolInvocationStatus(status string) string {
	switch strings.TrimSpace(status) {
	case "", "completed", "complete":
		return "completed"
	case "running":
		return "running"
	case "error":
		return "error"
	default:
		return status
	}
}

func conversationDTO(row store.Conversation) ChatConversation {
	return ChatConversation{
		ID:        row.ID,
		Title:     row.Title,
		CreatedAt: row.CreatedAt,
		UpdatedAt: row.UpdatedAt,
	}
}

func messageDTO(row store.Message) ChatMessage {
	toolInvocations := make([]ToolInvocation, 0, len(row.ToolInvocations))
	for _, invocation := range row.ToolInvocations {
		toolInvocations = append(toolInvocations, toolInvocationDTO(invocation))
	}
	timelineParts := make([]MessagePart, 0, len(row.Parts))
	for _, part := range row.Parts {
		timelineParts = append(timelineParts, messagePartDTO(part))
	}

	return ChatMessage{
		ID:              row.ID,
		ConversationID:  row.ConversationID,
		Role:            row.Role,
		Content:         row.Content,
		Reasoning:       row.Reasoning,
		Status:          normalizeMessageStatus(row.Role, row.Status),
		CreatedAt:       row.CreatedAt,
		ToolInvocations: toolInvocations,
		TimelineParts:   timelineParts,
	}
}

func messagePartDTO(row store.MessagePart) MessagePart {
	var invocation *ToolInvocation
	if row.ToolInvocation != nil {
		dto := toolInvocationDTO(*row.ToolInvocation)
		invocation = &dto
	}

	return MessagePart{
		ID:         row.ID,
		MessageID:  row.MessageID,
		Type:       row.Type,
		OrderIndex: row.OrderIndex,
		Text:       row.Text,
		Invocation: invocation,
		CreatedAt:  row.CreatedAt,
	}
}

func toolInvocationDTO(row store.ToolInvocation) ToolInvocation {
	return ToolInvocation{
		ID:        row.ID,
		MessageID: row.MessageID,
		ToolName:  row.ToolName,
		Args:      json.RawMessage(row.Args),
		Result:    json.RawMessage(row.Result),
		Error:     row.Error,
		LatencyMS: row.LatencyMS,
		Status:    normalizeToolInvocationStatus(row.Status),
		CreatedAt: row.CreatedAt,
	}
}
