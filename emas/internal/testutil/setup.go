package testutil

import (
	"bytes"
	"emas/internal/repository"
	"encoding/json"
	_ "github.com/ncruces/go-sqlite3/embed"
	"io"
	"net/http/httptest"
	"runtime"
	"runtime/debug"
	"strings"
	"sync"

	"github.com/gin-gonic/gin"
	"github.com/ncruces/go-sqlite3/gormlite"
	"gorm.io/gorm"
)

func init() {
	gin.SetMode(gin.TestMode)
}

var (
	sharedTestDB   *gorm.DB
	sharedTestDBMu sync.Mutex
)

// NewTestDB returns an in-memory SQLite DB with migrations applied.
// Skips the test if CGO is disabled (SQLite driver requires CGO on Windows).
func NewTestDB(t interface {
	Fatal(...interface{})
	Skip(...interface{})
}) *gorm.DB {
	sharedTestDBMu.Lock()
	defer sharedTestDBMu.Unlock()

	if sharedTestDB == nil {
		runtime.GC()
		debug.FreeOSMemory()
		db, err := gorm.Open(gormlite.Open("file:emas_test_shared?mode=memory&cache=shared"), &gorm.Config{})
		if err != nil {
			if contains(err.Error(), "CGO_ENABLED") || contains(err.Error(), "cgo") {
				t.Skip("Skipping test: SQLite requires CGO. Run with CGO_ENABLED=1 and gcc installed.")
			}
			t.Fatal("open test db:", err)
		}
		sqlDB, err := db.DB()
		if err != nil {
			t.Fatal("open test sql db:", err)
		}
		sqlDB.SetMaxOpenConns(1)
		sqlDB.SetMaxIdleConns(1)
		sqlDB.SetConnMaxLifetime(0)
		sharedTestDB = newTestDBWithDB(t, db)
	}
	if err := resetTestDB(sharedTestDB); err != nil {
		t.Fatal("reset test db:", err)
	}
	return sharedTestDB
}

func resetTestDB(db *gorm.DB) error {
	runtime.GC()
	debug.FreeOSMemory()
	tables := []string{
		"ai_chat_messages",
		"ai_conversations",
		"quality_inspection_records",
		"production_logs",
		"ai_proposals",
		"ml_training_events",
		"inventory_reservations",
		"product_inventory_reservations",
		"product_inventory",
		"job_dependencies",
		"inventory_expected_arrivals",
		"inventory_transactions",
		"wip_inventory",
		"job_step_schedule_slots",
		"job_steps",
		"jobs",
		"machine_downtime",
		"machine_capabilities",
		"machine_calendar",
		"maintenance_records",
		"product_bom",
		"formula_ingredients",
		"process_steps",
		"products",
		"formula",
		"product_process",
		"inventory_materials",
		"machines",
		"reference_machine_types",
		"reference_product_types",
		"reference_locations",
		"reference_storage_locations",
		"reference_step_types",
	}
	for _, table := range tables {
		if err := db.Exec("DELETE FROM " + table).Error; err != nil {
			return err
		}
	}
	return nil
}

func contains(s, sub string) bool {
	return strings.Contains(strings.ToLower(s), strings.ToLower(sub))
}

func newTestDBWithDB(t interface{ Fatal(...interface{}) }, db *gorm.DB) *gorm.DB {
	if err := repository.AutoMigrate(db); err != nil {
		t.Fatal("migrate:", err)
	}
	return db
}

// NewTestRouter returns a configured Gin router with the given DB.
// Pass router.Setup from the test to avoid import cycles.
func NewTestRouter(db *gorm.DB, setupFn func(*gorm.DB) *gin.Engine) *gin.Engine {
	return setupFn(db)
}

// Request executes an HTTP request against the given router and returns the response.
func Request(r *gin.Engine, method, path string, body interface{}) *httptest.ResponseRecorder {
	var bodyReader io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		bodyReader = bytes.NewReader(b)
	}
	req := httptest.NewRequest(method, path, bodyReader)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

// RequestRaw executes an HTTP request with raw body.
func RequestRaw(r *gin.Engine, method, path string, body []byte) *httptest.ResponseRecorder {
	var bodyReader io.Reader
	if len(body) > 0 {
		bodyReader = bytes.NewReader(body)
	}
	req := httptest.NewRequest(method, path, bodyReader)
	if len(body) > 0 {
		req.Header.Set("Content-Type", "application/json")
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

// ParseJSON unmarshals response body into v.
func ParseJSON(w *httptest.ResponseRecorder, v interface{}) error {
	return json.Unmarshal(w.Body.Bytes(), v)
}

// DecodeResponse parses the standard API response into data and error.
func DecodeResponse(w *httptest.ResponseRecorder) (success bool, data interface{}, errMsg string) {
	var m struct {
		Success bool        `json:"success"`
		Data    interface{} `json:"data"`
		Error   string      `json:"error"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &m)
	return m.Success, m.Data, m.Error
}
