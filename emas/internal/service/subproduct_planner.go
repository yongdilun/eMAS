package service

import (
	"emas/internal/domain"
	"emas/pkg/id"
	"emas/pkg/logger"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"

	"go.uber.org/zap"
)

const (
	reasonCodeSubproductShortage      = "subproduct_shortage"
	reasonCodeBuyItemDelay            = "buy_item_delay"
	reasonCodeNoValidProcess          = "no_valid_process"
	reasonCodeDependencyDepthExceeded = "dependency_depth_exceeded"
	reasonCodeSubjobLimitExceeded     = "subjob_limit_exceeded"
	reasonCodeParentReflowLimit       = "parent_reflow_limit_exceeded"
	reasonCodeChildJobLate            = "child_job_late"
	reasonCodeInsufficientOutput      = "insufficient_production_output"

	planningStatusPlanned       = "planned"
	planningStatusBlocked       = "blocked"
	planningStatusUnschedulable = "unschedulable"

	inventoryActionReserveMaterial = "reserve_material"
	inventoryActionReserveProduct  = "reserve_product"
	inventoryActionProduceProduct  = "produce_product"
	inventoryActionProduceWIP      = "produce_wip"
	inventoryActionConsumeWIP      = "consume_wip"
)

type schedulerSubproductLimits struct {
	MaxDependencyDepth    int
	MaxGeneratedPerRoot   int
	MaxGeneratedPerBatch  int
	MaxParentReflowPasses int
}

type childPlanningAttempt struct {
	PlanningDeadline time.Time
	TargetCompletion *time.Time
}

type proposalBuildOptions struct {
	BatchState              *subproductBatchState
	RootOrderIndex          int
	IncludeInventoryActions bool
	EarliestStartFloor      *time.Time
	TargetCompletion        *time.Time
	TentativeSlots          []TentativeSlot
}

type subproductBatchState struct {
	svc                 *AIPredictiveService
	ledger              *tentativeInventoryLedger
	totalGeneratedNodes int
}

type ledgerEntry struct {
	Sequence    int
	Action      InventoryAction
	EffectiveAt time.Time
}

type virtualMaterialArrival struct {
	MaterialID string
	Qty        float64
	At         time.Time
}

type tentativeInventoryLedger struct {
	nextSequence     int
	activeEntries    []ledgerEntry
	historyEntries   []ledgerEntry
	productBaseline  map[string]float64
	materialBaseline map[string]float64
	virtualArrivals  []virtualMaterialArrival
	excludedJobIDs   []string
}

type productAvailabilityResult struct {
	AvailableNow float64
	FutureQty    float64
	ReadyAt      *time.Time
	ShortageQty  float64
}

func newSubproductBatchState(s *AIPredictiveService) *subproductBatchState {
	return &subproductBatchState{
		svc:    s,
		ledger: newTentativeInventoryLedger(),
	}
}

func (s *subproductBatchState) clone() *subproductBatchState {
	if s == nil {
		return nil
	}
	cloned := &subproductBatchState{
		svc:                 s.svc,
		totalGeneratedNodes: s.totalGeneratedNodes,
	}
	if s.ledger != nil {
		cloned.ledger = s.ledger.clone()
	} else {
		cloned.ledger = newTentativeInventoryLedger()
	}
	return cloned
}

func newTentativeInventoryLedger() *tentativeInventoryLedger {
	return &tentativeInventoryLedger{
		productBaseline:  map[string]float64{},
		materialBaseline: map[string]float64{},
		virtualArrivals:  nil,
		excludedJobIDs:   nil,
	}
}

func (l *tentativeInventoryLedger) appendVirtualArrival(materialID string, qty float64, arriveAt time.Time) {
	l.virtualArrivals = append(l.virtualArrivals, virtualMaterialArrival{
		MaterialID: materialID,
		Qty:        qty,
		At:         normalizeMaterialEventTime(arriveAt),
	})
}

func (l *tentativeInventoryLedger) clone() *tentativeInventoryLedger {
	if l == nil {
		return newTentativeInventoryLedger()
	}
	cloned := &tentativeInventoryLedger{
		nextSequence:     l.nextSequence,
		activeEntries:    append([]ledgerEntry(nil), l.activeEntries...),
		historyEntries:   append([]ledgerEntry(nil), l.historyEntries...),
		productBaseline:  make(map[string]float64, len(l.productBaseline)),
		materialBaseline: make(map[string]float64, len(l.materialBaseline)),
		virtualArrivals:  append([]virtualMaterialArrival(nil), l.virtualArrivals...),
		excludedJobIDs:   append([]string(nil), l.excludedJobIDs...),
	}
	for key, value := range l.productBaseline {
		cloned.productBaseline[key] = value
	}
	for key, value := range l.materialBaseline {
		cloned.materialBaseline[key] = value
	}
	return cloned
}

func (l *tentativeInventoryLedger) hasSequence(seq int) bool {
	if l == nil || seq <= 0 {
		return false
	}
	for _, entry := range l.activeEntries {
		if entry.Sequence == seq {
			return true
		}
	}
	for _, entry := range l.historyEntries {
		if entry.Sequence == seq {
			return true
		}
	}
	return false
}

func (l *tentativeInventoryLedger) next() int {
	l.nextSequence++
	return l.nextSequence
}

func (l *tentativeInventoryLedger) append(action InventoryAction) InventoryAction {
	action.Sequence = l.next()
	action.EffectiveAt = normalizeMaterialEventTime(action.EffectiveAt)
	entry := ledgerEntry{
		Sequence:    action.Sequence,
		Action:      action,
		EffectiveAt: action.EffectiveAt,
	}
	l.activeEntries = append(l.activeEntries, entry)
	return action
}

func (l *tentativeInventoryLedger) activeBefore(at time.Time) []ledgerEntry {
	out := make([]ledgerEntry, 0, len(l.activeEntries))
	for _, entry := range l.activeEntries {
		if entry.EffectiveAt.After(at) {
			continue
		}
		out = append(out, entry)
	}
	return out
}

func (l *tentativeInventoryLedger) compact(cursor time.Time) {
	if len(l.activeEntries) == 0 {
		return
	}
	cursor = alignSuccessorStart(cursor.UTC())
	remaining := make([]ledgerEntry, 0, len(l.activeEntries))
	for _, entry := range l.activeEntries {
		if !entry.EffectiveAt.Before(cursor) {
			remaining = append(remaining, entry)
			continue
		}
		switch entry.Action.ActionType {
		case inventoryActionReserveMaterial:
			l.materialBaseline[entry.Action.ResourceID] -= entry.Action.Quantity
		case inventoryActionReserveProduct:
			l.productBaseline[entry.Action.ResourceID] -= entry.Action.Quantity
		case inventoryActionProduceProduct:
			l.productBaseline[entry.Action.ResourceID] += entry.Action.Quantity
		}
		l.historyEntries = append(l.historyEntries, entry)
	}
	l.activeEntries = remaining
}

func (s *AIPredictiveService) subproductLimits() schedulerSubproductLimits {
	limits := schedulerSubproductLimits{
		MaxDependencyDepth:    4,
		MaxGeneratedPerRoot:   200,  // FIX: Increased from 12 to prevent truncation
		MaxGeneratedPerBatch:  2000, // FIX: Increased from 64 to prevent truncation
		MaxParentReflowPasses: 3,
	}
	if s.settingsRepo == nil {
		return limits
	}
	if v, err := s.settingsRepo.GetInt("scheduling.subproduct.max_dependency_depth", limits.MaxDependencyDepth); err == nil && v > 0 {
		limits.MaxDependencyDepth = v
	}
	if v, err := s.settingsRepo.GetInt("scheduling.subproduct.max_generated_subjobs_per_root", limits.MaxGeneratedPerRoot); err == nil && v > 0 {
		limits.MaxGeneratedPerRoot = v
	}
	if v, err := s.settingsRepo.GetInt("scheduling.subproduct.max_total_generated_nodes_per_batch", limits.MaxGeneratedPerBatch); err == nil && v > 0 {
		limits.MaxGeneratedPerBatch = v
	}
	if v, err := s.settingsRepo.GetInt("scheduling.subproduct.max_parent_reflow_passes_per_root", limits.MaxParentReflowPasses); err == nil && v > 0 {
		limits.MaxParentReflowPasses = v
	}
	return limits
}

func (s *AIPredictiveService) finalizeProposalPlan(job *domain.Job, preview *SolverPreview, proposal *SchedulingProposal, opts proposalBuildOptions) (*SchedulingProposal, error) {
	started := time.Now()
	previewSteps := 0
	if preview != nil {
		previewSteps = len(preview.Steps)
	}
	if proposal == nil {
		return nil, nil
	}
	if opts.BatchState == nil {
		opts.BatchState = newSubproductBatchState(s)
	}

	analysisState := opts.BatchState.clone()
	attemptState := opts.BatchState.clone()

	if err := s.decorateProposalWithInventoryPlan(job, preview, proposal, opts.TentativeSlots, attemptState, opts.RootOrderIndex, opts.TargetCompletion); err != nil {
		return nil, err
	}

	if shortages, resolutions, score, err := s.analyzeProposalMaterialShortages(proposal, analysisState.ledger); err == nil {
		proposal.MaterialShortages = shortages
		proposal.ShortageResolutions = resolutions
		proposal.GlobalScore = score
		for _, sh := range shortages {
			if !sh.AllStepMaterialsFeasible {
				proposal.Feasible = false
				proposal.BlockedReasons = appendUniqueString(proposal.BlockedReasons, "reason_code=material_shortage")
				break
			}
		}
	}

	if proposal.Feasible {
		opts.BatchState.ledger = attemptState.ledger
		opts.BatchState.totalGeneratedNodes = attemptState.totalGeneratedNodes
	}

	proposal.InventoryActionCount = len(proposal.InventoryActions)
	if !opts.IncludeInventoryActions {
		proposal.InventoryActions = nil
	}
	if job != nil {
		logger.L().Info("batch_reschedule_timing",
			zap.String("stage", "finalize_proposal_plan"),
			zap.String("job_id", job.JobID),
			zap.Int("preview_steps", previewSteps),
			zap.Int("proposed_slots", len(proposal.ProposedSlots)),
			zap.Int("dependent_jobs", len(proposal.DependentJobs)),
			zap.Int("inventory_actions", proposal.InventoryActionCount),
			zap.Int("material_shortages", len(proposal.MaterialShortages)),
			zap.Bool("feasible", proposal.Feasible),
			zap.Duration("elapsed", time.Since(started)),
		)
	}
	return proposal, nil
}

func (s *AIPredictiveService) decorateProposalWithInventoryPlan(job *domain.Job, preview *SolverPreview, proposal *SchedulingProposal, tentativeSlots []TentativeSlot, state *subproductBatchState, rootOrder int, targetCompletion *time.Time) error {
	if job == nil || preview == nil || proposal == nil || state == nil {
		return nil
	}
	limits := s.subproductLimits()
	reflowPasses := 0
	materialReflowPasses := 0
	localTentative := make([]TentativeSlot, 0)
	stepBounds := boundsByJobStep(proposal.ProposedSlots)
	stepSequence := stepSequenceIndex(preview)
	stepByJobStep := previewStepIndex(preview)
	childCount := 0

	for _, step := range preview.Steps {
		var (
			bounds      slotBounds
			ok          bool
			inputs      []domain.ProcessStepMaterial
			stepBlocked bool
		)

		previousActions := append([]InventoryAction(nil), proposal.InventoryActions...)
		previousDeps := append([]DependentJobPlan(nil), proposal.DependentJobs...)

		for {
			bounds, ok = stepBounds[step.JobStepID]
			if !ok {
				break
			}
			state.ledger.compact(bounds.Start)
			var err error
			inputs, err = s.scheduling.psmRepo.ListInputsByStepID(step.StepID)
			if err != nil {
				return err
			}
			materialCheck, err := s.checkAllStepMaterials(step, bounds.Start, inputs, state)
			if err != nil {
				return err
			}
			if materialCheck.AnyShort {
				if readyAt, canReflow := latestShortDemandReadyAt(materialCheck.ShortDemands); canReflow && readyAt.After(bounds.Start) && materialReflowPasses < limits.MaxParentReflowPasses {
					accelerationNeeds := materialAccelerationNeedsFromShortDemands(job.JobID, step.JobStepID, bounds.Start, *readyAt, materialCheck.ShortDemands)
					materialReflowPasses++
					delta := readyAt.Sub(bounds.Start)
					previousSlots := append([]ProposedSlot(nil), proposal.ProposedSlots...)
					s.shiftProposalSuffix(proposal, step.JobStepID, delta, stepSequence)
					if err := s.repairReflowedProposalSuffix(job.JobID, proposal, tentativeSlots, targetCompletion); err == nil {
						appendMaterialAccelerationNeeds(proposal, accelerationNeeds)
						stepBounds = boundsByJobStep(proposal.ProposedSlots)
						proposal.InventoryActions = previousActions
						proposal.DependentJobs = previousDeps
						continue
					}
					proposal.ProposedSlots = previousSlots
					recomputeProposalBounds(proposal)
					stepBounds = boundsByJobStep(proposal.ProposedSlots)
				}
				proposal.Feasible = false
				proposal.BlockedReasons = appendUniqueString(proposal.BlockedReasons, "reason_code=material_shortage")
				if materialCheck.Partial != nil {
					proposal.PartialFeasibility = materialCheck.Partial
					if materialCheck.DeferredNode != nil {
						proposal.DeferredNodes = append(proposal.DeferredNodes, *materialCheck.DeferredNode)
					}
				}
				for _, demand := range materialCheck.ShortDemands {
					proposal.InventoryActions = append(proposal.InventoryActions, InventoryAction{
						ActionType:  inventoryActionReserveMaterial,
						ResourceID:  demand.MaterialID,
						JobID:       job.JobID,
						JobStepID:   step.JobStepID,
						Quantity:    demand.RequiredQty,
						EffectiveAt: normalizeMaterialEventTime(bounds.Start),
					})
				}
				stepBlocked = true
			}
			break
		}
		if !ok {
			continue
		}

		pendingActions := make(map[string][]InventoryAction)

		for _, input := range inputs {
			required := float64(step.QuantityTarget) * input.QuantityPerUnit
			if required <= 0 || input.ProductID == nil {
				continue
			}

			productID := *input.ProductID
			wipQty := s.localWIPAvailability(job.JobID, step.JobStepID, productID, bounds.Start, proposal.InventoryActions)
			needFromShared := required - wipQty
			if needFromShared < 0 {
				needFromShared = 0
			}
			dependencyPlanKey := ""

			availability, err := s.productAvailabilityForPlanning(productID, needFromShared, bounds.Start, state.ledger, job.JobID)
			if err != nil {
				return err
			}

			// FIX: Prevent WIP time-travel.
			// If stock exists but is only ready in the future, we MUST reflow the parent
			// job to wait for it before allowing standard reservations to proceed.
			if availability.ReadyAt != nil && availability.ReadyAt.After(bounds.Start) {
				delta := alignSuccessorStart(*availability.ReadyAt).Sub(bounds.Start)
				s.shiftProposalSuffix(proposal, step.JobStepID, delta, stepSequence)
				if err := s.repairReflowedProposalSuffix(job.JobID, proposal, tentativeSlots, targetCompletion); err != nil {
					proposal.Feasible = false
					proposal.BlockedReasons = appendUniqueString(proposal.BlockedReasons, "reason_code="+reasonCodeChildJobLate)
					stepBlocked = true
					break
				}
				stepBounds = boundsByJobStep(proposal.ProposedSlots)
				bounds = stepBounds[step.JobStepID]

				availability, err = s.productAvailabilityForPlanning(productID, needFromShared, bounds.Start, state.ledger, job.JobID)
				if err != nil {
					return err
				}
			}

			shortage := availability.ShortageQty
			if shortage > 0 {
				source, canMake := s.resolveSubproductSource(job.ProductID, productID)
				if source == domain.IngredientSourceBuy {
					s.addBlockedDependency(proposal, job.JobID, step.JobStepID, productID, shortage, availability, reasonCodeBuyItemDelay, "Insufficient bought-in subproduct stock.")
					continue
				}
				if !canMake {
					s.addBlockedDependency(proposal, job.JobID, step.JobStepID, productID, shortage, availability, reasonCodeNoValidProcess, "No valid process exists for the required subproduct.")
					continue
				}
				if childCount >= limits.MaxGeneratedPerRoot || state.totalGeneratedNodes >= limits.MaxGeneratedPerBatch {
					code := reasonCodeSubjobLimitExceeded
					s.addBlockedDependency(proposal, job.JobID, step.JobStepID, productID, shortage, availability, code, "Subjob generation limit exceeded.")
					proposal.Feasible = false
					proposal.BlockedReasons = appendUniqueString(proposal.BlockedReasons, "reason_code="+code)
					continue
				}
				childCount++
				state.totalGeneratedNodes++
				planKey := fmt.Sprintf("%s|%s|%02d|%02d", job.JobID, productID, step.StepSequence, childCount)
				childPlan, childActions, childSlots, childCompletion, childAccelerationNeeds, nestedCount, err := s.planVirtualSubproductJob(job, step, bounds.Start, productID, shortage, planKey, 1, rootOrder, tentativeSlots, localTentative, state, limits, targetCompletion)
				if err != nil {
					return err
				}
				childCount += nestedCount
				proposal.DependentJobs = append(proposal.DependentJobs, childPlan...)
				appendMaterialAccelerationNeeds(proposal, childAccelerationNeeds)

				if len(childActions) > 0 {
					pendingActions[planKey] = append(pendingActions[planKey], childActions...)
				}

				if isPlannedDependentJob(proposal.DependentJobs, planKey) {
					if pa, ok := pendingActions[planKey]; ok && len(pa) > 0 {
						proposal.InventoryActions = append(proposal.InventoryActions, pa...)
						delete(pendingActions, planKey)
					}
					dependencyPlanKey = planKey
					localTentative = append(localTentative, childSlots...)
					for _, ts := range childSlots {
						tentativeSlots = append(tentativeSlots, ts)
					}
				}
				availability, err = s.productAvailabilityForPlanning(productID, needFromShared, bounds.Start, state.ledger, job.JobID)
				if err != nil {
					return err
				}
				shortage = availability.ShortageQty
				topUpPasses := 0
				for shortage > 0 {
					if !isPlannedDependentJob(proposal.DependentJobs, planKey) {
						break
					}

					readyAt := latestDependencyReadyAt(childCompletion, availability.ReadyAt)
					if readyAt == nil || !readyAt.After(bounds.Start) {
						if topUpPasses < 3 {
							topUpPasses++
							topUpKey := fmt.Sprintf("%s|topup|%02d", planKey, topUpPasses)
							childCount++
							state.totalGeneratedNodes++
							topUpPlans, topUpActions, topUpSlots, topUpCompletion, topUpAccelerationNeeds, nestedCount, topUpErr := s.planVirtualSubproductJob(job, step, bounds.Start, productID, shortage, topUpKey, 1, rootOrder, tentativeSlots, localTentative, state, limits, targetCompletion)
							if topUpErr == nil {
								childCount += nestedCount
								proposal.DependentJobs = append(proposal.DependentJobs, topUpPlans...)
								appendMaterialAccelerationNeeds(proposal, topUpAccelerationNeeds)

								if len(topUpActions) > 0 {
									pendingActions[topUpKey] = append(pendingActions[topUpKey], topUpActions...)
								}

								if isPlannedDependentJob(proposal.DependentJobs, topUpKey) {
									if pa, ok := pendingActions[topUpKey]; ok && len(pa) > 0 {
										proposal.InventoryActions = append(proposal.InventoryActions, pa...)
										delete(pendingActions, topUpKey)
									}
									if dependencyPlanKey == "" {
										dependencyPlanKey = topUpKey
									}

									localTentative = append(localTentative, topUpSlots...)
									for _, ts := range topUpSlots {
										tentativeSlots = append(tentativeSlots, ts)
									}
									if topUpCompletion != nil {
										childCompletion = topUpCompletion
									}
									availability, err = s.productAvailabilityForPlanning(productID, needFromShared, bounds.Start, state.ledger, job.JobID)
									if err != nil {
										return err
									}
									shortage = availability.ShortageQty
									continue
								}
							}
						}
						break
					}
					reflowPasses++
					if reflowPasses > limits.MaxParentReflowPasses {
						setDependentJobPlanStatus(proposal.DependentJobs, planKey, planningStatusUnschedulable, reasonCodeParentReflowLimit, "Parent reflow limit exceeded before dependency could be satisfied.")
						proposal.Feasible = false
						proposal.BlockedReasons = appendUniqueString(proposal.BlockedReasons, "reason_code="+reasonCodeParentReflowLimit)
						if pa, ok := pendingActions[planKey]; ok && len(pa) > 0 {
							proposal.InventoryActions = append(proposal.InventoryActions, pa...)
						} else {
							for i := 1; i <= 3; i++ {
								topKey := fmt.Sprintf("%s|topup|%02d", planKey, i)
								if pa2, ok2 := pendingActions[topKey]; ok2 && len(pa2) > 0 {
									proposal.InventoryActions = append(proposal.InventoryActions, pa2...)
									break
								}
							}
						}
						delete(pendingActions, planKey)
						for i := 1; i <= 3; i++ {
							delete(pendingActions, fmt.Sprintf("%s|topup|%02d", planKey, i))
						}
						break
					}
					delta := alignSuccessorStart(*readyAt).Sub(bounds.Start)
					s.shiftProposalSuffix(proposal, step.JobStepID, delta, stepSequence)
					if err := s.repairReflowedProposalSuffix(job.JobID, proposal, tentativeSlots, targetCompletion); err != nil {
						setDependentJobPlanStatus(proposal.DependentJobs, planKey, planningStatusUnschedulable, reasonCodeChildJobLate, "Parent suffix could not be repaired onto a valid machine/resource calendar window.")
						proposal.Feasible = false
						proposal.BlockedReasons = appendUniqueString(proposal.BlockedReasons, "reason_code="+reasonCodeChildJobLate)
						if pa, ok := pendingActions[planKey]; ok && len(pa) > 0 {
							proposal.InventoryActions = append(proposal.InventoryActions, pa...)
						} else {
							for i := 1; i <= 3; i++ {
								topKey := fmt.Sprintf("%s|topup|%02d", planKey, i)
								if pa2, ok2 := pendingActions[topKey]; ok2 && len(pa2) > 0 {
									proposal.InventoryActions = append(proposal.InventoryActions, pa2...)
									break
								}
							}
						}
						delete(pendingActions, planKey)
						for i := 1; i <= 3; i++ {
							delete(pendingActions, fmt.Sprintf("%s|topup|%02d", planKey, i))
						}
						return err
					}
					stepBounds = boundsByJobStep(proposal.ProposedSlots)
					bounds = stepBounds[step.JobStepID]
					availability, err = s.productAvailabilityForPlanning(productID, needFromShared, bounds.Start, state.ledger, job.JobID)
					if err != nil {
						return err
					}
					shortage = availability.ShortageQty
				}
				if shortage > 0 {
					if plan := dependentJobPlanByKey(proposal.DependentJobs, planKey); plan != nil && plan.PlanningStatus != planningStatusPlanned && strings.TrimSpace(plan.ReasonCode) != "" {
						proposal.Feasible = false
						proposal.BlockedReasons = appendUniqueString(proposal.BlockedReasons, "reason_code="+plan.ReasonCode)
						if pa, ok := pendingActions[planKey]; ok && len(pa) > 0 {
							proposal.InventoryActions = append(proposal.InventoryActions, pa...)
						} else {
							for i := 1; i <= 3; i++ {
								topKey := fmt.Sprintf("%s|topup|%02d", planKey, i)
								if pa2, ok2 := pendingActions[topKey]; ok2 && len(pa2) > 0 {
									proposal.InventoryActions = append(proposal.InventoryActions, pa2...)
									break
								}
							}
						}
						delete(pendingActions, planKey)
						for i := 1; i <= 3; i++ {
							delete(pendingActions, fmt.Sprintf("%s|topup|%02d", planKey, i))
						}
						continue
					}
					if childCompletion != nil && !childCompletion.After(bounds.Start) {
						// fall through
					} else {
						setDependentJobPlanStatus(proposal.DependentJobs, planKey, planningStatusUnschedulable, reasonCodeChildJobLate, "Child job cannot finish before the parent consuming step.")
						proposal.Feasible = false
						proposal.BlockedReasons = appendUniqueString(proposal.BlockedReasons, "reason_code="+reasonCodeChildJobLate)
						continue
					}
				}
			}
			actionType := inventoryActionReserveProduct
			if wipQty >= required {
				actionType = inventoryActionConsumeWIP
			}
			action := InventoryAction{
				ActionType:  actionType,
				ResourceID:  productID,
				JobID:       job.JobID,
				JobStepID:   step.JobStepID,
				Quantity:    required,
				EffectiveAt: normalizeMaterialEventTime(bounds.Start),
				PlanKey:     dependencyPlanKey,
			}
			if actionType == inventoryActionReserveProduct {
				action = state.ledger.append(action)
			} else {
				action.Sequence = state.ledger.next()
				action.EffectiveAt = normalizeMaterialEventTime(action.EffectiveAt)
			}
			proposal.InventoryActions = append(proposal.InventoryActions, action)
		}

		if stepBlocked {
			continue
		}

		for _, input := range inputs {
			required := float64(step.QuantityTarget) * input.QuantityPerUnit
			if required <= 0 || input.MaterialID == nil {
				continue
			}
			action := InventoryAction{
				ActionType:  inventoryActionReserveMaterial,
				ResourceID:  *input.MaterialID,
				JobID:       job.JobID,
				JobStepID:   step.JobStepID,
				Quantity:    required,
				EffectiveAt: normalizeMaterialEventTime(bounds.Start),
			}
			action = state.ledger.append(action)
			proposal.InventoryActions = append(proposal.InventoryActions, action)
		}

		outputs, err := s.scheduling.psmRepo.ListOutputsByStepID(step.StepID)
		if err != nil {
			return err
		}
		for _, output := range outputs {
			if output.ProductID == nil {
				continue
			}
			actionType := inventoryActionProduceProduct
			if s.hasSameJobConsumer(preview, stepByJobStep, step.StepSequence, *output.ProductID) {
				actionType = inventoryActionProduceWIP
			}
			action := InventoryAction{
				ActionType:  actionType,
				ResourceID:  *output.ProductID,
				JobID:       job.JobID,
				JobStepID:   step.JobStepID,
				Quantity:    float64(step.QuantityTarget) * output.QuantityPerUnit,
				EffectiveAt: normalizeMaterialEventTime(bounds.End),
			}
			if actionType == inventoryActionProduceProduct {
				action = state.ledger.append(action)
			} else {
				action.Sequence = state.ledger.next()
				action.EffectiveAt = normalizeMaterialEventTime(action.EffectiveAt)
			}
			proposal.InventoryActions = append(proposal.InventoryActions, action)
		}
	}
	proposal.InventoryActionCount = len(proposal.InventoryActions)
	finalizeProposalScores(proposal, job)
	return nil
}

func (s *AIPredictiveService) planVirtualSubproductJob(parentJob *domain.Job, consumerStep SolverPreviewStep, needAt time.Time, productID string, shortage float64, planKey string, depth int, rootOrder int, batchTentative, localTentative []TentativeSlot, state *subproductBatchState, limits schedulerSubproductLimits, parentTargetCompletion *time.Time) ([]DependentJobPlan, []InventoryAction, []TentativeSlot, *time.Time, []materialAccelerationNeed, int, error) {
	if depth > limits.MaxDependencyDepth {
		dep := DependentJobPlan{
			PlanKey:           planKey,
			ParentJobID:       parentJob.JobID,
			ConsumerJobStepID: consumerStep.JobStepID,
			ProductID:         productID,
			DependencyDepth:   depth,
			RequiredQty:       shortage,
			PlannedQty:        shortage,
			ShortageQty:       shortage,
			PlanningStatus:    planningStatusUnschedulable,
			ReasonCode:        reasonCodeDependencyDepthExceeded,
			Reason:            "Dependency depth limit exceeded.",
			Explanation: ProposalExplanation{
				Required:          shortage,
				Available:         0,
				PlannedProduction: shortage,
			},
		}
		return []DependentJobPlan{dep}, nil, nil, nil, nil, 0, nil
	}
	plannedQty := s.roundPlannedSubproductQty(productID, shortage)
	sharedTentative := append(append([]TentativeSlot{}, batchTentative...), localTentative...)
	attempts := buildChildPlanningAttempts(parentJob.Deadline, parentTargetCompletion, needAt)
	var proposal *SchedulingProposal
	var committedState *subproductBatchState
	var lastBuildErr error
	for _, attempt := range attempts {
		virtualJob := &domain.Job{
			JobID:         planKey,
			ProductID:     productID,
			QuantityTotal: maxInt(int(math.Ceil(plannedQty)), 1),
			Priority:      parentJob.Priority,
			Deadline:      attempt.PlanningDeadline,
			Status:        domain.JobStatusPlanned,
			CreatedAt:     time.Now().UTC(),
			UpdatedAt:     time.Now().UTC(),
			Notes:         "virtual_subproduct_plan",
		}
		preview, err := s.buildVirtualPreview(productID, virtualJob.QuantityTotal, virtualJob.Deadline, sharedTentative)
		if err != nil {
			return []DependentJobPlan{{
				PlanKey:           planKey,
				ParentJobID:       parentJob.JobID,
				ConsumerJobStepID: consumerStep.JobStepID,
				ProductID:         productID,
				DependencyDepth:   depth,
				RequiredQty:       shortage,
				PlannedQty:        plannedQty,
				ShortageQty:       shortage,
				PlanningStatus:    planningStatusBlocked,
				ReasonCode:        reasonCodeNoValidProcess,
				Reason:            "No valid process exists for the required subproduct.",
				Explanation: ProposalExplanation{
					Required:          shortage,
					Available:         0,
					PlannedProduction: plannedQty,
				},
			}}, nil, nil, nil, nil, 0, nil
		}
		candidateProposal, err := s.buildProposalForPreview(virtualJob, preview, sharedTentative, attempt.TargetCompletion)
		if err != nil {
			lastBuildErr = err
			continue
		}
		attemptState := state.clone()
		if err := s.decorateProposalWithInventoryPlan(virtualJob, preview, candidateProposal, sharedTentative, attemptState, rootOrder, attempt.TargetCompletion); err != nil {
			lastBuildErr = err
			continue
		}
		proposal = candidateProposal
		if proposal.Feasible {
			committedState = attemptState
			break
		}
	}
	if proposal == nil {
		if lastBuildErr != nil {
			return nil, nil, nil, nil, nil, 0, lastBuildErr
		}
		return nil, nil, nil, nil, nil, 0, fmt.Errorf("failed to build child proposal for %s", productID)
	}
	childStatus := planningStatusPlanned
	childReasonCode := ""
	childReason := ""
	if !proposal.Feasible {
		childStatus, childReasonCode, childReason = summarizeDependentProposalFailure(proposal)
	}
	childPlan := DependentJobPlan{
		PlanKey:             planKey,
		ParentJobID:         parentJob.JobID,
		ConsumerJobStepID:   consumerStep.JobStepID,
		ProductID:           productID,
		DependencyDepth:     depth,
		RequiredQty:         shortage,
		PlannedQty:          plannedQty,
		ShortageQty:         shortage,
		ExistingStock:       math.Max(shortage-shortage, 0),
		FutureStockQty:      0,
		EstimatedCompletion: proposal.EstimatedCompletion,
		PlanningStatus:      childStatus,
		ReasonCode:          childReasonCode,
		Reason:              childReason,
		Explanation: ProposalExplanation{
			Required:          shortage,
			Available:         0,
			PlannedProduction: plannedQty,
		},
		ProposedSlots: proposal.ProposedSlots,
	}
	deps := []DependentJobPlan{childPlan}
	if len(proposal.DependentJobs) > 0 {
		deps = append(deps, proposal.DependentJobs...)
	}
	if proposal.Feasible && committedState != nil {
		state.ledger = committedState.ledger
		state.totalGeneratedNodes = committedState.totalGeneratedNodes
		tentative := proposedSlotsToTentatives(proposal.ProposedSlots)
		return deps, append([]InventoryAction{}, proposal.InventoryActions...), tentative, proposal.EstimatedCompletion, append([]materialAccelerationNeed(nil), proposal.materialAccelerationNeeds...), len(proposal.DependentJobs), nil
	}
	return deps, append([]InventoryAction{}, proposal.InventoryActions...), nil, nil, append([]materialAccelerationNeed(nil), proposal.materialAccelerationNeeds...), len(proposal.DependentJobs), nil
}

func buildChildPlanningAttempts(parentDeadline time.Time, parentTargetCompletion *time.Time, needAt time.Time) []childPlanningAttempt {
	needAt = alignSuccessorStart(needAt.UTC())
	baseDeadline := needAt
	if !parentDeadline.IsZero() && parentDeadline.After(baseDeadline) {
		baseDeadline = alignSuccessorStart(parentDeadline.UTC())
	}
	if parentTargetCompletion != nil && !parentTargetCompletion.IsZero() {
		targetDeadline := alignSuccessorStart(parentTargetCompletion.UTC())
		if targetDeadline.After(baseDeadline) {
			baseDeadline = targetDeadline
		}
	}
	attempts := make([]childPlanningAttempt, 0, 3)
	firstTarget := needAt
	attempts = append(attempts, childPlanningAttempt{
		PlanningDeadline: baseDeadline,
		TargetCompletion: &firstTarget,
	})
	relaxedDeadline := baseDeadline.Add(30 * 24 * time.Hour)
	relaxedDeadline = alignSuccessorStart(relaxedDeadline.UTC())
	attempts = append(attempts, childPlanningAttempt{
		PlanningDeadline: relaxedDeadline,
		TargetCompletion: nil,
	})
	maxDeadline := alignSuccessorStart(time.Now().UTC().Add(time.Duration(maxHorizonDays) * 24 * time.Hour))
	if maxDeadline.After(relaxedDeadline) {
		attempts = append(attempts, childPlanningAttempt{
			PlanningDeadline: maxDeadline,
			TargetCompletion: nil,
		})
	}
	return attempts
}

func isPlannedDependentJob(plans []DependentJobPlan, planKey string) bool {
	for _, plan := range plans {
		if plan.PlanKey == planKey && plan.PlanningStatus == planningStatusPlanned {
			return true
		}
	}
	return false
}

func dependentJobPlanByKey(plans []DependentJobPlan, planKey string) *DependentJobPlan {
	for i := range plans {
		if plans[i].PlanKey == planKey {
			return &plans[i]
		}
	}
	return nil
}

func summarizeDependentProposalFailure(proposal *SchedulingProposal) (string, string, string) {
	if proposal == nil {
		return planningStatusBlocked, reasonCodeSubproductShortage, "Dependency proposal is not feasible."
	}
	for _, dep := range proposal.DependentJobs {
		if dep.PlanningStatus == planningStatusPlanned {
			continue
		}
		status := dep.PlanningStatus
		if status == "" {
			status = planningStatusBlocked
		}
		reasonCode := dep.ReasonCode
		if strings.TrimSpace(reasonCode) == "" {
			reasonCode = reasonCodeSubproductShortage
		}
		reason := dep.Reason
		if strings.TrimSpace(reason) == "" {
			reason = "Dependency proposal is not feasible."
		}
		return status, reasonCode, reason
	}
	for _, blocked := range proposal.BlockedReasons {
		if code := blockedReasonCode(blocked); code != "" {
			return planningStatusBlocked, code, blocked
		}
	}
	return planningStatusBlocked, reasonCodeSubproductShortage, "Dependency proposal is not feasible."
}

func blockedReasonCode(reason string) string {
	reason = strings.TrimSpace(reason)
	const prefix = "reason_code="
	if !strings.HasPrefix(reason, prefix) {
		return ""
	}
	rest := strings.TrimSpace(strings.TrimPrefix(reason, prefix))
	if rest == "" {
		return ""
	}
	if idx := strings.IndexAny(rest, " :"); idx >= 0 {
		return rest[:idx]
	}
	return rest
}

func latestDependencyReadyAt(childCompletion, availabilityReadyAt *time.Time) *time.Time {
	switch {
	case childCompletion == nil && availabilityReadyAt == nil:
		return nil
	case childCompletion == nil:
		ready := alignSuccessorStart(availabilityReadyAt.UTC())
		return &ready
	case availabilityReadyAt == nil:
		ready := alignSuccessorStart(childCompletion.UTC())
		return &ready
	default:
		childReady := alignSuccessorStart(childCompletion.UTC())
		availabilityReady := alignSuccessorStart(availabilityReadyAt.UTC())
		if availabilityReady.After(childReady) {
			return &availabilityReady
		}
		return &childReady
	}
}

func latestShortDemandReadyAt(demands []*DemandMaterial) (*time.Time, bool) {
	var latest time.Time
	haveLatest := false
	for _, demand := range demands {
		if demand == nil {
			continue
		}
		if demand.ReadyAt == nil || demand.ReadyAt.IsZero() {
			return nil, false
		}
		ready := alignSuccessorStart(demand.ReadyAt.UTC())
		if !haveLatest || ready.After(latest) {
			latest = ready
			haveLatest = true
		}
	}
	if !haveLatest {
		return nil, false
	}
	return &latest, true
}

func shortDemandMaterialIDs(demands []*DemandMaterial) []string {
	ids := make([]string, 0, len(demands))
	for _, demand := range demands {
		if demand == nil || strings.TrimSpace(demand.MaterialID) == "" {
			continue
		}
		ids = append(ids, demand.MaterialID)
	}
	sort.Strings(ids)
	return ids
}

func setDependentJobPlanStatus(plans []DependentJobPlan, planKey, status, reasonCode, reason string) {
	for i := range plans {
		if plans[i].PlanKey != planKey {
			continue
		}
		plans[i].PlanningStatus = status
		plans[i].ReasonCode = reasonCode
		plans[i].Reason = reason
		return
	}
}

func normalizeFeasibleDependentJobPlans(proposal *SchedulingProposal) {
	if proposal == nil || !proposal.Feasible {
		return
	}
	for i := range proposal.DependentJobs {
		dep := &proposal.DependentJobs[i]
		if dep.PlanningStatus != planningStatusUnschedulable {
			continue
		}
		if dep.ReasonCode != reasonCodeChildJobLate {
			continue
		}
		if len(dep.ProposedSlots) == 0 {
			continue
		}
		dep.PlanningStatus = planningStatusPlanned
		dep.ReasonCode = ""
		dep.Reason = ""
	}
}

func (s *AIPredictiveService) repairReflowedProposalSuffix(jobID string, proposal *SchedulingProposal, tentativeSlots []TentativeSlot, targetCompletion *time.Time) error {
	if proposal == nil {
		return nil
	}
	if err := s.validateProposalSlotsStrict(jobID, proposal); err == nil {
		return nil
	}
	targetByJob := map[string]*time.Time{}
	if targetCompletion != nil {
		targetByJob[jobID] = targetCompletion
	}
	if err := s.chainAwareForwardRepair([]*SchedulingProposal{proposal}, chainRepairPassBudget([]*SchedulingProposal{proposal}), tentativeSlots, targetByJob); err != nil {
		return err
	}
	return s.validateProposalSlotsStrict(jobID, proposal)
}

func (s *AIPredictiveService) buildVirtualPreview(productID string, quantity int, deadline time.Time, tentative []TentativeSlot) (*SolverPreview, error) {
	process, err := s.scheduling.processRepo.GetProcessByProductIDAsOf(productID, time.Now())
	if err != nil || process == nil {
		return nil, err
	}
	steps, err := s.scheduling.processRepo.ListStepsByProcessID(process.ProcessID)
	if err != nil {
		return nil, err
	}
	cursor := roundUpToHalfHour(time.Now().UTC())
	wideWindow := virtualPreviewWindow(cursor, deadline)
	preview := &SolverPreview{
		JobID:         "virtual-" + productID,
		ProductID:     productID,
		QuantityTotal: quantity,
		Priority:      domain.JobPriorityMedium,
		Deadline:      alignSuccessorStart(deadline.UTC()),
		CanStartNow:   true,
		Steps:         make([]SolverPreviewStep, 0, len(steps)),
	}
	for _, processStep := range steps {
		candidates, err := s.scheduling.CandidateMachinesForStepWithTentative(processStep.StepID, cursor, cursor.Add(wideWindow), tentative)
		if err != nil {
			return nil, err
		}
		durationMetrics := stepDurationMetrics(processStep, candidates, float64(quantity))
		preview.Steps = append(preview.Steps, SolverPreviewStep{
			JobStepID:              processStep.StepID,
			StepID:                 processStep.StepID,
			StepName:               processStep.StepName,
			StepType:               processStep.StepType,
			StepSequence:           processStep.StepSequence,
			QuantityTarget:         quantity,
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
			ActualDurationMins:     durationMetrics.ActualDurationMins,
			EstimatedDurationMins:  durationMetrics.ReservedDurationMins,
			RoundingOverheadMins:   durationMetrics.RoundingOverheadMins,
			CandidateMachines:      candidates,
		})
		cursor = alignSuccessorStart(cursor.Add(durationMetrics.ReservedDuration).Add(time.Duration(processStep.MinWaitMinutes+processStep.TransferMinutes) * time.Minute))
	}
	return preview, nil
}

func virtualPreviewWindow(cursor, deadline time.Time) time.Duration {
	minWindow := 30 * 24 * time.Hour
	buffer := 30 * 24 * time.Hour
	maxWindow := time.Duration(maxHorizonDays) * 24 * time.Hour
	if cursor.IsZero() {
		cursor = roundUpToHalfHour(time.Now().UTC())
	}
	window := maxWindow
	if !deadline.IsZero() && deadline.After(cursor) {
		deadlineWindow := deadline.Sub(cursor) + buffer
		if deadlineWindow > window {
			window = deadlineWindow
		}
	}
	if window < minWindow {
		window = minWindow
	}
	return window
}

func (s *AIPredictiveService) resolveSubproductSource(parentProductID, componentProductID string) (string, bool) {
	product, err := s.scheduling.productRepo.GetByID(parentProductID)
	if err != nil || product == nil {
		return domain.IngredientSourceMake, s.hasProcess(componentProductID)
	}
	ingredients, bomItems, _, err := s.scheduling.loadProductComponents(product)
	if err == nil {
		for _, ingredient := range ingredients {
			if ingredient.ProductID != nil && *ingredient.ProductID == componentProductID {
				return ingredient.Source, s.hasProcess(componentProductID)
			}
		}
		for _, item := range bomItems {
			if item.ProductComponentID != nil && *item.ProductComponentID == componentProductID {
				return domain.IngredientSourceMake, s.hasProcess(componentProductID)
			}
		}
	}
	return domain.IngredientSourceMake, s.hasProcess(componentProductID)
}

func (s *AIPredictiveService) hasProcess(productID string) bool {
	process, err := s.scheduling.processRepo.GetProcessByProductIDAsOf(productID, time.Now())
	return err == nil && process != nil
}

func (s *AIPredictiveService) roundPlannedSubproductQty(productID string, required float64) float64 {
	process, err := s.scheduling.processRepo.GetProcessByProductIDAsOf(productID, time.Now())
	if err != nil || process == nil {
		return required
	}
	steps, err := s.scheduling.processRepo.ListStepsByProcessID(process.ProcessID)
	if err != nil || len(steps) == 0 {
		return required
	}
	last := steps[len(steps)-1]
	lot := maxInt(last.MinBatchSize, last.BatchSize)
	if lot <= 1 {
		return required
	}
	return math.Ceil(required/float64(lot)) * float64(lot)
}

func (s *AIPredictiveService) productAvailabilityForPlanning(productID string, requiredQty float64, at time.Time, ledger *tentativeInventoryLedger, allowedRootJobID string) (*productAvailabilityResult, error) {
	at = alignSuccessorStart(at.UTC())
	records, err := s.scheduling.inventoryRepo.ListProductInventoryByProductID(productID)
	if err != nil {
		return nil, err
	}
	pendingReservations, err := s.scheduling.inventoryRepo.ListProductReservations(productID, domain.InventoryReservationStatusPending)
	if err != nil {
		return nil, err
	}
	type event struct {
		At    time.Time
		Delta float64
	}
	availableNow := ledger.productBaseline[productID]
	events := make([]event, 0, len(records)+len(pendingReservations)+len(ledger.activeEntries))
	for _, record := range records {
		available := math.Max(record.QuantityOnHand-record.QuantityReserved, 0)
		when := alignSuccessorStart(record.AvailableFrom.UTC())
		if when.After(at) {
			events = append(events, event{At: when, Delta: available})
			continue
		}
		availableNow += available
	}
	for _, res := range pendingReservations {
		when := alignSuccessorStart(res.NeededAt.UTC())
		if when.After(at) {
			events = append(events, event{At: when, Delta: -res.ReservedQty})
			continue
		}
		availableNow -= res.ReservedQty
	}
	for _, entry := range ledger.activeEntries {
		if entry.Action.ResourceID != productID {
			continue
		}
		if !ledgerProductActionVisibleToRoot(entry.Action, allowedRootJobID) {
			continue
		}
		delta := 0.0
		switch entry.Action.ActionType {
		case inventoryActionReserveProduct:
			delta = -entry.Action.Quantity
		case inventoryActionProduceProduct:
			delta = entry.Action.Quantity
		default:
			continue
		}
		if entry.EffectiveAt.After(at) {
			events = append(events, event{At: entry.EffectiveAt, Delta: delta})
			continue
		}
		availableNow += delta
	}
	sort.Slice(events, func(i, j int) bool {
		if events[i].At.Equal(events[j].At) {
			return events[i].Delta > events[j].Delta
		}
		return events[i].At.Before(events[j].At)
	})
	result := &productAvailabilityResult{
		AvailableNow: math.Max(availableNow, 0),
		ShortageQty:  math.Max(requiredQty-availableNow, 0),
	}
	if availableNow >= requiredQty {
		return result, nil
	}
	current := availableNow
	for _, entry := range events {
		current += entry.Delta
		if current > result.FutureQty {
			result.FutureQty = current
		}
		if current >= requiredQty {
			ready := entry.At
			result.ReadyAt = &ready
			result.ShortageQty = 0
			return result, nil
		}
	}
	return result, nil
}

func ledgerProductActionVisibleToRoot(action InventoryAction, allowedRootJobID string) bool {
	return true
}

func ledgerRootJobID(jobID string) string {
	jobID = strings.TrimSpace(jobID)
	if jobID == "" {
		return ""
	}
	if idx := strings.Index(jobID, "|"); idx > 0 {
		return jobID[:idx]
	}
	return jobID
}

func (s *AIPredictiveService) localWIPAvailability(jobID, jobStepID, productID string, at time.Time, actions []InventoryAction) float64 {
	total := 0.0
	if strings.HasPrefix(jobStepID, "JS-") {
		total += s.scheduling.wipAvailableAtStep(jobStepID, productID)
	}
	for _, action := range actions {
		if action.JobID != jobID || action.ResourceID != productID || action.EffectiveAt.After(at) {
			continue
		}
		switch action.ActionType {
		case inventoryActionProduceWIP:
			total += action.Quantity
		case inventoryActionConsumeWIP:
			total -= action.Quantity
		}
	}
	if total < 0 {
		return 0
	}
	return total
}

func (s *AIPredictiveService) hasSameJobConsumer(preview *SolverPreview, stepByJobStep map[string]SolverPreviewStep, currentSequence int, productID string) bool {
	if preview == nil || s.scheduling.psmRepo == nil {
		return false
	}
	for _, step := range preview.Steps {
		if step.StepSequence <= currentSequence {
			continue
		}
		inputs, err := s.scheduling.psmRepo.ListInputsByStepID(step.StepID)
		if err != nil {
			continue
		}
		for _, input := range inputs {
			if input.ProductID != nil && *input.ProductID == productID {
				return true
			}
		}
	}
	_ = stepByJobStep
	return false
}

func (s *AIPredictiveService) addBlockedDependency(proposal *SchedulingProposal, parentJobID, consumerJobStepID, productID string, shortage float64, availability *productAvailabilityResult, reasonCode, reason string) {
	if proposal == nil {
		return
	}
	dep := DependentJobPlan{
		PlanKey:            fmt.Sprintf("%s|%s|blocked|%s", parentJobID, consumerJobStepID, productID),
		ParentJobID:        parentJobID,
		ConsumerJobStepID:  consumerJobStepID,
		ProductID:          productID,
		RequiredQty:        shortage,
		PlannedQty:         shortage,
		ShortageQty:        shortage,
		ExistingStock:      availability.AvailableNow,
		FutureStockQty:     availability.FutureQty,
		FutureStockReadyAt: availability.ReadyAt,
		PlanningStatus:     planningStatusBlocked,
		ReasonCode:         reasonCode,
		Reason:             reason,
		Explanation: ProposalExplanation{
			Required:          shortage,
			Available:         availability.AvailableNow,
			PlannedProduction: shortage,
		},
	}
	proposal.DependentJobs = append(proposal.DependentJobs, dep)
	proposal.Feasible = false
	proposal.BlockedReasons = appendUniqueString(proposal.BlockedReasons, "reason_code="+reasonCode)
}

type slotBounds struct {
	Start time.Time
	End   time.Time
}

func boundsByJobStep(slots []ProposedSlot) map[string]slotBounds {
	result := make(map[string]slotBounds)
	for _, slot := range slots {
		bounds, ok := result[slot.JobStepID]
		if !ok {
			result[slot.JobStepID] = slotBounds{Start: slot.ScheduledStart, End: slot.ScheduledEnd}
			continue
		}
		if slot.ScheduledStart.Before(bounds.Start) {
			bounds.Start = slot.ScheduledStart
		}
		if slot.ScheduledEnd.After(bounds.End) {
			bounds.End = slot.ScheduledEnd
		}
		result[slot.JobStepID] = bounds
	}
	return result
}

func stepSequenceIndex(preview *SolverPreview) map[string]int {
	result := make(map[string]int, len(preview.Steps))
	for _, step := range preview.Steps {
		result[step.JobStepID] = step.StepSequence
	}
	return result
}

func previewStepIndex(preview *SolverPreview) map[string]SolverPreviewStep {
	result := make(map[string]SolverPreviewStep, len(preview.Steps))
	for _, step := range preview.Steps {
		result[step.JobStepID] = step
	}
	return result
}

func (s *AIPredictiveService) shiftProposalSuffix(proposal *SchedulingProposal, jobStepID string, delta time.Duration, stepSequence map[string]int) {
	if proposal == nil || delta <= 0 {
		return
	}
	sequence := stepSequence[jobStepID]
	for i := range proposal.ProposedSlots {
		if stepSequence[proposal.ProposedSlots[i].JobStepID] < sequence {
			continue
		}
		duration := ceilDurationTo30Min(proposal.ProposedSlots[i].ScheduledEnd.Sub(proposal.ProposedSlots[i].ScheduledStart))
		proposal.ProposedSlots[i].ScheduledStart = alignSuccessorStart(proposal.ProposedSlots[i].ScheduledStart.Add(delta))
		proposal.ProposedSlots[i].ScheduledEnd = proposal.ProposedSlots[i].ScheduledStart.Add(duration)
	}
	recomputeProposalBounds(proposal)
}

func proposedSlotsToTentatives(slots []ProposedSlot) []TentativeSlot {
	out := make([]TentativeSlot, 0, len(slots))
	for _, slot := range slots {
		out = append(out, TentativeSlot{
			MachineID:      slot.MachineID,
			ScheduledStart: slot.ScheduledStart,
			ScheduledEnd:   slot.ScheduledEnd,
		})
	}
	return out
}

func appendUniqueString(items []string, item string) []string {
	for _, existing := range items {
		if existing == item {
			return items
		}
	}
	return append(items, item)
}

func stripInventoryActionsForResponse(proposal *SchedulingProposal, include bool) *SchedulingProposal {
	if proposal == nil || include {
		return proposal
	}
	cp := *proposal
	cp.InventoryActions = nil
	if len(proposal.DependentJobs) > 0 {
		cp.DependentJobs = append([]DependentJobPlan(nil), proposal.DependentJobs...)
	}
	return &cp
}

func canonicalProposalForPersistence(proposal *SchedulingProposal) *SchedulingProposal {
	if proposal == nil {
		return nil
	}
	cp := *proposal
	if len(proposal.InventoryActions) > 0 {
		cp.InventoryActions = append([]InventoryAction(nil), proposal.InventoryActions...)
	}
	if len(proposal.DependentJobs) > 0 {
		cp.DependentJobs = append([]DependentJobPlan(nil), proposal.DependentJobs...)
	}
	return &cp
}

func generatedJobIDMap(jobSteps []domain.JobSteps) map[string]string {
	result := make(map[string]string, len(jobSteps))
	for _, step := range jobSteps {
		result[step.StepID] = step.JobStepID
	}
	return result
}

type stepMaterialCheckResult struct {
	AnyShort     bool
	ShortDemands []*DemandMaterial
	Partial      *PartialFeasibilityPlan
	DeferredNode *DeferredPlanningNode
}

func materialAccelerationNeedsFromShortDemands(jobID, jobStepID string, needAt, readyAt time.Time, demands []*DemandMaterial) []materialAccelerationNeed {
	out := make([]materialAccelerationNeed, 0, len(demands))
	needAt = normalizeMaterialEventTime(needAt)
	readyAt = normalizeMaterialEventTime(readyAt)
	if !readyAt.After(needAt) {
		return out
	}
	for _, demand := range demands {
		if demand == nil || strings.TrimSpace(demand.MaterialID) == "" {
			continue
		}
		slotDeficit := roundDisplayQty(demand.RequiredQty - math.Max(demand.AvailableQty, 0))
		if slotDeficit <= 0 {
			continue
		}
		out = append(out, materialAccelerationNeed{
			MaterialID:   strings.TrimSpace(demand.MaterialID),
			JobID:        strings.TrimSpace(jobID),
			JobStepID:    strings.TrimSpace(jobStepID),
			NeedAt:       needAt,
			ReadyAt:      readyAt,
			RequiredQty:  roundDisplayQty(demand.RequiredQty),
			AvailableQty: roundDisplayQty(math.Max(demand.AvailableQty, 0)),
			ShortageQty:  slotDeficit,
		})
	}
	return out
}

func appendMaterialAccelerationNeeds(proposal *SchedulingProposal, needs []materialAccelerationNeed) {
	if proposal == nil || len(needs) == 0 {
		return
	}
	seen := make(map[string]struct{}, len(proposal.materialAccelerationNeeds)+len(needs))
	for _, existing := range proposal.materialAccelerationNeeds {
		seen[materialAccelerationNeedSignature(existing)] = struct{}{}
	}
	for _, need := range needs {
		sig := materialAccelerationNeedSignature(need)
		if _, ok := seen[sig]; ok {
			continue
		}
		proposal.materialAccelerationNeeds = append(proposal.materialAccelerationNeeds, need)
		seen[sig] = struct{}{}
	}
}

func materialAccelerationNeedSignature(need materialAccelerationNeed) string {
	return strings.Join([]string{
		strings.TrimSpace(need.MaterialID),
		strings.TrimSpace(need.JobID),
		strings.TrimSpace(need.JobStepID),
		normalizeMaterialEventTime(need.NeedAt).Format(time.RFC3339),
		normalizeMaterialEventTime(need.ReadyAt).Format(time.RFC3339),
		fmt.Sprintf("%.4f", roundDisplayQty(need.ShortageQty)),
	}, "|")
}

func (s *AIPredictiveService) checkAllStepMaterials(step SolverPreviewStep, consumeAt time.Time, inputs []domain.ProcessStepMaterial, state *subproductBatchState) (*stepMaterialCheckResult, error) {
	result := &stepMaterialCheckResult{}
	blocking := make([]string, 0)
	minFeasibleUnits := float64(step.QuantityTarget)
	for _, input := range inputs {
		if input.MaterialID == nil {
			continue
		}
		required := float64(step.QuantityTarget) * input.QuantityPerUnit
		ledger := newTentativeInventoryLedger()
		if state != nil && state.ledger != nil {
			ledger = state.ledger
		}
		opening, events, err := s.buildMaterialTimeline(*input.MaterialID, consumeAt, ledger)
		if err != nil {
			return nil, err
		}
		available := opening
		shortage := math.Max(required-available, 0)
		enoughNow := available >= required
		var readyAt *time.Time
		if !enoughNow {
			current := available
			for _, event := range events {
				current += event.Delta
				if current >= required {
					ready := event.At
					readyAt = &ready
					shortage = 0
					break
				}
			}
			if shortage > 0 {
				shortage = math.Max(required-current, 0)
			}
		}
		mat := &DemandMaterial{
			MaterialID:   *input.MaterialID,
			MaterialName: "",
			RequiredQty:  required,
			Unit:         "",
			ReservedQty:  0,
			AvailableQty: available,
			EnoughNow:    enoughNow,
			ShortageQty:  shortage,
			ReadyAt:      readyAt,
		}

		if !enoughNow {
			result.AnyShort = true
			blocking = append(blocking, *input.MaterialID)
			result.ShortDemands = append(result.ShortDemands, mat)
		}
		if input.QuantityPerUnit > 0 {
			availableUnits := math.Max(mat.AvailableQty, 0) / input.QuantityPerUnit
			if availableUnits < minFeasibleUnits {
				minFeasibleUnits = availableUnits
			}
		}
	}
	if result.AnyShort && minFeasibleUnits > 0 && minFeasibleUnits < float64(step.QuantityTarget) {
		deferredQty := float64(step.QuantityTarget) - minFeasibleUnits
		deferredKey := "deferred-" + step.JobStepID + "-" + id.New()
		partial := &PartialFeasibilityPlan{
			FeasibleQty:          minFeasibleUnits,
			DeferredQty:          deferredQty,
			DeferredUntil:        nil,
			BlockingMaterials:    blocking,
			DeferredPlanningNode: deferredKey,
		}
		node := &DeferredPlanningNode{
			PlanKey:           deferredKey,
			ParentJobID:       "",
			JobStepID:         step.JobStepID,
			DeferredQty:       deferredQty,
			EarliestStartAt:   normalizeMaterialEventTime(consumeAt.Add(30 * time.Minute)),
			BlockingMaterials: blocking,
			PlanningStatus:    "pending_deferred",
		}
		result.Partial = partial
		result.DeferredNode = node
	}
	return result, nil
}

func newGeneratedJob(productID string, quantity int, deadline time.Time, notes string) *domain.Job {
	return &domain.Job{
		JobID:         id.NewPrefixed(id.PrefixJob),
		ProductID:     productID,
		QuantityTotal: quantity,
		Priority:      domain.JobPriorityMedium,
		Deadline:      alignSuccessorStart(deadline.UTC()),
		Status:        domain.JobStatusPlanned,
		CreatedAt:     time.Now().UTC(),
		UpdatedAt:     time.Now().UTC(),
		Notes:         notes,
	}
}
