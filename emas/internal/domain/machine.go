package domain

import "time"

// MachineStatus represents current machine state
const (
	MachineStatusIdle        = "idle"
	MachineStatusRunning     = "running"
	MachineStatusMaintenance = "maintenance"
	MachineStatusOffline     = "offline"
)

// Machine - physical equipment
type Machine struct {
	MachineID               string     `gorm:"column:machine_id;primaryKey;size:50"`
	MachineName             string     `gorm:"column:machine_name;size:255"`
	MachineType             string     `gorm:"column:machine_type;size:100"` // CNC / Press / Coating etc
	Location                string     `gorm:"column:location;size:255"`
	Status                  string     `gorm:"column:status;size:20"`
	CapacityPerHour         int        `gorm:"column:capacity_per_hour"`
	DefaultSetupTime        int        `gorm:"column:default_setup_time"`
	DefaultCleaningTime     int        `gorm:"column:default_cleaning_time"`
	DefaultChangeoverTime   int        `gorm:"column:default_changeover_time"`
	UtilizationRate         float64    `gorm:"column:utilization_rate"`
	LastMaintenanceDate     *time.Time `gorm:"column:last_maintenance_date"`
	MaintenanceIntervalDays int        `gorm:"column:maintenance_interval_days"`
}

func (Machine) TableName() string { return "machines" }

// MachineCalendar - availability windows (shifts, maintenance, holidays)
type MachineCalendar struct {
	CalendarID       string    `gorm:"column:calendar_id;primaryKey;size:50"`
	MachineID        string    `gorm:"column:machine_id;size:50;index"`
	StartTime        time.Time `gorm:"column:start_time"`
	EndTime          time.Time `gorm:"column:end_time"`
	AvailabilityType string    `gorm:"column:availability_type;size:50"` // work, maintenance, holiday, shutdown
	ShiftName        string    `gorm:"column:shift_name;size:50"`        // A/B/Night
}

func (MachineCalendar) TableName() string { return "machine_calendar" }

// MachineCapabilities - which process steps a machine can perform
type MachineCapabilities struct {
	CapabilityID     string  `gorm:"column:capability_id;primaryKey;size:50"`
	MachineID        string  `gorm:"column:machine_id;size:50;index"`
	StepID           string  `gorm:"column:step_id;size:50;index"`
	EfficiencyFactor float64 `gorm:"column:efficiency_factor"` // speed modifier for this step
}

func (MachineCapabilities) TableName() string { return "machine_capabilities" }
