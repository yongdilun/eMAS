package repository

import (
	"emas/internal/domain"

	"gorm.io/gorm"
)

type FormulaRepository struct {
	db *gorm.DB
}

func NewFormulaRepository(db *gorm.DB) *FormulaRepository {
	return &FormulaRepository{db: db}
}

func (r *FormulaRepository) Create(f *domain.Formula) error {
	return r.db.Create(f).Error
}

func (r *FormulaRepository) GetByID(id string) (*domain.Formula, error) {
	var f domain.Formula
	err := r.db.Where("formula_id = ?", id).First(&f).Error
	if err != nil {
		return nil, err
	}
	return &f, nil
}

func (r *FormulaRepository) ListAll() ([]domain.Formula, error) {
	var list []domain.Formula
	err := r.db.Find(&list).Error
	return list, err
}

func (r *FormulaRepository) Update(f *domain.Formula) error {
	return r.db.Save(f).Error
}

func (r *FormulaRepository) Delete(id string) error {
	_ = r.db.Where("formula_id = ?", id).Delete(&domain.FormulaIngredients{})
	return r.db.Where("formula_id = ?", id).Delete(&domain.Formula{}).Error
}

func (r *FormulaRepository) CreateIngredient(i *domain.FormulaIngredients) error {
	return r.db.Create(i).Error
}

// ExistsIngredientMaterial returns true if formula already has this material
func (r *FormulaRepository) ExistsIngredientMaterial(formulaID, materialID string) (bool, error) {
	var count int64
	err := r.db.Model(&domain.FormulaIngredients{}).
		Where("formula_id = ? AND material_id = ?", formulaID, materialID).
		Count(&count).Error
	return count > 0, err
}

// ExistsIngredientProduct returns true if formula already has this product
func (r *FormulaRepository) ExistsIngredientProduct(formulaID, productID string) (bool, error) {
	var count int64
	err := r.db.Model(&domain.FormulaIngredients{}).
		Where("formula_id = ? AND product_id = ?", formulaID, productID).
		Count(&count).Error
	return count > 0, err
}

func (r *FormulaRepository) ListIngredientsByFormulaID(formulaID string) ([]domain.FormulaIngredients, error) {
	var list []domain.FormulaIngredients
	err := r.db.Where("formula_id = ?", formulaID).Find(&list).Error
	return list, err
}

// IngredientWithNames - ingredient with resolved material/product names for API response
type IngredientWithNames struct {
	IngredientID    string   `json:"ingredient_id"`
	FormulaID       string   `json:"formula_id"`
	ComponentType   string   `json:"component_type"`
	MaterialID      *string  `json:"material_id"`
	MaterialName    *string  `json:"material_name"`
	ProductID       *string  `json:"product_id"`
	ProductName     *string  `json:"product_name"`
	QuantityPerUnit float64  `json:"quantity_per_unit"`
	Unit            string   `json:"unit"`
	ScrapRate       float64  `json:"scrap_rate"`
}

func (r *FormulaRepository) ListIngredientsWithNames(formulaID string) ([]IngredientWithNames, error) {
	var list []IngredientWithNames
	err := r.db.Table("formula_ingredients fi").
		Select("fi.ingredient_id, fi.formula_id, fi.component_type, fi.material_id, fi.product_id, fi.quantity as quantity_per_unit, fi.unit, fi.scrap_rate, im.material_name, p.product_name").
		Joins("LEFT JOIN inventory_materials im ON fi.material_id = im.material_id").
		Joins("LEFT JOIN products p ON fi.product_id = p.product_id").
		Where("fi.formula_id = ?", formulaID).
		Scan(&list).Error
	return list, err
}
