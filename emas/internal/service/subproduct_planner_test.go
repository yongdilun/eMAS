package service

import (
	"emas/internal/domain"
	"emas/internal/repository"
	"emas/internal/testutil"
	"testing"
	"time"
)

func TestProductAvailabilityForPlanning_OnlyUsesEarlierLedgerOutput(t *testing.T) {
	db := testutil.NewTestDB(t)
	jobRepo := repository.NewJobRepository(db)
	stepRepo := repository.NewJobStepRepository(db)
	slotRepo := repository.NewJobSlotRepository(db)
	proposalRepo := repository.NewAIProposalRepository(db)
	machineRepo := repository.NewMachineRepository(db)
	maintenanceRepo := repository.NewMaintenanceRepository(db)
	settingsRepo := repository.NewSystemSettingsRepository(db)
	processRepo := repository.NewProcessRepository(db)
	formulaRepo := repository.NewFormulaRepository(db)
	productRepo := repository.NewProductRepository(db)
	capRepo := repository.NewMachineCapabilityRepository(db)
	downtimeRepo := repository.NewMachineDowntimeRepository(db)
	bomRepo := repository.NewProductBOMRepository(db)
	invRepo := repository.NewInventoryRepository(db)
	logRepo := repository.NewProductionLogRepository(db)
	setupRepo := repository.NewSetupRepository(db)
	trainingRepo := repository.NewMLTrainingEventRepository(db)
	resourceRepo := repository.NewResourceRepository(db)
	wipRepo := repository.NewWIPRepository(db)
	psmRepo := repository.NewProcessStepMaterialRepository(db)
	schedulingSvc := NewSchedulingService(productRepo, bomRepo, formulaRepo, processRepo, jobRepo, stepRepo, slotRepo, machineRepo, capRepo, downtimeRepo, maintenanceRepo, invRepo, logRepo, proposalRepo, setupRepo, trainingRepo, resourceRepo, wipRepo, psmRepo, settingsRepo)
	jobSlotSvc := NewJobSlotService(slotRepo, stepRepo, processRepo, jobRepo, schedulingSvc)
	eventRepo := repository.NewSchedulingEventRepository(db)
	ai := NewAIPredictiveService(db, jobRepo, stepRepo, slotRepo, proposalRepo, machineRepo, maintenanceRepo, settingsRepo, schedulingSvc, jobSlotSvc, eventRepo)

	ledger := newTentativeInventoryLedger()
	produceAt := time.Date(2026, 4, 4, 10, 0, 0, 0, time.UTC)
	ledger.append(InventoryAction{
		ActionType:  inventoryActionProduceProduct,
		ResourceID:  "P-007",
		JobID:       "JOB-A",
		JobStepID:   "STEP-A",
		Quantity:    10,
		EffectiveAt: produceAt,
	})

	before, err := ai.productAvailabilityForPlanning("P-007", 5, produceAt.Add(-30*time.Minute), ledger, "")
	if err != nil {
		t.Fatalf("availability before output: %v", err)
	}
	if before.AvailableNow != 0 {
		t.Fatalf("expected no availability before earlier output, got %.2f", before.AvailableNow)
	}

	after, err := ai.productAvailabilityForPlanning("P-007", 5, produceAt, ledger, "")
	if err != nil {
		t.Fatalf("availability at output: %v", err)
	}
	if after.AvailableNow < 5 {
		t.Fatalf("expected earlier ledger output to satisfy demand, got %.2f", after.AvailableNow)
	}
}

func TestStripInventoryActionsForResponse_PreservesCanonicalCount(t *testing.T) {
	proposal := &SchedulingProposal{
		JobID:                "JOB-1",
		InventoryActionCount: 2,
		InventoryActions: []InventoryAction{
			{Sequence: 1, ActionType: inventoryActionReserveMaterial, ResourceID: "MAT-001"},
			{Sequence: 2, ActionType: inventoryActionProduceProduct, ResourceID: "P-007"},
		},
		DependentJobs: []DependentJobPlan{
			{PlanKey: "JOB-1|P-007|01|01", ProductID: "P-007", PlanningStatus: planningStatusPlanned},
		},
	}

	stripped := stripInventoryActionsForResponse(proposal, false)
	if len(stripped.InventoryActions) != 0 {
		t.Fatalf("expected response proposal to omit inventory actions")
	}
	if stripped.InventoryActionCount != 2 {
		t.Fatalf("expected action count to remain visible, got %d", stripped.InventoryActionCount)
	}
	if len(proposal.InventoryActions) != 2 {
		t.Fatal("expected canonical proposal to keep inventory actions")
	}
}

func TestInventorySnapshotIncludesProductReservations(t *testing.T) {
	db := testutil.NewTestDB(t)
	invRepo := repository.NewInventoryRepository(db)
	now := time.Date(2026, 4, 3, 8, 0, 0, 0, time.UTC)
	if err := invRepo.CreateProductReservation(&domain.ProductInventoryReservation{
		ReservationID: "PRES-1",
		ProductID:     "P-007",
		JobID:         "JOB-1",
		JobStepID:     "JS-1",
		ReservedQty:   4,
		NeededAt:      now,
		Status:        domain.InventoryReservationStatusPending,
		CreatedAt:     now,
		UpdatedAt:     now,
	}); err != nil {
		t.Fatalf("create product reservation: %v", err)
	}

	jobRepo := repository.NewJobRepository(db)
	stepRepo := repository.NewJobStepRepository(db)
	slotRepo := repository.NewJobSlotRepository(db)
	proposalRepo := repository.NewAIProposalRepository(db)
	machineRepo := repository.NewMachineRepository(db)
	maintenanceRepo := repository.NewMaintenanceRepository(db)
	settingsRepo := repository.NewSystemSettingsRepository(db)
	processRepo := repository.NewProcessRepository(db)
	formulaRepo := repository.NewFormulaRepository(db)
	productRepo := repository.NewProductRepository(db)
	capRepo := repository.NewMachineCapabilityRepository(db)
	downtimeRepo := repository.NewMachineDowntimeRepository(db)
	bomRepo := repository.NewProductBOMRepository(db)
	logRepo := repository.NewProductionLogRepository(db)
	setupRepo := repository.NewSetupRepository(db)
	trainingRepo := repository.NewMLTrainingEventRepository(db)
	resourceRepo := repository.NewResourceRepository(db)
	wipRepo := repository.NewWIPRepository(db)
	psmRepo := repository.NewProcessStepMaterialRepository(db)
	schedulingSvc := NewSchedulingService(productRepo, bomRepo, formulaRepo, processRepo, jobRepo, stepRepo, slotRepo, machineRepo, capRepo, downtimeRepo, maintenanceRepo, invRepo, logRepo, proposalRepo, setupRepo, trainingRepo, resourceRepo, wipRepo, psmRepo, settingsRepo)
	jobSlotSvc := NewJobSlotService(slotRepo, stepRepo, processRepo, jobRepo, schedulingSvc)
	eventRepo := repository.NewSchedulingEventRepository(db)
	ai := NewAIPredictiveService(db, jobRepo, stepRepo, slotRepo, proposalRepo, machineRepo, maintenanceRepo, settingsRepo, schedulingSvc, jobSlotSvc, eventRepo)

	snapshot := ai.buildInventorySnapshot()
	if len(snapshot.ProductReservations) != 1 {
		t.Fatalf("expected 1 product reservation in snapshot, got %d", len(snapshot.ProductReservations))
	}
	if snapshot.ProductReservations[0].ResourceID != "P-007" {
		t.Fatalf("expected reserved product P-007, got %s", snapshot.ProductReservations[0].ResourceID)
	}
}

func TestNormalizeFeasibleDependentJobPlans_ClearsProvisionalLateStatus(t *testing.T) {
	proposal := &SchedulingProposal{
		Feasible: true,
		DependentJobs: []DependentJobPlan{
			{
				PlanKey:         "JOB-1|P-007|01|01",
				ProductID:       "P-007",
				PlanningStatus:  planningStatusUnschedulable,
				ReasonCode:      reasonCodeChildJobLate,
				Reason:          "Child job cannot finish before the parent consuming step.",
				ProposedSlots:   []ProposedSlot{{StepID: "STP-P007-1"}},
				DependencyDepth: 1,
			},
		},
	}

	normalizeFeasibleDependentJobPlans(proposal)

	if proposal.DependentJobs[0].PlanningStatus != planningStatusPlanned {
		t.Fatalf("expected feasible proposal to normalize provisional child lateness, got %s", proposal.DependentJobs[0].PlanningStatus)
	}
	if proposal.DependentJobs[0].ReasonCode != "" {
		t.Fatalf("expected reason code to be cleared, got %s", proposal.DependentJobs[0].ReasonCode)
	}
}

func TestProductAvailabilityForPlanning_IgnoresOtherRootLedgerOutput(t *testing.T) {
	db := testutil.NewTestDB(t)
	jobRepo := repository.NewJobRepository(db)
	stepRepo := repository.NewJobStepRepository(db)
	slotRepo := repository.NewJobSlotRepository(db)
	proposalRepo := repository.NewAIProposalRepository(db)
	machineRepo := repository.NewMachineRepository(db)
	maintenanceRepo := repository.NewMaintenanceRepository(db)
	settingsRepo := repository.NewSystemSettingsRepository(db)
	processRepo := repository.NewProcessRepository(db)
	formulaRepo := repository.NewFormulaRepository(db)
	productRepo := repository.NewProductRepository(db)
	capRepo := repository.NewMachineCapabilityRepository(db)
	downtimeRepo := repository.NewMachineDowntimeRepository(db)
	bomRepo := repository.NewProductBOMRepository(db)
	invRepo := repository.NewInventoryRepository(db)
	logRepo := repository.NewProductionLogRepository(db)
	setupRepo := repository.NewSetupRepository(db)
	trainingRepo := repository.NewMLTrainingEventRepository(db)
	resourceRepo := repository.NewResourceRepository(db)
	wipRepo := repository.NewWIPRepository(db)
	psmRepo := repository.NewProcessStepMaterialRepository(db)
	schedulingSvc := NewSchedulingService(productRepo, bomRepo, formulaRepo, processRepo, jobRepo, stepRepo, slotRepo, machineRepo, capRepo, downtimeRepo, maintenanceRepo, invRepo, logRepo, proposalRepo, setupRepo, trainingRepo, resourceRepo, wipRepo, psmRepo, settingsRepo)
	jobSlotSvc := NewJobSlotService(slotRepo, stepRepo, processRepo, jobRepo, schedulingSvc)
	eventRepo := repository.NewSchedulingEventRepository(db)
	ai := NewAIPredictiveService(db, jobRepo, stepRepo, slotRepo, proposalRepo, machineRepo, maintenanceRepo, settingsRepo, schedulingSvc, jobSlotSvc, eventRepo)

	ledger := newTentativeInventoryLedger()
	produceAt := time.Date(2026, 4, 4, 10, 0, 0, 0, time.UTC)
	ledger.append(InventoryAction{
		ActionType:  inventoryActionProduceProduct,
		ResourceID:  "P-003",
		JobID:       "JOB-OTHER",
		JobStepID:   "STEP-OTHER",
		Quantity:    10,
		EffectiveAt: produceAt,
	})

	visible, err := ai.productAvailabilityForPlanning("P-003", 5, produceAt, ledger, "")
	if err != nil {
		t.Fatalf("availability with unrestricted root: %v", err)
	}
	if visible.AvailableNow < 5 {
		t.Fatalf("expected unrestricted planning to see ledger output, got %.2f", visible.AvailableNow)
	}

	hidden, err := ai.productAvailabilityForPlanning("P-003", 5, produceAt, ledger, "JOB-SEED-016")
	if err != nil {
		t.Fatalf("availability with root filter: %v", err)
	}
	if hidden.AvailableNow != 0 {
		t.Fatalf("expected other-root output to be hidden, got %.2f", hidden.AvailableNow)
	}
}

func TestProductAvailabilityForPlanning_SeesOtherRootReservations(t *testing.T) {
	db := testutil.NewTestDB(t)
	jobRepo := repository.NewJobRepository(db)
	stepRepo := repository.NewJobStepRepository(db)
	slotRepo := repository.NewJobSlotRepository(db)
	proposalRepo := repository.NewAIProposalRepository(db)
	machineRepo := repository.NewMachineRepository(db)
	maintenanceRepo := repository.NewMaintenanceRepository(db)
	settingsRepo := repository.NewSystemSettingsRepository(db)
	processRepo := repository.NewProcessRepository(db)
	formulaRepo := repository.NewFormulaRepository(db)
	productRepo := repository.NewProductRepository(db)
	capRepo := repository.NewMachineCapabilityRepository(db)
	downtimeRepo := repository.NewMachineDowntimeRepository(db)
	bomRepo := repository.NewProductBOMRepository(db)
	invRepo := repository.NewInventoryRepository(db)
	logRepo := repository.NewProductionLogRepository(db)
	setupRepo := repository.NewSetupRepository(db)
	trainingRepo := repository.NewMLTrainingEventRepository(db)
	resourceRepo := repository.NewResourceRepository(db)
	wipRepo := repository.NewWIPRepository(db)
	psmRepo := repository.NewProcessStepMaterialRepository(db)
	schedulingSvc := NewSchedulingService(productRepo, bomRepo, formulaRepo, processRepo, jobRepo, stepRepo, slotRepo, machineRepo, capRepo, downtimeRepo, maintenanceRepo, invRepo, logRepo, proposalRepo, setupRepo, trainingRepo, resourceRepo, wipRepo, psmRepo, settingsRepo)
	jobSlotSvc := NewJobSlotService(slotRepo, stepRepo, processRepo, jobRepo, schedulingSvc)
	eventRepo := repository.NewSchedulingEventRepository(db)
	ai := NewAIPredictiveService(db, jobRepo, stepRepo, slotRepo, proposalRepo, machineRepo, maintenanceRepo, settingsRepo, schedulingSvc, jobSlotSvc, eventRepo)

	now := time.Date(2026, 4, 4, 10, 0, 0, 0, time.UTC)
	if err := invRepo.CreateProductInventory(&domain.ProductInventory{
		InventoryID:      "PINV-TEST-001",
		ProductID:        "P-003",
		QuantityOnHand:   100,
		QuantityReserved: 0,
		Status:           domain.ProductInventoryStatusAvailable,
		StorageLocation:  "FG-TEST",
		AvailableFrom:    now,
		LastUpdated:      now,
	}); err != nil {
		t.Fatalf("create product inventory: %v", err)
	}

	ledger := newTentativeInventoryLedger()
	ledger.append(InventoryAction{
		ActionType:  inventoryActionReserveProduct,
		ResourceID:  "P-003",
		JobID:       "JOB-OTHER",
		JobStepID:   "STEP-OTHER",
		Quantity:    80,
		EffectiveAt: now,
	})

	// Empty allowedRootJobID: ledger entries from any job count (shared virtual pool).
	// A non-empty root hides other roots' actions (see ledgerProductActionVisibleToRoot).
	availability, err := ai.productAvailabilityForPlanning("P-003", 30, now, ledger, "")
	if err != nil {
		t.Fatalf("availability with ledger reservation: %v", err)
	}
	if availability.AvailableNow != 20 {
		t.Fatalf("expected ledger reservation to reduce shared stock to 20, got %.2f", availability.AvailableNow)
	}
}

func TestVirtualPreviewWindowExtendsBeyondLegacy72Hours(t *testing.T) {
	cursor := time.Date(2026, 4, 7, 8, 0, 0, 0, time.UTC)
	deadline := cursor.Add(10 * 24 * time.Hour)

	window := virtualPreviewWindow(cursor, deadline)
	if window <= 72*time.Hour {
		t.Fatalf("expected virtual preview window to exceed 72h, got %s", window)
	}
}

func TestVirtualChildDeadlineUsesParentDeadlineWhenLater(t *testing.T) {
	parentDeadline := time.Date(2026, 4, 21, 17, 0, 0, 0, time.UTC)
	needAt := time.Date(2026, 4, 10, 10, 0, 0, 0, time.UTC)

	virtualDeadline := alignSuccessorStart(needAt.UTC())
	if parentDeadline.After(virtualDeadline) {
		virtualDeadline = alignSuccessorStart(parentDeadline.UTC())
	}

	if !virtualDeadline.Equal(alignSuccessorStart(parentDeadline.UTC())) {
		t.Fatalf("expected child planning deadline to use parent deadline, got %s", virtualDeadline)
	}
}

func TestBuildChildPlanningAttempts_RelaxesBeyondNeedAt(t *testing.T) {
	parentDeadline := time.Date(2026, 4, 21, 17, 0, 0, 0, time.UTC)
	needAt := time.Date(2026, 4, 10, 10, 0, 0, 0, time.UTC)

	attempts := buildChildPlanningAttempts(parentDeadline, nil, needAt)
	if len(attempts) < 2 {
		t.Fatalf("expected multiple child planning attempts, got %d", len(attempts))
	}
	if attempts[0].TargetCompletion == nil || !attempts[0].TargetCompletion.Equal(alignSuccessorStart(needAt.UTC())) {
		t.Fatalf("expected first attempt to target the consuming-step need time")
	}
	if !attempts[1].PlanningDeadline.After(attempts[0].PlanningDeadline) {
		t.Fatalf("expected relaxed attempt to extend planning deadline")
	}
	if attempts[1].TargetCompletion != nil {
		t.Fatalf("expected relaxed attempt to clear target completion bias")
	}
}

func TestBuildChildPlanningAttempts_UsesParentTargetCompletionWhenLater(t *testing.T) {
	parentDeadline := time.Date(2026, 4, 21, 17, 0, 0, 0, time.UTC)
	targetCompletion := time.Date(2026, 5, 3, 11, 0, 0, 0, time.UTC)
	needAt := time.Date(2026, 4, 10, 10, 0, 0, 0, time.UTC)

	attempts := buildChildPlanningAttempts(parentDeadline, &targetCompletion, needAt)
	if len(attempts) == 0 {
		t.Fatal("expected child planning attempts")
	}
	if !attempts[0].PlanningDeadline.Equal(alignSuccessorStart(targetCompletion.UTC())) {
		t.Fatalf("expected first attempt deadline to inherit parent target completion, got %s", attempts[0].PlanningDeadline)
	}
}

func TestSubproductBatchStateClone_IsolatedLedgerMutation(t *testing.T) {
	state := newSubproductBatchState(nil)
	state.totalGeneratedNodes = 2
	state.ledger.productBaseline["P-003"] = 12
	state.ledger.materialBaseline["MAT-001"] = 7
	state.ledger.append(InventoryAction{
		ActionType:  inventoryActionReserveProduct,
		ResourceID:  "P-003",
		JobID:       "JOB-1",
		JobStepID:   "STEP-1",
		Quantity:    4,
		EffectiveAt: time.Date(2026, 4, 7, 8, 0, 0, 0, time.UTC),
	})

	cloned := state.clone()
	cloned.totalGeneratedNodes = 9
	cloned.ledger.productBaseline["P-003"] = 1
	cloned.ledger.materialBaseline["MAT-001"] = 2
	cloned.ledger.activeEntries[0].Action.Quantity = 99
	cloned.ledger.append(InventoryAction{
		ActionType:  inventoryActionProduceProduct,
		ResourceID:  "P-003",
		JobID:       "JOB-1",
		JobStepID:   "STEP-2",
		Quantity:    6,
		EffectiveAt: time.Date(2026, 4, 7, 10, 0, 0, 0, time.UTC),
	})

	if state.totalGeneratedNodes != 2 {
		t.Fatalf("expected original node count to stay isolated, got %d", state.totalGeneratedNodes)
	}
	if state.ledger.productBaseline["P-003"] != 12 {
		t.Fatalf("expected original product baseline to stay 12, got %.2f", state.ledger.productBaseline["P-003"])
	}
	if state.ledger.materialBaseline["MAT-001"] != 7 {
		t.Fatalf("expected original material baseline to stay 7, got %.2f", state.ledger.materialBaseline["MAT-001"])
	}
	if got := state.ledger.activeEntries[0].Action.Quantity; got != 4 {
		t.Fatalf("expected original active entry quantity to stay 4, got %.2f", got)
	}
	if len(state.ledger.activeEntries) != 1 {
		t.Fatalf("expected original active entries to remain 1, got %d", len(state.ledger.activeEntries))
	}
}

func TestParentShortagePreservesExistingDependentReason(t *testing.T) {
	proposal := &SchedulingProposal{
		DependentJobs: []DependentJobPlan{
			{
				PlanKey:         "JOB-1|P-003|03|01",
				ProductID:       "P-003",
				PlanningStatus:  planningStatusBlocked,
				ReasonCode:      reasonCodeSubproductShortage,
				Reason:          "Nested shortage still exists.",
				DependencyDepth: 1,
			},
		},
	}

	planKey := "JOB-1|P-003|03|01"
	if plan := dependentJobPlanByKey(proposal.DependentJobs, planKey); plan != nil && plan.PlanningStatus != planningStatusPlanned && plan.ReasonCode != "" {
		proposal.Feasible = false
		proposal.BlockedReasons = appendUniqueString(proposal.BlockedReasons, "reason_code="+plan.ReasonCode)
	} else {
		setDependentJobPlanStatus(proposal.DependentJobs, planKey, planningStatusUnschedulable, reasonCodeChildJobLate, "Child job cannot finish before the parent consuming step.")
		proposal.Feasible = false
		proposal.BlockedReasons = appendUniqueString(proposal.BlockedReasons, "reason_code="+reasonCodeChildJobLate)
	}

	if got := proposal.DependentJobs[0].ReasonCode; got != reasonCodeSubproductShortage {
		t.Fatalf("expected nested reason code to be preserved, got %s", got)
	}
	if len(proposal.BlockedReasons) != 1 || proposal.BlockedReasons[0] != "reason_code="+reasonCodeSubproductShortage {
		t.Fatalf("expected blocked reasons to preserve nested shortage, got %#v", proposal.BlockedReasons)
	}
}

func TestSummarizeDependentProposalFailure_UsesNestedReason(t *testing.T) {
	proposal := &SchedulingProposal{
		Feasible: false,
		BlockedReasons: []string{
			"reason_code=" + reasonCodeChildJobLate,
		},
		DependentJobs: []DependentJobPlan{
			{
				PlanKey:        "JOB-1|P-003|03|01|nested",
				ProductID:      "P-003",
				PlanningStatus: planningStatusBlocked,
				ReasonCode:     reasonCodeSubproductShortage,
				Reason:         "Insufficient chrome-plating supply for the child job.",
			},
		},
	}

	status, code, reason := summarizeDependentProposalFailure(proposal)
	if status != planningStatusBlocked {
		t.Fatalf("expected blocked status, got %s", status)
	}
	if code != reasonCodeSubproductShortage {
		t.Fatalf("expected nested shortage code, got %s", code)
	}
	if reason != "Insufficient chrome-plating supply for the child job." {
		t.Fatalf("expected nested reason to win, got %q", reason)
	}
}

func TestLatestShortDemandReadyAt_UsesLatestWhenAllMaterialsHaveReadyTime(t *testing.T) {
	early := time.Date(2026, 4, 12, 8, 0, 0, 0, time.UTC)
	late := time.Date(2026, 4, 12, 10, 30, 0, 0, time.UTC)

	readyAt, ok := latestShortDemandReadyAt([]*DemandMaterial{
		{MaterialID: "MAT-001", ReadyAt: &early},
		{MaterialID: "MAT-002", ReadyAt: &late},
	})
	if !ok || readyAt == nil {
		t.Fatal("expected all-ready shortage set to be reflowable")
	}
	if !readyAt.Equal(alignSuccessorStart(late.UTC())) {
		t.Fatalf("expected latest ready time %s, got %s", alignSuccessorStart(late.UTC()), *readyAt)
	}
}

func TestLatestShortDemandReadyAt_RequiresAllShortMaterialsToHaveReadyTime(t *testing.T) {
	ready := time.Date(2026, 4, 12, 8, 0, 0, 0, time.UTC)

	readyAt, ok := latestShortDemandReadyAt([]*DemandMaterial{
		{MaterialID: "MAT-001", ReadyAt: &ready},
		{MaterialID: "MAT-002"},
	})
	if ok || readyAt != nil {
		t.Fatalf("expected shortage set with unknown material readiness to stay blocked, got ok=%v readyAt=%v", ok, readyAt)
	}
}
