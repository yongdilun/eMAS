package domain

import "time"

// InventoryStatus values
const (
	InventoryStatusInStock    = "in_stock"
	InventoryStatusLowStock   = "low_stock"
	InventoryStatusOutOfStock = "out_of_stock"
)

// InventoryMaterials - raw materials and consumables
type InventoryMaterials struct {
	MaterialID      string    `gorm:"column:material_id;primaryKey;size:50"`
	MaterialName    string    `gorm:"column:material_name;size:255"`
	Unit            string    `gorm:"column:unit;size:50"`
	CurrentStock    float64   `gorm:"column:current_stock"`
	MinStock        float64   `gorm:"column:min_stock"`
	ReorderLevel    float64   `gorm:"column:reorder_level"`
	StorageLocation string    `gorm:"column:storage_location;size:255"`
	Status          string    `gorm:"column:status;size:20"`
	LastUpdated     time.Time `gorm:"column:last_updated"`
}

func (InventoryMaterials) TableName() string { return "inventory_materials" }

// InventoryTransactionType values
const (
	TransactionTypeReceive = "receive"
	TransactionTypeConsume = "consume"
	TransactionTypeAdjust  = "adjust"
)

// InventoryTransactions - stock movements
type InventoryTransactions struct {
	TransactionID   string    `gorm:"column:transaction_id;primaryKey;size:50"`
	MaterialID      string    `gorm:"column:material_id;size:50;index"`
	TransactionType string    `gorm:"column:transaction_type;size:20"`
	Quantity        float64   `gorm:"column:quantity"`
	ReferenceJobID  string    `gorm:"column:reference_job_id;size:50;index"`
	Timestamp       time.Time `gorm:"column:timestamp"`
	Notes           string    `gorm:"column:notes;type:text"`
}

func (InventoryTransactions) TableName() string { return "inventory_transactions" }

// ExpectedArrivalStatus values
const (
	ExpectedArrivalStatusPending   = "pending"
	ExpectedArrivalStatusReceived  = "received"
	ExpectedArrivalStatusCancelled = "cancelled"
)

// InventoryExpectedArrival - planned future stock arrivals
type InventoryExpectedArrival struct {
	ArrivalID        string     `gorm:"column:arrival_id;primaryKey;size:50"`
	MaterialID       string     `gorm:"column:material_id;size:50;index;not null"`
	Quantity         float64    `gorm:"column:quantity;not null"`
	ExpectedArriveAt time.Time  `gorm:"column:expected_arrive_at;index;not null"`
	Status           string     `gorm:"column:status;size:20;default:pending"`
	Notes            string     `gorm:"column:notes;type:text"`
	ReferenceJobID   string     `gorm:"column:reference_job_id;size:50;index"`
	ReceivedAt       *time.Time `gorm:"column:received_at"`
	CreatedAt        time.Time  `gorm:"column:created_at"`
}

func (InventoryExpectedArrival) TableName() string { return "inventory_expected_arrivals" }

// ProductInventoryStatus values
const (
	ProductInventoryStatusAvailable = "available"
	ProductInventoryStatusReserved  = "reserved"
	ProductInventoryStatusBlocked   = "blocked"
	// ProductInventoryStatusPlanned marks records created at proposal-apply time to represent
	// planned production output. These bridge the plan-apply gap so that subsequent proposals
	// in the same Apply All batch see production committed by earlier proposals, matching the
	// visibility the batch planning ledger provides during proposal generation.
	ProductInventoryStatusPlanned = "planned"
)

// ProductInventory - on-hand finished/semi-finished inventory for sub-product readiness
type ProductInventory struct {
	InventoryID      string    `gorm:"column:inventory_id;primaryKey;size:50"`
	ProductID        string    `gorm:"column:product_id;size:50;index;not null"`
	QuantityOnHand   float64   `gorm:"column:quantity_on_hand;not null"`
	QuantityReserved float64   `gorm:"column:quantity_reserved;not null"`
	Status           string    `gorm:"column:status;size:20;default:available"`
	StorageLocation  string    `gorm:"column:storage_location;size:255"`
	AvailableFrom    time.Time `gorm:"column:available_from;index"`
	LastUpdated      time.Time `gorm:"column:last_updated"`
}

func (ProductInventory) TableName() string { return "product_inventory" }

// InventoryReservationStatus values
const (
	InventoryReservationStatusPending  = "pending"
	InventoryReservationStatusConsumed = "consumed"
	InventoryReservationStatusReleased = "released"
)

// InventoryReservation - time-phased stock reservation against a job/job step
type InventoryReservation struct {
	ReservationID string    `gorm:"column:reservation_id;primaryKey;size:50"`
	MaterialID    string    `gorm:"column:material_id;size:50;index;not null"`
	JobID         string    `gorm:"column:job_id;size:50;index"`
	JobStepID     string    `gorm:"column:job_step_id;size:50;index"`
	ReservedQty   float64   `gorm:"column:reserved_qty;not null"`
	NeededAt      time.Time `gorm:"column:needed_at;index"`
	Status        string    `gorm:"column:status;size:20;default:pending"`
	CreatedAt     time.Time `gorm:"column:created_at"`
	UpdatedAt     time.Time `gorm:"column:updated_at"`
}

func (InventoryReservation) TableName() string { return "inventory_reservations" }
