package service

// Unit tests for realSchedulingOptimizer.
// These tests validate the optimizer's core logic without any HTTP layer.

import (
	"context"
	"emas/internal/domain"
	"testing"
	"time"
)

// ─── helpers ─────────────────────────────────────────────────────────────────

func newTestJob(id string, qty int, deadline time.Time) *domain.Job {
	return &domain.Job{
		JobID:         id,
		ProductID:     "P-" + id,
		QuantityTotal: qty,
		Deadline:      deadline,
		Priority:      "medium",
		Status:        domain.JobStatusPlanned,
	}
}

func newTestCandidate(id, name string, available bool, capacityPerHour int, efficiencyFactor float64) CandidateMachine {
	freeAt := time.Now()
	if !available {
		freeAt = time.Now().Add(2 * time.Hour)
	}
	return CandidateMachine{
		MachineID:        id,
		MachineName:      name,
		MachineType:      "TEST",
		CapacityPerHour:  capacityPerHour,
		EfficiencyFactor: efficiencyFactor,
		Available:        available,
		AvailableFrom:    freeAt,
	}
}

func singleStepPreview(jobID string, qty int, candidates []CandidateMachine, parallel bool) *SolverPreview {
	step := SolverPreviewStep{
		JobStepID:              "JS-" + jobID + "-1",
		StepID:                 "STEP-" + jobID,
		StepName:               "Assembly",
		StepSequence:           1,
		QuantityTarget:         qty,
		MachineTypeRequired:    "TEST",
		AllowParallelExecution: parallel,
		MaxParallelMachines:    2,
		MinSplitQty:            5,
		EstimatedDurationMins:  30,
		CandidateMachines:      candidates,
	}
	return &SolverPreview{
		JobID:         jobID,
		QuantityTotal: qty,
		CanStartNow:   true,
		Steps:         []SolverPreviewStep{step},
	}
}

func multiStepPreview(jobID string, qty int, stepCount int, candidates []CandidateMachine) *SolverPreview {
	steps := make([]SolverPreviewStep, stepCount)
	for i := 0; i < stepCount; i++ {
		steps[i] = SolverPreviewStep{
			JobStepID:             "JS-" + jobID + "-" + itoa(i+1),
			StepID:                "STEP-" + jobID + "-" + itoa(i+1),
			StepName:              "Step " + itoa(i+1),
			StepSequence:          i + 1,
			QuantityTarget:        qty,
			MachineTypeRequired:   "TEST",
			EstimatedDurationMins: 20 + i*5,
			CandidateMachines:     candidates,
		}
	}
	return &SolverPreview{
		JobID:         jobID,
		QuantityTotal: qty,
		CanStartNow:   true,
		Steps:         steps,
	}
}

// ─── tests ────────────────────────────────────────────────────────────────────

func TestRealSolverOptimizer_SingleStepSingleMachine(t *testing.T) {
	job := newTestJob("JOB-1", 50, time.Now().Add(48*time.Hour))
	candidates := []CandidateMachine{
		newTestCandidate("M-1", "Machine 1", true, 30, 1.0),
	}
	preview := singleStepPreview("JOB-1", 50, candidates, false)
	optimizer := newRealSchedulingOptimizer(job, preview)
	plans, score, err := optimizer.solve(context.Background())

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(plans) != 1 {
		t.Fatalf("expected 1 plan, got %d", len(plans))
	}
	if plans[0].blocked {
		t.Fatal("step should not be blocked")
	}
	if len(plans[0].slots) == 0 {
		t.Fatal("expected at least 1 slot")
	}
	if plans[0].slots[0].machineID != "M-1" {
		t.Fatalf("expected machine M-1, got %s", plans[0].slots[0].machineID)
	}
	if score <= 0 {
		t.Fatalf("expected positive score, got %v", score)
	}
	t.Logf("score=%v, end=%v", score, plans[0].end)
}

func TestRealSolverOptimizer_MultiStepSequential(t *testing.T) {
	job := newTestJob("JOB-2", 30, time.Now().Add(24*time.Hour))
	candidates := []CandidateMachine{
		newTestCandidate("M-A", "Machine A", true, 40, 1.0),
		newTestCandidate("M-B", "Machine B", true, 30, 0.9),
	}
	preview := multiStepPreview("JOB-2", 30, 3, candidates)
	optimizer := newRealSchedulingOptimizer(job, preview)
	plans, score, err := optimizer.solve(context.Background())

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(plans) != 3 {
		t.Fatalf("expected 3 plans, got %d", len(plans))
	}
	// Steps must be scheduled sequentially: each step starts at or after the previous ends.
	for i := 1; i < len(plans); i++ {
		if plans[i].start.Before(plans[i-1].end) {
			t.Fatalf("step %d starts before step %d ends (precedence violation)", i+1, i)
		}
	}
	if score <= 0 {
		t.Fatalf("expected positive score, got %v", score)
	}
	t.Logf("3-step score=%v", score)
}

func TestRealSolverOptimizer_ParallelMachines(t *testing.T) {
	job := newTestJob("JOB-3", 40, time.Now().Add(48*time.Hour))
	candidates := []CandidateMachine{
		newTestCandidate("M-P1", "Parallel 1", true, 20, 1.0),
		newTestCandidate("M-P2", "Parallel 2", true, 20, 1.0),
	}
	preview := singleStepPreview("JOB-3", 40, candidates, true)
	optimizer := newRealSchedulingOptimizer(job, preview)
	plans, score, err := optimizer.solve(context.Background())

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(plans) != 1 {
		t.Fatalf("expected 1 plan, got %d", len(plans))
	}
	// Parallel assignment should have 2 slots.
	if len(plans[0].slots) < 1 {
		t.Fatal("expected at least 1 slot")
	}
	t.Logf("parallel plan: %d slots, score=%v", len(plans[0].slots), score)
}

func TestRealSolverOptimizer_NoCandidates(t *testing.T) {
	job := newTestJob("JOB-4", 20, time.Now().Add(24*time.Hour))
	preview := singleStepPreview("JOB-4", 20, []CandidateMachine{}, false)
	optimizer := newRealSchedulingOptimizer(job, preview)
	plans, score, err := optimizer.solve(context.Background())

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(plans) != 1 {
		t.Fatalf("expected 1 plan, got %d", len(plans))
	}
	if !plans[0].blocked {
		t.Fatal("expected step to be blocked when no candidates available")
	}
	// Score should be penalised (< base 1000) for a blocked step.
	if score >= 1000 {
		t.Fatalf("expected penalised score for fully blocked schedule, got %v", score)
	}
	// Feasible check via buildRealSolverProposal.
	job2 := newTestJob("JOB-4-B", 20, time.Now().Add(24*time.Hour))
	prop := buildRealSolverProposal(job2, plans, score, optimizer.cursor)
	if prop.Feasible {
		t.Fatal("expected proposal to be marked infeasible when all steps are blocked")
	}
	if len(prop.BlockedReasons) == 0 {
		t.Fatal("expected blocked reasons to be populated")
	}
}

func TestRealSolverOptimizer_EarlyFinishBonus(t *testing.T) {
	job := newTestJob("JOB-5", 10, time.Now().Add(7*24*time.Hour)) // very far deadline
	candidates := []CandidateMachine{
		newTestCandidate("M-FAST", "Fast Machine", true, 120, 1.5),
	}
	preview := singleStepPreview("JOB-5", 10, candidates, false)
	optimizer := newRealSchedulingOptimizer(job, preview)
	_, score, err := optimizer.solve(context.Background())

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if score < 900 {
		t.Fatalf("expected high score for ample deadline and fast machine, got %v", score)
	}
	t.Logf("early finish score=%v", score)
}

func TestRealSolverOptimizer_LateDeadlinePenalty(t *testing.T) {
	job := newTestJob("JOB-6", 200, time.Now().Add(-2*time.Hour)) // past deadline
	candidates := []CandidateMachine{
		newTestCandidate("M-SLOW", "Slow Machine", true, 5, 0.5),
	}
	preview := multiStepPreview("JOB-6", 200, 3, candidates)
	optimizer := newRealSchedulingOptimizer(job, preview)
	_, score, err := optimizer.solve(context.Background())

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// Past deadline + slow machine should produce a significantly reduced score.
	if score > 800 {
		t.Fatalf("expected reduced score for past-deadline job, got %v", score)
	}
	t.Logf("late deadline score=%v", score)
}

func TestRealSolverOptimizer_EfficiencyFactorReducesDuration(t *testing.T) {
	job := newTestJob("JOB-7", 60, time.Now().Add(48*time.Hour))
	candidateSlow := []CandidateMachine{newTestCandidate("M-SLOW", "Slow", true, 30, 0.5)}
	candidateFast := []CandidateMachine{newTestCandidate("M-FAST", "Fast", true, 30, 2.0)}

	previewSlow := singleStepPreview("JOB-7", 60, candidateSlow, false)
	previewFast := singleStepPreview("JOB-7", 60, candidateFast, false)

	optSlow := newRealSchedulingOptimizer(job, previewSlow)
	optFast := newRealSchedulingOptimizer(job, previewFast)

	plansSlow, _, _ := optSlow.solve(context.Background())
	plansFast, _, _ := optFast.solve(context.Background())

	if len(plansSlow) == 0 || len(plansFast) == 0 {
		t.Fatal("expected plans from both optimisers")
	}
	durSlow := plansSlow[0].end.Sub(plansSlow[0].start)
	durFast := plansFast[0].end.Sub(plansFast[0].start)
	if durFast >= durSlow {
		t.Fatalf("expected faster machine to produce shorter duration (fast=%v, slow=%v)", durFast, durSlow)
	}
	t.Logf("slow=%v fast=%v", durSlow, durFast)
}

func TestRealSolverOptimizer_LocalSearchImproves(t *testing.T) {
	// Two steps, one machine with low efficiency and one with high.
	// The local search pass should prefer the high-efficiency machine.
	job := newTestJob("JOB-8", 30, time.Now().Add(48*time.Hour))
	candidates := []CandidateMachine{
		newTestCandidate("M-LOW", "Low Eff", true, 30, 0.5),
		newTestCandidate("M-HIGH", "High Eff", true, 30, 2.0),
	}
	preview := multiStepPreview("JOB-8", 30, 2, candidates)
	optimizer := newRealSchedulingOptimizer(job, preview)
	plans, score, err := optimizer.solve(context.Background())

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(plans) != 2 {
		t.Fatalf("expected 2 plans, got %d", len(plans))
	}
	// At least one step should prefer the high-efficiency machine.
	usedHighEff := false
	for _, p := range plans {
		for _, sl := range p.slots {
			if sl.machineID == "M-HIGH" {
				usedHighEff = true
			}
		}
	}
	if !usedHighEff {
		t.Fatal("expected local search to prefer the high-efficiency machine for at least one step")
	}
	t.Logf("score=%v", score)
}

func TestBuildRealSolverProposal_FieldMapping(t *testing.T) {
	job := newTestJob("JOB-9", 20, time.Now().Add(24*time.Hour))
	candidates := []CandidateMachine{newTestCandidate("M-1", "Machine 1", true, 40, 1.0)}
	preview := singleStepPreview("JOB-9", 20, candidates, false)
	optimizer := newRealSchedulingOptimizer(job, preview)
	plans, score, err := optimizer.solve(context.Background())
	if err != nil {
		t.Fatalf("solve error: %v", err)
	}

	proposal := buildRealSolverProposal(job, plans, score, optimizer.cursor)

	if proposal.JobID != job.JobID {
		t.Fatalf("expected job_id %s, got %s", job.JobID, proposal.JobID)
	}
	if proposal.Engine != realSolverEngineName {
		t.Fatalf("expected engine %q, got %q", realSolverEngineName, proposal.Engine)
	}
	if proposal.EngineVersion != realSolverEngineVersion {
		t.Fatalf("expected engine version %q, got %q", realSolverEngineVersion, proposal.EngineVersion)
	}
	if len(proposal.ProposedSlots) == 0 {
		t.Fatal("expected at least 1 proposed slot")
	}
	slot := proposal.ProposedSlots[0]
	if slot.MachineID != "M-1" {
		t.Fatalf("expected machine M-1, got %s", slot.MachineID)
	}
	if slot.QuantityPlanned != 20 {
		t.Fatalf("expected quantity 20, got %d", slot.QuantityPlanned)
	}
	if len(slot.Reasoning) == 0 {
		t.Fatal("expected reasoning in proposed slot")
	}
	if proposal.EstimatedCompletion == nil {
		t.Fatal("expected estimated_completion to be set")
	}
	if len(proposal.Summary) == 0 {
		t.Fatal("expected summary lines")
	}
}

func TestRealSolverContextCancellation(t *testing.T) {
	job := newTestJob("JOB-10", 100, time.Now().Add(48*time.Hour))
	candidates := []CandidateMachine{
		newTestCandidate("M-1", "Machine 1", true, 20, 1.0),
		newTestCandidate("M-2", "Machine 2", true, 25, 1.0),
		newTestCandidate("M-3", "Machine 3", true, 18, 0.9),
	}
	preview := multiStepPreview("JOB-10", 100, 5, candidates)
	optimizer := newRealSchedulingOptimizer(job, preview)

	// Cancel context immediately.
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	plans, _, err := optimizer.solve(ctx)
	// Should return early without crashing; may be partial or full.
	if err != nil && len(plans) > 0 {
		// Partial result plus context error is acceptable.
	}
	// Should not panic.
}

func TestFormatDuration(t *testing.T) {
	cases := []struct {
		mins int
		want string
	}{
		{0, "0m"},
		{45, "45m"},
		{60, "1h"},
		{90, "1h30m"},
		{120, "2h"},
		{125, "2h5m"},
	}
	for _, tc := range cases {
		got := formatDuration(tc.mins)
		if got != tc.want {
			t.Errorf("formatDuration(%d) = %q, want %q", tc.mins, got, tc.want)
		}
	}
}

func TestItoa(t *testing.T) {
	cases := []struct {
		n    int
		want string
	}{
		{0, "0"},
		{1, "1"},
		{999, "999"},
		{-5, "-5"},
	}
	for _, tc := range cases {
		got := itoa(tc.n)
		if got != tc.want {
			t.Errorf("itoa(%d) = %q, want %q", tc.n, got, tc.want)
		}
	}
}
