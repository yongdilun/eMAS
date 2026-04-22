package repository

import (
	"emas/internal/domain"
	"gorm.io/gorm"
)

type ChatbotApprovalRepository interface {
	Create(approval *domain.ChatbotApproval) error
	GetByID(id string) (*domain.ChatbotApproval, error)
	Update(approval *domain.ChatbotApproval) error
	GetPendingByConversation(conversationID string) ([]domain.ChatbotApproval, error)
}

type chatbotApprovalRepo struct {
	db *gorm.DB
}

func NewChatbotApprovalRepository(db *gorm.DB) ChatbotApprovalRepository {
	return &chatbotApprovalRepo{db: db}
}

func (r *chatbotApprovalRepo) Create(approval *domain.ChatbotApproval) error {
	return r.db.Create(approval).Error
}

func (r *chatbotApprovalRepo) GetByID(id string) (*domain.ChatbotApproval, error) {
	var approval domain.ChatbotApproval
	if err := r.db.Where("id = ?", id).First(&approval).Error; err != nil {
		return nil, err
	}
	return &approval, nil
}

func (r *chatbotApprovalRepo) Update(approval *domain.ChatbotApproval) error {
	return r.db.Save(approval).Error
}

func (r *chatbotApprovalRepo) GetPendingByConversation(conversationID string) ([]domain.ChatbotApproval, error) {
	var approvals []domain.ChatbotApproval
	if err := r.db.Where("conversation_id = ? AND status = ?", conversationID, "PENDING").Find(&approvals).Error; err != nil {
		return nil, err
	}
	return approvals, nil
}
