package domain

import (
	"time"
)

type ChatbotApproval struct {
	ID               string     `json:"id"`
	ConversationID   string     `json:"conversation_id"`
	TurnAuditID      string     `json:"turn_audit_id"`
	RequestID        string     `json:"request_id"`
	ToolName         string     `json:"tool_name"`
	Method           string     `json:"method"`
	Path             string     `json:"path"`
	ArgsJSON         string     `json:"args_json"`
	RiskSummary      string     `json:"risk_summary"`
	SideEffectLevel  string     `json:"side_effect_level"`
	Status           string     `json:"status"` // PENDING, APPROVED, REJECTED, EXECUTED, EXPIRED, FAILED
	IdempotencyKey   string     `json:"idempotency_key"`
	RequestedBy      string     `json:"requested_by"`
	DecidedBy        *string    `json:"decided_by"`
	DecidedAt        *time.Time `json:"decided_at"`
	ExecutionError   *string    `json:"execution_error"`
	ResultSnapshotID *string    `json:"result_snapshot_id"`
	CreatedAt        time.Time  `json:"created_at"`
}
