package middleware_test

import (
	"net/http"
	"testing"

	"emas/internal/middleware"
	"emas/internal/testutil"
	"emas/pkg/logger"

	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
	"go.uber.org/zap/zaptest/observer"
)

func TestRequestContextPropagatesCorrelationIDAndStructuredLog(t *testing.T) {
	core, logs := observer.New(zap.InfoLevel)
	previous := logger.Log
	logger.Log = zap.New(core)
	t.Cleanup(func() { logger.Log = previous })

	r := gin.New()
	r.Use(middleware.RequestContext())
	r.GET("/ping/:id", func(c *gin.Context) {
		requestID, _ := c.Get(middleware.ContextRequestIDKey)
		correlationID, _ := c.Get(middleware.ContextCorrelationIDKey)
		c.JSON(http.StatusOK, gin.H{
			"request_id":     requestID,
			"correlation_id": correlationID,
		})
	})

	w := testutil.RequestWithHeaders(r, http.MethodGet, "/ping/42?debug=true", nil, map[string]string{
		"X-Request-Id":     "req-test-1",
		"X-Correlation-Id": "corr-test-1",
	})

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	if got := w.Header().Get("X-Request-Id"); got != "req-test-1" {
		t.Fatalf("X-Request-Id = %q, want req-test-1", got)
	}
	if got := w.Header().Get("X-Correlation-Id"); got != "corr-test-1" {
		t.Fatalf("X-Correlation-Id = %q, want corr-test-1", got)
	}

	entries := logs.FilterMessage("http_request").All()
	if len(entries) != 1 {
		t.Fatalf("logged http_request entries = %d, want 1", len(entries))
	}
	fields := entries[0].ContextMap()
	assertLogField(t, fields, "request_id", "req-test-1")
	assertLogField(t, fields, "correlation_id", "corr-test-1")
	assertLogField(t, fields, "method", http.MethodGet)
	assertLogField(t, fields, "path", "/ping/42")
	assertLogField(t, fields, "route", "/ping/:id")
	assertLogField(t, fields, "query", "debug=true")
	if fields["latency_ms"] == nil {
		t.Fatal("expected latency_ms log field")
	}
}

func TestRequestContextGeneratesIDsWhenHeadersAreMissing(t *testing.T) {
	r := gin.New()
	r.Use(middleware.RequestContext())
	r.GET("/ping", func(c *gin.Context) {
		c.Status(http.StatusNoContent)
	})

	w := testutil.RequestWithHeaders(r, http.MethodGet, "/ping", nil, nil)

	requestID := w.Header().Get("X-Request-Id")
	if requestID == "" {
		t.Fatal("expected generated X-Request-Id")
	}
	if got := w.Header().Get("X-Correlation-Id"); got != requestID {
		t.Fatalf("X-Correlation-Id = %q, want generated request id %q", got, requestID)
	}
}

func assertLogField(t *testing.T, fields map[string]interface{}, key string, want interface{}) {
	t.Helper()
	if got := fields[key]; got != want {
		t.Fatalf("log field %s = %v, want %v", key, got, want)
	}
}
