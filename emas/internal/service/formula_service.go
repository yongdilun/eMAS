package service

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/pkg/id"
	"errors"
	"time"

	"gorm.io/gorm"
)

var (
	ErrIngredientBothIDs  = errors.New("provide exactly one of material_id or product_id")
	ErrIngredientNeither  = errors.New("provide material_id or product_id")
	ErrIngredientCircular = errors.New("product_id would create circular dependency")
)

type FormulaService struct {
	formulaRepo *repository.FormulaRepository
	productRepo *repository.ProductRepository // optional, for circular dep check
}

func NewFormulaService(formulaRepo *repository.FormulaRepository, productRepo *repository.ProductRepository) *FormulaService {
	return &FormulaService{formulaRepo: formulaRepo, productRepo: productRepo}
}

func (s *FormulaService) Create(req dto.CreateFormulaRequest) (*domain.Formula, error) {
	f := &domain.Formula{
		FormulaID:    req.FormulaID,
		FormulaName:  req.FormulaName,
		Version:      req.Version,
		Instructions: req.Instructions,
		SafetyNotes:  req.SafetyNotes,
		CreatedAt:    time.Now(),
	}
	if err := s.formulaRepo.Create(f); err != nil {
		return nil, err
	}
	return s.formulaRepo.GetByID(req.FormulaID)
}

func (s *FormulaService) GetByID(id string) (*domain.Formula, error) {
	return s.formulaRepo.GetByID(id)
}

func (s *FormulaService) ListAll() ([]domain.Formula, error) {
	return s.formulaRepo.ListAll()
}

func (s *FormulaService) AddIngredient(formulaID string, req dto.AddFormulaIngredientRequest) (*domain.FormulaIngredients, error) {
	hasMat := req.MaterialID != ""
	hasProd := req.ProductID != ""
	if hasMat && hasProd {
		return nil, ErrIngredientBothIDs
	}
	if !hasMat && !hasProd {
		return nil, ErrIngredientNeither
	}
	qty := req.QuantityPerUnit
	if qty == 0 {
		qty = req.Quantity
	}
	if qty <= 0 {
		return nil, errors.New("quantity_per_unit must be positive")
	}
	unit := req.Unit
	if unit == "" {
		unit = "pcs"
	}
	ing := &domain.FormulaIngredients{
		IngredientID:    id.NewPrefixed("ING-"),
		FormulaID:       formulaID,
		QuantityPerUnit: qty,
		Unit:            unit,
		ScrapRate:       req.ScrapRate,
		Percentage:      req.Percentage,
	}
	if hasMat {
		exists, err := s.formulaRepo.ExistsIngredientMaterial(formulaID, req.MaterialID)
		if err != nil {
			return nil, err
		}
		if exists {
			return nil, errors.New("formula already has this material")
		}
		ing.ComponentType = domain.ComponentTypeMaterial
		ing.MaterialID = &req.MaterialID
	} else {
		ing.ComponentType = domain.ComponentTypeProduct
		ing.ProductID = &req.ProductID
		exists, err := s.formulaRepo.ExistsIngredientProduct(formulaID, req.ProductID)
		if err != nil {
			return nil, err
		}
		if exists {
			return nil, errors.New("formula already has this product")
		}
		if s.productRepo != nil {
			if _, err := s.productRepo.GetByID(req.ProductID); err != nil {
				return nil, errors.New("product_id not found")
			}
			if err := s.ensureNoFormulaCycle(formulaID, req.ProductID); err != nil {
				return nil, err
			}
		}
	}
	if err := s.formulaRepo.CreateIngredient(ing); err != nil {
		return nil, err
	}
	return ing, nil
}

func (s *FormulaService) ListIngredients(formulaID string) ([]repository.IngredientWithNames, error) {
	return s.formulaRepo.ListIngredientsWithNames(formulaID)
}

func (s *FormulaService) Delete(id string) error {
	return s.formulaRepo.Delete(id)
}

func (s *FormulaService) ensureNoFormulaCycle(formulaID, childProductID string) error {
	if s.productRepo == nil {
		return nil
	}
	owner, err := s.productRepo.GetByFormulaID(formulaID)
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil
		}
		return err
	}
	rootProductID := owner.ProductID
	if childProductID == rootProductID {
		return ErrIngredientCircular
	}
	seen := map[string]bool{}
	var walk func(productID string) error
	walk = func(productID string) error {
		if seen[productID] {
			return nil
		}
		seen[productID] = true
		product, err := s.productRepo.GetByID(productID)
		if err != nil {
			return err
		}
		if product.FormulaID == "" {
			return nil
		}
		ingredients, err := s.formulaRepo.ListIngredientsByFormulaID(product.FormulaID)
		if err != nil {
			return err
		}
		for _, ing := range ingredients {
			if ing.ProductID == nil {
				continue
			}
			if *ing.ProductID == rootProductID {
				return ErrIngredientCircular
			}
			if err := walk(*ing.ProductID); err != nil {
				return err
			}
		}
		return nil
	}
	return walk(childProductID)
}
