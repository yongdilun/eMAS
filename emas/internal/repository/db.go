package repository

import (
	"emas/config"
	"fmt"

	"gorm.io/driver/mysql"
	"gorm.io/gorm"
)

// InitDB initializes database connection
func InitDB(cfg *config.Config) (*gorm.DB, error) {
	dsn := fmt.Sprintf("%s:%s@tcp(%s:%s)/%s?charset=utf8mb4&parseTime=True&loc=Local",
		cfg.DBUser, cfg.DBPassword, cfg.DBHost, cfg.DBPort, cfg.DBName)
	return gorm.Open(mysql.Open(dsn), &gorm.Config{})
}
