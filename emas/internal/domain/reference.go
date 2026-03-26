package domain

// ReferenceMachineType - machine category lookup
type ReferenceMachineType struct {
	ID          int    `gorm:"column:id;primaryKey;autoIncrement" json:"id"`
	Name        string `gorm:"column:name;size:100;uniqueIndex;not null" json:"name"`
	Description string `gorm:"column:description;type:text" json:"description"`
}

func (ReferenceMachineType) TableName() string { return "reference_machine_types" }

// ReferenceProductType - product category lookup
type ReferenceProductType struct {
	ID   int    `gorm:"column:id;primaryKey;autoIncrement" json:"id"`
	Name string `gorm:"column:name;size:100;uniqueIndex;not null" json:"name"`
}

func (ReferenceProductType) TableName() string { return "reference_product_types" }

// ReferenceLocation - factory floor zone/bay lookup
type ReferenceLocation struct {
	ID      int     `gorm:"column:id;primaryKey;autoIncrement" json:"id"`
	Zone    string  `gorm:"column:zone;size:100;not null" json:"zone"`
	Bay     *string `gorm:"column:bay;size:50" json:"bay"`
	Display string  `gorm:"-" json:"display"` // computed in app
}

func (ReferenceLocation) TableName() string { return "reference_locations" }

// ReferenceStorageLocation - warehouse storage lookup
type ReferenceStorageLocation struct {
	ID   int    `gorm:"column:id;primaryKey;autoIncrement" json:"id"`
	Name string `gorm:"column:name;size:150;uniqueIndex;not null" json:"name"`
	Type string `gorm:"column:type;size:50;default:shelf" json:"type"` // shelf, rack, cold, hazardous, floor, dock
}

func (ReferenceStorageLocation) TableName() string { return "reference_storage_locations" }

// ReferenceStepType - process step template lookup
type ReferenceStepType struct {
	ID                 int     `gorm:"column:id;primaryKey;autoIncrement" json:"id"`
	Name               string  `gorm:"column:name;size:100;uniqueIndex;not null" json:"name"`
	DefaultMachineType *string `gorm:"column:default_machine_type;size:100" json:"default_machine_type"`
}

func (ReferenceStepType) TableName() string { return "reference_step_types" }
