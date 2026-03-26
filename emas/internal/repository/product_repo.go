package repository

import (
	"emas/internal/domain"

	"gorm.io/gorm"
)

type ProductRepository struct {
	db *gorm.DB
}

func NewProductRepository(db *gorm.DB) *ProductRepository {
	return &ProductRepository{db: db}
}

func (r *ProductRepository) Create(p *domain.Product) error {
	return r.db.Create(p).Error
}

func (r *ProductRepository) GetByID(id string) (*domain.Product, error) {
	var p domain.Product
	err := r.db.Where("product_id = ?", id).First(&p).Error
	if err != nil {
		return nil, err
	}
	return &p, nil
}

func (r *ProductRepository) GetByFormulaID(formulaID string) (*domain.Product, error) {
	var p domain.Product
	err := r.db.Where("formula_id = ?", formulaID).First(&p).Error
	if err != nil {
		return nil, err
	}
	return &p, nil
}

func (r *ProductRepository) ListAll() ([]domain.Product, error) {
	var products []domain.Product
	err := r.db.Find(&products).Error
	return products, err
}

func (r *ProductRepository) Update(p *domain.Product) error {
	return r.db.Save(p).Error
}

func (r *ProductRepository) Delete(id string) error {
	return r.db.Where("product_id = ?", id).Delete(&domain.Product{}).Error
}
