package main

import (
	"emas/internal/repository"
	"emas/internal/router"
	"emas/internal/seeddata"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sync"

	"github.com/gin-gonic/gin"
	_ "github.com/ncruces/go-sqlite3/embed"
	"github.com/ncruces/go-sqlite3/gormlite"
	"gorm.io/gorm"
)

func main() {
	addr := env("E2E_SERVER_ADDR", "127.0.0.1:18080")
	dbPath := env("E2E_SQLITE_PATH", filepath.Join(os.TempDir(), "emas-e2e-server.db"))
	if dbPath != ":memory:" {
		_ = os.Remove(dbPath)
	}

	db, err := gorm.Open(gormlite.Open(dbPath), &gorm.Config{})
	if err != nil {
		log.Fatalf("open e2e sqlite db: %v", err)
	}
	sqlDB, err := db.DB()
	if err != nil {
		log.Fatalf("open e2e sql db: %v", err)
	}
	sqlDB.SetMaxOpenConns(1)
	sqlDB.SetMaxIdleConns(1)

	if err := repository.AutoMigrate(db); err != nil {
		log.Fatalf("migrate e2e db: %v", err)
	}
	if err := seeddata.SeedCanonical(db, seeddata.SeedOptions{ValidateFingerprint: true}); err != nil {
		log.Fatalf("seed canonical e2e db: %v", err)
	}

	r := router.Setup(db)
	var resetMu sync.Mutex
	resetHandler := func(c *gin.Context) {
		resetMu.Lock()
		defer resetMu.Unlock()
		if err := resetCanonicalE2EDB(db); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, gin.H{"status": "ok", "seed": "canonical"})
	}
	r.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok", "seed": "canonical"})
	})
	r.POST("/__e2e/reset", resetHandler)
	r.POST("/api/v1/__e2e/reset", resetHandler)

	log.Printf("e2e seeded Go API listening on http://%s", addr)
	if err := r.Run(addr); err != nil {
		log.Fatalf("run e2e server: %v", err)
	}
}

func env(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func resetCanonicalE2EDB(db *gorm.DB) error {
	tables := []string{
		"ai_chat_messages",
		"ai_conversations",
		"chatbot_approvals",
		"chatbot_tool_execution_snapshots",
		"chatbot_turn_audits",
		"quality_inspection_records",
		"production_logs",
		"ai_proposals",
		"ml_training_events",
		"inventory_reservations",
		"product_inventory_reservations",
		"product_inventory",
		"job_dependencies",
		"inventory_expected_arrivals",
		"inventory_transactions",
		"wip_inventory",
		"job_step_schedule_slots",
		"job_steps",
		"jobs",
		"machine_downtime",
		"machine_capabilities",
		"machine_calendar",
		"maintenance_records",
		"product_bom",
		"formula_ingredients",
		"process_steps",
		"products",
		"formula",
		"product_process",
		"inventory_materials",
		"machines",
		"reference_machine_types",
		"reference_product_types",
		"reference_locations",
		"reference_storage_locations",
		"reference_step_types",
	}
	for _, table := range tables {
		if err := db.Exec("DELETE FROM " + table).Error; err != nil {
			return fmt.Errorf("reset %s: %w", table, err)
		}
	}
	if err := seeddata.SeedCanonical(db, seeddata.SeedOptions{ValidateFingerprint: true}); err != nil {
		return fmt.Errorf("seed canonical: %w", err)
	}
	return nil
}
