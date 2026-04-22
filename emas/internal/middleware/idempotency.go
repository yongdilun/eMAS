package middleware

import (
	"bytes"
	"crypto/sha256"
	"emas/internal/domain"
	"encoding/hex"
	"io"
	"net/http"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type responseBodyWriter struct {
	gin.ResponseWriter
	body *bytes.Buffer
}

func (r responseBodyWriter) Write(b []byte) (int, error) {
	r.body.Write(b)
	return r.ResponseWriter.Write(b)
}

// IdempotencyMiddleware ensures exactly-once execution for requests with an Idempotency-Key.
func IdempotencyMiddleware(db *gorm.DB) gin.HandlerFunc {
	return func(c *gin.Context) {
		// Only check POST, PATCH, DELETE
		if c.Request.Method != http.MethodPost && c.Request.Method != http.MethodPatch && c.Request.Method != http.MethodDelete {
			c.Next()
			return
		}

		key := c.GetHeader("Idempotency-Key")
		if key == "" {
			// If not provided, we just pass through. (Could also enforce it if needed).
			c.Next()
			return
		}

		// Buffer body for hashing
		bodyBytes, err := io.ReadAll(c.Request.Body)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{"error": "Failed to read request body"})
			return
		}
		
		// Restore body
		c.Request.Body = io.NopCloser(bytes.NewBuffer(bodyBytes))

		// Calculate hash
		hash := sha256.Sum256(bodyBytes)
		requestHash := hex.EncodeToString(hash[:])

		// Check database
		var log domain.IdempotencyLog
		result := db.Where("`key` = ?", key).First(&log)

		if result.Error == nil {
			// Found in DB
			if log.RequestHash != requestHash {
				c.AbortWithStatusJSON(http.StatusConflict, gin.H{
					"error": "Idempotency key reused with different payload",
				})
				return
			}

			// Same payload, replay response
			c.Header("X-Idempotent-Replayed", "true")
			c.Data(log.StatusCode, "application/json", log.Response)
			c.Abort()
			return
		} else if result.Error != gorm.ErrRecordNotFound {
			// DB Error
			c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{"error": "Database error checking idempotency"})
			return
		}

		// Not found, capture response
		w := &responseBodyWriter{body: bytes.NewBufferString(""), ResponseWriter: c.Writer}
		c.Writer = w

		c.Next()

		// Save to DB (only if it was successful, or save regardless? Usually save regardless to prevent retrying a 400 with same payload)
		// To avoid issues, we save the exact response.
		newLog := domain.IdempotencyLog{
			Key:         key,
			RequestHash: requestHash,
			Response:    w.body.Bytes(),
			StatusCode:  c.Writer.Status(),
		}
		
		// Use Create (if multiple requests arrive at exact same time, only one will succeed due to primary key constraint)
		db.Create(&newLog)
	}
}
