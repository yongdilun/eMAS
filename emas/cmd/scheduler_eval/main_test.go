package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"emas/internal/schedulereval"
)

func TestRunRequestedScenariosUsesMemoryFixture(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "60000")

	scorecards, err := runRequestedScenarios(runOptions{
		scenario:    schedulereval.ScenarioNoShortageControl,
		endpoint:    schedulereval.EndpointBatchProposals,
		orderBy:     "epo",
		timeout:     90 * time.Second,
		useMemoryDB: true,
		headers: map[string]string{
			"X-User-Id":   "scheduler-eval-test",
			"X-User-Role": "planner",
		},
	})
	if err != nil {
		t.Fatalf("run requested scenario: %v", err)
	}
	if len(scorecards) != 1 {
		t.Fatalf("scorecards=%d, want 1", len(scorecards))
	}
	score := scorecards[0]
	if len(score.Failures) > 0 {
		t.Fatalf("unexpected hard failures: %#v", score.Failures)
	}
	if !score.Score.HardGatePassed {
		t.Fatalf("hard gate should pass: %#v", score.Score)
	}
	if score.Feasibility.FeasibleJobs != 2 || score.Feasibility.InfeasibleJobs != 0 {
		t.Fatalf("unexpected feasibility metrics: %#v", score.Feasibility)
	}
}

func TestWriteFileCreatingParent(t *testing.T) {
	target := filepath.Join(t.TempDir(), "nested", "report.json")
	if err := writeFileCreatingParent(target, []byte(`{"ok":true}`)); err != nil {
		t.Fatalf("write file creating parent: %v", err)
	}
	data, err := os.ReadFile(target)
	if err != nil {
		t.Fatalf("read written file: %v", err)
	}
	if string(data) != `{"ok":true}` {
		t.Fatalf("written data=%q", data)
	}
}

func TestRunRequestedScenariosComparesSchedulerVersions(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "60000")

	scorecards, err := runRequestedScenarios(runOptions{
		scenario:          schedulereval.ScenarioNoShortageControl,
		endpoint:          schedulereval.EndpointBatchProposals,
		schedulerVersion:  "all",
		timeout:           90 * time.Second,
		useMemoryDB:       true,
		compareSchedulers: true,
		headers: map[string]string{
			"X-User-Id":   "scheduler-eval-test",
			"X-User-Role": "planner",
		},
	})
	if err != nil {
		t.Fatalf("run version comparison: %v", err)
	}
	if len(scorecards) != len(schedulereval.SchedulerProfiles()) {
		t.Fatalf("scorecards=%d, want %d", len(scorecards), len(schedulereval.SchedulerProfiles()))
	}
	seen := map[string]bool{}
	for _, score := range scorecards {
		seen[score.Metadata.SchedulerProfile] = true
		if len(score.Failures) > 0 {
			t.Fatalf("%s hard failures: %#v", score.Metadata.SchedulerProfile, score.Failures)
		}
	}
	if !seen[schedulereval.SchedulerProfileV1Current] ||
		!seen[schedulereval.SchedulerProfileV2MaterialAwarePriority] ||
		!seen[schedulereval.SchedulerProfileV3WeightedTardiness] ||
		!seen[schedulereval.SchedulerProfileV4ProductDeadlineFIFO] {
		t.Fatalf("missing scheduler profiles in scorecards: %v", seen)
	}
	report := schedulereval.NewReport(scorecards)
	expectedDiffs := len(schedulereval.SchedulerProfiles()) - 1
	if len(report.VersionDiffs) != expectedDiffs {
		t.Fatalf("version diffs=%d, want %d: %#v", len(report.VersionDiffs), expectedDiffs, report.VersionDiffs)
	}
	diff := report.VersionDiffs[0]
	if diff.LeftSchedulerProfile != schedulereval.SchedulerProfileV1Current {
		t.Fatalf("unexpected version diff profiles: %#v", diff)
	}
}
