package service

import (
	"emas/internal/domain"
	"emas/internal/repository"
	"emas/internal/testutil"
	"testing"
	"time"
)

func TestDependentJobStepApplyOrderUsesStepSequence(t *testing.T) {
	createdSteps := []domain.JobSteps{
		{JobStepID: "JS-Z", StepID: "STP-P007-2", StepSequence: 2},
		{JobStepID: "JS-A", StepID: "STP-P007-1", StepSequence: 1},
		{JobStepID: "JS-Y", StepID: "STP-P007-3", StepSequence: 3},
	}

	order := []string{"JS-Z", "JS-Y", "JS-A"}
	order = dependentJobStepApplyOrder(order, createdSteps)

	want := []string{"JS-A", "JS-Z", "JS-Y"}
	for i := range want {
		if order[i] != want[i] {
			t.Fatalf("expected step-sequence apply order %v, got %v", want, order)
		}
	}
}

func TestAllocateProposalReservations_AllowsChildBackedProductReservation(t *testing.T) {
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

	err := ai.allocateProposalReservations(db, []InventoryAction{
		{
			Sequence:    1,
			ActionType:  inventoryActionReserveProduct,
			ResourceID:  "P-003",
			JobID:       "JOB-ROOT",
			JobStepID:   "JS-ROOT-3",
			Quantity:    20,
			EffectiveAt: time.Date(2026, 4, 7, 10, 0, 0, 0, time.UTC),
			PlanKey:     "JOB-ROOT|P-003|03|01",
		},
	}, map[string]struct{}{
		"JOB-ROOT|P-003|03|01": {},
	})
	if err != nil {
		t.Fatalf("expected child-backed reservation to be accepted, got %v", err)
	}

	rows, err := invRepo.ListProductReservations("P-003", domain.InventoryReservationStatusPending)
	if err != nil {
		t.Fatalf("list product reservations: %v", err)
	}
	if len(rows) != 1 {
		t.Fatalf("expected 1 pending product reservation, got %d", len(rows))
	}
}
