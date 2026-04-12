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
