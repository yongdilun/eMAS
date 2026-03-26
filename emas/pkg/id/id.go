package id

import "github.com/google/uuid"

// New returns a new UUID string
func New() string {
	return uuid.New().String()
}

// NewPrefixed returns ID with prefix (e.g. "JOB-", "SLOT-")
func NewPrefixed(prefix string) string {
	return prefix + uuid.New().String()[:8]
}
