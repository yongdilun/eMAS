package repository

import (
	"emas/internal/domain"

	"gorm.io/gorm"
)

type ProcessStepMaterialRepository struct {
	db *gorm.DB
}

func NewProcessStepMaterialRepository(db *gorm.DB) *ProcessStepMaterialRepository {
	return &ProcessStepMaterialRepository{db: db}
}

func (r *ProcessStepMaterialRepository) ListByStepID(stepID string) ([]domain.ProcessStepMaterial, error) {
	var list []domain.ProcessStepMaterial
	err := r.db.Where("step_id = ?", stepID).Find(&list).Error
	return list, err
}

func (r *ProcessStepMaterialRepository) ListInputsByStepID(stepID string) ([]domain.ProcessStepMaterial, error) {
	var list []domain.ProcessStepMaterial
	err := r.db.Where("step_id = ? AND role = ?", stepID, domain.ProcessStepMaterialRoleInput).Find(&list).Error
	return list, err
}

func (r *ProcessStepMaterialRepository) ListOutputsByStepID(stepID string) ([]domain.ProcessStepMaterial, error) {
	var list []domain.ProcessStepMaterial
	err := r.db.Where("step_id = ? AND role = ?", stepID, domain.ProcessStepMaterialRoleOutput).Find(&list).Error
	return list, err
}

func (r *ProcessStepMaterialRepository) Create(m *domain.ProcessStepMaterial) error {
	return r.db.Create(m).Error
}

func (r *ProcessStepMaterialRepository) GetByID(id string) (*domain.ProcessStepMaterial, error) {
	var m domain.ProcessStepMaterial
	err := r.db.Where("id = ?", id).First(&m).Error
	if err != nil {
		return nil, err
	}
	return &m, nil
}

func (r *ProcessStepMaterialRepository) Delete(id string) error {
	return r.db.Where("id = ?", id).Delete(&domain.ProcessStepMaterial{}).Error
}
