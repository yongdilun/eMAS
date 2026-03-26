package repository

import (
	"emas/internal/domain"

	"gorm.io/gorm"
)

type AIChatMessageRepository struct {
	db *gorm.DB
}

func NewAIChatMessageRepository(db *gorm.DB) *AIChatMessageRepository {
	return &AIChatMessageRepository{db: db}
}

func (r *AIChatMessageRepository) Create(m *domain.AIChatMessage) error {
	return r.db.Create(m).Error
}

// ListByConversationID returns messages ordered by created_at ascending (oldest first)
// so the conversation reads top-to-bottom as user → assistant → user → assistant.
func (r *AIChatMessageRepository) ListByConversationID(conversationID string) ([]domain.AIChatMessage, error) {
	var list []domain.AIChatMessage
	err := r.db.Where("conversation_id = ?", conversationID).
		Order("created_at ASC, id ASC").
		Find(&list).Error
	return list, err
}
