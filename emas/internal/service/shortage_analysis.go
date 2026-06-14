package service

import (
	"context"
	"crypto/sha256"
	"emas/internal/domain"
	"emas/pkg/id"
	"emas/pkg/logger"
	"encoding/hex"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"

	"go.uber.org/zap"
)

// roundDisplayQty normalizes quantities returned in shortage/replenishment JSON so UIs
// do not show IEEE-754 tails (e.g. 216.60000000000002).
func roundDisplayQty(q float64) float64 {
	if q <= 0 {
		return 0
	}
	return mathRound(q, 4)
}

type ReplenishmentArrivalInput struct {
	OptionType        string
	MaterialID        string
	Quantity          float64
	ArriveAt          time.Time
	Notes             string
	InventorySnapshot *InventorySnapshot
}

type ReplenishAndReplanInput struct {
	Arrivals            []ReplenishmentArrivalInput
	Attempt             int
	PreviousDeficits    map[string]float64
	PreviousGlobalScore float64
	AllowPartial        bool
}

type shortageTimelineEvent struct {
	At    time.Time
	Delta float64
}

type aggregateInventoryEvent struct {
	At    time.Time
	Delta float64
	JobID string
}

func sortAggregateInventoryEvents(events []aggregateInventoryEvent) {
	sort.Slice(events, func(i, j int) bool {
		if events[i].At.Equal(events[j].At) {
			if events[i].Delta == events[j].Delta {
				return events[i].JobID < events[j].JobID
			}
			return events[i].Delta > events[j].Delta
		}
		return events[i].At.Before(events[j].At)
	})
}

func normalizeMaterialEventTime(t time.Time) time.Time {
	return alignSuccessorStart(t.UTC())
}

func isLikelyRawMaterialID(id string) bool {
	return strings.HasPrefix(strings.ToUpper(strings.TrimSpace(id)), "MAT-")
}

// batchMaterialShortageFloorFromProposals takes the peak (max) deficit,
// rather than summing them, because individual proposal evaluations
// already accumulate sequential ledger demand.
func batchMaterialShortageFloorFromProposals(proposals []*SchedulingProposal, materialID string) float64 {
	maxVal := 0.0
	for _, p := range proposals {
		if p == nil {
			continue
		}

		// Sum deficits within the same proposal (if multiple steps require it)
		proposalSum := 0.0
		for _, sh := range p.MaterialShortages {
			if sh.MaterialID != materialID {
				continue
			}
			proposalSum += sh.MaxDeficit
		}

		// Take the highest cumulative deficit across all evaluated proposals
		if proposalSum > maxVal {
			maxVal = proposalSum
		}
	}
	return roundDisplayQty(maxVal)
}

func batchMaterialShortageMinStart(proposals []*SchedulingProposal, materialID string) (time.Time, bool) {
	var best time.Time
	ok := false
	for _, p := range proposals {
		if p == nil {
			continue
		}
		for _, sh := range p.MaterialShortages {
			if sh.MaterialID != materialID {
				continue
			}
			if sh.ShortageStartAt.IsZero() {
				continue
			}
			t := sh.ShortageStartAt.UTC()
			if !ok || t.Before(best) {
				best = t
				ok = true
			}
		}
	}
	return best, ok
}

func (s *AIPredictiveService) computeInventorySnapshot(materialID string) (*InventorySnapshot, error) {
	mat, err := s.scheduling.inventoryRepo.GetMaterialByID(materialID)
	if err != nil {
		return nil, err
	}
	sumRes, err := s.scheduling.inventoryRepo.SumActiveReservations(materialID)
	if err != nil {
		return nil, err
	}
	arrivals, err := s.scheduling.inventoryRepo.ListExpectedArrivals(materialID, nil, nil, domain.ExpectedArrivalStatusPending)
	if err != nil {
		return nil, err
	}
	sumArr := 0.0
	for _, a := range arrivals {
		sumArr += a.Quantity
	}
	raw := fmt.Sprintf("%s:%.6f:%.6f:%.6f", materialID, mat.CurrentStock, sumRes, sumArr)
	hash := sha256.Sum256([]byte(raw))
	return &InventorySnapshot{
		MaterialID: materialID,
		Version:    hex.EncodeToString(hash[:]),
		ComputedAt: time.Now().UTC(),
	}, nil
}

func (s *AIPredictiveService) buildMaterialTimeline(materialID string, at time.Time, ledger *tentativeInventoryLedger) (float64, []shortageTimelineEvent, error) {
	at = normalizeMaterialEventTime(at)
	mat, err := s.scheduling.inventoryRepo.GetMaterialByID(materialID)
	if err != nil {
		return 0, nil, err
	}
	var excluded []string
	if ledger != nil {
		excluded = ledger.excludedJobIDs
	}
	sumResUntil, err := s.scheduling.inventoryRepo.SumActiveReservationsUntilExcluding(materialID, at, excluded)
	if err != nil {
		return 0, nil, err
	}
	opening := mat.CurrentStock - sumResUntil
	events := make([]shortageTimelineEvent, 0, 32)

	arrivals, err := s.scheduling.inventoryRepo.ListExpectedArrivals(materialID, nil, nil, domain.ExpectedArrivalStatusPending)
	if err != nil {
		return 0, nil, err
	}
	for _, arrival := range arrivals {
		when := normalizeMaterialEventTime(arrival.ExpectedArriveAt)
		if !when.After(at) {
			opening += arrival.Quantity
			continue
		}
		events = append(events, shortageTimelineEvent{
			At:    when,
			Delta: arrival.Quantity,
		})
	}
	reservations, err := s.scheduling.inventoryRepo.ListReservationsExcluding(materialID, domain.InventoryReservationStatusPending, excluded)
	if err != nil {
		return 0, nil, err
	}
	for _, res := range reservations {
		when := normalizeMaterialEventTime(res.NeededAt)
		if !when.After(at) {
			continue
		}
		events = append(events, shortageTimelineEvent{
			At:    when,
			Delta: -res.ReservedQty,
		})
	}
	if ledger != nil {
		// Match materialAvailabilityForPlanning: baseline carries all pre-`at` state,
		// and the timeline only contains events strictly after `at`.
		// materialBaseline is negative for reservations, so adding it reduces opening.
		opening += ledger.materialBaseline[materialID]
		for _, entry := range ledger.activeEntries {
			if entry.Action.ActionType != inventoryActionReserveMaterial || entry.Action.ResourceID != materialID {
				continue
			}
			when := normalizeMaterialEventTime(entry.EffectiveAt)
			if !when.After(at) {
				opening -= entry.Action.Quantity
				continue
			}
			events = append(events, shortageTimelineEvent{
				At:    when,
				Delta: -entry.Action.Quantity,
			})
		}
		// Virtual arrivals: injected by the convergence loop with a specific
		// future timestamp. Only appear as opening if they arrive on or before `at`;
		// otherwise they appear as a positive forward-scan event — exactly like a
		// real expected_arrival row from the DB.
		for _, va := range ledger.virtualArrivals {
			if va.MaterialID != materialID || va.Qty <= 0 {
				continue
			}
			if !va.At.After(at) {
				opening += va.Qty
			} else {
				events = append(events, shortageTimelineEvent{
					At:    va.At,
					Delta: va.Qty,
				})
			}
		}
	}
	sort.Slice(events, func(i, j int) bool {
		if events[i].At.Equal(events[j].At) {
			return events[i].Delta > events[j].Delta
		}
		return events[i].At.Before(events[j].At)
	})
	return opening, events, nil
}

// buildMaterialReplenishOptionsForSubproductManufacture emits raw-material replenish rows
// needed to manufacture `manufactureUnits` of `dependencyProductID`.
func (s *AIPredictiveService) buildMaterialReplenishOptionsForSubproductManufacture(
	dependencyProductID string,
	manufactureUnits float64,
	needAt time.Time,
	affectedJobIDs []string,
	ledger *tentativeInventoryLedger,
) ([]ShortageResolutionOption, error) {
	if manufactureUnits <= 0 || strings.TrimSpace(dependencyProductID) == "" {
		return nil, nil
	}
	product, err := s.scheduling.productRepo.GetByID(dependencyProductID)
	if err != nil {
		return nil, err
	}
	ingredients, bomItems, _, err := s.scheduling.loadProductComponents(product)
	if err != nil {
		return nil, err
	}
	type matAgg struct {
		qty           float64
		leadTimeHours int
	}
	needs := make(map[string]*matAgg)
	for _, ing := range ingredients {
		if ing.ComponentType != domain.ComponentTypeMaterial || ing.MaterialID == nil {
			continue
		}
		mid := strings.TrimSpace(*ing.MaterialID)
		if mid == "" {
			continue
		}
		req := manufactureUnits * ing.QuantityPerUnit * (1.0 + ing.ScrapRate)
		if req <= 0 {
			continue
		}
		if needs[mid] == nil {
			needs[mid] = &matAgg{}
		}
		needs[mid].qty += req
		if ing.LeadTimeHours > needs[mid].leadTimeHours {
			needs[mid].leadTimeHours = ing.LeadTimeHours
		}
	}
	for _, b := range bomItems {
		if b.ComponentType != domain.ComponentTypeMaterial || b.MaterialID == nil {
			continue
		}
		mid := strings.TrimSpace(*b.MaterialID)
		if mid == "" {
			continue
		}
		req := manufactureUnits * b.QuantityRequired * (1.0 + b.ScrapRate)
		if req <= 0 {
			continue
		}
		if needs[mid] == nil {
			needs[mid] = &matAgg{}
		}
		needs[mid].qty += req
	}
	if len(needs) == 0 {
		return nil, nil
	}
	out := make([]ShortageResolutionOption, 0, len(needs))
	for mid, agg := range needs {
		mat, err := s.scheduling.inventoryRepo.GetMaterialByID(mid)
		if err != nil {
			continue
		}
		netQty, err := s.netMaterialDeficitByNeedTime(mid, agg.qty, needAt, ledger)
		if err != nil {
			return nil, err
		}
		if netQty <= 0 {
			continue
		}
		leadTimeHours := agg.leadTimeHours
		earliestPossible := normalizeMaterialEventTime(time.Now().UTC().Add(time.Duration(leadTimeHours) * time.Hour))
		safeAt := normalizeMaterialEventTime(needAt.Add(-30 * time.Minute))
		suggested := safeAt
		if earliestPossible.After(suggested) {
			suggested = earliestPossible
		}
		repl := &ReplenishmentSuggestion{
			MaterialID:              mid,
			MaterialName:            mat.MaterialName,
			SuggestedQty:            netQty,
			SuggestedArriveAt:       suggested,
			EarliestPossibleArrival: earliestPossible,
			IsLeadTimeConstrained:   earliestPossible.After(needAt),
			SafetyBufferMins:        30,
			LeadTimeHours:           leadTimeHours,
			MergedFromCount:         1,
			Rationale:               "Raw material for manufacturing " + dependencyProductID + " to satisfy the dependent-job shortage.",
		}
		primaryType := "replenish"
		if repl.IsLeadTimeConstrained {
			primaryType = "delay_jobs"
		}
		out = append(out, ShortageResolutionOption{
			MaterialID:          mid,
			OptionType:          primaryType,
			Priority:            2,
			Description:         "Purchase or schedule arrival of " + mat.MaterialName + " to support production of " + dependencyProductID + ".",
			ImpactSummary:       "Material replenishment alternative when additional in-house production is not the only option.",
			Replenishment:       repl,
			AffectedJobIDs:      affectedJobIDs,
			DependencyProductID: dependencyProductID,
		})
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].MaterialID < out[j].MaterialID
	})
	return out, nil
}

func (s *AIPredictiveService) netMaterialDeficitByNeedTime(materialID string, requiredQty float64, needAt time.Time, ledger *tentativeInventoryLedger) (float64, error) {
	if requiredQty <= 0 || strings.TrimSpace(materialID) == "" {
		return 0, nil
	}
	startAt := normalizeMaterialEventTime(time.Now().UTC())
	needAt = normalizeMaterialEventTime(needAt)
	opening, events, err := s.buildMaterialTimeline(materialID, startAt, ledger)
	if err != nil {
		return 0, err
	}
	available := opening
	for _, event := range events {
		if event.At.After(needAt) {
			break
		}
		available += event.Delta
	}
	deficit := requiredQty - available
	if deficit <= 0 {
		return 0, nil
	}
	return roundDisplayQty(deficit), nil
}

func (s *AIPredictiveService) AnalyzeShortagesForProposal(jobID string) (*SchedulingProposal, error) {
	prop, err := s.BuildProposalWithOptions(jobID, true)
	if err != nil {
		return nil, err
	}
	shortages, resolutions, score, err := s.analyzeProposalMaterialShortages(prop, nil)
	if err != nil {
		return nil, err
	}
	prop.MaterialShortages = shortages
	prop.ShortageResolutions = resolutions
	prop.GlobalScore = score
	return prop, nil
}

func (s *AIPredictiveService) analyzeProposalMaterialShortages(proposal *SchedulingProposal, ledger *tentativeInventoryLedger) ([]MaterialShortageInfo, []ShortageResolutionOption, float64, error) {
	if proposal == nil {
		return nil, nil, 0, nil
	}
	grouped := make(map[string][]InventoryAction)
	for _, act := range proposal.InventoryActions {
		if act.ActionType != inventoryActionReserveMaterial {
			continue
		}
		// FIX 3: DEDUPLICATE SHORTAGE PER JOB
		// Group by ResourceID ONLY (instead of ResourceID|JobStepID).
		// Never allow ["MAT-002","MAT-002"]. This forces ONE holistic timeline per material.
		mid := strings.TrimSpace(act.ResourceID)
		grouped[mid] = append(grouped[mid], act)
	}
	shortages := make([]MaterialShortageInfo, 0)
	global := 0.0
	for materialID, actions := range grouped {
		opening, events, err := s.buildMaterialTimeline(materialID, time.Now().UTC(), ledger)
		if err != nil {
			return nil, nil, 0, err
		}
		type proposalMaterialEvent struct {
			At        time.Time
			Delta     float64
			OwnAction bool
			Action    InventoryAction
		}
		timeline := make([]proposalMaterialEvent, 0, len(events)+len(actions))
		for _, event := range events {
			timeline = append(timeline, proposalMaterialEvent{
				At:    event.At,
				Delta: event.Delta,
			})
		}
		for _, action := range actions {
			timeline = append(timeline, proposalMaterialEvent{
				At:        normalizeMaterialEventTime(action.EffectiveAt),
				Delta:     -action.Quantity,
				OwnAction: true,
				Action:    action,
			})
		}
		sort.Slice(timeline, func(i, j int) bool {
			if timeline[i].At.Equal(timeline[j].At) {
				if timeline[i].Delta == timeline[j].Delta {
					if timeline[i].OwnAction == timeline[j].OwnAction {
						return timeline[i].Action.JobStepID < timeline[j].Action.JobStepID
					}
					return !timeline[i].OwnAction
				}
				return timeline[i].Delta > timeline[j].Delta
			}
			return timeline[i].At.Before(timeline[j].At)
		})
		mat, err := s.scheduling.inventoryRepo.GetMaterialByID(materialID)
		if err != nil {
			return nil, nil, 0, err
		}
		running := opening
		maxDeficit := 0.0
		var shortageAt *time.Time
		jobStepID := ""
		for _, event := range timeline {
			before := running
			running += event.Delta
			if !event.OwnAction {
				continue
			}
			beforeDeficit := math.Max(-before, 0)
			afterDeficit := math.Max(-running, 0)
			causedDeficit := roundDisplayQty(afterDeficit - beforeDeficit)
			if causedDeficit <= 0 {
				continue
			}
			if causedDeficit > maxDeficit {
				maxDeficit = causedDeficit
			}
			if shortageAt == nil {
				t := event.At
				shortageAt = &t
				jobStepID = event.Action.JobStepID
			}
		}
		maxDeficit = roundDisplayQty(maxDeficit)
		if maxDeficit <= 0 {
			continue
		}
		global += maxDeficit
		snap, _ := s.computeInventorySnapshot(materialID)
		startAt := normalizeMaterialEventTime(time.Now().UTC())
		if shortageAt != nil {
			startAt = *shortageAt
		}
		shortages = append(shortages, MaterialShortageInfo{
			MaterialID:               materialID,
			MaterialName:             mat.MaterialName,
			Unit:                     mat.Unit,
			JobStepID:                jobStepID,
			AllStepMaterialsFeasible: false,
			ShortageStartAt:          startAt,
			MaxDeficit:               maxDeficit,
			CurrentStock:             mat.CurrentStock,
			FeasibleQty:              0,
			AffectedJobIDs:           []string{proposal.JobID},
			AffectedStepIDs:          []string{jobStepID},
			Snapshot:                 snap,
		})
	}
	sort.Slice(shortages, func(i, j int) bool {
		return shortages[i].ShortageStartAt.Before(shortages[j].ShortageStartAt)
	})
	resolutions := make([]ShortageResolutionOption, 0, len(shortages))
	for _, sh := range shortages {
		leadTimeHours := 0
		if mat, err := s.scheduling.inventoryRepo.GetMaterialByID(sh.MaterialID); err == nil {
			_ = mat
		}
		earliestPossible := normalizeMaterialEventTime(time.Now().UTC().Add(time.Duration(leadTimeHours) * time.Hour))
		safeAt := normalizeMaterialEventTime(sh.ShortageStartAt.Add(-30 * time.Minute))
		suggested := safeAt
		if earliestPossible.After(suggested) {
			suggested = earliestPossible
		}
		repl := &ReplenishmentSuggestion{
			MaterialID:              sh.MaterialID,
			MaterialName:            sh.MaterialName,
			SuggestedQty:            sh.MaxDeficit,
			SuggestedArriveAt:       suggested,
			EarliestPossibleArrival: earliestPossible,
			IsLeadTimeConstrained:   earliestPossible.After(sh.ShortageStartAt),
			SafetyBufferMins:        30,
			LeadTimeHours:           leadTimeHours,
			MergedFromCount:         1,
			Rationale:               "Cover peak projected deficit before first shortage time.",
		}
		primaryType := "replenish"
		if repl.IsLeadTimeConstrained {
			primaryType = "delay_jobs"
		}
		// Single option per raw-material shortage: either replenish or delay_jobs when
		// lead-time makes immediate replenishment infeasible. A second row duplicated the
		// same qty/time and confused clients (no distinct "delay vs buy" signal without
		// a separate timeline model).
		resolutions = append(resolutions, ShortageResolutionOption{
			MaterialID:     sh.MaterialID,
			OptionType:     primaryType,
			Priority:       1,
			Description:    "Primary recommended resolution for this material.",
			ImpactSummary:  "Mitigates shortage for impacted step.",
			Replenishment:  repl,
			AffectedJobIDs: sh.AffectedJobIDs,
		})
	}
	for i := range shortages {
		m := make([]ShortageResolutionOption, 0, 2)
		for _, r := range resolutions {
			if r.MaterialID == shortages[i].MaterialID {
				m = append(m, r)
			}
		}
		shortages[i].PerMaterialResolutions = m
	}

	// Detect subproduct shortages from blocked/unschedulable DependentJobPlan entries.
	// These are product inputs (e.g. P-007) whose child jobs could not be planned.
	// Surface the raw-material arrivals needed to manufacture that dependency; the
	// normal scheduler must then schedule the child production job.
	for i := range proposal.DependentJobs {
		dep := &proposal.DependentJobs[i]
		if dep.PlanningStatus == planningStatusPlanned {
			continue
		}
		// Use the consuming step's need-at time as the shortage reference point.
		needAt := normalizeMaterialEventTime(time.Now().UTC())
		if dep.FutureStockReadyAt != nil {
			needAt = *dep.FutureStockReadyAt
		} else if dep.EstimatedCompletion != nil {
			needAt = *dep.EstimatedCompletion
		}
		shortageQty := dep.ShortageQty
		if shortageQty <= 0 {
			shortageQty = dep.RequiredQty
		}
		shortageQty = roundDisplayQty(shortageQty)
		materialOpts, matErr := s.buildMaterialReplenishOptionsForSubproductManufacture(dep.ProductID, shortageQty, needAt, []string{proposal.JobID}, ledger)
		if matErr != nil {
			logger.L().Warn("subproduct_material_replenish_options_failed",
				zap.String("dependency_product_id", dep.ProductID),
				zap.String("parent_job_id", proposal.JobID),
				zap.Error(matErr))
			materialOpts = nil
		}
		dep.ReplenishmentSuggestion = nil
		perRes := make([]ShortageResolutionOption, 0, len(materialOpts))
		perRes = append(perRes, materialOpts...)
		dep.ResolutionOptions = perRes

		for _, mo := range materialOpts {
			resolutions = append(resolutions, mo)
		}
		global += shortageQty
	}

	resolutions = normalizeShortageResolutionOptions(resolutions)

	// Re-map per-material lists from normalized/deduped canonical set.
	// Subproduct/BOM shortage rows use MaterialID = dependency product id; raw-material
	// replenish alternatives use MaterialID = material id and DependencyProductID = that product.
	// Match both so per_material_resolutions mirrors dependent_jobs[].resolution_options.
	for i := range shortages {
		m := make([]ShortageResolutionOption, 0, 4)
		for _, r := range resolutions {
			if r.MaterialID == shortages[i].MaterialID {
				m = append(m, r)
				continue
			}
			if strings.TrimSpace(r.DependencyProductID) != "" && r.DependencyProductID == shortages[i].MaterialID {
				m = append(m, r)
			}
		}
		shortages[i].PerMaterialResolutions = m
	}
	for i := range proposal.DependentJobs {
		dep := &proposal.DependentJobs[i]
		if dep.PlanningStatus == planningStatusPlanned {
			continue
		}
		m := make([]ShortageResolutionOption, 0, 4)
		for _, r := range resolutions {
			if r.MaterialID == dep.ProductID {
				m = append(m, r)
				continue
			}
			if strings.TrimSpace(r.DependencyProductID) != "" && r.DependencyProductID == dep.ProductID {
				m = append(m, r)
			}
		}
		dep.ResolutionOptions = m
	}

	return shortages, resolutions, roundDisplayQty(global), nil
}

func (s *AIPredictiveService) buildBatchMaterialReplenishmentAggregate(proposals []*SchedulingProposal, ledger *tentativeInventoryLedger) []BatchMaterialReplenishmentLine {
	if s == nil || len(proposals) == 0 {
		return nil
	}

	actionsByMat := make(map[string][]InventoryAction)

	for _, p := range proposals {
		if p == nil {
			continue
		}
		for _, act := range p.InventoryActions {
			if act.ActionType == inventoryActionReserveMaterial {
				mid := strings.TrimSpace(act.ResourceID)
				actionsByMat[mid] = append(actionsByMat[mid], act)
			}
		}
	}

	now := time.Now().UTC()
	out := make([]BatchMaterialReplenishmentLine, 0, len(actionsByMat))

	for materialID, actions := range actionsByMat {
		opening, events, err := s.buildMaterialTimeline(materialID, now, ledger)
		if err != nil {
			continue
		}

		timelineEvents := make([]aggregateInventoryEvent, 0, len(events)+len(actions))
		for _, event := range events {
			timelineEvents = append(timelineEvents, aggregateInventoryEvent{
				At:    event.At,
				Delta: event.Delta,
			})
		}
		for _, act := range actions {
			timelineEvents = append(timelineEvents, aggregateInventoryEvent{
				At:    normalizeMaterialEventTime(act.EffectiveAt),
				Delta: -act.Quantity,
				JobID: ledgerRootJobID(strings.TrimSpace(act.JobID)),
			})
		}
		sortAggregateInventoryEvents(timelineEvents)

		minBalance := opening
		running := opening
		var shortageAt *time.Time
		shortageRoots := make([]string, 0)

		for _, event := range timelineEvents {
			running += event.Delta
			if running < minBalance {
				minBalance = running
			}
			if running < 0 && shortageAt == nil {
				t := event.At
				shortageAt = &t
			}
			if event.Delta < 0 && event.JobID != "" && running < 0 {
				shortageRoots = appendUniqueString(shortageRoots, event.JobID)
			}
		}

		maxDeficit := roundDisplayQty(math.Max(-minBalance, 0))
		if maxDeficit <= 0 {
			continue
		}

		mat, err := s.scheduling.inventoryRepo.GetMaterialByID(materialID)
		if err != nil {
			continue
		}

		startAt := normalizeMaterialEventTime(now)
		if shortageAt != nil {
			startAt = *shortageAt
		}

		earliestPossible := normalizeMaterialEventTime(now.Add(time.Duration(mat.ReorderLevel) * time.Hour))
		safeAt := normalizeMaterialEventTime(startAt.Add(-24 * time.Hour))
		suggested := safeAt
		if earliestPossible.After(suggested) {
			suggested = earliestPossible
		}

		primaryType := "replenish"
		if earliestPossible.After(startAt) {
			primaryType = "delay_jobs"
		}

		out = append(out, BatchMaterialReplenishmentLine{
			MaterialID:              materialID,
			MaterialName:            mat.MaterialName,
			Unit:                    mat.Unit,
			RecommendedQty:          maxDeficit,
			SuggestedArriveAt:       suggested,
			EarliestPossibleArrival: earliestPossible,
			ShortageStartAt:         startAt,
			OptionType:              primaryType,
			AffectedJobIDs:          shortageRoots,
			Rationale:               "Batch unified timeline deficit calculation.",
		})
	}
	out = mergeMatAggMax(out, s.buildBatchMaterialAggregateFromResolutionOptions(proposals))
	out = mergeMatAggMax(out, s.buildBatchMaterialAggregateFromAccelerationNeeds(proposals))
	sort.Slice(out, func(i, j int) bool { return out[i].MaterialID < out[j].MaterialID })
	return out
}

func (s *AIPredictiveService) buildBatchMaterialAggregateFromAccelerationNeeds(proposals []*SchedulingProposal) []BatchMaterialReplenishmentLine {
	if s == nil || s.scheduling == nil || s.scheduling.inventoryRepo == nil || len(proposals) == 0 {
		return nil
	}
	now := normalizeMaterialEventTime(time.Now().UTC())
	byMaterial := make(map[string]BatchMaterialReplenishmentLine)
	seenNeeds := make(map[string]struct{})
	for _, p := range proposals {
		if p == nil || len(p.materialAccelerationNeeds) == 0 || !proposalShouldRecommendMaterialAcceleration(p) {
			continue
		}
		for _, need := range p.materialAccelerationNeeds {
			mid := strings.TrimSpace(need.MaterialID)
			qty := roundDisplayQty(need.ShortageQty)
			needAt := normalizeMaterialEventTime(need.NeedAt)
			readyAt := normalizeMaterialEventTime(need.ReadyAt)
			if mid == "" || qty <= 0 || needAt.IsZero() || !readyAt.After(needAt) {
				continue
			}
			signature := materialAccelerationNeedSignature(need)
			if _, ok := seenNeeds[signature]; ok {
				continue
			}
			seenNeeds[signature] = struct{}{}

			mat, err := s.scheduling.inventoryRepo.GetMaterialByID(mid)
			if err != nil {
				continue
			}
			suggested := normalizeMaterialEventTime(needAt.Add(-30 * time.Minute))
			if suggested.Before(now) {
				suggested = now
			}
			existing := byMaterial[mid]
			if existing.MaterialID == "" {
				existing = BatchMaterialReplenishmentLine{
					MaterialID:              mid,
					MaterialName:            mat.MaterialName,
					Unit:                    mat.Unit,
					SuggestedArriveAt:       suggested,
					EarliestPossibleArrival: now,
					ShortageStartAt:         needAt,
					OptionType:              "replenish",
					Rationale:               "Batch material acceleration for late jobs waiting on delayed arrivals.",
				}
			}
			existing.RecommendedQty = roundDisplayQty(existing.RecommendedQty + qty)
			if suggested.Before(existing.SuggestedArriveAt) || existing.SuggestedArriveAt.IsZero() {
				existing.SuggestedArriveAt = suggested
			}
			if needAt.Before(existing.ShortageStartAt) || existing.ShortageStartAt.IsZero() {
				existing.ShortageStartAt = needAt
			}
			if p.JobID != "" {
				existing.AffectedJobIDs = appendUniqueString(existing.AffectedJobIDs, strings.TrimSpace(p.JobID))
			}
			if need.JobID != "" && !strings.Contains(need.JobID, "|") {
				existing.AffectedJobIDs = appendUniqueString(existing.AffectedJobIDs, strings.TrimSpace(need.JobID))
			}
			byMaterial[mid] = existing
		}
	}
	out := make([]BatchMaterialReplenishmentLine, 0, len(byMaterial))
	for _, line := range byMaterial {
		out = append(out, line)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].MaterialID < out[j].MaterialID })
	return out
}

func proposalShouldRecommendMaterialAcceleration(p *SchedulingProposal) bool {
	if p == nil || len(p.materialAccelerationNeeds) == 0 {
		return false
	}
	if p.DeadlineStatus != nil {
		return p.DeadlineStatus.IsLate
	}
	if !p.Feasible {
		return false
	}
	return len(materialIndependentBlockedReasons(p.BlockedReasons)) == 0
}

func (s *AIPredictiveService) buildBatchMaterialAggregateFromResolutionOptions(proposals []*SchedulingProposal) []BatchMaterialReplenishmentLine {
	if s == nil || s.scheduling == nil || s.scheduling.inventoryRepo == nil || len(proposals) == 0 {
		return nil
	}
	type proposalMaterialResolution struct {
		proposal *SchedulingProposal
		option   ShortageResolutionOption
		qty      float64
	}
	perProposalMaterial := make(map[string]proposalMaterialResolution)
	for _, p := range proposals {
		if p == nil {
			continue
		}
		for _, opt := range p.ShortageResolutions {
			if strings.EqualFold(strings.TrimSpace(opt.OptionType), "schedule_production") {
				continue
			}
			if opt.Replenishment == nil {
				continue
			}
			mid := strings.TrimSpace(opt.MaterialID)
			qty := roundDisplayQty(opt.Replenishment.SuggestedQty)
			if mid == "" || qty <= 0 {
				continue
			}
			key := strings.TrimSpace(p.JobID) + "|" + mid
			current, exists := perProposalMaterial[key]
			if !exists ||
				qty > current.qty ||
				(qty == current.qty &&
					!opt.Replenishment.SuggestedArriveAt.IsZero() &&
					(current.option.Replenishment == nil ||
						current.option.Replenishment.SuggestedArriveAt.IsZero() ||
						opt.Replenishment.SuggestedArriveAt.Before(current.option.Replenishment.SuggestedArriveAt))) {
				perProposalMaterial[key] = proposalMaterialResolution{proposal: p, option: opt, qty: qty}
			}
		}
	}

	byMaterial := make(map[string]BatchMaterialReplenishmentLine)
	for _, candidate := range perProposalMaterial {
		p := candidate.proposal
		opt := candidate.option
		if p == nil || opt.Replenishment == nil {
			continue
		}
		mid := strings.TrimSpace(opt.MaterialID)
		qty := candidate.qty
		if mid == "" || qty <= 0 {
			continue
		}
		mat, err := s.scheduling.inventoryRepo.GetMaterialByID(mid)
		if err != nil {
			continue
		}
		suggested := opt.Replenishment.SuggestedArriveAt
		if suggested.IsZero() {
			suggested = normalizeMaterialEventTime(time.Now().UTC())
		}
		earliest := opt.Replenishment.EarliestPossibleArrival
		if earliest.IsZero() {
			earliest = suggested
		}
		existing := byMaterial[mid]
		if existing.MaterialID == "" {
			existing = BatchMaterialReplenishmentLine{
				MaterialID:              mid,
				MaterialName:            mat.MaterialName,
				Unit:                    mat.Unit,
				SuggestedArriveAt:       suggested,
				EarliestPossibleArrival: earliest,
				ShortageStartAt:         suggested.Add(30 * time.Minute),
				OptionType:              "replenish",
				Rationale:               "Batch material recommendation from proposal shortage resolutions.",
			}
			if strings.TrimSpace(opt.DependencyProductID) != "" {
				existing.Rationale = "Batch raw-material recommendation for subproduct manufacture."
			}
		}
		existing.RecommendedQty = roundDisplayQty(existing.RecommendedQty + qty)
		if suggested.Before(existing.SuggestedArriveAt) || existing.SuggestedArriveAt.IsZero() {
			existing.SuggestedArriveAt = suggested
			existing.ShortageStartAt = suggested.Add(30 * time.Minute)
		}
		if earliest.Before(existing.EarliestPossibleArrival) || existing.EarliestPossibleArrival.IsZero() {
			existing.EarliestPossibleArrival = earliest
		}
		if opt.Replenishment.IsLeadTimeConstrained || strings.EqualFold(strings.TrimSpace(opt.OptionType), "delay_jobs") {
			existing.OptionType = "delay_jobs"
		}
		for _, jobID := range opt.AffectedJobIDs {
			existing.AffectedJobIDs = appendUniqueString(existing.AffectedJobIDs, strings.TrimSpace(jobID))
		}
		if p.JobID != "" {
			existing.AffectedJobIDs = appendUniqueString(existing.AffectedJobIDs, strings.TrimSpace(p.JobID))
		}
		byMaterial[mid] = existing
	}
	out := make([]BatchMaterialReplenishmentLine, 0, len(byMaterial))
	for _, line := range byMaterial {
		out = append(out, line)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].MaterialID < out[j].MaterialID })
	return out
}

// ─────────────────────────────────────────────────────────────────────────────
// Batch Shortage Convergence Loop
//
// convergeBatchShortageAggregates runs up to maxConvergencePasses full
// re-evaluation passes over the finalized proposal set and returns the
// stabilised (converged) material-replenishment aggregate. It replaces the
// single-pass calls that previously caused the
// "14 → 2 → 1" multi-click UX pattern.
//
// Algorithm (per pass):
//  1. Build a virtual tentativeInventoryLedger seeded with the current
//     aggregate material recommendations.
//  2. For every proposal in the batch, re-run decorateProposalWithInventoryPlan
//     + analyzeProposalMaterialShortages against a clone of that ledger so
//     cross-job inventory competition, ledger interactions and timing shifts
//     are all captured by the real planner — not approximated.
//  3. Rebuild the aggregates from the re-evaluated proposals.
//  4. Monotonically merge with the previous pass (max per material) to
//     prevent regression from ledger over-estimation.
//  5. Stop when: infeasible_count == 0, aggregate delta < 0.01, or cap hit.
// ─────────────────────────────────────────────────────────────────────────────

const maxConvergencePasses = 5

type convergenceProposalCache struct {
	jobs     map[string]*domain.Job
	previews map[string]*SolverPreview
}

// convergeBatchShortageAggregates is the entry point called from ScheduleJobSet.
func (s *AIPredictiveService) convergeBatchShortageAggregates(
	proposals []*SchedulingProposal,
	tentativeSlots []TentativeSlot,
	completionTargets map[string]*time.Time,
	excludedJobIDs []string,
) ([]BatchMaterialReplenishmentLine, int) {
	started := time.Now()
	cache := &convergenceProposalCache{
		jobs:     make(map[string]*domain.Job, len(proposals)),
		previews: make(map[string]*SolverPreview, len(proposals)),
	}
	// FIX: Create a base ledger just for exclusions so the initial aggregates
	// don't double-deduct existing DB reservations.
	baseLedger := newTentativeInventoryLedger()
	baseLedger.excludedJobIDs = excludedJobIDs

	initialAggStarted := time.Now()
	matAgg := s.buildBatchMaterialReplenishmentAggregate(proposals, baseLedger)
	logBatchTiming("convergence_initial_aggregate_build",
		zap.Int("proposal_count", len(proposals)),
		zap.Int("material_aggregate_count", len(matAgg)),
		zap.Duration("elapsed", time.Since(initialAggStarted)),
	)

	if len(proposals) == 0 {
		logBatchTiming("convergence_total",
			zap.Int("proposal_count", 0),
			zap.Int("passes", 0),
			zap.Duration("elapsed", time.Since(started)),
		)
		return matAgg, 0
	}

	// Fast path: if every proposal is already feasible, there is nothing to
	// converge — return the (empty) aggregate immediately.
	if infeasibleCountInReEvaluated(proposals) == 0 {
		logBatchTiming("convergence_total",
			zap.Int("proposal_count", len(proposals)),
			zap.Int("passes", 0),
			zap.Int("final_infeasible", 0),
			zap.Duration("elapsed", time.Since(started)),
		)
		return matAgg, 0
	}

	convIter := 0
	var lastReEvaluated []*SchedulingProposal

	for pass := 0; pass < maxConvergencePasses; pass++ {
		passStarted := time.Now()
		if allAggregatesZero(matAgg) {
			logBatchTiming("convergence_pass",
				zap.Int("pass", pass+1),
				zap.String("result", "all_aggregates_zero"),
				zap.Int("material_aggregate_count", len(matAgg)),
				zap.Duration("elapsed", time.Since(passStarted)),
			)
			break
		}

		// Seed a fresh virtual ledger with the CURRENT accumulated recommendations.
		seedLedger := seededLedgerFromAggregates(matAgg, excludedJobIDs)

		// Re-evaluate ALL proposals each pass — not just the initially-infeasible
		// ones — because resolving a material shortage causes subproduct jobs to be
		// scheduled earlier, which can consume a DIFFERENT material that was fine
		// before. A currently-feasible proposal can become infeasible in the next
		// real run (the cascade: MAT-002 fixed → subproduct reflows → MAT-010 short).
		// Skipping feasible proposals misses that cascade entirely.
		reEvalStarted := time.Now()
		reEvaluated := s.reEvaluateProposalsWithLedger(proposals, seedLedger, tentativeSlots, completionTargets, cache)
		reEvalElapsed := time.Since(reEvalStarted)
		lastReEvaluated = reEvaluated

		// Check if the current seedLedger made everything feasible BEFORE we scrub.
		reInfeasible := infeasibleCountInReEvaluated(reEvaluated)

		// DESIGN FIX: Scrub against baseLedger for ABSOLUTE totals.
		// reEvaluateProposalsWithLedger used seedLedger, so MaterialShortages and
		// ShortageResolutions only contain the DELTA (unmet) demand.
		// To prevent mergeMatAggMax from incorrectly doing MAX(absolute, delta),
		// we recalculate the shortages against the real baseLedger.
		rescrubStarted := time.Now()
		for _, p := range reEvaluated {
			if p == nil {
				continue
			}
			shortages, resolutions, score, _ := s.analyzeProposalMaterialShortages(p, baseLedger)
			p.MaterialShortages = shortages
			p.ShortageResolutions = resolutions
			p.GlobalScore = score
		}
		rescrubElapsed := time.Since(rescrubStarted)

		// Now pass baseLedger to the builders. This guarantees they see the full,
		// un-masked absolute demand of the entire reflowed timeline.
		aggregateRebuildStarted := time.Now()
		nextMatAgg := s.buildBatchMaterialReplenishmentAggregate(reEvaluated, baseLedger)
		aggregateRebuildElapsed := time.Since(aggregateRebuildStarted)

		// Monotonically merge: take max per material so we never regress.
		// This ensures the recommendation always covers BOTH the original shortage
		// and any secondary shortages exposed by the reflow.
		nextMatAgg = mergeMatAggMax(matAgg, nextMatAgg)

		convIter = pass + 1
		stable := batchAggStable(matAgg, nextMatAgg)
		logBatchTiming("convergence_pass",
			zap.Int("pass", pass+1),
			zap.Int("re_evaluated_count", len(reEvaluated)),
			zap.Int("re_infeasible", reInfeasible),
			zap.Int("material_aggregate_count", len(nextMatAgg)),
			zap.Bool("stable", stable),
			zap.Duration("re_evaluate_elapsed", reEvalElapsed),
			zap.Duration("rescrub_elapsed", rescrubElapsed),
			zap.Duration("aggregate_rebuild_elapsed", aggregateRebuildElapsed),
			zap.Duration("elapsed", time.Since(passStarted)),
		)

		if reInfeasible == 0 || stable {
			matAgg = nextMatAgg
			break
		}

		matAgg = nextMatAgg
	}

	// ── Final competitive-demand pass ──────────────────────────────────────────
	// Each proposal in the convergence loop above was re-evaluated with an
	// INDEPENDENT clone of the seeded ledger — correct for detecting individual
	// shortages, but it means each proposal sees the full seeded stock all to
	// itself. When many proposals now compete for the same material at the same
	// arrival time, the isolated view shows "feasible" but combined demand
	// exceeds supply.
	//
	// Calling buildBatchMaterialReplenishmentAggregate on the last re-evaluated
	// set merges ALL proposals' InventoryActions on a single shared timeline —
	// the same logic as the initial aggregate — giving the true combined
	// competitive demand with the post-reflow scheduling.  Merge this into the
	// accumulated aggregate so the final recommendation covers both the cascade
	// and the cross-job competition.
	// ──────────────────────────────────────────────────────────────────────────
	if len(lastReEvaluated) > 0 {
		finalCompetitiveStarted := time.Now()
		competitiveMatAgg := s.buildBatchMaterialReplenishmentAggregate(lastReEvaluated, baseLedger)
		matAgg = mergeMatAggMax(matAgg, competitiveMatAgg)
		logBatchTiming("convergence_final_competitive_pass",
			zap.Int("re_evaluated_count", len(lastReEvaluated)),
			zap.Int("competitive_material_aggregate_count", len(competitiveMatAgg)),
			zap.Duration("elapsed", time.Since(finalCompetitiveStarted)),
		)
	}

	logBatchTiming("convergence_total",
		zap.Int("proposal_count", len(proposals)),
		zap.Int("passes", convIter),
		zap.Int("final_material_aggregate_count", len(matAgg)),
		zap.Int("final_infeasible", infeasibleCountInReEvaluated(lastReEvaluated)),
		zap.Duration("elapsed", time.Since(started)),
	)
	return matAgg, convIter
}

// infeasibleProposalsOnly returns only the proposals that are not feasible.
// Used to limit convergence re-evaluation to proposals that can actually
// benefit from a virtual stock injection.
func infeasibleProposalsOnly(proposals []*SchedulingProposal) []*SchedulingProposal {
	out := make([]*SchedulingProposal, 0, len(proposals))
	for _, p := range proposals {
		if p != nil && !p.Feasible {
			out = append(out, p)
		}
	}
	return out
}

// seededLedgerFromAggregates builds a tentativeInventoryLedger that virtualises
// the effect of applying the current batch recommendations:
//   - material_replenishment lines → virtualArrival at SuggestedArriveAt
//     (NOT materialBaseline — the virtual stock must only be available from
//     the recommended arrival time, not immediately, so that the convergence
//     re-evaluation detects proposals whose steps need material BEFORE that date)
func seededLedgerFromAggregates(
	matAgg []BatchMaterialReplenishmentLine,
	excludedJobIDs []string,
) *tentativeInventoryLedger {
	ledger := newTentativeInventoryLedger()
	ledger.excludedJobIDs = excludedJobIDs
	now := time.Now().UTC()
	for _, m := range matAgg {
		if m.RecommendedQty <= 0 {
			continue
		}
		arriveAt := m.SuggestedArriveAt
		if arriveAt.IsZero() || arriveAt.Before(now) {
			// If no suggested time or already in the past, treat as on-hand now.
			ledger.materialBaseline[m.MaterialID] += m.RecommendedQty
		} else {
			// Future arrival: inject as a time-stamped virtual arrival so the
			// timeline scan correctly shows the stock only from arriveAt onward.
			ledger.appendVirtualArrival(m.MaterialID, m.RecommendedQty, arriveAt)
		}
	}
	return ledger
}

// reEvaluateProposalsWithLedger returns a fresh slice of proposals where
// InventoryActions, MaterialShortages, ShortageResolutions, Feasible and
// reEvaluateProposalsWithLedger returns a fresh slice of proposals where
// InventoryActions, MaterialShortages, ShortageResolutions, Feasible and
// GlobalScore are re-derived by running the FULL planner pipeline
// against a single, sequentially drained seedLedger.
func (s *AIPredictiveService) reEvaluateProposalsWithLedger(
	proposals []*SchedulingProposal,
	seedLedger *tentativeInventoryLedger,
	tentativeSlots []TentativeSlot,
	completionTargets map[string]*time.Time,
	cache *convergenceProposalCache,
) []*SchedulingProposal {
	started := time.Now()
	if s == nil || s.scheduling == nil {
		return proposals
	}

	// DESIGN FIX (The "Hard Fix"): Use ONE shared ledger for the entire batch.
	// This forces jobs to compete for the virtual seeded stock chronologically,
	// exactly as they do in the real planner. It prevents false-feasibility
	// where multiple jobs claim the same seeded material.
	sharedBatchState := &subproductBatchState{
		svc:    s,
		ledger: seedLedger, // DO NOT CLONE!
	}

	if cache == nil {
		cache = &convergenceProposalCache{
			jobs:     make(map[string]*domain.Job, len(proposals)),
			previews: make(map[string]*SolverPreview, len(proposals)),
		}
	}
	if cache.jobs == nil {
		cache.jobs = make(map[string]*domain.Job, len(proposals))
	}
	if cache.previews == nil {
		cache.previews = make(map[string]*SolverPreview, len(proposals))
	}

	reEvaluated := make([]*SchedulingProposal, 0, len(proposals))
	reusedOriginal := 0
	previewFailures := 0
	decorateFailures := 0
	feasibleCommitted := 0
	previewCacheHits := 0
	for _, orig := range proposals {
		if orig == nil {
			reEvaluated = append(reEvaluated, orig)
			reusedOriginal++
			continue
		}

		job := cache.jobs[orig.JobID]
		if job == nil {
			loaded, err := s.scheduling.getJobByID(orig.JobID)
			if err != nil || loaded == nil {
				reEvaluated = append(reEvaluated, orig)
				reusedOriginal++
				continue
			}
			job = loaded
			cache.jobs[orig.JobID] = job
		}

		preview := cache.previews[orig.JobID]
		if preview == nil {
			loaded, err := s.scheduling.BuildSolverPreviewWithTentativeSlotsAndFloor(
				orig.JobID, tentativeSlots, nil,
			)
			if err != nil || loaded == nil {
				reEvaluated = append(reEvaluated, orig)
				previewFailures++
				continue
			}
			preview = loaded
			cache.previews[orig.JobID] = preview
		} else {
			previewCacheHits++
		}

		candidate := shallowCloneProposal(orig)

		var targetCompletion *time.Time
		if completionTargets != nil {
			targetCompletion = completionTargets[orig.JobID]
		}

		// FIX 2: Clone state to prevent failed jobs from draining the shared seed ledger
		attemptState := sharedBatchState.clone()
		analysisLedger := attemptState.ledger.clone()

		if err := s.decorateProposalWithInventoryPlan(job, preview, candidate, tentativeSlots, attemptState, 0, targetCompletion); err != nil {
			reEvaluated = append(reEvaluated, orig)
			decorateFailures++
			continue
		}

		if shortages, resolutions, score, err := s.analyzeProposalMaterialShortages(candidate, analysisLedger); err == nil {
			candidate.MaterialShortages = shortages
			candidate.ShortageResolutions = resolutions
			candidate.GlobalScore = score
			candidate.Feasible = true

			newBlocked := make([]string, 0, len(orig.BlockedReasons))
			for _, br := range orig.BlockedReasons {
				if !strings.Contains(br, "material_shortage") {
					newBlocked = append(newBlocked, br)
				}
			}
			for _, sh := range shortages {
				if !sh.AllStepMaterialsFeasible {
					candidate.Feasible = false
					newBlocked = appendUniqueString(newBlocked, "reason_code=material_shortage")
					break
				}
			}
			candidate.BlockedReasons = newBlocked
		}

		// FIX 2.1: Only commit the ledger drain if the job actually survived the reflow
		if candidate.Feasible {
			sharedBatchState.ledger = attemptState.ledger
			sharedBatchState.totalGeneratedNodes = attemptState.totalGeneratedNodes
			feasibleCommitted++
		}

		reEvaluated = append(reEvaluated, candidate)
	}
	logBatchTiming("re_evaluate_proposals_with_ledger",
		zap.Int("proposal_count", len(proposals)),
		zap.Int("re_evaluated_count", len(reEvaluated)),
		zap.Int("reused_original", reusedOriginal),
		zap.Int("preview_failures", previewFailures),
		zap.Int("decorate_failures", decorateFailures),
		zap.Int("feasible_committed", feasibleCommitted),
		zap.Int("preview_cache_hits", previewCacheHits),
		zap.Duration("elapsed", time.Since(started)),
	)
	return reEvaluated
}

// shallowCloneProposalKeepInventory makes a value copy of a SchedulingProposal,
// keeping InventoryActions (needed by analyzeProposalMaterialShortages) and
// ProposedSlots intact while resetting only the shortage/resolution fields.
func shallowCloneProposalKeepInventory(p *SchedulingProposal) *SchedulingProposal {
	if p == nil {
		return nil
	}
	cp := *p
	cp.ProposedSlots = append([]ProposedSlot(nil), p.ProposedSlots...)
	cp.DependentJobs = append([]DependentJobPlan(nil), p.DependentJobs...)
	cp.InventoryActions = append([]InventoryAction(nil), p.InventoryActions...)
	cp.MaterialShortages = nil
	cp.ShortageResolutions = nil
	cp.materialAccelerationNeeds = append([]materialAccelerationNeed(nil), p.materialAccelerationNeeds...)
	cp.PartialFeasibility = nil
	cp.DeferredNodes = nil
	cp.BlockedReasons = append([]string(nil), p.BlockedReasons...)
	return &cp
}

// shallowCloneProposal makes a value copy of a SchedulingProposal while keeping
// ProposedSlots pointing to the same underlying array (read-only in this context).
// DependentJobs, MaterialShortages and ShortageResolutions are reset so they can
// be freshly populated by the re-evaluation pass.
func shallowCloneProposal(p *SchedulingProposal) *SchedulingProposal {
	if p == nil {
		return nil
	}
	cp := *p
	cp.ProposedSlots = append([]ProposedSlot(nil), p.ProposedSlots...)
	cp.DependentJobs = nil
	cp.MaterialShortages = nil
	cp.ShortageResolutions = nil
	cp.materialAccelerationNeeds = nil
	cp.PartialFeasibility = nil
	cp.DeferredNodes = nil
	cp.InventoryActions = nil
	cp.InventoryActionCount = 0
	cp.BlockedReasons = append([]string(nil), p.BlockedReasons...)
	cp.Feasible = p.Feasible
	return &cp
}

// allAggregatesZero returns true when both aggregates are empty or all quantities
// are zero — meaning there is nothing left to recommend.
func allAggregatesZero(mat []BatchMaterialReplenishmentLine) bool {
	for _, m := range mat {
		if m.RecommendedQty > 0 {
			return false
		}
	}
	return true
}

// batchAggStable returns true if the two aggregate pairs are materially identical
// (all qty differences < 0.01).
func batchAggStable(
	oldMat, newMat []BatchMaterialReplenishmentLine,
) bool {
	const eps = 0.01
	if len(oldMat) != len(newMat) {
		return false
	}
	oldMatByID := make(map[string]float64, len(oldMat))
	for _, m := range oldMat {
		oldMatByID[m.MaterialID] = m.RecommendedQty
	}
	for _, m := range newMat {
		diff := m.RecommendedQty - oldMatByID[m.MaterialID]
		if diff < 0 {
			diff = -diff
		}
		if diff >= eps {
			return false
		}
	}
	return true
}

// infeasibleCountInReEvaluated counts proposals that are still infeasible after
// a re-evaluation pass.
func infeasibleCountInReEvaluated(proposals []*SchedulingProposal) int {
	n := 0
	for _, p := range proposals {
		if p != nil && !p.Feasible {
			n++
		}
	}
	return n
}

// mergeMatAggMax returns a new material aggregate where each material's
// RecommendedQty is max(prev, next) and SuggestedArriveAt is min(prev, next)
// (i.e. we need the most stock AND we need it by the earliest deadline).
// New materials present only in next are included as-is.
// Materials present only in prev are preserved (conservative: still needed).
func mergeMatAggMax(prev, next []BatchMaterialReplenishmentLine) []BatchMaterialReplenishmentLine {
	byID := make(map[string]BatchMaterialReplenishmentLine, len(prev))
	for _, m := range prev {
		byID[m.MaterialID] = m
	}
	out := make([]BatchMaterialReplenishmentLine, 0, len(next))
	covered := make(map[string]bool, len(next))
	for _, m := range next {
		covered[m.MaterialID] = true
		if p, ok := byID[m.MaterialID]; ok {
			// qty: take the larger of the two (never regress coverage).
			if p.RecommendedQty > m.RecommendedQty {
				m.RecommendedQty = p.RecommendedQty
			}
			// arrive-at: take the earlier of the two — we need the stock by the
			// soonest deadline any infeasible job requires it.
			if !p.SuggestedArriveAt.IsZero() &&
				(m.SuggestedArriveAt.IsZero() || p.SuggestedArriveAt.Before(m.SuggestedArriveAt)) {
				m.SuggestedArriveAt = p.SuggestedArriveAt
			}
			// Merge affected job IDs (deduplicated union).
			if len(p.AffectedJobIDs) > 0 {
				seen := make(map[string]struct{}, len(m.AffectedJobIDs))
				for _, id := range m.AffectedJobIDs {
					seen[id] = struct{}{}
				}
				for _, id := range p.AffectedJobIDs {
					if _, ok := seen[id]; !ok {
						m.AffectedJobIDs = append(m.AffectedJobIDs, id)
					}
				}
			}
		}
		out = append(out, m)
	}
	// Include any prev entries not present in next (conservative: may still be needed).
	for _, m := range prev {
		if !covered[m.MaterialID] && m.RecommendedQty > 0 {
			out = append(out, m)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].MaterialID < out[j].MaterialID })
	return out
}

// ─────────────────────────────────────────────────────────────────────────────

func normalizeShortageResolutionOptions(options []ShortageResolutionOption) []ShortageResolutionOption {
	if len(options) == 0 {
		return options
	}
	dedup := make(map[string]ShortageResolutionOption, len(options))
	order := make([]string, 0, len(options))
	for _, opt := range options {
		enriched := enrichResolutionOption(opt)
		if !enriched.IsActionable {
			continue
		}
		sig := recommendationSignature(enriched)
		if _, exists := dedup[sig]; exists {
			continue
		}
		dedup[sig] = enriched
		order = append(order, sig)
	}
	out := make([]ShortageResolutionOption, 0, len(order))
	for _, sig := range order {
		out = append(out, dedup[sig])
	}
	return out
}

func enrichResolutionOption(opt ShortageResolutionOption) ShortageResolutionOption {
	flags := make([]string, 0, 4)
	entityID := strings.TrimSpace(opt.MaterialID)
	if entityID == "" {
		flags = append(flags, "missing_entity_id")
	}
	hasQty := false
	hasTime := false
	hasRationale := false
	if opt.Replenishment != nil {
		if opt.Replenishment.SuggestedQty > 0 {
			hasQty = true
		}
		if !opt.Replenishment.SuggestedArriveAt.IsZero() {
			hasTime = true
		}
		if strings.TrimSpace(opt.Replenishment.Rationale) != "" {
			hasRationale = true
		}
	}
	if !hasQty {
		flags = append(flags, "missing_suggested_qty")
	}
	if !hasTime {
		flags = append(flags, "missing_suggested_arrive_at")
	}
	if !hasRationale && strings.TrimSpace(opt.Description) == "" && strings.TrimSpace(opt.ImpactSummary) == "" {
		flags = append(flags, "missing_rationale")
	}
	// Actionable if we can identify entity and have at least one practical field.
	isActionable := entityID != "" && (hasQty || hasTime || hasRationale || opt.EarliestFeasibleStart != nil)
	opt.IsActionable = isActionable
	opt.QualityFlags = flags
	opt.RecommendationID = recommendationID(opt)
	return opt
}

func recommendationSignature(opt ShortageResolutionOption) string {
	qty := ""
	at := ""
	rationale := ""
	if opt.Replenishment != nil {
		qty = strconv.FormatFloat(opt.Replenishment.SuggestedQty, 'f', 4, 64)
		at = opt.Replenishment.SuggestedArriveAt.UTC().Format(time.RFC3339)
		rationale = strings.TrimSpace(opt.Replenishment.Rationale)
	}
	return strings.Join([]string{
		strings.TrimSpace(opt.MaterialID),
		strings.ToLower(strings.TrimSpace(opt.OptionType)),
		qty,
		at,
		rationale,
		strings.TrimSpace(opt.DependencyProductID),
	}, "|")
}

func recommendationID(opt ShortageResolutionOption) string {
	sig := recommendationSignature(opt)
	hash := sha256.Sum256([]byte(sig))
	return "REC-" + hex.EncodeToString(hash[:])[:12]
}

func (s *AIPredictiveService) ApplyReplenishment(ctx context.Context, items []ReplenishmentArrivalInput) (map[string]interface{}, error) {
	_ = ctx
	if s.scheduling == nil || s.scheduling.inventoryRepo == nil {
		return nil, newSchedulingActionError(500, "scheduling inventory is not configured")
	}

	// Group material rows by material_id only. Product-production rows are no
	// longer supported by this endpoint; callers must replenish missing raw material
	// and let the scheduler plan the dependent production job.
	type aggKey struct {
		id string
	}

	aggItems := make(map[aggKey]*ReplenishmentArrivalInput)
	validRows := 0
	replenishRows := 0
	unsupportedScheduleProductionRows := 0

	for _, item := range items {
		if strings.TrimSpace(item.MaterialID) == "" || item.Quantity <= 0 {
			continue
		}
		opt := strings.ToLower(strings.TrimSpace(item.OptionType))
		if opt == "schedule_production" {
			unsupportedScheduleProductionRows++
			continue
		}
		validRows++
		replenishRows++

		k := aggKey{id: item.MaterialID}

		if existing, ok := aggItems[k]; ok {
			// Sum the quantities across ALL jobs to resolve the total deficit
			existing.Quantity += item.Quantity

			// Always push the arrival time back to the earliest required date across the batch
			if item.ArriveAt.Before(existing.ArriveAt) {
				existing.ArriveAt = item.ArriveAt
			}
		} else {
			cp := item
			aggItems[k] = &cp
		}
	}

	var mergedItems []ReplenishmentArrivalInput
	for _, v := range aggItems {
		mergedItems = append(mergedItems, *v)
	}

	created := make([]domain.InventoryExpectedArrival, 0)
	skipped := 0

	agentDebugNDJSON("AR1", "shortage_analysis.ApplyReplenishment", "apply_request", map[string]any{
		"raw_request_len":                      len(items),
		"merged_request_len":                   len(mergedItems),
		"input_rows_valid":                     validRows,
		"replenish_rows":                       replenishRows,
		"unsupported_schedule_production_rows": unsupportedScheduleProductionRows,
	})

	// Use mergedItems instead of the raw fragmented items
	for _, item := range mergedItems {
		if strings.TrimSpace(item.MaterialID) == "" || item.Quantity <= 0 {
			continue
		}
		if item.InventorySnapshot != nil {
			current, err := s.computeInventorySnapshot(item.MaterialID)
			if err != nil {
				return nil, err
			}
			if current.Version != item.InventorySnapshot.Version {
				return nil, newSchedulingActionError(409, "snapshot_conflict: inventory changed since analysis")
			}
		}
		from := item.ArriveAt.Add(-30 * time.Minute)
		to := item.ArriveAt.Add(30 * time.Minute)
		existing, err := s.scheduling.inventoryRepo.ListExpectedArrivals(item.MaterialID, &from, &to, domain.ExpectedArrivalStatusPending)
		if err != nil {
			return nil, err
		}
		covered := 0.0
		for _, ex := range existing {
			covered += ex.Quantity
		}
		toCreate := math.Max(item.Quantity-covered, 0)
		if toCreate <= 0 {
			skipped++
			continue
		}
		rec := domain.InventoryExpectedArrival{
			ArrivalID:        id.NewPrefixed(id.PrefixExpectedArrival),
			MaterialID:       item.MaterialID,
			Quantity:         toCreate,
			ExpectedArriveAt: normalizeMaterialEventTime(item.ArriveAt),
			Status:           domain.ExpectedArrivalStatusPending,
			Notes:            strings.TrimSpace(item.Notes),
			CreatedAt:        time.Now().UTC(),
		}
		if rec.Notes == "" {
			rec.Notes = "replan-key:" + item.MaterialID + ":" + normalizeMaterialEventTime(item.ArriveAt).Format(time.RFC3339)
		}
		if err := s.scheduling.inventoryRepo.CreateExpectedArrival(&rec); err != nil {
			return nil, err
		}
		created = append(created, rec)
	}
	result := map[string]interface{}{
		"created_arrivals":                     created,
		"skipped_duplicates":                   skipped,
		"unsupported_schedule_production_rows": unsupportedScheduleProductionRows,
		"input_suggestion_rows_valid":          validRows,
		"any_new_records":                      len(created) > 0,
	}
	agentDebugNDJSON("AR1", "shortage_analysis.ApplyReplenishment", "apply_result", map[string]any{
		"input_rows_valid":                     validRows,
		"created_arrivals_count":               len(created),
		"skipped_material_duplicates":          skipped,
		"unsupported_schedule_production_rows": unsupportedScheduleProductionRows,
		"any_new_records":                      len(created) > 0,
	})
	return result, nil
}

func (s *AIPredictiveService) ReplenishAndReplan(ctx context.Context, jobID, actor string, input ReplenishAndReplanInput) (*SchedulingProposal, error) {
	maxAttempts := 3
	if input.Attempt >= maxAttempts {
		return nil, newSchedulingActionError(409, "convergence_failed: max attempts reached")
	}
	for _, item := range input.Arrivals {
		if strings.EqualFold(strings.TrimSpace(item.OptionType), "schedule_production") {
			continue
		}
		mat, err := s.scheduling.inventoryRepo.GetMaterialByID(item.MaterialID)
		if err != nil {
			return nil, err
		}
		earliest := normalizeMaterialEventTime(time.Now().UTC().Add(time.Duration(mat.ReorderLevel) * time.Hour))
		if normalizeMaterialEventTime(item.ArriveAt).Before(earliest) {
			return nil, newSchedulingActionError(422, "lead_time_infeasible: arrival time is earlier than lead-time allows")
		}
	}
	if _, err := s.ApplyReplenishment(ctx, input.Arrivals); err != nil {
		return nil, err
	}
	proposal, err := s.GenerateProposalWithOptions(jobID, actor, true)
	if err != nil {
		return nil, err
	}
	shortages, resolutions, score, err := s.analyzeProposalMaterialShortages(proposal, nil)
	if err != nil {
		return nil, err
	}
	proposal.MaterialShortages = shortages
	proposal.ShortageResolutions = resolutions
	proposal.GlobalScore = score
	for materialID, old := range input.PreviousDeficits {
		newDef := 0.0
		for _, sh := range shortages {
			if sh.MaterialID == materialID {
				newDef = sh.MaxDeficit
				break
			}
		}
		if newDef >= old {
			return nil, newSchedulingActionError(409, "convergence_failed: material deficit did not improve")
		}
	}
	if input.PreviousGlobalScore > 0 && score >= input.PreviousGlobalScore {
		return nil, newSchedulingActionError(409, "convergence_failed: global shortage score did not improve")
	}
	return proposal, nil
}
