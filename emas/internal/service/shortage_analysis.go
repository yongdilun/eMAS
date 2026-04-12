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

type batchProdShortageFloorMeta struct {
	totalSum          float64
	minShortageStart  time.Time
	haveMinStart      bool
	jobs              map[string]struct{}
}

func batchProdShortageFloorFromProposals(proposals []*SchedulingProposal, productID string) batchProdShortageFloorMeta {
	meta := batchProdShortageFloorMeta{jobs: make(map[string]struct{})}
	total := 0.0
	for _, p := range proposals {
		if p == nil {
			continue
		}
		for _, sh := range p.MaterialShortages {
			if sh.MaterialID != productID {
				continue
			}
			total += sh.MaxDeficit
			if !sh.ShortageStartAt.IsZero() {
				t := sh.ShortageStartAt.UTC()
				if !meta.haveMinStart || t.Before(meta.minShortageStart) {
					meta.minShortageStart = t
					meta.haveMinStart = true
				}
			}
			if strings.TrimSpace(p.JobID) != "" {
				meta.jobs[p.JobID] = struct{}{}
			}
			for _, jid := range sh.AffectedJobIDs {
				if strings.TrimSpace(jid) != "" {
					meta.jobs[jid] = struct{}{}
				}
			}
		}
		// Also scrape subproduct shortages mapped to schedule_production.
		for _, opt := range p.ShortageResolutions {
			if !strings.EqualFold(strings.TrimSpace(opt.OptionType), "schedule_production") || opt.Replenishment == nil || opt.MaterialID != productID {
				continue
			}
			total += opt.Replenishment.SuggestedQty
			if !opt.Replenishment.SuggestedArriveAt.IsZero() {
				t := opt.Replenishment.SuggestedArriveAt.UTC()
				if !meta.haveMinStart || t.Before(meta.minShortageStart) {
					meta.minShortageStart = t
					meta.haveMinStart = true
				}
			}
			if strings.TrimSpace(p.JobID) != "" {
				meta.jobs[p.JobID] = struct{}{}
			}
		}
	}
	meta.totalSum = roundDisplayQty(total)
	return meta
}

// batchNonRawMaterialShortageFloorMeta derives per-product shortage floors from material_shortages
// rows whose material_id is a product (not MAT-*), for schedule_production bulk lines when
// shortage_resolutions omit schedule_production or under-state qty vs. the cards.
func batchNonRawMaterialShortageFloorMeta(proposals []*SchedulingProposal) map[string]*batchProdShortageFloorMeta {
	out := make(map[string]*batchProdShortageFloorMeta)
	for _, p := range proposals {
		if p == nil {
			continue
		}
		sums := make(map[string]float64)
		for _, sh := range p.MaterialShortages {
			pid := strings.TrimSpace(sh.MaterialID)
			if pid == "" || isLikelyRawMaterialID(pid) {
				continue
			}
			sums[pid] += sh.MaxDeficit
		}
		for pid, sum := range sums {
			if sum <= 0 {
				continue
			}
			m := out[pid]
			if m == nil {
				m = &batchProdShortageFloorMeta{jobs: make(map[string]struct{})}
				out[pid] = m
			}
			if sum > m.totalSum {
				m.totalSum = sum
			}
		}
		for _, sh := range p.MaterialShortages {
			pid := strings.TrimSpace(sh.MaterialID)
			if pid == "" || isLikelyRawMaterialID(pid) {
				continue
			}
			if sums[pid] <= 0 {
				continue
			}
			m := out[pid]
			if m == nil {
				continue
			}
			if !sh.ShortageStartAt.IsZero() {
				t := sh.ShortageStartAt.UTC()
				if !m.haveMinStart || t.Before(m.minShortageStart) {
					m.minShortageStart = t
					m.haveMinStart = true
				}
			}
			if strings.TrimSpace(p.JobID) != "" {
				m.jobs[p.JobID] = struct{}{}
			}
			for _, jid := range sh.AffectedJobIDs {
				if strings.TrimSpace(jid) != "" {
					m.jobs[jid] = struct{}{}
				}
			}
		}
	}
	return out
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

// buildMaterialReplenishOptionsForSubproductManufacture emits option_type=replenish rows for raw materials
// needed to manufacture `manufactureUnits` of `dependencyProductID`, so planners can use apply-replenishment
// when the only previous option was schedule_production (subproduct shortage).
func (s *AIPredictiveService) buildMaterialReplenishOptionsForSubproductManufacture(
	dependencyProductID string,
	manufactureUnits float64,
	needAt time.Time,
	affectedJobIDs []string,
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
			SuggestedQty:            roundDisplayQty(agg.qty),
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
		jobStepID := ""
		if len(actions) > 0 {
			jobStepID = actions[0].JobStepID
		}
		opening, events, err := s.buildMaterialTimeline(materialID, time.Now().UTC(), ledger)
		if err != nil {
			return nil, nil, 0, err
		}
		for _, action := range actions {
			// NEW: If it has a sequence, the ledger already deducted it in buildMaterialTimeline.
			if ledger != nil && action.Sequence > 0 {
				continue
			}
			events = append(events, shortageTimelineEvent{
				At:    normalizeMaterialEventTime(action.EffectiveAt),
				Delta: -action.Quantity,
			})
		}
		sort.Slice(events, func(i, j int) bool {
			if events[i].At.Equal(events[j].At) {
				return events[i].Delta > events[j].Delta
			}
			return events[i].At.Before(events[j].At)
		})
		mat, err := s.scheduling.inventoryRepo.GetMaterialByID(materialID)
		if err != nil {
			return nil, nil, 0, err
		}
		running := opening
		minBalance := running
		var shortageAt *time.Time
		for _, event := range events {
			running += event.Delta
			if running < minBalance {
				minBalance = running
			}
			if running < 0 && shortageAt == nil {
				t := event.At
				shortageAt = &t
			}
		}
		maxDeficit := roundDisplayQty(math.Max(-minBalance, 0))
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
	// These are product inputs (e.g. P-007) whose child jobs could not be planned, leaving
	// the parent step unable to run. We surface them as ShortageResolutionOption with
	// option_type="schedule_production" and populate each DependentJobPlan's own
	// ReplenishmentSuggestion so the frontend has a clear, actionable signal.
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
		safeAt := normalizeMaterialEventTime(needAt.Add(-30 * time.Minute))
		earliest := normalizeMaterialEventTime(time.Now().UTC())
		suggested := safeAt
		if earliest.After(suggested) {
			suggested = earliest
		}
		shortageQty := dep.ShortageQty
		if shortageQty <= 0 {
			shortageQty = dep.RequiredQty
		}
		shortageQty = roundDisplayQty(shortageQty)
		repl := &ReplenishmentSuggestion{
			MaterialID:              dep.ProductID,
			MaterialName:            dep.ProductID,
			SuggestedQty:            shortageQty,
			SuggestedArriveAt:       suggested,
			EarliestPossibleArrival: earliest,
			IsLeadTimeConstrained:   earliest.After(needAt),
			SafetyBufferMins:        30,
			MergedFromCount:         1,
			Rationale:               "Production of " + dep.ProductID + " must be scheduled before the consuming step can proceed. Reason: " + dep.ReasonCode,
		}
		productionOption := ShortageResolutionOption{
			MaterialID:     dep.ProductID,
			OptionType:     "schedule_production",
			Priority:       1,
			Description:    "Schedule production of " + dep.ProductID + " before the consuming step starts.",
			ImpactSummary:  "Subproduct shortage blocks the parent step. Scheduling additional production will unblock it.",
			Replenishment:  repl,
			AffectedJobIDs: []string{proposal.JobID},
		}
		materialOpts, matErr := s.buildMaterialReplenishOptionsForSubproductManufacture(dep.ProductID, shortageQty, needAt, []string{proposal.JobID})
		if matErr != nil {
			logger.L().Warn("subproduct_material_replenish_options_failed",
				zap.String("dependency_product_id", dep.ProductID),
				zap.String("parent_job_id", proposal.JobID),
				zap.Error(matErr))
			materialOpts = nil
		}
		dep.ReplenishmentSuggestion = repl
		perRes := make([]ShortageResolutionOption, 0, 1+len(materialOpts))
		perRes = append(perRes, productionOption)
		perRes = append(perRes, materialOpts...)
		dep.ResolutionOptions = perRes

		// FIX 4: STRICT SEPARATION
		// COMPLETELY REMOVED the block that did: shortages = append(shortages, MaterialShortageInfo{ MaterialID: dep.ProductID ... })
		// P-* is now strictly delegated to ShortageResolutions (schedule_production).
		// They will never mix inside `shortage_material_ids` again.

		resolutions = append(resolutions, productionOption)
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

// buildBatchMaterialReplenishmentAggregate returns one replenishment line per raw material by
// merging every proposal's reserve_material actions into a single timeline (same family as
// analyzeProposalMaterialShortages, without naive summing of per-job max deficits).
func (s *AIPredictiveService) buildBatchMaterialReplenishmentAggregate(proposals []*SchedulingProposal, ledger *tentativeInventoryLedger) []BatchMaterialReplenishmentLine {
	if s == nil || len(proposals) == 0 || s.scheduling == nil || s.scheduling.inventoryRepo == nil {
		return nil
	}
	byMaterial := make(map[string][]InventoryAction)
	affectedRoots := make(map[string]map[string]struct{})
	for _, p := range proposals {
		if p == nil {
			continue
		}
		for _, act := range p.InventoryActions {
			if act.ActionType != inventoryActionReserveMaterial {
				continue
			}
			mid := strings.TrimSpace(act.ResourceID)
			if mid == "" {
				continue
			}
			byMaterial[mid] = append(byMaterial[mid], act)
			if affectedRoots[mid] == nil {
				affectedRoots[mid] = make(map[string]struct{})
			}
			root := ledgerRootJobID(act.JobID)
			if root == "" {
				root = act.JobID
			}
			if root != "" {
				affectedRoots[mid][root] = struct{}{}
			}
		}
	}
	for _, p := range proposals {
		if p == nil {
			continue
		}
		for _, sh := range p.MaterialShortages {
			mid := strings.TrimSpace(sh.MaterialID)
			if mid == "" || !isLikelyRawMaterialID(mid) {
				continue
			}
			if _, ok := byMaterial[mid]; !ok {
				byMaterial[mid] = nil
			}
			if affectedRoots[mid] == nil {
				affectedRoots[mid] = make(map[string]struct{})
			}
			if strings.TrimSpace(p.JobID) != "" {
				affectedRoots[mid][p.JobID] = struct{}{}
			}
			for _, jid := range sh.AffectedJobIDs {
				if strings.TrimSpace(jid) != "" {
					affectedRoots[mid][jid] = struct{}{}
				}
			}
		}
	}
	now := time.Now().UTC()
	out := make([]BatchMaterialReplenishmentLine, 0, len(byMaterial))
	// #region agent log
	h1Boosts := make([]map[string]any, 0, 4)
	// #endregion
	for materialID, actions := range byMaterial {
		// FIX: Pass the ledger so old DB reservations for these jobs are excluded
		// and virtual seed arrivals are included in the batch timeline!
		opening, events, err := s.buildMaterialTimeline(materialID, now, ledger)
		if err != nil {
			continue
		}
		for _, a := range actions {
			events = append(events, shortageTimelineEvent{
				At:    normalizeMaterialEventTime(a.EffectiveAt),
				Delta: -a.Quantity,
			})
		}
		sort.Slice(events, func(i, j int) bool {
			if events[i].At.Equal(events[j].At) {
				return events[i].Delta > events[j].Delta
			}
			return events[i].At.Before(events[j].At)
		})
		mat, err := s.scheduling.inventoryRepo.GetMaterialByID(materialID)
		if err != nil {
			continue
		}
		running := opening
		minBalance := running
		var shortageAt *time.Time
		for _, event := range events {
			running += event.Delta
			if running < minBalance {
				minBalance = running
			}
			if running < 0 && shortageAt == nil {
				t := event.At
				shortageAt = &t
			}
		}
		maxDeficit := roundDisplayQty(math.Max(-minBalance, 0))

		// FIX 3: Safely restore the floor! Because the combined mathematical timeline
		// can resolve to 0 when supply >= demand, but sequential priority starvation
		// causes actual job failures. This ensures the reported deficit survives.
		floor := batchMaterialShortageFloorFromProposals(proposals, materialID)
		if floor > maxDeficit {
			maxDeficit = floor
		}

		if maxDeficit <= 0 {
			continue
		}

		// FIX: Prioritize the earliest reported shortage start time across the individual jobs.
		// The mathematical zero-crossing of the merged timeline (`shortageAt`) arrives too late
		// when a high-priority future job steals stock from a low-priority earlier job.
		startAt := normalizeMaterialEventTime(now)
		if t0, ok := batchMaterialShortageMinStart(proposals, materialID); ok {
			startAt = normalizeMaterialEventTime(t0)
		} else if shortageAt != nil {
			startAt = *shortageAt
		}

		leadTimeHours := 0 // Note: Ensure you fetch this from your DB if available!
		earliestPossible := normalizeMaterialEventTime(now.Add(time.Duration(leadTimeHours) * time.Hour))

		// FIX 2: AGGRESSIVE EARLY SUGGESTION
		// Push the requested arrival a full 24 hours BEFORE the first shortage hits
		// (instead of just 30 mins) to ensure true "earliest better" safety.
		safeAt := normalizeMaterialEventTime(startAt.Add(-24 * time.Hour))

		suggested := safeAt
		if earliestPossible.After(suggested) {
			// If lead time prevents 24h early arrival, default to the earliest physical possibility
			suggested = earliestPossible
		}
		primaryType := "replenish"
		if earliestPossible.After(startAt) {
			primaryType = "delay_jobs"
		}
		jobs := make([]string, 0, len(affectedRoots[materialID]))
		for jid := range affectedRoots[materialID] {
			if strings.TrimSpace(jid) == "" {
				continue
			}
			jobs = append(jobs, jid)
		}
		sort.Strings(jobs)
		out = append(out, BatchMaterialReplenishmentLine{
			MaterialID:              materialID,
			MaterialName:            mat.MaterialName,
			Unit:                    mat.Unit,
			RecommendedQty:          maxDeficit,
			SuggestedArriveAt:       suggested,
			EarliestPossibleArrival: earliestPossible,
			ShortageStartAt:         startAt,
			OptionType:              primaryType,
			AffectedJobIDs:          jobs,
			Rationale:               "Batch-level peak deficit for this material given all proposals' planned material reservations in this response (single merged timeline).",
		})
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].MaterialID < out[j].MaterialID
	})
	// #region agent log
	if len(h1Boosts) > 0 {
		agentDebugNDJSON("H1", "shortage_analysis.buildBatchMaterialReplenishmentAggregate", "aggregate_raw_material_floor_boost", map[string]any{"boosts": h1Boosts})
	}
	// #endregion
	return out
}

// buildBatchScheduleProductionAggregate merges schedule_production rows from every proposal's
// shortage_resolutions so bulk apply can create planned FG/subproduct inventory once per product.
func (s *AIPredictiveService) buildBatchScheduleProductionAggregate(proposals []*SchedulingProposal, ledger *tentativeInventoryLedger) []BatchScheduleProductionLine {
	if s == nil || len(proposals) == 0 {
		return nil
	}
	type agg struct {
		qty           float64
		suggested     time.Time
		earliest      time.Time
		haveSuggested bool
		haveEarliest  bool
		jobs          map[string]struct{}
	}
	byProduct := make(map[string]*agg)
	for _, p := range proposals {
		if p == nil {
			continue
		}
		for _, opt := range p.ShortageResolutions {
			if !strings.EqualFold(strings.TrimSpace(opt.OptionType), "schedule_production") {
				continue
			}
			if opt.Replenishment == nil {
				continue
			}
			pid := strings.TrimSpace(opt.MaterialID)
			if pid == "" {
				continue
			}
			a := byProduct[pid]
			if a == nil {
				a = &agg{jobs: make(map[string]struct{})}
				byProduct[pid] = a
			}
			a.qty += opt.Replenishment.SuggestedQty
			sa := normalizeMaterialEventTime(opt.Replenishment.SuggestedArriveAt)
			if !a.haveSuggested || sa.Before(a.suggested) {
				a.suggested = sa
				a.haveSuggested = true
			}
			ea := normalizeMaterialEventTime(opt.Replenishment.EarliestPossibleArrival)
			if !a.haveEarliest || ea.Before(a.earliest) {
				a.earliest = ea
				a.haveEarliest = true
			}
			if strings.TrimSpace(p.JobID) != "" {
				a.jobs[p.JobID] = struct{}{}
			}
			for _, jid := range opt.AffectedJobIDs {
				if strings.TrimSpace(jid) != "" {
					a.jobs[jid] = struct{}{}
				}
			}
		}
	}
	floorMeta := batchNonRawMaterialShortageFloorMeta(proposals)
	// #region agent log
	h2Boosts := make([]map[string]any, 0, 4)
	// #endregion
	for pid, fm := range floorMeta {
		if fm == nil || roundDisplayQty(fm.totalSum) <= 0 {
			continue
		}
		if byProduct[pid] == nil {
			byProduct[pid] = &agg{jobs: make(map[string]struct{})}
		}
	}
	out := make([]BatchScheduleProductionLine, 0, len(byProduct))
	for productID, a := range byProduct {
		fm := floorMeta[productID]
		if fm != nil {
			for jid := range fm.jobs {
				a.jobs[jid] = struct{}{}
			}
			if fm.haveMinStart {
				sa := normalizeMaterialEventTime(fm.minShortageStart)
				if !a.haveSuggested || sa.Before(a.suggested) {
					a.suggested = sa
					a.haveSuggested = true
				}
				if !a.haveEarliest || sa.Before(a.earliest) {
					a.earliest = sa
					a.haveEarliest = true
				}
			}

			// FIX: Apply the discovered floor quantity to the aggregate tracker
			if fm.totalSum > a.qty {
				a.qty = fm.totalSum
			}
		}
		qty := roundDisplayQty(a.qty)
		// FIX: Do not override qty with floor. Floor sums cumulative deficits!
		if qty <= 0 {
			continue
		}
		name := productID
		if s.scheduling != nil && s.scheduling.productRepo != nil {
			if pr, err := s.scheduling.productRepo.GetByID(productID); err == nil && strings.TrimSpace(pr.ProductName) != "" {
				name = pr.ProductName
			}
		}
		jobs := make([]string, 0, len(a.jobs))
		for jid := range a.jobs {
			jobs = append(jobs, jid)
		}
		sort.Strings(jobs)
		suggested := a.suggested
		if !a.haveSuggested {
			suggested = normalizeMaterialEventTime(time.Now().UTC())
		}
		earliest := a.earliest
		if !a.haveEarliest {
			earliest = normalizeMaterialEventTime(time.Now().UTC())
		}
		out = append(out, BatchScheduleProductionLine{
			ProductID:               productID,
			ProductName:             name,
			RecommendedQty:          qty,
			SuggestedArriveAt:       suggested,
			EarliestPossibleArrival: earliest,
			OptionType:              "schedule_production",
			AffectedJobIDs:          jobs,
			Rationale:               "Batch sum of schedule_production recommendations for this product across proposals (subproduct/FG shortage).",
		})
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].ProductID < out[j].ProductID
	})
	// #region agent log
	if len(h2Boosts) > 0 {
		agentDebugNDJSON("H2", "shortage_analysis.buildBatchScheduleProductionAggregate", "aggregate_schedule_production_floor_boost", map[string]any{"boosts": h2Boosts})
	}
	// #endregion
	return out
}

// ─────────────────────────────────────────────────────────────────────────────
// Batch Shortage Convergence Loop
//
// convergeBatchShortageAggregates runs up to maxConvergencePasses full
// re-evaluation passes over the finalized proposal set and returns the
// stabilised (converged) material-replenishment and schedule-production
// aggregates.  It replaces the single-pass calls that previously caused the
// "14 → 2 → 1" multi-click UX pattern.
//
// Algorithm (per pass):
//  1. Build a virtual tentativeInventoryLedger seeded with the current
//     aggregate recommendations (material arrivals + planned production).
//  2. For every proposal in the batch, re-run decorateProposalWithInventoryPlan
//     + analyzeProposalMaterialShortages against a clone of that ledger so
//     cross-job inventory competition, ledger interactions and timing shifts
//     are all captured by the real planner — not approximated.
//  3. Rebuild the aggregates from the re-evaluated proposals.
//  4. Monotonically merge with the previous pass (max per material/product) to
//     prevent regression from ledger over-estimation.
//  5. Stop when: infeasible_count == 0, aggregate delta < 0.01, or cap hit.
// ─────────────────────────────────────────────────────────────────────────────

const maxConvergencePasses = 5

// convergeBatchShortageAggregates is the entry point called from ScheduleJobSet.
func (s *AIPredictiveService) convergeBatchShortageAggregates(
	proposals []*SchedulingProposal,
	tentativeSlots []TentativeSlot,
	completionTargets map[string]*time.Time,
	excludedJobIDs []string,
) ([]BatchMaterialReplenishmentLine, []BatchScheduleProductionLine, int) {
	// FIX: Create a base ledger just for exclusions so the initial aggregates
	// don't double-deduct existing DB reservations.
	baseLedger := newTentativeInventoryLedger()
	baseLedger.excludedJobIDs = excludedJobIDs

	matAgg := s.buildBatchMaterialReplenishmentAggregate(proposals, baseLedger)
	prodAgg := s.buildBatchScheduleProductionAggregate(proposals, baseLedger)

	if len(proposals) == 0 {
		return matAgg, prodAgg, 0
	}

	// Fast path: if every proposal is already feasible, there is nothing to
	// converge — return the (empty) aggregate immediately.
	if infeasibleCountInReEvaluated(proposals) == 0 {
		return matAgg, prodAgg, 0
	}

	convIter := 0
	var lastReEvaluated []*SchedulingProposal

	for pass := 0; pass < maxConvergencePasses; pass++ {
		if allAggregatesZero(matAgg, prodAgg) {
			break
		}

		// Seed a fresh virtual ledger with the CURRENT accumulated recommendations.
		seedLedger := seededLedgerFromAggregates(matAgg, prodAgg, excludedJobIDs)

		// Re-evaluate ALL proposals each pass — not just the initially-infeasible
		// ones — because resolving a material shortage causes subproduct jobs to be
		// scheduled earlier, which can consume a DIFFERENT material that was fine
		// before. A currently-feasible proposal can become infeasible in the next
		// real run (the cascade: MAT-002 fixed → subproduct reflows → MAT-010 short).
		// Skipping feasible proposals misses that cascade entirely.
		reEvaluated := s.reEvaluateProposalsWithLedger(proposals, seedLedger, tentativeSlots, completionTargets)
		lastReEvaluated = reEvaluated

		// Check if the current seedLedger made everything feasible BEFORE we scrub.
		reInfeasible := infeasibleCountInReEvaluated(reEvaluated)

		// DESIGN FIX: Scrub against baseLedger for ABSOLUTE totals.
		// reEvaluateProposalsWithLedger used seedLedger, so MaterialShortages and
		// ShortageResolutions only contain the DELTA (unmet) demand.
		// To prevent mergeMatAggMax from incorrectly doing MAX(absolute, delta),
		// we recalculate the shortages against the real baseLedger.
		for _, p := range reEvaluated {
			if p == nil {
				continue
			}
			shortages, resolutions, score, _ := s.analyzeProposalMaterialShortages(p, baseLedger)
			p.MaterialShortages = shortages
			p.ShortageResolutions = resolutions
			p.GlobalScore = score
		}

		// Now pass baseLedger to the builders. This guarantees they see the full,
		// un-masked absolute demand of the entire reflowed timeline.
		nextMatAgg := s.buildBatchMaterialReplenishmentAggregate(reEvaluated, baseLedger)
		nextProdAgg := s.buildBatchScheduleProductionAggregate(reEvaluated, baseLedger)

		// Monotonically merge: take max per material/product so we never regress.
		// This ensures the recommendation always covers BOTH the original shortage
		// and any secondary shortages exposed by the reflow.
		nextMatAgg = mergeMatAggMax(matAgg, nextMatAgg)
		nextProdAgg = mergeProdAggMax(prodAgg, nextProdAgg)

		convIter = pass + 1

		if reInfeasible == 0 || batchAggStable(matAgg, nextMatAgg, prodAgg, nextProdAgg) {
			matAgg = nextMatAgg
			prodAgg = nextProdAgg
			break
		}

		matAgg = nextMatAgg
		prodAgg = nextProdAgg
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
		competitiveMatAgg := s.buildBatchMaterialReplenishmentAggregate(lastReEvaluated, baseLedger)
		competitiveProdAgg := s.buildBatchScheduleProductionAggregate(lastReEvaluated, baseLedger)
		matAgg = mergeMatAggMax(matAgg, competitiveMatAgg)
		prodAgg = mergeProdAggMax(prodAgg, competitiveProdAgg)
	}

	return matAgg, prodAgg, convIter
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
//   - schedule_production lines → productBaseline boost (available now)
func seededLedgerFromAggregates(
	matAgg []BatchMaterialReplenishmentLine,
	prodAgg []BatchScheduleProductionLine,
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
	for _, p := range prodAgg {
		if p.RecommendedQty <= 0 {
			continue
		}
		// Product baseline: equivalent to planned product inventory already on hand.
		ledger.productBaseline[p.ProductID] += p.RecommendedQty
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
) []*SchedulingProposal {
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

	reEvaluated := make([]*SchedulingProposal, 0, len(proposals))
	for _, orig := range proposals {
		if orig == nil {
			reEvaluated = append(reEvaluated, orig)
			continue
		}

		job, err := s.jobRepo.GetByID(orig.JobID)
		if err != nil || job == nil {
			reEvaluated = append(reEvaluated, orig)
			continue
		}

		preview, err := s.scheduling.BuildSolverPreviewWithTentativeSlotsAndFloor(
			orig.JobID, tentativeSlots, nil,
		)
		if err != nil || preview == nil {
			reEvaluated = append(reEvaluated, orig)
			continue
		}

		candidate := shallowCloneProposal(orig)

		var targetCompletion *time.Time
		if completionTargets != nil {
			targetCompletion = completionTargets[orig.JobID]
		}

		// Evaluate using the SHARED state so successful reservations drain the ledger
		// for the next job in the loop.
		if err := s.decorateProposalWithInventoryPlan(job, preview, candidate, tentativeSlots, sharedBatchState, 0, targetCompletion); err != nil {
			reEvaluated = append(reEvaluated, orig)
			continue
		}

		// Analyze shortages with the shared ledger's current state
		if shortages, resolutions, score, err := s.analyzeProposalMaterialShortages(candidate, sharedBatchState.ledger); err == nil {
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

		reEvaluated = append(reEvaluated, candidate)
	}
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
	cp.DependentJobs = append([]DependentJobPlan(nil), p.DependentJobs...)
	cp.InventoryActions = append([]InventoryAction(nil), p.InventoryActions...)
	cp.MaterialShortages = nil
	cp.ShortageResolutions = nil
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
	cp.DependentJobs = nil
	cp.MaterialShortages = nil
	cp.ShortageResolutions = nil
	cp.InventoryActions = nil
	cp.InventoryActionCount = 0
	cp.BlockedReasons = append([]string(nil), p.BlockedReasons...)
	cp.Feasible = p.Feasible
	return &cp
}

// allAggregatesZero returns true when both aggregates are empty or all quantities
// are zero — meaning there is nothing left to recommend.
func allAggregatesZero(mat []BatchMaterialReplenishmentLine, prod []BatchScheduleProductionLine) bool {
	for _, m := range mat {
		if m.RecommendedQty > 0 {
			return false
		}
	}
	for _, p := range prod {
		if p.RecommendedQty > 0 {
			return false
		}
	}
	return true
}

// batchAggStable returns true if the two aggregate pairs are materially identical
// (all qty differences < 0.01).
func batchAggStable(
	oldMat, newMat []BatchMaterialReplenishmentLine,
	oldProd, newProd []BatchScheduleProductionLine,
) bool {
	const eps = 0.01
	if len(oldMat) != len(newMat) || len(oldProd) != len(newProd) {
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
	oldProdByID := make(map[string]float64, len(oldProd))
	for _, p := range oldProd {
		oldProdByID[p.ProductID] = p.RecommendedQty
	}
	for _, p := range newProd {
		diff := p.RecommendedQty - oldProdByID[p.ProductID]
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


// mergeProdAggMax returns a new schedule-production aggregate where each product's
// RecommendedQty is max(prev, next).
func mergeProdAggMax(prev, next []BatchScheduleProductionLine) []BatchScheduleProductionLine {
	byID := make(map[string]BatchScheduleProductionLine, len(prev))
	for _, p := range prev {
		byID[p.ProductID] = p
	}
	out := make([]BatchScheduleProductionLine, 0, len(next))
	covered := make(map[string]bool, len(next))
	for _, p := range next {
		covered[p.ProductID] = true
		if pv, ok := byID[p.ProductID]; ok && pv.RecommendedQty > p.RecommendedQty {
			p.RecommendedQty = pv.RecommendedQty
			if pv.SuggestedArriveAt.Before(p.SuggestedArriveAt) {
				p.SuggestedArriveAt = pv.SuggestedArriveAt
			}
		}
		out = append(out, p)
	}
	for _, p := range prev {
		if !covered[p.ProductID] && p.RecommendedQty > 0 {
			out = append(out, p)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ProductID < out[j].ProductID })
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

	// FIX 1: STRICT "ONE MATERIAL, ONE QTY, EARLIEST TIME" AGGREGATION
	// Group by material_id and option_type ONLY. Remove the time bucket.
	type aggKey struct {
		id  string
		opt string
	}

	aggItems := make(map[aggKey]*ReplenishmentArrivalInput)
	validRows := 0
	replenishRows := 0
	scheduleProductionRows := 0

	for _, item := range items {
		if strings.TrimSpace(item.MaterialID) == "" || item.Quantity <= 0 {
			continue
		}
		validRows++
		opt := strings.ToLower(strings.TrimSpace(item.OptionType))
		if opt == "schedule_production" {
			scheduleProductionRows++
		} else {
			replenishRows++
		}

		k := aggKey{id: item.MaterialID, opt: opt}

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
	createdPlanned := make([]domain.ProductInventory, 0)
	skipped := 0
	skippedPlanned := 0

	agentDebugNDJSON("AR1", "shortage_analysis.ApplyReplenishment", "apply_request", map[string]any{
		"raw_request_len":          len(items),
		"merged_request_len":       len(mergedItems),
		"input_rows_valid":         validRows,
		"replenish_rows":           replenishRows,
		"schedule_production_rows": scheduleProductionRows,
	})

	// Use mergedItems instead of the raw fragmented items
	for _, item := range mergedItems {
		if strings.TrimSpace(item.MaterialID) == "" || item.Quantity <= 0 {
			continue
		}
		opt := strings.ToLower(strings.TrimSpace(item.OptionType))
		if opt == "schedule_production" {
			if s.scheduling.productRepo == nil {
				return nil, newSchedulingActionError(500, "product repository is not configured")
			}
			productID := strings.TrimSpace(item.MaterialID)
			if _, err := s.scheduling.productRepo.GetByID(productID); err != nil {
				return nil, err
			}
			when := normalizeMaterialEventTime(item.ArriveAt)
			from := when.Add(-30 * time.Minute)
			to := when.Add(30 * time.Minute)
			existing, err := s.scheduling.inventoryRepo.ListProductInventoryByProductID(productID)
			if err != nil {
				return nil, err
			}
			covered := 0.0
			for _, ex := range existing {
				if ex.Status != domain.ProductInventoryStatusPlanned {
					continue
				}
				af := normalizeMaterialEventTime(ex.AvailableFrom)
				if af.Before(from) || af.After(to) {
					continue
				}
				covered += math.Max(ex.QuantityOnHand-ex.QuantityReserved, 0)
			}
			toCreate := math.Max(item.Quantity-covered, 0)
			if toCreate <= 0 {
				skippedPlanned++
				continue
			}
			pinv := domain.ProductInventory{
				InventoryID:      id.NewPrefixed("PINV-SHORT-"),
				ProductID:        productID,
				QuantityOnHand:   toCreate,
				QuantityReserved: 0,
				Status:           domain.ProductInventoryStatusPlanned,
				StorageLocation:  "shortage_resolution:apply",
				AvailableFrom:    when,
				LastUpdated:      time.Now().UTC(),
			}
			if err := s.scheduling.inventoryRepo.CreateProductInventory(&pinv); err != nil {
				return nil, err
			}
			createdPlanned = append(createdPlanned, pinv)
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
			ArrivalID:        id.NewPrefixed("ARR-"),
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
		"created_arrivals":           created,
		"skipped_duplicates":         skipped,
		"created_planned_production": createdPlanned,
		"skipped_planned_duplicates": skippedPlanned,
	}
	agentDebugNDJSON("AR1", "shortage_analysis.ApplyReplenishment", "apply_result", map[string]any{
		"input_rows_valid":            validRows,
		"created_arrivals_count":      len(created),
		"created_planned_count":       len(createdPlanned),
		"skipped_material_duplicates": skipped,
		"skipped_planned_duplicates":  skippedPlanned,
		"any_new_records":             len(created) > 0 || len(createdPlanned) > 0,
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
