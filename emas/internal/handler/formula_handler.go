package handler

import (
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/internal/service"
	"errors"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
)

type FormulaHandler struct {
	formulaService *service.FormulaService
}

func NewFormulaHandler(formulaService *service.FormulaService) *FormulaHandler {
	return &FormulaHandler{formulaService: formulaService}
}

// @Summary Create a formula
// @Description Create a formula. formula_id is generated with the F- prefix when omitted.
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
// @Description Get a formula by ID. Supports optional field selection.
// @Tags formula
// @Accept json
// @Produce json
// @Param id path string true "Formula ID"
// @Param fields query string false "Comma-separated fields to return"
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
// @Description List formulas with optional filters, sorting, and pagination
// @Tags formula
// @Accept json
// @Produce json
// @Param q query string false "Search by formula name"
// @Param sort_by query string false "Field to sort by (formula_id, formula_name, created_at)"
// @Param sort_dir query string false "Sort direction (asc, desc)"
// @Param limit query int false "Limit number of results"
// @Param offset query int false "Offset for pagination"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=[]domain.Formula}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /formula [get]
func (h *FormulaHandler) List(c *gin.Context) {
	var f repository.FormulaListFilter
	f.NameLike = c.Query("q")
	f.SortBy = c.Query("sort_by")
	f.SortDir = c.Query("sort_dir")
	f.Fields = c.Query("fields")

	if v := c.Query("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			f.Limit = n
		}
	}
	if v := c.Query("offset"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			f.Offset = n
		}
	}

	list, err := h.formulaService.ListFiltered(f)
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
