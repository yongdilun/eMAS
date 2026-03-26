package repository

import (
	"emas/internal/domain"

	"gorm.io/gorm"
)

type JobStepRepository struct {
	db *gorm.DB
}

func NewJobStepRepository(db *gorm.DB) *JobStepRepository {
	return &JobStepRepository{db: db}
}

func (r *JobStepRepository) Create(s *domain.JobSteps) error {
	return r.db.Create(s).Error
}

func (r *JobStepRepository) CreateBatch(steps []domain.JobSteps) error {
	if len(steps) == 0 {
		return nil
	}
	return r.db.Create(&steps).Error
}

func (r *JobStepRepository) GetByID(id string) (*domain.JobSteps, error) {
	var s domain.JobSteps
	err := r.db.Where("job_step_id = ?", id).First(&s).Error
	if err != nil {
		return nil, err
	}
	return &s, nil
}

func (r *JobStepRepository) ListByJobID(jobID string) ([]domain.JobSteps, error) {
	var steps []domain.JobSteps
	err := r.db.Where("job_id = ?", jobID).Order("step_sequence").Find(&steps).Error
	return steps, err
}

func (r *JobStepRepository) Update(s *domain.JobSteps) error {
	return r.db.Save(s).Error
}

func (r *JobStepRepository) Delete(id string) error {
	return r.db.Where("job_step_id = ?", id).Delete(&domain.JobSteps{}).Error
}

func (r *JobStepRepository) DeleteByJobID(jobID string) error {
	return r.db.Where("job_id = ?", jobID).Delete(&domain.JobSteps{}).Error
}
