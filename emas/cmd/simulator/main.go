package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"math/rand"
	"os"
	"path/filepath"
	"time"

	"emas/config"
	"emas/internal/repository"
	"emas/internal/service"
)

type snapshotVectors struct {
	MachineIDs               []string  `json:"machine_ids"`
	QueueLengthsVector       []int     `json:"queue_lengths_vector"`
	MachineUtilizationVector []float64 `json:"machine_utilization_vector"`
}

type simulatedRow struct {
	Simulated bool `json:"simulated"`

	JobID      string `json:"job_id"`
	ProductID  string `json:"product_id"`
	ProposalID string `json:"proposal_id"`

	MachineID      string    `json:"machine_id"`
	ScheduledStart time.Time `json:"scheduled_start"`
	ScheduledEnd   time.Time `json:"scheduled_end"`

	MaterialShortageCount int `json:"material_shortage_count"`
	QueueLength           int `json:"queue_length"`

	SnapshotMachineIDs        []string  `json:"snapshot_machine_ids"`
	QueueLengthsVector        []int     `json:"queue_lengths_vector"`
	MachineUtilizationVector  []float64 `json:"machine_utilization_vector"`

	ActualEnd    time.Time `json:"actual_end"`
	DelayMinutes int       `json:"delay_minutes"`

	SimulationSeed int64  `json:"simulation_seed"`
	RuleVersion    string `json:"rule_version"`
}

func main() {
	var (
		targetRows = flag.Int("rows", 5000, "minimum number of JSONL rows to generate")
		outPath    = flag.String("out", filepath.Join("simulator_output", "simulated_training.jsonl"), "output JSONL path")
		seed       = flag.Int64("seed", 42, "random seed")
		orderBy    = flag.String("order_by", "readiness", "batch job ordering for proposal generation (epo/edd/fifo/readiness)")
	)
	flag.Parse()

	cfg, err := config.Load()
	if err != nil {
		panic(err)
	}
	db, err := repository.InitDB(cfg)
	if err != nil {
		panic(err)
	}
	if err := repository.AutoMigrate(db); err != nil {
		panic(err)
	}

	// Repositories
	jobRepo := repository.NewJobRepository(db)
	stepRepo := repository.NewJobStepRepository(db)
	slotRepo := repository.NewJobSlotRepository(db)
	processRepo := repository.NewProcessRepository(db)
	formulaRepo := repository.NewFormulaRepository(db)
	productRepo := repository.NewProductRepository(db)
	machineRepo := repository.NewMachineRepository(db)
	capRepo := repository.NewMachineCapabilityRepository(db)
	downtimeRepo := repository.NewMachineDowntimeRepository(db)
	maintenanceRepo := repository.NewMaintenanceRepository(db)
	bomRepo := repository.NewProductBOMRepository(db)
	invRepo := repository.NewInventoryRepository(db)
	logRepo := repository.NewProductionLogRepository(db)
	proposalRepo := repository.NewAIProposalRepository(db)
	setupRepo := repository.NewSetupRepository(db)
	resourceRepo := repository.NewResourceRepository(db)
	settingsRepo := repository.NewSystemSettingsRepository(db)
	wipRepo := repository.NewWIPRepository(db)
	psmRepo := repository.NewProcessStepMaterialRepository(db)

	// Services
	schedulingSvc := service.NewSchedulingService(productRepo, bomRepo, formulaRepo, processRepo, jobRepo, stepRepo, slotRepo, machineRepo, capRepo, downtimeRepo, maintenanceRepo, invRepo, logRepo, proposalRepo, setupRepo, resourceRepo, wipRepo, psmRepo, settingsRepo)
	jobSlotSvc := service.NewJobSlotService(slotRepo, stepRepo, processRepo, jobRepo, schedulingSvc)
	eventRepo := repository.NewSchedulingEventRepository(db)
	aiSvc := service.NewAIPredictiveService(db, jobRepo, stepRepo, slotRepo, proposalRepo, machineRepo, maintenanceRepo, settingsRepo, schedulingSvc, jobSlotSvc, eventRepo)

	jobs, err := jobRepo.ListAll()
	if err != nil {
		panic(err)
	}
	if len(jobs) == 0 {
		panic("no jobs found; run seed first (go run ./cmd/seed)")
	}

	if err := os.MkdirAll(filepath.Dir(*outPath), 0o755); err != nil {
		panic(err)
	}
	f, err := os.Create(*outPath)
	if err != nil {
		panic(err)
	}
	defer f.Close()
	w := bufio.NewWriterSize(f, 1<<20)
	defer w.Flush()

	rng := rand.New(rand.NewSource(*seed))
	rowCount := 0
	jobIdx := 0

	for rowCount < *targetRows {
		job := jobs[jobIdx%len(jobs)]
		jobIdx++

		// Generate and persist a proposal (ensures SnapshotJSON is saved).
		proposal, err := aiSvc.GenerateProposal(job.JobID, "simulator")
		if err != nil {
			continue
		}

		record, err := proposalRepo.GetByID(proposal.ProposalID)
		if err != nil || record == nil || record.SnapshotJSON == "" {
			continue
		}
		var snap snapshotVectors
		if err := json.Unmarshal([]byte(record.SnapshotJSON), &snap); err != nil {
			continue
		}
		if len(snap.MachineIDs) == 0 || len(snap.QueueLengthsVector) != len(snap.MachineIDs) || len(snap.MachineUtilizationVector) != len(snap.MachineIDs) {
			continue
		}
		indexByMachine := make(map[string]int, len(snap.MachineIDs))
		for i, mid := range snap.MachineIDs {
			indexByMachine[mid] = i
		}

		readiness, _ := schedulingSvc.CheckReadiness(job.ProductID, float64(job.QuantityTotal))
		materialShortages := 0
		if readiness != nil {
			for _, material := range readiness.Materials {
				if material.ShortageQty > 0 {
					materialShortages++
				}
			}
		}

		for _, slot := range proposal.ProposedSlots {
			if rowCount >= *targetRows {
				break
			}
			queueLen := 0
			if idx, ok := indexByMachine[slot.MachineID]; ok && idx >= 0 && idx < len(snap.QueueLengthsVector) {
				queueLen = snap.QueueLengthsVector[idx]
			}

			delay := 0
			if queueLen > 5 {
				delay += 30 + rng.Intn(31) // 30..60
			}
			if materialShortages > 0 {
				delay += 120 + rng.Intn(121) // 120..240
			}

			actualEnd := slot.ScheduledEnd.Add(time.Duration(delay) * time.Minute)
			out := simulatedRow{
				Simulated: true,

				JobID:      job.JobID,
				ProductID:  job.ProductID,
				ProposalID: proposal.ProposalID,

				MachineID:      slot.MachineID,
				ScheduledStart: slot.ScheduledStart,
				ScheduledEnd:   slot.ScheduledEnd,

				MaterialShortageCount: materialShortages,
				QueueLength:           queueLen,

				SnapshotMachineIDs:       snap.MachineIDs,
				QueueLengthsVector:       snap.QueueLengthsVector,
				MachineUtilizationVector: snap.MachineUtilizationVector,

				ActualEnd:        actualEnd,
				DelayMinutes:     delay,
				SimulationSeed:   *seed,
				RuleVersion:      fmt.Sprintf("q>5:+30..60;mshort>0:+120..240;order_by=%s", *orderBy),
			}
			b, _ := json.Marshal(out)
			_, _ = w.Write(b)
			_ = w.WriteByte('\n')
			rowCount++
		}
	}
}

