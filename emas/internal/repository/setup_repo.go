package repository

import (
	"emas/internal/domain"

	"gorm.io/gorm"
)

type SetupRepository struct {
	db *gorm.DB
}

func NewSetupRepository(db *gorm.DB) *SetupRepository {
	return &SetupRepository{db: db}
}

// GetSetupMinutes returns setup time in minutes when switching from fromProductID to toProductID on machineID.
// Looks up exact match first; falls back to fromProduct="" (any) or toProduct="" (any) if defined.
// Returns 0 if no rule found.
func (r *SetupRepository) GetSetupMinutes(machineID, fromProductID, toProductID string) (int, error) {
	var rule domain.MachineSetupRule
	// Prefer exact match
	err := r.db.Where("machine_id = ? AND from_product_id = ? AND to_product_id = ?", machineID, fromProductID, toProductID).First(&rule).Error
	if err == nil {
		return rule.SetupMinutes, nil
	}
	// Fallback: from any to toProduct
	err = r.db.Where("machine_id = ? AND (from_product_id = '' OR from_product_id IS NULL) AND to_product_id = ?", machineID, toProductID).First(&rule).Error
	if err == nil {
		return rule.SetupMinutes, nil
	}
	// Fallback: from fromProduct to any
	err = r.db.Where("machine_id = ? AND from_product_id = ? AND (to_product_id = '' OR to_product_id IS NULL)", machineID, fromProductID).First(&rule).Error
	if err == nil {
		return rule.SetupMinutes, nil
	}
	return 0, nil
}

func (r *SetupRepository) Create(rule *domain.MachineSetupRule) error {
	return r.db.Create(rule).Error
}
