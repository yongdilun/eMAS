package service

import (
	"emas/internal/domain"
	"encoding/json"
	"errors"
	"math"
	"sort"
	"strings"
	"time"

	"gorm.io/gorm"
)

type materialTimelineEvent struct {
	At    time.Time
	Delta float64
}

type productStockSnapshot struct {
	AvailableNow float64
	ReservedQty  float64
	ReadyAt      *time.Time
}

const (
	schedulerSlotGranularity        = 30 * time.Minute
	maxAlignedPlacementIterations   = 2048
	searchHorizonExceededReasonCode = "SEARCH_HORIZON_EXCEEDED"
	repairLimitExceededReasonCode   = "REPAIR_LIMIT_EXCEEDED"
	noFeasibleSlotReasonCode        = "NO_FEASIBLE_SLOT"
	lockWindowBlockedReasonCode     = "LOCK_WINDOW_BLOCKED"
	calendarOutsideShiftReasonCode  = "CALENDAR_OUTSIDE_SHIFT"
	invalidSlotAlignmentReasonCode  = "INVALID_SLOT_ALIGNMENT"
)

type StepDurationMetrics struct {
	ActualDuration       time.Duration
	ReservedDuration     time.Duration
	RoundingOverhead     time.Duration
	ActualDurationMins   int
	ReservedDurationMins int
	RoundingOverheadMins int
}

func roundUpToHalfHour(ts time.Time) time.Time {
	if ts.IsZero() {
		return ts
	}
	return roundUpToDuration(ts, schedulerSlotGranularity)
}

func roundUpToDuration(ts time.Time, step time.Duration) time.Time {
	if ts.IsZero() || step <= 0 {
		return ts
	}
	base := ts.Truncate(step)
	if base.Equal(ts) {
		return ts
	}
	return base.Add(step)
}

func ceilDurationTo30Min(d time.Duration) time.Duration {
	if d <= 0 {
		return schedulerSlotGranularity
	}
	if d%schedulerSlotGranularity == 0 {
		return d
	}
	return ((d / schedulerSlotGranularity) + 1) * schedulerSlotGranularity
}

func alignSuccessorStart(ts time.Time) time.Time {
	return roundUpToHalfHour(ts)
}

func isHalfHourAligned(ts time.Time) bool {
	if ts.IsZero() {
		return true
	}
	return ts.Second() == 0 && ts.Nanosecond() == 0 && (ts.Minute() == 0 || ts.Minute() == 30)
}

func sameOrAfter(a, b time.Time) bool {
	return a.Equal(b) || a.After(b)
}

func intervalContainsStart(interval BusyInterval, candidate time.Time) bool {
	return sameOrAfter(candidate, interval.Start) && candidate.Before(interval.End)
}

func intervalFullyContains(interval BusyInterval, start, end time.Time) bool {
	return sameOrAfter(start, interval.Start) && (end.Equal(interval.End) || end.Before(interval.End))
}

func nextAlignedWorkStart(base time.Time, workIntervals, blocked []BusyInterval, loc *time.Location) (time.Time, bool) {
	if base.IsZero() {
		base = time.Now().UTC()
	}
	if loc == nil {
		loc = base.Location()
	}
	workIntervals = normalizeBusyIntervals(workIntervals)
	blocked = normalizeBusyIntervals(blocked)
	if len(workIntervals) == 0 {
		return time.Time{}, false
	}
	candidate := roundUpToHalfHour(base.In(loc))
	for i := 0; i < maxAlignedPlacementIterations; i++ {
		var containing *BusyInterval
		var nextWork *BusyInterval
		for idx := range workIntervals {
			iv := workIntervals[idx]
			if intervalContainsStart(iv, candidate) {
				containing = &workIntervals[idx]
				break
			}
			if iv.Start.After(candidate) {
				nextWork = &workIntervals[idx]
				break
			}
		}
		if containing == nil {
			if nextWork == nil {
				return time.Time{}, false
			}
			candidate = roundUpToHalfHour(nextWork.Start.In(loc))
			continue
		}
		blockedShift := false
		for _, iv := range blocked {
			if intervalContainsStart(iv, candidate) {
				candidate = roundUpToHalfHour(iv.End.In(loc))
				blockedShift = true
				break
			}
		}
		if blockedShift {
			continue
		}

		if candidate.Before(containing.Start.In(loc)) {
			candidate = roundUpToHalfHour(containing.Start.In(loc))
			continue
		}
		return candidate.UTC(), true
	}
	return time.Time{}, false
}

func normalizeBusyIntervals(intervals []BusyInterval) []BusyInterval {
	filtered := make([]BusyInterval, 0, len(intervals))
	for _, iv := range intervals {
		if !iv.End.After(iv.Start) {
			continue
		}
		filtered = append(filtered, iv)
	}
	if len(filtered) <= 1 {
		return filtered
	}
	sort.Slice(filtered, func(i, j int) bool { return filtered[i].Start.Before(filtered[j].Start) })
	return mergeBusyIntervals(filtered)
}

func stepDurationMetrics(step domain.ProcessSteps, candidates []CandidateMachine, quantity float64) StepDurationMetrics {
	actual := estimateActualStepDuration(step, candidates, quantity)
	reserved := ceilDurationTo30Min(actual)
	rounding := reserved - actual
	return StepDurationMetrics{
		ActualDuration:       actual,
		ReservedDuration:     reserved,
		RoundingOverhead:     rounding,
		ActualDurationMins:   int(actual / time.Minute),
		ReservedDurationMins: int(reserved / time.Minute),
		RoundingOverheadMins: int(rounding / time.Minute),
	}
}

func (s *SchedulingService) loadProductComponents(product *domain.Product) ([]domain.FormulaIngredients, []domain.ProductBOM, string, error) {
	if product.FormulaID != "" {
		ingredients, err := s.formulaRepo.ListIngredientsByFormulaID(product.FormulaID)
		if err != nil {
			return nil, nil, "", err
		}
		return ingredients, nil, "formula", nil
	}
	bomItems, err := s.bomRepo.ListByProductID(product.ProductID)
	if err != nil {
		return nil, nil, "", err
	}
	return nil, bomItems, "bom", nil
}

func (s *SchedulingService) resolveStepContext(id string) (*domain.JobSteps, *domain.ProcessSteps, error) {
	jobStep, jobErr := s.getJobStepByID(id)
	if jobErr == nil {
		processStep, err := s.getProcessStepByID(jobStep.StepID)
		if err != nil {
			return nil, nil, err
		}
		return jobStep, processStep, nil
	}
	processStep, err := s.getProcessStepByID(id)
	if err != nil {
		return nil, nil, err
	}
	return nil, processStep, nil
}

func (s *SchedulingService) validateMachineWindow(processStep *domain.ProcessSteps, machineID string, start, end time.Time, quantity int, excludeSlotID string, toProductID string, ignoreMinSplitQty bool, result *SlotValidationResult) error {
	if !end.After(start) {
		result.AddHardReason("scheduled_end must be after scheduled_start (reason_code=" + invalidSlotAlignmentReasonCode + ")")
		return nil
	}
	if !isHalfHourAligned(start) || !isHalfHourAligned(end) {
		result.AddHardReason("slot start/end must align to :00 or :30 boundaries (reason_code=" + invalidSlotAlignmentReasonCode + ")")
		return nil
	}
	if end.Sub(start)%schedulerSlotGranularity != 0 {
		result.AddHardReason("slot duration must be a multiple of 30 minutes (reason_code=" + invalidSlotAlignmentReasonCode + ")")
		return nil
	}
	machine, err := s.getMachineByID(machineID)
	if err != nil {
		return err
	}
	if machine.Status == domain.MachineStatusOffline || machine.Status == domain.MachineStatusMaintenance {
		result.AddHardReason("machine is not currently schedulable")
	}
	ok, _, err := s.hasCapability(machineID, processStep.StepID)
	if err != nil {
		return err
	}
	if !ok && processStep.MachineTypeRequired == "" {
		result.AddHardReason("machine does not have capability for this step")
	}
	if processStep.MachineTypeRequired != "" && machine.MachineType != processStep.MachineTypeRequired {
		result.AddHardReason("machine_type does not match step requirement")
	}
	hasOverlap, overlaps, err := s.slotRepo.HasOverlap(machineID, start, end, excludeSlotID)
	if err != nil {
		return err
	}
	if hasOverlap {
		if len(overlaps) > 1 {
			result.AddHardReason("machine already has multiple overlapping slots")
		} else {
			result.AddHardReason("machine already has overlapping slots")
		}
	}
	downtimes, err := s.downtimeRepo.ListOverlapping(machineID, start, end)
	if err != nil {
		return err
	}
	if len(downtimes) > 0 {
		result.Valid = false
		result.Reasons = append(result.Reasons, "slot overlaps machine downtime")
	}
	maints, err := s.maintenanceRepo.ListOverlapping(machineID, start, end)
	if err != nil {
		return err
	}
	if len(maints) > 0 {
		result.AddHardReason("slot overlaps maintenance")
	}
	calendars, err := s.listMachineCalendars(machineID)
	if err != nil {
		return err
	}
	blocked := false
	coveredByWork := false
	hasWorkWindow := false
	if len(calendars) > 0 {
		for _, cal := range calendars {
			if cal.AvailabilityType == "work" {
				hasWorkWindow = true
			}
			if cal.StartTime.Before(end) && cal.EndTime.After(start) {
				if cal.AvailabilityType == "work" && !start.Before(cal.StartTime) && !end.After(cal.EndTime) {
					coveredByWork = true
				}
				if cal.AvailabilityType != "work" {
					blocked = true
				}
			}
		}
	}
	if blocked {
		result.AddHardReason("slot overlaps blocked machine calendar window")
	}
	if hasWorkWindow && !coveredByWork {
		result.AddHardReason("slot is outside machine work calendar (reason_code=calendar_outside_shift; ensure slot times fall within machine shift hours)")
	}
	if !s.isSlotInsideWorkTemplateFromSettings(start, end) {
		if s.isPublicHolidayFromSettings(start) || s.isPublicHolidayFromSettings(end.Add(-time.Second)) {
			result.AddHardReason("slot is outside scheduling work template (reason_code=holiday_blocked)")
		} else {
			result.AddHardReason("slot is outside scheduling work template (reason_code=calendar_outside_shift)")
		}
	}
	if !ignoreMinSplitQty && processStep.MinSplitQty > 0 && quantity < processStep.MinSplitQty {
		result.AddHardReason("slot quantity is below step min_split_qty")
	}
	return nil
}

// isSlotInsideWorkTemplateFromSettings returns true if [start, end] is fully inside a work window
// from the global scheduling settings.
func (s *SchedulingService) isSlotInsideWorkTemplateFromSettings(start, end time.Time) bool {
	if s.settingsRepo == nil {
		return true
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
		return true
	}
	loc := time.Local
	start = start.In(loc)
	end = end.In(loc)
	startDate := time.Date(start.Year(), start.Month(), start.Day(), 0, 0, 0, 0, loc)
	endDate := time.Date(end.Year(), end.Month(), end.Day(), 0, 0, 0, 0, loc)
	for day := startDate; !day.After(endDate); day = day.AddDate(0, 0, 1) {
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
		if (start.Equal(winStart) || start.After(winStart)) && (end.Equal(winEnd) || end.Before(winEnd)) && end.After(start) {
			return true
		}
	}
	return false
}

// nextWorkWindowStartFromSettings returns the earliest time >= from inside a work window
// from the global scheduling settings (work_start_time, work_end_time, work_days, public_holidays).
// Used when a resource/machine has no per-entity calendar.
func (s *SchedulingService) nextWorkWindowStartFromSettings(from time.Time) time.Time {
	if s.settingsRepo == nil {
		return roundUpToHalfHour(from)
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
		return roundUpToHalfHour(from)
	}
	startHH, startMM := startT.Hour(), startT.Minute()
	loc := time.Local
	from = from.In(loc)
	workIntervals := make([]BusyInterval, 0, 365)
	for d := 0; d < 365; d++ {
		day := from.AddDate(0, 0, d)
		wd := int(day.Weekday())
		if !workDays[wd] {
			continue
		}
		dateStr := day.Format("2006-01-02")
		if holidays != nil && holidays[dateStr] {
			continue
		}
		winStart := time.Date(day.Year(), day.Month(), day.Day(), startHH, startMM, 0, 0, loc)
		winEnd := time.Date(day.Year(), day.Month(), day.Day(), endT.Hour(), endT.Minute(), 0, 0, loc)
		if winEnd.After(from) {
			workIntervals = append(workIntervals, BusyInterval{Start: winStart.UTC(), End: winEnd.UTC()})
		}
	}
	next, ok := nextAlignedWorkStart(from.UTC(), workIntervals, nil, time.UTC)
	if !ok {
		return roundUpToHalfHour(from.UTC())
	}
	return next
}

func (s *SchedulingService) isPublicHolidayFromSettings(ts time.Time) bool {
	if s.settingsRepo == nil {
		return false
	}
	ph, ok, _ := s.settingsRepo.GetString("scheduling.public_holidays")
	if !ok || ph == "" {
		return false
	}
	var list []string
	if err := json.Unmarshal([]byte(ph), &list); err != nil {
		return false
	}
	loc := time.Local
	date := ts.In(loc).Format("2006-01-02")
	for _, d := range list {
		if strings.TrimSpace(d) == date {
			return true
		}
	}
	return false
}

// nextResourceWorkWindowStart returns the earliest time >= from when the step can run
// considering all required resources' work calendars. All resources must be available, so
// we return the latest of each resource's "next work window start". If no resources or no
// work calendars, returns from. When a resource has no calendar, falls back to global
// work template from scheduling settings.
func (s *SchedulingService) nextResourceWorkWindowStart(processStep *domain.ProcessSteps, from time.Time) time.Time {
	if s.resourceRepo == nil {
		return roundUpToHalfHour(from)
	}
	reqs, err := s.resourceRepo.ListRequirementsByStepID(processStep.StepID)
	if err != nil || len(reqs) == 0 {
		return roundUpToHalfHour(from)
	}
	latest := roundUpToHalfHour(from)
	for _, req := range reqs {
		calendars, err := s.resourceRepo.ListCalendarByResourceID(req.ResourceID)
		if err != nil {
			continue
		}
		var resourceNext time.Time
		if len(calendars) > 0 {
			workIntervals := make([]BusyInterval, 0, len(calendars))
			blocked := make([]BusyInterval, 0, len(calendars))
			for _, cal := range calendars {
				if !cal.EndTime.After(from) {
					continue
				}
				if cal.AvailabilityType == "work" {
					workIntervals = append(workIntervals, BusyInterval{Start: cal.StartTime.UTC(), End: cal.EndTime.UTC()})
					continue
				}
				blocked = append(blocked, BusyInterval{Start: cal.StartTime.UTC(), End: cal.EndTime.UTC()})
			}
			if len(workIntervals) > 0 {
				if next, ok := nextAlignedWorkStart(from.UTC(), workIntervals, blocked, time.UTC); ok {
					resourceNext = next
				}
			}
		} else {
			resourceNext = s.nextWorkWindowStartFromSettings(from)
		}
		if !resourceNext.IsZero() && resourceNext.After(latest) {
			latest = resourceNext
		}
	}
	return latest
}

// nextFittingResourceWorkStart is like nextResourceWorkWindowStart but also ensures
// that the proposed slot [start, start+duration] fits ENTIRELY within a single work
// calendar entry. This prevents the planner from generating a slot whose end time
// overflows the work window (e.g., a 15-hour slot when the calendar only allows 9 hours),
// which would always be rejected by validateResourceAvailability at apply time.
// It finds the earliest window start T >= from such that T+duration <= window.End.
// If no window is wide enough, it returns from unchanged (no better option exists).
func (s *SchedulingService) nextFittingResourceWorkStart(processStep *domain.ProcessSteps, from time.Time, duration time.Duration) time.Time {
	if s.resourceRepo == nil || duration <= 0 {
		return roundUpToHalfHour(from)
	}
	reqs, err := s.resourceRepo.ListRequirementsByStepID(processStep.StepID)
	if err != nil || len(reqs) == 0 {
		return roundUpToHalfHour(from)
	}
	latest := roundUpToHalfHour(from)
	for _, req := range reqs {
		calendars, err := s.resourceRepo.ListCalendarByResourceID(req.ResourceID)
		if err != nil {
			continue
		}
		if len(calendars) == 0 {
			resourceNext := s.nextWorkWindowStartFromSettings(from)
			if !resourceNext.IsZero() && resourceNext.After(latest) {
				latest = resourceNext
			}
			continue
		}
		// Collect future work windows, sort by start time.
		type window struct {
			start, end time.Time
		}
		var windows []window
		for _, cal := range calendars {
			if cal.AvailabilityType != "work" || !cal.EndTime.After(from) {
				continue
			}
			windows = append(windows, window{cal.StartTime.UTC(), cal.EndTime.UTC()})
		}
		sort.Slice(windows, func(i, j int) bool { return windows[i].start.Before(windows[j].start) })

		// Find the earliest window where [candidateStart, candidateStart+duration] fits.
		var resourceNext time.Time
		for _, w := range windows {
			if w.end.Sub(w.start) < duration {
				continue // Window is too narrow for this job — skip entirely.
			}
			candidateStart := from
			if w.start.After(candidateStart) {
				candidateStart = w.start
			}
			candidateStart = roundUpToHalfHour(candidateStart)
			if !candidateStart.Before(w.end) {
				continue // Rounded start is already past window end.
			}
			if candidateStart.Add(duration).After(w.end) {
				// Even starting at window.start the job overflows — skip.
				continue
			}
			resourceNext = candidateStart
			break
		}
		if !resourceNext.IsZero() && resourceNext.After(latest) {
			latest = resourceNext
		}
	}
	return latest
}

func (s *SchedulingService) validateResourceAvailability(processStep *domain.ProcessSteps, start, end time.Time, excludeSlotID string, result *SlotValidationResult) error {
	if s.resourceRepo == nil {
		return nil
	}
	reqs, err := s.resourceRepo.ListRequirementsByStepID(processStep.StepID)
	if err != nil || len(reqs) == 0 {
		return nil
	}
	for _, req := range reqs {
		calendars, err := s.resourceRepo.ListCalendarByResourceID(req.ResourceID)
		if err != nil {
			continue
		}
		if len(calendars) > 0 {
			coveredByWork := false
			blocked := false
			for _, cal := range calendars {
				if cal.StartTime.Before(end) && cal.EndTime.After(start) {
					if cal.AvailabilityType == "work" && !start.Before(cal.StartTime) && !end.After(cal.EndTime) {
						coveredByWork = true
					}
					if cal.AvailabilityType != "work" {
						blocked = true
					}
				}
			}
			if blocked {
				result.AddHardReason("required resource is blocked during slot time")
				continue
			}
			// Only enforce the work-calendar restriction when there is at least one
			// "work" entry that actually overlaps the slot's date range. If the
			// resource's calendar coverage ends before this slot (e.g. only 30
			// days were seeded), treat the slot as unrestricted rather than
			// blocking it forever.
			hasWorkForRange := false
			for _, c := range calendars {
				if c.AvailabilityType == "work" && c.StartTime.Before(end) && c.EndTime.After(start) {
					hasWorkForRange = true
					break
				}
			}
			if hasWorkForRange && !coveredByWork {
				result.AddHardReason("slot is outside resource work calendar (reason_code=resource_calendar_blocked)")
				continue
			}
		} else if s.settingsRepo != nil {
			if !s.isSlotInsideWorkTemplateFromSettings(start, end) {
				result.AddHardReason("slot is outside resource work calendar (reason_code=resource_calendar_blocked; ensure slot times fall within work hours from scheduling settings)")
				continue
			}
		}
		allocs, err := s.resourceRepo.ListAllocationsOverlapping(req.ResourceID, start, end, excludeSlotID)
		if err != nil {
			continue
		}
		if len(allocs) > 0 {
			result.AddHardReason("required resource is already allocated during slot time")
		}
	}
	return nil
}

func (s *SchedulingService) validateStepPrecedence(jobStep *domain.JobSteps, start time.Time, excludeSlotID string, result *SlotValidationResult) error {
	steps, err := s.stepRepo.ListByJobID(jobStep.JobID)
	if err != nil {
		return err
	}
	currentProcessStep, err := s.getProcessStepByID(jobStep.StepID)
	if err != nil {
		return err
	}
	predecessorStepIDs := getPredecessorStepIDs(currentProcessStep, steps)
	stepByProcessID := make(map[string]domain.JobSteps)
	for _, st := range steps {
		stepByProcessID[st.StepID] = st
	}
	for _, predStepID := range predecessorStepIDs {
		prev, ok := stepByProcessID[predStepID]
		if !ok {
			continue
		}
		prevSlots, err := s.slotRepo.ListByJobStepID(prev.JobStepID)
		if err != nil {
			return err
		}
		latestEnd := time.Time{}
		hasActivePlan := false
		for _, slot := range prevSlots {
			if slot.SlotID == excludeSlotID || slot.Status == domain.SlotStatusCancelled {
				continue
			}
			hasActivePlan = true
			if slot.ScheduledEnd.After(latestEnd) {
				latestEnd = slot.ScheduledEnd
			}
		}
		if prev.QuantityCompleted >= prev.QuantityTarget {
			continue
		}
		if !hasActivePlan {
			result.Valid = false
			result.Reasons = append(result.Reasons, "previous process step is not yet scheduled")
			continue
		}
		offset := time.Duration(0)
		if processStep, err := s.getProcessStepByID(prev.StepID); err == nil {
			offset = time.Duration(processStep.MinWaitMinutes+processStep.TransferMinutes) * time.Minute
		}
		earliestNextStart := alignSuccessorStart(latestEnd.Add(offset))
		if earliestNextStart.After(start) {
			result.AddHardReason("previous process step completes after the proposed aligned start (including wait/transfer time)")
		}
	}
	return nil
}

// getPredecessorStepIDs returns StepIDs that must complete before this step. Uses PredecessorStepIDs
// if set (JSON array); otherwise infers from StepSequence (step N depends on 1..N-1).
func getPredecessorStepIDs(processStep *domain.ProcessSteps, jobSteps []domain.JobSteps) []string {
	if processStep.PredecessorStepIDs != "" {
		var ids []string
		if err := json.Unmarshal([]byte(processStep.PredecessorStepIDs), &ids); err == nil && len(ids) > 0 {
			return ids
		}
	}
	// Backward compat: infer from StepSequence (step N depends on steps 1..N-1)
	var preds []string
	for _, js := range jobSteps {
		if js.StepSequence < processStep.StepSequence {
			preds = append(preds, js.StepID)
		}
	}
	return preds
}

func (s *SchedulingService) validateParallelPolicy(jobStepID string, processStep *domain.ProcessSteps, start, end time.Time, excludeSlotID string, result *SlotValidationResult) error {
	slots, err := s.slotRepo.ListByJobStepID(jobStepID)
	if err != nil {
		return err
	}
	if !processStep.AllowParallelExecution {
		for _, slot := range slots {
			if slot.SlotID == excludeSlotID || slot.Status == domain.SlotStatusCancelled {
				continue
			}
			if slot.ScheduledStart.Before(end) && slot.ScheduledEnd.After(start) {
				result.AddHardReason("step does not allow parallel execution")
				return nil
			}
		}
		return nil
	}
	if processStep.MaxParallelMachines <= 0 {
		return nil
	}
	parallelCount := 1
	for _, slot := range slots {
		if slot.SlotID == excludeSlotID || slot.Status == domain.SlotStatusCancelled {
			continue
		}
		if slot.ScheduledStart.Before(end) && slot.ScheduledEnd.After(start) {
			parallelCount++
		}
	}
	if parallelCount > processStep.MaxParallelMachines {
		result.AddHardReason("parallel machine count exceeds step max_parallel_machines")
	}
	return nil
}

func (s *SchedulingService) materialAvailability(materialID string, requiredQty float64, at time.Time, leadTimeHours int) (*DemandMaterial, error) {
	item, err := s.inventoryRepo.GetMaterialByID(materialID)
	if err != nil {
		return nil, err
	}
	// Use ALL pending reservations (not just those with needed_at <= at) so the
	// scheduler sees the true committed stock across every already-applied proposal.
	// Future-dated reservations are the whole problem: at = now means needed_at
	// filters to 0, hiding the full cumulative drain on the material.
	reservedNow, err := s.inventoryRepo.SumAllActiveReservations(materialID)
	if err != nil {
		return nil, err
	}
	available := item.CurrentStock - reservedNow
	result := &DemandMaterial{
		MaterialID:   materialID,
		MaterialName: item.MaterialName,
		RequiredQty:  requiredQty,
		Unit:         item.Unit,
		ReservedQty:  reservedNow,
		AvailableQty: available,
		EnoughNow:    available >= requiredQty,
	}
	if result.EnoughNow {
		if leadTimeHours > 0 {
			readyAt := at.Add(time.Duration(leadTimeHours) * time.Hour)
			result.ReadyAt = &readyAt
		}
		return result, nil
	}
	// Only fetch arrivals for the forward timeline. Reservations are already fully
	// baked into the baseline `reservedNow` above, so adding them again as negative
	// timeline deltas would double-count them.
	arrivals, err := s.inventoryRepo.ListExpectedArrivals(materialID, nil, nil, domain.ExpectedArrivalStatusPending)
	if err != nil {
		return nil, err
	}
	events := make([]materialTimelineEvent, 0, len(arrivals))
	for _, arrival := range arrivals {
		if arrival.ExpectedArriveAt.After(at) {
			events = append(events, materialTimelineEvent{At: arrival.ExpectedArriveAt, Delta: arrival.Quantity})
		}
	}
	sort.Slice(events, func(i, j int) bool {
		if events[i].At.Equal(events[j].At) {
			return events[i].Delta > events[j].Delta
		}
		return events[i].At.Before(events[j].At)
	})
	maxAvailable := available
	for _, event := range events {
		available += event.Delta
		if available > maxAvailable {
			maxAvailable = available
		}
		if available >= requiredQty {
			readyAt := event.At
			if leadTimeHours > 0 {
				readyAt = readyAt.Add(time.Duration(leadTimeHours) * time.Hour)
			}
			result.ReadyAt = &readyAt
			result.ShortageQty = 0
			return result, nil
		}
	}
	result.ShortageQty = math.Max(requiredQty-maxAvailable, 0)
	return result, nil
}

func (s *SchedulingService) productInventoryAvailability(productID string, requiredQty float64, at time.Time, leadTimeHours int) (*productStockSnapshot, error) {
	records, err := s.inventoryRepo.ListProductInventoryByProductID(productID)
	if err != nil {
		return nil, err
	}
	reservations, err := s.inventoryRepo.ListProductReservations(productID, domain.InventoryReservationStatusPending)
	if err != nil {
		return nil, err
	}
	snapshot := &productStockSnapshot{}
	current := 0.0
	future := make([]domain.ProductInventory, 0)
	for _, record := range records {
		availableQty := math.Max(record.QuantityOnHand-record.QuantityReserved, 0)
		snapshot.ReservedQty += record.QuantityReserved
		if record.AvailableFrom.After(at) {
			future = append(future, domain.ProductInventory{
				QuantityOnHand:   availableQty,
				AvailableFrom:    record.AvailableFrom,
				QuantityReserved: record.QuantityReserved,
			})
			continue
		}
		current += availableQty
	}
	for _, reservation := range reservations {
		when := alignSuccessorStart(reservation.NeededAt.UTC())
		if when.After(at) {
			future = append(future, domain.ProductInventory{
				QuantityOnHand: -reservation.ReservedQty,
				AvailableFrom:  when,
			})
			continue
		}
		current -= reservation.ReservedQty
	}
	snapshot.AvailableNow = current
	if current >= requiredQty {
		if leadTimeHours > 0 {
			readyAt := at.Add(time.Duration(leadTimeHours) * time.Hour)
			snapshot.ReadyAt = &readyAt
		}
		return snapshot, nil
	}
	sort.Slice(future, func(i, j int) bool { return future[i].AvailableFrom.Before(future[j].AvailableFrom) })
	for _, record := range future {
		current += record.QuantityOnHand
		if current >= requiredQty {
			readyAt := record.AvailableFrom
			if leadTimeHours > 0 {
				readyAt = readyAt.Add(time.Duration(leadTimeHours) * time.Hour)
			}
			snapshot.ReadyAt = &readyAt
			return snapshot, nil
		}
	}
	return snapshot, nil
}

func (s *SchedulingService) estimateManufacturingReadyAt(productID string, quantity float64, at time.Time, visited map[string]bool) (*time.Time, error) {
	if quantity <= 0 {
		readyAt := at
		return &readyAt, nil
	}
	if visited[productID] {
		return nil, errors.New("recursive product dependency detected")
	}
	visited[productID] = true
	defer delete(visited, productID)

	product, err := s.productRepo.GetByID(productID)
	if err != nil {
		return nil, err
	}
	ingredients, bomItems, _, err := s.loadProductComponents(product)
	if err != nil {
		return nil, err
	}
	inputReadyAt := at
	if len(ingredients) == 0 && len(bomItems) == 0 && product.ProcessID == "" {
		return nil, nil
	}
	if len(ingredients) > 0 {
		for _, ing := range ingredients {
			required := quantity * ing.QuantityPerUnit * (1 + ing.ScrapRate)
			readyAt, err := s.componentReadyAt(ing.MaterialID, ing.ProductID, required, at, visited, ing.LeadTimeHours)
			if err != nil {
				return nil, err
			}
			if readyAt == nil {
				return nil, nil
			}
			if readyAt.After(inputReadyAt) {
				inputReadyAt = *readyAt
			}
		}
	} else {
		for _, item := range bomItems {
			required := quantity * item.QuantityRequired * (1 + item.ScrapRate)
			readyAt, err := s.componentReadyAt(item.MaterialID, item.ProductComponentID, required, at, visited, 0)
			if err != nil {
				return nil, err
			}
			if readyAt == nil {
				return nil, nil
			}
			if readyAt.After(inputReadyAt) {
				inputReadyAt = *readyAt
			}
		}
	}
	return s.estimateProcessCompletionAt(productID, quantity, inputReadyAt)
}

func (s *SchedulingService) componentReadyAt(materialID, productID *string, requiredQty float64, at time.Time, visited map[string]bool, leadTimeHours int) (*time.Time, error) {
	if materialID != nil {
		material, err := s.materialAvailability(*materialID, requiredQty, at, leadTimeHours)
		if err != nil {
			return nil, err
		}
		if material.EnoughNow {
			if material.ReadyAt != nil {
				return material.ReadyAt, nil
			}
			readyAt := at
			return &readyAt, nil
		}
		if material.ReadyAt == nil {
			return nil, nil
		}
		return material.ReadyAt, nil
	}
	if productID == nil {
		return nil, nil
	}
	snapshot, err := s.productInventoryAvailability(*productID, requiredQty, at, leadTimeHours)
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return s.estimateManufacturingReadyAt(*productID, requiredQty, at, visited)
		}
		return nil, err
	}
	if snapshot.AvailableNow >= requiredQty {
		if snapshot.ReadyAt != nil {
			return snapshot.ReadyAt, nil
		}
		readyAt := at
		return &readyAt, nil
	}
	if snapshot.ReadyAt != nil {
		return snapshot.ReadyAt, nil
	}
	return s.estimateManufacturingReadyAt(*productID, requiredQty, at, visited)
}

func (s *SchedulingService) estimateProcessCompletionAt(productID string, quantity float64, startAt time.Time) (*time.Time, error) {
	process, err := s.processRepo.GetProcessByProductID(productID)
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			readyAt := startAt
			return &readyAt, nil
		}
		return nil, err
	}
	steps, err := s.processRepo.ListStepsByProcessID(process.ProcessID)
	if err != nil {
		return nil, err
	}
	cursor := startAt
	for i, step := range steps {
		candidates, err := s.candidateMachinesForProcessStep(&step, cursor, cursor.Add(8*time.Hour))
		if err != nil {
			return nil, err
		}
		if len(candidates) == 0 {
			return nil, nil
		}
		if step.AllowParallelExecution && step.MaxParallelMachines > 1 {
			maxParallel := minInt(step.MaxParallelMachines, len(candidates))
			selected := make([]CandidateMachine, 0, maxParallel)
			for _, candidate := range candidates {
				selected = append(selected, candidate)
				if len(selected) == maxParallel {
					break
				}
			}
			stepStart := cursor
			for _, candidate := range selected {
				if candidate.AvailableFrom.After(stepStart) {
					stepStart = candidate.AvailableFrom
				}
			}
			cursor = stepStart.Add(estimatedStepDuration(step, selected, quantity))
			if i+1 < len(steps) {
				cursor = cursor.Add(time.Duration(step.MinWaitMinutes+step.TransferMinutes) * time.Minute)
			}
			continue
		}
		best := candidates[0]
		stepStart := cursor
		if best.AvailableFrom.After(stepStart) {
			stepStart = best.AvailableFrom
		}
		cursor = stepStart.Add(estimatedStepDuration(step, []CandidateMachine{best}, quantity))
		if i+1 < len(steps) {
			cursor = cursor.Add(time.Duration(step.MinWaitMinutes+step.TransferMinutes) * time.Minute)
		}
	}
	readyAt := cursor
	return &readyAt, nil
}

func estimateActualStepDuration(step domain.ProcessSteps, candidates []CandidateMachine, quantity float64) time.Duration {
	fixedMinutes := step.DefaultPreparationTime + step.DefaultCleaningTime + step.DefaultChangeoverTime
	if fixedMinutes < 0 {
		fixedMinutes = 0
	}
	// Batch process: duration = numBatches * time per batch
	if step.IsBatchProcess && step.BatchSize > 0 {
		numBatches := int(math.Ceil(quantity / float64(step.BatchSize)))
		if numBatches <= 0 {
			numBatches = 1
		}
		processingMinutes := numBatches * step.DefaultProcessingTime
		if step.DefaultProcessingTime <= 0 {
			processingMinutes = numBatches
		}
		totalMinutes := fixedMinutes + processingMinutes
		return time.Duration(totalMinutes) * time.Minute
	}
	effectiveCapacityPerHour := 0.0
	for _, candidate := range candidates {
		capacity := float64(candidate.CapacityPerHour)
		if capacity <= 0 {
			continue
		}
		efficiency := candidate.EfficiencyFactor
		if efficiency <= 0 {
			efficiency = 1
		}
		effectiveCapacityPerHour += capacity * efficiency
	}
	processingMinutes := step.DefaultProcessingTime
	if quantity > 0 && effectiveCapacityPerHour > 0 {
		processingMinutes = int(math.Ceil((quantity / effectiveCapacityPerHour) * 60))
	}
	if processingMinutes < step.DefaultProcessingTime && step.DefaultProcessingTime > 0 && effectiveCapacityPerHour <= 0 {
		processingMinutes = step.DefaultProcessingTime
	}
	totalMinutes := fixedMinutes + processingMinutes
	if totalMinutes <= 0 && quantity > 0 {
		totalMinutes = 1
	}
	return time.Duration(totalMinutes) * time.Minute
}

func estimatedStepDuration(step domain.ProcessSteps, candidates []CandidateMachine, quantity float64) time.Duration {
	return ceilDurationTo30Min(estimateActualStepDuration(step, candidates, quantity))
}

// topologicalStepOrder returns job steps in dependency order using PredecessorStepIDs (or StepSequence when empty).
func topologicalStepOrder(steps []domain.JobSteps, processStepByID map[string]*domain.ProcessSteps) []domain.JobSteps {
	if len(steps) <= 1 {
		return steps
	}
	stepByStepID := make(map[string]domain.JobSteps)
	for _, st := range steps {
		stepByStepID[st.StepID] = st
	}
	getPreds := func(stepID string) []string {
		ps := processStepByID[stepID]
		if ps != nil && ps.PredecessorStepIDs != "" {
			var ids []string
			if err := json.Unmarshal([]byte(ps.PredecessorStepIDs), &ids); err == nil && len(ids) > 0 {
				return ids
			}
		}
		if ps == nil {
			return nil
		}
		var preds []string
		for _, st := range steps {
			pstep := processStepByID[st.StepID]
			if pstep != nil && pstep.StepSequence < ps.StepSequence {
				preds = append(preds, st.StepID)
			}
		}
		return preds
	}
	visited := make(map[string]bool)
	var result []domain.JobSteps
	var visit func(stepID string)
	visit = func(stepID string) {
		if visited[stepID] {
			return
		}
		visited[stepID] = true
		for _, pred := range getPreds(stepID) {
			if _, ok := stepByStepID[pred]; ok {
				visit(pred)
			}
		}
		if st, ok := stepByStepID[stepID]; ok {
			result = append(result, st)
		}
	}
	for _, st := range steps {
		visit(st.StepID)
	}
	return result
}

// wipAvailableAtStep returns the sum of Quantity for WIP at the given job step for the given product.
func (s *SchedulingService) wipAvailableAtStep(jobStepID, productID string) float64 {
	if s.wipRepo == nil {
		return 0
	}
	list, err := s.wipRepo.ListWIPByJobStepID(jobStepID)
	if err != nil {
		return 0
	}
	var sum float64
	for _, w := range list {
		if w.ProductID != nil && *w.ProductID == productID {
			sum += w.Quantity
		}
	}
	return sum
}

func demandTreeDepth(node DemandTreeNode) int {
	depth := 1
	for _, child := range node.Children {
		childDepth := 1 + demandTreeDepth(child)
		if childDepth > depth {
			depth = childDepth
		}
	}
	return depth
}

func totalMaterialDemand(materials []DemandMaterial) float64 {
	total := 0.0
	for _, material := range materials {
		total += material.RequiredQty
	}
	return total
}

func totalSubProductDemand(products []DemandSubProduct) float64 {
	total := 0.0
	for _, product := range products {
		total += product.RequiredQty
	}
	return total
}

func (s *SchedulingService) candidateMachinesForProcessStep(processStep *domain.ProcessSteps, start, end time.Time) ([]CandidateMachine, error) {
	return s.candidateMachinesForProcessStepWithTentative(processStep, start, end, nil)
}

func (s *SchedulingService) candidateMachinesForProcessStepWithTentative(processStep *domain.ProcessSteps, start, end time.Time, tentativeSlots []TentativeSlot) ([]CandidateMachine, error) {
	ids, err := s.listMachinesByStepID(processStep.StepID)
	if err != nil {
		return nil, err
	}
	if len(ids) == 0 {
		machines, err := s.listAllMachines()
		if err != nil {
			return nil, err
		}
		for _, machine := range machines {
			if processStep.MachineTypeRequired == "" || machine.MachineType == processStep.MachineTypeRequired {
				ids = append(ids, machine.MachineID)
			}
		}
	}
	out := make([]CandidateMachine, 0, len(ids))
	for _, machineID := range ids {
		machine, err := s.getMachineByID(machineID)
		if err != nil {
			continue
		}
		ok, cap, err := s.hasCapability(machineID, processStep.StepID)
		if err != nil {
			return nil, err
		}
		if !ok || cap == nil {
			cap = &domain.MachineCapabilities{MachineID: machineID, StepID: processStep.StepID, EfficiencyFactor: 1.0}
		}
		result := &SlotValidationResult{Valid: true}
		if err := s.validateMachineWindow(processStep, machineID, start, end, maxInt(1, processStep.MinSplitQty), "", "", false, result); err != nil {
			return nil, err
		}
		duration := end.Sub(start)
		feasibleStart, feasible, horizonReasons, horizonDiag := s.findFeasibleMachineStart(
			"",
			machineID,
			processStep,
			start,
			duration,
			maxInt(1, processStep.MinSplitQty),
			"",
			tentativeSlots,
			nil,
			end,
		)
		effectiveFree := feasibleStart
		if !feasible {
			effectiveFree = s.nextMachineFreeTimeWithTentative(machineID, start, duration, tentativeSlots)
			for _, reason := range horizonReasons {
				result.AddSoftReason(reason, 12)
			}
			if capHit, ok := horizonDiag["cap_hit"].(bool); ok && capHit {
				result.AddSoftReason("scheduling horizon reached; no feasible window in current horizon", 8)
			}
		}
		// Ensure the full slot [effectiveFree, effectiveFree+duration] fits within a
		// single work-calendar entry. nextFittingResourceWorkStart finds the earliest
		// window start where the entire duration is covered — not just the start of
		// any work interval — preventing the planner from proposing slots whose end
		// time overflows the calendar window (which would be rejected at apply time).
		resourceStart := s.nextFittingResourceWorkStart(processStep, effectiveFree, duration)
		if resourceStart.After(effectiveFree) {
			effectiveFree = resourceStart
		}
		available := result.Valid && feasible && !effectiveFree.After(start)
		if !available && result.Valid && len(tentativeSlots) > 0 {
			result.AddSoftReason("machine blocked by tentative slots from other jobs in batch", 10)
		}
		candidate := CandidateMachine{
			MachineID:        machine.MachineID,
			MachineName:      machine.MachineName,
			MachineType:      machine.MachineType,
			CapacityPerHour:  machine.CapacityPerHour,
			EfficiencyFactor: cap.EfficiencyFactor,
			Available:        available,
			AvailableFrom:    effectiveFree,
			Reasons:          result.Reasons,
		}
		if !result.Valid {
			candidate.AvailableFrom = effectiveFree
		}
		out = append(out, candidate)
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Available == out[j].Available {
			if out[i].EfficiencyFactor == out[j].EfficiencyFactor {
				return out[i].CapacityPerHour > out[j].CapacityPerHour
			}
			return out[i].EfficiencyFactor > out[j].EfficiencyFactor
		}
		return out[i].Available && !out[j].Available
	})
	return out, nil
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

// BusyInterval represents a time range when a resource is occupied.
type BusyInterval struct {
	Start time.Time
	End   time.Time
}

// mergeBusyIntervals merges overlapping intervals so the result is non-overlapping.
// Input must be sorted by Start.
func mergeBusyIntervals(intervals []BusyInterval) []BusyInterval {
	if len(intervals) <= 1 {
		return intervals
	}
	merged := make([]BusyInterval, 0, len(intervals))
	cur := intervals[0]
	for i := 1; i < len(intervals); i++ {
		next := intervals[i]
		if !next.Start.After(cur.End) {
			if next.End.After(cur.End) {
				cur.End = next.End
			}
		} else {
			merged = append(merged, cur)
			cur = next
		}
	}
	merged = append(merged, cur)
	return merged
}

// NextFreeFromIntervals returns the earliest time at or after `from` when the
// resource is free, given a sorted list of non-overlapping busy intervals.
func NextFreeFromIntervals(from time.Time, intervals []BusyInterval) time.Time {
	next := roundUpToHalfHour(from)
	for _, iv := range intervals {
		if !iv.End.After(next) {
			continue
		}
		if iv.Start.Before(next) || iv.Start.Equal(next) {
			next = roundUpToHalfHour(iv.End)
		} else {
			break
		}
	}
	return next
}

// NextFreeWindowFromIntervals returns the earliest start time at or after `from`
// such that [start, start+duration] does not overlap any busy interval.
// This prevents scheduling slots that would overlap due to insufficient gap.
func NextFreeWindowFromIntervals(from time.Time, duration time.Duration, intervals []BusyInterval) time.Time {
	candidate := roundUpToHalfHour(from)
	duration = ceilDurationTo30Min(duration)
	for i := 0; i < maxAlignedPlacementIterations; i++ {
		slotEnd := candidate.Add(duration)
		overlaps := false
		for _, iv := range intervals {
			if slotEnd.After(iv.Start) && candidate.Before(iv.End) {
				overlaps = true
				candidate = roundUpToHalfHour(iv.End)
				break
			}
		}
		if !overlaps {
			return candidate
		}
	}
	return candidate
}
