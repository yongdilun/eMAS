package service

import (
	"testing"
	"time"
)

func Test_proposalsDistinct_machineDiff(t *testing.T) {
	a := &SchedulingProposal{
		ProposedSlots: []ProposedSlot{{MachineID: "M1", ScheduledStart: time.Now(), ScheduledEnd: time.Now().Add(time.Hour)}},
	}
	b := &SchedulingProposal{
		ProposedSlots: []ProposedSlot{{MachineID: "M2", ScheduledStart: a.ProposedSlots[0].ScheduledStart, ScheduledEnd: a.ProposedSlots[0].ScheduledEnd}},
	}
	if !proposalsDistinct(a, b) {
		t.Fatal("expected distinct when machine differs")
	}
}

func Test_proposalsDistinct_same(t *testing.T) {
	start := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	end := start.Add(time.Hour)
	a := &SchedulingProposal{
		ProposedSlots: []ProposedSlot{{MachineID: "M1", ScheduledStart: start, ScheduledEnd: end}},
	}
	b := &SchedulingProposal{
		ProposedSlots: []ProposedSlot{{MachineID: "M1", ScheduledStart: start, ScheduledEnd: end}},
	}
	if proposalsDistinct(a, b) {
		t.Fatal("expected not distinct when identical")
	}
}

func Test_computeAdaptiveHorizonEnd_respectsDeadlineAndCap(t *testing.T) {
	now := time.Date(2026, 3, 24, 8, 0, 0, 0, time.UTC)
	// Default policy now allows up to 60d search cap.
	deadline := now.Add(4 * 24 * time.Hour)
	hp := defaultHorizonPolicy()
	got := computeAdaptiveHorizonEnd(now, deadline, nil, now, hp)
	if got.Before(deadline) {
		t.Fatalf("expected horizon to include deadline buffer; got=%s deadline=%s", got, deadline)
	}
	capped := computeAdaptiveHorizonEnd(now, now.Add(100*24*time.Hour), nil, now, hp)
	if capped.After(now.Add(hp.absoluteCap)) {
		t.Fatalf("expected capped horizon <= absolute cap; got=%s cap=%s", capped, now.Add(hp.absoluteCap))
	}
}

func Test_chooseTieredCandidate_prefersLowerSetupOnSameLatenessClass(t *testing.T) {
	cursor := time.Date(2026, 3, 24, 8, 0, 0, 0, time.UTC)
	deadline := cursor.Add(6 * time.Hour)
	cands := []CandidateMachine{
		{MachineID: "M-A", AvailableFrom: cursor.Add(30 * time.Minute)},
		{MachineID: "M-B", AvailableFrom: cursor.Add(30 * time.Minute)},
	}
	best, score := chooseTieredCandidate(cands, time.Hour, cursor, nil, deadline, "M-B")
	if best.MachineID != "M-B" {
		t.Fatalf("expected machine continuity preference to pick M-B, got %s", best.MachineID)
	}
	if score.setupCost != 0 {
		t.Fatalf("expected zero setup cost for same machine continuity, got %d", score.setupCost)
	}
}

func Test_defaultHorizonPolicy_explicitBoundaries(t *testing.T) {
	hp := defaultHorizonPolicy()
	if hp.rollingWindow != 72*time.Hour {
		t.Fatalf("expected rolling window 72h, got %s", hp.rollingWindow)
	}
	if hp.growBy != 8*time.Hour {
		t.Fatalf("expected growBy 8h, got %s", hp.growBy)
	}
	if hp.maxExpansions != 6 {
		t.Fatalf("expected maxExpansions 6, got %d", hp.maxExpansions)
	}
	// Default policy caps adaptive horizon at global 400d.
	if hp.absoluteCap != 400*24*time.Hour {
		t.Fatalf("expected absolute cap 400d, got %s", hp.absoluteCap)
	}
}

func Test_placementStages_matchConfiguredProfile(t *testing.T) {
	stages := placementStages()
	if len(stages) != 6 {
		t.Fatalf("expected 6 placement stages, got %d", len(stages))
	}
	expectedHorizon := []int{3, 7, 14, 21, 30, 400}
	expectedLateness := []int{0, 2, 7, 14, 30, 400}
	for i := range stages {
		if stages[i].HorizonDays != expectedHorizon[i] || stages[i].LatenessDays != expectedLateness[i] {
			t.Fatalf("unexpected stage[%d]: got horizon=%d lateness=%d", i, stages[i].HorizonDays, stages[i].LatenessDays)
		}
	}
}

func Test_topKByEarliestFinish_stableOrdering(t *testing.T) {
	cursor := time.Date(2026, 3, 24, 8, 0, 0, 0, time.UTC)
	cands := []CandidateMachine{
		{MachineID: "M2", AvailableFrom: cursor},
		{MachineID: "M1", AvailableFrom: cursor},
		{MachineID: "M3", AvailableFrom: cursor.Add(time.Hour)},
	}
	top := topKByEarliestFinish(cands, time.Hour, cursor, 2)
	if len(top) != 2 {
		t.Fatalf("expected top 2, got %d", len(top))
	}
	if top[0].MachineID != "M1" || top[1].MachineID != "M2" {
		t.Fatalf("expected stable machine_id tie break ordering M1,M2 got %s,%s", top[0].MachineID, top[1].MachineID)
	}
}

func Test_horizonTierConstants(t *testing.T) {
	if primaryHorizonDays != 3 {
		t.Fatalf("expected primary 3d, got %d", primaryHorizonDays)
	}
	if slightRelaxHorizonDays != 7 {
		t.Fatalf("expected slight relax 7d, got %d", slightRelaxHorizonDays)
	}
	if normalFallbackHorizonDays != 14 {
		t.Fatalf("expected normal fallback 14d, got %d", normalFallbackHorizonDays)
	}
	if aggressiveHorizonDays != 21 {
		t.Fatalf("expected aggressive 21d, got %d", aggressiveHorizonDays)
	}
	if lastResortHorizonDays != 30 {
		t.Fatalf("expected last resort 30d, got %d", lastResortHorizonDays)
	}
	if maxHorizonDays != 400 {
		t.Fatalf("expected max horizon 400d, got %d", maxHorizonDays)
	}
	if topKMachines != 5 {
		t.Fatalf("expected topKMachines 5, got %d", topKMachines)
	}
	if maxSlicesPerStep != 8 {
		t.Fatalf("expected maxSlicesPerStep 8, got %d", maxSlicesPerStep)
	}
	if minSliceMinutes != 30 {
		t.Fatalf("expected minSliceMinutes 30, got %d", minSliceMinutes)
	}
}

func Test_placementRetryEligible_filtersReasonCodes(t *testing.T) {
	if !placementRetryEligible([]string{"no feasible window found in scheduling horizon"}) {
		t.Fatalf("expected retry eligible for no feasible window")
	}
	if placementRetryEligible([]string{"reason_code=calendar_outside_shift"}) {
		t.Fatalf("expected retry ineligible for calendar_outside_shift")
	}
	if placementRetryEligible([]string{"reason_code=overlap_unresolved"}) {
		t.Fatalf("expected retry ineligible for overlap")
	}
	if placementRetryEligible([]string{"precedence violation"}) {
		t.Fatalf("expected retry ineligible for precedence")
	}
}

func Test_classifyAttemptResult_enumMapping(t *testing.T) {
	if got := classifyAttemptResult([]string{"reason_code=calendar_outside_shift"}); got != machineAttemptCalendar {
		t.Fatalf("expected CALENDAR, got %s", got)
	}
	if got := classifyAttemptResult([]string{"reason_code=overlap_unresolved"}); got != machineAttemptOverlap {
		t.Fatalf("expected OVERLAP, got %s", got)
	}
	if got := classifyAttemptResult([]string{"precedence violation"}); got != machineAttemptPrecedence {
		t.Fatalf("expected PRECEDENCE, got %s", got)
	}
	if got := classifyAttemptResult([]string{"no feasible window found in scheduling horizon"}); got != machineAttemptNoWindow {
		t.Fatalf("expected NO_WINDOW, got %s", got)
	}
}

func Test_shouldEarlyExitIdenticalFailure(t *testing.T) {
	if shouldEarlyExitIdenticalFailure(machineAttemptNoWindow, "NO_WINDOW|x", machineAttemptNoWindow, "NO_WINDOW|x", 2, false) {
		t.Fatalf("did not expect early exit under minimum attempt threshold")
	}
	if shouldEarlyExitIdenticalFailure(machineAttemptNoWindow, "NO_WINDOW|x", machineAttemptNoWindow, "NO_WINDOW|x", 3, false) {
		t.Fatalf("did not expect no-window early exit when disabled")
	}
	if !shouldEarlyExitIdenticalFailure(machineAttemptOverlap, "OVERLAP|x", machineAttemptOverlap, "OVERLAP|x", 3, false) {
		t.Fatalf("expected early exit for repeated non-no-window signature")
	}
	if shouldEarlyExitIdenticalFailure(machineAttemptNoWindow, "NO_WINDOW|x", machineAttemptNoWindow, "NO_WINDOW|y", 3, true) {
		t.Fatalf("did not expect early exit for different signatures")
	}
	if shouldEarlyExitIdenticalFailure(machineAttemptNoWindow, "NO_WINDOW|x", machineAttemptNoWindow, "NO_WINDOW|x", 1, true) {
		t.Fatalf("did not expect early exit on first attempt")
	}
}

func Test_placementCapEndHybrid_respectsNowAndDeadlineAnchors(t *testing.T) {
	now := time.Date(2026, 3, 24, 8, 0, 0, 0, time.UTC)
	start := now
	adaptive := now.Add(500 * 24 * time.Hour)
	effectiveDeadline := now.Add(10 * 24 * time.Hour)
	got := placementCapEndHybrid(now, start, adaptive, effectiveDeadline, 400)
	expect := effectiveDeadline.Add(time.Duration(hybridDeadlineBufferDays) * 24 * time.Hour)
	if !got.Equal(expect) {
		t.Fatalf("expected deadline-anchored hybrid cap %s, got %s", expect, got)
	}
	got2 := placementCapEndHybrid(now, start, adaptive, time.Time{}, 14)
	expect2 := now.Add(14 * 24 * time.Hour)
	if !got2.Equal(expect2) {
		t.Fatalf("expected now-anchored cap %s, got %s", expect2, got2)
	}
}

func Test_cloneTentativeSlots_immutableCopy(t *testing.T) {
	base := []TentativeSlot{
		{MachineID: "M-1", ScheduledStart: time.Date(2026, 1, 1, 8, 0, 0, 0, time.UTC), ScheduledEnd: time.Date(2026, 1, 1, 9, 0, 0, 0, time.UTC)},
	}
	cp := cloneTentativeSlots(base)
	cp[0].MachineID = "M-2"
	if base[0].MachineID != "M-1" {
		t.Fatalf("expected original tentative slice unchanged")
	}
}

func Test_planSplitSlicesSameMachineGreedy_deterministicAndComplete(t *testing.T) {
	free := []BusyInterval{
		{Start: time.Date(2026, 1, 1, 8, 0, 0, 0, time.UTC), End: time.Date(2026, 1, 1, 9, 0, 0, 0, time.UTC)},
		{Start: time.Date(2026, 1, 1, 10, 0, 0, 0, time.UTC), End: time.Date(2026, 1, 1, 11, 0, 0, 0, time.UTC)},
		{Start: time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC), End: time.Date(2026, 1, 1, 13, 0, 0, 0, time.UTC)},
	}
	res := planSplitSlicesSameMachineGreedy(free, 3*time.Hour)
	if !res.Valid {
		t.Fatalf("expected valid split plan")
	}
	if len(res.Slices) != 3 {
		t.Fatalf("expected 3 slices, got %d", len(res.Slices))
	}
	if res.CoveredMinutes < res.RequiredMinutes {
		t.Fatalf("expected covered >= required, got %d < %d", res.CoveredMinutes, res.RequiredMinutes)
	}
	for i := 0; i+1 < len(res.Slices); i++ {
		if res.Slices[i].End.After(res.Slices[i+1].Start) {
			t.Fatalf("slices overlap at index %d", i)
		}
	}
}

func Test_planSplitSlicesSameMachineGreedy_incompleteRejected(t *testing.T) {
	free := []BusyInterval{
		{Start: time.Date(2026, 1, 1, 8, 0, 0, 0, time.UTC), End: time.Date(2026, 1, 1, 8, 20, 0, 0, time.UTC)},
		{Start: time.Date(2026, 1, 1, 9, 0, 0, 0, time.UTC), End: time.Date(2026, 1, 1, 9, 20, 0, 0, time.UTC)},
	}
	res := planSplitSlicesSameMachineGreedy(free, time.Hour)
	if res.Valid {
		t.Fatalf("expected invalid split plan due to insufficient/min-slice windows")
	}
}

func Test_planSplitSlicesCrossMachineGreedy_canCoverWithFragmentedWindows(t *testing.T) {
	required := 90 * time.Minute
	machineFree := map[string][]BusyInterval{
		"M-A": {
			{Start: time.Date(2026, 1, 1, 8, 0, 0, 0, time.UTC), End: time.Date(2026, 1, 1, 8, 30, 0, 0, time.UTC)},
		},
		"M-B": {
			{Start: time.Date(2026, 1, 1, 8, 30, 0, 0, time.UTC), End: time.Date(2026, 1, 1, 9, 30, 0, 0, time.UTC)},
		},
	}
	used, res := planSplitSlicesCrossMachineGreedy(machineFree, required)
	if !res.Valid {
		t.Fatalf("expected valid cross-machine split plan")
	}
	if len(used) < 2 {
		t.Fatalf("expected at least two slices across machines, got %d", len(used))
	}
	if used[0].MachineID == "" || used[1].MachineID == "" {
		t.Fatalf("expected machine IDs for cross-machine slices")
	}
}

func Test_allocateSplitSliceQuantities_proportionalAndTotaled(t *testing.T) {
	slices := []BusyInterval{
		{Start: time.Date(2026, 1, 1, 8, 0, 0, 0, time.UTC), End: time.Date(2026, 1, 1, 8, 30, 0, 0, time.UTC)},
		{Start: time.Date(2026, 1, 1, 8, 30, 0, 0, time.UTC), End: time.Date(2026, 1, 1, 9, 30, 0, 0, time.UTC)},
	}
	got := allocateSplitSliceQuantities(90, slices)
	if len(got) != 2 {
		t.Fatalf("expected 2 allocations, got %d", len(got))
	}
	if got[0] != 30 || got[1] != 60 {
		t.Fatalf("expected proportional allocations [30 60], got %v", got)
	}
	if got[0]+got[1] != 90 {
		t.Fatalf("expected allocation total 90, got %d", got[0]+got[1])
	}
}

func Test_allocateSplitSliceQuantities_allowsSmallTemporalFragments(t *testing.T) {
	slices := []BusyInterval{
		{Start: time.Date(2026, 1, 1, 8, 0, 0, 0, time.UTC), End: time.Date(2026, 1, 1, 8, 20, 0, 0, time.UTC)},
		{Start: time.Date(2026, 1, 1, 8, 20, 0, 0, time.UTC), End: time.Date(2026, 1, 1, 8, 40, 0, 0, time.UTC)},
		{Start: time.Date(2026, 1, 1, 8, 40, 0, 0, time.UTC), End: time.Date(2026, 1, 1, 9, 0, 0, 0, time.UTC)},
	}
	got := allocateSplitSliceQuantities(10, slices)
	if len(got) != 3 {
		t.Fatalf("expected 3 allocations, got %v", got)
	}
	if got[0]+got[1]+got[2] != 10 {
		t.Fatalf("expected allocation total 10, got %d", got[0]+got[1]+got[2])
	}
}

func Test_freeIntervalsFromWindows_respectsBusyAndOrdering(t *testing.T) {
	work := []BusyInterval{
		{Start: time.Date(2026, 1, 1, 8, 0, 0, 0, time.UTC), End: time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)},
	}
	busy := []BusyInterval{
		{Start: time.Date(2026, 1, 1, 9, 0, 0, 0, time.UTC), End: time.Date(2026, 1, 1, 10, 0, 0, 0, time.UTC)},
	}
	free := freeIntervalsFromWindows(work, busy, work[0].Start, work[0].End, 10)
	if len(free) != 2 {
		t.Fatalf("expected 2 free intervals, got %d", len(free))
	}
	if !free[0].Start.Equal(time.Date(2026, 1, 1, 8, 0, 0, 0, time.UTC)) || !free[0].End.Equal(time.Date(2026, 1, 1, 9, 0, 0, 0, time.UTC)) {
		t.Fatalf("unexpected first free interval: %#v", free[0])
	}
}
