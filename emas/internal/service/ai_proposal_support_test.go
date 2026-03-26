package service

import (
	"emas/internal/domain"
	"testing"
)

func TestDecodeSchedulingProposalJSON_FeasibleFieldPresence(t *testing.T) {
	t.Run("present true", func(t *testing.T) {
		p, present, err := decodeSchedulingProposalJSON(`{"job_id":"JOB-1","product_id":"P-1","generated_at":"2026-01-01T00:00:00Z","feasible":true,"proposed_slots":[]}`)
		if err != nil {
			t.Fatalf("decode failed: %v", err)
		}
		if !present {
			t.Fatalf("expected feasible field to be present")
		}
		if !p.Feasible {
			t.Fatalf("expected feasible=true")
		}
	})

	t.Run("present false", func(t *testing.T) {
		p, present, err := decodeSchedulingProposalJSON(`{"job_id":"JOB-1","product_id":"P-1","generated_at":"2026-01-01T00:00:00Z","feasible":false,"proposed_slots":[]}`)
		if err != nil {
			t.Fatalf("decode failed: %v", err)
		}
		if !present {
			t.Fatalf("expected feasible field to be present")
		}
		if p.Feasible {
			t.Fatalf("expected feasible=false")
		}
	})
}

func TestDecodeProposalRecord_InferFeasibleWhenMissingField(t *testing.T) {
	svc := &AIPredictiveService{}

	t.Run("infer true when no blocked reasons", func(t *testing.T) {
		record := &domain.AIProposal{
			ProposalID:   "AIPROP-1",
			ProposalJSON: `{"job_id":"JOB-1","product_id":"P-1","generated_at":"2026-01-01T00:00:00Z","proposed_slots":[]}`,
		}
		p, err := svc.decodeProposalRecord(record)
		if err != nil {
			t.Fatalf("decode proposal failed: %v", err)
		}
		if !p.Feasible {
			t.Fatalf("expected inferred feasible=true")
		}
	})

	t.Run("infer false when blocked reasons exist", func(t *testing.T) {
		record := &domain.AIProposal{
			ProposalID:   "AIPROP-2",
			ProposalJSON: `{"job_id":"JOB-2","product_id":"P-2","generated_at":"2026-01-01T00:00:00Z","blocked_reasons":["reason_code=no_feasible_window"],"proposed_slots":[]}`,
		}
		p, err := svc.decodeProposalRecord(record)
		if err != nil {
			t.Fatalf("decode proposal failed: %v", err)
		}
		if p.Feasible {
			t.Fatalf("expected inferred feasible=false")
		}
	})
}
