// verify_applied simulates applied job slots in chronological order and checks:
//  1. Step sequencing: predecessor steps must end before successors start.
//  2. Inventory sufficiency: materials and subproducts must be available when each slot starts.
//
// Issues are written as NDJSON to the debug log. Run with:
//
//	go run ./emas/cmd/verify_applied/...
package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"sort"
	"time"

	"emas/config"
	"emas/internal/domain"
	"emas/internal/repository"
)

const debugLogPath = `c:\Users\dilun\OneDrive\Documents\eMas APi\.cursor\debug.log`

// --- logging ------------------------------------------------------------------

var debugLog *os.File

type entry struct {
	Timestamp  string  `json:"timestamp"`
	Event      string  `json:"event"`
	JobID      string  `json:"job_id,omitempty"`
	JobStepID  string  `json:"job_step_id,omitempty"`
	SlotID     string  `json:"slot_id,omitempty"`
	MaterialID string  `json:"material_id,omitempty"`
	ProductID  string  `json:"product_id,omitempty"`
	Need       float64 `json:"need,omitempty"`
	Have       float64 `json:"have,omitempty"`
	At         string  `json:"at,omitempty"`
	Message    string  `json:"message"`
}

func emit(e entry) {
	e.Timestamp = time.Now().UTC().Format(time.RFC3339)
	b, _ := json.Marshal(e)
	_, _ = debugLog.Write(b)
	_, _ = debugLog.WriteString("\n")
	fmt.Println(string(b))
}

// --- data models used in this script ------------------------------------------

type appliedSlot struct {
	SlotID          string
	JobID           string
	JobStepID       string
	StepID          string
	StepSequence    int
	ScheduledStart  time.Time
	ScheduledEnd    time.Time
	QuantityPlanned float64
}

// --- main ---------------------------------------------------------------------

func main() {
	var err error
	debugLog, err = os.OpenFile(debugLogPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		log.Fatal("open debug log:", err)
	}
	defer debugLog.Close()

	emit(entry{Event: "verify_start", Message: "=== applied-job verification simulation starting ==="})

	cfg, err := config.Load()
	if err != nil {
		log.Fatal("config:", err)
	}
	db, err := repository.InitDB(cfg)
	if err != nil {
		log.Fatal("db:", err)
	}

	// ── 1. Applied proposal IDs ───────────────────────────────────────────────
	var proposals []domain.AIProposal
	if err := db.Where("status = ?", domain.AIProposalStatusApplied).Find(&proposals).Error; err != nil {
		log.Fatal("load proposals:", err)
	}
	if len(proposals) == 0 {
		emit(entry{Event: "no_proposals", Message: "No applied proposals found – apply some proposals first."})
		return
	}
	propIDs := make([]string, len(proposals))
	for i, p := range proposals {
		propIDs[i] = p.ProposalID
	}
	emit(entry{Event: "proposals_loaded", Message: fmt.Sprintf("%d applied proposals found", len(proposals))})

	// ── 2. Slots from applied proposals ───────────────────────────────────────
	type rawSlot struct {
		SlotID          string    `gorm:"column:slot_id"`
		JobStepID       string    `gorm:"column:job_step_id"`
		ProposalID      string    `gorm:"column:proposal_id"`
		ScheduledStart  time.Time `gorm:"column:scheduled_start"`
		ScheduledEnd    time.Time `gorm:"column:scheduled_end"`
		QuantityPlanned float64   `gorm:"column:quantity_planned"`
		JobID           string    `gorm:"column:job_id"`
		StepID          string    `gorm:"column:step_id"`
		StepSequence    int       `gorm:"column:step_sequence"`
	}
	var rawSlots []rawSlot
	err = db.Table("job_step_schedule_slots AS s").
		Select("s.slot_id, s.job_step_id, s.proposal_id, s.scheduled_start, s.scheduled_end, s.quantity_planned, js.job_id, js.step_id, js.step_sequence").
		Joins("JOIN job_steps js ON js.job_step_id = s.job_step_id").
		Where("s.proposal_id IN ? AND s.status != ?", propIDs, "cancelled").
		Find(&rawSlots).Error
	if err != nil {
		log.Fatal("load slots:", err)
	}
	slots := make([]appliedSlot, 0, len(rawSlots))
	for _, rs := range rawSlots {
		slots = append(slots, appliedSlot{
			SlotID:          rs.SlotID,
			JobID:           rs.JobID,
			JobStepID:       rs.JobStepID,
			StepID:          rs.StepID,
			StepSequence:    rs.StepSequence,
			ScheduledStart:  rs.ScheduledStart,
			ScheduledEnd:    rs.ScheduledEnd,
			QuantityPlanned: rs.QuantityPlanned,
		})
	}
	emit(entry{Event: "slots_loaded", Message: fmt.Sprintf("%d active slots loaded", len(slots))})

	// ── 3. Process step materials ─────────────────────────────────────────────
	var psms []domain.ProcessStepMaterial
	if err := db.Find(&psms).Error; err != nil {
		log.Fatal("load process step materials:", err)
	}
	psmByStep := make(map[string][]domain.ProcessStepMaterial, len(psms))
	for _, psm := range psms {
		psmByStep[psm.StepID] = append(psmByStep[psm.StepID], psm)
	}

	// ── 4. Simulated material stock (start from DB current_stock) ─────────────
	var mats []domain.InventoryMaterials
	if err := db.Find(&mats).Error; err != nil {
		log.Fatal("load materials:", err)
	}
	matStock := make(map[string]float64, len(mats))
	for _, m := range mats {
		matStock[m.MaterialID] = m.CurrentStock
	}

	// ── 5. Simulated product stock (available + planned records) ──────────────
	var pinvs []domain.ProductInventory
	if err := db.Where("status IN ?", []string{
		domain.ProductInventoryStatusAvailable,
		domain.ProductInventoryStatusPlanned,
	}).Find(&pinvs).Error; err != nil {
		log.Fatal("load product inventory:", err)
	}
	prodStock := make(map[string]float64, len(pinvs))
	for _, p := range pinvs {
		prodStock[p.ProductID] += p.QuantityOnHand
	}

	// ── 6. Expected arrivals ──────────────────────────────────────────────────
	var arrivals []domain.InventoryExpectedArrival
	if err := db.Where("status = ?", domain.ExpectedArrivalStatusPending).
		Order("expected_arrive_at ASC").Find(&arrivals).Error; err != nil {
		log.Fatal("load arrivals:", err)
	}

	emit(entry{
		Event:   "initial_state",
		Message: fmt.Sprintf("mat_stocks=%d prod_stocks=%d pending_arrivals=%d", len(matStock), len(prodStock), len(arrivals)),
	})

	// ── 7. Sequencing check ───────────────────────────────────────────────────
	// per (job_id, step_sequence): earliest start and latest end across all slots
	type seqKey struct {
		JobID        string
		StepSequence int
	}
	stepEarliestStart := make(map[seqKey]time.Time)
	stepLatestEnd := make(map[seqKey]time.Time)
	for _, s := range slots {
		k := seqKey{s.JobID, s.StepSequence}
		if stepEarliestStart[k].IsZero() || s.ScheduledStart.Before(stepEarliestStart[k]) {
			stepEarliestStart[k] = s.ScheduledStart
		}
		if s.ScheduledEnd.After(stepLatestEnd[k]) {
			stepLatestEnd[k] = s.ScheduledEnd
		}
	}

	seqViolations := 0
	for k, start := range stepEarliestStart {
		if k.StepSequence <= 1 {
			continue
		}
		// Check every lower-sequence step in the same job
		for k2, end := range stepLatestEnd {
			if k2.JobID != k.JobID || k2.StepSequence >= k.StepSequence {
				continue
			}
			if end.After(start) {
				seqViolations++
				emit(entry{
					Event: "sequence_violation",
					JobID: k.JobID,
					At:    start.Format(time.RFC3339),
					Message: fmt.Sprintf(
						"step_seq=%d earliest_start=%s overlaps predecessor step_seq=%d latest_end=%s (gap=-%s)",
						k.StepSequence, start.Format(time.RFC3339),
						k2.StepSequence, end.Format(time.RFC3339),
						end.Sub(start).String(),
					),
				})
			}
		}
	}
	if seqViolations == 0 {
		emit(entry{Event: "sequence_ok", Message: "All predecessor/successor step orderings are correct"})
	} else {
		emit(entry{Event: "sequence_summary", Message: fmt.Sprintf("%d sequencing violations found", seqViolations)})
	}

	// ── 8. Chronological inventory simulation ─────────────────────────────────
	// Build events: slot START (consume inputs) and slot END (produce outputs).
	type simEvent struct {
		At    time.Time
		IsEnd bool
		Slot  appliedSlot
	}
	events := make([]simEvent, 0, len(slots)*2)
	for _, s := range slots {
		events = append(events, simEvent{At: s.ScheduledStart, IsEnd: false, Slot: s})
		events = append(events, simEvent{At: s.ScheduledEnd, IsEnd: true, Slot: s})
	}
	// Sort: earlier time first; ties: END before START (produce before consume at same instant)
	sort.Slice(events, func(i, j int) bool {
		if events[i].At.Equal(events[j].At) {
			return events[i].IsEnd && !events[j].IsEnd
		}
		return events[i].At.Before(events[j].At)
	})

	arrIdx := 0
	invShortages := 0

	for _, ev := range events {
		// Apply pending arrivals up to this event's time
		for arrIdx < len(arrivals) && !arrivals[arrIdx].ExpectedArriveAt.After(ev.At) {
			a := arrivals[arrIdx]
			matStock[a.MaterialID] += a.Quantity
			emit(entry{
				Event:      "arrival_applied",
				MaterialID: a.MaterialID,
				At:         a.ExpectedArriveAt.Format(time.RFC3339),
				Message: fmt.Sprintf(
					"arrival %s: +%.0f units of %s; stock now %.0f",
					a.ArrivalID, a.Quantity, a.MaterialID, matStock[a.MaterialID],
				),
			})
			arrIdx++
		}

		psmsForStep := psmByStep[ev.Slot.StepID]
		qty := ev.Slot.QuantityPlanned

		if ev.IsEnd {
			// ── Produce outputs ──────────────────────────────────────────────
			for _, psm := range psmsForStep {
				if psm.Role != domain.ProcessStepMaterialRoleOutput {
					continue
				}
				produced := psm.QuantityPerUnit * qty
				if psm.MaterialID != nil && *psm.MaterialID != "" {
					matStock[*psm.MaterialID] += produced
				}
				if psm.ProductID != nil && *psm.ProductID != "" {
					prodStock[*psm.ProductID] += produced
					emit(entry{
						Event:     "product_produced",
						JobID:     ev.Slot.JobID,
						JobStepID: ev.Slot.JobStepID,
						SlotID:    ev.Slot.SlotID,
						ProductID: *psm.ProductID,
						Have:      prodStock[*psm.ProductID],
						At:        ev.At.Format(time.RFC3339),
						Message: fmt.Sprintf(
							"job=%s seq=%d produced %.0f of PROD %s; stock now %.0f",
							ev.Slot.JobID, ev.Slot.StepSequence, produced, *psm.ProductID, prodStock[*psm.ProductID],
						),
					})
				}
			}
		} else {
			// ── Consume inputs ───────────────────────────────────────────────
			for _, psm := range psmsForStep {
				if psm.Role != domain.ProcessStepMaterialRoleInput {
					continue
				}
				needed := psm.QuantityPerUnit * qty

				if psm.MaterialID != nil && *psm.MaterialID != "" {
					mid := *psm.MaterialID
					have := matStock[mid]
					if have < needed-0.001 { // tolerance for floating point
						invShortages++
						emit(entry{
							Event:      "material_shortage",
							JobID:      ev.Slot.JobID,
							JobStepID:  ev.Slot.JobStepID,
							SlotID:     ev.Slot.SlotID,
							MaterialID: mid,
							Need:       needed,
							Have:       have,
							At:         ev.At.Format(time.RFC3339),
							Message: fmt.Sprintf(
								"SHORTAGE job=%s seq=%d needs %.2f of MAT %s but only %.2f available",
								ev.Slot.JobID, ev.Slot.StepSequence, needed, mid, have,
							),
						})
					}
					// deduct (allow going negative to track cumulative deficit)
					matStock[mid] -= needed
				}

				if psm.ProductID != nil && *psm.ProductID != "" {
					pid := *psm.ProductID
					have := prodStock[pid]
					if have < needed-0.001 {
						invShortages++
						emit(entry{
							Event:     "product_shortage",
							JobID:     ev.Slot.JobID,
							JobStepID: ev.Slot.JobStepID,
							SlotID:    ev.Slot.SlotID,
							ProductID: pid,
							Need:      needed,
							Have:      have,
							At:        ev.At.Format(time.RFC3339),
							Message: fmt.Sprintf(
								"SHORTAGE job=%s seq=%d needs %.2f of PROD %s but only %.2f available",
								ev.Slot.JobID, ev.Slot.StepSequence, needed, pid, have,
							),
						})
					}
					prodStock[pid] -= needed
				}
			}
		}
	}

	// ── 9. Final stock snapshot ───────────────────────────────────────────────
	for mid, stock := range matStock {
		if stock < 0 {
			emit(entry{
				Event:      "final_negative_stock",
				MaterialID: mid,
				Have:       stock,
				Message:    fmt.Sprintf("Material %s ends simulation with negative stock %.2f", mid, stock),
			})
		}
	}
	for pid, stock := range prodStock {
		if stock < 0 {
			emit(entry{
				Event:     "final_negative_stock",
				ProductID: pid,
				Have:      stock,
				Message:   fmt.Sprintf("Product %s ends simulation with negative stock %.2f", pid, stock),
			})
		}
	}

	// ── 10. Summary ───────────────────────────────────────────────────────────
	emit(entry{
		Event: "verify_complete",
		Message: fmt.Sprintf(
			"=== DONE: sequence_violations=%d  inventory_shortages=%d ===",
			seqViolations, invShortages,
		),
	})
}
