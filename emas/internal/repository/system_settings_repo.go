package repository

import (
	"emas/internal/domain"
	"strconv"
	"strings"
	"time"

	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

type SystemSettingsRepository struct {
	db *gorm.DB
}

func NewSystemSettingsRepository(db *gorm.DB) *SystemSettingsRepository {
	return &SystemSettingsRepository{db: db}
}

func (r *SystemSettingsRepository) GetString(key string) (string, bool, error) {
	key = strings.TrimSpace(key)
	if key == "" {
		return "", false, nil
	}
	var row domain.SystemSetting
	err := r.db.Where("`key` = ?", key).First(&row).Error
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			return "", false, nil
		}
		return "", false, err
	}
	return row.Value, true, nil
}

func (r *SystemSettingsRepository) PutString(key, value string) error {
	key = strings.TrimSpace(key)
	if key == "" {
		return nil
	}
	now := time.Now().UTC()
	row := domain.SystemSetting{
		Key:       key,
		Value:     value,
		UpdatedAt: now,
	}
	return r.db.Clauses(clause.OnConflict{
		Columns:   []clause.Column{{Name: "key"}},
		DoUpdates: clause.AssignmentColumns([]string{"value", "updated_at"}),
	}).Create(&row).Error
}

func (r *SystemSettingsRepository) GetInt(key string, defaultValue int) (int, error) {
	v, ok, err := r.GetString(key)
	if err != nil || !ok {
		return defaultValue, err
	}
	n, err := strconv.Atoi(strings.TrimSpace(v))
	if err != nil {
		return defaultValue, nil
	}
	return n, nil
}

func (r *SystemSettingsRepository) PutInt(key string, n int) error {
	return r.PutString(key, strconv.Itoa(n))
}

func (r *SystemSettingsRepository) GetFloat(key string, defaultValue float64) (float64, error) {
	v, ok, err := r.GetString(key)
	if err != nil || !ok {
		return defaultValue, err
	}
	f, err := strconv.ParseFloat(strings.TrimSpace(v), 64)
	if err != nil {
		return defaultValue, nil
	}
	return f, nil
}

func (r *SystemSettingsRepository) PutFloat(key string, f float64) error {
	return r.PutString(key, strconv.FormatFloat(f, 'f', -1, 64))
}

