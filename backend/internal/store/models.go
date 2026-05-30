package store

import (
	"time"

	"gorm.io/datatypes"
)

type Conversation struct {
	ID        string `gorm:"primaryKey"`
	Title     string
	CreatedAt time.Time
	UpdatedAt time.Time
	Messages  []Message `gorm:"foreignKey:ConversationID;constraint:OnDelete:CASCADE;"`
}

type Message struct {
	ID              string `gorm:"primaryKey"`
	ConversationID  string `gorm:"index;not null"`
	Conversation    Conversation
	Role            string
	Content         string
	Reasoning       string
	Status          string
	CreatedAt       time.Time
	ToolInvocations []ToolInvocation `gorm:"foreignKey:MessageID;constraint:OnDelete:CASCADE;"`
}

type ToolInvocation struct {
	ID        string `gorm:"primaryKey"`
	MessageID string `gorm:"index;not null"`
	Message   Message
	ToolName  string
	Args      datatypes.JSON
	Result    datatypes.JSON
	Error     string
	LatencyMS int64
	Status    string
	CreatedAt time.Time
}
