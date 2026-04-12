package service

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/pkg/id"
	"fmt"
	"sort"
	"strings"
	"time"

	"gorm.io/gorm"
)

func (s *AIPredictiveService) allocateProposalReservations(tx *gorm.DB, actions []InventoryAction, childBackedPlanKeys map[string]struct{}) error {
    if len(actions) == 0 {
        return nil
    }

    // 1. Create transactional versions of the repos/services
    txInventory := repository.NewInventoryRepository(tx)
    
    // This is the key: Create a transactional wrapper so it sees uncommitted batch writes
    txScheduling := s.scheduling.WithTransaction(tx) 

    // Create an empty ledger solely to satisfy the signature of materialAvailabilityForPlanning.
    emptyLedger := newTentativeInventoryLedger()

    actions = append([]InventoryAction(nil), actions...)
    sort.Slice(actions, func(i, j int) bool {
        if actions[i].Sequence == actions[j].Sequence {
            return actions[i].ActionType < actions[j].ActionType
        }
        return actions[i].Sequence < actions[j].Sequence
    })

    for _, action := range actions {
        switch action.ActionType {
        case inventoryActionProduceProduct:
            // Write to TX repo (uncommitted row)
            if err := txInventory.CreateProductInventory(&domain.ProductInventory{
                InventoryID:      id.NewPrefixed("PINV-SCHED-"),
                ProductID:        action.ResourceID,
                QuantityOnHand:   action.Quantity,
                QuantityReserved: 0,
                Status:           domain.ProductInventoryStatusPlanned,
                StorageLocation:  "scheduled:" + action.JobStepID,
                AvailableFrom:    alignSuccessorStart(action.EffectiveAt.UTC()),
                LastUpdated:      time.Now().UTC(),
            }); err != nil {
                return err
            }

        case inventoryActionReserveMaterial:
            // Use txInventory so we see reservations made by earlier jobs in this ApplyAll batch!
            availability, err := s.materialAvailabilityForPlanning(txInventory, action.ResourceID, action.Quantity, action.EffectiveAt, emptyLedger)
            if err != nil {
                return err
            }
            
            if !availability.EnoughNow {
                return newSchedulingActionError(422, "reason_code=material_shortage material reservation cannot be allocated for "+action.ResourceID+" (short_qty="+fmt.Sprintf("%.2f", availability.ShortageQty)+")")
            }
            
            if err := txInventory.CreateReservation(&domain.InventoryReservation{
                ReservationID: id.NewPrefixed("IRES-"),
                MaterialID:    action.ResourceID,
                JobID:         action.JobID,
                JobStepID:     action.JobStepID,
                ReservedQty:   action.Quantity,
                NeededAt:      alignSuccessorStart(action.EffectiveAt.UTC()),
                Status:        domain.InventoryReservationStatusPending,
                CreatedAt:     time.Now().UTC(),
                UpdatedAt:     time.Now().UTC(),
            }); err != nil {
                return err
            }

        case inventoryActionReserveProduct:
            // 2. FIX: Bypass the isolated local ledger and call productInventoryAvailability
            // on the transactional service so it can read the PINV-SCHED- production above.
            snapshot, err := txScheduling.productInventoryAvailability(action.ResourceID, action.Quantity, action.EffectiveAt, 0)
            if err != nil {
                return err
            }

            if snapshot.AvailableNow < action.Quantity && snapshot.ReadyAt == nil && !reservationBackedByDependentChild(action, childBackedPlanKeys) {
                return newSchedulingActionError(422, "reason_code="+reasonCodeSubproductShortage+" product reservation cannot be allocated for "+action.ResourceID)
            }

            if err := txInventory.CreateProductReservation(&domain.ProductInventoryReservation{
                ReservationID: id.NewPrefixed("PRES-"),
                ProductID:     action.ResourceID,
                JobID:         action.JobID,
                JobStepID:     action.JobStepID,
                ReservedQty:   action.Quantity,
                NeededAt:      alignSuccessorStart(action.EffectiveAt.UTC()),
                Status:        domain.InventoryReservationStatusPending,
                CreatedAt:     time.Now().UTC(),
                UpdatedAt:     time.Now().UTC(),
            }); err != nil {
                return err
            }
        }
    }
    return nil
}

func reservationBackedByDependentChild(action InventoryAction, childBackedPlanKeys map[string]struct{}) bool {
	if strings.TrimSpace(action.PlanKey) == "" {
		return false
	}
	if len(childBackedPlanKeys) == 0 {
		return false
	}
	_, ok := childBackedPlanKeys[action.PlanKey]
	return ok
}

func (s *AIPredictiveService) createDependentJobsAndApply(tx *gorm.DB, proposal *SchedulingProposal, proposalID string) (map[string]string, map[string]map[string]string, []string, []CreatedDependencyLink, error) {
	if proposal == nil || len(proposal.DependentJobs) == 0 {
		return map[string]string{}, map[string]map[string]string{}, nil, nil, nil
	}
	txJobRepo := repository.NewJobRepository(tx)
	txStepRepo := repository.NewJobStepRepository(tx)
	txSlotRepo := repository.NewJobSlotRepository(tx)
	txProcessRepo := repository.NewProcessRepository(tx)
	txInventoryRepo := repository.NewInventoryRepository(tx)
	txScheduling := s.scheduling.WithTransaction(tx)
	txSlotService := NewJobSlotService(txSlotRepo, txStepRepo, txProcessRepo, txJobRepo, txScheduling)
	txDependencyRepo := repository.NewJobDependencyRepository(tx)
	createdJobs := make([]string, 0, len(proposal.DependentJobs))
	createdLinks := make([]CreatedDependencyLink, 0, len(proposal.DependentJobs))
	jobIDByPlanKey := make(map[string]string, len(proposal.DependentJobs))
	stepMapByPlanKey := make(map[string]map[string]string, len(proposal.DependentJobs))
	deps := append([]DependentJobPlan(nil), proposal.DependentJobs...)
	sort.Slice(deps, func(i, j int) bool {
		if deps[i].DependencyDepth == deps[j].DependencyDepth {
			if deps[i].ProductID == deps[j].ProductID {
				return deps[i].PlanKey < deps[j].PlanKey
			}
			return deps[i].ProductID < deps[j].ProductID
		}
		return deps[i].DependencyDepth > deps[j].DependencyDepth
	})
	for _, dep := range deps {
		if dep.PlanningStatus != planningStatusPlanned {
			return nil, nil, nil, nil, newSchedulingActionError(422, "reason_code="+dep.ReasonCode+" dependency plan is not schedulable for "+dep.ProductID)
		}
		job := newGeneratedJob(dep.ProductID, maxInt(int(dep.PlannedQty), 1), dep.estimatedNeedTime(), "generated_by_scheduler:"+dep.PlanKey)
		job.Priority = domain.JobPriorityMedium
		if err := txJobRepo.Create(job); err != nil {
			return nil, nil, nil, nil, err
		}
		steps, err := txSlotService.CreateJobStepsFromRouting(job.JobID)
		if err != nil {
			return nil, nil, nil, nil, err
		}
		stepMap := generatedJobIDMap(steps)
		depProposal := &SchedulingProposal{
			JobID:         job.JobID,
			ProposedSlots: make([]ProposedSlot, 0, len(dep.ProposedSlots)),
		}
		for _, proposed := range dep.ProposedSlots {
			mappedJobStepID := stepMap[proposed.StepID]
			if mappedJobStepID == "" {
				if strings.HasPrefix(proposed.JobStepID, "JS-") {
					mappedJobStepID = proposed.JobStepID
				} else {
					mappedJobStepID = stepMap[proposed.JobStepID]
				}
			}
			if mappedJobStepID == "" {
				return nil, nil, nil, nil, fmt.Errorf("generated child slot step mapping missing for %s", proposed.StepID)
			}
			ps := proposed
			ps.JobStepID = mappedJobStepID
			depProposal.ProposedSlots = append(depProposal.ProposedSlots, ps)
		}
		dep.ProposedSlots = depProposal.ProposedSlots
		if err := s.applyDependentSlots(txSlotService, steps, dep, proposalID); err != nil {
			return nil, nil, nil, nil, err
		}
		jobIDByPlanKey[dep.PlanKey] = job.JobID
		stepMapByPlanKey[dep.PlanKey] = stepMap
		dep.GeneratedJobID = job.JobID
		dep.GeneratedStepIDMap = stepMap
		createdJobs = append(createdJobs, job.JobID)
		parentJobID := dep.ParentJobID
		if mapped, ok := jobIDByPlanKey[parentJobID]; ok {
			parentJobID = mapped
		}
		consumerJobStepID := dep.ConsumerJobStepID
		if parentSteps := stepMapByPlanKey[dep.ParentJobID]; parentSteps != nil {
			if mapped := parentSteps[dep.ConsumerJobStepID]; mapped != "" {
				consumerJobStepID = mapped
			}
		}
		link := &domain.JobDependency{
			DependencyID:      id.NewPrefixed("JDEP-"),
			ParentJobID:       parentJobID,
			ChildJobID:        job.JobID,
			ConsumerJobStepID: consumerJobStepID,
			ProductID:         dep.ProductID,
			RequiredQty:       dep.RequiredQty,
			PlannedQty:        dep.PlannedQty,
			RelationType:      domain.JobDependencyRelationSubproductSupply,
			CreatedAt:         time.Now().UTC(),
			UpdatedAt:         time.Now().UTC(),
		}
		if err := txDependencyRepo.Create(link); err != nil {
			return nil, nil, nil, nil, err
		}
		createdLinks = append(createdLinks, CreatedDependencyLink{
			DependencyID: link.DependencyID,
			ParentJobID:  link.ParentJobID,
			ChildJobID:   link.ChildJobID,
			ProductID:    link.ProductID,
		})
		_ = txInventoryRepo
	}
	return jobIDByPlanKey, stepMapByPlanKey, createdJobs, createdLinks, nil
}

func (s *AIPredictiveService) applyDependentSlots(slotService *JobSlotService, createdSteps []domain.JobSteps, dep DependentJobPlan, proposalID string) error {
	if slotService == nil || len(dep.ProposedSlots) == 0 {
		return nil
	}
	stepIDToJobStepID := generatedJobIDMap(createdSteps)
	grouped := make(map[string][]dto.CreateSlotRequest)
	order := make([]string, 0)
	seen := make(map[string]bool)
	for _, proposed := range dep.ProposedSlots {
		jobStepID := stepIDToJobStepID[proposed.StepID]
		if jobStepID == "" {
			if strings.HasPrefix(proposed.JobStepID, "JS-") {
				jobStepID = proposed.JobStepID
			} else {
				jobStepID = stepIDToJobStepID[proposed.JobStepID]
			}
		}
		if jobStepID == "" {
			return fmt.Errorf("generated child slot step mapping missing for %s", proposed.StepID)
		}
		if !seen[jobStepID] {
			seen[jobStepID] = true
			order = append(order, jobStepID)
		}
		duration := maxInt(proposed.EstimatedDurationMins, int(proposed.ScheduledEnd.Sub(proposed.ScheduledStart).Minutes()))
		grouped[jobStepID] = append(grouped[jobStepID], dto.CreateSlotRequest{
			JobStepID:         jobStepID,
			ProposalID:        proposalID,
			MachineID:         proposed.MachineID,
			StartTime:         proposed.ScheduledStart.Format(time.RFC3339),
			DurationMins:      duration,
			Quantity:          proposed.QuantityPlanned,
			SplitGroupID:      dep.PlanKey,
			AllocationPercent: proposed.AllocationPercent,
			IsParallel:        proposed.IsParallel,
			BatchSequence:     proposed.BatchSequence,
			ProcessingMins:    duration,
		})
	}
	order = dependentJobStepApplyOrder(order, createdSteps)
	for _, jobStepID := range order {
		ignoreMinSplitQty := isTemporalSliceRequestGroup(grouped[jobStepID])
		sort.SliceStable(grouped[jobStepID], func(i, j int) bool {
			return grouped[jobStepID][i].StartTime < grouped[jobStepID][j].StartTime
		})
		var previousEnd *time.Time
		for i := range grouped[jobStepID] {
			rs := &grouped[jobStepID][i]
			start, err := time.Parse(time.RFC3339, rs.StartTime)
			if err != nil {
				return err
			}
			if previousEnd != nil && previousEnd.After(start) {
				start = alignSuccessorStart(*previousEnd)
				rs.StartTime = start.Format(time.RFC3339)
			}
			end := start.Add(time.Duration(rs.DurationMins) * time.Minute)
			validation, vErr := slotService.scheduling.ValidateSlotWithOptions(jobStepID, rs.MachineID, start, end, rs.Quantity, "", SlotValidationOptions{IgnoreMinSplitQty: ignoreMinSplitQty})
			if vErr != nil {
				return vErr
			}
			if !validation.Valid && len(validation.Reasons) > 0 {
				reasonLower := strings.ToLower(validation.Reasons[0])
				if strings.Contains(reasonLower, "overlapping") || strings.Contains(reasonLower, "outside") || strings.Contains(reasonLower, "calendar") || strings.Contains(reasonLower, "previous process step completes") {
				// Scan at most 14 days (672 half-hour slots) to find a valid window.
				// The original 4096-step cap caused 26-second timeouts when no slot
				// existed within the full horizon.
				scanStart := alignSuccessorStart(start.Add(30 * time.Minute))
				scanCap := alignSuccessorStart(time.Now().UTC().Add(14 * 24 * time.Hour))
				for scanSteps := 0; scanSteps < 672 && !scanStart.After(scanCap); scanSteps++ {
						scanEnd := scanStart.Add(time.Duration(rs.DurationMins) * time.Minute)
						scanCheck, scanErr := slotService.scheduling.ValidateSlotWithOptions(jobStepID, rs.MachineID, scanStart, scanEnd, rs.Quantity, "", SlotValidationOptions{IgnoreMinSplitQty: ignoreMinSplitQty})
						if scanErr == nil && scanCheck.Valid {
							start = scanStart
							end = scanEnd
							rs.StartTime = scanStart.Format(time.RFC3339)
							validation = scanCheck
							break
						}
					scanStart = alignSuccessorStart(scanStart.Add(30 * time.Minute))
				}
			}
		}
		if !validation.Valid {
		// Wrap as SchedulingActionError(422) so the HTTP handler maps it to 422, not 500.
		return newSchedulingActionError(422, "reason_code=resource_calendar_blocked slot unavailable for dependent job "+dep.ProductID+": "+strings.Join(validation.Reasons, "; "))
		}
			prev := end
			previousEnd = &prev
		}
		if _, err := slotService.SplitStep(jobStepID, grouped[jobStepID]); err != nil {
			return err
		}
	}
	return nil
}

func dependentJobStepApplyOrder(order []string, createdSteps []domain.JobSteps) []string {
	if len(order) <= 1 {
		return order
	}
	sequenceByJobStepID := make(map[string]int, len(createdSteps))
	for _, step := range createdSteps {
		sequenceByJobStepID[step.JobStepID] = step.StepSequence
	}
	sort.Slice(order, func(i, j int) bool {
		si := sequenceByJobStepID[order[i]]
		sj := sequenceByJobStepID[order[j]]
		if si == sj {
			return order[i] < order[j]
		}
		return si < sj
	})
	return order
}

func (dep DependentJobPlan) estimatedNeedTime() time.Time {
	if dep.EstimatedCompletion != nil && !dep.EstimatedCompletion.IsZero() {
		return *dep.EstimatedCompletion
	}
	return time.Now().UTC().Add(24 * time.Hour)
}

func (s *AIPredictiveService) materialAvailabilityForPlanning(invRepo *repository.InventoryRepository, materialID string, requiredQty float64, at time.Time, ledger *tentativeInventoryLedger) (*DemandMaterial, error) {
	at = alignSuccessorStart(at.UTC())
	material, err := invRepo.GetMaterialByID(materialID)
	if err != nil {
		return nil, err
	}
	var excluded []string
	if ledger != nil {
		excluded = ledger.excludedJobIDs
	}
	reservedNow, err := invRepo.SumActiveReservationsUntilExcluding(materialID, at, excluded)
	if err != nil {
		return nil, err
	}
	// Fetch arrivals up-front so we can count those arriving on or before `at` as
	// additional stock (purchase orders already placed that will be on-hand by the
	// time this step runs). Arrivals after `at` are treated as future events only.
	arrivals, err := invRepo.ListExpectedArrivals(materialID, nil, nil, domain.ExpectedArrivalStatusPending)
	if err != nil {
		return nil, err
	}
	preAtArrivals := 0.0
	for _, arrival := range arrivals {
		when := alignSuccessorStart(arrival.ExpectedArriveAt.UTC())
		if !when.After(at) {
			preAtArrivals += arrival.Quantity
		}
	}
	available := material.CurrentStock - reservedNow + ledger.materialBaseline[materialID] + preAtArrivals
	result := &DemandMaterial{
		MaterialID:   materialID,
		MaterialName: material.MaterialName,
		RequiredQty:  requiredQty,
		Unit:         material.Unit,
		ReservedQty:  reservedNow,
		AvailableQty: available,
		EnoughNow:    available >= requiredQty,
	}
	for _, entry := range ledger.activeEntries {
		if entry.Action.ResourceID != materialID {
			continue
		}
		switch entry.Action.ActionType {
		case inventoryActionReserveMaterial:
			if !entry.EffectiveAt.After(at) {
				available -= entry.Action.Quantity
			}
		}
	}
	if available >= requiredQty {
		result.AvailableQty = available
		result.EnoughNow = true
		return result, nil
	}
	type event struct {
		At    time.Time
		Delta float64
	}
	events := make([]event, 0, len(arrivals)+len(ledger.activeEntries)+len(ledger.virtualArrivals))
	for _, arrival := range arrivals {
		when := alignSuccessorStart(arrival.ExpectedArriveAt.UTC())
		if when.After(at) {
			events = append(events, event{At: when, Delta: arrival.Quantity})
		}
	}
	for _, entry := range ledger.activeEntries {
		if entry.Action.ResourceID != materialID || entry.EffectiveAt.Before(at) {
			continue
		}
		if entry.Action.ActionType == inventoryActionReserveMaterial {
			events = append(events, event{At: entry.EffectiveAt, Delta: -entry.Action.Quantity})
		}
	}
	// Virtual arrivals from convergence seeding: add as positive future events
	// so the timeline scan surfaces them at the correct future timestamp.
	for _, va := range ledger.virtualArrivals {
		if va.MaterialID != materialID || va.Qty <= 0 {
			continue
		}
		when := alignSuccessorStart(va.At.UTC())
		if !when.After(at) {
			// Already past the step time — treat as additional opening stock.
			available += va.Qty
		} else {
			events = append(events, event{At: when, Delta: va.Qty})
		}
	}
	sort.Slice(events, func(i, j int) bool {
		if events[i].At.Equal(events[j].At) {
			return events[i].Delta > events[j].Delta
		}
		return events[i].At.Before(events[j].At)
	})
	slotTimeAvailable := available // slot-time balance before any future-arrival events
	current := available
	for _, event := range events {
		current += event.Delta
		if current >= requiredQty {
			ready := event.At
			result.ReadyAt = &ready
			// Keep slot-time available so callers can compute the actual deficit at
			// the step's scheduled time, not the post-arrival balance.
			result.AvailableQty = slotTimeAvailable
			result.ShortageQty = requiredQty - slotTimeAvailable
			result.EnoughNow = false
			return result, nil
		}
	}
	result.AvailableQty = slotTimeAvailable
	result.ShortageQty = requiredQty - current
	return result, nil
}

func sortRootProposalOrder(order []string, stepRepo *repository.JobStepRepository) {
	sort.Slice(order, func(i, j int) bool {
		si, _ := stepRepo.GetByID(order[i])
		sj, _ := stepRepo.GetByID(order[j])
		if si == nil || sj == nil {
			return order[i] < order[j]
		}
		if si.StepSequence == sj.StepSequence {
			return order[i] < order[j]
		}
		return si.StepSequence < sj.StepSequence
	})
}

func remapActionJobIDs(actions []InventoryAction, rootJobID string, createdJobIDs map[string]string, stepMaps map[string]map[string]string) []InventoryAction {
	out := make([]InventoryAction, 0, len(actions))
	for _, action := range actions {
		cp := action
		if createdJobID, ok := createdJobIDs[action.JobID]; ok {
			cp.JobID = createdJobID
			if stepMap := stepMaps[action.JobID]; stepMap != nil {
				if mapped := stepMap[action.JobStepID]; mapped != "" {
					cp.JobStepID = mapped
				}
			}
		} else if cp.JobID == "" {
			cp.JobID = rootJobID
		}
		out = append(out, cp)
	}
	return out
}

func plannedDependentPlanKeys(deps []DependentJobPlan) map[string]struct{} {
	if len(deps) == 0 {
		return nil
	}
	keys := make(map[string]struct{}, len(deps))
	for _, dep := range deps {
		if dep.PlanningStatus != planningStatusPlanned || strings.TrimSpace(dep.PlanKey) == "" {
			continue
		}
		keys[dep.PlanKey] = struct{}{}
	}
	return keys
}

func resolveDependentParentJobID(parentRef string, createdJobIDs map[string]string) string {
	if mapped, ok := createdJobIDs[parentRef]; ok {
		return mapped
	}
	return parentRef
}

func schedulerNoteAppend(existing, note string) string {
	existing = strings.TrimSpace(existing)
	if existing == "" {
		return note
	}
	return existing + "\n" + note
}
