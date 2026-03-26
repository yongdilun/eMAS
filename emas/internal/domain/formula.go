package domain

import "time"

// Formula - recipe / formula definition
type Formula struct {
	FormulaID     string     `gorm:"column:formula_id;primaryKey;size:50"`
	FormulaName   string     `gorm:"column:formula_name;size:255"`
	Version       int        `gorm:"column:version"`
	Instructions  string     `gorm:"column:instructions;type:text"`
	SafetyNotes   string     `gorm:"column:safety_notes;type:text"`
	CreatedAt     time.Time  `gorm:"column:created_at"`
	EffectiveFrom *time.Time `gorm:"column:effective_from"`
	EffectiveTo   *time.Time `gorm:"column:effective_to"`
}

func (Formula) TableName() string { return "formula" }

const (
	ComponentTypeMaterial = "material"
	ComponentTypeProduct  = "product"
)

const (
	IngredientSourceMake = "make"
	IngredientSourceBuy  = "buy"
)

// FormulaIngredients - materials or sub-products used in a formula
type FormulaIngredients struct {
	IngredientID    string  `gorm:"column:ingredient_id;primaryKey;size:50" json:"ingredient_id"`
	FormulaID       string  `gorm:"column:formula_id;size:50;index" json:"formula_id"`
	ComponentType   string  `gorm:"column:component_type;size:20;default:material" json:"component_type"`
	MaterialID      *string `gorm:"column:material_id;size:50;index" json:"material_id,omitempty"`
	ProductID       *string `gorm:"column:product_id;size:50;index" json:"product_id,omitempty"`
	QuantityPerUnit float64 `gorm:"column:quantity" json:"quantity_per_unit"`
	Unit            string  `gorm:"column:unit;size:50" json:"unit"`
	ScrapRate       float64 `gorm:"column:scrap_rate" json:"scrap_rate"`
	Percentage      float64 `gorm:"column:percentage" json:"percentage,omitempty"`
	LeadTimeHours   int     `gorm:"column:lead_time_hours;default:0" json:"lead_time_hours"` // 0 = instant
	Source          string  `gorm:"column:source;size:20;default:buy" json:"source"`        // "make" | "buy"
}

func (FormulaIngredients) TableName() string { return "formula_ingredients" }
