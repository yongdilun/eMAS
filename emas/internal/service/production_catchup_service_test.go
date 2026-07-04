package service

import (
	"testing"
	"time"

	"emas/internal/domain"
	"emas/internal/repository"
	"emas/internal/testutil"
)

func TestProductionCatchUpDryRunAndCompleteDueSlots(t *testing.T) {
	db := testutil.NewTestDB(t)
	now := time.Date(2026, 7, 10, 12, 0, 0, 0, time.UTC)
	records := []interface{}{
		&domain.Job{JobID: "JOB-CATCH-1", ProductID: "P-CATCH", QuantityTotal: 5, Status: domain.JobStatusScheduled, Deadline: now.Add(24 * time.Hour), CreatedAt: now, UpdatedAt: now},
		&domain.JobSteps{JobStepID: "JSTEP-CATCH-1", JobID: "JOB-CATCH-1", StepID: "STEP-CATCH", StepSequence: 1, QuantityTarget: 5, Status: domain.JobStepStatusScheduled},
		&domain.JobStepScheduleSlots{SlotID: "SLOT-CATCH-DUE", JobStepID: "JSTEP-CATCH-1", MachineID: "M-CATCH", ScheduledStart: now.Add(-2 * time.Hour), ScheduledEnd: now.Add(-time.Hour), QuantityPlanned: 5, Status: domain.SlotStatusPlanned},
		&domain.ProcessStepMaterial{ID: "PSM-CATCH-OUT", StepID: "STEP-CATCH", ProductID: strPtrServiceTest("P-CATCH"), Role: domain.ProcessStepMaterialRoleOutput, QuantityPerUnit: 1, Unit: "pcs"},
		&domain.Job{JobID: "JOB-CATCH-2", ProductID: "P-CATCH", QuantityTotal: 4, Status: domain.JobStatusScheduled, Deadline: now.Add(48 * time.Hour), CreatedAt: now, UpdatedAt: now},
		&domain.JobSteps{JobStepID: "JSTEP-CATCH-2", JobID: "JOB-CATCH-2", StepID: "STEP-CATCH", StepSequence: 1, QuantityTarget: 4, Status: domain.JobStepStatusScheduled},
		&domain.JobStepScheduleSlots{SlotID: "SLOT-CATCH-FUTURE", JobStepID: "JSTEP-CATCH-2", MachineID: "M-CATCH", ScheduledStart: now.Add(time.Hour), ScheduledEnd: now.Add(2 * time.Hour), QuantityPlanned: 4, Status: domain.SlotStatusPlanned},
	}
	for _, record := range records {
		if err := db.Create(record).Error; err != nil {
			t.Fatalf("seed %T: %v", record, err)
		}
	}

	logSvc := NewProductionLogService(
		db,
		repository.NewProductionLogRepository(db),
		repository.NewJobSlotRepository(db),
		repository.NewJobStepRepository(db),
		repository.NewJobRepository(db),
		nil,
		nil,
	)
	catchUp := NewProductionCatchUpService(db, logSvc)

	dryRun, err := catchUp.CatchUpDueSlots(ProductionCatchUpOptions{AsOf: now, JobPrefix: "JOB-CATCH", DryRun: true})
	if err != nil {
		t.Fatalf("dry run catch-up: %v", err)
	}
	if dryRun.Candidates != 1 || dryRun.Completed != 0 || len(dryRun.Rows) != 1 || dryRun.Rows[0].Action != "would_log" {
		t.Fatalf("dry run result = %+v, want one would_log candidate", dryRun)
	}
	var logCount int64
	if err := db.Model(&domain.ProductionLogs{}).Count(&logCount).Error; err != nil {
		t.Fatalf("count logs after dry run: %v", err)
	}
	if logCount != 0 {
		t.Fatalf("logs after dry run = %d, want 0", logCount)
	}

	applied, err := catchUp.CatchUpDueSlots(ProductionCatchUpOptions{AsOf: now, JobPrefix: "JOB-CATCH"})
	if err != nil {
		t.Fatalf("apply catch-up: %v", err)
	}
	if applied.Candidates != 1 || applied.Completed != 1 || applied.Rows[0].Action != "logged" {
		t.Fatalf("apply result = %+v, want one logged candidate", applied)
	}
	var dueSlot domain.JobStepScheduleSlots
	if err := db.First(&dueSlot, "slot_id = ?", "SLOT-CATCH-DUE").Error; err != nil {
		t.Fatalf("load due slot: %v", err)
	}
	if dueSlot.Status != domain.SlotStatusCompleted || dueSlot.ActualEnd == nil {
		t.Fatalf("due slot status/actual_end = %s/%v, want completed with actual_end", dueSlot.Status, dueSlot.ActualEnd)
	}
	var futureSlot domain.JobStepScheduleSlots
	if err := db.First(&futureSlot, "slot_id = ?", "SLOT-CATCH-FUTURE").Error; err != nil {
		t.Fatalf("load future slot: %v", err)
	}
	if futureSlot.Status != domain.SlotStatusPlanned {
		t.Fatalf("future slot status = %s, want planned", futureSlot.Status)
	}

	second, err := catchUp.CatchUpDueSlots(ProductionCatchUpOptions{AsOf: now, JobPrefix: "JOB-CATCH"})
	if err != nil {
		t.Fatalf("second catch-up: %v", err)
	}
	if second.Candidates != 0 || second.Completed != 0 {
		t.Fatalf("second result = %+v, want no remaining candidates", second)
	}
}
