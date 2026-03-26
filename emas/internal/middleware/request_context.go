package middleware

import (
	"emas/pkg/logger"
	"time"

	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

const ContextRequestIDKey = "request_id"

func RequestContext() gin.HandlerFunc {
	return func(c *gin.Context) {
		requestID := c.GetHeader("X-Request-Id")
		if requestID == "" {
			requestID = "req-" + time.Now().UTC().Format("20060102150405.000000000")
		}
		c.Set(ContextRequestIDKey, requestID)
		c.Writer.Header().Set("X-Request-Id", requestID)
		start := time.Now()
		c.Next()
		logger.L().Info("http_request",
			zap.String("request_id", requestID),
			zap.String("method", c.Request.Method),
			zap.String("path", c.FullPath()),
			zap.Int("status", c.Writer.Status()),
			zap.Duration("latency", time.Since(start)),
		)
	}
}
