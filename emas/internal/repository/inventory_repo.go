package repository

import (
	"emas/internal/domain"
	"strings"
	"time"

	"gorm.io/gorm"
)

type InventoryRepository struct {
	db *gorm.DB
}

func NewInventoryRepository(db *gorm.DB) *InventoryRepository {
	return &InventoryRepository{db: db}
}

func (r *InventoryRepository) GetMaterialByID(id string) (*domain.InventoryMaterials, error) {
	var m domain.InventoryMaterials
	err := r.db.Where("material_id = ?", id).First(&m).Error
	if err != nil {
		return nil, err
	}
	return &m, nil
}

func (r *InventoryRepository) UpdateMaterial(m *domain.InventoryMaterials) error {
	return r.db.Save(m).Error
}

func (r *InventoryRepository) CreateTransaction(t *domain.InventoryTransactions) error {
	return r.db.Create(t).Error
}

func (r *InventoryRepository) ListMaterials() ([]domain.InventoryMaterials, error) {
	var materials []domain.InventoryMaterials
	err := r.db.Find(&materials).Error
	return materials, err
}

type InventoryListFilter struct {
	Status   string
	NameLike string
	SortBy   string // material_name, current_stock, last_updated
	SortDir  string // asc, desc
	Limit    int
	Offset   int
}

func (r *InventoryRepository) ListMaterialsFiltered(f InventoryListFilter) ([]domain.InventoryMaterials, error) {
	q := r.db.Model(&domain.InventoryMaterials{})

	if f.Status != "" {
		q = q.Where("status = ?", f.Status)
	}
	if f.NameLike != "" {
		q = q.Where("LOWER(material_name) LIKE ?", "%"+strings.ToLower(f.NameLike)+"%")
	}

	sortDir := strings.ToLower(f.SortDir)
	if sortDir != "asc" && sortDir != "desc" {
		sortDir = "asc"
	}
	switch strings.ToLower(f.SortBy) {
	case "current_stock":
		q = q.Order("current_stock " + sortDir)
	case "last_updated":
		q = q.Order("last_updated " + sortDir)
	default:
		q = q.Order("material_name " + sortDir)
	}

	if f.Limit > 0 {
		q = q.Limit(f.Limit)
	}
	if f.Offset > 0 {
		q = q.Offset(f.Offset)
	}

	var materials []domain.InventoryMaterials
	if err := q.Find(&materials).Error; err != nil {
		return nil, err
	}
	return materials, nil
}

func (r *InventoryRepository) CreateMaterial(m *domain.InventoryMaterials) error {
	return r.db.Create(m).Error
}

func (r *InventoryRepository) CreateExpectedArrival(a *domain.InventoryExpectedArrival) error {
	return r.db.Create(a).Error
}

func (r *InventoryRepository) ListExpectedArrivals(materialID string, from, to *time.Time, status string) ([]domain.InventoryExpectedArrival, error) {
	q := r.db.Model(&domain.InventoryExpectedArrival{})
	if materialID != "" {
		q = q.Where("material_id = ?", materialID)
	}
	if from != nil {
		q = q.Where("expected_arrive_at >= ?", *from)
	}
	if to != nil {
		q = q.Where("expected_arrive_at <= ?", *to)
	}
	if status != "" {
		q = q.Where("status = ?", status)
	}
	q = q.Order("expected_arrive_at ASC")
	var list []domain.InventoryExpectedArrival
	err := q.Find(&list).Error
	return list, err
}

func (r *InventoryRepository) CreateProductInventory(p *domain.ProductInventory) error {
	return r.db.Create(p).Error
}

func (r *InventoryRepository) UpdateProductInventory(p *domain.ProductInventory) error {
	return r.db.Save(p).Error
}

func (r *InventoryRepository) GetProductInventory(productID string) (*domain.ProductInventory, error) {
	var inv domain.ProductInventory
	err := r.db.Where("product_id = ?", productID).Order("available_from ASC").First(&inv).Error
	if err != nil {
		return nil, err
	}
	return &inv, nil
}

func (r *InventoryRepository) ListProductInventory() ([]domain.ProductInventory, error) {
	var list []domain.ProductInventory
	err := r.db.Order("product_id").Find(&list).Error
	return list, err
}

func (r *InventoryRepository) ListProductInventoryByProductID(productID string) ([]domain.ProductInventory, error) {
	var list []domain.ProductInventory
	err := r.db.Where("product_id = ?", productID).Order("available_from ASC").Find(&list).Error
	return list, err
}

func (r *InventoryRepository) CreateReservation(res *domain.InventoryReservation) error {
	return r.db.Create(res).Error
}

func (r *InventoryRepository) UpdateReservation(res *domain.InventoryReservation) error {
	return r.db.Save(res).Error
}

func (r *InventoryRepository) ListReservations(materialID string, status string) ([]domain.InventoryReservation, error) {
	return r.ListReservationsExcluding(materialID, status, nil)
}

func (r *InventoryRepository) ListReservationsExcluding(materialID string, status string, excludeJobIDs []string) ([]domain.InventoryReservation, error) {
	q := r.db.Model(&domain.InventoryReservation{})
	if materialID != "" {
		q = q.Where("material_id = ?", materialID)
	}
	if status != "" {
		q = q.Where("status = ?", status)
	}
	if len(excludeJobIDs) > 0 {
		q = q.Where("job_id NOT IN ?", excludeJobIDs)
	}
	var list []domain.InventoryReservation
	err := q.Order("needed_at ASC").Find(&list).Error
	return list, err
}

func (r *InventoryRepository) ListReservationsByMaterialUntil(materialID string, neededAt time.Time, status string) ([]domain.InventoryReservation, error) {
	q := r.db.Model(&domain.InventoryReservation{}).Where("material_id = ? AND needed_at <= ?", materialID, neededAt)
	if status != "" {
		q = q.Where("status = ?", status)
	}
	var list []domain.InventoryReservation
	err := q.Order("needed_at ASC").Find(&list).Error
	return list, err
}

func (r *InventoryRepository) SumActiveReservations(materialID string) (float64, error) {
	var total float64
	err := r.db.Model(&domain.InventoryReservation{}).
		Where("material_id = ? AND status = ?", materialID, domain.InventoryReservationStatusPending).
		Select("COALESCE(SUM(reserved_qty),0)").
		Scan(&total).Error
	return total, err
}

func (r *InventoryRepository) SumActiveReservationsUntil(materialID string, neededAt time.Time) (float64, error) {
	return r.SumActiveReservationsUntilExcluding(materialID, neededAt, nil)
}

func (r *InventoryRepository) SumActiveReservationsUntilExcluding(materialID string, neededAt time.Time, excludeJobIDs []string) (float64, error) {
	var total float64
	q := r.db.Model(&domain.InventoryReservation{}).
		Where("material_id = ? AND status = ? AND needed_at <= ?", materialID, domain.InventoryReservationStatusPending, neededAt)
	if len(excludeJobIDs) > 0 {
		q = q.Where("job_id NOT IN ?", excludeJobIDs)
	}
	err := q.Select("COALESCE(SUM(reserved_qty),0)").Scan(&total).Error
	return total, err
}

// SumAllActiveReservations returns the total pending reserved quantity for a material
// regardless of needed_at. This gives the true committed/locked stock across all
// future-scheduled slots, so the scheduler knows the real free inventory.
func (r *InventoryRepository) SumAllActiveReservations(materialID string) (float64, error) {
	var total float64
	err := r.db.Model(&domain.InventoryReservation{}).
		Where("material_id = ? AND status = ?", materialID, domain.InventoryReservationStatusPending).
		Select("COALESCE(SUM(reserved_qty),0)").
		Scan(&total).Error
	return total, err
}

func (r *InventoryRepository) CreateProductReservation(res *domain.ProductInventoryReservation) error {
	return r.db.Create(res).Error
}

func (r *InventoryRepository) UpdateProductReservation(res *domain.ProductInventoryReservation) error {
	return r.db.Save(res).Error
}

func (r *InventoryRepository) ListProductReservations(productID, status string) ([]domain.ProductInventoryReservation, error) {
	q := r.db.Model(&domain.ProductInventoryReservation{})
	if productID != "" {
		q = q.Where("product_id = ?", productID)
	}
	if status != "" {
		q = q.Where("status = ?", status)
	}
	var list []domain.ProductInventoryReservation
	err := q.Order("needed_at ASC, reservation_id ASC").Find(&list).Error
	return list, err
}

func (r *InventoryRepository) ListProductReservationsByProductUntil(productID string, neededAt time.Time, status string) ([]domain.ProductInventoryReservation, error) {
	q := r.db.Model(&domain.ProductInventoryReservation{}).Where("product_id = ? AND needed_at <= ?", productID, neededAt)
	if status != "" {
		q = q.Where("status = ?", status)
	}
	var list []domain.ProductInventoryReservation
	err := q.Order("needed_at ASC, reservation_id ASC").Find(&list).Error
	return list, err
}

func (r *InventoryRepository) SumActiveProductReservations(productID string) (float64, error) {
	var total float64
	err := r.db.Model(&domain.ProductInventoryReservation{}).
		Where("product_id = ? AND status = ?", productID, domain.InventoryReservationStatusPending).
		Select("COALESCE(SUM(reserved_qty),0)").
		Scan(&total).Error
	return total, err
}

func (r *InventoryRepository) SumActiveProductReservationsUntil(productID string, neededAt time.Time) (float64, error) {
	var total float64
	err := r.db.Model(&domain.ProductInventoryReservation{}).
		Where("product_id = ? AND status = ? AND needed_at <= ?", productID, domain.InventoryReservationStatusPending, neededAt).
		Select("COALESCE(SUM(reserved_qty),0)").
		Scan(&total).Error
	return total, err
}
