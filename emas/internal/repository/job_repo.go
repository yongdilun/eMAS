package repository

import (
	"emas/internal/domain"
	"strings"
	"time"

	"gorm.io/gorm"
)

type JobRepository struct {
	db *gorm.DB
}

func NewJobRepository(db *gorm.DB) *JobRepository {
	return &JobRepository{db: db}
}

func (r *JobRepository) Create(j *domain.Job) error {
	return r.db.Create(j).Error
}

func (r *JobRepository) GetByID(id string) (*domain.Job, error) {
	var j domain.Job
	err := r.db.Where("job_id = ?", id).First(&j).Error
	if err != nil {
		return nil, err
	}
	return &j, nil
}

func (r *JobRepository) ListAll() ([]domain.Job, error) {
	var jobs []domain.Job
	err := r.db.Order("created_at DESC").Find(&jobs).Error
	return jobs, err
}

type JobListFilter struct {
	ProductID string
	Status    string
	Priority  string
	MachineID string
	Start     *time.Time // deadline >= start
	End       *time.Time // deadline <= end
	SortBy    string     // created_at, deadline, priority
	SortDir   string     // asc, desc
	Limit     int
	Offset    int
	Fields    []string
}

func (r *JobRepository) ListFiltered(f JobListFilter) ([]domain.Job, error) {
	q := r.db.Model(&domain.Job{})
	if len(f.Fields) > 0 {
		columns := make([]string, 0, len(f.Fields))
		seen := make(map[string]bool)
		for _, field := range f.Fields {
			normalized := strings.ToLower(strings.TrimSpace(field))
			if normalized == "id" {
				normalized = "job_id"
			}
			switch normalized {
			case "job_id", "product_id", "quantity_total", "quantity_completed", "priority", "deadline", "status", "created_at", "updated_at", "notes":
				if !seen[normalized] {
					columns = append(columns, normalized)
					seen[normalized] = true
				}
			}
		}
		if len(columns) > 0 {
			q = q.Select(columns)
		}
	}

	if f.ProductID != "" {
		q = q.Where("product_id = ?", f.ProductID)
	}
	if f.Status != "" {
		q = q.Where("status = ?", f.Status)
	}
	if f.Priority != "" {
		q = q.Where("priority = ?", f.Priority)
	}
	if f.Start != nil {
		q = q.Where("deadline >= ?", *f.Start)
	}
	if f.End != nil {
		q = q.Where("deadline <= ?", *f.End)
	}
	if f.MachineID != "" {
		q = q.Joins("JOIN job_steps ON job_steps.job_id = jobs.job_id").
			Joins("JOIN job_step_schedule_slots ON job_step_schedule_slots.job_step_id = job_steps.job_step_id").
			Where("job_step_schedule_slots.machine_id = ?", f.MachineID).
			Group("jobs.job_id")
	}

	sortDir := strings.ToLower(f.SortDir)
	if sortDir != "asc" && sortDir != "desc" {
		sortDir = "desc"
	}
	sortBy := strings.ToLower(f.SortBy)
	switch sortBy {
	case "deadline":
		q = q.Order("deadline " + sortDir)
	case "priority":
		q = q.Order("priority " + sortDir)
	case "quantity_total":
		q = q.Order("quantity_total " + sortDir)
	case "completion":
		q = q.Order("(CASE WHEN quantity_total > 0 THEN quantity_completed * 100.0 / quantity_total ELSE 0 END) " + sortDir)
	default:
		q = q.Order("created_at " + sortDir)
	}

	if f.Limit > 0 {
		q = q.Limit(f.Limit)
	}
	if f.Offset > 0 {
		q = q.Offset(f.Offset)
	}

	var jobs []domain.Job
	if err := q.Find(&jobs).Error; err != nil {
		return nil, err
	}
	return jobs, nil
}

func (r *JobRepository) ListByStatus(status string) ([]domain.Job, error) {
	var jobs []domain.Job
	err := r.db.Where("status = ?", status).Order("created_at DESC").Find(&jobs).Error
	return jobs, err
}

func (r *JobRepository) ListByDateRange(start, end time.Time) ([]domain.Job, error) {
	var jobs []domain.Job
	err := r.db.Where("deadline >= ? AND deadline <= ?", start, end).Order("deadline").Find(&jobs).Error
	return jobs, err
}

func (r *JobRepository) Update(j *domain.Job) error {
	return r.db.Save(j).Error
}

func (r *JobRepository) Delete(id string) error {
	result := r.db.Where("job_id = ?", id).Delete(&domain.Job{})
	if result.Error != nil {
		return result.Error
	}
	if result.RowsAffected == 0 {
		return gorm.ErrRecordNotFound
	}
	return nil
}
