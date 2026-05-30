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
}

type Message struct {
	ID             string `gorm:"primaryKey"`
	ConversationID string `gorm:"index"`
	Role           string
	Content        string
	Reasoning      string
	Status         string
	CreatedAt      time.Time
}

type ToolInvocation struct {
	ID        string `gorm:"primaryKey"`
	MessageID string `gorm:"index"`
	ToolName  string
	Args      datatypes.JSON
	Result    datatypes.JSON
	Error     string
	LatencyMS int64
	Status    string
	CreatedAt time.Time
}
