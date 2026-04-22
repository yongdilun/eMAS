package service

import (
	"emas/internal/domain"
	"emas/pkg/logger"
	"math"
	"strings"
	"time"

	"go.uber.org/zap"
)

type BatchDemand struct {
	RawMaterials map[string]float64
	SubProducts  map[string]float64
}

// ... keep logLedgerState ...
func logLedgerState(ledger *tentativeInventoryLedger, context string) {
	if ledger == nil {
		logger.L().Info("ledger_state_nil", zap.String("context", context))
		return
	}

	materialVirtualMap := make(map[string]float64)
	for _, va := range ledger.virtualArrivals {
		materialVirtualMap[va.MaterialID] += va.Qty
	}

	logger.L().Info("ledger_state_snapshot",
		zap.String("context", context),
		zap.Int("virtual_arrival_count", len(ledger.virtualArrivals)),
		zap.Int("active_entries_count", len(ledger.activeEntries)),
		zap.Int("excluded_job_ids", len(ledger.excludedJobIDs)),
		zap.Reflect("virtual_arrivals_by_material", materialVirtualMap),
		zap.Reflect("material_baseline", ledger.materialBaseline),
		zap.Reflect("product_baseline", ledger.productBaseline))
}

func (s *AIPredictiveService) calculateGrossBatchDemand(jobs []domain.Job) BatchDemand {
	demand := BatchDemand{
		RawMaterials: make(map[string]float64),
		SubProducts:  make(map[string]float64),
	}
	
	// Tracks virtual stock of subproducts to prevent double counting shared dependencies
	subProductLedger := make(map[string]float64)

	for _, job := range jobs {
		product, err := s.scheduling.productRepo.GetByID(job.ProductID)
		if err != nil {
			continue
		}
		visited := make(map[string]bool)
		s.recursiveBOMExplosion(product.ProductID, float64(job.QuantityTotal), visited, subProductLedger, &demand)
	}
	return demand
}

func jobIDsFromList(jobs []domain.Job) []string {
	ids := make([]string, len(jobs))
	for i, j := range jobs {
		ids[i] = j.JobID
	}
	return ids
}

// recursiveBOMExplosion recursively traverses the BOM tree and aggregates raw material (MAT-*)
// requirements. It accumulates totals into the provided map.
func (s *AIPredictiveService) recursiveBOMExplosion(
	productID string,
	quantityNeeded float64,
	visited map[string]bool,
	subProductLedger map[string]float64,
	demand *BatchDemand,
) {
	if quantityNeeded <= 0 || visited[productID] {
		return
	}
	visited[productID] = true
	defer func() { visited[productID] = false }()

	product, err := s.scheduling.productRepo.GetByID(productID)
	if err != nil {
		return
	}

	ingredients, bomItems, _, err := s.scheduling.loadProductComponents(product)
	if err != nil {
		return
	}

	processComponent := func(compType string, matID *string, prodID *string, qtyPerUnit float64, scrap float64) {
		if compType == domain.ComponentTypeMaterial && matID != nil {
			mid := strings.TrimSpace(*matID)
			if mid != "" && isLikelyRawMaterialID(mid) {
				required := quantityNeeded * qtyPerUnit * (1.0 + scrap)
				demand.RawMaterials[mid] += required
			}
		} else if compType == domain.ComponentTypeProduct && prodID != nil {
			subProdID := strings.TrimSpace(*prodID)
			if subProdID != "" {
				required := quantityNeeded * qtyPerUnit * (1.0 + scrap)
				
				// Deduct from virtual shared stock first
				available := subProductLedger[subProdID]
				netRequired := required - available
				if netRequired <= 0 {
					subProductLedger[subProdID] = available - required
					return // Fully satisfied by virtual stock, stop explosion
				}
				subProductLedger[subProdID] = 0 // Consumed all available
				
				// Round to shop-floor lot size
				planned := s.roundPlannedSubproductQty(subProdID, netRequired)
				plannedInt := int(math.Ceil(planned))
				if plannedInt < 1 {
					plannedInt = 1
				}
				plannedFloat := float64(plannedInt)

				// Push the excess lot production back to the virtual ledger
				subProductLedger[subProdID] += (plannedFloat - netRequired)
				
				// Record the true subproduct demand
				demand.SubProducts[subProdID] += plannedFloat

				s.recursiveBOMExplosion(subProdID, plannedFloat, visited, subProductLedger, demand)
			}
		}
	}

	for _, ing := range ingredients {
		processComponent(ing.ComponentType, ing.MaterialID, ing.ProductID, ing.QuantityPerUnit, ing.ScrapRate)
	}
	for _, bom := range bomItems {
		processComponent(bom.ComponentType, bom.MaterialID, bom.ProductComponentID, bom.QuantityRequired, bom.ScrapRate)
	}
}

// injectPredictiveShortages compares the gross demand against real inventory and seeds the
// shared ledger with virtual stock so the scheduler thinks it's already on the way.
// This prevents premature shortage blocking during the batch scheduling pass.
func (s *AIPredictiveService) injectPredictiveShortages(
	grossDemand BatchDemand,
	ledger *tentativeInventoryLedger,
) {
	// Only inject raw materials for the timeline
	injectedCount := 0
	evaluated := make([]string, 0, len(grossDemand.RawMaterials))
	for matID, totalNeeded := range grossDemand.RawMaterials {
		if totalNeeded <= 0 {
			continue
		}
		evaluated = append(evaluated, matID)

		// Get current real stock (opening + future arrivals - reservations), excluding
		// reservations from the jobs currently being re-planned in this batch.
		opening, events, err := s.buildMaterialTimeline(matID, time.Now().UTC(), ledger)
		if err != nil {
			agentDebugNDJSON("DIAGNOSTIC", "service.predictive_bom.go:injectPredictiveShortages", "predictive_shortages_timeline_failed", map[string]any{
				"material_id": matID,
				"total_needed": totalNeeded,
				"error": err.Error(),
			})
			logger.L().Warn("predictive_shortages_timeline_failed",
				zap.String("material_id", matID),
				zap.Float64("total_needed", totalNeeded),
				zap.Error(err))
			continue
		}

		minBalance := opening
		available := opening
		// Summarize events for diagnostics
		eventCount := len(events)
		for _, event := range events {
			available += event.Delta
			if available < minBalance {
				minBalance = available
			}
		}

		agentDebugNDJSON("DIAGNOSTIC", "service.predictive_bom.go:injectPredictiveShortages", "predictive_shortages_material_analysis", map[string]any{
			"material_id":       matID,
			"material_total_needed": totalNeeded,
			"current_opening":   opening,
			"projected_min_balance": minBalance,
			"future_events":     eventCount,
		})

		if totalNeeded > minBalance {
			deficit := totalNeeded - minBalance

			// Inject far in the past so even past-due jobs see it as opening stock
			safeArrivalDate := time.Now().UTC().AddDate(-10, 0, 0)
			
			// -------------------------------------------------------------
			// FIX: Use the ledger's virtual arrival mechanism so the core planner
			// correctly observes the injected stock during forward-scan timelines.
			// -------------------------------------------------------------
			ledger.appendVirtualArrival(matID, deficit, safeArrivalDate)
			injectedCount++

			agentDebugNDJSON("DIAGNOSTIC", "service.predictive_bom.go:injectPredictiveShortages", "predictive_shortages_injected", map[string]any{
				"material_id": matID,
				"deficit":     deficit,
				"min_balance": minBalance,
				"total_needed": totalNeeded,
				"arrive_at":    safeArrivalDate.Format(time.RFC3339),
			})

			logger.L().Info("predictive_shortages_injected_via_negative_reservation",
				zap.String("material_id", matID),
				zap.Float64("deficit", deficit),
				zap.Float64("min_balance", minBalance),
				zap.Float64("total_needed", totalNeeded),
				zap.String("arrive_at", safeArrivalDate.Format(time.RFC3339)))
		} else {
			agentDebugNDJSON("DIAGNOSTIC", "service.predictive_bom.go:injectPredictiveShortages", "predictive_shortages_sufficient_stock", map[string]any{
				"material_id": matID,
				"min_balance": minBalance,
				"total_needed": totalNeeded,
			})
			logger.L().Debug("predictive_shortages_sufficient_stock",
				zap.String("material_id", matID),
				zap.Float64("min_balance", minBalance),
				zap.Float64("total_needed", totalNeeded))
		}
	}
}
