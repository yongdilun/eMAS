package repository

import (
	"emas/internal/domain"

	"gorm.io/gorm"
)

type MachineCapabilityRepository struct {
	db *gorm.DB
}

func NewMachineCapabilityRepository(db *gorm.DB) *MachineCapabilityRepository {
	return &MachineCapabilityRepository{db: db}
}

func (r *MachineCapabilityRepository) Create(c *domain.MachineCapabilities) error {
	return r.db.Create(c).Error
}

func (r *MachineCapabilityRepository) ListByMachineID(machineID string) ([]domain.MachineCapabilities, error) {
	var caps []domain.MachineCapabilities
	err := r.db.Where("machine_id = ?", machineID).Find(&caps).Error
	return caps, err
}

func (r *MachineCapabilityRepository) DeleteByMachineID(machineID string) error {
	return r.db.Where("machine_id = ?", machineID).Delete(&domain.MachineCapabilities{}).Error
}

func (r *MachineCapabilityRepository) ListMachinesByStepID(stepID string) ([]string, error) {
	var ids []string
	err := r.db.Model(&domain.MachineCapabilities{}).Where("step_id = ?", stepID).Distinct("machine_id").Pluck("machine_id", &ids).Error
	return ids, err
}

func (r *MachineCapabilityRepository) ListStepIDsByMachineID(machineID string) ([]string, error) {
	var ids []string
	err := r.db.Model(&domain.MachineCapabilities{}).Where("machine_id = ?", machineID).Pluck("step_id", &ids).Error
	return ids, err
}

func (r *MachineCapabilityRepository) HasCapability(machineID, stepID string) (bool, *domain.MachineCapabilities, error) {
	var cap domain.MachineCapabilities
	err := r.db.Where("machine_id = ? AND step_id = ?", machineID, stepID).First(&cap).Error
	if err == gorm.ErrRecordNotFound {
		return false, nil, nil
	}
	if err != nil {
		return false, nil, err
	}
	return true, &cap, nil
}
