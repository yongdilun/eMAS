package service

import (
	"context"
	"emas/internal/domain"
	"emas/internal/handler/dto"
)

type ChatPlanner interface {
	Plan(query string, history []domain.AIChatMessage, registry ToolRegistry) (*ChatPlan, error)
	Name() string
}

type ToolRegistry interface {
	List() []ChatToolDefinition
	Get(name string) (ChatToolDefinition, bool)
}

type ReadOnlyToolExecutor interface {
	Execute(ctx context.Context, conversationID string, turnAuditID string, calls []ChatToolCall) ([]ChatToolExecutionResult, error)
}

type ConversationRepository interface {
	Create(c *domain.AIConversation) error
	GetByID(id string) (*domain.AIConversation, error)
	List(limit, offset int) ([]domain.AIConversation, error)
	Update(c *domain.AIConversation) error
}

type TurnAuditRepository interface {
	Create(audit *domain.ChatbotTurnAudit) error
	Update(audit *domain.ChatbotTurnAudit) error
}

type ChatToolSnapshotRepository interface {
	Create(snapshot *domain.ChatbotToolExecutionSnapshot) error
}

type ChatConversationService interface {
	ListConversations(limit, offset int) ([]domain.AIConversation, error)
	CreateConversation(title string) (*domain.AIConversation, error)
	GetConversation(conversationID string) (*domain.AIConversation, []domain.AIChatMessage, error)
	SendMessage(conversationID, query, requestID string) (*domain.AIChatMessage, *dto.AICommandResponse, error)
}

type ChatToolDefinition struct {
	Name            string
	Description     string
	Path            string
	Version         int
	SchemaVersion   int
	CapabilityTags  []string
	ReadOnly        bool // Deprecated by SideEffectLevel, but keep for compatibility if needed
	ConcurrencySafe bool
	Idempotent      bool
	
	// Phase 1 additions
	Method           string                                       // GET, POST, PUT, PATCH, DELETE
	SideEffectLevel  string                                       // NONE, LOW, HIGH, DESTRUCTIVE
	RequiresApproval bool                                         // Set true if Method != GET
	IdempotencyScope string                                       // "turn", "approval", "custom"
	IdempotencyKeyFn func(args map[string]interface{}) string     // Optional override
	
	InputSchema     map[string]string
	RequiredArgs    []string
	Execute         func(context.Context, map[string]interface{}) (interface{}, error)
}

type ChatToolCall struct {
	Name string                 `json:"name"`
	Args map[string]interface{} `json:"args"`
}

type ChatPlan struct {
	IntentSummary       string         `json:"intent_summary"`
	Action              string         `json:"action"`
	Confidence          float64        `json:"confidence"`
	Ambiguous           bool           `json:"ambiguous"`
	ClarificationPrompt []string       `json:"clarification_prompts,omitempty"`
	PlanExplanation     string         `json:"plan_explanation"`
	ToolCalls           []ChatToolCall `json:"tool_calls,omitempty"`
}

type ChatToolExecutionResult struct {
	Tool          ChatToolDefinition
	Call          ChatToolCall
	Output        interface{}
	LatencyMs     int
	Success       bool
	Error         string
	SuggestedCall dto.AISuggestedCall
	Source        dto.AISourceRef
}
