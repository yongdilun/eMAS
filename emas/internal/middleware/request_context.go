package middleware

import (
	"emas/pkg/logger"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"go.uber.org/zap"
)

const (
	ContextRequestIDKey     = "request_id"
	ContextCorrelationIDKey = "correlation_id"
)

func RequestContext() gin.HandlerFunc {
	return func(c *gin.Context) {
		requestID := c.GetHeader("X-Request-Id")
		if requestID == "" {
			requestID = "req-" + uuid.NewString()
		}
		correlationID := c.GetHeader("X-Correlation-Id")
		if correlationID == "" {
			correlationID = requestID
		}
		c.Set(ContextRequestIDKey, requestID)
		c.Set(ContextCorrelationIDKey, correlationID)
		c.Writer.Header().Set("X-Request-Id", requestID)
		c.Writer.Header().Set("X-Correlation-Id", correlationID)
		start := time.Now()
		c.Next()
		route := c.FullPath()
		if route == "" {
			route = c.Request.URL.Path
		}
		logger.L().Info("http_request",
			zap.String("request_id", requestID),
			zap.String("correlation_id", correlationID),
			zap.String("method", c.Request.Method),
			zap.String("path", c.Request.URL.Path),
			zap.String("route", route),
			zap.String("query", c.Request.URL.RawQuery),
			zap.Int("status", c.Writer.Status()),
			zap.Int64("latency_ms", time.Since(start).Milliseconds()),
			zap.String("client_ip", c.ClientIP()),
			zap.String("user_agent", c.Request.UserAgent()),
			zap.String("errors", c.Errors.String()),
		)
	}
}
