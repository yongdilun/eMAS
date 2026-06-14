package seeddata

import (
	"fmt"

	"gorm.io/gorm"
)

var canonicalResetTables = []string{
	"idempotency_logs",
	"ai_chat_messages",
	"ai_conversations",
	"chatbot_approvals",
	"chatbot_tool_execution_snapshots",
	"chatbot_turn_audits",
	"scheduling_events",
	"quality_inspection_records",
	"production_logs",
	"ai_proposals",
	"ml_training_events",
	"inventory_reservations",
	"product_inventory_reservations",
	"product_inventory",
	"job_dependencies",
	"inventory_expected_arrivals",
	"inventory_transactions",
	"wip_inventory",
	"job_step_schedule_slots",
	"job_steps",
	"jobs",
	"resource_allocations",
	"resource_calendar",
	"step_resource_requirements",
	"resources",
	"machine_downtime",
	"machine_capabilities",
	"machine_calendar",
	"maintenance_records",
	"machine_setup_rules",
	"product_bom",
	"process_step_materials",
	"formula_ingredients",
	"process_steps",
	"products",
	"formula",
	"product_process",
	"inventory_materials",
	"machines",
	"system_settings",
	"reference_machine_types",
	"reference_product_types",
	"reference_locations",
	"reference_storage_locations",
	"reference_step_types",
}

func ResetCanonicalDB(db *gorm.DB, opts SeedOptions) error {
	return db.Transaction(func(tx *gorm.DB) error {
		for _, table := range canonicalResetTables {
			if err := tx.Exec("DELETE FROM " + table).Error; err != nil {
				return fmt.Errorf("reset %s: %w", table, err)
			}
		}
		return SeedCanonical(tx, opts)
	})
}
