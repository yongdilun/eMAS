package handler

import (
	"encoding/json"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
)

const (
	SettingTheme         = "app.theme"
	SettingLanguage      = "app.language"
	SettingNotifications = "app.notifications"
	SettingAIEnabled     = "app.ai_enabled"
	defaultTheme         = "light"
	defaultLanguage      = "en"
	defaultNotifications = true
	defaultAIEnabled     = true
)

type SettingsHandler struct {
	settingsRepo *repository.SystemSettingsRepository
}

func NewSettingsHandler(settingsRepo *repository.SystemSettingsRepository) *SettingsHandler {
	return &SettingsHandler{settingsRepo: settingsRepo}
}

// flexibleBool unmarshals from either a boolean or an object like {"enabled": true}.
// This prevents "cannot unmarshal object into Go struct field of type bool" when
// the frontend sends notifications/ai_enabled as an object.
type flexibleBool struct {
	val *bool
}

func (f *flexibleBool) UnmarshalJSON(data []byte) error {
	var b bool
	if err := json.Unmarshal(data, &b); err == nil {
		f.val = &b
		return nil
	}
	var obj struct {
		Enabled *bool `json:"enabled"`
	}
	if err := json.Unmarshal(data, &obj); err == nil && obj.Enabled != nil {
		f.val = obj.Enabled
		return nil
	}
	return nil // ignore invalid values; treat as "not provided"
}

func (f *flexibleBool) Bool() (bool, bool) {
	if f.val == nil {
		return false, false
	}
	return *f.val, true
}

type SettingsResponse struct {
	Theme         string   `json:"theme"`
	Language      string   `json:"language"`
	Notifications bool     `json:"notifications"`
	AIEnabled     bool     `json:"ai_enabled"`
	Integrations  []string `json:"integrations"`
}

// @Summary Get settings
// @Description Get settings
// @Tags settings
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=SettingsResponse}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /settings/get [get]
func (h *SettingsHandler) Get(c *gin.Context) {
	res := SettingsResponse{
		Theme:         defaultTheme,
		Language:      defaultLanguage,
		Notifications: defaultNotifications,
		AIEnabled:     defaultAIEnabled,
		Integrations:  []string{"erp", "mes"},
	}
	if h.settingsRepo != nil {
		if v, ok, _ := h.settingsRepo.GetString(SettingTheme); ok && v != "" {
			res.Theme = strings.TrimSpace(v)
		}
		if v, ok, _ := h.settingsRepo.GetString(SettingLanguage); ok && v != "" {
			res.Language = strings.TrimSpace(v)
		}
		if v, ok, _ := h.settingsRepo.GetString(SettingNotifications); ok {
			res.Notifications = strings.ToLower(strings.TrimSpace(v)) == "true" || v == "1"
		}
		if v, ok, _ := h.settingsRepo.GetString(SettingAIEnabled); ok {
			res.AIEnabled = strings.ToLower(strings.TrimSpace(v)) == "true" || v == "1"
		}
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: res})
}

// @Summary Update settings
// @Description Update settings
// @Tags settings
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=SettingsResponse}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /settings/update [put]
func (h *SettingsHandler) Update(c *gin.Context) {
	var req struct {
		Theme         *string       `json:"theme"`
		Language      *string       `json:"language"`
		Notifications *flexibleBool `json:"notifications"`
		AIEnabled     *flexibleBool `json:"ai_enabled"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	// Build response from stored values (or defaults), then overlay request
	res := SettingsResponse{
		Theme:         defaultTheme,
		Language:      defaultLanguage,
		Notifications: defaultNotifications,
		AIEnabled:     defaultAIEnabled,
		Integrations:  []string{"erp", "mes"},
	}
	if h.settingsRepo != nil {
		if v, ok, _ := h.settingsRepo.GetString(SettingTheme); ok && v != "" {
			res.Theme = strings.TrimSpace(v)
		}
		if v, ok, _ := h.settingsRepo.GetString(SettingLanguage); ok && v != "" {
			res.Language = strings.TrimSpace(v)
		}
		if v, ok, _ := h.settingsRepo.GetString(SettingNotifications); ok {
			res.Notifications = strings.ToLower(strings.TrimSpace(v)) == "true" || v == "1"
		}
		if v, ok, _ := h.settingsRepo.GetString(SettingAIEnabled); ok {
			res.AIEnabled = strings.ToLower(strings.TrimSpace(v)) == "true" || v == "1"
		}
	}
	if req.Theme != nil {
		res.Theme = strings.TrimSpace(*req.Theme)
		if res.Theme == "" {
			res.Theme = defaultTheme
		}
		if h.settingsRepo != nil {
			_ = h.settingsRepo.PutString(SettingTheme, res.Theme)
		}
	}
	if req.Language != nil {
		res.Language = strings.TrimSpace(*req.Language)
		if res.Language == "" {
			res.Language = defaultLanguage
		}
		if h.settingsRepo != nil {
			_ = h.settingsRepo.PutString(SettingLanguage, res.Language)
		}
	}
	if req.Notifications != nil {
		if v, ok := req.Notifications.Bool(); ok {
			res.Notifications = v
			if h.settingsRepo != nil {
				_ = h.settingsRepo.PutString(SettingNotifications, strconv.FormatBool(v))
			}
		}
	}
	if req.AIEnabled != nil {
		if v, ok := req.AIEnabled.Bool(); ok {
			res.AIEnabled = v
			if h.settingsRepo != nil {
				_ = h.settingsRepo.PutString(SettingAIEnabled, strconv.FormatBool(v))
			}
		}
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: res})
}
