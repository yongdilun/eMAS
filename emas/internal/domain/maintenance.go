package domain

import "time"

// MaintenanceType values
const (
	MaintenanceTypePreventive = "preventive"
	MaintenanceTypeCorrective = "corrective"
)

// MaintenanceRecords - machine maintenance history
type MaintenanceRecords struct {
	MaintenanceID   string    `gorm:"column:maintenance_id;primaryKey;size:50"`
	MachineID       string    `gorm:"column:machine_id;size:50;index"`
	MaintenanceType string    `gorm:"column:maintenance_type;size:20"`
	StartTime       time.Time `gorm:"column:start_time"`
	EndTime         time.Time `gorm:"column:end_time"`
	Technician      string    `gorm:"column:technician;size:100"`
	Description     string    `gorm:"column:description;type:text"`
}

func (MaintenanceRecords) TableName() string { return "maintenance_records" }
