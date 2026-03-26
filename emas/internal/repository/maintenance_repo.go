package repository

import (
	"emas/internal/domain"
	"time"

	"gorm.io/gorm"
)

type MaintenanceRepository struct {
	db *gorm.DB
}

func NewMaintenanceRepository(db *gorm.DB) *MaintenanceRepository {
	return &MaintenanceRepository{db: db}
}

func (r *MaintenanceRepository) Create(m *domain.MaintenanceRecords) error {
	return r.db.Create(m).Error
}

func (r *MaintenanceRepository) ListByMachineID(machineID string) ([]domain.MaintenanceRecords, error) {
	var records []domain.MaintenanceRecords
	err := r.db.Where("machine_id = ?", machineID).Order("start_time DESC").Find(&records).Error
	return records, err
}

func (r *MaintenanceRepository) ListOverlapping(machineID string, start, end time.Time) ([]domain.MaintenanceRecords, error) {
	var records []domain.MaintenanceRecords
	err := r.db.Where("machine_id = ? AND start_time < ? AND end_time > ?", machineID, end, start).
		Order("start_time").Find(&records).Error
	return records, err
}
