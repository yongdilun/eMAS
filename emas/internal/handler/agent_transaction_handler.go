package handler

import (
	"errors"
	"net/http"

	"emas/internal/handler/dto"
	"emas/internal/service"

	"github.com/gin-gonic/gin"
)

type AgentTransactionHandler struct {
	service *service.AgentTransactionService
}

func NewAgentTransactionHandler(service *service.AgentTransactionService) *AgentTransactionHandler {
	return &AgentTransactionHandler{service: service}
}

func (h *AgentTransactionHandler) BundleDryRun(c *gin.Context) {
	var req service.AgentTransactionRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	result, err := h.service.DryRun(req)
	if err != nil {
		status, msg := agentTransactionStatus(err)
		c.JSON(status, dto.Response{Success: false, Error: msg})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: result})
}

func (h *AgentTransactionHandler) Commit(c *gin.Context) {
	var req service.AgentTransactionRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	bundleKey := c.GetHeader("Idempotency-Key")
	if bundleKey == "" {
		bundleKey = c.GetHeader("X-Bundle-Idempotency-Key")
	}
	result, err := h.service.Commit(req, bundleKey)
	if err != nil {
		status, msg := agentTransactionStatus(err)
		c.JSON(status, dto.Response{Success: false, Error: msg})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: result})
}

func agentTransactionStatus(err error) (int, string) {
	var txErr *service.AgentTransactionError
	if errors.As(err, &txErr) {
		return txErr.StatusCode, txErr.Message
	}
	return http.StatusInternalServerError, err.Error()
}
