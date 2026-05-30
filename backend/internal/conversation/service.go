package conversation

import (
	"context"
	"errors"
	"strings"
	"time"

	"ai-investment-assistant/backend/internal/store"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

const defaultConversationTitle = "New chat"

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
}

type ToolInvocation struct {
	ID        string    `json:"id"`
	MessageID string    `json:"messageId"`
	ToolName  string    `json:"toolName"`
	Args      []byte    `json:"args,omitempty"`
	Result    []byte    `json:"result,omitempty"`
	Error     string    `json:"error,omitempty"`
	LatencyMS int64     `json:"latencyMs"`
	Status    string    `json:"status"`
	CreatedAt time.Time `json:"createdAt"`
}

type CreateMessageInput struct {
	ConversationID string
	Role           string
	Content        string
	Reasoning      string
	Status         string
}

func NewService(db *gorm.DB) *Service {
	return &Service{db: db}
}

func (s *Service) ListConversations(ctx context.Context) ([]ChatConversation, error) {
	var rows []store.Conversation
	if err := s.db.WithContext(ctx).Order("updated_at desc").Find(&rows).Error; err != nil {
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
		Where("conversation_id = ?", conversationID).
		Order("created_at asc").
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
		Status:         input.Status,
	}
	if row.Status == "" {
		row.Status = "complete"
	}

	if err := s.db.WithContext(ctx).Create(&row).Error; err != nil {
		return ChatMessage{}, err
	}
	return messageDTO(row), nil
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
		return tx.Where("conversation_id = ? AND created_at > ?", row.ConversationID, row.CreatedAt).
			Delete(&store.Message{}).Error
	})
	if err != nil {
		return ChatMessage{}, err
	}
	return messageDTO(row), nil
}

func IsNotFound(err error) bool {
	return errors.Is(err, gorm.ErrRecordNotFound)
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
	return ChatMessage{
		ID:             row.ID,
		ConversationID: row.ConversationID,
		Role:           row.Role,
		Content:        row.Content,
		Reasoning:      row.Reasoning,
		Status:         row.Status,
		CreatedAt:      row.CreatedAt,
	}
}
