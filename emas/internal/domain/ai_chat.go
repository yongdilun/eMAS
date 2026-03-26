package domain

import "time"

// AIConversation represents a chat conversation (no user_id - single-tenant).
type AIConversation struct {
	ID        string    `gorm:"column:id;primaryKey;size:64" json:"id"`
	Title     string    `gorm:"column:title;size:255;not null" json:"title"`
	CreatedAt time.Time `gorm:"column:created_at" json:"created_at"`
	UpdatedAt time.Time `gorm:"column:updated_at" json:"updated_at"`
}

func (AIConversation) TableName() string { return "ai_conversations" }

// AIChatMessage represents a message in a conversation.
type AIChatMessage struct {
	ID             string    `gorm:"column:id;primaryKey;size:64" json:"id"`
	ConversationID string    `gorm:"column:conversation_id;size:64;index;not null" json:"conversation_id"`
	Role           string    `gorm:"column:role;size:20;not null" json:"role"` // user | assistant
	Content        string    `gorm:"column:content;type:text;not null" json:"content"`
	Metadata       string    `gorm:"column:metadata;type:text" json:"metadata,omitempty"` // JSON: intent, result_cards, entities, etc.
	CreatedAt      time.Time `gorm:"column:created_at" json:"created_at"`
}

func (AIChatMessage) TableName() string { return "ai_chat_messages" }
