package repository

import (
	"emas/internal/domain"

	"gorm.io/gorm"
)

type JobDependencyRepository struct {
	db *gorm.DB
}

func NewJobDependencyRepository(db *gorm.DB) *JobDependencyRepository {
	return &JobDependencyRepository{db: db}
}

func (r *JobDependencyRepository) Create(dep *domain.JobDependency) error {
	return r.db.Create(dep).Error
}

func (r *JobDependencyRepository) ListByParentJobID(jobID string) ([]domain.JobDependency, error) {
	var deps []domain.JobDependency
	err := r.db.Where("parent_job_id = ?", jobID).Order("created_at ASC, dependency_id ASC").Find(&deps).Error
	return deps, err
}

func (r *JobDependencyRepository) ListByChildJobID(jobID string) ([]domain.JobDependency, error) {
	var deps []domain.JobDependency
	err := r.db.Where("child_job_id = ?", jobID).Order("created_at ASC, dependency_id ASC").Find(&deps).Error
	return deps, err
}

func (r *JobDependencyRepository) ListByConsumerJobStepID(jobStepID string) ([]domain.JobDependency, error) {
	var deps []domain.JobDependency
	err := r.db.Where("consumer_job_step_id = ?", jobStepID).Order("created_at ASC, dependency_id ASC").Find(&deps).Error
	return deps, err
}
