package handler

import (
	"emas/internal/handler/dto"
	"emas/internal/service"
	"net/http"

	"github.com/gin-gonic/gin"
)

type ProductHandler struct {
	productService *service.ProductService
}

func NewProductHandler(productService *service.ProductService) *ProductHandler {
	return &ProductHandler{productService: productService}
}

// @Summary Create a new product
// @Description Create a new product with the provided details
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
// @Description Get a product by ID
// @Tags products
// @Accept json
// @Produce json
// @Param id path string true "Product ID"
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
// @Description List all products
// @Tags products
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=[]domain.Product}
// @Failure 500 {object} dto.Response
// @Router /products [get]

func (h *ProductHandler) List(c *gin.Context) {
	products, err := h.productService.ListAll()
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: products})
}

// @Summary Get a scheduling definition by product ID
// @Description Get a scheduling definition by product ID
// @Tags products
// @Accept json
// @Produce json
// @Param id path string true "Product ID"
// @Success 200 {object} dto.Response{data=domain.SchedulingDefinition}
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
// @Success 200 {object} dto.Response{success=true}
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
