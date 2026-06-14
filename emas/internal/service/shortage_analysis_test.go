package service

import (
	"emas/internal/domain"
	"emas/internal/repository"
	"emas/internal/testutil"
	"testing"
	"time"
)

func newTestAIPredictiveService(t *testing.T) (*AIPredictiveService, *repository.InventoryRepository) {
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
	return ai, invRepo
}

func TestAnalyzeProposalMaterialShortages_UsesNetOpeningStateAtNow(t *testing.T) {
	ai, invRepo := newTestAIPredictiveService(t)
	now := alignSuccessorStart(time.Now().UTC())

	if err := invRepo.CreateMaterial(&domain.InventoryMaterials{
		MaterialID:   "MAT-001",
		MaterialName: "Test Material",
		Unit:         "kg",
		CurrentStock: 0,
		Status:       domain.InventoryStatusInStock,
		LastUpdated:  now.Add(-2 * time.Hour),
	}); err != nil {
		t.Fatalf("create material: %v", err)
	}
	if err := invRepo.CreateExpectedArrival(&domain.InventoryExpectedArrival{
		ArrivalID:        "ARR-1",
		MaterialID:       "MAT-001",
		Quantity:         10,
		ExpectedArriveAt: now.Add(-1 * time.Hour),
		Status:           domain.ExpectedArrivalStatusPending,
		CreatedAt:        now.Add(-2 * time.Hour),
	}); err != nil {
		t.Fatalf("create expected arrival: %v", err)
	}
	if err := invRepo.CreateReservation(&domain.InventoryReservation{
		ReservationID: "IRES-1",
		MaterialID:    "MAT-001",
		JobID:         "JOB-OLD",
		JobStepID:     "JS-OLD-1",
		ReservedQty:   5,
		NeededAt:      now.Add(-30 * time.Minute),
		Status:        domain.InventoryReservationStatusPending,
		CreatedAt:     now.Add(-2 * time.Hour),
		UpdatedAt:     now.Add(-2 * time.Hour),
	}); err != nil {
		t.Fatalf("create reservation: %v", err)
	}

	availability, err := ai.materialAvailabilityForPlanning(invRepo, "MAT-001", 5, now.Add(time.Hour), newTentativeInventoryLedger())
	if err != nil {
		t.Fatalf("material availability: %v", err)
	}
	if !availability.EnoughNow || availability.ShortageQty > 0 {
		t.Fatalf("expected replenishment-adjusted stock to satisfy demand, got enough=%v shortage=%.2f available=%.2f", availability.EnoughNow, availability.ShortageQty, availability.AvailableQty)
	}

	proposal := &SchedulingProposal{
		JobID: "JOB-NEW",
		InventoryActions: []InventoryAction{
			{
				ActionType:  inventoryActionReserveMaterial,
				ResourceID:  "MAT-001",
				JobID:       "JOB-NEW",
				JobStepID:   "JS-NEW-1",
				Quantity:    5,
				EffectiveAt: now.Add(time.Hour),
			},
		},
	}

	shortages, resolutions, score, err := ai.analyzeProposalMaterialShortages(proposal, nil)
	if err != nil {
		t.Fatalf("analyze shortages: %v", err)
	}
	if len(shortages) != 0 {
		t.Fatalf("expected no shortages after pre-now replenishment is netted into opening state, got %+v", shortages)
	}
	if len(resolutions) != 0 {
		t.Fatalf("expected no shortage resolutions, got %+v", resolutions)
	}
	if score != 0 {
		t.Fatalf("expected zero shortage score, got %.2f", score)
	}
}

func TestSubproductRawMaterialOptionsNetExpectedArrivalsBeforeNeedTime(t *testing.T) {
	ai, invRepo := newTestAIPredictiveService(t)
	now := alignSuccessorStart(time.Now().UTC())
	needAt := now.Add(24 * time.Hour)
	matID := "MAT-CHILD-NET"
	childID := "P-CHILD-NET"

	if err := ai.scheduling.productRepo.Create(&domain.Product{
		ProductID:     childID,
		ProductName:   "Child Product Netting",
		UnitOfMeasure: "pcs",
		Status:        domain.ProductStatusActive,
		CreatedAt:     now,
	}); err != nil {
		t.Fatalf("create child product: %v", err)
	}
	if err := invRepo.CreateMaterial(&domain.InventoryMaterials{
		MaterialID:   matID,
		MaterialName: "Child Net Material",
		Unit:         "kg",
		CurrentStock: 5,
		ReorderLevel: 0,
		Status:       domain.InventoryStatusInStock,
		LastUpdated:  now.Add(-time.Hour),
	}); err != nil {
		t.Fatalf("create child material: %v", err)
	}
	if err := ai.scheduling.bomRepo.Create(&domain.ProductBOM{
		BOMID:            "BOM-CHILD-NET-1",
		ProductID:        childID,
		ComponentType:    domain.ComponentTypeMaterial,
		MaterialID:       &matID,
		QuantityRequired: 2,
		Unit:             "kg",
	}); err != nil {
		t.Fatalf("create child BOM: %v", err)
	}

	options, err := ai.buildMaterialReplenishOptionsForSubproductManufacture(childID, 100, needAt, []string{"JOB-PARENT"}, nil)
	if err != nil {
		t.Fatalf("build options without arrivals: %v", err)
	}
	if len(options) != 1 {
		t.Fatalf("options without arrivals count=%d, want 1: %#v", len(options), options)
	}
	if got := options[0].Replenishment.SuggestedQty; got != 195 {
		t.Fatalf("initial suggested qty=%.2f, want net deficit 195 after current stock", got)
	}

	if err := invRepo.CreateExpectedArrival(&domain.InventoryExpectedArrival{
		ArrivalID:        "ARR-CHILD-NET-1",
		MaterialID:       matID,
		Quantity:         195,
		ExpectedArriveAt: needAt.Add(-30 * time.Minute),
		Status:           domain.ExpectedArrivalStatusPending,
		CreatedAt:        now,
	}); err != nil {
		t.Fatalf("create expected arrival: %v", err)
	}

	options, err = ai.buildMaterialReplenishOptionsForSubproductManufacture(childID, 100, needAt, []string{"JOB-PARENT"}, nil)
	if err != nil {
		t.Fatalf("build options with covering arrival: %v", err)
	}
	if len(options) != 0 {
		t.Fatalf("expected covering expected arrival to remove child raw-material options, got %#v", options)
	}
}

func TestBatchAggregatesAffectedJobsOnlyShortageCausers(t *testing.T) {
	ai, invRepo := newTestAIPredictiveService(t)
	now := alignSuccessorStart(time.Now().UTC())

	if err := invRepo.CreateMaterial(&domain.InventoryMaterials{
		MaterialID:   "MAT-AGG",
		MaterialName: "Aggregate Material",
		Unit:         "kg",
		CurrentStock: 10,
		ReorderLevel: 0,
		Status:       domain.InventoryStatusInStock,
		LastUpdated:  now.Add(-time.Hour),
	}); err != nil {
		t.Fatalf("create material: %v", err)
	}

	materialProposals := []*SchedulingProposal{
		{
			JobID: "JOB-A",
			InventoryActions: []InventoryAction{{
				ActionType:  inventoryActionReserveMaterial,
				ResourceID:  "MAT-AGG",
				JobID:       "JOB-A",
				JobStepID:   "JS-A",
				Quantity:    5,
				EffectiveAt: now.Add(time.Hour),
			}},
		},
		{
			JobID: "JOB-B",
			InventoryActions: []InventoryAction{{
				ActionType:  inventoryActionReserveMaterial,
				ResourceID:  "MAT-AGG",
				JobID:       "JOB-B|P-CHILD|01|01",
				JobStepID:   "JS-B",
				Quantity:    8,
				EffectiveAt: now.Add(2 * time.Hour),
			}},
		},
	}

	matAgg := ai.buildBatchMaterialReplenishmentAggregate(materialProposals, nil)
	if len(matAgg) != 1 {
		t.Fatalf("material aggregate count = %d, want 1: %#v", len(matAgg), matAgg)
	}
	if got := matAgg[0].AffectedJobIDs; len(got) != 1 || got[0] != "JOB-B" {
		t.Fatalf("material affected jobs = %#v, want only JOB-B", got)
	}
	if matAgg[0].RecommendedQty != 3 {
		t.Fatalf("material recommended qty = %.2f, want 3", matAgg[0].RecommendedQty)
	}

	if err := invRepo.CreateMaterial(&domain.InventoryMaterials{
		MaterialID:   "MAT-DEP",
		MaterialName: "Dependency Material",
		Unit:         "kg",
		CurrentStock: 0,
		ReorderLevel: 0,
		Status:       domain.InventoryStatusInStock,
		LastUpdated:  now.Add(-time.Hour),
	}); err != nil {
		t.Fatalf("create dependency material: %v", err)
	}

	dependencyProposals := []*SchedulingProposal{
		{
			JobID: "JOB-C",
			ShortageResolutions: []ShortageResolutionOption{{
				MaterialID:          "MAT-DEP",
				OptionType:          "replenish",
				Replenishment:       &ReplenishmentSuggestion{SuggestedQty: 4, SuggestedArriveAt: now.Add(3 * time.Hour), EarliestPossibleArrival: now.Add(2 * time.Hour)},
				AffectedJobIDs:      []string{"JOB-C"},
				DependencyProductID: "P-CHILD",
				IsActionable:        true,
			}},
		},
		{
			JobID: "JOB-D",
			ShortageResolutions: []ShortageResolutionOption{{
				MaterialID:          "MAT-DEP",
				OptionType:          "replenish",
				Replenishment:       &ReplenishmentSuggestion{SuggestedQty: 6, SuggestedArriveAt: now.Add(4 * time.Hour), EarliestPossibleArrival: now.Add(2 * time.Hour)},
				AffectedJobIDs:      []string{"JOB-D"},
				DependencyProductID: "P-CHILD",
				IsActionable:        true,
			}},
		},
	}

	depAgg := ai.buildBatchMaterialReplenishmentAggregate(dependencyProposals, nil)
	if len(depAgg) != 1 {
		t.Fatalf("dependency material aggregate count = %d, want 1: %#v", len(depAgg), depAgg)
	}
	if got := depAgg[0].AffectedJobIDs; len(got) != 2 || got[0] != "JOB-C" || got[1] != "JOB-D" {
		t.Fatalf("dependency affected jobs = %#v, want JOB-C and JOB-D", got)
	}
	if depAgg[0].RecommendedQty != 10 {
		t.Fatalf("dependency material recommended qty = %.2f, want 10", depAgg[0].RecommendedQty)
	}

	if err := invRepo.CreateMaterial(&domain.InventoryMaterials{
		MaterialID:   "MAT-RES",
		MaterialName: "Resolution Only Material",
		Unit:         "kg",
		CurrentStock: 0,
		ReorderLevel: 0,
		Status:       domain.InventoryStatusInStock,
		LastUpdated:  now.Add(-time.Hour),
	}); err != nil {
		t.Fatalf("create resolution-only material: %v", err)
	}
	resolutionOnly := []*SchedulingProposal{{
		JobID: "JOB-E",
		ShortageResolutions: []ShortageResolutionOption{{
			MaterialID:     "MAT-RES",
			OptionType:     "replenish",
			Replenishment:  &ReplenishmentSuggestion{SuggestedQty: 11, SuggestedArriveAt: now.Add(5 * time.Hour), EarliestPossibleArrival: now.Add(2 * time.Hour)},
			AffectedJobIDs: []string{"JOB-E"},
			IsActionable:   true,
		}},
	}}
	resAgg := ai.buildBatchMaterialReplenishmentAggregate(resolutionOnly, nil)
	if len(resAgg) != 1 {
		t.Fatalf("resolution-only material aggregate count = %d, want 1: %#v", len(resAgg), resAgg)
	}
	if resAgg[0].MaterialID != "MAT-RES" || resAgg[0].RecommendedQty != 11 {
		t.Fatalf("resolution-only aggregate = %#v, want MAT-RES qty 11", resAgg[0])
	}

	duplicateAlternatives := []*SchedulingProposal{{
		JobID: "JOB-F",
		ShortageResolutions: []ShortageResolutionOption{
			{
				MaterialID:     "MAT-RES",
				OptionType:     "replenish",
				Replenishment:  &ReplenishmentSuggestion{SuggestedQty: 20, SuggestedArriveAt: now.Add(3 * time.Hour), EarliestPossibleArrival: now.Add(2 * time.Hour)},
				AffectedJobIDs: []string{"JOB-F"},
				IsActionable:   true,
			},
			{
				MaterialID:          "MAT-RES",
				DependencyProductID: "P-007",
				OptionType:          "replenish",
				Replenishment:       &ReplenishmentSuggestion{SuggestedQty: 20, SuggestedArriveAt: now.Add(8 * time.Hour), EarliestPossibleArrival: now.Add(2 * time.Hour)},
				AffectedJobIDs:      []string{"JOB-F"},
				IsActionable:        true,
			},
			{
				MaterialID:    "P-007",
				OptionType:    "schedule_production",
				Replenishment: &ReplenishmentSuggestion{SuggestedQty: 20, SuggestedArriveAt: now.Add(8 * time.Hour)},
				IsActionable:  true,
			},
		},
	}}
	dedupAgg := ai.buildBatchMaterialReplenishmentAggregate(duplicateAlternatives, nil)
	if len(dedupAgg) != 1 {
		t.Fatalf("dedup aggregate count = %d, want 1: %#v", len(dedupAgg), dedupAgg)
	}
	if dedupAgg[0].MaterialID != "MAT-RES" || dedupAgg[0].RecommendedQty != 20 {
		t.Fatalf("dedup aggregate = %#v, want MAT-RES qty 20", dedupAgg[0])
	}
}

func TestBatchMaterialAggregateIncludesLateFutureArrivalWaits(t *testing.T) {
	ai, invRepo := newTestAIPredictiveService(t)
	now := alignSuccessorStart(time.Now().UTC())

	if err := invRepo.CreateMaterial(&domain.InventoryMaterials{
		MaterialID:   "MAT-WAIT",
		MaterialName: "Delayed Arrival Material",
		Unit:         "kg",
		CurrentStock: 0,
		ReorderLevel: 0,
		Status:       domain.InventoryStatusInStock,
		LastUpdated:  now.Add(-time.Hour),
	}); err != nil {
		t.Fatalf("create material: %v", err)
	}

	proposals := []*SchedulingProposal{
		{
			JobID:    "JOB-LATE-WAIT",
			Feasible: true,
			DeadlineStatus: &DeadlineStatus{
				Deadline:      now.Add(4 * time.Hour),
				IsLate:        true,
				TardinessMins: 240,
				LateBy:        "4 hours",
			},
			materialAccelerationNeeds: []materialAccelerationNeed{{
				MaterialID:   "MAT-WAIT",
				JobID:        "JOB-LATE-WAIT",
				JobStepID:    "JS-LATE-WAIT-1",
				NeedAt:       now.Add(2 * time.Hour),
				ReadyAt:      now.Add(72 * time.Hour),
				RequiredQty:  25,
				AvailableQty: 5,
				ShortageQty:  20,
			}},
		},
		{
			JobID:    "JOB-ONTIME-WAIT",
			Feasible: true,
			DeadlineStatus: &DeadlineStatus{
				Deadline: now.Add(7 * 24 * time.Hour),
				IsLate:   false,
			},
			materialAccelerationNeeds: []materialAccelerationNeed{{
				MaterialID:   "MAT-WAIT",
				JobID:        "JOB-ONTIME-WAIT",
				JobStepID:    "JS-ONTIME-WAIT-1",
				NeedAt:       now.Add(3 * time.Hour),
				ReadyAt:      now.Add(24 * time.Hour),
				RequiredQty:  100,
				AvailableQty: 0,
				ShortageQty:  100,
			}},
		},
	}

	agg := ai.buildBatchMaterialReplenishmentAggregate(proposals, nil)
	if len(agg) != 1 {
		t.Fatalf("aggregate count = %d, want 1: %#v", len(agg), agg)
	}
	if agg[0].MaterialID != "MAT-WAIT" || agg[0].RecommendedQty != 20 {
		t.Fatalf("aggregate = %#v, want MAT-WAIT qty 20", agg[0])
	}
	if got := agg[0].AffectedJobIDs; len(got) != 1 || got[0] != "JOB-LATE-WAIT" {
		t.Fatalf("affected jobs = %#v, want only JOB-LATE-WAIT", got)
	}
	if !agg[0].SuggestedArriveAt.Before(now.Add(2 * time.Hour)) {
		t.Fatalf("suggested arrival = %s, want before need time %s", agg[0].SuggestedArriveAt, now.Add(2*time.Hour))
	}
}
