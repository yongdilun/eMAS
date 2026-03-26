package service

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/pkg/id"
	"errors"
)

type ProductSchedulingDefinition struct {
	Product           *domain.Product                  `json:"product"`
	Process           *domain.ProductProcess           `json:"process,omitempty"`
	Steps             []domain.ProcessSteps            `json:"steps,omitempty"`
	Formula           *domain.Formula                  `json:"formula,omitempty"`
	Ingredients       []repository.IngredientWithNames `json:"ingredients,omitempty"`
	BOMItems          []domain.ProductBOM              `json:"bom_items,omitempty"`
	CompositionSource string                           `json:"composition_source"`
}

type ProductService struct {
	productRepo *repository.ProductRepository
	bomRepo     *repository.ProductBOMRepository
	formulaRepo *repository.FormulaRepository
	processRepo *repository.ProcessRepository
}

func NewProductService(
	productRepo *repository.ProductRepository,
	bomRepo *repository.ProductBOMRepository,
	formulaRepo *repository.FormulaRepository,
	processRepo *repository.ProcessRepository,
) *ProductService {
	return &ProductService{
		productRepo: productRepo,
		bomRepo:     bomRepo,
		formulaRepo: formulaRepo,
		processRepo: processRepo,
	}
}

func (s *ProductService) Create(req dto.CreateProductRequest) (*domain.Product, error) {
	p := &domain.Product{
		ProductID:     req.ProductID,
		ProductName:   req.ProductName,
		Description:   req.Description,
		UnitOfMeasure: req.UnitOfMeasure,
		ProductType:   req.ProductType,
		Status:        domain.ProductStatusActive,
		FormulaID:     req.FormulaID,
		ProcessID:     req.ProcessID,
	}
	if p.UnitOfMeasure == "" {
		p.UnitOfMeasure = "pcs"
	}
	if err := s.validateDefinitionRefs(p.FormulaID, p.ProcessID); err != nil {
		return nil, err
	}
	if err := s.productRepo.Create(p); err != nil {
		return nil, err
	}
	return s.productRepo.GetByID(req.ProductID)
}

func (s *ProductService) GetByID(id string) (*domain.Product, error) {
	return s.productRepo.GetByID(id)
}

func (s *ProductService) ListAll() ([]domain.Product, error) {
	return s.productRepo.ListAll()
}

func (s *ProductService) GetSchedulingDefinition(productID string) (*ProductSchedulingDefinition, error) {
	product, err := s.productRepo.GetByID(productID)
	if err != nil {
		return nil, err
	}
	def := &ProductSchedulingDefinition{Product: product}
	if product.ProcessID != "" && s.processRepo != nil {
		process, err := s.processRepo.GetProcessByID(product.ProcessID)
		if err == nil {
			def.Process = process
			def.Steps, _ = s.processRepo.ListStepsByProcessID(process.ProcessID)
		}
	}
	if product.FormulaID != "" && s.formulaRepo != nil {
		formula, err := s.formulaRepo.GetByID(product.FormulaID)
		if err == nil {
			def.Formula = formula
			def.Ingredients, _ = s.formulaRepo.ListIngredientsWithNames(product.FormulaID)
			def.CompositionSource = "formula"
		}
	}
	def.BOMItems, _ = s.bomRepo.ListByProductID(productID)
	if def.CompositionSource == "" && len(def.BOMItems) > 0 {
		def.CompositionSource = "bom"
	}
	return def, nil
}

func (s *ProductService) LinkBOM(productID string, formulaID string, processID string, items []dto.BOMItem) error {
	product, err := s.productRepo.GetByID(productID)
	if err != nil {
		return err
	}
	nextFormulaID := product.FormulaID
	if formulaID != "" {
		nextFormulaID = formulaID
	}
	nextProcessID := product.ProcessID
	if processID != "" {
		nextProcessID = processID
	}
	if err := s.validateDefinitionRefs(nextFormulaID, nextProcessID); err != nil {
		return err
	}
	product.FormulaID = nextFormulaID
	product.ProcessID = nextProcessID
	if err := s.productRepo.Update(product); err != nil {
		return err
	}
	if items == nil {
		return nil
	}
	if err := s.bomRepo.DeleteByProductID(productID); err != nil {
		return err
	}
	for _, it := range items {
		hasMat := it.MaterialID != ""
		hasProd := it.ProductID != ""
		if hasMat && hasProd {
			return errors.New("provide exactly one of material_id or product_id")
		}
		if !hasMat && !hasProd {
			return errors.New("provide material_id or product_id")
		}
		qty := it.QuantityPerUnit
		if qty == 0 {
			qty = it.QuantityRequired
		}
		if qty <= 0 {
			return errors.New("quantity_per_unit must be positive")
		}
		unit := it.Unit
		if unit == "" {
			unit = "pcs"
		}
		b := &domain.ProductBOM{
			BOMID:            id.NewPrefixed("BOM-"),
			ProductID:        productID,
			QuantityRequired: qty,
			Unit:             unit,
			ScrapRate:        it.ScrapRate,
		}
		if hasMat {
			b.ComponentType = domain.ComponentTypeMaterial
			b.MaterialID = &it.MaterialID
		} else {
			b.ComponentType = domain.ComponentTypeProduct
			b.ProductComponentID = &it.ProductID
			if err := s.ensureNoBOMCycle(productID, it.ProductID); err != nil {
				return err
			}
		}
		if err := s.bomRepo.Create(b); err != nil {
			return err
		}
	}
	return nil
}

func (s *ProductService) validateDefinitionRefs(formulaID, processID string) error {
	if formulaID != "" && s.formulaRepo != nil {
		if _, err := s.formulaRepo.GetByID(formulaID); err != nil {
			return errors.New("formula_id not found")
		}
	}
	if processID != "" && s.processRepo != nil {
		if _, err := s.processRepo.GetProcessByID(processID); err != nil {
			return errors.New("process_id not found")
		}
	}
	return nil
}

func (s *ProductService) ensureNoBOMCycle(rootProductID, candidateProductID string) error {
	if candidateProductID == rootProductID {
		return errors.New("product_id cannot reference the parent product (circular)")
	}
	if _, err := s.productRepo.GetByID(candidateProductID); err != nil {
		return errors.New("product_id not found")
	}
	seen := map[string]bool{}
	var walk func(productID string) error
	walk = func(productID string) error {
		if seen[productID] {
			return nil
		}
		seen[productID] = true
		items, err := s.bomRepo.ListByProductID(productID)
		if err != nil {
			return err
		}
		for _, item := range items {
			if item.ProductComponentID == nil {
				continue
			}
			child := *item.ProductComponentID
			if child == rootProductID {
				return errors.New("product_id would create transitive circular dependency")
			}
			if err := walk(child); err != nil {
				return err
			}
		}
		return nil
	}
	return walk(candidateProductID)
}
