package service

import (
	"context"
	"emas/internal/domain"
	"emas/internal/repository"
	"encoding/json"
	"errors"
	"time"
)

var (
	ErrApprovalNotFound   = errors.New("approval not found")
	ErrApprovalNotPending = errors.New("approval is not in PENDING state")
	ErrUnauthorized       = errors.New("unauthorized to approve this action")
	ErrToolNotFound       = errors.New("tool not found in registry")
)

type ApprovalExecutor interface {
	Approve(ctx context.Context, approvalID string, userID string, userRole string) (*domain.ChatbotApproval, interface{}, error)
	Reject(ctx context.Context, approvalID string, userID string, reason string) (*domain.ChatbotApproval, error)
}

type approvalExecutor struct {
	approvalRepo repository.ChatbotApprovalRepository
	snapshotRepo ChatToolSnapshotRepository
	registry     ToolRegistry
}

func NewApprovalExecutor(
	approvalRepo repository.ChatbotApprovalRepository,
	snapshotRepo ChatToolSnapshotRepository,
	registry ToolRegistry,
) ApprovalExecutor {
	return &approvalExecutor{
		approvalRepo: approvalRepo,
		snapshotRepo: snapshotRepo,
		registry:     registry,
	}
}

func (e *approvalExecutor) Approve(ctx context.Context, approvalID string, userID string, userRole string) (*domain.ChatbotApproval, interface{}, error) {
	approval, err := e.approvalRepo.GetByID(approvalID)
	if err != nil {
		return nil, nil, ErrApprovalNotFound
	}

	// Idempotency check
	if approval.Status == "EXECUTED" {
		return approval, nil, nil // Or fetch the snapshot result if needed
	}
	if approval.Status != "PENDING" {
		return approval, nil, ErrApprovalNotPending
	}

	// Authorization check
	if err := e.checkAuth(approval.SideEffectLevel, userRole); err != nil {
		return approval, nil, err
	}

	// Get tool definition
	toolDef, ok := e.registry.Get(approval.ToolName)
	if !ok {
		return approval, nil, ErrToolNotFound
	}

	// Unmarshal args
	var args map[string]interface{}
	if err := json.Unmarshal([]byte(approval.ArgsJSON), &args); err != nil {
		return approval, nil, err
	}

	// Execute
	now := time.Now().UTC()
	approval.DecidedBy = &userID
	approval.DecidedAt = &now

	result, execErr := toolDef.Execute(ctx, args)
	
	// Create snapshot
	snapshotID := "SNAP-" + approvalID // Basic ID for now
	snapshot := &domain.ChatbotToolExecutionSnapshot{
		ID:             snapshotID,
		ConversationID: approval.ConversationID,
		TurnAuditID:    approval.TurnAuditID,
		ToolName:       toolDef.Name,
		InputJSON:      approval.ArgsJSON,
		CreatedAt:      now,
	}

	if execErr != nil {
		errStr := execErr.Error()
		approval.Status = "FAILED"
		approval.ExecutionError = &errStr
		snapshot.Success = false
		snapshot.Error = errStr
	} else {
		approval.Status = "EXECUTED"
		approval.ResultSnapshotID = &snapshotID
		snapshot.Success = true
		if resultBytes, err := json.Marshal(result); err == nil {
			snapshot.OutputJSON = string(resultBytes)
		}
	}

	// Save snapshot (if repo is available)
	if e.snapshotRepo != nil {
		_ = e.snapshotRepo.Create(snapshot)
	}

	// Update approval
	if err := e.approvalRepo.Update(approval); err != nil {
		return approval, nil, err
	}

	return approval, result, execErr
}

func (e *approvalExecutor) Reject(ctx context.Context, approvalID string, userID string, reason string) (*domain.ChatbotApproval, error) {
	approval, err := e.approvalRepo.GetByID(approvalID)
	if err != nil {
		return nil, ErrApprovalNotFound
	}

	if approval.Status != "PENDING" {
		return approval, ErrApprovalNotPending
	}

	now := time.Now().UTC()
	approval.Status = "REJECTED"
	approval.DecidedBy = &userID
	approval.DecidedAt = &now
	if reason != "" {
		approval.ExecutionError = &reason // store reason here or in a new field
	}

	if err := e.approvalRepo.Update(approval); err != nil {
		return approval, err
	}

	return approval, nil
}

func (e *approvalExecutor) checkAuth(sideEffectLevel string, role string) error {
	// e.g. LOW -> planner, manager, admin
	// HIGH/DESTRUCTIVE -> manager, admin
	if sideEffectLevel == "HIGH" || sideEffectLevel == "DESTRUCTIVE" {
		if role != "admin" && role != "manager" {
			return ErrUnauthorized
		}
	}
	return nil
}
