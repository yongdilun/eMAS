package domain

import "time"

// ProductProcess - routing template: defines how a product is manufactured
type ProductProcess struct {
	ProcessID     string     `gorm:"column:process_id;primaryKey;size:50"`
	ProductID     string     `gorm:"column:product_id;size:50;index"`
	ProcessName   string     `gorm:"column:process_name;size:255"`
	Version       int        `gorm:"column:version"`
	Description   string     `gorm:"column:description;type:text"`
	EffectiveFrom *time.Time `gorm:"column:effective_from"`
	EffectiveTo   *time.Time `gorm:"column:effective_to"`
	IsPrimary     bool       `gorm:"column:is_primary;default:true"`  // primary vs alternative routing
	Sequence      int        `gorm:"column:sequence;default:0"`       // order when multiple (0=primary)
}

func (ProductProcess) TableName() string { return "product_process" }

// ProcessSteps - individual steps within a process
type ProcessSteps struct {
	StepID                 string `gorm:"column:step_id;primaryKey;size:50" json:"step_id"`
	ProcessID              string `gorm:"column:process_id;size:50;index" json:"process_id"`
	StepSequence           int    `gorm:"column:step_sequence" json:"step_sequence"`
	StepName               string `gorm:"column:step_name;size:255" json:"step_name"`
	StepType               string `gorm:"column:step_type;size:100;index" json:"step_type"` // matches reference_step_types.name
	MachineTypeRequired    string `gorm:"column:machine_type_required;size:100" json:"machine_type_required"`
	DefaultPreparationTime int    `gorm:"column:default_preparation_time" json:"default_preparation_time"` // minutes
	DefaultProcessingTime  int    `gorm:"column:default_processing_time" json:"default_processing_time"`  // minutes
	DefaultCleaningTime    int    `gorm:"column:default_cleaning_time" json:"default_cleaning_time"`      // minutes
	DefaultChangeoverTime  int    `gorm:"column:default_changeover_time" json:"default_changeover_time"`  // minutes
	AllowParallelExecution bool   `gorm:"column:allow_parallel_execution" json:"allow_parallel_execution"`
	MaxParallelMachines    int    `gorm:"column:max_parallel_machines" json:"max_parallel_machines"`
	MinSplitQty            int    `gorm:"column:min_split_qty" json:"min_split_qty"`
	TransferBatchSize      int    `gorm:"column:transfer_batch_size" json:"transfer_batch_size"`
	MinWaitMinutes         int    `gorm:"column:min_wait_minutes" json:"min_wait_minutes"`         // e.g. cooling time before next step
	TransferMinutes        int    `gorm:"column:transfer_minutes" json:"transfer_minutes"`         // transport time to next step
	BatchSize              int    `gorm:"column:batch_size" json:"batch_size"`                     // 0 = no batch constraint
	MinBatchSize           int    `gorm:"column:min_batch_size" json:"min_batch_size"`             // minimum batch when splitting
	IsBatchProcess         bool   `gorm:"column:is_batch_process" json:"is_batch_process"`         // true if step runs in batches
	QualityCheckRequired   bool   `gorm:"column:quality_check_required" json:"quality_check_required"`
	Notes                  string `gorm:"column:notes;type:text" json:"notes"`
	PredecessorStepIDs     string `gorm:"column:predecessor_step_ids;type:text" json:"predecessor_step_ids"` // JSON array of step_ids; empty = infer from StepSequence
}

func (ProcessSteps) TableName() string { return "process_steps" }
