// scheduler_eval runs backend-first scheduler scorecards against the Go API
// handlers. It is intentionally separate from Factory Agent behavior.
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
	"time"

	"emas/config"
	"emas/internal/repository"
	"emas/internal/router"
	"emas/internal/schedulereval"
	"emas/internal/seeddata"
	"emas/pkg/featureflags"

	"github.com/gin-gonic/gin"
	_ "github.com/ncruces/go-sqlite3/embed"
	"github.com/ncruces/go-sqlite3/gormlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

func main() {
	gin.SetMode(gin.ReleaseMode)

	var (
		scenario          = flag.String("scenario", schedulereval.ScenarioCanonicalSeed, "scenario id to evaluate, or all")
		endpoint          = flag.String("endpoint", "both", "batch-proposals, reschedule-all, or both")
		orderBy           = flag.String("order-by", featureflags.DefaultBatchOrderBy, "scheduler ordering: epo, edd, fifo, readiness, material_priority, weighted_tardiness_material, product_deadline_fifo")
		schedulerVersion  = flag.String("scheduler-version", "", "scheduler profile to evaluate, or all; known: "+strings.Join(schedulereval.SchedulerProfileIDs(), ", "))
		compareSchedulers = flag.Bool("compare-schedulers", false, "run all known scheduler profiles on isolated scenario fixtures")
		timeout           = flag.Duration("timeout", 240*time.Second, "maximum duration per scenario")
		resetCanonical    = flag.Bool("reset-canonical", false, "reset and seed the configured DB with the canonical cmd/seed dataset before running")
		setupFixture      = flag.Bool("setup-fixture", false, "create the selected non-canonical scenario fixture through the Go API before running")
		useMemoryDB       = flag.Bool("use-memory-db", false, "run each scenario against a fresh in-memory SQLite DB; required for -scenario all")
		allowMutate       = flag.Bool("allow-mutate", false, "allow mutating evaluation steps such as one-shot material apply")
		baselineJSON      = flag.String("baseline-json", "", "optional prior JSON report/scorecard to attach report-only metric deltas")
		jsonOut           = flag.String("json-out", "", "optional path for JSON report")
		markdownOut       = flag.String("markdown-out", "", "optional path for Markdown report")
		gitSHA            = flag.String("git-sha", "", "optional git SHA to stamp into metadata")
		seedFingerprint   = flag.String("seed-fingerprint", "", "optional seed fingerprint to stamp into metadata")
	)
	flag.Parse()

	if *scenario != "all" {
		if _, ok := schedulereval.ScenarioByID(*scenario); !ok {
			log.Fatalf("unknown scenario %q; known scenarios: %s", *scenario, strings.Join(knownScenarios(), ", "))
		}
	}
	if *scenario == "all" && !*useMemoryDB {
		log.Fatalf("-scenario all requires -use-memory-db so each fixture runs isolated")
	}
	if *schedulerVersion != "" && *schedulerVersion != "all" {
		if _, ok := schedulereval.SchedulerProfileByID(*schedulerVersion); !ok {
			log.Fatalf("unknown scheduler version %q; known scheduler versions: %s", *schedulerVersion, strings.Join(knownSchedulerProfiles(), ", "))
		}
	}
	if (*compareSchedulers || *schedulerVersion == "all") && !*useMemoryDB {
		log.Fatalf("scheduler version comparison requires -use-memory-db so each scheduler profile runs isolated")
	}
	if *scenario == schedulereval.ScenarioOneShotResolution && !*allowMutate && !*useMemoryDB {
		log.Fatalf("scenario %q applies material recommendations; rerun with -allow-mutate against a disposable or explicitly approved DB", *scenario)
	}

	headers := map[string]string{
		"X-User-Id":   "scheduler-eval",
		"X-User-Role": "planner",
	}

	scorecards, err := runRequestedScenarios(runOptions{
		scenario:          *scenario,
		endpoint:          *endpoint,
		orderBy:           *orderBy,
		schedulerVersion:  *schedulerVersion,
		compareSchedulers: *compareSchedulers,
		timeout:           *timeout,
		resetCanonical:    *resetCanonical,
		setupFixture:      *setupFixture,
		useMemoryDB:       *useMemoryDB,
		allowMutate:       *allowMutate,
		gitSHA:            *gitSHA,
		seedFingerprint:   *seedFingerprint,
		headers:           headers,
	})
	if err != nil {
		log.Fatal(err)
	}

	if *baselineJSON != "" {
		data, err := os.ReadFile(*baselineJSON)
		if err != nil {
			log.Fatal("read baseline json:", err)
		}
		baseline, err := schedulereval.DecodeReport(data)
		if err != nil {
			log.Fatal("decode baseline json:", err)
		}
		scorecards = schedulereval.ApplyBaseline(scorecards, baseline)
	}

	jsonReport, err := schedulereval.MarshalJSONReport(scorecards)
	if err != nil {
		log.Fatal("marshal report:", err)
	}
	if *jsonOut != "" {
		if err := writeFileCreatingParent(*jsonOut, jsonReport); err != nil {
			log.Fatal("write json report:", err)
		}
	}
	markdown := schedulereval.MarkdownReport(scorecards)
	if *markdownOut != "" {
		if err := writeFileCreatingParent(*markdownOut, []byte(markdown)); err != nil {
			log.Fatal("write markdown report:", err)
		}
	}
	fmt.Println(markdown)

	failures := 0
	for _, score := range scorecards {
		failures += len(score.Failures)
	}
	if failures > 0 {
		os.Exit(1)
	}
}

type runOptions struct {
	scenario          string
	endpoint          string
	orderBy           string
	schedulerVersion  string
	compareSchedulers bool
	timeout           time.Duration
	resetCanonical    bool
	setupFixture      bool
	useMemoryDB       bool
	allowMutate       bool
	gitSHA            string
	seedFingerprint   string
	headers           map[string]string
}

type runScenarioOptions struct {
	scenarioID       string
	endpoint         string
	orderBy          string
	schedulerProfile string
	resetCanonical   bool
	setupFixture     bool
	allowMutate      bool
	gitSHA           string
	seedFingerprint  string
	headers          map[string]string
}

func runRequestedScenarios(opts runOptions) ([]schedulereval.Scorecard, error) {
	profiles, err := profilesToRun(opts)
	if err != nil {
		return nil, err
	}
	if opts.scenario == "all" {
		return runAllIsolated(opts, profiles)
	}
	var out []schedulereval.Scorecard
	for _, profile := range profiles {
		ctx, cancel := context.WithTimeout(context.Background(), opts.timeout)
		db, err := openEvaluationDB(opts.useMemoryDB)
		if err != nil {
			cancel()
			return nil, fmt.Errorf("db: %w", err)
		}
		scorecards, err := runScenario(ctx, db, runScenarioOptions{
			scenarioID:       opts.scenario,
			endpoint:         opts.endpoint,
			orderBy:          profile.OrderBy,
			schedulerProfile: profile.ID,
			resetCanonical:   opts.resetCanonical || (opts.useMemoryDB && opts.scenario == schedulereval.ScenarioCanonicalSeed),
			setupFixture:     opts.setupFixture || (opts.useMemoryDB && opts.scenario != schedulereval.ScenarioCanonicalSeed),
			allowMutate:      opts.allowMutate || opts.useMemoryDB,
			gitSHA:           opts.gitSHA,
			seedFingerprint:  opts.seedFingerprint,
			headers:          opts.headers,
		})
		cancel()
		if err != nil {
			return nil, err
		}
		out = append(out, scorecards...)
	}
	return out, nil
}

func runAllIsolated(opts runOptions, profiles []schedulereval.SchedulerProfileDefinition) ([]schedulereval.Scorecard, error) {
	var out []schedulereval.Scorecard
	for _, scenarioID := range schedulereval.ScenarioIDs() {
		for _, profile := range profiles {
			ctx, cancel := context.WithTimeout(context.Background(), opts.timeout)
			db, err := openEvaluationDB(true)
			if err != nil {
				cancel()
				return nil, fmt.Errorf("open isolated DB for %s/%s: %w", scenarioID, profile.ID, err)
			}
			scorecards, err := runScenario(ctx, db, runScenarioOptions{
				scenarioID:       scenarioID,
				endpoint:         opts.endpoint,
				orderBy:          profile.OrderBy,
				schedulerProfile: profile.ID,
				resetCanonical:   scenarioID == schedulereval.ScenarioCanonicalSeed,
				setupFixture:     scenarioID != schedulereval.ScenarioCanonicalSeed,
				allowMutate:      true,
				gitSHA:           opts.gitSHA,
				seedFingerprint:  seedFingerprintForScenario(scenarioID),
				headers:          opts.headers,
			})
			cancel()
			if err != nil {
				return nil, fmt.Errorf("scenario %s/%s: %w", scenarioID, profile.ID, err)
			}
			out = append(out, scorecards...)
		}
	}
	return out, nil
}

func runScenario(ctx context.Context, db *gorm.DB, opts runScenarioOptions) ([]schedulereval.Scorecard, error) {
	if opts.resetCanonical {
		if err := seeddata.ResetCanonicalDB(db, seeddata.SeedOptions{ValidateFingerprint: true}); err != nil {
			return nil, fmt.Errorf("reset canonical seed: %w", err)
		}
	}
	r := router.Setup(db)
	if opts.setupFixture {
		if _, err := schedulereval.SetupScenarioFixture(ctx, r, opts.scenarioID, opts.headers); err != nil {
			return nil, fmt.Errorf("setup scenario fixture: %w", err)
		}
	}

	runner := schedulereval.HTTPRunner{Handler: r, OrderBy: opts.orderBy, Headers: opts.headers}
	req := schedulereval.RunRequest{
		ScenarioID:              opts.scenarioID,
		SchedulerProfile:        opts.schedulerProfile,
		IncludeInventoryActions: true,
		DryRun:                  true,
		GitSHA:                  opts.gitSHA,
		SeedFingerprint:         firstNonEmpty(opts.seedFingerprint, seedFingerprintForScenario(opts.scenarioID)),
	}
	if opts.scenarioID == schedulereval.ScenarioOneShotResolution {
		if !opts.allowMutate {
			return nil, fmt.Errorf("scenario %q applies material recommendations; rerun with -allow-mutate", opts.scenarioID)
		}
		score, err := runner.RunOneShotResolution(ctx, req, schedulereval.EvaluateOptions{})
		if err != nil {
			return nil, fmt.Errorf("run one-shot resolution: %w", err)
		}
		return []schedulereval.Scorecard{score}, nil
	}

	var out []schedulereval.Scorecard
	for _, ep := range endpointsToRun(opts.endpoint) {
		req.Endpoint = ep
		score, err := runner.RunScorecard(ctx, req, schedulereval.EvaluateOptions{})
		if err != nil {
			return nil, fmt.Errorf("run %s: %w", ep, err)
		}
		out = append(out, score)
	}
	return out, nil
}

func profilesToRun(opts runOptions) ([]schedulereval.SchedulerProfileDefinition, error) {
	if opts.compareSchedulers || opts.schedulerVersion == "all" {
		return schedulereval.SchedulerProfiles(), nil
	}
	if strings.TrimSpace(opts.schedulerVersion) != "" {
		profile, ok := schedulereval.SchedulerProfileByID(opts.schedulerVersion)
		if !ok {
			return nil, fmt.Errorf("unknown scheduler version %q", opts.schedulerVersion)
		}
		return []schedulereval.SchedulerProfileDefinition{profile}, nil
	}
	return []schedulereval.SchedulerProfileDefinition{{
		ID:      "",
		OrderBy: opts.orderBy,
	}}, nil
}

func openEvaluationDB(useMemory bool) (*gorm.DB, error) {
	if useMemory {
		db, err := gorm.Open(gormlite.Open(fmt.Sprintf("file:scheduler_eval_%d?mode=memory&cache=shared", time.Now().UnixNano())), &gorm.Config{
			Logger: logger.Default.LogMode(logger.Silent),
		})
		if err != nil {
			return nil, err
		}
		sqlDB, err := db.DB()
		if err != nil {
			return nil, err
		}
		sqlDB.SetMaxOpenConns(1)
		sqlDB.SetMaxIdleConns(1)
		if err := repository.AutoMigrate(db); err != nil {
			return nil, err
		}
		return db, nil
	}
	cfg, err := config.Load()
	if err != nil {
		return nil, fmt.Errorf("config: %w", err)
	}
	return repository.InitDB(cfg)
}

func endpointsToRun(endpoint string) []string {
	switch endpoint {
	case "", "both":
		return []string{schedulereval.EndpointBatchProposals, schedulereval.EndpointRescheduleAll}
	case schedulereval.EndpointBatchProposals, schedulereval.EndpointRescheduleAll:
		return []string{endpoint}
	default:
		log.Fatalf("unknown endpoint %q; use batch-proposals, reschedule-all, or both", endpoint)
	}
	return nil
}

func knownScenarios() []string {
	return append([]string{"all"}, schedulereval.ScenarioIDs()...)
}

func knownSchedulerProfiles() []string {
	return append([]string{"all"}, schedulereval.SchedulerProfileIDs()...)
}

func seedFingerprintForScenario(scenarioID string) string {
	if scenarioID == schedulereval.ScenarioCanonicalSeed {
		return "canonical-seed-v1"
	}
	return "scheduler-eval-fixture-v1:" + scenarioID
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func writeFileCreatingParent(path string, data []byte) error {
	dir := filepath.Dir(path)
	if dir != "." && dir != "" {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return err
		}
	}
	return os.WriteFile(path, data, 0o644)
}
