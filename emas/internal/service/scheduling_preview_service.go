package service

import (
	"emas/internal/domain"
	"errors"
	"time"
)

type SolverPreview struct {
	JobID               string              `json:"job_id"`
	ProductID           string              `json:"product_id"`
	QuantityTotal       int                 `json:"quantity_total"`
	Priority            string              `json:"priority"`
	Deadline            time.Time           `json:"deadline"`
	CanStartNow         bool                `json:"can_start_now"`
	EarliestReadyAt     *time.Time          `json:"earliest_ready_at,omitempty"`
	EstimatedCompletion *time.Time          `json:"estimated_completion,omitempty"`
	Objectives          []string            `json:"objectives"`
	Constraints         []string            `json:"constraints"`
	Steps               []SolverPreviewStep `json:"steps"`
}

type SolverPreviewStep struct {
	JobStepID               string             `json:"job_step_id"`
	StepID                  string             `json:"step_id"`
	StepName                string             `json:"step_name"`
	StepType                string             `json:"step_type"`
	StepSequence            int                `json:"step_sequence"`
	QuantityTarget          int                `json:"quantity_target"`
	MachineTypeRequired     string             `json:"machine_type_required"`
	AllowParallelExecution  bool               `json:"allow_parallel_execution"`
	MaxParallelMachines     int                `json:"max_parallel_machines"`
	MinSplitQty             int                `json:"min_split_qty"`
	MinBatchSize            int                `json:"min_batch_size"`
	BatchSize               int                `json:"batch_size"`
	IsBatchProcess          bool               `json:"is_batch_process"`
	TransferBatchSize       int                `json:"transfer_batch_size"`
	MinWaitMinutes          int                `json:"min_wait_minutes"`
	TransferMinutes         int                `json:"transfer_minutes"`
	EarliestStepStart       time.Time          `json:"earliest_step_start"`
	EstimatedDurationMins   int                `json:"estimated_duration_mins"`
	CandidateMachines       []CandidateMachine `json:"candidate_machines"`
}

func (s *SchedulingService) BuildSolverPreview(jobID string) (*SolverPreview, error) {
	job, err := s.jobRepo.GetByID(jobID)
	if err != nil {
		return nil, err
	}
	steps, err := s.stepRepo.ListByJobID(jobID)
	if err != nil {
		return nil, err
	}
	if len(steps) == 0 {
		return nil, errors.New("job has no job steps")
	}
	readiness, err := s.CheckReadiness(job.ProductID, float64(job.QuantityTotal))
	if err != nil {
		return nil, err
	}
	estimate, err := s.EstimateJobEarliestCompletion(jobID)
	if err != nil {
		estimate = nil
	}
	cursor := time.Now()
	if readiness != nil && readiness.EarliestReadyAt != nil && readiness.EarliestReadyAt.After(cursor) {
		cursor = *readiness.EarliestReadyAt
	}
	preview := &SolverPreview{
		JobID:           job.JobID,
		ProductID:       job.ProductID,
		QuantityTotal:   job.QuantityTotal,
		Priority:        job.Priority,
		Deadline:        job.Deadline,
		CanStartNow:     readiness != nil && readiness.CanStartNow,
		EarliestReadyAt: func() *time.Time { if readiness == nil { return nil }; return readiness.EarliestReadyAt }(),
		Objectives: []string{
			"maximize_on_time_completion",
			"minimize_total_tardiness",
			"minimize_changeovers_and_idle_gaps",
		},
		Constraints: []string{
			"material_and_sub_product_readiness",
			"step_precedence",
			"machine_capability",
			"machine_calendar",
			"downtime_and_maintenance",
			"parallel_machine_limits",
			"min_split_quantity",
		},
	}
	if estimate != nil {
		completion := estimate.EstimatedCompletion
		preview.EstimatedCompletion = &completion
	}
	processStepByID := make(map[string]*domain.ProcessSteps)
	for _, jobStep := range steps {
		if ps, err := s.processRepo.GetStepByID(jobStep.StepID); err == nil {
			processStepByID[jobStep.StepID] = ps
		}
	}
	orderedSteps := topologicalStepOrder(steps, processStepByID)
	for _, jobStep := range orderedSteps {
		processStep, err := s.processRepo.GetStepByID(jobStep.StepID)
		if err != nil {
			return nil, err
		}
		// WIP check: for steps that consume products, ensure we have enough (WIP + inventory)
		if s.psmRepo != nil && s.wipRepo != nil {
			inputs, _ := s.psmRepo.ListInputsByStepID(jobStep.StepID)
			for _, in := range inputs {
				if in.ProductID == nil {
					continue
				}
				required := float64(jobStep.QuantityTarget) * in.QuantityPerUnit
				wipQty := s.wipAvailableAtStep(jobStep.JobStepID, *in.ProductID)
				neededFromInv := required - wipQty
				if neededFromInv <= 0 {
					continue
				}
				snapshot, err := s.productInventoryAvailability(*in.ProductID, neededFromInv, cursor, 0)
				if err != nil {
					continue
				}
				if snapshot.AvailableNow < neededFromInv && snapshot.ReadyAt != nil && snapshot.ReadyAt.After(cursor) {
					cursor = *snapshot.ReadyAt
				}
			}
		}
		// Use wide window to fetch candidates for capacity-based duration (quantity scales time)
		wideWindow := 72 * time.Hour
		if processStep.DefaultProcessingTime > 0 {
			d := time.Duration(processStep.DefaultProcessingTime*2) * time.Minute
			if d > wideWindow {
				wideWindow = d
			}
		}
		candidates, err := s.CandidateMachinesForStep(jobStep.JobStepID, cursor, cursor.Add(wideWindow))
		if err != nil {
			return nil, err
		}
		duration := estimatedStepDuration(*processStep, candidates, float64(jobStep.QuantityTarget))
		candidates, err = s.CandidateMachinesForStep(jobStep.JobStepID, cursor, cursor.Add(duration))
		if err != nil {
			return nil, err
		}
		preview.Steps = append(preview.Steps, SolverPreviewStep{
			JobStepID:              jobStep.JobStepID,
			StepID:                 processStep.StepID,
			StepName:               processStep.StepName,
			StepType:               processStep.StepType,
			StepSequence:           jobStep.StepSequence,
			QuantityTarget:         jobStep.QuantityTarget,
			MachineTypeRequired:    processStep.MachineTypeRequired,
			AllowParallelExecution: processStep.AllowParallelExecution,
			MaxParallelMachines:    processStep.MaxParallelMachines,
			MinSplitQty:            processStep.MinSplitQty,
			MinBatchSize:           processStep.MinBatchSize,
			BatchSize:              processStep.BatchSize,
			IsBatchProcess:         processStep.IsBatchProcess,
			TransferBatchSize:      processStep.TransferBatchSize,
			MinWaitMinutes:         processStep.MinWaitMinutes,
			TransferMinutes:        processStep.TransferMinutes,
			EarliestStepStart:      cursor,
			EstimatedDurationMins:  int(duration.Minutes()),
			CandidateMachines:      candidates,
		})
		cursor = cursor.Add(duration)
		cursor = cursor.Add(time.Duration(processStep.MinWaitMinutes+processStep.TransferMinutes) * time.Minute)
	}
	return preview, nil
}

// BuildSolverPreviewWithTentativeSlots builds a solver preview for a job, treating
// the given tentative slots as if they were committed (e.g. from earlier jobs in
// a batch). Use for multi-job batch scheduling.
func (s *SchedulingService) BuildSolverPreviewWithTentativeSlots(jobID string, tentativeSlots []TentativeSlot) (*SolverPreview, error) {
	job, err := s.jobRepo.GetByID(jobID)
	if err != nil {
		return nil, err
	}
	steps, err := s.stepRepo.ListByJobID(jobID)
	if err != nil {
		return nil, err
	}
	if len(steps) == 0 {
		return nil, errors.New("job has no job steps")
	}
	readiness, err := s.CheckReadiness(job.ProductID, float64(job.QuantityTotal))
	if err != nil {
		return nil, err
	}
	estimate, err := s.EstimateJobEarliestCompletion(jobID)
	if err != nil {
		estimate = nil
	}
	cursor := time.Now()
	if readiness != nil && readiness.EarliestReadyAt != nil && readiness.EarliestReadyAt.After(cursor) {
		cursor = *readiness.EarliestReadyAt
	}
	preview := &SolverPreview{
		JobID:           job.JobID,
		ProductID:       job.ProductID,
		QuantityTotal:   job.QuantityTotal,
		Priority:        job.Priority,
		Deadline:        job.Deadline,
		CanStartNow:     readiness != nil && readiness.CanStartNow,
		EarliestReadyAt: func() *time.Time { if readiness == nil { return nil }; return readiness.EarliestReadyAt }(),
		Objectives: []string{
			"maximize_on_time_completion",
			"minimize_total_tardiness",
			"minimize_changeovers_and_idle_gaps",
		},
		Constraints: []string{
			"material_and_sub_product_readiness",
			"step_precedence",
			"machine_capability",
			"machine_calendar",
			"downtime_and_maintenance",
			"parallel_machine_limits",
			"min_split_quantity",
		},
	}
	if estimate != nil {
		completion := estimate.EstimatedCompletion
		preview.EstimatedCompletion = &completion
	}
	processStepByID := make(map[string]*domain.ProcessSteps)
	for _, jobStep := range steps {
		if ps, err := s.processRepo.GetStepByID(jobStep.StepID); err == nil {
			processStepByID[jobStep.StepID] = ps
		}
	}
	orderedSteps := topologicalStepOrder(steps, processStepByID)
	for _, jobStep := range orderedSteps {
		processStep, err := s.processRepo.GetStepByID(jobStep.StepID)
		if err != nil {
			return nil, err
		}
		// WIP check: for steps that consume products, ensure we have enough (WIP + inventory)
		if s.psmRepo != nil && s.wipRepo != nil {
			inputs, _ := s.psmRepo.ListInputsByStepID(jobStep.StepID)
			for _, in := range inputs {
				if in.ProductID == nil {
					continue
				}
				required := float64(jobStep.QuantityTarget) * in.QuantityPerUnit
				wipQty := s.wipAvailableAtStep(jobStep.JobStepID, *in.ProductID)
				neededFromInv := required - wipQty
				if neededFromInv <= 0 {
					continue
				}
				snapshot, err := s.productInventoryAvailability(*in.ProductID, neededFromInv, cursor, 0)
				if err != nil {
					continue
				}
				if snapshot.AvailableNow < neededFromInv && snapshot.ReadyAt != nil && snapshot.ReadyAt.After(cursor) {
					cursor = *snapshot.ReadyAt
				}
			}
		}
		// Use wide window to fetch candidates for capacity-based duration (quantity scales time)
		wideWindow := 72 * time.Hour
		if processStep.DefaultProcessingTime > 0 {
			d := time.Duration(processStep.DefaultProcessingTime*2) * time.Minute
			if d > wideWindow {
				wideWindow = d
			}
		}
		candidates, err := s.CandidateMachinesForStepWithTentative(jobStep.JobStepID, cursor, cursor.Add(wideWindow), tentativeSlots)
		if err != nil {
			return nil, err
		}
		duration := estimatedStepDuration(*processStep, candidates, float64(jobStep.QuantityTarget))
		candidates, err = s.CandidateMachinesForStepWithTentative(jobStep.JobStepID, cursor, cursor.Add(duration), tentativeSlots)
		if err != nil {
			return nil, err
		}
		preview.Steps = append(preview.Steps, SolverPreviewStep{
			JobStepID:              jobStep.JobStepID,
			StepID:                 processStep.StepID,
			StepName:               processStep.StepName,
			StepType:               processStep.StepType,
			StepSequence:           jobStep.StepSequence,
			QuantityTarget:         jobStep.QuantityTarget,
			MachineTypeRequired:    processStep.MachineTypeRequired,
			AllowParallelExecution: processStep.AllowParallelExecution,
			MaxParallelMachines:    processStep.MaxParallelMachines,
			MinSplitQty:            processStep.MinSplitQty,
			MinBatchSize:           processStep.MinBatchSize,
			BatchSize:              processStep.BatchSize,
			IsBatchProcess:         processStep.IsBatchProcess,
			TransferBatchSize:      processStep.TransferBatchSize,
			MinWaitMinutes:         processStep.MinWaitMinutes,
			TransferMinutes:        processStep.TransferMinutes,
			EarliestStepStart:      cursor,
			EstimatedDurationMins:  int(duration.Minutes()),
			CandidateMachines:      candidates,
		})
		cursor = cursor.Add(duration)
		cursor = cursor.Add(time.Duration(processStep.MinWaitMinutes+processStep.TransferMinutes) * time.Minute)
	}
	return preview, nil
}
