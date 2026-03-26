package repository

import (
	"emas/internal/domain"
	"time"

	"gorm.io/gorm"
)

type MachineDowntimeRepository struct {
	db *gorm.DB
}

func NewMachineDowntimeRepository(db *gorm.DB) *MachineDowntimeRepository {
	return &MachineDowntimeRepository{db: db}
}

func (r *MachineDowntimeRepository) Create(d *domain.MachineDowntime) error {
	return r.db.Create(d).Error
}

func (r *MachineDowntimeRepository) ListByMachineID(machineID string) ([]domain.MachineDowntime, error) {
	var records []domain.MachineDowntime
	err := r.db.Where("machine_id = ?", machineID).Order("start_time DESC").Find(&records).Error
	return records, err
}

func (r *MachineDowntimeRepository) ListOverlapping(machineID string, start, end time.Time) ([]domain.MachineDowntime, error) {
	var records []domain.MachineDowntime
	err := r.db.Where("machine_id = ? AND start_time < ? AND end_time > ?", machineID, end, start).
		Order("start_time").Find(&records).Error
	return records, err
}
