package service

import (
	"emas/internal/domain"
	"testing"
	"time"
)

func TestHighRiskCandidateJobsLimitsBeforeExpensiveRiskEvaluation(t *testing.T) {
	now := time.Now()
	jobs := []domain.Job{
		{JobID: "JOB-LOW", Priority: domain.JobPriorityLow, Deadline: now.AddDate(0, 0, 14), Status: domain.JobStatusPlanned, QuantityTotal: 100},
		{JobID: "JOB-URGENT", Priority: domain.JobPriorityUrgent, Deadline: now.AddDate(0, 0, 14), Status: domain.JobStatusPlanned, QuantityTotal: 100},
		{JobID: "JOB-BLOCKED", Priority: domain.JobPriorityLow, Deadline: now.AddDate(0, 0, 14), Status: domain.JobStatusBlocked, QuantityTotal: 100},
	}

	got := highRiskCandidateJobs(jobs, 2)

	if len(got) != 2 {
		t.Fatalf("expected 2 candidates, got %d", len(got))
	}
	if got[0].JobID != "JOB-BLOCKED" {
		t.Fatalf("expected blocked job first, got %s", got[0].JobID)
	}
	if got[1].JobID != "JOB-URGENT" {
		t.Fatalf("expected urgent job second, got %s", got[1].JobID)
	}
	if len(jobs) != 3 || jobs[0].JobID != "JOB-LOW" {
		t.Fatalf("candidate selection mutated original jobs: %#v", jobs)
	}
}
