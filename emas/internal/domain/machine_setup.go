package domain

// MachineSetupRule - setup time when switching from one product to another on a machine
type MachineSetupRule struct {
	ID             string `gorm:"column:id;primaryKey;size:50"`
	MachineID      string `gorm:"column:machine_id;size:50;index;not null"`
	FromProductID  string `gorm:"column:from_product_id;size:50;index"` // empty = any/first
	ToProductID    string `gorm:"column:to_product_id;size:50;index"`   // empty = any
	SetupMinutes   int    `gorm:"column:setup_minutes;not null"`
	FromProductFamily string `gorm:"column:from_product_family;size:100;index"`
	ToProductFamily   string `gorm:"column:to_product_family;size:100;index"`
}

func (MachineSetupRule) TableName() string { return "machine_setup_rules" }
