package repository

import (
	"emas/internal/domain"

	"gorm.io/gorm"
)

type AIConversationRepository struct {
	db *gorm.DB
}

func NewAIConversationRepository(db *gorm.DB) *AIConversationRepository {
	return &AIConversationRepository{db: db}
}

func (r *AIConversationRepository) Create(c *domain.AIConversation) error {
	return r.db.Create(c).Error
}

func (r *AIConversationRepository) GetByID(id string) (*domain.AIConversation, error) {
	var conv domain.AIConversation
	if err := r.db.Where("id = ?", id).First(&conv).Error; err != nil {
		return nil, err
	}
	return &conv, nil
}

func (r *AIConversationRepository) List(limit, offset int) ([]domain.AIConversation, error) {
	var list []domain.AIConversation
	q := r.db.Order("updated_at DESC")
	if limit > 0 {
		q = q.Limit(limit)
	}
	if offset > 0 {
		q = q.Offset(offset)
	}
	err := q.Find(&list).Error
	return list, err
}

func (r *AIConversationRepository) Update(c *domain.AIConversation) error {
	return r.db.Save(c).Error
}
