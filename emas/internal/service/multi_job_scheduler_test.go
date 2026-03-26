package service

import (
	"emas/internal/domain"
	"emas/internal/repository"
	"emas/internal/testutil"
	"testing"
	"time"
)

func TestRescheduleAll_LockInWindowSkipsImminentJobs(t *testing.T) {
	db := testutil.NewTestDB(t)

	jobRepo := repository.NewJobRepository(db)
	stepRepo := repository.NewJobStepRepository(db)
	slotRepo := repository.NewJobSlotRepository(db)
	proposalRepo := repository.NewAIProposalRepository(db)
	machineRepo := repository.NewMachineRepository(db)
	maintenanceRepo := repository.NewMaintenanceRepository(db)
	settingsRepo := repository.NewSystemSettingsRepository(db)

	// Set lock-in window to 240 minutes (default).
	_ = settingsRepo.PutInt("scheduling.lock_in_window_minutes", 240)

	// Minimal scheduling service graph (many deps are unused by resolveJobsForReschedule path).
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

	// Create two planned jobs.
	j1 := domain.Job{JobID: "JOB-LOCK-1", ProductID: "P-1", QuantityTotal: 1, Priority: domain.JobPriorityLow, Deadline: time.Now().Add(24 * time.Hour), Status: domain.JobStatusPlanned}
	j2 := domain.Job{JobID: "JOB-LOCK-2", ProductID: "P-1", QuantityTotal: 1, Priority: domain.JobPriorityLow, Deadline: time.Now().Add(24 * time.Hour), Status: domain.JobStatusPlanned}
	_ = jobRepo.Create(&j1)
	_ = jobRepo.Create(&j2)

	// Create job steps so slots can join to job_id.
	js1 := domain.JobSteps{JobStepID: "JS-1", JobID: j1.JobID, StepID: "S1", StepSequence: 1, QuantityTarget: 1}
	js2 := domain.JobSteps{JobStepID: "JS-2", JobID: j2.JobID, StepID: "S1", StepSequence: 1, QuantityTarget: 1}
	_ = stepRepo.Create(&js1)
	_ = stepRepo.Create(&js2)

	// Add an imminent active slot for JOB-LOCK-1 starting within 4 hours.
	now := time.Now()
	s1 := domain.JobStepScheduleSlots{
		SlotID:         "SLOT-1",
		JobStepID:      js1.JobStepID,
		ProposalID:     "P",
		MachineID:      "M1",
		ScheduledStart: now.Add(30 * time.Minute),
		ScheduledEnd:   now.Add(60 * time.Minute),
		Status:         domain.SlotStatusPlanned,
	}
	_ = slotRepo.Create(&s1)

	// JOB-LOCK-2 has no active slot.

	jobs, err := ai.resolveJobsForReschedule()
	if err != nil {
		t.Fatalf("resolveJobsForReschedule err: %v", err)
	}
	found1 := false
	found2 := false
	for _, j := range jobs {
		if j.JobID == j1.JobID {
			found1 = true
		}
		if j.JobID == j2.JobID {
			found2 = true
		}
	}
	if found1 {
		t.Fatalf("expected %s to be excluded by lock-in window", j1.JobID)
	}
	if !found2 {
		t.Fatalf("expected %s to remain eligible", j2.JobID)
	}
}

func Test_sortJobsByOrder_EDD(t *testing.T) {
	now := time.Now().UTC()
	jobs := []domain.Job{
		{JobID: "J1", Deadline: now.Add(48 * time.Hour), CreatedAt: now},
		{JobID: "J2", Deadline: now.Add(24 * time.Hour), CreatedAt: now},
		{JobID: "J3", Deadline: now.Add(72 * time.Hour), CreatedAt: now},
	}
	sortJobsByOrder(jobs, "edd", nil)
	if jobs[0].JobID != "J2" {
		t.Fatalf("EDD: first should be J2 (earliest deadline), got %s", jobs[0].JobID)
	}
	if jobs[1].JobID != "J1" {
		t.Fatalf("EDD: second should be J1, got %s", jobs[1].JobID)
	}
	if jobs[2].JobID != "J3" {
		t.Fatalf("EDD: third should be J3, got %s", jobs[2].JobID)
	}
}

func Test_sortJobsByOrder_EPO(t *testing.T) {
	now := time.Now().UTC()
	jobs := []domain.Job{
		{JobID: "J1", Priority: domain.JobPriorityLow, Deadline: now.Add(24 * time.Hour), CreatedAt: now},
		{JobID: "J2", Priority: domain.JobPriorityHigh, Deadline: now.Add(48 * time.Hour), CreatedAt: now},
		{JobID: "J3", Priority: domain.JobPriorityUrgent, Deadline: now.Add(72 * time.Hour), CreatedAt: now},
	}
	sortJobsByOrder(jobs, "epo", nil)
	if jobs[0].JobID != "J3" {
		t.Fatalf("EPO: first should be J3 (urgent), got %s", jobs[0].JobID)
	}
	if jobs[1].JobID != "J2" {
		t.Fatalf("EPO: second should be J2 (high), got %s", jobs[1].JobID)
	}
	if jobs[2].JobID != "J1" {
		t.Fatalf("EPO: third should be J1 (low), got %s", jobs[2].JobID)
	}
}

func Test_sortJobsByOrder_EPO_tieBreakDeadline(t *testing.T) {
	now := time.Now().UTC()
	jobs := []domain.Job{
		{JobID: "J1", Priority: domain.JobPriorityHigh, Deadline: now.Add(48 * time.Hour), CreatedAt: now},
		{JobID: "J2", Priority: domain.JobPriorityHigh, Deadline: now.Add(24 * time.Hour), CreatedAt: now},
	}
	sortJobsByOrder(jobs, "epo", nil)
	if jobs[0].JobID != "J2" {
		t.Fatalf("EPO tie-break: first should be J2 (earlier deadline), got %s", jobs[0].JobID)
	}
}

func Test_sortJobsByOrder_FIFO(t *testing.T) {
	base := time.Now().UTC()
	jobs := []domain.Job{
		{JobID: "J1", CreatedAt: base.Add(2 * time.Hour), Deadline: base},
		{JobID: "J2", CreatedAt: base, Deadline: base},
		{JobID: "J3", CreatedAt: base.Add(1 * time.Hour), Deadline: base},
	}
	sortJobsByOrder(jobs, "fifo", nil)
	if jobs[0].JobID != "J2" {
		t.Fatalf("FIFO: first should be J2 (earliest CreatedAt), got %s", jobs[0].JobID)
	}
	if jobs[1].JobID != "J3" {
		t.Fatalf("FIFO: second should be J3, got %s", jobs[1].JobID)
	}
	if jobs[2].JobID != "J1" {
		t.Fatalf("FIFO: third should be J1, got %s", jobs[2].JobID)
	}
}

func Test_sortJobsByOrder_readiness(t *testing.T) {
	now := time.Now().UTC()
	later := now.Add(7 * 24 * time.Hour)
	jobs := []domain.Job{
		{JobID: "J1", Priority: domain.JobPriorityHigh, Deadline: now, CreatedAt: now},
		{JobID: "J2", Priority: domain.JobPriorityHigh, Deadline: now, CreatedAt: now},
		{JobID: "J3", Priority: domain.JobPriorityMedium, Deadline: now, CreatedAt: now},
	}
	readinessAt := map[string]time.Time{
		"J1": later,
		"J2": now,
		"J3": now.Add(1 * time.Hour),
	}
	sortJobsByOrder(jobs, "readiness", readinessAt)
	if jobs[0].JobID != "J2" {
		t.Fatalf("readiness: first should be J2 (ready now), got %s", jobs[0].JobID)
	}
	if jobs[1].JobID != "J3" {
		t.Fatalf("readiness: second should be J3 (ready +1h), got %s", jobs[1].JobID)
	}
	if jobs[2].JobID != "J1" {
		t.Fatalf("readiness: third should be J1 (ready +7d), got %s", jobs[2].JobID)
	}
}

func Test_sortJobsByOrder_defaultFallback(t *testing.T) {
	now := time.Now().UTC()
	jobs := []domain.Job{
		{JobID: "J1", Priority: domain.JobPriorityHigh, Deadline: now, CreatedAt: now},
	}
	sortJobsByOrder(jobs, "invalid", nil)
	sortJobsByOrder(jobs, "", nil)
	if len(jobs) != 1 || jobs[0].JobID != "J1" {
		t.Fatal("invalid/empty order_by should fallback to EPO without panicking")
	}
}

func Test_repairOverlapsInProposals_ChainedConflictsResolved(t *testing.T) {
	base := time.Date(2026, 3, 24, 8, 0, 0, 0, time.UTC)
	p1 := &SchedulingProposal{
		JobID: "J1",
		ProposedSlots: []ProposedSlot{
			{MachineID: "M-CNC-01", ScheduledStart: base, ScheduledEnd: base.Add(2 * time.Hour)},
		},
	}
	p2 := &SchedulingProposal{
		JobID: "J2",
		ProposedSlots: []ProposedSlot{
			{MachineID: "M-CNC-01", ScheduledStart: base.Add(30 * time.Minute), ScheduledEnd: base.Add(3 * time.Hour)},
		},
	}
	p3 := &SchedulingProposal{
		JobID: "J3",
		ProposedSlots: []ProposedSlot{
			{MachineID: "M-CNC-01", ScheduledStart: base.Add(1 * time.Hour), ScheduledEnd: base.Add(4 * time.Hour)},
		},
	}
	proposals := []*SchedulingProposal{p1, p2, p3}
	changed := repairOverlapsInProposals(proposals)
	if !changed {
		t.Fatal("expected overlap repair to modify proposals")
	}
	if machines := overlappingMachinesInProposals(proposals); len(machines) != 0 {
		t.Fatalf("expected no overlapping machines after repair, got %v", machines)
	}
}

func Test_rebalanceByDeadlinePressure_prioritizesMoreLateJobs(t *testing.T) {
	base := time.Date(2026, 3, 24, 8, 0, 0, 0, time.UTC)
	p1End := base.Add(10 * time.Hour)
	p2End := base.Add(6 * time.Hour)
	proposals := []*SchedulingProposal{
		{JobID: "J1", EarliestStart: base, EstimatedCompletion: &p1End},
		{JobID: "J2", EarliestStart: base, EstimatedCompletion: &p2End},
	}
	deadlines := map[string]time.Time{
		"J1": base.Add(5 * time.Hour),
		"J2": base.Add(5 * time.Hour),
	}
	rebalanceByDeadlinePressure(proposals, deadlines)
	if proposals[0].JobID != "J1" {
		t.Fatalf("expected most late proposal first, got %s", proposals[0].JobID)
	}
}

func Test_linearizeOverlapsByMachine_removesSimpleOverlap(t *testing.T) {
	base := time.Date(2026, 3, 24, 8, 0, 0, 0, time.UTC)
	p1 := &SchedulingProposal{JobID: "J1", ProposedSlots: []ProposedSlot{{MachineID: "M1", ScheduledStart: base, ScheduledEnd: base.Add(2 * time.Hour)}}}
	p2 := &SchedulingProposal{JobID: "J2", ProposedSlots: []ProposedSlot{{MachineID: "M1", ScheduledStart: base.Add(time.Hour), ScheduledEnd: base.Add(3 * time.Hour)}}}
	proposals := []*SchedulingProposal{p1, p2}
	linearizeOverlapsByMachine(proposals)
	if p2.ProposedSlots[0].ScheduledStart.Before(p1.ProposedSlots[0].ScheduledEnd) {
		t.Fatalf("expected p2 start >= p1 end after linearize, got %s < %s", p2.ProposedSlots[0].ScheduledStart, p1.ProposedSlots[0].ScheduledEnd)
	}
}

func Test_tentativeSlotsFromActiveRows_ExcludeSelectedJobs(t *testing.T) {
	rows := []repository.ActiveSlotRow{
		{
			JobID:          "JOB-SELECTED",
			MachineID:      "M-CNC-01",
			ScheduledStart: time.Date(2026, 3, 24, 8, 0, 0, 0, time.UTC),
			ScheduledEnd:   time.Date(2026, 3, 24, 9, 0, 0, 0, time.UTC),
		},
		{
			JobID:          "JOB-LOCKED",
			MachineID:      "M-CNC-02",
			ScheduledStart: time.Date(2026, 3, 24, 9, 0, 0, 0, time.UTC),
			ScheduledEnd:   time.Date(2026, 3, 24, 10, 0, 0, 0, time.UTC),
		},
	}
	excluded := map[string]bool{"JOB-SELECTED": true}
	tentative := tentativeSlotsFromActiveRows(rows, excluded)
	if len(tentative) != 1 {
		t.Fatalf("expected 1 tentative slot, got %d", len(tentative))
	}
	if tentative[0].MachineID != "M-CNC-02" {
		t.Fatalf("expected remaining machine M-CNC-02, got %s", tentative[0].MachineID)
	}
}
