package domain

import "time"

// ProductionLogs - actual production execution records
type ProductionLogs struct {
	ProductionID     string    `gorm:"column:production_id;primaryKey;size:50"`
	SlotID           string    `gorm:"column:slot_id;size:50;index"`
	StartTime        time.Time `gorm:"column:start_time"`
	EndTime          time.Time `gorm:"column:end_time"`
	QuantityProduced int       `gorm:"column:quantity_produced"`
	QuantityScrap    int       `gorm:"column:quantity_scrap"`
	OperatorNotes    string    `gorm:"column:operator_notes;type:text"`
	DowntimeMinutes  *int      `gorm:"column:downtime_minutes"` // Gap 7 - downtime during slot for OEE
}

func (ProductionLogs) TableName() string { return "production_logs" }
