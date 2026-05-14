package handler

import (
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/internal/service"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

type ProductHandler struct {
	productService *service.ProductService
}

func NewProductHandler(productService *service.ProductService) *ProductHandler {
	return &ProductHandler{productService: productService}
}

// @Summary Create a new product
// @Description Create a new product with the provided details. product_id is generated with the P- prefix when omitted.
// @Tags products
// @Accept json
// @Produce json
// @Param product body dto.CreateProductRequest true "Product data"
// @Success 201 {object} dto.Response{data=domain.Product}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /products [post]
func (h *ProductHandler) Create(c *gin.Context) {
	var req dto.CreateProductRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	product, err := h.productService.Create(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: product})
}

// @Summary Get a product by ID
// @Description Get a product by ID. Supports optional field selection.
// @Tags products
// @Accept json
// @Produce json
// @Param id path string true "Product ID"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=domain.Product}
// @Failure 404 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /products/{id} [get]
func (h *ProductHandler) GetByID(c *gin.Context) {
	id := c.Param("id")
	product, err := h.productService.GetByID(id)
	if err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: product})
}

// @Summary List all products
// @Description List products with optional filters, sorting, and field selection
// @Tags products
// @Accept json
// @Produce json
// @Param status query string false "Filter by status" Enums(active,obsolete)
// @Param product_type query string false "Filter by product type"
// @Param sort_by query string false "Field to sort by" Enums(product_id,product_name,created_at)
// @Param sort_dir query string false "asc|desc" Enums(asc,desc)
// @Param limit query int false "Page size"
// @Param offset query int false "Offset"
// @Param fields query string false "Comma-separated fields; use product_id for ID-only view"
// @Success 200 {object} dto.Response{data=[]domain.Product}
// @Failure 500 {object} dto.Response
// @Router /products [get]
func (h *ProductHandler) List(c *gin.Context) {
	var query dto.ProductListQuery
	if err := c.ShouldBindQuery(&query); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	var f repository.ProductListFilter
	f.Status = strings.TrimSpace(string(query.Status))
	f.ProductType = strings.TrimSpace(query.ProductType)
	f.SortBy = strings.TrimSpace(query.SortBy)
	f.SortDir = strings.TrimSpace(string(query.SortDir))
	f.Limit = query.Limit
	f.Offset = query.Offset
	if f.SortBy == "" {
		f.SortBy = "product_id"
	}
	if f.SortDir == "" {
		f.SortDir = "asc"
	}

	products, err := h.productService.ListFiltered(f)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}

	fields := strings.TrimSpace(strings.ToLower(query.Fields))
	if fields != "" {
		selected := make(map[string]bool)
		for _, token := range strings.Split(fields, ",") {
			normalized := strings.TrimSpace(token)
			if normalized != "" {
				selected[normalized] = true
			}
		}
		if len(selected) == 1 && selected["product_id"] {
			ids := make([]dto.ProductIDOnly, 0, len(products))
			for _, p := range products {
				ids = append(ids, dto.ProductIDOnly{ProductID: p.ProductID})
			}
			c.JSON(http.StatusOK, dto.Response{Success: true, Data: ids})
			return
		}
	}

	c.JSON(http.StatusOK, dto.Response{Success: true, Data: products})
}

// @Summary Get a scheduling definition by product ID
// @Description Get a scheduling definition by product ID
// @Tags products
// @Accept json
// @Produce json
// @Param id path string true "Product ID"
// @Success 200 {object} dto.Response{data=service.ProductSchedulingDefinition}
// @Failure 404 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /products/{id}/scheduling-definition [get]
func (h *ProductHandler) GetSchedulingDefinition(c *gin.Context) {
	id := c.Param("id")
	def, err := h.productService.GetSchedulingDefinition(id)
	if err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: def})
}

// @Summary Link a BOM to a product
// @Description Link a BOM to a product
// @Tags products
// @Accept json
// @Produce json
// @Param id path string true "Product ID"
// @Param request body dto.LinkProductRequest true "Link Product Request"
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /products/{id}/bom [put]
func (h *ProductHandler) LinkBOM(c *gin.Context) {
	productID := c.Param("id")
	var req dto.LinkProductRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	if err := h.productService.LinkBOM(productID, req.FormulaID, req.ProcessID, req.BOMItems); err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true})
}
