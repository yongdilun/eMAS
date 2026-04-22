package handler

import (
	"errors"
	"net/http"
	"strings"

	"emas/internal/handler/dto"
	"emas/internal/service"

	"github.com/gin-gonic/gin"
)

type FormulaHandler struct {
	formulaService *service.FormulaService
}

func NewFormulaHandler(formulaService *service.FormulaService) *FormulaHandler {
	return &FormulaHandler{formulaService: formulaService}
}

// @Summary Create a formula
// @Description Create a formula
// @Tags formula
// @Accept json
// @Produce json
// @Param request body dto.CreateFormulaRequest true "Create Formula Request"
// @Success 201 {object} dto.Response{data=domain.Formula}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /formula [post]
func (h *FormulaHandler) Create(c *gin.Context) {
	var req dto.CreateFormulaRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	f, err := h.formulaService.Create(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: f})
}

// @Summary Get a formula by ID
// @Description Get a formula by ID
// @Tags formula
// @Accept json
// @Produce json
// @Param id path string true "Formula ID"
// @Success 200 {object} dto.Response{data=domain.Formula}
// @Failure 404 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /formula/{id} [get]
func (h *FormulaHandler) GetByID(c *gin.Context) {
	id := c.Param("id")
	f, err := h.formulaService.GetByID(id)
	if err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: f})
}

// @Summary List all formulas
// @Description List all formulas
// @Tags formula
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=[]domain.Formula}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /formula [get]
func (h *FormulaHandler) List(c *gin.Context) {
	list, err := h.formulaService.ListAll()
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: list})
}

// @Summary Add an ingredient to a formula
// @Description Add an ingredient to a formula
// @Tags formula
// @Accept json
// @Produce json
// @Param id path string true "Formula ID"
// @Param request body dto.AddFormulaIngredientRequest true "Add Formula Ingredient Request"
// @Success 201 {object} dto.Response{data=domain.FormulaIngredients}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /formula/{id}/ingredients [post]
func (h *FormulaHandler) AddIngredient(c *gin.Context) {
	id := c.Param("id")
	var req dto.AddFormulaIngredientRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	ing, err := h.formulaService.AddIngredient(id, req)
	if err != nil {
		code := http.StatusInternalServerError
		if errors.Is(err, service.ErrIngredientBothIDs) || errors.Is(err, service.ErrIngredientNeither) || errors.Is(err, service.ErrIngredientCircular) || strings.Contains(err.Error(), "quantity_per_unit") || strings.Contains(err.Error(), "product_id not found") {
			code = http.StatusUnprocessableEntity
		}
		c.JSON(code, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: ing})
}

// @Summary List ingredients for a formula
// @Description List ingredients for a formula
// @Tags formula
// @Accept json
// @Produce json
// @Param id path string true "Formula ID"
// @Success 200 {object} dto.Response{data=[]repository.IngredientWithNames}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /formula/{id}/ingredients [get]
func (h *FormulaHandler) ListIngredients(c *gin.Context) {
	id := c.Param("id")
	list, err := h.formulaService.ListIngredients(id)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: list})
}

// @Summary Delete a formula
// @Description Delete a formula
// @Tags formula
// @Accept json
// @Produce json
// @Param id path string true "Formula ID"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /formula/{id} [delete]
func (h *FormulaHandler) Delete(c *gin.Context) {
	id := c.Param("id")
	if err := h.formulaService.Delete(id); err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true})
}
