package repository

import (
	"emas/internal/domain"

	"gorm.io/gorm"
)

type WIPRepository struct {
	db *gorm.DB
}

func NewWIPRepository(db *gorm.DB) *WIPRepository {
	return &WIPRepository{db: db}
}

func (r *WIPRepository) ListWIPByJobStepID(jobStepID string) ([]domain.WIPInventory, error) {
	var list []domain.WIPInventory
	err := r.db.Where("job_step_id = ?", jobStepID).Find(&list).Error
	return list, err
}

func (r *WIPRepository) UpsertWIP(w *domain.WIPInventory) error {
	return r.db.Save(w).Error
}
