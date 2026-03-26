package main

import (
	"emas/config"
	"emas/internal/repository"
	"emas/internal/router"
	"emas/pkg/logger"
	"net/http"

	"github.com/gin-gonic/gin"
)

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

	if err := repository.AutoMigrate(db); err != nil {
		panic(err)
	}

	r := router.Setup(db)

	r.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	})

	if err := r.Run(cfg.ServerAddr); err != nil {
		panic(err)
	}
}
