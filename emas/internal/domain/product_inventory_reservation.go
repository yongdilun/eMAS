package domain

import "time"

type ProductInventoryReservation struct {
	ReservationID string    `gorm:"column:reservation_id;primaryKey;size:50"`
	ProductID     string    `gorm:"column:product_id;size:50;index;not null"`
	JobID         string    `gorm:"column:job_id;size:50;index"`
	JobStepID     string    `gorm:"column:job_step_id;size:50;index"`
	ReservedQty   float64   `gorm:"column:reserved_qty;not null"`
	NeededAt      time.Time `gorm:"column:needed_at;index"`
	Status        string    `gorm:"column:status;size:20;default:pending"`
	CreatedAt     time.Time `gorm:"column:created_at"`
	UpdatedAt     time.Time `gorm:"column:updated_at"`
}

func (ProductInventoryReservation) TableName() string { return "product_inventory_reservations" }
