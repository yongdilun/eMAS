package schedulereval

import (
	"bytes"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
)

type Report struct {
	SchemaVersion int           `json:"schema_version"`
	Summary       ReportSummary `json:"summary"`
	Scorecards    []Scorecard   `json:"scorecards"`
	Diffs         []RunDiff     `json:"diffs,omitempty"`
	VersionDiffs  []RunDiff     `json:"version_diffs,omitempty"`
}

type ReportSummary struct {
	ScenarioCount       int     `json:"scenario_count"`
	ScorecardCount      int     `json:"scorecard_count"`
	HardFailureCount    int     `json:"hard_failure_count"`
	WarningCount        int     `json:"warning_count"`
	AverageOverallScore float64 `json:"average_overall_score"`
	AverageQualityScore float64 `json:"average_quality_score"`
	WorstOverallScore   float64 `json:"worst_overall_score"`
	WorstScorecard      string  `json:"worst_scorecard,omitempty"`
}

type RunDiff struct {
	ScenarioID            string             `json:"scenario_id"`
	LeftEndpoint          string             `json:"left_endpoint"`
	RightEndpoint         string             `json:"right_endpoint"`
	LeftSchedulerProfile  string             `json:"left_scheduler_profile,omitempty"`
	RightSchedulerProfile string             `json:"right_scheduler_profile,omitempty"`
	ScheduleHashEqual     bool               `json:"schedule_hash_equal"`
	MetricDeltas          map[string]float64 `json:"metric_deltas,omitempty"`
	LeftFailureCount      int                `json:"left_failure_count"`
	RightFailureCount     int                `json:"right_failure_count"`
	LeftBlockedCount      int                `json:"left_blocked_count"`
	RightBlockedCount     int                `json:"right_blocked_count"`
	LeftProposalCount     int                `json:"left_proposal_count"`
	RightProposalCount    int                `json:"right_proposal_count"`
}

func NewReport(scorecards []Scorecard) Report {
	return Report{SchemaVersion: 1, Summary: summarizeScorecards(scorecards), Scorecards: scorecards, Diffs: EndpointDiffs(scorecards), VersionDiffs: VersionDiffs(scorecards)}
}

func MarshalJSONReport(scorecards []Scorecard) ([]byte, error) {
	report := NewReport(scorecards)
	return json.MarshalIndent(report, "", "  ")
}

func MarkdownReport(scorecards []Scorecard) string {
	report := NewReport(scorecards)
	var b bytes.Buffer
	b.WriteString("# Scheduler Evaluation Report\n\n")
	fmt.Fprintf(&b, "- Scorecards: `%d`\n", report.Summary.ScorecardCount)
	fmt.Fprintf(&b, "- Hard failures: `%d`, warnings: `%d`\n", report.Summary.HardFailureCount, report.Summary.WarningCount)
	fmt.Fprintf(&b, "- Average overall score: `%.2f`, average quality score: `%.2f`\n", report.Summary.AverageOverallScore, report.Summary.AverageQualityScore)
	if report.Summary.WorstScorecard != "" {
		fmt.Fprintf(&b, "- Worst scorecard: `%s` at `%.2f`\n", report.Summary.WorstScorecard, report.Summary.WorstOverallScore)
	}
	b.WriteString("\n")
	for _, score := range report.Scorecards {
		title := score.Metadata.ScenarioID + " / " + score.Metadata.Endpoint
		if score.Metadata.SchedulerProfile != "" {
			title += " / " + score.Metadata.SchedulerProfile
		}
		fmt.Fprintf(&b, "## %s\n\n", title)
		fmt.Fprintf(&b, "- Generated: `%s`\n", score.Metadata.Timestamp.Format("2006-01-02T15:04:05Z07:00"))
		if score.Metadata.SchedulerProfile != "" {
			fmt.Fprintf(&b, "- Scheduler profile: `%s`\n", score.Metadata.SchedulerProfile)
		}
		fmt.Fprintf(&b, "- Engine: `%s` `%s`\n", emptyDash(score.Metadata.SchedulerEngine), emptyDash(score.Metadata.SchedulerVersion))
		fmt.Fprintf(&b, "- Runtime: `%d ms`\n", score.Performance.RuntimeMS)
		fmt.Fprintf(&b, "- Score: overall `%.2f`, correctness `%.2f`, quality `%.2f`, performance `%.2f`, hard_gate_passed=`%t`\n", score.Score.OverallScore, score.Score.CorrectnessScore, score.Score.QualityScore, score.Score.PerformanceScore, score.Score.HardGatePassed)
		fmt.Fprintf(&b, "- Proposals: `%d`, blocked: `%d`, feasible: `%d`, infeasible: `%d`\n", score.Performance.ProposalCount, score.Performance.BlockedCount, score.Feasibility.FeasibleJobs, score.Feasibility.InfeasibleJobs)
		fmt.Fprintf(&b, "- Hard failures: `%d`, warnings: `%d`\n", len(score.Failures), len(score.Warnings))
		fmt.Fprintf(&b, "- Schedule hash: `%s`\n", score.Stability.ScheduleHash)
		fmt.Fprintf(&b, "- Quality: on-time `%d`, late `%d`, total tardiness `%d min`, makespan `%d min`, utilization `%.2f%%`\n\n", score.Quality.OnTimeCount, score.Quality.LateCount, score.Quality.TotalTardinessMins, score.Quality.MakespanMins, score.Quality.MachineUtilizationPct)
		if len(score.Quality.TopLateJobs) > 0 {
			b.WriteString("- Top late jobs:")
			limit := len(score.Quality.TopLateJobs)
			if limit > 5 {
				limit = 5
			}
			for i := 0; i < limit; i++ {
				job := score.Quality.TopLateJobs[i]
				product := job.ProductID
				if product == "" {
					product = "-"
				}
				fmt.Fprintf(&b, " `%s` (%s, %d min)", job.JobID, product, job.TardinessMins)
				if i < limit-1 {
					b.WriteString(",")
				}
			}
			b.WriteString("\n\n")
		}
		if len(score.Material.AggregateMaterialIDs) > 0 {
			fmt.Fprintf(&b, "- Material aggregate rows: `%s`\n\n", strings.Join(score.Material.AggregateMaterialIDs, ", "))
		}
		if len(score.Material.AggregateAccelerationIDs) > 0 {
			fmt.Fprintf(&b, "- Optional acceleration rows: `%s`\n\n", strings.Join(score.Material.AggregateAccelerationIDs, ", "))
		}
		writeFindings(&b, "Failures", score.Failures)
		writeFindings(&b, "Warnings", score.Warnings)
	}
	if len(report.Diffs) > 0 {
		b.WriteString("## Endpoint Diffs\n\n")
		for _, diff := range report.Diffs {
			profile := firstNonEmpty(diff.LeftSchedulerProfile, "-")
			fmt.Fprintf(&b, "- `%s` / `%s`: `%s` vs `%s`, hash_equal=`%t`, blocked `%d -> %d`, proposals `%d -> %d`, failures `%d -> %d`\n",
				diff.ScenarioID,
				profile,
				diff.LeftEndpoint,
				diff.RightEndpoint,
				diff.ScheduleHashEqual,
				diff.LeftBlockedCount,
				diff.RightBlockedCount,
				diff.LeftProposalCount,
				diff.RightProposalCount,
				diff.LeftFailureCount,
				diff.RightFailureCount,
			)
		}
		b.WriteString("\n")
	}
	if len(report.VersionDiffs) > 0 {
		b.WriteString("## Scheduler Version Diffs\n\n")
		for _, diff := range report.VersionDiffs {
			fmt.Fprintf(&b, "- `%s` / `%s`: `%s` vs `%s`, hash_equal=`%t`, late `%+.0f`, tardiness `%+.0f min`, max tardiness `%+.0f min`, quality `%+.2f`, overall `%+.2f`, failures `%d -> %d`\n",
				diff.ScenarioID,
				diff.LeftEndpoint,
				diff.LeftSchedulerProfile,
				diff.RightSchedulerProfile,
				diff.ScheduleHashEqual,
				diff.MetricDeltas["late_count"],
				diff.MetricDeltas["total_tardiness_mins"],
				diff.MetricDeltas["max_tardiness_mins"],
				diff.MetricDeltas["quality_score"],
				diff.MetricDeltas["overall_score"],
				diff.LeftFailureCount,
				diff.RightFailureCount,
			)
		}
		b.WriteString("\n")
	}
	return b.String()
}

func summarizeScorecards(scorecards []Scorecard) ReportSummary {
	out := ReportSummary{ScorecardCount: len(scorecards)}
	if len(scorecards) == 0 {
		return out
	}
	scenarios := map[string]struct{}{}
	var overallTotal, qualityTotal float64
	worstScore := 101.0
	for _, score := range scorecards {
		scenarios[score.Metadata.ScenarioID] = struct{}{}
		out.HardFailureCount += len(score.Failures)
		out.WarningCount += len(score.Warnings)
		overallTotal += score.Score.OverallScore
		qualityTotal += score.Score.QualityScore
		if score.Score.OverallScore < worstScore {
			worstScore = score.Score.OverallScore
			out.WorstOverallScore = score.Score.OverallScore
			out.WorstScorecard = score.Metadata.ScenarioID + "/" + score.Metadata.Endpoint + profileSuffix(score.Metadata.SchedulerProfile)
		}
	}
	out.ScenarioCount = len(scenarios)
	out.AverageOverallScore = round2(overallTotal / float64(len(scorecards)))
	out.AverageQualityScore = round2(qualityTotal / float64(len(scorecards)))
	return out
}

func EndpointDiffs(scorecards []Scorecard) []RunDiff {
	byScenario := map[string][]Scorecard{}
	for _, score := range scorecards {
		key := score.Metadata.ScenarioID + "\x00" + score.Metadata.SchedulerProfile
		byScenario[key] = append(byScenario[key], score)
	}
	diffs := make([]RunDiff, 0)
	for _, scores := range byScenario {
		if len(scores) < 2 {
			continue
		}
		sort.SliceStable(scores, func(i, j int) bool {
			return scores[i].Metadata.Endpoint < scores[j].Metadata.Endpoint
		})
		left, right := scores[0], scores[1]
		diffs = append(diffs, RunDiff{
			ScenarioID:            left.Metadata.ScenarioID,
			LeftEndpoint:          left.Metadata.Endpoint,
			RightEndpoint:         right.Metadata.Endpoint,
			LeftSchedulerProfile:  left.Metadata.SchedulerProfile,
			RightSchedulerProfile: right.Metadata.SchedulerProfile,
			ScheduleHashEqual:     left.Stability.ScheduleHash == right.Stability.ScheduleHash,
			MetricDeltas:          metricDeltas(left, right),
			LeftFailureCount:      len(left.Failures),
			RightFailureCount:     len(right.Failures),
			LeftBlockedCount:      left.Performance.BlockedCount,
			RightBlockedCount:     right.Performance.BlockedCount,
			LeftProposalCount:     left.Performance.ProposalCount,
			RightProposalCount:    right.Performance.ProposalCount,
		})
	}
	sort.SliceStable(diffs, func(i, j int) bool {
		if diffs[i].ScenarioID != diffs[j].ScenarioID {
			return diffs[i].ScenarioID < diffs[j].ScenarioID
		}
		return diffs[i].LeftSchedulerProfile < diffs[j].LeftSchedulerProfile
	})
	return diffs
}

func VersionDiffs(scorecards []Scorecard) []RunDiff {
	byScenarioEndpoint := map[string][]Scorecard{}
	for _, score := range scorecards {
		if score.Metadata.SchedulerProfile == "" {
			continue
		}
		key := score.Metadata.ScenarioID + "\x00" + score.Metadata.Endpoint
		byScenarioEndpoint[key] = append(byScenarioEndpoint[key], score)
	}
	diffs := make([]RunDiff, 0)
	for _, scores := range byScenarioEndpoint {
		if len(scores) < 2 {
			continue
		}
		sort.SliceStable(scores, func(i, j int) bool {
			return schedulerProfileRank(scores[i].Metadata.SchedulerProfile) < schedulerProfileRank(scores[j].Metadata.SchedulerProfile)
		})
		left := scores[0]
		for _, right := range scores[1:] {
			diffs = append(diffs, RunDiff{
				ScenarioID:            left.Metadata.ScenarioID,
				LeftEndpoint:          left.Metadata.Endpoint,
				RightEndpoint:         right.Metadata.Endpoint,
				LeftSchedulerProfile:  left.Metadata.SchedulerProfile,
				RightSchedulerProfile: right.Metadata.SchedulerProfile,
				ScheduleHashEqual:     left.Stability.ScheduleHash == right.Stability.ScheduleHash,
				MetricDeltas:          metricDeltas(left, right),
				LeftFailureCount:      len(left.Failures),
				RightFailureCount:     len(right.Failures),
				LeftBlockedCount:      left.Performance.BlockedCount,
				RightBlockedCount:     right.Performance.BlockedCount,
				LeftProposalCount:     left.Performance.ProposalCount,
				RightProposalCount:    right.Performance.ProposalCount,
			})
		}
	}
	sort.SliceStable(diffs, func(i, j int) bool {
		if diffs[i].ScenarioID != diffs[j].ScenarioID {
			return diffs[i].ScenarioID < diffs[j].ScenarioID
		}
		return diffs[i].LeftEndpoint < diffs[j].LeftEndpoint
	})
	return diffs
}

func schedulerProfileRank(profile string) int {
	for i, known := range SchedulerProfiles() {
		if known.ID == profile {
			return i
		}
	}
	return len(SchedulerProfiles()) + 1
}

func metricDeltas(left, right Scorecard) map[string]float64 {
	return map[string]float64{
		"blocked_count":           float64(right.Performance.BlockedCount - left.Performance.BlockedCount),
		"proposal_count":          float64(right.Performance.ProposalCount - left.Performance.ProposalCount),
		"runtime_ms":              float64(right.Performance.RuntimeMS - left.Performance.RuntimeMS),
		"late_count":              float64(right.Quality.LateCount - left.Quality.LateCount),
		"total_tardiness_mins":    float64(right.Quality.TotalTardinessMins - left.Quality.TotalTardinessMins),
		"max_tardiness_mins":      float64(right.Quality.MaxTardinessMins - left.Quality.MaxTardinessMins),
		"overall_score":           right.Score.OverallScore - left.Score.OverallScore,
		"quality_score":           right.Score.QualityScore - left.Score.QualityScore,
		"machine_overlap_count":   float64(right.Correctness.MachineOverlapCount - left.Correctness.MachineOverlapCount),
		"aggregate_material_rows": float64(right.Material.AggregateReplenishmentCount - left.Material.AggregateReplenishmentCount),
		"acceleration_rows":       float64(right.Material.AggregateAccelerationCount - left.Material.AggregateAccelerationCount),
	}
}

func profileSuffix(profile string) string {
	if profile == "" {
		return ""
	}
	return "/" + profile
}

func writeFindings(b *bytes.Buffer, title string, findings []Finding) {
	if len(findings) == 0 {
		return
	}
	fmt.Fprintf(b, "### %s\n\n", title)
	for _, f := range findings {
		target := firstNonEmpty(f.JobID, f.MaterialID, f.MachineID, f.StepID)
		if target != "" {
			fmt.Fprintf(b, "- `%s` `%s`: %s\n", f.Code, target, f.Message)
		} else {
			fmt.Fprintf(b, "- `%s`: %s\n", f.Code, f.Message)
		}
	}
	b.WriteString("\n")
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

func emptyDash(value string) string {
	if value == "" {
		return "-"
	}
	return value
}
