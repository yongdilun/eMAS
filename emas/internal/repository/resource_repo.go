package repository

import (
	"emas/internal/domain"
	"time"

	"gorm.io/gorm"
)

type ResourceRepository struct {
	db *gorm.DB
}

func NewResourceRepository(db *gorm.DB) *ResourceRepository {
	return &ResourceRepository{db: db}
}

func (r *ResourceRepository) ListRequirementsByStepID(stepID string) ([]domain.StepResourceRequirement, error) {
	var list []domain.StepResourceRequirement
	err := r.db.Where("step_id = ?", stepID).Find(&list).Error
	return list, err
}

func (r *ResourceRepository) ListCalendarByResourceID(resourceID string) ([]domain.ResourceCalendar, error) {
	var list []domain.ResourceCalendar
	err := r.db.Where("resource_id = ?", resourceID).Order("start_time").Find(&list).Error
	return list, err
}

// ListAllocationsOverlapping returns allocations for resourceID that overlap [start, end], excluding excludeSlotID
func (r *ResourceRepository) ListAllocationsOverlapping(resourceID string, start, end time.Time, excludeSlotID string) ([]domain.ResourceAllocation, error) {
	var list []domain.ResourceAllocation
	q := r.db.Where("resource_id = ? AND start_time < ? AND end_time > ?", resourceID, end, start)
	if excludeSlotID != "" {
		q = q.Where("slot_id <> ?", excludeSlotID)
	}
	err := q.Find(&list).Error
	return list, err
}

func (r *ResourceRepository) GetResourceByID(id string) (*domain.Resource, error) {
	var res domain.Resource
	err := r.db.Where("resource_id = ?", id).First(&res).Error
	if err != nil {
		return nil, err
	}
	return &res, nil
}

func (r *ResourceRepository) ListAll() ([]domain.Resource, error) {
	var list []domain.Resource
	err := r.db.Find(&list).Error
	return list, err
}

func (r *ResourceRepository) DeleteCalendarByResourceID(resourceID string) error {
	return r.db.Where("resource_id = ?", resourceID).Delete(&domain.ResourceCalendar{}).Error
}

func (r *ResourceRepository) CreateCalendar(cal domain.ResourceCalendar) error {
	return r.db.Create(&cal).Error
}
