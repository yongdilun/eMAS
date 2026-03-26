package domain

import "time"

// SystemSetting stores runtime-tunable configuration values.
// It is intentionally generic (key/value) so we can add settings without schema churn.
type SystemSetting struct {
	Key       string    `gorm:"column:key;primaryKey;size:191" json:"key"`
	Value     string    `gorm:"column:value;type:text" json:"value"`
	UpdatedAt time.Time `gorm:"column:updated_at" json:"updated_at"`
}

func (SystemSetting) TableName() string { return "system_settings" }

