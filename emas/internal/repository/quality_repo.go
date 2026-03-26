package repository

import (
	"emas/internal/domain"

	"gorm.io/gorm"
)

type QualityRepository struct {
	db *gorm.DB
}

func NewQualityRepository(db *gorm.DB) *QualityRepository {
	return &QualityRepository{db: db}
}

func (r *QualityRepository) Create(q *domain.QualityInspectionRecords) error {
	return r.db.Create(q).Error
}

func (r *QualityRepository) ListByJobStepID(jobStepID string) ([]domain.QualityInspectionRecords, error) {
	var records []domain.QualityInspectionRecords
	err := r.db.Where("job_step_id = ?", jobStepID).Find(&records).Error
	return records, err
}
