package schedulereval

import (
	"testing"
	"time"

	"emas/internal/service"
)

func TestEvaluateDetectsMachineOverlapAndMissingSlots(t *testing.T) {
	start := time.Date(2026, 6, 14, 8, 0, 0, 0, time.UTC)
	result := EndpointResult{
		Metadata: RunMetadata{ScenarioID: ScenarioNoShortageControl, Endpoint: EndpointBatchProposals},
		Proposals: []*service.SchedulingProposal{
			{
				ProposalID: "P1",
				JobID:      "J1",
				ProductID:  "PRD",
				Feasible:   true,
				ProposedSlots: []service.ProposedSlot{{
					JobStepID:      "J1-S1",
					StepID:         "S1",
					MachineID:      "M1",
					ScheduledStart: start,
					ScheduledEnd:   start.Add(time.Hour),
				}},
			},
			{
				ProposalID: "P2",
				JobID:      "J2",
				ProductID:  "PRD",
				Feasible:   true,
				ProposedSlots: []service.ProposedSlot{{
					JobStepID:      "J2-S1",
					StepID:         "S1",
					MachineID:      "M1",
					ScheduledStart: start.Add(30 * time.Minute),
					ScheduledEnd:   start.Add(90 * time.Minute),
				}},
			},
			{
				ProposalID:    "P3",
				JobID:         "J3",
				ProductID:     "PRD",
				Feasible:      true,
				ProposedSlots: nil,
			},
		},
	}

	score := Evaluate(result, EvaluateOptions{})

	if score.Correctness.MachineOverlapCount != 1 {
		t.Fatalf("MachineOverlapCount=%d, want 1", score.Correctness.MachineOverlapCount)
	}
	if score.Feasibility.FeasibleWithoutSlots != 1 {
		t.Fatalf("FeasibleWithoutSlots=%d, want 1", score.Feasibility.FeasibleWithoutSlots)
	}
	if len(score.Failures) != 2 {
		t.Fatalf("failures=%d, want 2: %#v", len(score.Failures), score.Failures)
	}
}

func TestEvaluateRequiresShortageEvidenceForMaterialInfeasible(t *testing.T) {
	result := EndpointResult{
		Metadata: RunMetadata{ScenarioID: ScenarioTrueMaterialShortage, Endpoint: EndpointBatchProposals},
		Proposals: []*service.SchedulingProposal{
			{
				ProposalID:     "P1",
				JobID:          "J1",
				ProductID:      "PRD",
				Feasible:       false,
				BlockedReasons: []string{"reason_code=material_shortage"},
			},
		},
	}

	score := Evaluate(result, EvaluateOptions{})

	if score.Feasibility.InfeasibleWithoutShortageEvidence != 1 {
		t.Fatalf("InfeasibleWithoutShortageEvidence=%d, want 1", score.Feasibility.InfeasibleWithoutShortageEvidence)
	}
	if len(score.Failures) == 0 {
		t.Fatalf("expected hard failure for material shortage without evidence")
	}
}

func TestEvaluateComputesQualityMetricsAndStableHash(t *testing.T) {
	start := time.Date(2026, 6, 14, 8, 0, 0, 0, time.UTC)
	deadline := start.Add(90 * time.Minute)
	done := start.Add(2 * time.Hour)
	proposals := []*service.SchedulingProposal{
		{
			ProposalID:          "volatile-id-1",
			JobID:               "J1",
			ProductID:           "P-A",
			Feasible:            true,
			EstimatedCompletion: &done,
			DeadlineStatus: &service.DeadlineStatus{
				Deadline:      deadline,
				IsLate:        true,
				TardinessMins: 30,
			},
			ProposedSlots: []service.ProposedSlot{{
				JobStepID:       "J1-S1",
				StepID:          "S1",
				MachineID:       "M1",
				ScheduledStart:  start,
				ScheduledEnd:    start.Add(time.Hour),
				QuantityPlanned: 10,
			}},
		},
		{
			ProposalID: "volatile-id-2",
			JobID:      "J2",
			ProductID:  "P-B",
			Feasible:   true,
			ProposedSlots: []service.ProposedSlot{{
				JobStepID:       "J2-S1",
				StepID:          "S1",
				MachineID:       "M1",
				ScheduledStart:  start.Add(2 * time.Hour),
				ScheduledEnd:    start.Add(3 * time.Hour),
				QuantityPlanned: 10,
			}},
		},
	}

	score := Evaluate(EndpointResult{
		Metadata:  RunMetadata{ScenarioID: ScenarioNoShortageControl, Endpoint: EndpointBatchProposals},
		Proposals: proposals,
		Summary:   &service.BatchProposalSummary{Generated: 2, Blocked: 0, OnTimeCount: 1, LateCount: 1},
		Runtime:   time.Second,
	}, EvaluateOptions{})

	if score.Quality.TotalTardinessMins != 30 {
		t.Fatalf("TotalTardinessMins=%d, want 30", score.Quality.TotalTardinessMins)
	}
	if score.Quality.MakespanMins != 180 {
		t.Fatalf("MakespanMins=%d, want 180", score.Quality.MakespanMins)
	}
	if score.Quality.SetupSwitches != 1 {
		t.Fatalf("SetupSwitches=%d, want 1", score.Quality.SetupSwitches)
	}
	if score.Performance.JobsPerSecond != 2 {
		t.Fatalf("JobsPerSecond=%f, want 2", score.Performance.JobsPerSecond)
	}

	copyWithDifferentIDs := []*service.SchedulingProposal{
		cloneProposalForHash(proposals[1], "different-2"),
		cloneProposalForHash(proposals[0], "different-1"),
	}
	if StableScheduleHash(proposals) != StableScheduleHash(copyWithDifferentIDs) {
		t.Fatalf("stable schedule hash changed when only proposal IDs/order changed")
	}
	copyWithDifferentIDs[0].ProposedSlots[0].ScheduledStart = copyWithDifferentIDs[0].ProposedSlots[0].ScheduledStart.Add(time.Minute)
	if StableScheduleHash(proposals) == StableScheduleHash(copyWithDifferentIDs) {
		t.Fatalf("stable schedule hash did not change after schedule changed")
	}
}

func TestEvaluateRecordsTopLateJobsByTardiness(t *testing.T) {
	start := time.Date(2026, 6, 14, 8, 0, 0, 0, time.UTC)
	proposal := func(jobID string, tardiness int) *service.SchedulingProposal {
		deadline := start.Add(time.Hour)
		done := deadline.Add(time.Duration(tardiness) * time.Minute)
		return &service.SchedulingProposal{
			ProposalID:          "P-" + jobID,
			JobID:               jobID,
			ProductID:           "PROD-" + jobID,
			Feasible:            true,
			EstimatedCompletion: &done,
			DeadlineStatus: &service.DeadlineStatus{
				Deadline:      deadline,
				IsLate:        tardiness > 0,
				TardinessMins: tardiness,
			},
			ProposedSlots: []service.ProposedSlot{{
				JobStepID:      jobID + "-S1",
				StepID:         "S1",
				MachineID:      "M-" + jobID,
				ScheduledStart: start,
				ScheduledEnd:   start.Add(30 * time.Minute),
			}},
		}
	}

	score := Evaluate(EndpointResult{
		Metadata: RunMetadata{ScenarioID: ScenarioCanonicalSeed, Endpoint: EndpointBatchProposals},
		Proposals: []*service.SchedulingProposal{
			proposal("J1", 30),
			proposal("J2", 120),
			proposal("J3", 60),
		},
		Runtime: time.Second,
	}, EvaluateOptions{})

	if len(score.Quality.TopLateJobs) != 3 {
		t.Fatalf("TopLateJobs=%d, want 3", len(score.Quality.TopLateJobs))
	}
	got := []string{score.Quality.TopLateJobs[0].JobID, score.Quality.TopLateJobs[1].JobID, score.Quality.TopLateJobs[2].JobID}
	want := []string{"J2", "J3", "J1"}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("TopLateJobs order=%v, want %v", got, want)
		}
	}
}

func TestValidateScenarioExpectationCatchesUnexpectedMaterialShortage(t *testing.T) {
	score := Scorecard{
		Material: MaterialMetrics{AggregateReplenishmentCount: 1, AggregateMaterialIDs: []string{"MAT-1"}},
	}
	findings := ValidateScenarioExpectation(score, ScenarioExpectation{
		ExpectNoMaterialShortage: true,
		ExpectNoAggregateRows:    true,
	})
	if len(findings) != 2 {
		t.Fatalf("findings=%d, want 2: %#v", len(findings), findings)
	}
}

func TestValidateScenarioExpectationTreatsAccelerationAsReportOnly(t *testing.T) {
	score := Scorecard{
		Material: MaterialMetrics{AggregateAccelerationCount: 1, AggregateAccelerationIDs: []string{"MAT-FAST"}},
	}
	findings := ValidateScenarioExpectation(score, ScenarioExpectation{
		ExpectNoMaterialShortage: true,
		ExpectNoAggregateRows:    true,
	})
	if len(findings) != 0 {
		t.Fatalf("optional acceleration should not trip shortage gates: %#v", findings)
	}
}

func TestApplyBaselineAttachesHashAndReportOnlyDeltas(t *testing.T) {
	current := Scorecard{
		Metadata:    RunMetadata{ScenarioID: ScenarioCanonicalSeed, Endpoint: EndpointBatchProposals},
		Performance: PerformanceMetrics{ProposalCount: 5, BlockedCount: 1, RuntimeMS: 1200},
		Quality:     QualityMetrics{LateCount: 2, TotalTardinessMins: 45},
		Stability:   StabilityMetrics{ScheduleHash: "current"},
	}
	baseline := NewReport([]Scorecard{{
		Metadata:    RunMetadata{ScenarioID: ScenarioCanonicalSeed, Endpoint: EndpointBatchProposals},
		Performance: PerformanceMetrics{ProposalCount: 4, BlockedCount: 0, RuntimeMS: 1000},
		Quality:     QualityMetrics{LateCount: 1, TotalTardinessMins: 30},
		Stability:   StabilityMetrics{ScheduleHash: "baseline"},
	}})

	applied := ApplyBaseline([]Scorecard{current}, baseline)

	if applied[0].Stability.BaselineHash != "baseline" {
		t.Fatalf("BaselineHash=%q, want baseline", applied[0].Stability.BaselineHash)
	}
	if got := applied[0].Stability.MetricDeltas["blocked_count"]; got != 1 {
		t.Fatalf("blocked_count delta=%v, want 1", got)
	}
	if got := applied[0].Stability.MetricDeltas["runtime_ms"]; got != 200 {
		t.Fatalf("runtime_ms delta=%v, want 200", got)
	}
}

func TestScoreQualityDistinguishesLargeTardinessImprovements(t *testing.T) {
	v1 := Scorecard{
		Quality:     QualityMetrics{LateCount: 10, TotalTardinessMins: 437190, MaxTardinessMins: 74400},
		Performance: PerformanceMetrics{RuntimeMS: 50000, JobsPerSecond: 0.5},
	}
	v3 := Scorecard{
		Quality:     QualityMetrics{LateCount: 10, TotalTardinessMins: 304740, MaxTardinessMins: 74400},
		Performance: PerformanceMetrics{RuntimeMS: 50000, JobsPerSecond: 0.5},
	}

	v1.RecalculateScore()
	v3.RecalculateScore()

	if v3.Score.QualityScore <= v1.Score.QualityScore {
		t.Fatalf("lower tardiness should improve quality score: v1=%#v v3=%#v", v1.Score, v3.Score)
	}
	if v3.Score.QualityScore == 0 {
		t.Fatalf("large but improved tardiness should not saturate at zero quality: %#v", v3.Score)
	}
}

func TestScoreQualityDistinguishesMaxTardinessOutliers(t *testing.T) {
	flat := Scorecard{
		Quality:     QualityMetrics{LateCount: 10, TotalTardinessMins: 304620, MaxTardinessMins: 49620},
		Performance: PerformanceMetrics{RuntimeMS: 50000, JobsPerSecond: 0.5},
	}
	outlier := Scorecard{
		Quality:     QualityMetrics{LateCount: 10, TotalTardinessMins: 304620, MaxTardinessMins: 63210},
		Performance: PerformanceMetrics{RuntimeMS: 50000, JobsPerSecond: 0.5},
	}

	flat.RecalculateScore()
	outlier.RecalculateScore()

	if flat.Score.QualityScore <= outlier.Score.QualityScore {
		t.Fatalf("lower max tardiness should improve quality score: flat=%#v outlier=%#v", flat.Score, outlier.Score)
	}
}

func cloneProposalForHash(p *service.SchedulingProposal, proposalID string) *service.SchedulingProposal {
	cp := *p
	cp.ProposalID = proposalID
	cp.ProposedSlots = append([]service.ProposedSlot(nil), p.ProposedSlots...)
	cp.BlockedReasons = append([]string(nil), p.BlockedReasons...)
	return &cp
}
