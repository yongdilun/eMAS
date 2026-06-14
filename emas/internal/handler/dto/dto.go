package dto

import "time"

type MachineStatus string
type JobPriority string
type JobStatus string
type SlotStatus string
type InventoryStatus string
type ExpectedArrivalStatus string
type ProductInventoryStatus string
type InventoryReservationStatus string
type ProductStatus string
type SortDirection string

type MachineListQuery struct {
	Status      MachineStatus `form:"status" binding:"omitempty,oneof=idle running maintenance offline" enums:"idle,running,maintenance,offline"`
	MachineName string        `form:"machine_name"`
	MachineType string        `form:"machine_type"`
	Location    string        `form:"location"`
	SortBy      string        `form:"sort_by" binding:"omitempty,oneof=machine_id machine_name machine_type status location capacity_per_hour utilization_rate last_maintenance_date created_at" enums:"machine_id,machine_name,machine_type,status,location,capacity_per_hour,utilization_rate,last_maintenance_date,created_at"`
	SortDir     SortDirection `form:"sort_dir" binding:"omitempty,oneof=asc desc" enums:"asc,desc"`
	Limit       int           `form:"limit" binding:"omitempty,gte=0"`
	Offset      int           `form:"offset" binding:"omitempty,gte=0"`
	Fields      string        `form:"fields"`
}

type JobListQuery struct {
	ProductID string        `form:"product_id"`
	Status    JobStatus     `form:"status" binding:"omitempty,oneof=planned scheduled running blocked paused completed cancelled" enums:"planned,scheduled,running,blocked,paused,completed,cancelled"`
	Priority  JobPriority   `form:"priority" binding:"omitempty,oneof=low medium high urgent" enums:"low,medium,high,urgent"`
	MachineID string        `form:"machine_id"`
	Start     string        `form:"start"`
	End       string        `form:"end"`
	SortBy    string        `form:"sort_by" binding:"omitempty,oneof=created_at deadline priority quantity_total completion" enums:"created_at,deadline,priority,quantity_total,completion"`
	SortDir   SortDirection `form:"sort_dir" binding:"omitempty,oneof=asc desc" enums:"asc,desc"`
	Limit     int           `form:"limit" binding:"omitempty,gte=0"`
	Offset    int           `form:"offset" binding:"omitempty,gte=0"`
	Fields    string        `form:"fields"`
}

type ProductListQuery struct {
	Status      ProductStatus `form:"status" binding:"omitempty,oneof=active obsolete" enums:"active,obsolete"`
	ProductType string        `form:"product_type"`
	SortBy      string        `form:"sort_by" binding:"omitempty,oneof=product_id product_name created_at" enums:"product_id,product_name,created_at"`
	SortDir     SortDirection `form:"sort_dir" binding:"omitempty,oneof=asc desc" enums:"asc,desc"`
	Limit       int           `form:"limit" binding:"omitempty,gte=0"`
	Offset      int           `form:"offset" binding:"omitempty,gte=0"`
	Fields      string        `form:"fields"`
}

type InventoryMaterialsListQuery struct {
	Status  InventoryStatus `form:"status" binding:"omitempty,oneof=in_stock low_stock out_of_stock" enums:"in_stock,low_stock,out_of_stock"`
	Q       string          `form:"q"`
	SortBy  string          `form:"sort_by" binding:"omitempty,oneof=material_name current_stock last_updated" enums:"material_name,current_stock,last_updated"`
	SortDir SortDirection   `form:"sort_dir" binding:"omitempty,oneof=asc desc" enums:"asc,desc"`
	Limit   int             `form:"limit" binding:"omitempty,gte=0"`
	Offset  int             `form:"offset" binding:"omitempty,gte=0"`
}

type ExpectedArrivalListQuery struct {
	MaterialID string                `form:"material_id"`
	Status     ExpectedArrivalStatus `form:"status" binding:"omitempty,oneof=pending received cancelled" enums:"pending,received,cancelled"`
	From       string                `form:"from"`
	To         string                `form:"to"`
}

type ProductInventoryListQuery struct {
	ProductID string                 `form:"product_id"`
	Status    ProductInventoryStatus `form:"status" binding:"omitempty,oneof=available reserved blocked planned" enums:"available,reserved,blocked,planned"`
	SortBy    string                 `form:"sort_by" binding:"omitempty,oneof=product_id available_from last_updated quantity_on_hand quantity_reserved status" enums:"product_id,available_from,last_updated,quantity_on_hand,quantity_reserved,status"`
	SortDir   SortDirection          `form:"sort_dir" binding:"omitempty,oneof=asc desc" enums:"asc,desc"`
	Limit     int                    `form:"limit" binding:"omitempty,gte=0"`
	Offset    int                    `form:"offset" binding:"omitempty,gte=0"`
	Fields    string                 `form:"fields"`
}

type InventoryReservationListQuery struct {
	MaterialID string                     `form:"material_id"`
	Status     InventoryReservationStatus `form:"status" binding:"omitempty,oneof=pending consumed released" enums:"pending,consumed,released"`
}

// API response wrapper
type Response struct {
	Success bool        `json:"success"`
	Data    interface{} `json:"data,omitempty"`
	Error   string      `json:"error,omitempty"`
}

// --- Job DTOs ---
type CreateJobRequest struct {
	ProductID     string              `json:"product_id" binding:"required"`
	QuantityTotal int                 `json:"quantity_total" binding:"required,gt=0"`
	Priority      JobPriority         `json:"priority" binding:"omitempty,oneof=low medium high urgent" enums:"low,medium,high,urgent"`
	Deadline      string              `json:"deadline"` // RFC3339
	Notes         string              `json:"notes"`
	Slots         []CreateSlotRequest `json:"slots"` // optional split slots
}

type CreateSlotRequest struct {
	JobStepID         string  `json:"job_step_id"` // optional, for split
	ProposalID        string  `json:"proposal_id"`
	MachineID         string  `json:"machine_id" binding:"required"`
	StartTime         string  `json:"start_time" binding:"required"` // RFC3339
	DurationMins      int     `json:"duration_mins" binding:"required,gt=0"`
	Quantity          int     `json:"quantity" binding:"required,gt=0"`
	SplitGroupID      string  `json:"split_group_id"`
	AllocationPercent float64 `json:"allocation_percent"`
	IsParallel        bool    `json:"is_parallel"`
	BatchSequence     int     `json:"batch_sequence"`
	PrepMins          int     `json:"prep_mins"`
	ProcessingMins    int     `json:"processing_mins"`
	CleaningMins      int     `json:"cleaning_mins"`
	BufferMins        int     `json:"buffer_mins"`
}

type UpdateJobRequest struct {
	QuantityTotal *int         `json:"quantity_total"`
	Priority      *JobPriority `json:"priority" binding:"omitempty,oneof=low medium high urgent" enums:"low,medium,high,urgent"`
	Deadline      *time.Time   `json:"deadline"`
	Status        *JobStatus   `json:"status" binding:"omitempty,oneof=planned scheduled running blocked paused completed cancelled" enums:"planned,scheduled,running,blocked,paused,completed,cancelled"`
	Notes         *string      `json:"notes"`
}

type UpdateSlotRequest struct {
	MachineID         *string    `json:"machine_id"`
	ScheduledStart    *time.Time `json:"scheduled_start"`
	ScheduledEnd      *time.Time `json:"scheduled_end"`
	QuantityPlanned   *int       `json:"quantity_planned"`
	AllocationPercent *float64   `json:"allocation_percent"`
	IsParallel        *bool      `json:"is_parallel"`
	BatchSequence     *int       `json:"batch_sequence"`
	// Production / execution (Gap 2 - Start, Pause, Resume, Complete)
	ActualStart *time.Time  `json:"actual_start"`
	ActualEnd   *time.Time  `json:"actual_end"`
	Status      *SlotStatus `json:"status" binding:"omitempty,oneof=planned running paused completed cancelled" enums:"planned,running,paused,completed,cancelled"`
}

type JobResponse struct {
	JobID             string            `json:"job_id"`
	ProductID         string            `json:"product_id"`
	QuantityTotal     int               `json:"quantity_total"`
	QuantityCompleted int               `json:"quantity_completed"`
	Priority          string            `json:"priority"`
	Deadline          time.Time         `json:"deadline"`
	Status            string            `json:"status"`
	CreatedAt         time.Time         `json:"created_at"`
	UpdatedAt         time.Time         `json:"updated_at"`
	Notes             string            `json:"notes"`
	Steps             []JobStepResponse `json:"steps,omitempty"`
	Slots             []SlotResponse    `json:"slots,omitempty"`
}

type JobStepResponse struct {
	JobStepID         string `json:"job_step_id"`
	JobID             string `json:"job_id"`
	StepID            string `json:"step_id"`
	StepSequence      int    `json:"step_sequence"`
	QuantityTarget    int    `json:"quantity_target"`
	QuantityCompleted int    `json:"quantity_completed"`
	Status            string `json:"status"`
}

type SlotResponse struct {
	SlotID          string     `json:"slot_id"`
	JobStepID       string     `json:"job_step_id"`
	MachineID       string     `json:"machine_id"`
	ScheduledStart  time.Time  `json:"scheduled_start"`
	ScheduledEnd    time.Time  `json:"scheduled_end"`
	QuantityPlanned int        `json:"quantity_planned"`
	Status          string     `json:"status"`
	ActualStart     *time.Time `json:"actual_start,omitempty"`
	ActualEnd       *time.Time `json:"actual_end,omitempty"`
}

// --- Create job steps from routing ---
type CreateJobStepsRequest struct {
	JobID string `json:"job_id" binding:"required"`
}

// --- Split step request ---
type SplitStepRequest struct {
	JobStepID string              `json:"job_step_id" binding:"required"`
	Splits    []CreateSlotRequest `json:"splits" binding:"required"`
}

// --- Machine DTOs ---
type CreateMachineRequest struct {
	MachineID               string `json:"machine_id"` // Optional; generated with M- prefix when omitted.
	MachineName             string `json:"machine_name" binding:"required"`
	MachineType             string `json:"machine_type" binding:"required"`
	Location                string `json:"location"`
	CapacityPerHour         int    `json:"capacity_per_hour"`
	DefaultSetupTime        int    `json:"default_setup_time"`
	DefaultCleaningTime     int    `json:"default_cleaning_time"`
	DefaultChangeoverTime   int    `json:"default_changeover_time"`
	MaintenanceIntervalDays int    `json:"maintenance_interval_days"`
}

// --- Scheduling events ---
type SchedulingEventRequest struct {
	Type    string `json:"type" binding:"required"`
	Payload string `json:"payload" binding:"required"`
}

// --- Reference / lookup DTOs ---
type CreateMachineTypeRequest struct {
	Name        string `json:"name" binding:"required"`
	Description string `json:"description"`
}

type UpdateMachineTypeRequest struct {
	Name        *string `json:"name"`
	Description *string `json:"description"`
}

type CreateProductTypeRequest struct {
	Name string `json:"name" binding:"required"`
}

type CreateLocationRequest struct {
	Zone string  `json:"zone" binding:"required"`
	Bay  *string `json:"bay"`
}

type CreateStorageLocationRequest struct {
	Name string `json:"name" binding:"required"`
	Type string `json:"type"`
}

type CreateStepTypeRequest struct {
	Name               string  `json:"name" binding:"required"`
	DefaultMachineType *string `json:"default_machine_type"`
}

type UpdateMachineRequest struct {
	MachineName             *string        `json:"machine_name"`
	MachineType             *string        `json:"machine_type"`
	Location                *string        `json:"location"`
	Status                  *MachineStatus `json:"status" binding:"omitempty,oneof=idle running maintenance offline" enums:"idle,running,maintenance,offline"`
	CapacityPerHour         *int           `json:"capacity_per_hour"`
	DefaultSetupTime        *int           `json:"default_setup_time"`
	DefaultCleaningTime     *int           `json:"default_cleaning_time"`
	DefaultChangeoverTime   *int           `json:"default_changeover_time"`
	MaintenanceIntervalDays *int           `json:"maintenance_interval_days"`
}

type AssignCapabilityRequest struct {
	StepID           string  `json:"step_id" binding:"required"`
	EfficiencyFactor float64 `json:"efficiency_factor"`
}

type RecordDowntimeRequest struct {
	MachineID     string    `json:"machine_id" binding:"required"`
	JobStepSlotID string    `json:"job_step_slot_id"`
	Cause         string    `json:"cause"`
	StartTime     time.Time `json:"start_time"`
	EndTime       time.Time `json:"end_time"`
}

// --- Product DTOs ---
type CreateProductRequest struct {
	ProductID     string `json:"product_id"` // Optional; generated with P- prefix when omitted.
	ProductName   string `json:"product_name" binding:"required"`
	Description   string `json:"description"`
	UnitOfMeasure string `json:"unit_of_measure"`
	ProductType   string `json:"product_type"`
	FormulaID     string `json:"formula_id"`
	ProcessID     string `json:"process_id"`
}

type ProductIDOnly struct {
	ProductID string `json:"product_id"`
}

type LinkProductRequest struct {
	FormulaID string    `json:"formula_id"`
	BOMItems  []BOMItem `json:"bom_items"`
	ProcessID string    `json:"process_id"`
}

type BOMItem struct {
	MaterialID       string  `json:"material_id"`       // required if product_id not set
	ProductID        string  `json:"product_id"`        // sub-product, required if material_id not set
	QuantityPerUnit  float64 `json:"quantity_per_unit"` // required; qty per 1 unit of parent
	QuantityRequired float64 `json:"quantity_required"` // backward compat
	Unit             string  `json:"unit"`
	ScrapRate        float64 `json:"scrap_rate"`
}

// --- Inventory DTOs ---
type CreateMaterialRequest struct {
	MaterialID      string  `json:"material_id"` // Optional; generated with MAT- prefix when omitted.
	MaterialName    string  `json:"material_name" binding:"required"`
	Unit            string  `json:"unit"`
	CurrentStock    float64 `json:"current_stock"`
	MinStock        float64 `json:"min_stock"`
	ReorderLevel    float64 `json:"reorder_level"`
	StorageLocation string  `json:"storage_location"`
}

type ConsumeMaterialRequest struct {
	MaterialID     string  `json:"material_id" binding:"required"`
	Quantity       float64 `json:"quantity" binding:"required,gt=0"`
	ReferenceJobID string  `json:"reference_job_id"`
	SlotID         string  `json:"slot_id"`
}

type ReceiveMaterialRequest struct {
	MaterialID string  `json:"material_id" binding:"required"`
	Quantity   float64 `json:"quantity" binding:"required,gt=0"`
}

type ScheduleExpectedArrivalRequest struct {
	MaterialID       string    `json:"material_id" binding:"required"`
	Quantity         float64   `json:"quantity" binding:"required,gt=0"`
	ExpectedArriveAt time.Time `json:"expected_arrive_at" binding:"required"`
	Notes            string    `json:"notes"`
}

type CreateProductInventoryRequest struct {
	ProductID        string                 `json:"product_id" binding:"required"`
	QuantityOnHand   float64                `json:"quantity_on_hand" binding:"required,gte=0"`
	QuantityReserved float64                `json:"quantity_reserved"`
	Status           ProductInventoryStatus `json:"status" binding:"omitempty,oneof=available reserved blocked planned" enums:"available,reserved,blocked,planned"`
	StorageLocation  string                 `json:"storage_location"`
	AvailableFrom    time.Time              `json:"available_from"`
}

type CreateInventoryReservationRequest struct {
	MaterialID  string    `json:"material_id" binding:"required"`
	JobID       string    `json:"job_id"`
	JobStepID   string    `json:"job_step_id"`
	ReservedQty float64   `json:"reserved_qty" binding:"required,gt=0"`
	NeededAt    time.Time `json:"needed_at"`
}

// --- Production Log DTOs ---
type LogProductionRequest struct {
	SlotID           string    `json:"slot_id" binding:"required"`
	StartTime        time.Time `json:"start_time"`
	EndTime          time.Time `json:"end_time"`
	QuantityProduced int       `json:"quantity_produced"`
	QuantityScrap    int       `json:"quantity_scrap"`
	OperatorNotes    string    `json:"operator_notes"`
	DowntimeMinutes  *int      `json:"downtime_minutes"` // Gap 7 - downtime during slot for OEE
}

// --- Quality DTOs ---
type RecordInspectionRequest struct {
	JobStepID     string `json:"job_step_id" binding:"required"`
	InspectorName string `json:"inspector_name"`
	Result        string `json:"result"` // pass, fail
	DefectCount   int    `json:"defect_count"`
	Notes         string `json:"notes"`
}

// --- Process DTOs ---
type CreateProcessRequest struct {
	ProcessID   string `json:"process_id"` // Optional; generated with PRC- prefix when omitted.
	ProductID   string `json:"product_id" binding:"required"`
	ProcessName string `json:"process_name" binding:"required"`
	Version     int    `json:"version"`
	Description string `json:"description"`
}

// AddProcessStepMaterialRequest - add material/product to a process step
type AddProcessStepMaterialRequest struct {
	MaterialID      string  `json:"material_id"`       // required if product_id not set
	ProductID       string  `json:"product_id"`        // required if material_id not set
	Role            string  `json:"role"`              // "input" or "output"
	QuantityPerUnit float64 `json:"quantity_per_unit"` // required
	Unit            string  `json:"unit"`
}

type CreateProcessStepRequest struct {
	StepID                 string `json:"step_id"`
	StepSequence           int    `json:"step_sequence"`
	StepName               string `json:"step_name" binding:"required"`
	StepType               string `json:"step_type"`
	MachineTypeRequired    string `json:"machine_type_required"`
	DefaultPreparationTime int    `json:"default_preparation_time"`
	DefaultProcessingTime  int    `json:"default_processing_time"`
	DefaultCleaningTime    int    `json:"default_cleaning_time"`
	DefaultChangeoverTime  int    `json:"default_changeover_time"`
	AllowParallelExecution bool   `json:"allow_parallel_execution"`
	MaxParallelMachines    int    `json:"max_parallel_machines"`
	MinSplitQty            int    `json:"min_split_qty"`
	TransferBatchSize      int    `json:"transfer_batch_size"`
	QualityCheckRequired   bool   `json:"quality_check_required"`
	Notes                  string `json:"notes"`
}

// --- Formula DTOs ---
type CreateFormulaRequest struct {
	FormulaID    string `json:"formula_id"` // Optional; generated with F- prefix when omitted.
	FormulaName  string `json:"formula_name" binding:"required"`
	Version      int    `json:"version"`
	Instructions string `json:"instructions"`
	SafetyNotes  string `json:"safety_notes"`
}

type AddFormulaIngredientRequest struct {
	MaterialID      string  `json:"material_id"`       // required if product_id not set
	ProductID       string  `json:"product_id"`        // required if material_id not set (sub-product)
	QuantityPerUnit float64 `json:"quantity_per_unit"` // required; qty per 1 unit of parent
	Quantity        float64 `json:"quantity"`          // backward compat, maps to quantity_per_unit
	Unit            string  `json:"unit"`
	ScrapRate       float64 `json:"scrap_rate"` // 0-1
	Percentage      float64 `json:"percentage"`
}

// --- Scheduling DTOs ---
type SchedulingExplosionRequest struct {
	ProductID string  `json:"product_id" binding:"required"`
	Quantity  float64 `json:"quantity" binding:"required,gt=0"`
}

type SchedulingReadinessRequest struct {
	ProductID string  `json:"product_id" binding:"required"`
	Quantity  float64 `json:"quantity" binding:"required,gt=0"`
}

type SchedulingSlotValidationRequest struct {
	JobStepID      string    `json:"job_step_id" binding:"required"`
	MachineID      string    `json:"machine_id" binding:"required"`
	ScheduledStart time.Time `json:"scheduled_start" binding:"required"`
	ScheduledEnd   time.Time `json:"scheduled_end" binding:"required"`
	Quantity       int       `json:"quantity" binding:"required,gt=0"`
	ExcludeSlotID  string    `json:"exclude_slot_id"`
}

type ProposalDecisionRequest struct {
	Notes                   string `json:"notes"`
	Reason                  string `json:"reason"`
	IdempotencyKey          string `json:"idempotency_key"`
	SkipStalenessCheck      bool   `json:"skip_staleness_check"` // true when applying from batch (Apply All); proposals 2+ would otherwise fail staleness
	IncludeInventoryActions *bool  `json:"include_inventory_actions,omitempty"`
}

// BatchProposalsRequest for POST /ai/scheduling/batch-proposals
type BatchProposalsRequest struct {
	JobIDs                  []string `json:"job_ids"`  // explicit job IDs; if empty and Scope set, use scope
	Scope                   string   `json:"scope"`    // "all_unscheduled" = all jobs with status planned/scheduled and no active slots
	OrderBy                 string   `json:"order_by"` // "edd" | "epo" | "fifo" (default: "epo")
	IncludeInventoryActions bool     `json:"include_inventory_actions"`
}

// RescheduleAllRequest for POST /ai/scheduling/reschedule-all
type RescheduleAllRequest struct {
	OrderBy string `json:"order_by"` // "edd" | "epo" | "fifo" | "readiness" (default: "epo")
	DryRun  bool   `json:"dry_run"`  // if true: preview only, no cancel/delete/persist; returns proposals without side effects
}

// VerifyOverlapsRequest for POST /ai/scheduling/verify-overlaps
type VerifyOverlapsRequest struct {
	ProposalIDs []string                 `json:"proposal_ids"` // fetch proposals from DB (scope=proposals)
	Proposals   []VerifyOverlapsProposal `json:"proposals"`    // or pass inline (e.g. data.proposals from batch-proposals)
	Scope       string                   `json:"scope"`        // "proposals" (default) | "applied" - verify proposals vs applied slots
	JobIDs      []string                 `json:"job_ids"`      // optional when scope=applied; if empty, check all jobs with active slots
}

// VerifyOverlapsProposal is one proposal with slots (matches batch-proposals item)
type VerifyOverlapsProposal struct {
	ProposalID    string               `json:"proposal_id"`
	JobID         string               `json:"job_id"`
	ProposedSlots []VerifyOverlapsSlot `json:"proposed_slots"`
}

// VerifyOverlapsSlot is a slot with machine and time range
type VerifyOverlapsSlot struct {
	JobStepID      string    `json:"job_step_id"`
	MachineID      string    `json:"machine_id"`
	ScheduledStart time.Time `json:"scheduled_start"`
	ScheduledEnd   time.Time `json:"scheduled_end"`
}

type InventorySnapshotInput struct {
	MaterialID string    `json:"material_id" binding:"required"`
	Version    string    `json:"version" binding:"required"`
	ComputedAt time.Time `json:"computed_at"`
}

type ReplenishmentArrivalItem struct {
	// OptionType: omit or "replenish" (default) = material expected arrival. Other values are ignored by material apply.
	OptionType        string                  `json:"option_type,omitempty"`
	MaterialID        string                  `json:"material_id" binding:"required"`
	Quantity          float64                 `json:"quantity" binding:"required,gt=0"`
	ArriveAt          time.Time               `json:"arrive_at" binding:"required"`
	Notes             string                  `json:"notes"`
	InventorySnapshot *InventorySnapshotInput `json:"inventory_snapshot,omitempty"`
}

type ApplyReplenishmentRequest struct {
	Suggestions []ReplenishmentArrivalItem `json:"suggestions" binding:"required,min=1"`
}

// ApplyReplenishmentBatchRequest is for POST /ai/scheduling/apply-replenishment-batch (no proposal id).
// Send either "suggestions" or "arrivals" (same item shape as per-proposal apply-replenishment).
type ApplyReplenishmentBatchRequest struct {
	Suggestions []ReplenishmentArrivalItem `json:"suggestions"`
	Arrivals    []ReplenishmentArrivalItem `json:"arrivals"`
}

type ReplenishAndReplanRequest struct {
	Arrivals            []ReplenishmentArrivalItem `json:"arrivals" binding:"required,min=1"`
	Attempt             int                        `json:"attempt"`
	PreviousDeficits    map[string]float64         `json:"previous_deficits"`
	PreviousGlobalScore float64                    `json:"previous_global_score"`
	AllowPartial        bool                       `json:"allow_partial"`
}

// --- Maintenance DTOs ---
type RecordMaintenanceRequest struct {
	MachineID       string    `json:"machine_id" binding:"required"`
	MaintenanceType string    `json:"maintenance_type"`
	Technician      string    `json:"technician"`
	Description     string    `json:"description"`
	StartTime       time.Time `json:"start_time"`
	EndTime         time.Time `json:"end_time"`
}
