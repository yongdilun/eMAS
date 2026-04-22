package handler

import (
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/internal/service"
	"net/http"

	"github.com/gin-gonic/gin"
)

type ChatbotApprovalHandler struct {
	approvalRepo repository.ChatbotApprovalRepository
	executor     service.ApprovalExecutor
}

func NewChatbotApprovalHandler(
	approvalRepo repository.ChatbotApprovalRepository,
	executor service.ApprovalExecutor,
) *ChatbotApprovalHandler {
	return &ChatbotApprovalHandler{
		approvalRepo: approvalRepo,
		executor:     executor,
	}
}

// @Summary Get an approval by ID
// @Description Get an approval by ID
// @Tags chatbot approval
// @Accept json
// @Produce json
// @Param id path string true "Approval ID"
// @Success 200 {object} dto.Response{data=domain.ChatbotApproval}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /chatbot/approval/{id} [get]
func (h *ChatbotApprovalHandler) Get(c *gin.Context) {
	id := c.Param("id")
	if id == "" {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "approval id required"})
		return
	}

	approval, err := h.approvalRepo.GetByID(id)
	if err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: "approval not found"})
		return
	}

	c.JSON(http.StatusOK, dto.Response{Success: true, Data: approval})
}

// @Summary Approve an approval
// @Description Approve an approval
// @Tags chatbot approval
// @Accept json
// @Produce json
// @Param id path string true "Approval ID"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /chatbot/approval/{id}/approve [post]
func (h *ChatbotApprovalHandler) Approve(c *gin.Context) {
	id := c.Param("id")
	if id == "" {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "approval id required"})
		return
	}

	// In a real implementation, extract user details from JWT token or context
	userID := c.GetHeader("X-User-Id")
	if userID == "" {
		userID = "system"
	}
	userRole := c.GetHeader("X-User-Role")
	if userRole == "" {
		userRole = "admin" // For testing
	}

	approval, result, err := h.executor.Approve(c.Request.Context(), id, userID, userRole)
	if err != nil {
		if err == service.ErrUnauthorized {
			c.JSON(http.StatusForbidden, dto.Response{Success: false, Error: err.Error()})
			return
		}
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}

	c.JSON(http.StatusOK, dto.Response{Success: true, Data: map[string]interface{}{
		"approval": approval,
		"result":   result,
	}})
}

// @Summary Reject an approval
// @Description Reject an approval
// @Tags chatbot approval
// @Accept json
// @Produce json
// @Param id path string true "Approval ID"
// @Success 200 {object} dto.Response{data=domain.ChatbotApproval}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /chatbot/approval/{id}/reject [post]
func (h *ChatbotApprovalHandler) Reject(c *gin.Context) {
	id := c.Param("id")
	if id == "" {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "approval id required"})
		return
	}

	var req struct {
		Reason string `json:"reason"`
	}
	_ = c.ShouldBindJSON(&req)

	userID := c.GetHeader("X-User-Id")
	if userID == "" {
		userID = "system"
	}

	approval, err := h.executor.Reject(c.Request.Context(), id, userID, req.Reason)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}

	c.JSON(http.StatusOK, dto.Response{Success: true, Data: approval})
}

// @Summary List pending approvals
// @Description List pending approvals
// @Tags chatbot approval
// @Accept json
// @Produce json
// @Param id path string true "Chat ID"
// @Success 200 {object} dto.Response{data=[]domain.ChatbotApproval}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /chatbot/approval/pending [get]
func (h *ChatbotApprovalHandler) ListPending(c *gin.Context) {
	chatId := c.Param("id")
	if chatId == "" {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "chat id required"})
		return
	}

	approvals, err := h.approvalRepo.GetPendingByConversation(chatId)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}

	c.JSON(http.StatusOK, dto.Response{Success: true, Data: approvals})
}
