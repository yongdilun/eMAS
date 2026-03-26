package handler

import (
	"emas/internal/handler/dto"
	"emas/internal/service"
	"net/http"

	"github.com/gin-gonic/gin"
)

type QualityHandler struct {
	qualityService *service.QualityService
}

func NewQualityHandler(qualityService *service.QualityService) *QualityHandler {
	return &QualityHandler{qualityService: qualityService}
}

func (h *QualityHandler) RecordInspection(c *gin.Context) {
	var req dto.RecordInspectionRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	record, err := h.qualityService.RecordInspection(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: record})
}
