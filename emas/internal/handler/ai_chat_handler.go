package handler

import (
	"encoding/json"
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/service"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
)

type AIChatHandler struct {
	chatService *service.AIChatService
}

// NewAIChatHandler creates a new AI chat handler.
func NewAIChatHandler(chatService *service.AIChatService) *AIChatHandler {
	return &AIChatHandler{chatService: chatService}
}

// CreateConversationRequest is the optional body for POST /ai/chats.
type CreateConversationRequest struct {
	Title string `json:"title"`
}

// SendMessageRequest is the body for POST /ai/chats/:id/messages.
type SendMessageRequest struct {
	Query string `json:"query" binding:"required"`
}

// List returns all conversations, most recent first.
func (h *AIChatHandler) List(c *gin.Context) {
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "50"))
	offset, _ := strconv.Atoi(c.DefaultQuery("offset", "0"))
	if limit <= 0 {
		limit = 50
	}
	if limit > 100 {
		limit = 100
	}

	list, err := h.chatService.ListConversations(limit, offset)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: list})
}

// Create creates a new conversation.
func (h *AIChatHandler) Create(c *gin.Context) {
	var req CreateConversationRequest
	_ = c.ShouldBindJSON(&req)

	conv, err := h.chatService.CreateConversation(req.Title)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: conv})
}

// Get returns a conversation with its messages.
func (h *AIChatHandler) Get(c *gin.Context) {
	id := c.Param("id")
	if id == "" {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "conversation id required"})
		return
	}

	conv, msgs, err := h.chatService.GetConversation(id)
	if err != nil {
		if err == service.ErrConversationNotFound {
			c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: "conversation not found"})
			return
		}
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}

	resp := toConversationResponse(conv, msgs)
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: resp})
}

// SendMessage sends a user message, invokes AI, persists both, and returns the assistant response.
func (h *AIChatHandler) SendMessage(c *gin.Context) {
	id := c.Param("id")
	if id == "" {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "conversation id required"})
		return
	}

	var req SendMessageRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	query := strings.TrimSpace(req.Query)
	if query == "" {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "query is required and cannot be empty"})
		return
	}

	_, res, err := h.chatService.SendMessage(id, query)
	if err != nil {
		if err == service.ErrConversationNotFound {
			c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: "conversation not found"})
			return
		}
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}

	// Response shape matches POST /ai/command per spec
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: res})
}

func toConversationResponse(conv *domain.AIConversation, msgs []domain.AIChatMessage) map[string]interface{} {
	messageList := make([]map[string]interface{}, 0, len(msgs))
	for _, m := range msgs {
		msg := map[string]interface{}{
			"id":        m.ID,
			"role":      m.Role,
			"content":   m.Content,
			"timestamp": m.CreatedAt.Format("2006-01-02T15:04:05Z07:00"),
		}
		if m.Metadata != "" {
			var meta map[string]interface{}
			if err := json.Unmarshal([]byte(m.Metadata), &meta); err == nil {
				if intent, ok := meta["intent"]; ok {
					msg["intent"] = intent
				}
				if cards, ok := meta["result_cards"]; ok {
					msg["result_cards"] = cards
				}
			}
		}
		messageList = append(messageList, msg)
	}
	return map[string]interface{}{
		"id":         conv.ID,
		"title":      conv.Title,
		"created_at": conv.CreatedAt.Format("2006-01-02T15:04:05Z07:00"),
		"updated_at": conv.UpdatedAt.Format("2006-01-02T15:04:05Z07:00"),
		"messages":   messageList,
	}
}

