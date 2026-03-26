package handler

import (
	"emas/internal/handler/dto"
	"emas/internal/service"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

type AIHandler struct {
	processor *service.AICommandProcessor
}

// NewAIHandler creates a new AI handler.
func NewAIHandler(processor *service.AICommandProcessor) *AIHandler {
	return &AIHandler{processor: processor}
}

type AICommandRequest struct {
	Query           string `json:"query" binding:"required"`
	ExecuteReadonly bool   `json:"execute_readonly"`
	Debug           bool   `json:"debug"`
}

func (h *AIHandler) ParseCommand(c *gin.Context) {
	var req AICommandRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	raw := strings.TrimSpace(req.Query)
	res, err := h.processor.ProcessCommand(raw, req.ExecuteReadonly, req.Debug)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: res})
}
