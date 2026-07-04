package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"time"

	"emas/config"
	"emas/internal/repository"
	"emas/internal/service"

	"gorm.io/gorm"
)

func main() {
	var (
		dryRun    = flag.Bool("dry-run", false, "show due slots without writing production logs")
		asOfText  = flag.String("as-of", "", "catch up slots due at or before this RFC3339 time; defaults to now")
		jobPrefix = flag.String("job-prefix", "", "optional job_id prefix filter")
	)
	flag.Parse()

	asOf := time.Now().UTC()
	if *asOfText != "" {
		parsed, err := time.Parse(time.RFC3339, *asOfText)
		if err != nil {
			log.Fatalf("invalid -as-of: %v", err)
		}
		asOf = parsed.UTC()
	}

	cfg, err := config.Load()
	if err != nil {
		log.Fatal("config:", err)
	}
	db, err := repository.InitDB(cfg)
	if err != nil {
		log.Fatal("db:", err)
	}
	if cfg.AutoMigrate {
		if err := repository.AutoMigrate(db); err != nil {
			log.Fatal("migrate:", err)
		}
	}

	catchUp := service.NewProductionCatchUpService(db, productionLogService(db))
	result, err := catchUp.CatchUpDueSlots(service.ProductionCatchUpOptions{
		AsOf:      asOf,
		JobPrefix: *jobPrefix,
		DryRun:    *dryRun,
	})
	if err != nil {
		_ = json.NewEncoder(os.Stdout).Encode(result)
		log.Fatal(err)
	}
	out, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		log.Fatal("encode result:", err)
	}
	fmt.Println(string(out))
}

func productionLogService(db *gorm.DB) *service.ProductionLogService {
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
	trainingRepo := repository.NewMLTrainingEventRepository(db)
	resourceRepo := repository.NewResourceRepository(db)
	wipRepo := repository.NewWIPRepository(db)
	psmRepo := repository.NewProcessStepMaterialRepository(db)
	settingsRepo := repository.NewSystemSettingsRepository(db)
	schedulingSvc := service.NewSchedulingService(productRepo, bomRepo, formulaRepo, processRepo, jobRepo, stepRepo, slotRepo, machineRepo, capRepo, downtimeRepo, maintenanceRepo, invRepo, logRepo, proposalRepo, setupRepo, trainingRepo, resourceRepo, wipRepo, psmRepo, settingsRepo)
	return service.NewProductionLogService(db, logRepo, slotRepo, stepRepo, jobRepo, proposalRepo, schedulingSvc)
}
