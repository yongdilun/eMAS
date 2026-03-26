package domain

import "time"

// ProductStatus represents product lifecycle status
const (
	ProductStatusActive   = "active"
	ProductStatusObsolete = "obsolete"
)

// Product - master data for manufactured/finished products
type Product struct {
	ProductID     string    `gorm:"column:product_id;primaryKey;size:50"`
	ProductName   string    `gorm:"column:product_name;size:255"`
	Description   string    `gorm:"column:description;type:text"`
	UnitOfMeasure string    `gorm:"column:unit_of_measure;size:50"` // pcs / kg / liter
	ProductType   string    `gorm:"column:product_type;size:100"`
	Status        string    `gorm:"column:status;size:20"`   // active, obsolete
	FormulaID     string    `gorm:"column:formula_id;size:50;index"` // linked formula for BOM/recipe
	ProcessID     string    `gorm:"column:process_id;size:50;index"` // active routing for scheduling
	CreatedAt     time.Time `gorm:"column:created_at"`
}

func (Product) TableName() string { return "products" }
