package repository

import (
	"emas/internal/domain"

	"gorm.io/gorm"
)

// AutoMigrate runs GORM auto-migration for all domain models
func AutoMigrate(db *gorm.DB) error {
	return db.AutoMigrate(
		&domain.ReferenceMachineType{},
		&domain.ReferenceProductType{},
		&domain.ReferenceLocation{},
		&domain.ReferenceStorageLocation{},
		&domain.ReferenceStepType{},
		&domain.Product{},
		&domain.ProductBOM{},
		&domain.ProductProcess{},
		&domain.ProcessSteps{},
		&domain.ProcessStepMaterial{},
		&domain.MachineSetupRule{},
		&domain.Resource{},
		&domain.StepResourceRequirement{},
		&domain.ResourceCalendar{},
		&domain.ResourceAllocation{},
		&domain.WIPInventory{},
		&domain.SchedulingEvent{},
		&domain.Formula{},
		&domain.FormulaIngredients{},
		&domain.Machine{},
		&domain.MachineCalendar{},
		&domain.MachineCapabilities{},
		&domain.MachineDowntime{},
		&domain.Job{},
		&domain.JobSteps{},
		&domain.AIProposal{},
		&domain.JobStepScheduleSlots{},
		&domain.InventoryMaterials{},
		&domain.InventoryTransactions{},
		&domain.InventoryExpectedArrival{},
		&domain.ProductInventory{},
		&domain.InventoryReservation{},
		&domain.QualityInspectionRecords{},
		&domain.ProductionLogs{},
		&domain.MaintenanceRecords{},
		&domain.SystemSetting{},
		&domain.AIConversation{},
		&domain.AIChatMessage{},
	)
}
