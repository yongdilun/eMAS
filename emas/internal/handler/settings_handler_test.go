package handler_test

import (
	"net/http"
	"testing"

	"emas/internal/router"
	"emas/internal/testutil"
)

func TestSettingsHandler_Get(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "GET", "/api/v1/settings", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("get settings: got %d", w.Code)
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("get settings failed")
	}
	m := data.(map[string]interface{})
	if m["theme"] == nil {
		t.Error("theme missing")
	}
	if m["integrations"] == nil {
		t.Error("integrations missing")
	}
}

func TestSettingsHandler_Update(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "PUT", "/api/v1/settings", map[string]interface{}{
		"theme": "dark", "language": "zh", "notifications": false,
	})
	if w.Code != http.StatusOK {
		t.Fatalf("update settings: got %d", w.Code)
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("update failed")
	}
	m := data.(map[string]interface{})
	if m["theme"] != "dark" {
		t.Errorf("theme: got %v", m["theme"])
	}
	if m["language"] != "zh" {
		t.Errorf("language: got %v", m["language"])
	}
}

func TestSettingsHandler_Update_NotificationsAsObject(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	// Frontend may send notifications as object { enabled: true } instead of bool
	w := testutil.Request(r, "PUT", "/api/v1/settings", map[string]interface{}{
		"theme":          "dark",
		"notifications":  map[string]interface{}{"enabled": true},
		"ai_enabled":     map[string]interface{}{"enabled": false},
	})
	if w.Code != http.StatusOK {
		t.Fatalf("update with object form: got %d: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("update failed")
	}
	m := data.(map[string]interface{})
	if m["theme"] != "dark" {
		t.Errorf("theme: got %v", m["theme"])
	}
	if m["notifications"] != true {
		t.Errorf("notifications: got %v, want true", m["notifications"])
	}
	if m["ai_enabled"] != false {
		t.Errorf("ai_enabled: got %v, want false", m["ai_enabled"])
	}

	// Persistence: GET should return saved values
	w2 := testutil.Request(r, "GET", "/api/v1/settings", nil)
	if w2.Code != http.StatusOK {
		t.Fatalf("get after update: got %d", w2.Code)
	}
	_, data2, _ := testutil.DecodeResponse(w2)
	m2 := data2.(map[string]interface{})
	if m2["theme"] != "dark" {
		t.Errorf("get theme: got %v, want dark", m2["theme"])
	}
	if m2["notifications"] != true {
		t.Errorf("get notifications: got %v, want true", m2["notifications"])
	}
	if m2["ai_enabled"] != false {
		t.Errorf("get ai_enabled: got %v, want false", m2["ai_enabled"])
	}
}
