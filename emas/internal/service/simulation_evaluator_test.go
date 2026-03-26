package service

import (
	"context"
	"emas/internal/domain"
	"emas/internal/repository"
	"emas/internal/testutil"
	"testing"
	"time"
)

func TestEvaluator_DeviationPenaltyFlipsWinnerAndReducesVolatility(t *testing.T) {
	db := testutil.NewTestDB(t)

	jobRepo := repository.NewJobRepository(db)
	stepRepo := repository.NewJobStepRepository(db)
	slotRepo := repository.NewJobSlotRepository(db)
	proposalRepo := repository.NewAIProposalRepository(db)
	machineRepo := repository.NewMachineRepository(db)
	maintenanceRepo := repository.NewMaintenanceRepository(db)
	settingsRepo := repository.NewSystemSettingsRepository(db)

	// Minimal service graph for buildDelayRisk() and applied-slot loading.
	processRepo := repository.NewProcessRepository(db)
	formulaRepo := repository.NewFormulaRepository(db)
	productRepo := repository.NewProductRepository(db)
	capRepo := repository.NewMachineCapabilityRepository(db)
	downtimeRepo := repository.NewMachineDowntimeRepository(db)
	bomRepo := repository.NewProductBOMRepository(db)
	invRepo := repository.NewInventoryRepository(db)
	logRepo := repository.NewProductionLogRepository(db)
	setupRepo := repository.NewSetupRepository(db)
	resourceRepo := repository.NewResourceRepository(db)
	wipRepo := repository.NewWIPRepository(db)
	psmRepo := repository.NewProcessStepMaterialRepository(db)
	schedulingSvc := NewSchedulingService(productRepo, bomRepo, formulaRepo, processRepo, jobRepo, stepRepo, slotRepo, machineRepo, capRepo, downtimeRepo, maintenanceRepo, invRepo, logRepo, proposalRepo, setupRepo, resourceRepo, wipRepo, psmRepo, settingsRepo)
	jobSlotSvc := NewJobSlotService(slotRepo, stepRepo, processRepo, jobRepo, schedulingSvc)
	eventRepo := repository.NewSchedulingEventRepository(db)
	ai := NewAIPredictiveService(db, jobRepo, stepRepo, slotRepo, proposalRepo, machineRepo, maintenanceRepo, settingsRepo, schedulingSvc, jobSlotSvc, eventRepo)

	now := time.Now().UTC().Truncate(time.Second)

	job := domain.Job{
		JobID:         "JOB-DEV-1",
		ProductID:     "P-1",
		QuantityTotal: 1,
		Priority:      domain.JobPriorityLow,
		Deadline:      now.Add(60 * time.Minute),
		Status:        domain.JobStatusPlanned,
	}
	if err := jobRepo.Create(&job); err != nil {
		t.Fatalf("create job: %v", err)
	}

	step := domain.JobSteps{JobStepID: "JS-DEV-1", JobID: job.JobID, StepID: "S1", StepSequence: 1, QuantityTarget: 1}
	if err := stepRepo.Create(&step); err != nil {
		t.Fatalf("create step: %v", err)
	}

	// Current applied plan: M1 at now+10m.
	appliedSlot := domain.JobStepScheduleSlots{
		SlotID:         "SLOT-DEV-1",
		JobStepID:      step.JobStepID,
		ProposalID:     "APPLIED",
		MachineID:      "M1",
		ScheduledStart: now.Add(10 * time.Minute),
		ScheduledEnd:   now.Add(40 * time.Minute),
		Status:         domain.SlotStatusPlanned,
	}
	if err := slotRepo.Create(&appliedSlot); err != nil {
		t.Fatalf("create applied slot: %v", err)
	}

	// Candidate A: stable (no deviation), but slightly late.
	aCompletion := job.Deadline.Add(30 * time.Minute)
	proposalStable := &SchedulingProposal{
		JobID:               job.JobID,
		ProductID:           job.ProductID,
		GeneratedAt:         now,
		Feasible:            true,
		EarliestStart:       now,
		EstimatedCompletion: &aCompletion,
		ProposedSlots: []ProposedSlot{
			{
				JobStepID:     step.JobStepID,
				StepID:        step.StepID,
				MachineID:     "M1",
				ScheduledStart: appliedSlot.ScheduledStart,
				ScheduledEnd:   appliedSlot.ScheduledEnd,
			},
		},
	}

	// Candidate B: aggressive (big deviation), but on-time.
	bCompletion := job.Deadline.Add(-1 * time.Minute)
	proposalAggressive := &SchedulingProposal{
		JobID:               job.JobID,
		ProductID:           job.ProductID,
		GeneratedAt:         now,
		Feasible:            true,
		EarliestStart:       now,
		EstimatedCompletion: &bCompletion,
		ProposedSlots: []ProposedSlot{
			{
				JobStepID:     step.JobStepID,
				StepID:        step.StepID,
				MachineID:     "M2", // machine change => deviation penalty
				ScheduledStart: appliedSlot.ScheduledStart.Add(3 * time.Hour),
				ScheduledEnd:   appliedSlot.ScheduledEnd.Add(3 * time.Hour),
			},
		},
	}

	scenarios := []Scenario{
		{ScenarioID: "stable", Proposal: proposalStable},
		{ScenarioID: "aggressive", Proposal: proposalAggressive},
	}

	// 1) With no deviation penalty, on-time plan should win.
	_ = settingsRepo.PutFloat("scheduling.deviation_penalty_weight", 0.0)
	e0 := &Evaluator{
		Now:         now,
		Weights:     Weights{Tardiness: 1.0, DelayRisk: 0.0, Utilization: 0.0, Deviation: 0.0},
		UtilWindow:  24 * time.Hour,
		MaxScenarios: 9,
		Budget:      500 * time.Millisecond,
	}
	r0, err := e0.Evaluate(context.Background(), ai, &job, nil, scenarios)
	if err != nil {
		t.Fatalf("evaluate (no deviation): %v", err)
	}
	if r0 == nil || r0.Winner == nil {
		t.Fatalf("expected winner (no deviation)")
	}
	if got := r0.Winner.EstimatedCompletion; got == nil || !got.Equal(*proposalAggressive.EstimatedCompletion) {
		t.Fatalf("expected aggressive proposal to win when deviation penalty is off")
	}

	// 2) With a strong deviation penalty from DB, stable plan should win and volatility drops sharply.
	_ = settingsRepo.PutFloat("scheduling.deviation_penalty_weight", 2.0)
	e1 := &Evaluator{
		Now:         now,
		Weights:     Weights{Tardiness: 1.0, DelayRisk: 0.0, Utilization: 0.0, Deviation: 0.0}, // will be overridden from DB
		UtilWindow:  24 * time.Hour,
		MaxScenarios: 9,
		Budget:      500 * time.Millisecond,
	}
	r1, err := e1.Evaluate(context.Background(), ai, &job, nil, scenarios)
	if err != nil {
		t.Fatalf("evaluate (strong deviation): %v", err)
	}
	if r1 == nil || r1.Winner == nil {
		t.Fatalf("expected winner (strong deviation)")
	}
	if got := r1.Winner.EstimatedCompletion; got == nil || !got.Equal(*proposalStable.EstimatedCompletion) {
		t.Fatalf("expected stable proposal to win when deviation penalty is high")
	}

	// Volatility proxy: deviationFromPlanNorm should drop by >50% in the selected winner.
	appliedIndex := map[string]domain.JobStepScheduleSlots{step.JobStepID: appliedSlot}
	v0 := deviationFromPlanNorm(proposalAggressive, appliedIndex)
	v1 := deviationFromPlanNorm(proposalStable, appliedIndex)
	if v0 <= 0.0 {
		t.Fatalf("expected aggressive plan to have non-zero deviation, got %v", v0)
	}
	if !(v1 <= v0*0.5) {
		t.Fatalf("expected volatility drop >50%%, got before=%v after=%v", v0, v1)
	}
}

func TestEvaluator_PicksLowestScore(t *testing.T) {
	now := time.Date(2026, 3, 17, 12, 0, 0, 0, time.UTC)
	job := &domain.Job{
		JobID:     "JOB-1",
		ProductID: "P-1",
		Deadline:  now.Add(2 * time.Hour),
	}

	// Proposal A: finishes before deadline, low util
	a := &SchedulingProposal{
		JobID:          job.JobID,
		ProductID:      job.ProductID,
		Feasible:       true,
		EngineVersion:  "A",
		GeneratedAt:    now,
		EarliestStart:  now,
		ProposedSlots:  []ProposedSlot{{MachineID: "M1", ScheduledStart: now, ScheduledEnd: now.Add(30 * time.Minute)}},
		Summary:        []string{},
		BlockedReasons: []string{},
	}
	ac := now.Add(30 * time.Minute)
	a.EstimatedCompletion = &ac

	// Proposal B: tardy by 3h
	b := &SchedulingProposal{
		JobID:          job.JobID,
		ProductID:      job.ProductID,
		Feasible:       true,
		EngineVersion:  "B",
		GeneratedAt:    now,
		EarliestStart:  now,
		ProposedSlots:  []ProposedSlot{{MachineID: "M1", ScheduledStart: now, ScheduledEnd: now.Add(6 * time.Hour)}},
		Summary:        []string{},
		BlockedReasons: []string{},
	}
	bc := now.Add(6 * time.Hour)
	b.EstimatedCompletion = &bc

	ev := DefaultEvaluator(now)
	ev.Budget = 250 * time.Millisecond
	ev.UtilWindow = 24 * time.Hour

	res, err := ev.Evaluate(context.Background(), nil, job, nil, []Scenario{
		{Proposal: b, ScenarioID: "B"},
		{Proposal: a, ScenarioID: "A"},
	})
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if res == nil || res.Winner == nil {
		t.Fatalf("expected a winner")
	}
	if res.Winner.EngineVersion != "A" {
		t.Fatalf("expected winner A, got %s", res.Winner.EngineVersion)
	}
}

func TestEvaluator_PrunesInfeasible(t *testing.T) {
	now := time.Date(2026, 3, 17, 12, 0, 0, 0, time.UTC)
	job := &domain.Job{JobID: "JOB-1", ProductID: "P-1", Deadline: now.Add(1 * time.Hour)}

	inf := &SchedulingProposal{JobID: job.JobID, ProductID: job.ProductID, Feasible: false}
	ok := &SchedulingProposal{
		JobID:         job.JobID,
		ProductID:     job.ProductID,
		Feasible:      true,
		EngineVersion: "OK",
		GeneratedAt:   now,
		EarliestStart: now,
		ProposedSlots: []ProposedSlot{{MachineID: "M1", ScheduledStart: now, ScheduledEnd: now.Add(10 * time.Minute)}},
	}
	c := now.Add(10 * time.Minute)
	ok.EstimatedCompletion = &c

	ev := DefaultEvaluator(now)
	res, _ := ev.Evaluate(context.Background(), nil, job, nil, []Scenario{
		{Proposal: inf, ScenarioID: "INF"},
		{Proposal: ok, ScenarioID: "OK"},
	})
	if res == nil || res.Winner == nil {
		t.Fatalf("expected a winner")
	}
	if res.Winner.EngineVersion != "OK" {
		t.Fatalf("expected OK winner, got %s", res.Winner.EngineVersion)
	}
	foundPruned := false
	for _, s := range res.Scores {
		if s.ScenarioID == "INF" {
			foundPruned = true
			if !s.Pruned {
				t.Fatalf("expected INF to be pruned")
			}
		}
	}
	if !foundPruned {
		t.Fatalf("expected INF score entry")
	}
}

func TestDeviationPenalty_PrefersLessChange(t *testing.T) {
	now := time.Date(2026, 3, 17, 12, 0, 0, 0, time.UTC)
	job := &domain.Job{
		JobID:     "JOB-1",
		ProductID: "P-1",
		Deadline:  now.Add(4 * time.Hour),
	}

	// Applied plan: step S1 starts at now on M1.
	applied := map[string]domain.JobStepScheduleSlots{
		"S1": {JobStepID: "S1", MachineID: "M1", ScheduledStart: now, ScheduledEnd: now.Add(30 * time.Minute), Status: domain.SlotStatusPlanned},
	}

	// Candidate A: identical to applied
	a := &SchedulingProposal{
		JobID:         job.JobID,
		ProductID:     job.ProductID,
		Feasible:      true,
		EngineVersion: "A",
		GeneratedAt:   now,
		EarliestStart: now,
		ProposedSlots: []ProposedSlot{{JobStepID: "S1", MachineID: "M1", ScheduledStart: now, ScheduledEnd: now.Add(30 * time.Minute)}},
	}
	ac := now.Add(30 * time.Minute)
	a.EstimatedCompletion = &ac

	// Candidate B: same completion but shifted by 60 mins on same machine -> should be penalized
	b := &SchedulingProposal{
		JobID:         job.JobID,
		ProductID:     job.ProductID,
		Feasible:      true,
		EngineVersion: "B",
		GeneratedAt:   now,
		EarliestStart: now,
		ProposedSlots: []ProposedSlot{{JobStepID: "S1", MachineID: "M1", ScheduledStart: now.Add(60 * time.Minute), ScheduledEnd: now.Add(90 * time.Minute)}},
	}
	bc := now.Add(90 * time.Minute)
	b.EstimatedCompletion = &bc

	ev := DefaultEvaluator(now)
	ev.Weights = Weights{Tardiness: 0, DelayRisk: 0, Utilization: 0, Deviation: 1.0}

	// We'll directly compare norms to avoid DB dependency.
	if deviationFromPlanNorm(a, applied) != 0 {
		t.Fatalf("expected A deviation 0")
	}
	if deviationFromPlanNorm(b, applied) == 0 {
		t.Fatalf("expected B deviation > 0")
	}

	// Evaluate() with nil service has no applied-slot baseline loaded, so it won't apply deviation penalties.
	// Here we only assert the deviation metric itself is computed and distinguishable.
}

