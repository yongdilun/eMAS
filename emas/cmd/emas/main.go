package main

import (
	"emas/config"
	"emas/internal/repository"
	"emas/internal/router"
	"emas/pkg/logger"
	"net/http"

	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

// @title eMas Factory API
// @version 1.0
// @description Factory operations API.
// @host localhost:8080
// @BasePath /api/v1
func main() {
	_ = logger.Init()

	cfg, err := config.Load()
	if err != nil {
		panic(err)
	}

	db, err := repository.InitDB(cfg)
	if err != nil {
		panic(err)
	}

	if cfg.AutoMigrate {
		logger.L().Warn("automigrate_enabled",
			zap.String("scope", "tests_and_local_only"),
			zap.String("disable_with", "EMAS_AUTO_MIGRATE=false"),
		)
		if err := repository.AutoMigrate(db); err != nil {
			panic(err)
		}
	} else {
		logger.L().Info("automigrate_skipped",
			zap.String("reason", "EMAS_AUTO_MIGRATE=false"),
		)
	}

	r := router.Setup(db)

	r.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	})

	if err := r.Run(cfg.ServerAddr); err != nil {
		panic(err)
	}
}
