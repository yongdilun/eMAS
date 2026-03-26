package handler

import (
	"emas/internal/handler/dto"
	"emas/internal/service"
	"net/http"

	"github.com/gin-gonic/gin"
)

type ProductionLogHandler struct {
	productionLogService *service.ProductionLogService
}

func NewProductionLogHandler(productionLogService *service.ProductionLogService) *ProductionLogHandler {
	return &ProductionLogHandler{productionLogService: productionLogService}
}

func (h *ProductionLogHandler) LogProduction(c *gin.Context) {
	var req dto.LogProductionRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	log, err := h.productionLogService.LogProduction(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: log})
}
