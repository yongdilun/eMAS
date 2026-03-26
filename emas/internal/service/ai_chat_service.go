package service

import (
	"encoding/json"
	"errors"
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/pkg/id"
	"sort"
	"strings"
	"time"
)

var ErrConversationNotFound = errors.New("conversation not found")

// AIChatService manages AI chat conversations and messages.
type AIChatService struct {
	convRepo  *repository.AIConversationRepository
	msgRepo   *repository.AIChatMessageRepository
	processor *AICommandProcessor
}

// NewAIChatService creates a new chat service.
func NewAIChatService(convRepo *repository.AIConversationRepository, msgRepo *repository.AIChatMessageRepository, processor *AICommandProcessor) *AIChatService {
	return &AIChatService{
		convRepo:  convRepo,
		msgRepo:   msgRepo,
		processor: processor,
	}
}

// ListConversations returns conversations ordered by most recently updated first.
func (s *AIChatService) ListConversations(limit, offset int) ([]domain.AIConversation, error) {
	return s.convRepo.List(limit, offset)
}

// CreateConversation creates a new conversation with optional title.
func (s *AIChatService) CreateConversation(title string) (*domain.AIConversation, error) {
	if title == "" {
		title = "New conversation"
	}
	now := time.Now().UTC()
	conv := &domain.AIConversation{
		ID:        id.New(),
		Title:     title,
		CreatedAt: now,
		UpdatedAt: now,
	}
	if err := s.convRepo.Create(conv); err != nil {
		return nil, err
	}
	// Optional: add welcome assistant message
	welcome := &domain.AIChatMessage{
		ID:             id.New(),
		ConversationID: conv.ID,
		Role:           "assistant",
		Content:        "Welcome back! How can I assist you with smart factory operations today?",
		CreatedAt:      now,
	}
	_ = s.msgRepo.Create(welcome)
	return conv, nil
}

// GetConversation returns a conversation with its messages, or ErrConversationNotFound.
func (s *AIChatService) GetConversation(conversationID string) (*domain.AIConversation, []domain.AIChatMessage, error) {
	conv, err := s.convRepo.GetByID(conversationID)
	if err != nil {
		return nil, nil, ErrConversationNotFound
	}
	msgs, err := s.msgRepo.ListByConversationID(conversationID)
	if err != nil {
		return nil, nil, err
	}
	// Ensure ascending order by created_at (oldest first); use id as tiebreaker for same-second messages
	sort.Slice(msgs, func(i, j int) bool {
		if msgs[i].CreatedAt.Before(msgs[j].CreatedAt) {
			return true
		}
		if msgs[i].CreatedAt.After(msgs[j].CreatedAt) {
			return false
		}
		return msgs[i].ID < msgs[j].ID
	})
	return conv, msgs, nil
}

// SendMessage persists the user message, calls the AI command processor, persists the assistant response, and returns both.
func (s *AIChatService) SendMessage(conversationID, query string) (*domain.AIChatMessage, *dto.AICommandResponse, error) {
	conv, err := s.convRepo.GetByID(conversationID)
	if err != nil {
		return nil, nil, ErrConversationNotFound
	}

	now := time.Now().UTC()

	// 1. Persist user message
	userMsg := &domain.AIChatMessage{
		ID:             id.New(),
		ConversationID: conversationID,
		Role:           "user",
		Content:        query,
		CreatedAt:      now,
	}
	if err := s.msgRepo.Create(userMsg); err != nil {
		return nil, nil, err
	}

	// 2. Call AI command processor with execute_readonly=true (concise, non-debug output)
	res, err := s.processor.ProcessCommand(query, true, false)
	if err != nil {
		return nil, nil, err
	}

	// 3. Persist assistant message with metadata (use current time so it sorts after user message)
	metaJSON, _ := json.Marshal(map[string]interface{}{
		"intent":         res.Intent,
		"action":         res.Action,
		"result_cards":   res.ResultCards,
		"entities":       res.Entities,
		"suggested_calls": res.SuggestedCalls,
		"bdi_result":     res.BDIResult,
	})
	assistantMsg := &domain.AIChatMessage{
		ID:             id.New(),
		ConversationID: conversationID,
		Role:           "assistant",
		Content:        res.Message,
		Metadata:       string(metaJSON),
		CreatedAt:      time.Now().UTC(),
	}
	if err := s.msgRepo.Create(assistantMsg); err != nil {
		return nil, nil, err
	}

	// 4. Update conversation updated_at and optionally title
	conv.UpdatedAt = now
	if conv.Title == "New conversation" && len(query) > 0 {
		title := strings.TrimSpace(query)
		if len(title) > 50 {
			title = title[:47] + "..."
		}
		if title != "" {
			conv.Title = title
		}
	}
	_ = s.convRepo.Update(conv)

	return assistantMsg, res, nil
}
