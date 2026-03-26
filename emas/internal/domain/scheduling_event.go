package domain

import "time"

// SchedulingEventType values
const (
	SchedulingEventMachineDown   = "machine_down"
	SchedulingEventJobDelay      = "job_delay"
	SchedulingEventUrgentInsert  = "urgent_insert"
)

// SchedulingEvent - event that may trigger rescheduling
type SchedulingEvent struct {
	ID        string    `gorm:"column:id;primaryKey;size:50"`
	Type      string    `gorm:"column:type;size:50;index;not null"`
	Payload   string    `gorm:"column:payload;type:text"` // JSON
	CreatedAt time.Time `gorm:"column:created_at"`
}

func (SchedulingEvent) TableName() string { return "scheduling_events" }
