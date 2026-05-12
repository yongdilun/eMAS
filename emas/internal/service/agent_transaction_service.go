package service

import (
	"errors"
	"fmt"
	"strings"
	"time"

	"emas/internal/domain"
	"emas/pkg/id"

	"gorm.io/gorm"
)

type AgentStagedWrite struct {
	IntentID        string                 `json:"intent_id,omitempty"`
	DecisionID      string                 `json:"decision_id,omitempty"`
	ToolCallID      string                 `json:"tool_call_id,omitempty"`
	ToolName        string                 `json:"tool_name"`
	Args            map[string]interface{} `json:"args"`
	OutputRef       string                 `json:"output_ref,omitempty"`
	WriteGeneration int                    `json:"write_generation,omitempty"`
	IdempotencyKey  string                 `json:"idempotency_key,omitempty"`
	Status          string                 `json:"status,omitempty"`
}

type AgentTransactionRequest struct {
	StagedWrites         []AgentStagedWrite `json:"staged_writes"`
	BundleIdempotencyKey string             `json:"bundle_idempotency_key,omitempty"`
}

type AgentTransactionOperationResult struct {
	Index          int                    `json:"index"`
	ToolName       string                 `json:"tool_name"`
	OutputRef      string                 `json:"output_ref,omitempty"`
	IdempotencyKey string                 `json:"idempotency_key,omitempty"`
	Status         string                 `json:"status"`
	PrimaryID      string                 `json:"primary_id,omitempty"`
	Data           map[string]interface{} `json:"data,omitempty"`
}

type AgentTransactionResult struct {
	DryRun     bool                              `json:"dry_run"`
	Committed  bool                              `json:"committed"`
	Operations []AgentTransactionOperationResult `json:"operations"`
}

type AgentTransactionError struct {
	StatusCode int
	Message    string
}

func (e *AgentTransactionError) Error() string { return e.Message }

type AgentTransactionService struct {
	db *gorm.DB
}

func NewAgentTransactionService(db *gorm.DB) *AgentTransactionService {
	return &AgentTransactionService{db: db}
}

var errAgentDryRunRollback = errors.New("agent transaction dry-run rollback")

func (s *AgentTransactionService) DryRun(req AgentTransactionRequest) (*AgentTransactionResult, error) {
	if err := validateTransactionRequest(req, false); err != nil {
		return nil, err
	}
	var result *AgentTransactionResult
	err := s.db.Transaction(func(tx *gorm.DB) error {
		var applyErr error
		result, applyErr = s.apply(tx, req, true)
		if applyErr != nil {
			return applyErr
		}
		return errAgentDryRunRollback
	})
	if errors.Is(err, errAgentDryRunRollback) {
		return result, nil
	}
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (s *AgentTransactionService) Commit(req AgentTransactionRequest, bundleKey string) (*AgentTransactionResult, error) {
	req.BundleIdempotencyKey = strings.TrimSpace(firstNonEmpty(bundleKey, req.BundleIdempotencyKey))
	if err := validateTransactionRequest(req, true); err != nil {
		return nil, err
	}
	var result *AgentTransactionResult
	err := s.db.Transaction(func(tx *gorm.DB) error {
		var applyErr error
		result, applyErr = s.apply(tx, req, false)
		return applyErr
	})
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (s *AgentTransactionService) apply(tx *gorm.DB, req AgentTransactionRequest, dryRun bool) (*AgentTransactionResult, error) {
	refs := map[string]string{}
	out := &AgentTransactionResult{DryRun: dryRun, Committed: !dryRun}
	for i, op := range req.StagedWrites {
		rawArgs := op.Args
		if rawArgs == nil {
			rawArgs = map[string]interface{}{}
		}
		args := resolveAgentRefs(rawArgs, refs).(map[string]interface{})
		if unresolved := findUnresolvedAgentRef(args); unresolved != "" {
			return nil, &AgentTransactionError{StatusCode: 400, Message: "unknown transaction ref: " + unresolved}
		}
		primaryID, data, err := applyAgentOperation(tx, op.ToolName, args)
		if err != nil {
			return nil, err
		}
		if strings.TrimSpace(op.OutputRef) != "" {
			refs[op.OutputRef] = primaryID
		}
		out.Operations = append(out.Operations, AgentTransactionOperationResult{
			Index:          i,
			ToolName:       op.ToolName,
			OutputRef:      op.OutputRef,
			IdempotencyKey: op.IdempotencyKey,
			Status:         "validated",
			PrimaryID:      primaryID,
			Data:           data,
		})
	}
	if !dryRun {
		for i := range out.Operations {
			out.Operations[i].Status = "committed"
		}
	}
	return out, nil
}

func validateTransactionRequest(req AgentTransactionRequest, commit bool) error {
	if len(req.StagedWrites) == 0 {
		return &AgentTransactionError{StatusCode: 400, Message: "staged_writes must contain at least one operation"}
	}
	if commit && strings.TrimSpace(req.BundleIdempotencyKey) == "" {
		return &AgentTransactionError{StatusCode: 400, Message: "bundle idempotency key is required"}
	}
	seenKeys := map[string]bool{}
	seenRefs := map[string]bool{}
	for i, op := range req.StagedWrites {
		if strings.TrimSpace(op.ToolName) == "" {
			return &AgentTransactionError{StatusCode: 400, Message: fmt.Sprintf("staged_writes[%d].tool_name is required", i)}
		}
		if commit {
			key := strings.TrimSpace(op.IdempotencyKey)
			if key == "" {
				return &AgentTransactionError{StatusCode: 400, Message: fmt.Sprintf("staged_writes[%d].idempotency_key is required", i)}
			}
			if seenKeys[key] {
				return &AgentTransactionError{StatusCode: 409, Message: fmt.Sprintf("duplicate idempotency key in bundle: %s", key)}
			}
			seenKeys[key] = true
		}
		ref := strings.TrimSpace(op.OutputRef)
		if ref == "" {
			continue
		}
		if seenRefs[ref] {
			return &AgentTransactionError{StatusCode: 409, Message: fmt.Sprintf("duplicate output_ref in bundle: %s", ref)}
		}
		seenRefs[ref] = true
	}
	return nil
}

func applyAgentOperation(tx *gorm.DB, toolName string, args map[string]interface{}) (string, map[string]interface{}, error) {
	switch strings.ToLower(strings.TrimSpace(toolName)) {
	case "post__machines":
		return applyCreateMachine(tx, args)
	case "put__machines_{id}", "patch__machines_{id}":
		return applyUpdateMachine(tx, args)
	case "delete__machines_{id}":
		return applyDeleteMachine(tx, args)
	case "post__jobs":
		return applyCreateJob(tx, args)
	case "put__jobs_{id}", "patch__jobs_{id}":
		return applyUpdateJob(tx, args)
	case "delete__jobs_{id}":
		return applyDeleteJob(tx, args)
	case "put__slots_{id}", "patch__slots_{id}":
		return applyUpdateSlot(tx, args)
	case "delete__slots_{id}":
		return applyCancelSlot(tx, args)
	case "post__machines_{id}_capabilities":
		return applyAssignMachineCapability(tx, args)
	case "post__machines_downtime":
		return applyRecordMachineDowntime(tx, args)
	case "post__maintenance":
		return applyRecordMaintenance(tx, args)
	case "post__quality_inspections":
		return applyRecordQualityInspection(tx, args)
	case "post__products":
		return applyCreateProduct(tx, args)
	case "post__inventory_materials":
		return applyCreateMaterial(tx, args)
	case "post__inventory_receive":
		return applyReceiveMaterial(tx, args)
	case "post__inventory_consume":
		return applyConsumeMaterial(tx, args)
	case "post__inventory_expected-arrivals":
		return applyExpectedArrival(tx, args)
	case "post__inventory_product-stock":
		return applyProductInventory(tx, args)
	case "post__inventory_reservations":
		return applyInventoryReservation(tx, args)
	default:
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "unsupported transaction tool: " + toolName}
	}
}

func applyCreateMachine(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	machineID := stringArg(args, "machine_id")
	if machineID == "" {
		machineID = id.NewPrefixed(id.PrefixMachine)
	}
	if exists(tx, &domain.Machine{}, "machine_id = ?", machineID) {
		return "", nil, &AgentTransactionError{StatusCode: 409, Message: "machine already exists: " + machineID}
	}
	name := stringArg(args, "machine_name")
	machineType := stringArg(args, "machine_type")
	if name == "" || machineType == "" {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "machine_name and machine_type are required"}
	}
	status := stringArg(args, "status")
	if status == "" {
		status = domain.MachineStatusIdle
	}
	if !validMachineStatus(status) {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "invalid machine status: " + status}
	}
	m := &domain.Machine{
		MachineID:               machineID,
		MachineName:             name,
		MachineType:             machineType,
		Location:                stringArg(args, "location"),
		Status:                  status,
		CapacityPerHour:         intArg(args, "capacity_per_hour"),
		DefaultSetupTime:        intArg(args, "default_setup_time"),
		DefaultCleaningTime:     intArg(args, "default_cleaning_time"),
		DefaultChangeoverTime:   intArg(args, "default_changeover_time"),
		MaintenanceIntervalDays: intArg(args, "maintenance_interval_days"),
	}
	if err := tx.Create(m).Error; err != nil {
		return "", nil, err
	}
	return machineID, map[string]interface{}{"machine_id": machineID}, nil
}

func applyUpdateMachine(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	machineID := firstNonEmpty(stringArg(args, "id"), stringArg(args, "machine_id"))
	if machineID == "" {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "id is required"}
	}
	var m domain.Machine
	if err := tx.Where("machine_id = ?", machineID).First(&m).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return "", nil, &AgentTransactionError{StatusCode: 404, Message: "machine not found: " + machineID}
		}
		return "", nil, err
	}
	if v := stringArg(args, "machine_name"); v != "" {
		m.MachineName = v
	}
	if v := stringArg(args, "machine_type"); v != "" {
		m.MachineType = v
	}
	if v := stringArg(args, "location"); v != "" {
		m.Location = v
	}
	if v := stringArg(args, "status"); v != "" {
		if !validMachineStatus(v) {
			return "", nil, &AgentTransactionError{StatusCode: 400, Message: "invalid machine status: " + v}
		}
		m.Status = v
	}
	if _, ok := args["capacity_per_hour"]; ok {
		m.CapacityPerHour = intArg(args, "capacity_per_hour")
	}
	if err := tx.Save(&m).Error; err != nil {
		return "", nil, err
	}
	return machineID, map[string]interface{}{"machine_id": machineID}, nil
}

func applyDeleteMachine(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	machineID := firstNonEmpty(stringArg(args, "id"), stringArg(args, "machine_id"))
	if machineID == "" {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "id is required"}
	}
	res := tx.Where("machine_id = ?", machineID).Delete(&domain.Machine{})
	if res.Error != nil {
		return "", nil, res.Error
	}
	if res.RowsAffected == 0 {
		return "", nil, &AgentTransactionError{StatusCode: 404, Message: "machine not found: " + machineID}
	}
	return machineID, map[string]interface{}{"machine_id": machineID}, nil
}

func applyCreateJob(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	productID := stringArg(args, "product_id")
	quantity := intArg(args, "quantity_total")
	if productID == "" || quantity <= 0 {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "product_id and positive quantity_total are required"}
	}
	if !exists(tx, &domain.Product{}, "product_id = ?", productID) {
		return "", nil, &AgentTransactionError{StatusCode: 404, Message: "product not found: " + productID}
	}
	deadline := time.Now().Add(24 * time.Hour)
	if raw := stringArg(args, "deadline"); raw != "" {
		parsed, err := time.Parse(time.RFC3339, raw)
		if err != nil {
			return "", nil, &AgentTransactionError{StatusCode: 400, Message: "deadline must be RFC3339"}
		}
		deadline = parsed
	}
	priority := stringArg(args, "priority")
	if priority == "" {
		priority = domain.JobPriorityMedium
	}
	jobID := id.NewPrefixed(id.PrefixJob)
	job := &domain.Job{
		JobID:         jobID,
		ProductID:     productID,
		QuantityTotal: quantity,
		Priority:      priority,
		Deadline:      deadline,
		Status:        domain.JobStatusPlanned,
		CreatedAt:     time.Now(),
		UpdatedAt:     time.Now(),
		Notes:         stringArg(args, "notes"),
	}
	if err := tx.Create(job).Error; err != nil {
		return "", nil, err
	}
	return jobID, map[string]interface{}{"job_id": jobID}, nil
}

func applyUpdateJob(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	jobID := firstNonEmpty(stringArg(args, "id"), stringArg(args, "job_id"))
	if jobID == "" {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "id is required"}
	}
	var job domain.Job
	if err := tx.Where("job_id = ?", jobID).First(&job).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return "", nil, &AgentTransactionError{StatusCode: 404, Message: "job not found: " + jobID}
		}
		return "", nil, err
	}
	if _, ok := args["quantity_total"]; ok {
		q := intArg(args, "quantity_total")
		if q <= 0 {
			return "", nil, &AgentTransactionError{StatusCode: 400, Message: "quantity_total must be positive"}
		}
		job.QuantityTotal = q
	}
	if v := stringArg(args, "priority"); v != "" {
		if !validJobPriority(v) {
			return "", nil, &AgentTransactionError{StatusCode: 400, Message: "invalid job priority: " + v}
		}
		job.Priority = v
	}
	if v := stringArg(args, "deadline"); v != "" {
		t, err := parseAgentTime(v)
		if err != nil {
			return "", nil, &AgentTransactionError{StatusCode: 400, Message: "deadline must be RFC3339"}
		}
		job.Deadline = t
	}
	if v := stringArg(args, "status"); v != "" {
		if !validJobStatus(v) {
			return "", nil, &AgentTransactionError{StatusCode: 400, Message: "invalid job status: " + v}
		}
		job.Status = v
	}
	if _, ok := args["notes"]; ok {
		job.Notes = stringArg(args, "notes")
	}
	job.UpdatedAt = time.Now()
	if err := tx.Save(&job).Error; err != nil {
		return "", nil, err
	}
	return jobID, map[string]interface{}{"job_id": jobID}, nil
}

func applyDeleteJob(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	jobID := firstNonEmpty(stringArg(args, "id"), stringArg(args, "job_id"))
	if jobID == "" {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "id is required"}
	}
	if !exists(tx, &domain.Job{}, "job_id = ?", jobID) {
		return "", nil, &AgentTransactionError{StatusCode: 404, Message: "job not found: " + jobID}
	}
	var steps []domain.JobSteps
	if err := tx.Where("job_id = ?", jobID).Find(&steps).Error; err != nil {
		return "", nil, err
	}
	for _, step := range steps {
		if err := tx.Where("job_step_id = ?", step.JobStepID).Delete(&domain.JobStepScheduleSlots{}).Error; err != nil {
			return "", nil, err
		}
	}
	if err := tx.Where("job_id = ?", jobID).Delete(&domain.JobSteps{}).Error; err != nil {
		return "", nil, err
	}
	if err := tx.Where("job_id = ?", jobID).Delete(&domain.Job{}).Error; err != nil {
		return "", nil, err
	}
	return jobID, map[string]interface{}{"job_id": jobID}, nil
}

func applyUpdateSlot(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	slotID := firstNonEmpty(stringArg(args, "id"), stringArg(args, "slot_id"))
	if slotID == "" {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "id is required"}
	}
	var slot domain.JobStepScheduleSlots
	if err := tx.Where("slot_id = ?", slotID).First(&slot).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return "", nil, &AgentTransactionError{StatusCode: 404, Message: "slot not found: " + slotID}
		}
		return "", nil, err
	}
	if v := stringArg(args, "machine_id"); v != "" {
		if !exists(tx, &domain.Machine{}, "machine_id = ?", v) {
			return "", nil, &AgentTransactionError{StatusCode: 404, Message: "machine not found: " + v}
		}
		slot.MachineID = v
	}
	if v := stringArg(args, "scheduled_start"); v != "" {
		t, err := parseAgentTime(v)
		if err != nil {
			return "", nil, &AgentTransactionError{StatusCode: 400, Message: "scheduled_start must be RFC3339"}
		}
		slot.ScheduledStart = t
	}
	if v := stringArg(args, "scheduled_end"); v != "" {
		t, err := parseAgentTime(v)
		if err != nil {
			return "", nil, &AgentTransactionError{StatusCode: 400, Message: "scheduled_end must be RFC3339"}
		}
		slot.ScheduledEnd = t
	}
	if _, ok := args["quantity_planned"]; ok {
		q := intArg(args, "quantity_planned")
		if q <= 0 {
			return "", nil, &AgentTransactionError{StatusCode: 400, Message: "quantity_planned must be positive"}
		}
		slot.QuantityPlanned = q
	}
	if _, ok := args["allocation_percent"]; ok {
		slot.AllocationPercent = floatArg(args, "allocation_percent")
	}
	if _, ok := args["is_parallel"]; ok {
		slot.IsParallel = boolArg(args, "is_parallel")
	}
	if _, ok := args["batch_sequence"]; ok {
		slot.BatchSequence = intArg(args, "batch_sequence")
	}
	if v := stringArg(args, "status"); v != "" {
		if !validSlotStatus(v) {
			return "", nil, &AgentTransactionError{StatusCode: 400, Message: "invalid slot status: " + v}
		}
		slot.Status = v
	}
	if v := stringArg(args, "actual_start"); v != "" {
		t, err := parseAgentTime(v)
		if err != nil {
			return "", nil, &AgentTransactionError{StatusCode: 400, Message: "actual_start must be RFC3339"}
		}
		slot.ActualStart = &t
	}
	if v := stringArg(args, "actual_end"); v != "" {
		t, err := parseAgentTime(v)
		if err != nil {
			return "", nil, &AgentTransactionError{StatusCode: 400, Message: "actual_end must be RFC3339"}
		}
		slot.ActualEnd = &t
	}
	if err := tx.Save(&slot).Error; err != nil {
		return "", nil, err
	}
	return slotID, map[string]interface{}{"slot_id": slotID}, nil
}

func applyCancelSlot(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	slotID := firstNonEmpty(stringArg(args, "id"), stringArg(args, "slot_id"))
	if slotID == "" {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "id is required"}
	}
	res := tx.Model(&domain.JobStepScheduleSlots{}).Where("slot_id = ?", slotID).Update("status", domain.SlotStatusCancelled)
	if res.Error != nil {
		return "", nil, res.Error
	}
	if res.RowsAffected == 0 {
		return "", nil, &AgentTransactionError{StatusCode: 404, Message: "slot not found: " + slotID}
	}
	return slotID, map[string]interface{}{"slot_id": slotID}, nil
}

func applyAssignMachineCapability(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	machineID := firstNonEmpty(stringArg(args, "id"), stringArg(args, "machine_id"))
	stepID := stringArg(args, "step_id")
	if machineID == "" || stepID == "" {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "machine id and step_id are required"}
	}
	if !exists(tx, &domain.Machine{}, "machine_id = ?", machineID) {
		return "", nil, &AgentTransactionError{StatusCode: 404, Message: "machine not found: " + machineID}
	}
	efficiency := floatArg(args, "efficiency_factor")
	if efficiency <= 0 {
		efficiency = 1
	}
	capabilityID := id.NewPrefixed("CAP-")
	capability := &domain.MachineCapabilities{
		CapabilityID:     capabilityID,
		MachineID:        machineID,
		StepID:           stepID,
		EfficiencyFactor: efficiency,
	}
	if err := tx.Create(capability).Error; err != nil {
		return "", nil, err
	}
	return capabilityID, map[string]interface{}{"capability_id": capabilityID}, nil
}

func applyRecordMachineDowntime(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	machineID := stringArg(args, "machine_id")
	if machineID == "" {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "machine_id is required"}
	}
	if !exists(tx, &domain.Machine{}, "machine_id = ?", machineID) {
		return "", nil, &AgentTransactionError{StatusCode: 404, Message: "machine not found: " + machineID}
	}
	start, end, err := startEndArgs(args)
	if err != nil {
		return "", nil, err
	}
	downtimeID := id.NewPrefixed("DT-")
	record := &domain.MachineDowntime{
		DowntimeID:      downtimeID,
		MachineID:       machineID,
		JobStepSlotID:   stringArg(args, "job_step_slot_id"),
		Cause:           stringArg(args, "cause"),
		StartTime:       start,
		EndTime:         end,
		DurationMinutes: int(end.Sub(start).Minutes()),
	}
	if err := tx.Create(record).Error; err != nil {
		return "", nil, err
	}
	return downtimeID, map[string]interface{}{"downtime_id": downtimeID}, nil
}

func applyRecordMaintenance(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	machineID := stringArg(args, "machine_id")
	if machineID == "" {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "machine_id is required"}
	}
	if !exists(tx, &domain.Machine{}, "machine_id = ?", machineID) {
		return "", nil, &AgentTransactionError{StatusCode: 404, Message: "machine not found: " + machineID}
	}
	start, end, err := startEndArgs(args)
	if err != nil {
		return "", nil, err
	}
	maintenanceType := stringArg(args, "maintenance_type")
	if maintenanceType == "" {
		maintenanceType = domain.MaintenanceTypePreventive
	}
	if maintenanceType != domain.MaintenanceTypePreventive && maintenanceType != domain.MaintenanceTypeCorrective {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "invalid maintenance_type: " + maintenanceType}
	}
	maintenanceID := id.NewPrefixed("MNT-")
	record := &domain.MaintenanceRecords{
		MaintenanceID:   maintenanceID,
		MachineID:       machineID,
		MaintenanceType: maintenanceType,
		StartTime:       start,
		EndTime:         end,
		Technician:      stringArg(args, "technician"),
		Description:     stringArg(args, "description"),
	}
	if err := tx.Create(record).Error; err != nil {
		return "", nil, err
	}
	if err := tx.Model(&domain.Machine{}).Where("machine_id = ?", machineID).Update("last_maintenance_date", end).Error; err != nil {
		return "", nil, err
	}
	return maintenanceID, map[string]interface{}{"maintenance_id": maintenanceID}, nil
}

func applyRecordQualityInspection(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	jobStepID := stringArg(args, "job_step_id")
	if jobStepID == "" {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "job_step_id is required"}
	}
	if !exists(tx, &domain.JobSteps{}, "job_step_id = ?", jobStepID) {
		return "", nil, &AgentTransactionError{StatusCode: 404, Message: "job step not found: " + jobStepID}
	}
	result := stringArg(args, "result")
	if result == "" {
		result = domain.QualityResultPass
	}
	if result != domain.QualityResultPass && result != domain.QualityResultFail {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "invalid quality result: " + result}
	}
	inspectionID := id.NewPrefixed("QC-")
	record := &domain.QualityInspectionRecords{
		InspectionID:   inspectionID,
		JobStepID:      jobStepID,
		InspectionTime: time.Now(),
		InspectorName:  stringArg(args, "inspector_name"),
		Result:         result,
		DefectCount:    intArg(args, "defect_count"),
		Notes:          stringArg(args, "notes"),
	}
	if err := tx.Create(record).Error; err != nil {
		return "", nil, err
	}
	return inspectionID, map[string]interface{}{"inspection_id": inspectionID}, nil
}

func applyCreateProduct(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	productID := stringArg(args, "product_id")
	if productID == "" {
		productID = id.NewPrefixed(id.PrefixProduct)
	}
	if exists(tx, &domain.Product{}, "product_id = ?", productID) {
		return "", nil, &AgentTransactionError{StatusCode: 409, Message: "product already exists: " + productID}
	}
	name := stringArg(args, "product_name")
	if name == "" {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "product_name is required"}
	}
	status := stringArg(args, "status")
	if status == "" {
		status = domain.ProductStatusActive
	}
	if status != domain.ProductStatusActive && status != domain.ProductStatusObsolete {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "invalid product status: " + status}
	}
	product := &domain.Product{
		ProductID:     productID,
		ProductName:   name,
		Description:   stringArg(args, "description"),
		UnitOfMeasure: firstNonEmpty(stringArg(args, "unit_of_measure"), "pcs"),
		ProductType:   stringArg(args, "product_type"),
		Status:        status,
		FormulaID:     stringArg(args, "formula_id"),
		ProcessID:     stringArg(args, "process_id"),
		CreatedAt:     time.Now(),
	}
	if err := tx.Create(product).Error; err != nil {
		return "", nil, err
	}
	return productID, map[string]interface{}{"product_id": productID}, nil
}

func applyCreateMaterial(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	materialID := stringArg(args, "material_id")
	if materialID == "" {
		materialID = id.NewPrefixed(id.PrefixInventory)
	}
	if exists(tx, &domain.InventoryMaterials{}, "material_id = ?", materialID) {
		return "", nil, &AgentTransactionError{StatusCode: 409, Message: "material already exists: " + materialID}
	}
	name := stringArg(args, "material_name")
	if name == "" {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "material_name is required"}
	}
	currentStock := floatArg(args, "current_stock")
	minStock := floatArg(args, "min_stock")
	reorderLevel := floatArg(args, "reorder_level")
	material := &domain.InventoryMaterials{
		MaterialID:      materialID,
		MaterialName:    name,
		Unit:            firstNonEmpty(stringArg(args, "unit"), "pcs"),
		CurrentStock:    currentStock,
		MinStock:        minStock,
		ReorderLevel:    reorderLevel,
		StorageLocation: stringArg(args, "storage_location"),
		Status:          inventoryStatus(currentStock, minStock, reorderLevel),
		LastUpdated:     time.Now(),
	}
	if err := tx.Create(material).Error; err != nil {
		return "", nil, err
	}
	return materialID, map[string]interface{}{"material_id": materialID}, nil
}

func applyReceiveMaterial(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	return applyInventoryMovement(tx, args, domain.TransactionTypeReceive)
}

func applyConsumeMaterial(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	return applyInventoryMovement(tx, args, domain.TransactionTypeConsume)
}

func applyInventoryMovement(tx *gorm.DB, args map[string]interface{}, movementType string) (string, map[string]interface{}, error) {
	materialID := stringArg(args, "material_id")
	quantity := floatArg(args, "quantity")
	if materialID == "" || quantity <= 0 {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "material_id and positive quantity are required"}
	}
	var material domain.InventoryMaterials
	if err := tx.Where("material_id = ?", materialID).First(&material).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return "", nil, &AgentTransactionError{StatusCode: 404, Message: "material not found: " + materialID}
		}
		return "", nil, err
	}
	if movementType == domain.TransactionTypeConsume {
		material.CurrentStock -= quantity
	} else {
		material.CurrentStock += quantity
	}
	material.Status = inventoryStatus(material.CurrentStock, material.MinStock, material.ReorderLevel)
	material.LastUpdated = time.Now()
	if err := tx.Save(&material).Error; err != nil {
		return "", nil, err
	}
	transactionID := id.NewPrefixed("TXN-")
	transaction := &domain.InventoryTransactions{
		TransactionID:   transactionID,
		MaterialID:      materialID,
		TransactionType: movementType,
		Quantity:        quantity,
		ReferenceJobID:  stringArg(args, "reference_job_id"),
		Timestamp:       time.Now(),
		Notes:           stringArg(args, "notes"),
	}
	if err := tx.Create(transaction).Error; err != nil {
		return "", nil, err
	}
	return transactionID, map[string]interface{}{"transaction_id": transactionID, "material_id": materialID}, nil
}

func applyExpectedArrival(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	materialID := stringArg(args, "material_id")
	quantity := floatArg(args, "quantity")
	if materialID == "" || quantity <= 0 {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "material_id and positive quantity are required"}
	}
	if !exists(tx, &domain.InventoryMaterials{}, "material_id = ?", materialID) {
		return "", nil, &AgentTransactionError{StatusCode: 404, Message: "material not found: " + materialID}
	}
	arriveAt, err := parseAgentTime(stringArg(args, "expected_arrive_at"))
	if err != nil {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "expected_arrive_at must be RFC3339"}
	}
	arrivalID := id.NewPrefixed(id.PrefixExpectedArrival)
	arrival := &domain.InventoryExpectedArrival{
		ArrivalID:        arrivalID,
		MaterialID:       materialID,
		Quantity:         quantity,
		ExpectedArriveAt: arriveAt,
		Status:           domain.ExpectedArrivalStatusPending,
		Notes:            stringArg(args, "notes"),
		ReferenceJobID:   stringArg(args, "reference_job_id"),
		CreatedAt:        time.Now(),
	}
	if err := tx.Create(arrival).Error; err != nil {
		return "", nil, err
	}
	return arrivalID, map[string]interface{}{"arrival_id": arrivalID}, nil
}

func applyProductInventory(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	productID := stringArg(args, "product_id")
	qty := floatArg(args, "quantity_on_hand")
	if productID == "" || qty < 0 {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "product_id and non-negative quantity_on_hand are required"}
	}
	if !exists(tx, &domain.Product{}, "product_id = ?", productID) {
		return "", nil, &AgentTransactionError{StatusCode: 404, Message: "product not found: " + productID}
	}
	status := stringArg(args, "status")
	if status == "" {
		status = domain.ProductInventoryStatusAvailable
	}
	if !validProductInventoryStatus(status) {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "invalid product inventory status: " + status}
	}
	availableFrom := time.Now()
	if v := stringArg(args, "available_from"); v != "" {
		t, err := parseAgentTime(v)
		if err != nil {
			return "", nil, &AgentTransactionError{StatusCode: 400, Message: "available_from must be RFC3339"}
		}
		availableFrom = t
	}
	inventoryID := id.NewPrefixed("PINV-")
	record := &domain.ProductInventory{
		InventoryID:      inventoryID,
		ProductID:        productID,
		QuantityOnHand:   qty,
		QuantityReserved: floatArg(args, "quantity_reserved"),
		Status:           status,
		StorageLocation:  stringArg(args, "storage_location"),
		AvailableFrom:    availableFrom,
		LastUpdated:      time.Now(),
	}
	if err := tx.Create(record).Error; err != nil {
		return "", nil, err
	}
	return inventoryID, map[string]interface{}{"inventory_id": inventoryID}, nil
}

func applyInventoryReservation(tx *gorm.DB, args map[string]interface{}) (string, map[string]interface{}, error) {
	materialID := stringArg(args, "material_id")
	qty := floatArg(args, "reserved_qty")
	if materialID == "" || qty <= 0 {
		return "", nil, &AgentTransactionError{StatusCode: 400, Message: "material_id and positive reserved_qty are required"}
	}
	if !exists(tx, &domain.InventoryMaterials{}, "material_id = ?", materialID) {
		return "", nil, &AgentTransactionError{StatusCode: 404, Message: "material not found: " + materialID}
	}
	neededAt := time.Now()
	if v := stringArg(args, "needed_at"); v != "" {
		t, err := parseAgentTime(v)
		if err != nil {
			return "", nil, &AgentTransactionError{StatusCode: 400, Message: "needed_at must be RFC3339"}
		}
		neededAt = t
	}
	reservationID := id.NewPrefixed("RES-")
	record := &domain.InventoryReservation{
		ReservationID: reservationID,
		MaterialID:    materialID,
		JobID:         stringArg(args, "job_id"),
		JobStepID:     stringArg(args, "job_step_id"),
		ReservedQty:   qty,
		NeededAt:      neededAt,
		Status:        domain.InventoryReservationStatusPending,
		CreatedAt:     time.Now(),
		UpdatedAt:     time.Now(),
	}
	if err := tx.Create(record).Error; err != nil {
		return "", nil, err
	}
	return reservationID, map[string]interface{}{"reservation_id": reservationID}, nil
}

func resolveAgentRefs(value interface{}, refs map[string]string) interface{} {
	switch v := value.(type) {
	case map[string]interface{}:
		out := make(map[string]interface{}, len(v))
		for key, item := range v {
			out[key] = resolveAgentRefs(item, refs)
		}
		return out
	case []interface{}:
		out := make([]interface{}, len(v))
		for i, item := range v {
			out[i] = resolveAgentRefs(item, refs)
		}
		return out
	case string:
		if resolved, ok := refs[v]; ok {
			return resolved
		}
		return v
	default:
		return v
	}
}

func findUnresolvedAgentRef(value interface{}) string {
	switch v := value.(type) {
	case map[string]interface{}:
		for _, item := range v {
			if found := findUnresolvedAgentRef(item); found != "" {
				return found
			}
		}
	case []interface{}:
		for _, item := range v {
			if found := findUnresolvedAgentRef(item); found != "" {
				return found
			}
		}
	case string:
		if strings.HasPrefix(v, "$ref:") {
			return v
		}
	}
	return ""
}

func exists(tx *gorm.DB, model interface{}, query string, args ...interface{}) bool {
	var count int64
	return tx.Model(model).Where(query, args...).Count(&count).Error == nil && count > 0
}

func stringArg(args map[string]interface{}, key string) string {
	v, ok := args[key]
	if !ok || v == nil {
		return ""
	}
	switch t := v.(type) {
	case string:
		return strings.TrimSpace(t)
	default:
		return strings.TrimSpace(fmt.Sprint(t))
	}
}

func intArg(args map[string]interface{}, key string) int {
	v, ok := args[key]
	if !ok || v == nil {
		return 0
	}
	switch t := v.(type) {
	case int:
		return t
	case int64:
		return int(t)
	case float64:
		return int(t)
	case float32:
		return int(t)
	default:
		var out int
		_, _ = fmt.Sscanf(fmt.Sprint(t), "%d", &out)
		return out
	}
}

func floatArg(args map[string]interface{}, key string) float64 {
	v, ok := args[key]
	if !ok || v == nil {
		return 0
	}
	switch t := v.(type) {
	case float64:
		return t
	case float32:
		return float64(t)
	case int:
		return float64(t)
	case int64:
		return float64(t)
	default:
		var out float64
		_, _ = fmt.Sscanf(fmt.Sprint(t), "%f", &out)
		return out
	}
}

func boolArg(args map[string]interface{}, key string) bool {
	v, ok := args[key]
	if !ok || v == nil {
		return false
	}
	switch t := v.(type) {
	case bool:
		return t
	case string:
		switch strings.ToLower(strings.TrimSpace(t)) {
		case "1", "true", "yes", "y":
			return true
		default:
			return false
		}
	default:
		return fmt.Sprint(t) == "1"
	}
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value)
		}
	}
	return ""
}

func validMachineStatus(status string) bool {
	switch status {
	case domain.MachineStatusIdle, domain.MachineStatusRunning, domain.MachineStatusMaintenance, domain.MachineStatusOffline:
		return true
	default:
		return false
	}
}

func validJobPriority(priority string) bool {
	switch priority {
	case domain.JobPriorityLow, domain.JobPriorityMedium, domain.JobPriorityHigh, domain.JobPriorityUrgent:
		return true
	default:
		return false
	}
}

func validJobStatus(status string) bool {
	switch status {
	case domain.JobStatusPlanned, domain.JobStatusScheduled, domain.JobStatusRunning, domain.JobStatusBlocked, domain.JobStatusPaused, domain.JobStatusCompleted, domain.JobStatusCancelled:
		return true
	default:
		return false
	}
}

func validSlotStatus(status string) bool {
	switch status {
	case domain.SlotStatusPlanned, domain.SlotStatusRunning, domain.SlotStatusPaused, domain.SlotStatusCompleted, domain.SlotStatusCancelled:
		return true
	default:
		return false
	}
}

func validProductInventoryStatus(status string) bool {
	switch status {
	case domain.ProductInventoryStatusAvailable, domain.ProductInventoryStatusReserved, domain.ProductInventoryStatusBlocked, domain.ProductInventoryStatusPlanned:
		return true
	default:
		return false
	}
}

func inventoryStatus(currentStock, minStock, reorderLevel float64) string {
	if currentStock <= 0 {
		return domain.InventoryStatusOutOfStock
	}
	if currentStock < minStock {
		return domain.InventoryStatusLowStock
	}
	if reorderLevel > 0 && currentStock < reorderLevel {
		return domain.InventoryStatusLowStock
	}
	return domain.InventoryStatusInStock
}

func parseAgentTime(raw string) (time.Time, error) {
	if strings.TrimSpace(raw) == "" {
		return time.Time{}, errors.New("missing time")
	}
	return time.Parse(time.RFC3339, strings.TrimSpace(raw))
}

func startEndArgs(args map[string]interface{}) (time.Time, time.Time, error) {
	start, err := parseAgentTime(stringArg(args, "start_time"))
	if err != nil {
		return time.Time{}, time.Time{}, &AgentTransactionError{StatusCode: 400, Message: "start_time must be RFC3339"}
	}
	end, err := parseAgentTime(stringArg(args, "end_time"))
	if err != nil {
		return time.Time{}, time.Time{}, &AgentTransactionError{StatusCode: 400, Message: "end_time must be RFC3339"}
	}
	if !end.After(start) {
		return time.Time{}, time.Time{}, &AgentTransactionError{StatusCode: 400, Message: "end_time must be after start_time"}
	}
	return start, end, nil
}
