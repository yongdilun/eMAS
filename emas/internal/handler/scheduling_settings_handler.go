package handler

import (
	"encoding/json"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/internal/service"
	"errors"
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

const (
	SettingLockInWindowMinutes     = "scheduling.lock_in_window_minutes"
	SettingDeviationPenaltyWeight  = "scheduling.deviation_penalty_weight"
	SettingSplitStrategy           = "scheduling.split_strategy"
	SettingObjective               = "scheduling.objective"
	SettingAutoRescheduleOnEvent   = "scheduling.auto_reschedule_on_event"
	SettingWorkStartTime           = "scheduling.work_start_time"
	SettingWorkEndTime             = "scheduling.work_end_time"
	SettingWorkDays                = "scheduling.work_days"
	SettingPublicHolidays          = "scheduling.public_holidays"
	SettingLatenessWeight          = "scheduling.score.lateness_weight"
	SettingSetupWeight             = "scheduling.score.setup_weight"
	SettingSlackWeight             = "scheduling.score.slack_weight"
	defaultLockInWindowMinutes     = 240
	defaultDeviationPenaltyWeight  = 0.25
	defaultSplitStrategy           = "equal"
	defaultObjective               = "minimize_tardiness"
	defaultAutoRescheduleOnEvent   = false
	defaultWorkStartTime           = "08:00"
	defaultWorkEndTime             = "17:00"
	defaultWorkDays                = "1,2,3,4,5"
	defaultLatenessWeight          = 1.0
	defaultSetupWeight             = 0.6
	defaultSlackWeight             = 0.3
)

var hhmmRegex = regexp.MustCompile(`^([01]?\d|2[0-3]):([0-5]\d)$`)

type SchedulingSettingsHandler struct {
	settingsRepo *repository.SystemSettingsRepository
	scheduling   *service.SchedulingService
}

func NewSchedulingSettingsHandler(settingsRepo *repository.SystemSettingsRepository, scheduling *service.SchedulingService) *SchedulingSettingsHandler {
	return &SchedulingSettingsHandler{settingsRepo: settingsRepo, scheduling: scheduling}
}

type SchedulingSettingsResponse struct {
	LockInWindowMinutes     int      `json:"lock_in_window_minutes"`
	DeviationPenaltyWeight  float64  `json:"deviation_penalty_weight"`
	SplitStrategy           string   `json:"split_strategy"`
	Objective               string   `json:"objective"`
	AutoRescheduleOnEvent   bool     `json:"auto_reschedule_on_event"`
	WorkStartTime           string   `json:"work_start_time"`
	WorkEndTime             string   `json:"work_end_time"`
	WorkDays                string   `json:"work_days"`
	PublicHolidays          []string `json:"public_holidays"`
	LatenessWeight          float64  `json:"lateness_weight"`
	SetupWeight             float64  `json:"setup_weight"`
	SlackWeight             float64  `json:"slack_weight"`
	UpdatedAt               string   `json:"updated_at,omitempty"`
}

func (h *SchedulingSettingsHandler) Get(c *gin.Context) {
	// @Summary Get scheduling settings
	// @Description Get scheduling settings
	// @Tags scheduling
	// @Accept json
	// @Produce json
	// @Success 200 {object} dto.Response{data=SchedulingSettingsResponse}
	// @Failure 400 {object} dto.Response
	// @Failure 500 {object} dto.Response
	// @Router /scheduling/settings [get]
	lockMins := defaultLockInWindowMinutes
	penalty := defaultDeviationPenaltyWeight
	splitStrategy := defaultSplitStrategy
	objective := defaultObjective
	autoReschedule := defaultAutoRescheduleOnEvent
	workStart := defaultWorkStartTime
	workEnd := defaultWorkEndTime
	workDays := defaultWorkDays
	publicHolidays := []string{}
	latenessWeight := defaultLatenessWeight
	setupWeight := defaultSetupWeight
	slackWeight := defaultSlackWeight
	updatedAt := ""

	if h.settingsRepo != nil {
		if v, err := h.settingsRepo.GetInt(SettingLockInWindowMinutes, defaultLockInWindowMinutes); err == nil {
			lockMins = v
		}
		if v, err := h.settingsRepo.GetFloat(SettingDeviationPenaltyWeight, defaultDeviationPenaltyWeight); err == nil {
			penalty = v
		}
		if v, ok, _ := h.settingsRepo.GetString(SettingSplitStrategy); ok && v != "" {
			splitStrategy = strings.ToLower(strings.TrimSpace(v))
		}
		if v, ok, _ := h.settingsRepo.GetString(SettingObjective); ok && v != "" {
			objective = strings.ToLower(strings.TrimSpace(v))
		}
		if v, ok, _ := h.settingsRepo.GetString(SettingAutoRescheduleOnEvent); ok {
			autoReschedule = strings.ToLower(strings.TrimSpace(v)) == "true" || v == "1"
		}
		if v, ok, _ := h.settingsRepo.GetString(SettingWorkStartTime); ok && v != "" {
			workStart = strings.TrimSpace(v)
		}
		if v, ok, _ := h.settingsRepo.GetString(SettingWorkEndTime); ok && v != "" {
			workEnd = strings.TrimSpace(v)
		}
		if v, ok, _ := h.settingsRepo.GetString(SettingWorkDays); ok && v != "" {
			workDays = strings.TrimSpace(v)
		}
		if v, ok, _ := h.settingsRepo.GetString(SettingPublicHolidays); ok && v != "" {
			_ = json.Unmarshal([]byte(v), &publicHolidays)
		}
		if v, err := h.settingsRepo.GetFloat(SettingLatenessWeight, defaultLatenessWeight); err == nil {
			latenessWeight = v
		}
		if v, err := h.settingsRepo.GetFloat(SettingSetupWeight, defaultSetupWeight); err == nil {
			setupWeight = v
		}
		if v, err := h.settingsRepo.GetFloat(SettingSlackWeight, defaultSlackWeight); err == nil {
			slackWeight = v
		}
	}

	updatedAt = time.Now().UTC().Format(time.RFC3339)

	c.JSON(http.StatusOK, dto.Response{Success: true, Data: SchedulingSettingsResponse{
		LockInWindowMinutes:    lockMins,
		DeviationPenaltyWeight: penalty,
		SplitStrategy:          splitStrategy,
		Objective:              objective,
		AutoRescheduleOnEvent:  autoReschedule,
		WorkStartTime:          workStart,
		WorkEndTime:            workEnd,
		WorkDays:               workDays,
		PublicHolidays:         publicHolidays,
		LatenessWeight:         latenessWeight,
		SetupWeight:            setupWeight,
		SlackWeight:            slackWeight,
		UpdatedAt:              updatedAt,
	}})
}

type UpdateSchedulingSettingsRequest struct {
	LockInWindowMinutes    *int      `json:"lock_in_window_minutes"`
	DeviationPenaltyWeight *float64  `json:"deviation_penalty_weight"`
	SplitStrategy          *string   `json:"split_strategy"`
	Objective              *string   `json:"objective"`
	AutoRescheduleOnEvent  *bool     `json:"auto_reschedule_on_event"`
	WorkStartTime          *string   `json:"work_start_time"`
	WorkEndTime            *string   `json:"work_end_time"`
	WorkDays               *string   `json:"work_days"`
	PublicHolidays         *[]string `json:"public_holidays"`
	LatenessWeight         *float64  `json:"lateness_weight"`
	SetupWeight            *float64  `json:"setup_weight"`
	SlackWeight            *float64  `json:"slack_weight"`
}

var validSplitStrategies = map[string]bool{
	"equal": true, "proportional": true, "manual": true,
	"min_time": true, "priority": true,
}

var validObjectives = map[string]bool{
	"minimize_tardiness": true, "minimize_makespan": true, "balance_load": true,
	"maximize_utilization": true,
}

// @Summary Update scheduling settings
// @Description Update scheduling settings
// @Tags scheduling
// @Accept json
// @Produce json
// @Param request body UpdateSchedulingSettingsRequest true "Update Scheduling Settings Request"
// @Success 200 {object} dto.Response{data=SchedulingSettingsResponse}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /scheduling/settings [put]
func (h *SchedulingSettingsHandler) Update(c *gin.Context) {
	requiresCalendarRefresh := false
	if h.settingsRepo == nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: "settings repository not configured"})
		return
	}
	var req UpdateSchedulingSettingsRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}

	if req.LockInWindowMinutes != nil {
		if *req.LockInWindowMinutes < 0 || *req.LockInWindowMinutes > 1440 {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "lock_in_window_minutes must be 0..1440"})
			return
		}
		if err := h.settingsRepo.PutInt(SettingLockInWindowMinutes, *req.LockInWindowMinutes); err != nil {
			c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
			return
		}
	}
	if req.DeviationPenaltyWeight != nil {
		if *req.DeviationPenaltyWeight < 0 || *req.DeviationPenaltyWeight > 5 {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "deviation_penalty_weight must be 0..5"})
			return
		}
		if err := h.settingsRepo.PutFloat(SettingDeviationPenaltyWeight, *req.DeviationPenaltyWeight); err != nil {
			c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
			return
		}
	}
	if req.SplitStrategy != nil {
		s := strings.ToLower(strings.TrimSpace(*req.SplitStrategy))
		if !validSplitStrategies[s] {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "split_strategy must be equal, proportional, manual, min_time, or priority"})
			return
		}
		if err := h.settingsRepo.PutString(SettingSplitStrategy, s); err != nil {
			c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
			return
		}
	}
	if req.Objective != nil {
		o := strings.ToLower(strings.TrimSpace(*req.Objective))
		if !validObjectives[o] {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "objective must be minimize_tardiness, minimize_makespan, balance_load, or maximize_utilization"})
			return
		}
		if err := h.settingsRepo.PutString(SettingObjective, o); err != nil {
			c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
			return
		}
	}
	if req.AutoRescheduleOnEvent != nil {
		val := "false"
		if *req.AutoRescheduleOnEvent {
			val = "true"
		}
		if err := h.settingsRepo.PutString(SettingAutoRescheduleOnEvent, val); err != nil {
			c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
			return
		}
	}
	workStartVal, _, _ := h.settingsRepo.GetString(SettingWorkStartTime)
	if workStartVal == "" {
		workStartVal = defaultWorkStartTime
	}
	workEndVal, _, _ := h.settingsRepo.GetString(SettingWorkEndTime)
	if workEndVal == "" {
		workEndVal = defaultWorkEndTime
	}
	if req.WorkStartTime != nil {
		s := strings.TrimSpace(*req.WorkStartTime)
		if !hhmmRegex.MatchString(s) {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "work_start_time must be HH:MM (24h)"})
			return
		}
		workStartVal = s
		requiresCalendarRefresh = true
	}
	if req.WorkEndTime != nil {
		s := strings.TrimSpace(*req.WorkEndTime)
		if !hhmmRegex.MatchString(s) {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "work_end_time must be HH:MM (24h)"})
			return
		}
		workEndVal = s
		requiresCalendarRefresh = true
	}
	if (req.WorkStartTime != nil || req.WorkEndTime != nil) && !isTimeBefore(workStartVal, workEndVal) {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "work_start_time must be before work_end_time"})
		return
	}
	if req.WorkStartTime != nil {
		_ = h.settingsRepo.PutString(SettingWorkStartTime, workStartVal)
	}
	if req.WorkEndTime != nil {
		_ = h.settingsRepo.PutString(SettingWorkEndTime, workEndVal)
	}
	if req.WorkDays != nil {
		s := strings.TrimSpace(*req.WorkDays)
		if err := validateWorkDays(s); err != nil {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
			return
		}
		if err := h.settingsRepo.PutString(SettingWorkDays, s); err != nil {
			c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
			return
		}
		requiresCalendarRefresh = true
	}
	if req.PublicHolidays != nil {
		for _, d := range *req.PublicHolidays {
			if !isValidISODate(d) {
				c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "public_holidays must be YYYY-MM-DD dates: " + d})
				return
			}
		}
		b, _ := json.Marshal(*req.PublicHolidays)
		if err := h.settingsRepo.PutString(SettingPublicHolidays, string(b)); err != nil {
			c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
			return
		}
		requiresCalendarRefresh = true
	}
	if req.LatenessWeight != nil {
		if *req.LatenessWeight < 0 || *req.LatenessWeight > 5 {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "lateness_weight must be 0..5"})
			return
		}
		if err := h.settingsRepo.PutFloat(SettingLatenessWeight, *req.LatenessWeight); err != nil {
			c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
			return
		}
	}
	if req.SetupWeight != nil {
		if *req.SetupWeight < 0 || *req.SetupWeight > 5 {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "setup_weight must be 0..5"})
			return
		}
		if err := h.settingsRepo.PutFloat(SettingSetupWeight, *req.SetupWeight); err != nil {
			c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
			return
		}
	}
	if req.SlackWeight != nil {
		if *req.SlackWeight < 0 || *req.SlackWeight > 5 {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "slack_weight must be 0..5"})
			return
		}
		if err := h.settingsRepo.PutFloat(SettingSlackWeight, *req.SlackWeight); err != nil {
			c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
			return
		}
	}

	if requiresCalendarRefresh && h.scheduling != nil {
		if err := h.scheduling.RefreshWorkCalendarsFromSettings(); err != nil {
			c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: "settings saved but failed to refresh work calendars: " + err.Error()})
			return
		}
	}

	h.Get(c)
}

// @Summary Is time before
// @Description Is time before
// @Tags scheduling
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=bool}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /scheduling/is-time-before [get]
func isTimeBefore(a, b string) bool {
	ta, errA := time.Parse("15:04", strings.TrimSpace(a))
	tb, errB := time.Parse("15:04", strings.TrimSpace(b))
	if errA != nil || errB != nil {
		return true
	}
	return ta.Before(tb)
}

// @Summary Validate work days
// @Description Validate work days
// @Tags scheduling
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=error}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /scheduling/validate-work-days [get]
func validateWorkDays(s string) error {
	seen := make(map[rune]bool)
	for _, p := range strings.Split(s, ",") {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		if len(p) != 1 || p[0] < '0' || p[0] > '6' {
			return errors.New("work_days must be comma-separated 0-6 (0=Sun, 6=Sat)")
		}
		c := rune(p[0])
		if seen[c] {
			return errors.New("work_days must not contain duplicates")
		}
		seen[c] = true
	}
	return nil
}

// @Summary Is valid ISO date
// @Description Is valid ISO date
// @Tags scheduling
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=bool}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /scheduling/is-valid-iso-date [get]
func isValidISODate(s string) bool {
	_, err := time.Parse("2006-01-02", strings.TrimSpace(s))
	return err == nil
}
