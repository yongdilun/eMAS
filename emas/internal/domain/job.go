package domain

import "time"

// JobPriority values
const (
	JobPriorityLow    = "low"
	JobPriorityMedium = "medium"
	JobPriorityHigh   = "high"
	JobPriorityUrgent = "urgent"
)

// JobStatus values
const (
	JobStatusPlanned   = "planned"
	JobStatusScheduled = "scheduled"
	JobStatusRunning   = "running"
	JobStatusPaused    = "paused"
	JobStatusCompleted = "completed"
	JobStatusCancelled = "cancelled"
)

// JobDeadlineStatus is computed from max(slot.scheduled_end) vs job.deadline; shown on job responses for late labels.
type JobDeadlineStatus struct {
	IsLate bool   `json:"is_late"`
	LateBy string `json:"late_by"` // human-readable: "2 days", "4 hours", "on time"
}

// Job - production order
type Job struct {
	JobID             string             `gorm:"column:job_id;primaryKey;size:50" json:"job_id"`
	ProductID         string             `gorm:"column:product_id;size:50;index" json:"product_id"`
	QuantityTotal     int                `gorm:"column:quantity_total" json:"quantity_total"`
	QuantityCompleted int                `gorm:"column:quantity_completed" json:"quantity_completed"`
	Priority          string             `gorm:"column:priority;size:20" json:"priority"`
	Deadline          time.Time          `gorm:"column:deadline" json:"deadline"`
	Status            string             `gorm:"column:status;size:20" json:"status"`
	CreatedAt         time.Time          `gorm:"column:created_at" json:"created_at"`
	UpdatedAt         time.Time          `gorm:"column:updated_at" json:"updated_at"`
	Notes             string             `gorm:"column:notes;type:text" json:"notes"`
	DeadlineStatus    *JobDeadlineStatus `gorm:"-" json:"deadline_status,omitempty"`
}

func (Job) TableName() string { return "jobs" }

// JobStepStatus values
const (
	JobStepStatusPending   = "pending"
	JobStepStatusScheduled = "scheduled"
	JobStepStatusRunning   = "running"
	JobStepStatusCompleted = "completed"
)

// JobSteps - steps within a production order
type JobSteps struct {
	JobStepID         string `gorm:"column:job_step_id;primaryKey;size:50" json:"job_step_id"`
	JobID             string `gorm:"column:job_id;size:50;index" json:"job_id"`
	StepID            string `gorm:"column:step_id;size:50;index" json:"step_id"`
	StepSequence      int    `gorm:"column:step_sequence" json:"step_sequence"`
	QuantityTarget    int    `gorm:"column:quantity_target" json:"quantity_target"`
	QuantityCompleted int    `gorm:"column:quantity_completed" json:"quantity_completed"`
	Status            string `gorm:"column:status;size:20" json:"status"`
}

func (JobSteps) TableName() string { return "job_steps" }
