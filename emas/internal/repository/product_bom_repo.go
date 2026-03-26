package repository

import (
	"emas/internal/domain"

	"gorm.io/gorm"
)

type ProductBOMRepository struct {
	db *gorm.DB
}

func NewProductBOMRepository(db *gorm.DB) *ProductBOMRepository {
	return &ProductBOMRepository{db: db}
}

func (r *ProductBOMRepository) ListByProductID(productID string) ([]domain.ProductBOM, error) {
	var items []domain.ProductBOM
	err := r.db.Where("product_id = ?", productID).Find(&items).Error
	return items, err
}

func (r *ProductBOMRepository) Create(b *domain.ProductBOM) error {
	return r.db.Create(b).Error
}

func (r *ProductBOMRepository) DeleteByProductID(productID string) error {
	return r.db.Where("product_id = ?", productID).Delete(&domain.ProductBOM{}).Error
}
