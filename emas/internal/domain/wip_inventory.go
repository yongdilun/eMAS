package domain

import "time"

// WIPInventory - work-in-progress at a job step (output of previous step, input for next)
type WIPInventory struct {
	ID          string    `gorm:"column:id;primaryKey;size:50"`
	JobStepID   string    `gorm:"column:job_step_id;size:50;index;not null"`
	MaterialID  *string   `gorm:"column:material_id;size:50;index"`
	ProductID   *string   `gorm:"column:product_id;size:50;index"`
	Quantity    float64   `gorm:"column:quantity;not null"`
	Unit        string    `gorm:"column:unit;size:50"`
	Location    string    `gorm:"column:location;size:100"`
	UpdatedAt   time.Time `gorm:"column:updated_at"`
}

func (WIPInventory) TableName() string { return "wip_inventory" }
