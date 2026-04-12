package domain

import "time"

const (
	JobDependencyRelationSubproductSupply = "subproduct_supply"
)

type JobDependency struct {
	DependencyID      string    `gorm:"column:dependency_id;primaryKey;size:50"`
	ParentJobID       string    `gorm:"column:parent_job_id;size:50;index;not null"`
	ChildJobID        string    `gorm:"column:child_job_id;size:50;index;not null"`
	ConsumerJobStepID string    `gorm:"column:consumer_job_step_id;size:50;index;not null"`
	ProductID         string    `gorm:"column:product_id;size:50;index;not null"`
	RequiredQty       float64   `gorm:"column:required_qty;not null"`
	PlannedQty        float64   `gorm:"column:planned_qty;not null"`
	RelationType      string    `gorm:"column:relation_type;size:50;not null"`
	CreatedAt         time.Time `gorm:"column:created_at"`
	UpdatedAt         time.Time `gorm:"column:updated_at"`
}

func (JobDependency) TableName() string { return "job_dependencies" }
