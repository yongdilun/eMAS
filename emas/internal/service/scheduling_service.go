package service

import (
	"emas/internal/domain"
	"emas/internal/repository"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"
)

type DemandTreeNode struct {
	ProductID   string           `json:"product_id"`
	ProductName string           `json:"product_name"`
	Quantity    float64          `json:"quantity"`
	FormulaID   string           `json:"formula_id,omitempty"`
	Materials   []DemandMaterial `json:"materials,omitempty"`
	Children    []DemandTreeNode `json:"children,omitempty"`
}

type DemandMaterial struct {
	MaterialID    string     `json:"material_id"`
	MaterialName  string     `json:"material_name"`
	RequiredQty   float64    `json:"required_qty"`
	Unit          string     `json:"unit"`
	ReadyAt       *time.Time `json:"ready_at,omitempty"`
	EnoughNow     bool       `json:"enough_now"`
	AvailableQty  float64    `json:"available_qty"`
	ReservedQty   float64    `json:"reserved_qty"`
	ShortageQty   float64    `json:"shortage_qty"`
	LeadTimeHours int        `json:"lead_time_hours,omitempty"` // from formula; 0 = instant
}

type DemandSubProduct struct {
	ProductID     string     `json:"product_id"`
	ProductName   string     `json:"product_name"`
	RequiredQty   float64    `json:"required_qty"`
	AvailableQty  float64    `json:"available_qty"`
	ReservedQty   float64    `json:"reserved_qty"`
	ShortageQty   float64    `json:"shortage_qty"`
	AvailableFrom *time.Time `json:"available_from,omitempty"`
	LeadTimeHours int        `json:"lead_time_hours,omitempty"` // from formula; 0 = instant
}

type SchedulingExplosion struct {
	ProductID   string             `json:"product_id"`
	ProductName string             `json:"product_name"`
	Quantity    float64            `json:"quantity"`
	Tree        DemandTreeNode     `json:"tree"`
	Materials   []DemandMaterial   `json:"materials"`
	SubProducts []DemandSubProduct `json:"sub_products"`
}

type SchedulingReadinessResult struct {
	ProductID       string             `json:"product_id"`
	Quantity        float64            `json:"quantity"`
	CanStartNow     bool               `json:"can_start_now"`
	EarliestReadyAt *time.Time         `json:"earliest_ready_at,omitempty"`
	Materials       []DemandMaterial   `json:"materials"`
	SubProducts     []DemandSubProduct `json:"sub_products"`
}

// TentativeSlot represents a slot not yet persisted, used for batch scheduling.
type TentativeSlot struct {
	MachineID      string
	ScheduledStart time.Time
	ScheduledEnd   time.Time
}

type CandidateMachine struct {
	MachineID        string    `json:"machine_id"`
	MachineName      string    `json:"machine_name"`
	MachineType      string    `json:"machine_type"`
	CapacityPerHour  int       `json:"capacity_per_hour"`
	EfficiencyFactor float64   `json:"efficiency_factor"`
	Available        bool      `json:"available"`
	AvailableFrom    time.Time `json:"available_from"`
	Reasons          []string  `json:"reasons,omitempty"`
}

const (
	ValidationTypeHard = "hard"
	ValidationTypeSoft = "soft"
)

type ValidationReason struct {
	Message string  `json:"message"`
	Type    string  `json:"type"`    // hard | soft
	Penalty float64 `json:"penalty"` // for tie-breaking
}

type SlotValidationResult struct {
	Valid             bool               `json:"valid"`
	JobStepID         string             `json:"job_step_id"`
	MachineID         string             `json:"machine_id"`
	ScheduledStart    time.Time          `json:"scheduled_start"`
	ScheduledEnd      time.Time          `json:"scheduled_end"`
	Reasons           []string           `json:"reasons,omitempty"` // flattened messages (backward compat)
	ValidationReasons []ValidationReason `json:"validation_reasons,omitempty"`
	HardReasons       []string           `json:"hard_reasons,omitempty"`
	SoftReasons       []string           `json:"soft_reasons,omitempty"`
	TotalPenalty      float64            `json:"total_penalty"`
}

func (r *SlotValidationResult) AddHardReason(msg string) {
	r.ValidationReasons = append(r.ValidationReasons, ValidationReason{Message: msg, Type: ValidationTypeHard, Penalty: 0})
	r.Reasons = append(r.Reasons, msg)
	r.Valid = false
}

func (r *SlotValidationResult) AddSoftReason(msg string, penalty float64) {
	r.ValidationReasons = append(r.ValidationReasons, ValidationReason{Message: msg, Type: ValidationTypeSoft, Penalty: penalty})
	r.Reasons = append(r.Reasons, msg)
}

func (r *SlotValidationResult) Finalize() {
	for _, vr := range r.ValidationReasons {
		if vr.Type == ValidationTypeHard {
			r.HardReasons = append(r.HardReasons, vr.Message)
		} else {
			r.SoftReasons = append(r.SoftReasons, vr.Message)
			r.TotalPenalty += vr.Penalty
		}
	}
}

type CompletionEstimate struct {
	JobID               string    `json:"job_id"`
	ProductID           string    `json:"product_id"`
	EarliestStart       time.Time `json:"earliest_start"`
	EstimatedCompletion time.Time `json:"estimated_completion"`
	EstimatedMinutes    int       `json:"estimated_minutes"`
}

type TrainingDatasetRow struct {
	JobID                   string     `json:"job_id"`
	ProductID               string     `json:"product_id"`
	JobPriority             string     `json:"job_priority"`
	JobDeadline             time.Time  `json:"job_deadline"`
	JobQuantityTotal        int        `json:"job_quantity_total"`
	JobQuantityCompleted    int        `json:"job_quantity_completed"`
	CanStartNow             bool       `json:"can_start_now"`
	EarliestReadyAt         *time.Time `json:"earliest_ready_at,omitempty"`
	MaterialShortageCount   int        `json:"material_shortage_count"`
	SubProductShortageCount int        `json:"sub_product_shortage_count"`
	TotalMaterialDemand     float64    `json:"total_material_demand"`
	TotalSubProductDemand   float64    `json:"total_sub_product_demand"`
	ProductNestingDepth     int        `json:"product_nesting_depth"`
	JobStepID               string     `json:"job_step_id"`
	StepID                  string     `json:"step_id"`
	StepSequence            int        `json:"step_sequence"`
	StepType                string     `json:"step_type"`
	ProposalID              string     `json:"proposal_id"`
	ProposalStatus          string     `json:"proposal_status"`
	ProposalEngine          string     `json:"proposal_engine"`
	ProposalObjectiveScore  float64    `json:"proposal_objective_score"`
	ProposalOutcomeRecorded bool       `json:"proposal_outcome_recorded"`
	ProposalRolloutState    string     `json:"proposal_rollout_state"`
	EstimateDeviationMins   int        `json:"estimate_deviation_mins"`

	// Snapshot vectors captured at proposal generation time (pre-scheduling context).
	SnapshotMachineIDs       []string  `json:"snapshot_machine_ids,omitempty"`
	QueueLengthsVector       []int     `json:"queue_lengths_vector,omitempty"`
	MachineUtilizationVector []float64 `json:"machine_utilization_vector,omitempty"`

	MachineTypeRequired     string     `json:"machine_type_required"`
	AllowParallelExecution  bool       `json:"allow_parallel_execution"`
	MaxParallelMachines     int        `json:"max_parallel_machines"`
	MinSplitQty             int        `json:"min_split_qty"`
	TransferBatchSize       int        `json:"transfer_batch_size"`
	SlotID                  string     `json:"slot_id"`
	MachineID               string     `json:"machine_id"`
	MachineStatus           string     `json:"machine_status"`
	MachineCapacityPerHour  int        `json:"machine_capacity_per_hour"`
	MachineUtilizationRate  float64    `json:"machine_utilization_rate"`
	MachineEfficiencyFactor float64    `json:"machine_efficiency_factor"`
	MachineHasCalendar      bool       `json:"machine_has_calendar"`
	MaintenanceDueInDays    int        `json:"maintenance_due_in_days"`
	ScheduledStart          time.Time  `json:"scheduled_start"`
	ScheduledEnd            time.Time  `json:"scheduled_end"`
	QuantityPlanned         int        `json:"quantity_planned"`
	AllocationPercent       float64    `json:"allocation_percent"`
	IsParallel              bool       `json:"is_parallel"`
	ProducedQty             int        `json:"produced_qty"`
	ScrapQty                int        `json:"scrap_qty"`
	SlotStatus              string     `json:"slot_status"`
	CompletionRatio         float64    `json:"completion_ratio"`
	ActualEnd               *time.Time `json:"actual_end,omitempty"`
	DelayMinutes            int        `json:"delay_minutes"`
}

type SchedulingService struct {
	productRepo     *repository.ProductRepository
	bomRepo         *repository.ProductBOMRepository
	formulaRepo     *repository.FormulaRepository
	processRepo     *repository.ProcessRepository
	jobRepo         *repository.JobRepository
	stepRepo        *repository.JobStepRepository
	slotRepo        *repository.JobSlotRepository
	machineRepo     *repository.MachineRepository
	capRepo         *repository.MachineCapabilityRepository
	downtimeRepo    *repository.MachineDowntimeRepository
	maintenanceRepo *repository.MaintenanceRepository
	inventoryRepo   *repository.InventoryRepository
	logRepo         *repository.ProductionLogRepository
	proposalRepo    *repository.AIProposalRepository
	setupRepo       *repository.SetupRepository
	resourceRepo    *repository.ResourceRepository
	wipRepo         *repository.WIPRepository
	psmRepo         *repository.ProcessStepMaterialRepository
	settingsRepo    *repository.SystemSettingsRepository
}

func NewSchedulingService(
	productRepo *repository.ProductRepository,
	bomRepo *repository.ProductBOMRepository,
	formulaRepo *repository.FormulaRepository,
	processRepo *repository.ProcessRepository,
	jobRepo *repository.JobRepository,
	stepRepo *repository.JobStepRepository,
	slotRepo *repository.JobSlotRepository,
	machineRepo *repository.MachineRepository,
	capRepo *repository.MachineCapabilityRepository,
	downtimeRepo *repository.MachineDowntimeRepository,
	maintenanceRepo *repository.MaintenanceRepository,
	inventoryRepo *repository.InventoryRepository,
	logRepo *repository.ProductionLogRepository,
	proposalRepo *repository.AIProposalRepository,
	setupRepo *repository.SetupRepository,
	resourceRepo *repository.ResourceRepository,
	wipRepo *repository.WIPRepository,
	psmRepo *repository.ProcessStepMaterialRepository,
	settingsRepo *repository.SystemSettingsRepository,
) *SchedulingService {
	return &SchedulingService{
		productRepo:     productRepo,
		bomRepo:         bomRepo,
		formulaRepo:     formulaRepo,
		processRepo:     processRepo,
		jobRepo:         jobRepo,
		stepRepo:        stepRepo,
		slotRepo:        slotRepo,
		machineRepo:     machineRepo,
		capRepo:         capRepo,
		downtimeRepo:    downtimeRepo,
		maintenanceRepo: maintenanceRepo,
		inventoryRepo:   inventoryRepo,
		logRepo:         logRepo,
		proposalRepo:    proposalRepo,
		setupRepo:       setupRepo,
		resourceRepo:    resourceRepo,
		wipRepo:         wipRepo,
		psmRepo:         psmRepo,
		settingsRepo:    settingsRepo,
	}
}

// WithSlotRepo returns a copy of s with slotRepo replaced. Use when validating within a transaction
// so slot queries see uncommitted slots (e.g. proposal apply creating step 1 then step 2).
func (s *SchedulingService) WithSlotRepo(slotRepo *repository.JobSlotRepository) *SchedulingService {
	return &SchedulingService{
		productRepo:     s.productRepo,
		bomRepo:         s.bomRepo,
		formulaRepo:     s.formulaRepo,
		processRepo:     s.processRepo,
		jobRepo:         s.jobRepo,
		stepRepo:        s.stepRepo,
		slotRepo:        slotRepo,
		machineRepo:     s.machineRepo,
		capRepo:         s.capRepo,
		downtimeRepo:    s.downtimeRepo,
		maintenanceRepo: s.maintenanceRepo,
		inventoryRepo:   s.inventoryRepo,
		logRepo:         s.logRepo,
		proposalRepo:    s.proposalRepo,
		setupRepo:       s.setupRepo,
		resourceRepo:    s.resourceRepo,
		wipRepo:         s.wipRepo,
		psmRepo:         s.psmRepo,
		settingsRepo:    s.settingsRepo,
	}
}

func (s *SchedulingService) ExplodeDemand(productID string, quantity float64) (*SchedulingExplosion, error) {
	product, err := s.productRepo.GetByID(productID)
	if err != nil {
		return nil, err
	}
	materials := map[string]*DemandMaterial{}
	subProducts := map[string]*DemandSubProduct{}
	path := map[string]bool{}
	tree, err := s.expandProduct(productID, quantity, path, materials, subProducts)
	if err != nil {
		return nil, err
	}
	return &SchedulingExplosion{
		ProductID:   product.ProductID,
		ProductName: product.ProductName,
		Quantity:    quantity,
		Tree:        tree,
		Materials:   sortMaterials(materials),
		SubProducts: sortSubProducts(subProducts),
	}, nil
}

func (s *SchedulingService) CheckReadiness(productID string, quantity float64) (*SchedulingReadinessResult, error) {
	now := time.Now()
	explosion, err := s.ExplodeDemand(productID, quantity)
	if err != nil {
		return nil, err
	}
	var maxReady time.Time
	canStart := true
	for i := range explosion.Materials {
		current := &explosion.Materials[i]
		mat, err := s.materialAvailability(current.MaterialID, current.RequiredQty, now, current.LeadTimeHours)
		if err != nil {
			canStart = false
			current.ShortageQty = current.RequiredQty
			continue
		}
		explosion.Materials[i] = *mat
		explosion.Materials[i].LeadTimeHours = current.LeadTimeHours
		if mat.EnoughNow {
			continue
		}
		canStart = false
		if mat.ReadyAt != nil && mat.ReadyAt.After(maxReady) {
			maxReady = *mat.ReadyAt
		}
	}
	for i := range explosion.SubProducts {
		sub := &explosion.SubProducts[i]
		snapshot, err := s.productInventoryAvailability(sub.ProductID, sub.RequiredQty, now, sub.LeadTimeHours)
		if err != nil {
			canStart = false
			sub.ShortageQty = sub.RequiredQty
			continue
		}
		sub.AvailableQty = snapshot.AvailableNow
		sub.ReservedQty = snapshot.ReservedQty
		if snapshot.AvailableNow >= sub.RequiredQty {
			continue
		}
		if snapshot.ReadyAt != nil {
			sub.AvailableFrom = snapshot.ReadyAt
			if snapshot.ReadyAt.After(maxReady) {
				maxReady = *snapshot.ReadyAt
			}
			continue
		}
		manufactureReadyAt, err := s.estimateManufacturingReadyAt(sub.ProductID, sub.RequiredQty-snapshot.AvailableNow, now, map[string]bool{})
		if err != nil {
			canStart = false
			sub.ShortageQty = math.Max(sub.RequiredQty-sub.AvailableQty, 0)
			continue
		}
		if manufactureReadyAt != nil {
			sub.AvailableFrom = manufactureReadyAt
			if manufactureReadyAt.After(maxReady) {
				maxReady = *manufactureReadyAt
			}
			continue
		}
		sub.ShortageQty = math.Max(sub.RequiredQty-sub.AvailableQty, 0)
		canStart = false
	}
	var earliest *time.Time
	if !canStart && !maxReady.IsZero() && maxReady.After(now) {
		earliest = &maxReady
	}
	return &SchedulingReadinessResult{
		ProductID:       productID,
		Quantity:        quantity,
		CanStartNow:     canStart,
		EarliestReadyAt: earliest,
		Materials:       explosion.Materials,
		SubProducts:     explosion.SubProducts,
	}, nil
}

// GetProcessStepForJobStep returns the process step for a job step (for duration calculation).
func (s *SchedulingService) GetProcessStepForJobStep(jobStepID string) (*domain.ProcessSteps, error) {
	_, processStep, err := s.resolveStepContext(jobStepID)
	return processStep, err
}

func (s *SchedulingService) CandidateMachinesForStep(stepID string, start, end time.Time) ([]CandidateMachine, error) {
	return s.CandidateMachinesForStepWithTentative(stepID, start, end, nil)
}

func (s *SchedulingService) CandidateMachinesForStepWithTentative(stepID string, start, end time.Time, tentativeSlots []TentativeSlot) ([]CandidateMachine, error) {
	jobStep, processStep, err := s.resolveStepContext(stepID)
	if err != nil {
		return nil, err
	}
	if jobStep == nil {
		return s.candidateMachinesForProcessStepWithTentative(processStep, start, end, tentativeSlots)
	}
	baseCandidates, err := s.candidateMachinesForProcessStepWithTentative(processStep, start, end, tentativeSlots)
	if err != nil {
		return nil, err
	}
	productID := ""
	if job, _ := s.jobRepo.GetByID(jobStep.JobID); job != nil {
		productID = job.ProductID
	}
	for i := range baseCandidates {
		// Candidate generation must not depend on DB precedence checks because
		// predecessor slots are not persisted yet during preview/proposal building.
		coreOK, err := s.validateSlotCoreForStep(processStep, baseCandidates[i].MachineID, start, end, 1, "")
		if err != nil {
			return nil, err
		}
		baseCandidates[i].Available = coreOK
		if !coreOK {
			baseCandidates[i].AvailableFrom = s.earliestStartWithSetup(baseCandidates[i].MachineID, start, end.Sub(start), productID, tentativeSlots)
			// Ensure AvailableFrom respects resource work calendar
			resourceStart := s.nextResourceWorkWindowStart(processStep, baseCandidates[i].AvailableFrom)
			if resourceStart.After(baseCandidates[i].AvailableFrom) {
				baseCandidates[i].AvailableFrom = resourceStart
			}
			baseCandidates[i].Reasons = []string{"not available in current window"}
		} else {
			baseCandidates[i].Reasons = nil
		}
	}
	sort.Slice(baseCandidates, func(i, j int) bool {
		if baseCandidates[i].Available == baseCandidates[j].Available {
			return baseCandidates[i].EfficiencyFactor > baseCandidates[j].EfficiencyFactor
		}
		return baseCandidates[i].Available && !baseCandidates[j].Available
	})
	return baseCandidates, nil
}

type SlotValidationOptions struct {
	IgnoreMinSplitQty bool
}

func (s *SchedulingService) ValidateSlot(jobStepID, machineID string, start, end time.Time, quantity int, excludeSlotID string) (*SlotValidationResult, error) {
	return s.ValidateSlotWithOptions(jobStepID, machineID, start, end, quantity, excludeSlotID, SlotValidationOptions{})
}

func (s *SchedulingService) ValidateSlotWithOptions(jobStepID, machineID string, start, end time.Time, quantity int, excludeSlotID string, opts SlotValidationOptions) (*SlotValidationResult, error) {
	result := &SlotValidationResult{
		Valid:          true,
		JobStepID:      jobStepID,
		MachineID:      machineID,
		ScheduledStart: start,
		ScheduledEnd:   end,
	}
	step, err := s.stepRepo.GetByID(jobStepID)
	if err != nil {
		return nil, err
	}
	processStep, err := s.processRepo.GetStepByID(step.StepID)
	if err != nil {
		return nil, err
	}
	job, _ := s.jobRepo.GetByID(step.JobID)
	toProductID := ""
	if job != nil {
		toProductID = job.ProductID
	}
	if err := s.validateMachineWindow(processStep, machineID, start, end, quantity, excludeSlotID, toProductID, opts.IgnoreMinSplitQty, result); err != nil {
		return nil, err
	}
	if err := s.validateResourceAvailability(processStep, start, end, excludeSlotID, result); err != nil {
		return nil, err
	}
	if err := s.validateStepPrecedence(step, start, excludeSlotID, result); err != nil {
		return nil, err
	}
	if err := s.validateParallelPolicy(jobStepID, processStep, start, end, excludeSlotID, result); err != nil {
		return nil, err
	}
	result.Finalize()
	return result, nil
}

func (s *SchedulingService) EstimateJobEarliestCompletion(jobID string) (*CompletionEstimate, error) {
	job, err := s.jobRepo.GetByID(jobID)
	if err != nil {
		return nil, err
	}
	steps, err := s.stepRepo.ListByJobID(jobID)
	if err != nil {
		return nil, err
	}
	readiness, err := s.CheckReadiness(job.ProductID, float64(job.QuantityTotal))
	if err != nil {
		return nil, err
	}
	cursor := time.Now()
	if readiness.EarliestReadyAt != nil && readiness.EarliestReadyAt.After(cursor) {
		cursor = *readiness.EarliestReadyAt
	}
	start := cursor
	for _, jobStep := range steps {
		processStep, err := s.processRepo.GetStepByID(jobStep.StepID)
		if err != nil {
			return nil, err
		}
		stepDuration := estimatedStepDuration(*processStep, nil, float64(job.QuantityTotal))
		candidates, err := s.CandidateMachinesForStep(jobStep.JobStepID, cursor, cursor.Add(stepDuration))
		if err != nil {
			return nil, err
		}
		if len(candidates) == 0 {
			return nil, errors.New("no candidate machines for step")
		}
		selectedStart := cursor
		selectedDuration := stepDuration
		if processStep.AllowParallelExecution && processStep.MaxParallelMachines > 1 {
			parallelCount := minInt(processStep.MaxParallelMachines, len(candidates))
			if parallelCount > 1 {
				for _, candidate := range candidates[:parallelCount] {
					if candidate.AvailableFrom.After(selectedStart) {
						selectedStart = candidate.AvailableFrom
					}
				}
				selectedDuration = estimatedStepDuration(*processStep, candidates[:parallelCount], float64(jobStep.QuantityTarget))
			}
		} else {
			selectedDuration = estimatedStepDuration(*processStep, candidates[:1], float64(jobStep.QuantityTarget))
			if !candidates[0].Available {
				selectedStart = candidates[0].AvailableFrom
			}
		}
		cursor = selectedStart.Add(selectedDuration)
	}
	return &CompletionEstimate{
		JobID:               jobID,
		ProductID:           job.ProductID,
		EarliestStart:       start,
		EstimatedCompletion: cursor,
		EstimatedMinutes:    int(cursor.Sub(start).Minutes()),
	}, nil
}

func (s *SchedulingService) ExportTrainingDataset() ([]TrainingDatasetRow, error) {
	jobs, err := s.jobRepo.ListAll()
	if err != nil {
		return nil, err
	}
	type snapshotVectors struct {
		MachineIDs               []string  `json:"machine_ids"`
		QueueLengthsVector       []int     `json:"queue_lengths_vector"`
		MachineUtilizationVector []float64 `json:"machine_utilization_vector"`
	}
	snapshotCache := map[string]*snapshotVectors{}
	var rows []TrainingDatasetRow
	for _, job := range jobs {
		readiness, _ := s.CheckReadiness(job.ProductID, float64(job.QuantityTotal))
		explosion, _ := s.ExplodeDemand(job.ProductID, float64(job.QuantityTotal))
		materialShortages := 0
		subProductShortages := 0
		totalMaterialQty := 0.0
		totalSubProductQty := 0.0
		nestingDepth := 0
		if readiness != nil {
			for _, material := range readiness.Materials {
				if material.ShortageQty > 0 {
					materialShortages++
				}
			}
			for _, subProduct := range readiness.SubProducts {
				if subProduct.ShortageQty > 0 {
					subProductShortages++
				}
			}
			totalMaterialQty = totalMaterialDemand(readiness.Materials)
			totalSubProductQty = totalSubProductDemand(readiness.SubProducts)
		}
		if explosion != nil {
			nestingDepth = demandTreeDepth(explosion.Tree)
		}
		steps, err := s.stepRepo.ListByJobID(job.JobID)
		if err != nil {
			return nil, err
		}
		for _, step := range steps {
			if step.StepID == "" {
				continue
			}
			processStep, err := s.processRepo.GetStepByID(step.StepID)
			if err != nil {
				continue
			}
			slots, err := s.slotRepo.ListByJobStepID(step.JobStepID)
			if err != nil {
				return nil, err
			}
			for _, slot := range slots {
				machine, _ := s.machineRepo.GetByID(slot.MachineID)
				hasCap, cap, _ := s.capRepo.HasCapability(slot.MachineID, step.StepID)
				var proposal *domain.AIProposal
				if s.proposalRepo != nil && slot.ProposalID != "" {
					proposal, _ = s.proposalRepo.GetByID(slot.ProposalID)
				}
				// Require proposal snapshots with vectors to prevent target leakage.
				// Rows without snapshot vectors are skipped to guarantee a consistent dataset shape.
				var snap *snapshotVectors
				if proposal != nil && proposal.SnapshotJSON != "" {
					if cached, ok := snapshotCache[proposal.ProposalID]; ok {
						snap = cached
					} else {
						var decoded snapshotVectors
						if err := json.Unmarshal([]byte(proposal.SnapshotJSON), &decoded); err == nil &&
							len(decoded.MachineIDs) > 0 &&
							len(decoded.QueueLengthsVector) == len(decoded.MachineIDs) &&
							len(decoded.MachineUtilizationVector) == len(decoded.MachineIDs) {
							snap = &decoded
						}
						snapshotCache[proposal.ProposalID] = snap
					}
				}
				if snap == nil {
					continue
				}
				if !hasCap || cap == nil {
					cap = &domain.MachineCapabilities{EfficiencyFactor: 1}
				}
				calendars, _ := s.machineRepo.ListCalendarByMachineID(slot.MachineID)
				produced, _ := s.logRepo.SumProducedBySlotID(slot.SlotID)
				logs, _ := s.logRepo.ListBySlotID(slot.SlotID)
				scrap := 0
				var actualEnd *time.Time
				for _, log := range logs {
					scrap += log.QuantityScrap
					if actualEnd == nil || log.EndTime.After(*actualEnd) {
						end := log.EndTime
						actualEnd = &end
					}
				}
				completionRatio := 0.0
				if slot.QuantityPlanned > 0 {
					completionRatio = float64(produced) / float64(slot.QuantityPlanned)
				}
				delayMinutes := 0
				if actualEnd != nil && actualEnd.After(slot.ScheduledEnd) {
					delayMinutes = int(actualEnd.Sub(slot.ScheduledEnd).Minutes())
				}
				maintenanceDueInDays := 0
				if machine != nil {
					base := time.Now()
					if machine.LastMaintenanceDate != nil {
						base = *machine.LastMaintenanceDate
					}
					dueAt := base.AddDate(0, 0, machine.MaintenanceIntervalDays)
					maintenanceDueInDays = int(dueAt.Sub(slot.ScheduledStart).Hours() / 24)
				}
				rows = append(rows, TrainingDatasetRow{
					JobID:                job.JobID,
					ProductID:            job.ProductID,
					JobPriority:          job.Priority,
					JobDeadline:          job.Deadline,
					JobQuantityTotal:     job.QuantityTotal,
					JobQuantityCompleted: job.QuantityCompleted,
					CanStartNow:          readiness != nil && readiness.CanStartNow,
					EarliestReadyAt: func() *time.Time {
						if readiness == nil {
							return nil
						}
						return readiness.EarliestReadyAt
					}(),
					MaterialShortageCount:   materialShortages,
					SubProductShortageCount: subProductShortages,
					TotalMaterialDemand:     totalMaterialQty,
					TotalSubProductDemand:   totalSubProductQty,
					ProductNestingDepth:     nestingDepth,
					JobStepID:               step.JobStepID,
					StepID:                  step.StepID,
					StepSequence:            step.StepSequence,
					StepType:                processStep.StepType,
					ProposalID:              slot.ProposalID,
					ProposalStatus: func() string {
						if proposal == nil {
							return ""
						}
						return proposal.Status
					}(),
					ProposalEngine: func() string {
						if proposal == nil {
							return ""
						}
						return proposal.Engine
					}(),
					ProposalObjectiveScore: func() float64 {
						if proposal == nil {
							return 0
						}
						return proposal.ObjectiveScore
					}(),
					ProposalOutcomeRecorded: func() bool { return proposal != nil && proposal.OutcomeJSON != "" }(),
					ProposalRolloutState: func() string {
						if proposal == nil {
							return ""
						}
						return proposal.RolloutState
					}(),
					EstimateDeviationMins: func() int {
						if proposal == nil {
							return 0
						}
						return proposal.EstimateDeviationMins
					}(),
					SnapshotMachineIDs:       snap.MachineIDs,
					QueueLengthsVector:       snap.QueueLengthsVector,
					MachineUtilizationVector: snap.MachineUtilizationVector,
					MachineTypeRequired:      processStep.MachineTypeRequired,
					AllowParallelExecution:   processStep.AllowParallelExecution,
					MaxParallelMachines:      processStep.MaxParallelMachines,
					MinSplitQty:              processStep.MinSplitQty,
					TransferBatchSize:        processStep.TransferBatchSize,
					SlotID:                   slot.SlotID,
					MachineID:                slot.MachineID,
					MachineStatus: func() string {
						if machine == nil {
							return ""
						}
						return machine.Status
					}(),
					MachineCapacityPerHour: func() int {
						if machine == nil {
							return 0
						}
						return machine.CapacityPerHour
					}(),
					MachineUtilizationRate: func() float64 {
						if machine == nil {
							return 0
						}
						return machine.UtilizationRate
					}(),
					MachineEfficiencyFactor: cap.EfficiencyFactor,
					MachineHasCalendar:      len(calendars) > 0,
					MaintenanceDueInDays:    maintenanceDueInDays,
					ScheduledStart:          slot.ScheduledStart,
					ScheduledEnd:            slot.ScheduledEnd,
					QuantityPlanned:         slot.QuantityPlanned,
					AllocationPercent:       slot.AllocationPercent,
					IsParallel:              slot.IsParallel,
					ProducedQty:             produced,
					ScrapQty:                scrap,
					SlotStatus:              slot.Status,
					CompletionRatio:         completionRatio,
					ActualEnd:               actualEnd,
					DelayMinutes:            delayMinutes,
				})
			}
		}
	}
	sort.Slice(rows, func(i, j int) bool {
		if rows[i].JobID == rows[j].JobID {
			return rows[i].ScheduledStart.Before(rows[j].ScheduledStart)
		}
		return rows[i].JobID < rows[j].JobID
	})
	return rows, nil
}

func (s *SchedulingService) expandProduct(productID string, quantity float64, path map[string]bool, materials map[string]*DemandMaterial, subProducts map[string]*DemandSubProduct) (DemandTreeNode, error) {
	if path[productID] {
		return DemandTreeNode{}, errors.New("recursive product dependency detected")
	}
	path[productID] = true
	defer delete(path, productID)

	product, err := s.productRepo.GetByID(productID)
	if err != nil {
		return DemandTreeNode{}, err
	}
	node := DemandTreeNode{
		ProductID:   product.ProductID,
		ProductName: product.ProductName,
		Quantity:    quantity,
		FormulaID:   product.FormulaID,
	}
	ingredients, bomItems, _, err := s.loadProductComponents(product)
	if err != nil {
		return DemandTreeNode{}, err
	}
	if len(ingredients) > 0 {
		for _, ing := range ingredients {
			required := quantity * ing.QuantityPerUnit * (1 + ing.ScrapRate)
			if ing.MaterialID != nil {
				matID := *ing.MaterialID
				matName := matID
				if mat, err := s.inventoryRepo.GetMaterialByID(matID); err == nil {
					matName = mat.MaterialName
				}
				if existing := materials[matID]; existing != nil {
					existing.RequiredQty += required
					if ing.LeadTimeHours > existing.LeadTimeHours {
						existing.LeadTimeHours = ing.LeadTimeHours
					}
				} else {
					materials[matID] = &DemandMaterial{
						MaterialID:    matID,
						MaterialName:  matName,
						RequiredQty:   required,
						Unit:          ing.Unit,
						LeadTimeHours: ing.LeadTimeHours,
					}
				}
				node.Materials = append(node.Materials, DemandMaterial{
					MaterialID:    matID,
					MaterialName:  matName,
					RequiredQty:   required,
					Unit:          ing.Unit,
					LeadTimeHours: ing.LeadTimeHours,
				})
			}
			if ing.ProductID != nil {
				childID := *ing.ProductID
				child, err := s.productRepo.GetByID(childID)
				if err != nil {
					return DemandTreeNode{}, err
				}
				if existing := subProducts[childID]; existing != nil {
					existing.RequiredQty += required
					if ing.LeadTimeHours > existing.LeadTimeHours {
						existing.LeadTimeHours = ing.LeadTimeHours
					}
				} else {
					subProducts[childID] = &DemandSubProduct{
						ProductID:     childID,
						ProductName:   child.ProductName,
						RequiredQty:   required,
						LeadTimeHours: ing.LeadTimeHours,
					}
				}
				childNode, err := s.expandProduct(childID, required, path, materials, subProducts)
				if err != nil {
					return DemandTreeNode{}, err
				}
				node.Children = append(node.Children, childNode)
			}
		}
		return node, nil
	}

	for _, item := range bomItems {
		required := quantity * item.QuantityRequired * (1 + item.ScrapRate)
		if item.MaterialID != nil {
			matID := *item.MaterialID
			matName := matID
			if mat, err := s.inventoryRepo.GetMaterialByID(matID); err == nil {
				matName = mat.MaterialName
			}
			if existing := materials[matID]; existing != nil {
				existing.RequiredQty += required
			} else {
				materials[matID] = &DemandMaterial{
					MaterialID:   matID,
					MaterialName: matName,
					RequiredQty:  required,
					Unit:         item.Unit,
				}
			}
			node.Materials = append(node.Materials, DemandMaterial{
				MaterialID:   matID,
				MaterialName: matName,
				RequiredQty:  required,
				Unit:         item.Unit,
			})
			continue
		}
		if item.ProductComponentID != nil {
			childID := *item.ProductComponentID
			child, err := s.productRepo.GetByID(childID)
			if err != nil {
				return DemandTreeNode{}, err
			}
			if existing := subProducts[childID]; existing != nil {
				existing.RequiredQty += required
			} else {
				subProducts[childID] = &DemandSubProduct{
					ProductID:   childID,
					ProductName: child.ProductName,
					RequiredQty: required,
				}
			}
			childNode, err := s.expandProduct(childID, required, path, materials, subProducts)
			if err != nil {
				return DemandTreeNode{}, err
			}
			node.Children = append(node.Children, childNode)
		}
	}
	return node, nil
}

func (s *SchedulingService) nextMachineFreeTime(machineID string, start time.Time) time.Time {
	return s.nextMachineFreeTimeWithTentative(machineID, start, 0, nil)
}

// findFeasibleMachineStart scans machine work windows and busy intervals to find
// the earliest feasible slot start in [start, horizonEnd]. It avoids minute-by-minute
// scanning by jumping across merged interval boundaries and only validating viable windows.
func (s *SchedulingService) findFeasibleMachineStart(
	jobStepID, machineID string,
	processStep *domain.ProcessSteps,
	start time.Time,
	duration time.Duration,
	quantity int,
	excludeSlotID string,
	tentativeSlots []TentativeSlot,
	predecessorEnd *time.Time,
	horizonEnd time.Time,
) (time.Time, bool, []string, map[string]interface{}) {
	if duration <= 0 {
		duration = time.Minute
	}
	if !horizonEnd.After(start) {
		horizonEnd = start.Add(72 * time.Hour)
	}
	effectiveStart := start
	if predecessorEnd != nil && predecessorEnd.After(effectiveStart) {
		effectiveStart = *predecessorEnd
	}
	workWindows := s.machineWorkWindows(machineID, effectiveStart, horizonEnd)
	busy := s.machineBusyIntervals(machineID, tentativeSlots)
	mergedBusy := mergeBusyIntervals(busy)
	diag := map[string]interface{}{
		"attempted_horizon_start": effectiveStart.UTC().Format(time.RFC3339),
		"attempted_horizon_end":   horizonEnd.UTC().Format(time.RFC3339),
		"cap_hit":                 false,
	}
	for _, window := range workWindows {
		candidate := window.Start
		if effectiveStart.After(candidate) {
			candidate = effectiveStart
		}
		for candidate.Add(duration).Before(window.End) || candidate.Add(duration).Equal(window.End) {
			candidate = NextFreeWindowFromIntervals(candidate, duration, mergedBusy)
			if candidate.Add(duration).After(window.End) {
				break
			}
			// For proposal generation/repair we validate against machine/resource/global
			// constraints using core validation and enforce precedence via predecessorEnd
			// (cursor), because DB-based precedence checks require persisted predecessor slots.
			ps := processStep
			if ps == nil && jobStepID != "" {
				if resolved, err := s.GetProcessStepForJobStep(jobStepID); err == nil {
					ps = resolved
				}
			}
			if ps == nil {
				return time.Time{}, false, []string{"missing process step; cannot validate machine calendar for placement"}, diag
			}
			ok, err := s.validateSlotCoreForStep(ps, machineID, candidate, candidate.Add(duration), quantity, excludeSlotID)
			if err != nil {
				return time.Time{}, false, []string{"slot validation failed: " + err.Error()}, diag
			}
			if ok {
				return candidate, true, nil, diag
			}
			// jump to end of first overlapping busy interval when possible; otherwise move to next boundary
			jumped := false
			for _, iv := range mergedBusy {
				if candidate.Before(iv.End) && candidate.Add(duration).After(iv.Start) {
					candidate = iv.End
					jumped = true
					break
				}
			}
			if !jumped {
				candidate = candidate.Add(15 * time.Minute)
			}
		}
	}
	diag["cap_hit"] = true
	return time.Time{}, false, []string{"no feasible window found in scheduling horizon"}, diag
}

func (s *SchedulingService) validateSlotCoreForStep(processStep *domain.ProcessSteps, machineID string, start, end time.Time, quantity int, excludeSlotID string) (bool, error) {
	result := &SlotValidationResult{Valid: true}
	if err := s.validateMachineWindow(processStep, machineID, start, end, quantity, excludeSlotID, "", false, result); err != nil {
		return false, err
	}
	if err := s.validateResourceAvailability(processStep, start, end, excludeSlotID, result); err != nil {
		return false, err
	}
	result.Finalize()
	return result.Valid, nil
}

func (s *SchedulingService) settingsWorkWindows(from, to time.Time) []BusyInterval {
	if !to.After(from) {
		return nil
	}
	if s.settingsRepo == nil {
		return []BusyInterval{{Start: from, End: to}}
	}
	workStart, ok1, _ := s.settingsRepo.GetString("scheduling.work_start_time")
	workEnd, ok2, _ := s.settingsRepo.GetString("scheduling.work_end_time")
	workDaysStr, ok3, _ := s.settingsRepo.GetString("scheduling.work_days")
	if !ok1 || workStart == "" {
		workStart = "08:00"
	}
	if !ok2 || workEnd == "" {
		workEnd = "17:00"
	}
	if !ok3 || workDaysStr == "" {
		workDaysStr = "1,2,3,4,5"
	}
	startT, err1 := time.Parse("15:04", workStart)
	endT, err2 := time.Parse("15:04", workEnd)
	if err1 != nil || err2 != nil || !endT.After(startT) {
		return nil
	}
	workDays := map[int]bool{}
	for _, p := range strings.Split(workDaysStr, ",") {
		p = strings.TrimSpace(p)
		if len(p) == 1 && p[0] >= '0' && p[0] <= '6' {
			workDays[int(p[0]-'0')] = true
		}
	}
	holidays := map[string]bool{}
	if ph, ok, _ := s.settingsRepo.GetString("scheduling.public_holidays"); ok && ph != "" {
		var list []string
		if json.Unmarshal([]byte(ph), &list) == nil {
			for _, d := range list {
				holidays[d] = true
			}
		}
	}
	loc := time.Local
	f := from.In(loc)
	t := to.In(loc)
	startDate := time.Date(f.Year(), f.Month(), f.Day(), 0, 0, 0, 0, loc)
	endDate := time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, loc)
	out := make([]BusyInterval, 0, 16)
	for day := startDate; !day.After(endDate); day = day.AddDate(0, 0, 1) {
		if !workDays[int(day.Weekday())] {
			continue
		}
		if holidays[day.Format("2006-01-02")] {
			continue
		}
		winStart := time.Date(day.Year(), day.Month(), day.Day(), startT.Hour(), startT.Minute(), 0, 0, loc)
		winEnd := time.Date(day.Year(), day.Month(), day.Day(), endT.Hour(), endT.Minute(), 0, 0, loc)
		if !winEnd.After(f) || !t.After(winStart) {
			continue
		}
		s := winStart
		e := winEnd
		if f.After(s) {
			s = f
		}
		if t.Before(e) {
			e = t
		}
		if e.After(s) {
			out = append(out, BusyInterval{Start: s.UTC(), End: e.UTC()})
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Start.Before(out[j].Start) })
	return mergeBusyIntervals(out)
}

func (s *SchedulingService) machineWorkWindows(machineID string, from, to time.Time) []BusyInterval {
	if !to.After(from) {
		return nil
	}
	global := s.settingsWorkWindows(from, to)
	if len(global) == 0 {
		return nil
	}
	calendars, err := s.machineRepo.ListCalendarByMachineID(machineID)
	if err != nil || len(calendars) == 0 {
		return global
	}
	windows := make([]BusyInterval, 0, len(calendars))
	for _, cal := range calendars {
		if cal.AvailabilityType != "work" {
			continue
		}
		start := cal.StartTime
		end := cal.EndTime
		if end.Before(from) || !start.Before(to) {
			continue
		}
		if from.After(start) {
			start = from
		}
		if to.Before(end) {
			end = to
		}
		if end.After(start) {
			windows = append(windows, BusyInterval{Start: start, End: end})
		}
	}
	if len(windows) == 0 {
		return global
	}
	sort.Slice(windows, func(i, j int) bool { return windows[i].Start.Before(windows[j].Start) })
	windows = mergeBusyIntervals(windows)
	intersections := make([]BusyInterval, 0, len(windows))
	for _, mw := range windows {
		for _, gw := range global {
			s := mw.Start
			if gw.Start.After(s) {
				s = gw.Start
			}
			e := mw.End
			if gw.End.Before(e) {
				e = gw.End
			}
			if e.After(s) {
				intersections = append(intersections, BusyInterval{Start: s, End: e})
			}
		}
	}
	return mergeBusyIntervals(intersections)
}

func (s *SchedulingService) machineBusyIntervals(machineID string, tentativeSlots []TentativeSlot) []BusyInterval {
	intervals := make([]BusyInterval, 0)
	slots, _ := s.slotRepo.ListByMachineID(machineID)
	for _, slot := range slots {
		if slot.Status == domain.SlotStatusCancelled {
			continue
		}
		intervals = append(intervals, BusyInterval{slot.ScheduledStart, slot.ScheduledEnd})
	}
	for _, ts := range tentativeSlots {
		if ts.MachineID == machineID {
			intervals = append(intervals, BusyInterval{ts.ScheduledStart, ts.ScheduledEnd})
		}
	}
	downtimes, _ := s.downtimeRepo.ListByMachineID(machineID)
	for _, dt := range downtimes {
		intervals = append(intervals, BusyInterval{dt.StartTime, dt.EndTime})
	}
	maints, _ := s.maintenanceRepo.ListByMachineID(machineID)
	for _, mt := range maints {
		intervals = append(intervals, BusyInterval{mt.StartTime, mt.EndTime})
	}
	calendars, _ := s.machineRepo.ListCalendarByMachineID(machineID)
	for _, cal := range calendars {
		if cal.AvailabilityType != "work" {
			intervals = append(intervals, BusyInterval{cal.StartTime, cal.EndTime})
		}
	}
	sort.Slice(intervals, func(i, j int) bool { return intervals[i].Start.Before(intervals[j].Start) })
	return intervals
}

// earliestStartWithSetup returns the earliest start time for a slot, accounting for machine busy intervals
// and setup time when switching products. Used when validation fails to give a feasible AvailableFrom.
func (s *SchedulingService) earliestStartWithSetup(machineID string, start time.Time, duration time.Duration, toProductID string, tentativeSlots []TentativeSlot) time.Time {
	raw := s.nextMachineFreeTimeWithTentative(machineID, start, duration, tentativeSlots)
	if s.setupRepo == nil || toProductID == "" {
		return raw
	}
	lastRow, err := s.slotRepo.GetLastSlotOnMachineBefore(machineID, raw)
	if err != nil || lastRow == nil {
		return raw
	}
	setupMins, _ := s.setupRepo.GetSetupMinutes(machineID, lastRow.ProductID, toProductID)
	if setupMins <= 0 {
		return raw
	}
	afterSetup := lastRow.Slot.ScheduledEnd.Add(time.Duration(setupMins) * time.Minute)
	if afterSetup.After(raw) {
		return afterSetup
	}
	return raw
}

// nextMachineFreeTimeWithTentative returns the earliest start such that a slot of
// duration can be placed without overlapping DB slots, tentative slots, downtimes, or maintenance.
// If duration is 0, returns the earliest moment the machine is free (legacy behavior).
func (s *SchedulingService) nextMachineFreeTimeWithTentative(machineID string, start time.Time, duration time.Duration, tentativeSlots []TentativeSlot) time.Time {
	intervals := s.machineBusyIntervals(machineID, tentativeSlots)
	intervals = mergeBusyIntervals(intervals)
	if duration > 0 {
		return NextFreeWindowFromIntervals(start, duration, intervals)
	}
	return NextFreeFromIntervals(start, intervals)
}

func adjustedDuration(base time.Duration, efficiency float64) time.Duration {
	if efficiency <= 0 {
		efficiency = 1.0
	}
	return time.Duration(math.Ceil(float64(base) / efficiency))
}

func parallelizedDuration(step *domain.ProcessSteps, candidates []CandidateMachine) time.Duration {
	if len(candidates) == 0 {
		return 0
	}
	fixed := step.DefaultPreparationTime + step.DefaultCleaningTime + step.DefaultChangeoverTime
	var totalEfficiency float64
	for _, candidate := range candidates {
		if candidate.EfficiencyFactor <= 0 {
			totalEfficiency += 1
		} else {
			totalEfficiency += candidate.EfficiencyFactor
		}
	}
	if totalEfficiency <= 0 {
		totalEfficiency = float64(len(candidates))
	}
	processing := int(math.Ceil(float64(step.DefaultProcessingTime) / totalEfficiency))
	return time.Duration(fixed+processing) * time.Minute
}

func sortMaterials(m map[string]*DemandMaterial) []DemandMaterial {
	out := make([]DemandMaterial, 0, len(m))
	for _, item := range m {
		out = append(out, *item)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].MaterialID < out[j].MaterialID })
	return out
}

func sortSubProducts(m map[string]*DemandSubProduct) []DemandSubProduct {
	out := make([]DemandSubProduct, 0, len(m))
	for _, item := range m {
		out = append(out, *item)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ProductID < out[j].ProductID })
	return out
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

const refreshWorkCalendarsHorizonDays = 90

// RefreshWorkCalendarsFromSettings regenerates ResourceCalendar and MachineCalendar
// for all resources and machines from the work template in scheduling settings.
func (s *SchedulingService) RefreshWorkCalendarsFromSettings() error {
	if s.settingsRepo == nil || s.resourceRepo == nil || s.machineRepo == nil {
		return errors.New("settings, resource, or machine repository not configured")
	}
	workStart, ok1, _ := s.settingsRepo.GetString("scheduling.work_start_time")
	workEnd, ok2, _ := s.settingsRepo.GetString("scheduling.work_end_time")
	workDaysStr, ok3, _ := s.settingsRepo.GetString("scheduling.work_days")
	if !ok1 || workStart == "" {
		workStart = "08:00"
	}
	if !ok2 || workEnd == "" {
		workEnd = "17:00"
	}
	if !ok3 || workDaysStr == "" {
		workDaysStr = "1,2,3,4,5"
	}
	workDays := make(map[int]bool)
	for _, p := range strings.Split(workDaysStr, ",") {
		p = strings.TrimSpace(p)
		if len(p) == 1 && p[0] >= '0' && p[0] <= '6' {
			workDays[int(p[0]-'0')] = true
		}
	}
	var holidays map[string]bool
	if ph, ok, _ := s.settingsRepo.GetString("scheduling.public_holidays"); ok && ph != "" {
		var list []string
		if json.Unmarshal([]byte(ph), &list) == nil {
			holidays = make(map[string]bool)
			for _, d := range list {
				holidays[d] = true
			}
		}
	}
	startT, err1 := time.Parse("15:04", workStart)
	endT, err2 := time.Parse("15:04", workEnd)
	if err1 != nil || err2 != nil {
		return errors.New("invalid work_start_time or work_end_time in settings")
	}
	now := time.Now()
	loc := now.Location()
	base := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, loc)

	resources, err := s.resourceRepo.ListAll()
	if err != nil {
		return fmt.Errorf("list resources: %w", err)
	}
	for _, res := range resources {
		if err := s.resourceRepo.DeleteCalendarByResourceID(res.ResourceID); err != nil {
			return fmt.Errorf("delete resource calendar %s: %w", res.ResourceID, err)
		}
		for i := 0; i < refreshWorkCalendarsHorizonDays; i++ {
			day := base.AddDate(0, 0, i)
			wd := int(day.Weekday())
			if !workDays[wd] {
				continue
			}
			dateStr := day.Format("2006-01-02")
			if holidays != nil && holidays[dateStr] {
				continue
			}
			winStart := time.Date(day.Year(), day.Month(), day.Day(), startT.Hour(), startT.Minute(), 0, 0, loc)
			winEnd := time.Date(day.Year(), day.Month(), day.Day(), endT.Hour(), endT.Minute(), 0, 0, loc)
			cal := domain.ResourceCalendar{
				ID:               fmt.Sprintf("RC-%s-%d", res.ResourceID, i),
				ResourceID:       res.ResourceID,
				StartTime:        winStart,
				EndTime:          winEnd,
				AvailabilityType: "work",
			}
			if err := s.resourceRepo.CreateCalendar(cal); err != nil {
				return fmt.Errorf("create resource calendar %s day %d: %w", res.ResourceID, i, err)
			}
		}
	}

	machines, err := s.machineRepo.ListAll()
	if err != nil {
		return fmt.Errorf("list machines: %w", err)
	}
	for _, m := range machines {
		if err := s.machineRepo.DeleteCalendarByMachineID(m.MachineID); err != nil {
			return fmt.Errorf("delete machine calendar %s: %w", m.MachineID, err)
		}
		for i := 0; i < refreshWorkCalendarsHorizonDays; i++ {
			day := base.AddDate(0, 0, i)
			wd := int(day.Weekday())
			if !workDays[wd] {
				continue
			}
			dateStr := day.Format("2006-01-02")
			if holidays != nil && holidays[dateStr] {
				continue
			}
			winStart := time.Date(day.Year(), day.Month(), day.Day(), startT.Hour(), startT.Minute(), 0, 0, loc)
			winEnd := time.Date(day.Year(), day.Month(), day.Day(), endT.Hour(), endT.Minute(), 0, 0, loc)
			cal := domain.MachineCalendar{
				CalendarID:       fmt.Sprintf("MC-%s-%d", m.MachineID, i),
				MachineID:        m.MachineID,
				StartTime:        winStart,
				EndTime:          winEnd,
				AvailabilityType: "work",
			}
			if err := s.machineRepo.CreateCalendar(cal); err != nil {
				return fmt.Errorf("create machine calendar %s day %d: %w", m.MachineID, i, err)
			}
		}
	}
	return nil
}
