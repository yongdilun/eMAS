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

func (h *FormulaHandler) GetByID(c *gin.Context) {
	id := c.Param("id")
	f, err := h.formulaService.GetByID(id)
	if err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: f})
}

func (h *FormulaHandler) List(c *gin.Context) {
	list, err := h.formulaService.ListAll()
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: list})
}

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

func (h *FormulaHandler) ListIngredients(c *gin.Context) {
	id := c.Param("id")
	list, err := h.formulaService.ListIngredients(id)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: list})
}

func (h *FormulaHandler) Delete(c *gin.Context) {
	id := c.Param("id")
	if err := h.formulaService.Delete(id); err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true})
}
