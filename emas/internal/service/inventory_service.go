package service

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/pkg/id"
	"time"
)

type InventoryService struct {
	invRepo *repository.InventoryRepository
}

func NewInventoryService(invRepo *repository.InventoryRepository) *InventoryService {
	return &InventoryService{invRepo: invRepo}
}

func (s *InventoryService) ConsumeMaterial(req dto.ConsumeMaterialRequest) error {
	m, err := s.invRepo.GetMaterialByID(req.MaterialID)
	if err != nil {
		return err
	}
	m.CurrentStock -= req.Quantity
	if m.CurrentStock < m.MinStock {
		m.Status = domain.InventoryStatusLowStock
	}
	if m.CurrentStock <= 0 {
		m.Status = domain.InventoryStatusOutOfStock
	}
	m.LastUpdated = time.Now()
	if err := s.invRepo.UpdateMaterial(m); err != nil {
		return err
	}
	t := &domain.InventoryTransactions{
		TransactionID:   id.NewPrefixed("TXN-"),
		MaterialID:      req.MaterialID,
		TransactionType: domain.TransactionTypeConsume,
		Quantity:        req.Quantity,
		ReferenceJobID:  req.ReferenceJobID,
		Timestamp:       time.Now(),
	}
	return s.invRepo.CreateTransaction(t)
}

func (s *InventoryService) ReceiveMaterial(req dto.ReceiveMaterialRequest) error {
	m, err := s.invRepo.GetMaterialByID(req.MaterialID)
	if err != nil {
		return err
	}
	m.CurrentStock += req.Quantity
	if m.CurrentStock >= m.ReorderLevel {
		m.Status = domain.InventoryStatusInStock
	}
	m.LastUpdated = time.Now()
	if err := s.invRepo.UpdateMaterial(m); err != nil {
		return err
	}
	t := &domain.InventoryTransactions{
		TransactionID:   id.NewPrefixed("TXN-"),
		MaterialID:      req.MaterialID,
		TransactionType: domain.TransactionTypeReceive,
		Quantity:        req.Quantity,
		Timestamp:       time.Now(),
	}
	return s.invRepo.CreateTransaction(t)
}

func (s *InventoryService) CreateMaterial(req dto.CreateMaterialRequest) (*domain.InventoryMaterials, error) {
	unit := req.Unit
	if unit == "" {
		unit = "pcs"
	}
	status := domain.InventoryStatusInStock
	if req.CurrentStock < req.MinStock {
		status = domain.InventoryStatusLowStock
	}
	if req.CurrentStock <= 0 {
		status = domain.InventoryStatusOutOfStock
	}
	m := &domain.InventoryMaterials{
		MaterialID:      req.MaterialID,
		MaterialName:    req.MaterialName,
		Unit:            unit,
		CurrentStock:    req.CurrentStock,
		MinStock:        req.MinStock,
		ReorderLevel:    req.ReorderLevel,
		StorageLocation: req.StorageLocation,
		Status:          status,
		LastUpdated:     time.Now(),
	}
	if err := s.invRepo.CreateMaterial(m); err != nil {
		return nil, err
	}
	return s.invRepo.GetMaterialByID(req.MaterialID)
}

func (s *InventoryService) GetMaterial(id string) (*domain.InventoryMaterials, error) {
	return s.invRepo.GetMaterialByID(id)
}

func (s *InventoryService) ListMaterials() ([]domain.InventoryMaterials, error) {
	return s.invRepo.ListMaterials()
}

func (s *InventoryService) ListMaterialsFiltered(f repository.InventoryListFilter) ([]domain.InventoryMaterials, error) {
	return s.invRepo.ListMaterialsFiltered(f)
}

func (s *InventoryService) ScheduleExpectedArrival(req dto.ScheduleExpectedArrivalRequest) (*domain.InventoryExpectedArrival, error) {
	if _, err := s.invRepo.GetMaterialByID(req.MaterialID); err != nil {
		return nil, err
	}
	a := &domain.InventoryExpectedArrival{
		ArrivalID:        id.NewPrefixed("ARR-"),
		MaterialID:       req.MaterialID,
		Quantity:         req.Quantity,
		ExpectedArriveAt: req.ExpectedArriveAt,
		Status:           domain.ExpectedArrivalStatusPending,
		Notes:            req.Notes,
		CreatedAt:        time.Now(),
	}
	if err := s.invRepo.CreateExpectedArrival(a); err != nil {
		return nil, err
	}
	return a, nil
}

func (s *InventoryService) ListExpectedArrivals(materialID, status string, from, to *time.Time) ([]domain.InventoryExpectedArrival, error) {
	return s.invRepo.ListExpectedArrivals(materialID, from, to, status)
}

func (s *InventoryService) CreateProductInventory(req dto.CreateProductInventoryRequest) (*domain.ProductInventory, error) {
	status := req.Status
	if status == "" {
		status = domain.ProductInventoryStatusAvailable
	}
	inv := &domain.ProductInventory{
		InventoryID:      id.NewPrefixed("PINV-"),
		ProductID:        req.ProductID,
		QuantityOnHand:   req.QuantityOnHand,
		QuantityReserved: req.QuantityReserved,
		Status:           status,
		StorageLocation:  req.StorageLocation,
		AvailableFrom:    req.AvailableFrom,
		LastUpdated:      time.Now(),
	}
	if inv.AvailableFrom.IsZero() {
		inv.AvailableFrom = time.Now()
	}
	if err := s.invRepo.CreateProductInventory(inv); err != nil {
		return nil, err
	}
	return inv, nil
}

func (s *InventoryService) ListProductInventory() ([]domain.ProductInventory, error) {
	return s.invRepo.ListProductInventory()
}

func (s *InventoryService) CreateReservation(req dto.CreateInventoryReservationRequest) (*domain.InventoryReservation, error) {
	if _, err := s.invRepo.GetMaterialByID(req.MaterialID); err != nil {
		return nil, err
	}
	res := &domain.InventoryReservation{
		ReservationID: id.NewPrefixed("RES-"),
		MaterialID:    req.MaterialID,
		JobID:         req.JobID,
		JobStepID:     req.JobStepID,
		ReservedQty:   req.ReservedQty,
		NeededAt:      req.NeededAt,
		Status:        domain.InventoryReservationStatusPending,
		CreatedAt:     time.Now(),
	}
	if res.NeededAt.IsZero() {
		res.NeededAt = time.Now()
	}
	if err := s.invRepo.CreateReservation(res); err != nil {
		return nil, err
	}
	return res, nil
}

func (s *InventoryService) ListReservations(materialID, status string) ([]domain.InventoryReservation, error) {
	return s.invRepo.ListReservations(materialID, status)
}
