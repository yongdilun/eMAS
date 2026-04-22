package domain

import (
	"time"
)

// IdempotencyLog serves as a DB-level backup for the idempotency cache.
// It stores the response for a specific idempotency key to prevent duplicate execution.
type IdempotencyLog struct {
	Key          string    `gorm:"primaryKey;type:varchar(255)" json:"key"`
	RequestHash  string    `gorm:"type:varchar(255);not null" json:"request_hash"`
	Response     []byte    `gorm:"type:blob;not null" json:"response"`
	StatusCode   int       `gorm:"not null" json:"status_code"`
	CreatedAt    time.Time `gorm:"autoCreateTime" json:"created_at"`
}
