package service

import (
	"testing"
	"time"

	"emas/internal/apperror"
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/internal/testutil"

	"gorm.io/gorm"
)

func newProductionLogExecutionService(db *gorm.DB) *ProductionLogService {
	return NewProductionLogService(
		db,
		repository.NewProductionLogRepository(db),
		repository.NewJobSlotRepository(db),
		repository.NewJobStepRepository(db),
		repository.NewJobRepository(db),
		nil,
		nil,
	)
}

func TestProductionLogRollsBackWhenMaterialStockIsInsufficient(t *testing.T) {
	db := testutil.NewTestDB(t)
	now := time.Date(2026, 7, 10, 8, 0, 0, 0, time.UTC)
	records := []interface{}{
		&domain.InventoryMaterials{MaterialID: "MAT-EXEC-LOW", MaterialName: "Low material", Unit: "kg", CurrentStock: 5, MinStock: 1, Status: domain.InventoryStatusInStock, LastUpdated: now},
		&domain.Job{JobID: "JOB-EXEC-LOW", ProductID: "P-EXEC-LOW", QuantityTotal: 3, Status: domain.JobStatusScheduled, Deadline: now.Add(24 * time.Hour), CreatedAt: now, UpdatedAt: now},
		&domain.JobSteps{JobStepID: "JSTEP-EXEC-LOW", JobID: "JOB-EXEC-LOW", StepID: "STEP-EXEC-LOW", StepSequence: 1, QuantityTarget: 3, Status: domain.JobStepStatusScheduled},
		&domain.JobStepScheduleSlots{SlotID: "SLOT-EXEC-LOW", JobStepID: "JSTEP-EXEC-LOW", MachineID: "M-EXEC-LOW", ScheduledStart: now, ScheduledEnd: now.Add(time.Hour), QuantityPlanned: 3, Status: domain.SlotStatusPlanned},
		&domain.ProcessStepMaterial{ID: "PSM-EXEC-LOW-IN", StepID: "STEP-EXEC-LOW", MaterialID: strPtrServiceTest("MAT-EXEC-LOW"), Role: domain.ProcessStepMaterialRoleInput, QuantityPerUnit: 2, Unit: "kg"},
		&domain.ProcessStepMaterial{ID: "PSM-EXEC-LOW-OUT", StepID: "STEP-EXEC-LOW", ProductID: strPtrServiceTest("P-EXEC-LOW"), Role: domain.ProcessStepMaterialRoleOutput, QuantityPerUnit: 1, Unit: "pcs"},
	}
	for _, record := range records {
		if err := db.Create(record).Error; err != nil {
			t.Fatalf("seed %T: %v", record, err)
		}
	}

	_, err := newProductionLogExecutionService(db).LogProduction(dto.LogProductionRequest{
		SlotID:           "SLOT-EXEC-LOW",
		StartTime:        now,
		EndTime:          now.Add(time.Hour),
		QuantityProduced: 3,
	})
	if !apperror.IsKind(err, apperror.KindConflict) {
		t.Fatalf("LogProduction error = %v, want conflict", err)
	}

	var material domain.InventoryMaterials
	if err := db.First(&material, "material_id = ?", "MAT-EXEC-LOW").Error; err != nil {
		t.Fatalf("reload material: %v", err)
	}
	if material.CurrentStock != 5 {
		t.Fatalf("stock after rejected log = %.2f, want 5", material.CurrentStock)
	}
	var logCount, txCount, productInventoryCount int64
	if err := db.Model(&domain.ProductionLogs{}).Where("slot_id = ?", "SLOT-EXEC-LOW").Count(&logCount).Error; err != nil {
		t.Fatalf("count logs: %v", err)
	}
	if err := db.Model(&domain.InventoryTransactions{}).Where("material_id = ?", "MAT-EXEC-LOW").Count(&txCount).Error; err != nil {
		t.Fatalf("count transactions: %v", err)
	}
	if err := db.Model(&domain.ProductInventory{}).Where("product_id = ?", "P-EXEC-LOW").Count(&productInventoryCount).Error; err != nil {
		t.Fatalf("count product inventory: %v", err)
	}
	if logCount != 0 || txCount != 0 || productInventoryCount != 0 {
		t.Fatalf("rollback counts logs/tx/product = %d/%d/%d, want 0/0/0", logCount, txCount, productInventoryCount)
	}
}

func TestProductionLogMultiStepJobProgressUsesMinimumStepCompletion(t *testing.T) {
	db := testutil.NewTestDB(t)
	now := time.Date(2026, 7, 10, 8, 0, 0, 0, time.UTC)
	records := []interface{}{
		&domain.InventoryMaterials{MaterialID: "MAT-EXEC-MULTI", MaterialName: "Multi material", Unit: "kg", CurrentStock: 100, MinStock: 1, Status: domain.InventoryStatusInStock, LastUpdated: now},
		&domain.Job{JobID: "JOB-EXEC-MULTI", ProductID: "P-EXEC-MULTI", QuantityTotal: 10, Status: domain.JobStatusScheduled, Deadline: now.Add(24 * time.Hour), CreatedAt: now, UpdatedAt: now},
		&domain.JobSteps{JobStepID: "JSTEP-EXEC-MULTI-1", JobID: "JOB-EXEC-MULTI", StepID: "STEP-EXEC-MULTI-1", StepSequence: 1, QuantityTarget: 10, Status: domain.JobStepStatusScheduled},
		&domain.JobSteps{JobStepID: "JSTEP-EXEC-MULTI-2", JobID: "JOB-EXEC-MULTI", StepID: "STEP-EXEC-MULTI-2", StepSequence: 2, QuantityTarget: 10, Status: domain.JobStepStatusScheduled},
		&domain.JobStepScheduleSlots{SlotID: "SLOT-EXEC-MULTI-1", JobStepID: "JSTEP-EXEC-MULTI-1", MachineID: "M-EXEC-MULTI-1", ScheduledStart: now, ScheduledEnd: now.Add(time.Hour), QuantityPlanned: 10, Status: domain.SlotStatusPlanned},
		&domain.JobStepScheduleSlots{SlotID: "SLOT-EXEC-MULTI-2", JobStepID: "JSTEP-EXEC-MULTI-2", MachineID: "M-EXEC-MULTI-2", ScheduledStart: now.Add(2 * time.Hour), ScheduledEnd: now.Add(3 * time.Hour), QuantityPlanned: 10, Status: domain.SlotStatusPlanned},
		&domain.ProcessStepMaterial{ID: "PSM-EXEC-MULTI-IN", StepID: "STEP-EXEC-MULTI-1", MaterialID: strPtrServiceTest("MAT-EXEC-MULTI"), Role: domain.ProcessStepMaterialRoleInput, QuantityPerUnit: 1, Unit: "kg"},
		&domain.ProcessStepMaterial{ID: "PSM-EXEC-MULTI-OUT", StepID: "STEP-EXEC-MULTI-2", ProductID: strPtrServiceTest("P-EXEC-MULTI"), Role: domain.ProcessStepMaterialRoleOutput, QuantityPerUnit: 1, Unit: "pcs"},
	}
	for _, record := range records {
		if err := db.Create(record).Error; err != nil {
			t.Fatalf("seed %T: %v", record, err)
		}
	}

	svc := newProductionLogExecutionService(db)
	if _, err := svc.LogProduction(dto.LogProductionRequest{SlotID: "SLOT-EXEC-MULTI-1", StartTime: now, EndTime: now.Add(time.Hour), QuantityProduced: 10}); err != nil {
		t.Fatalf("log step 1: %v", err)
	}
	if _, err := svc.LogProduction(dto.LogProductionRequest{SlotID: "SLOT-EXEC-MULTI-2", StartTime: now.Add(2 * time.Hour), EndTime: now.Add(3 * time.Hour), QuantityProduced: 10}); err != nil {
		t.Fatalf("log step 2: %v", err)
	}

	var job domain.Job
	if err := db.First(&job, "job_id = ?", "JOB-EXEC-MULTI").Error; err != nil {
		t.Fatalf("load job: %v", err)
	}
	if job.QuantityCompleted != 10 || job.Status != domain.JobStatusCompleted {
		t.Fatalf("job progress/status = %d/%s, want 10/completed", job.QuantityCompleted, job.Status)
	}
}

func strPtrServiceTest(s string) *string {
	return &s
}
