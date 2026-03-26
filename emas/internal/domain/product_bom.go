package domain

// ProductBOM - Bill of Materials: materials or sub-products required per product unit
type ProductBOM struct {
	BOMID             string   `gorm:"column:bom_id;primaryKey;size:50"`
	ProductID         string   `gorm:"column:product_id;size:50;index"`
	ComponentType     string   `gorm:"column:component_type;size:20;default:material"`
	MaterialID        *string  `gorm:"column:material_id;size:50;index"`
	ProductComponentID *string  `gorm:"column:product_component_id;size:50;index"` // sub-product
	QuantityRequired  float64  `gorm:"column:quantity_required"` // qty per 1 unit of parent
	Unit              string   `gorm:"column:unit;size:50"`
	ScrapRate         float64  `gorm:"column:scrap_rate"`
}

func (ProductBOM) TableName() string { return "product_bom" }
