package handler_test

import (
	"net/http"
	"testing"

	"emas/internal/router"
	"emas/internal/testutil"
	"gorm.io/gorm"
)

func isMySQL(db *gorm.DB) bool {
	return db.Dialector.Name() == "mysql"
}

func TestReportsHandler_Endpoints(t *testing.T) {
	db := testutil.NewTestDB(t)
	if !isMySQL(db) {
		t.Skip("Reports use MySQL-specific SQL; run with MySQL for full coverage")
	}
	r := testutil.NewTestRouter(db, router.Setup)

	tests := []struct {
		name string
		path string
	}{
		{"production-output", "/api/v1/reports/production-output"},
		{"machine-utilization", "/api/v1/reports/machine-utilization"},
		{"job-completion", "/api/v1/reports/job-completion"},
		{"inventory-trends", "/api/v1/reports/inventory-trends"},
		{"quality-trends", "/api/v1/reports/quality-trends"},
		{"oee", "/api/v1/reports/oee"},
		{"bottlenecks", "/api/v1/reports/bottlenecks"},
		{"maintenance-efficiency", "/api/v1/reports/maintenance-efficiency"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := testutil.Request(r, "GET", tt.path, nil)
			if w.Code != http.StatusOK {
				t.Fatalf("got %d for %s", w.Code, tt.path)
			}
			success, _, _ := testutil.DecodeResponse(w)
			if !success {
				t.Fatal("response success false")
			}
		})
	}
}

func TestReportsHandler_BottleneckForecast_SQLite(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	// Bottlenecks uses basic GORM, no MySQL-specific SQL
	w := testutil.Request(r, "GET", "/api/v1/reports/bottlenecks", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("bottlenecks: got %d", w.Code)
	}
}
