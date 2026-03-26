package domain

import "time"

// MachineDowntime - unplanned/planned machine downtime records
type MachineDowntime struct {
	DowntimeID      string    `gorm:"column:downtime_id;primaryKey;size:50"`
	MachineID       string    `gorm:"column:machine_id;size:50;index"`
	JobStepSlotID   string    `gorm:"column:job_step_slot_id;size:50;index"`
	Cause           string    `gorm:"column:cause;size:255"`
	StartTime       time.Time `gorm:"column:start_time"`
	EndTime         time.Time `gorm:"column:end_time"`
	DurationMinutes int       `gorm:"column:duration_minutes"`
}

func (MachineDowntime) TableName() string { return "machine_downtime" }
