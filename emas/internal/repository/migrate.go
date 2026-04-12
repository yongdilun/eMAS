package repository

import (
	"emas/internal/domain"
	"strings"

	"gorm.io/gorm"
)

// AutoMigrate runs GORM auto-migration for all domain models
func AutoMigrate(db *gorm.DB) error {
	if err := db.AutoMigrate(
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
		&domain.ProductInventoryReservation{},
		&domain.JobDependency{},
		&domain.QualityInspectionRecords{},
		&domain.ProductionLogs{},
		&domain.MLTrainingEvent{},
		&domain.MaintenanceRecords{},
		&domain.SystemSetting{},
		&domain.AIConversation{},
		&domain.AIChatMessage{},
	); err != nil {
		return err
	}
	return migrateMLTrainingEvents(db)
}

func migrateMLTrainingEvents(db *gorm.DB) error {
	if db == nil || !db.Migrator().HasTable(&domain.MLTrainingEvent{}) {
		return nil
	}
	if !db.Migrator().HasColumn(&domain.MLTrainingEvent{}, "lineage_id") {
		if err := db.Migrator().AddColumn(&domain.MLTrainingEvent{}, "LineageID"); err != nil {
			return err
		}
	}
	if !db.Migrator().HasColumn(&domain.MLTrainingEvent{}, "split_group_id") {
		if err := db.Migrator().AddColumn(&domain.MLTrainingEvent{}, "SplitGroupID"); err != nil {
			return err
		}
	}
	if !db.Migrator().HasColumn(&domain.MLTrainingEvent{}, "batch_sequence") {
		if err := db.Migrator().AddColumn(&domain.MLTrainingEvent{}, "BatchSequence"); err != nil {
			return err
		}
	}
	if err := db.Exec("UPDATE ml_training_events SET lineage_id = slot_id WHERE (lineage_id IS NULL OR lineage_id = '') AND slot_id IS NOT NULL AND slot_id <> ''").Error; err != nil {
		return err
	}
	if strings.EqualFold(db.Dialector.Name(), "mysql") {
		if err := db.Exec("ALTER TABLE ml_training_events MODIFY COLUMN slot_id varchar(50) NULL").Error; err != nil && !isIgnorableMLMigrationErr(err) {
			return err
		}
		if err := db.Exec("ALTER TABLE ml_training_events DROP PRIMARY KEY, ADD PRIMARY KEY (lineage_id)").Error; err != nil && !isIgnorableMLMigrationErr(err) {
			return err
		}
		if !db.Migrator().HasIndex(&domain.MLTrainingEvent{}, "idx_ml_training_events_slot_id") {
			if err := db.Exec("CREATE INDEX idx_ml_training_events_slot_id ON ml_training_events(slot_id)").Error; err != nil && !isIgnorableMLMigrationErr(err) {
				return err
			}
		}
	}
	return nil
}

func isIgnorableMLMigrationErr(err error) bool {
	if err == nil {
		return false
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "duplicate key name") ||
		strings.Contains(msg, "duplicate key") ||
		strings.Contains(msg, "already exists") ||
		strings.Contains(msg, "multiple primary key defined")
}
