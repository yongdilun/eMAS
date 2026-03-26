package repository

import (
	"emas/internal/domain"
	"time"

	"gorm.io/gorm"
)

type ProcessRepository struct {
	db *gorm.DB
}

func NewProcessRepository(db *gorm.DB) *ProcessRepository {
	return &ProcessRepository{db: db}
}

func (r *ProcessRepository) GetProcessByProductID(productID string) (*domain.ProductProcess, error) {
	return r.GetProcessByProductIDAsOf(productID, time.Now())
}

// GetProcessByProductIDAsOf returns the process effective at the given time (filter by effective date range).
// Prefers primary process; falls back to first alternative if primary not found.
func (r *ProcessRepository) GetProcessByProductIDAsOf(productID string, at time.Time) (*domain.ProductProcess, error) {
	list, err := r.ListProcessesByProductIDAsOf(productID, at)
	if err != nil || len(list) == 0 {
		return nil, err
	}
	return &list[0], nil
}

// ListProcessesByProductIDAsOf returns all processes for a product effective at `at`, ordered by primary first, then sequence.
func (r *ProcessRepository) ListProcessesByProductIDAsOf(productID string, at time.Time) ([]domain.ProductProcess, error) {
	var list []domain.ProductProcess
	q := r.db.Where("product_id = ?", productID)
	q = q.Where("(effective_from IS NULL OR effective_from <= ?)", at)
	q = q.Where("(effective_to IS NULL OR effective_to > ?)", at)
	err := q.Order("is_primary DESC, sequence ASC, version DESC").Find(&list).Error
	return list, err
}

func (r *ProcessRepository) GetProcessByID(processID string) (*domain.ProductProcess, error) {
	var p domain.ProductProcess
	err := r.db.Where("process_id = ?", processID).First(&p).Error
	if err != nil {
		return nil, err
	}
	return &p, nil
}

func (r *ProcessRepository) GetStepByID(stepID string) (*domain.ProcessSteps, error) {
	var s domain.ProcessSteps
	err := r.db.Where("step_id = ?", stepID).First(&s).Error
	if err != nil {
		return nil, err
	}
	return &s, nil
}

func (r *ProcessRepository) ListStepsByProcessID(processID string) ([]domain.ProcessSteps, error) {
	var steps []domain.ProcessSteps
	err := r.db.Where("process_id = ?", processID).Order("step_sequence").Find(&steps).Error
	return steps, err
}

func (r *ProcessRepository) Create(p *domain.ProductProcess) error {
	return r.db.Create(p).Error
}

func (r *ProcessRepository) CreateStep(s *domain.ProcessSteps) error {
	return r.db.Create(s).Error
}

func (r *ProcessRepository) ListAll() ([]domain.ProductProcess, error) {
	var list []domain.ProductProcess
	err := r.db.Find(&list).Error
	return list, err
}

func (r *ProcessRepository) Update(p *domain.ProductProcess) error {
	return r.db.Save(p).Error
}

func (r *ProcessRepository) Delete(processID string) error {
	_ = r.db.Where("process_id = ?", processID).Delete(&domain.ProcessSteps{})
	return r.db.Where("process_id = ?", processID).Delete(&domain.ProductProcess{}).Error
}
