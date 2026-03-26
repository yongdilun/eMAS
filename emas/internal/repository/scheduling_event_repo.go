package repository

import (
	"emas/internal/domain"

	"gorm.io/gorm"
)

type SchedulingEventRepository struct {
	db *gorm.DB
}

func NewSchedulingEventRepository(db *gorm.DB) *SchedulingEventRepository {
	return &SchedulingEventRepository{db: db}
}

func (r *SchedulingEventRepository) Create(e *domain.SchedulingEvent) error {
	return r.db.Create(e).Error
}
