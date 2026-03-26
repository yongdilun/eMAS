package service

import (
	"context"
	"emas/internal/domain"
	"errors"
)

// ProposalEngineAdapter is the canonical interface for all scheduling engines.
// Engines receive the normalised SolverPreview payload and return a proposal.
// Timeout enforcement is the caller's responsibility (via ctx).
type ProposalEngineAdapter interface {
	EngineName() string
	EngineVersion() string
	Generate(ctx context.Context, job *domain.Job, preview *SolverPreview) (*SchedulingProposal, error)
}

// ─── Preview-solver adapter ─────────────────────────────────────────────────

// PreviewSolverAdapter wraps the internal preview-solver heuristic that was
// previously called "solver". It is still useful in shadow mode.
type PreviewSolverAdapter struct {
	service *AIPredictiveService
}

func NewPreviewSolverAdapter(service *AIPredictiveService) *PreviewSolverAdapter {
	return &PreviewSolverAdapter{service: service}
}

func (a *PreviewSolverAdapter) EngineName() string    { return "preview-solver" }
func (a *PreviewSolverAdapter) EngineVersion() string { return "preview-optimizer-v2" }

func (a *PreviewSolverAdapter) Generate(ctx context.Context, job *domain.Job, preview *SolverPreview) (*SchedulingProposal, error) {
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	default:
	}
	if a.service == nil {
		return nil, errors.New("preview solver adapter is not configured")
	}
	proposal, err := a.service.buildPreviewSolverProposal(job, preview)
	if err != nil {
		return nil, err
	}
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	default:
	}
	return proposal, nil
}

// ─── Real-solver adapter ─────────────────────────────────────────────────────

// RealSolverAdapter wraps the production-grade dispatching optimizer
// (realSchedulingOptimizer) implemented in real_solver.go.
// Enable with AI_ROLLOUT_STATE=enforced-default or AI_PROPOSAL_ENGINE=real-solver.
type RealSolverAdapter struct{}

func NewRealSolverAdapter() *RealSolverAdapter { return &RealSolverAdapter{} }

func (a *RealSolverAdapter) EngineName() string    { return realSolverEngineName }
func (a *RealSolverAdapter) EngineVersion() string { return realSolverEngineVersion }

func (a *RealSolverAdapter) Generate(ctx context.Context, job *domain.Job, preview *SolverPreview) (*SchedulingProposal, error) {
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	default:
	}
	optimizer := newRealSchedulingOptimizer(job, preview)
	plans, score, err := optimizer.solve(ctx)
	if err != nil {
		return nil, err
	}
	proposal := buildRealSolverProposal(job, plans, score, optimizer.cursor)
	return proposal, nil
}
