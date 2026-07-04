// Seed command populates MySQL with canonical demo/test data.
package main

import (
	"emas/config"
	"emas/internal/repository"
	"emas/internal/seeddata"
	"flag"
	"log"
)

func main() {
	appendOnly := flag.Bool("append", false, "upsert canonical seed data without clearing existing demo records")
	reportHistoryOnly := flag.Bool("report-history-only", false, "seed only completed historical report production data without touching active schedule fixtures")
	flag.Parse()

	cfg, err := config.Load()
	if err != nil {
		log.Fatal("config:", err)
	}
	db, err := repository.InitDB(cfg)
	if err != nil {
		log.Fatal("db:", err)
	}
	opts := seeddata.SeedOptions{Migrate: true, ValidateFingerprint: true}
	if *reportHistoryOnly {
		if err := seeddata.SeedReportProductionHistory(db, seeddata.SeedOptions{Migrate: true}); err != nil {
			log.Fatal("seed report history:", err)
		}
		return
	}
	if *appendOnly {
		if err := seeddata.SeedCanonical(db, opts); err != nil {
			log.Fatal("seed:", err)
		}
		return
	}
	if err := seeddata.ResetCanonicalDB(db, opts); err != nil {
		log.Fatal("seed:", err)
	}
}
