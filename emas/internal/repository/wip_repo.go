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

func (r *WIPRepository) ListWIPByJobID(jobID string) ([]domain.WIPInventory, error) {
	var list []domain.WIPInventory
	err := r.db.Table("wip_inventory").
		Select("wip_inventory.*").
		Joins("JOIN job_steps ON job_steps.job_step_id = wip_inventory.job_step_id").
		Where("job_steps.job_id = ?", jobID).
		Order("wip_inventory.updated_at ASC, wip_inventory.id ASC").
		Scan(&list).Error
	return list, err
}

func (r *WIPRepository) UpsertWIP(w *domain.WIPInventory) error {
	return r.db.Save(w).Error
}
