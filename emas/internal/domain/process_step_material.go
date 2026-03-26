package domain

// ProcessStepMaterialRole values
const (
	ProcessStepMaterialRoleInput  = "input"
	ProcessStepMaterialRoleOutput = "output"
)

// ProcessStepMaterial - step-level material transformation (inputs/outputs per process step)
// Bridges Process and Formula: answers "what does Step 2 produce?" and "what does Step 3 need?"
type ProcessStepMaterial struct {
	ID             string  `gorm:"column:id;primaryKey;size:50"`
	StepID         string  `gorm:"column:step_id;size:50;index;not null"`
	MaterialID     *string `gorm:"column:material_id;size:50;index"`
	ProductID      *string `gorm:"column:product_id;size:50;index"`
	Role           string  `gorm:"column:role;size:20;not null"` // input | output
	QuantityPerUnit float64 `gorm:"column:quantity_per_unit;not null;default:1"`
	Unit           string  `gorm:"column:unit;size:50"`
}

func (ProcessStepMaterial) TableName() string { return "process_step_materials" }
