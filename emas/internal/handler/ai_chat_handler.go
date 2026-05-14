package handler

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/middleware"
	"emas/internal/service"
	"encoding/json"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
)

type AIChatHandler struct {
	chatService service.ChatConversationService
}

// NewAIChatHandler creates a new AI chat handler.
func NewAIChatHandler(chatService service.ChatConversationService) *AIChatHandler {
	return &AIChatHandler{chatService: chatService}
}

// @Summary List all conversations
// @Description List all conversations
// @Tags ai chats
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=[]domain.AIConversation}
// @Failure 500 {object} dto.Response
// @Router /ai/chats [get]
type CreateConversationRequest struct {
	Title string `json:"title"`
}

// @Summary Create a new conversation
// @Description Create a new conversation
// @Tags ai chats
// @Accept json
// @Produce json
// @Param request body CreateConversationRequest true "Create Conversation Request"
// @Success 201 {object} dto.Response{data=domain.AIConversation}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/chats [post]
type SendMessageRequest struct {
	Query string `json:"query" binding:"required"`
}

// @Summary Send a message to a conversation
// @Description Send a message to a conversation
// @Tags ai chats
// @Accept json
// @Produce json
// @Param id path string true "Conversation ID"
// @Param request body SendMessageRequest true "Send Message Request"
// @Success 200 {object} dto.Response{data=domain.AIChatMessage}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/chats/{id}/messages [post]

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

// @Summary Create a new conversation
// @Description Create a new conversation
// @Tags ai chats
// @Accept json
// @Produce json
// @Param request body CreateConversationRequest true "Create Conversation Request"
// @Success 201 {object} dto.Response{data=domain.AIConversation}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/chats [post]

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

// @Summary Get a conversation by ID
// @Description Get a conversation by ID. Supports optional field selection.
// @Tags ai chats
// @Accept json
// @Produce json
// @Param id path string true "Conversation ID"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=domain.AIConversation}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/chats/{id} [get]

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

// @Summary Send a message to a conversation
// @Description Send a message to a conversation
// @Tags ai chats
// @Accept json
// @Produce json
// @Param id path string true "Conversation ID"
// @Param request body SendMessageRequest true "Send Message Request"
// @Success 200 {object} dto.Response{data=domain.AIChatMessage}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/chats/{id}/messages [post]

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

	requestID := ""
	if v, ok := c.Get(middleware.ContextRequestIDKey); ok {
		if s, ok := v.(string); ok {
			requestID = s
		}
	}
	_, res, err := h.chatService.SendMessage(id, query, requestID)
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

// @Summary Convert a conversation to a response
// @Description Convert a conversation to a response
// @Tags ai chats
// @Accept json
// @Produce json
// @Param conv body domain.AIConversation true "Conversation"
// @Param msgs body []domain.AIChatMessage true "Messages"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/chats/{id}/messages [post]

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
				// Optional unified turn/UI metadata (best-effort passthrough)
				for _, key := range []string{
					"turn_id",
					"human_message",
					"message_kind",
					"status_label",
					"execution_mode",
					"suggested_calls",
					"guidance",
					"clarifications",
					"ambiguous",
					"confidence",
					"entities",
					"ui_blocks",
				} {
					if v, ok := meta[key]; ok {
						msg[key] = v
					}
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
