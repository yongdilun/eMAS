package domain

import "time"

// JobStepSlotStatus values
const (
	SlotStatusPlanned   = "planned"
	SlotStatusRunning   = "running"
	SlotStatusCompleted = "completed"
	SlotStatusCancelled = "cancelled"
	SlotStatusPaused    = "paused"
)

// JobStepScheduleSlots - scheduled time slots for job steps on machines
type JobStepScheduleSlots struct {
	SlotID                 string    `gorm:"column:slot_id;primaryKey;size:50" json:"slot_id"`
	JobStepID              string    `gorm:"column:job_step_id;size:50;index" json:"job_step_id"`
	ProposalID             string    `gorm:"column:proposal_id;size:50;index" json:"proposal_id"`
	MachineID              string    `gorm:"column:machine_id;size:50;index" json:"machine_id"`
	ScheduledStart         time.Time `gorm:"column:scheduled_start" json:"scheduled_start"`
	ScheduledEnd           time.Time `gorm:"column:scheduled_end" json:"scheduled_end"`
	QuantityPlanned        int       `gorm:"column:quantity_planned" json:"quantity_planned"`
	SplitGroupID           string    `gorm:"column:split_group_id;size:50;index" json:"split_group_id"`
	AllocationPercent      float64   `gorm:"column:allocation_percent" json:"allocation_percent"`
	IsParallel             bool      `gorm:"column:is_parallel" json:"is_parallel"`
	BatchSequence          int       `gorm:"column:batch_sequence" json:"batch_sequence"`
	PreparationTimeMinutes int       `gorm:"column:preparation_time_minutes" json:"preparation_time_minutes"`
	ProcessingTimeMinutes  int       `gorm:"column:processing_time_minutes" json:"processing_time_minutes"`
	CleaningTimeMinutes    int       `gorm:"column:cleaning_time_minutes" json:"cleaning_time_minutes"`
	ChangeoverTimeMinutes  int       `gorm:"column:changeover_time_minutes" json:"changeover_time_minutes"`
	BufferTimeMinutes      int        `gorm:"column:buffer_time_minutes" json:"buffer_time_minutes"`
	Status                 string     `gorm:"column:status;size:20" json:"status"`
	ActualStart            *time.Time `gorm:"column:actual_start" json:"actual_start,omitempty"`
	ActualEnd              *time.Time `gorm:"column:actual_end" json:"actual_end,omitempty"`
}

func (JobStepScheduleSlots) TableName() string { return "job_step_schedule_slots" }
