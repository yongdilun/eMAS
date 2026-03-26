package domain

import "time"

// ResourceType values
const (
	ResourceTypeOperator = "operator"
	ResourceTypeFixture  = "fixture"
	ResourceTypeTooling  = "tooling"
)

// Resource - operator, fixture, or tooling required by process steps
type Resource struct {
	ResourceID   string `gorm:"column:resource_id;primaryKey;size:50"`
	ResourceName string `gorm:"column:resource_name;size:255"`
	ResourceType string `gorm:"column:resource_type;size:50;index"` // operator | fixture | tooling
}

func (Resource) TableName() string { return "resources" }

// StepResourceRequirement - links process steps to required resources
type StepResourceRequirement struct {
	ID         string `gorm:"column:id;primaryKey;size:50"`
	StepID     string `gorm:"column:step_id;size:50;index;not null"`
	ResourceID string `gorm:"column:resource_id;size:50;index;not null"`
	Count      int    `gorm:"column:count;not null;default:1"`
}

func (StepResourceRequirement) TableName() string { return "step_resource_requirements" }

// ResourceCalendar - availability windows for a resource
type ResourceCalendar struct {
	ID               string    `gorm:"column:id;primaryKey;size:50"`
	ResourceID       string    `gorm:"column:resource_id;size:50;index;not null"`
	StartTime        time.Time `gorm:"column:start_time;not null"`
	EndTime          time.Time `gorm:"column:end_time;not null"`
	AvailabilityType string    `gorm:"column:availability_type;size:20"` // work | blocked
}

func (ResourceCalendar) TableName() string { return "resource_calendar" }

// ResourceAllocation - records resource assigned to a slot
type ResourceAllocation struct {
	ID         string    `gorm:"column:id;primaryKey;size:50"`
	SlotID     string    `gorm:"column:slot_id;size:50;index;not null"`
	ResourceID string    `gorm:"column:resource_id;size:50;index;not null"`
	StartTime  time.Time `gorm:"column:start_time;not null"`
	EndTime    time.Time `gorm:"column:end_time;not null"`
}

func (ResourceAllocation) TableName() string { return "resource_allocations" }
