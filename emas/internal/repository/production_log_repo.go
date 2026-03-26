package repository

import (
	"emas/internal/domain"

	"gorm.io/gorm"
)

type ProductionLogRepository struct {
	db *gorm.DB
}

func NewProductionLogRepository(db *gorm.DB) *ProductionLogRepository {
	return &ProductionLogRepository{db: db}
}

func (r *ProductionLogRepository) Create(l *domain.ProductionLogs) error {
	return r.db.Create(l).Error
}

func (r *ProductionLogRepository) ListBySlotID(slotID string) ([]domain.ProductionLogs, error) {
	var logs []domain.ProductionLogs
	err := r.db.Where("slot_id = ?", slotID).Find(&logs).Error
	return logs, err
}

func (r *ProductionLogRepository) SumProducedBySlotID(slotID string) (int, error) {
	var total int
	err := r.db.Model(&domain.ProductionLogs{}).
		Where("slot_id = ?", slotID).
		Select("COALESCE(SUM(quantity_produced),0)").
		Scan(&total).Error
	return total, err
}
