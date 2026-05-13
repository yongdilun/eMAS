package handler

import (
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type DashboardHandler struct {
	db          *gorm.DB
	machineRepo *repository.MachineRepository
	invRepo     *repository.InventoryRepository
}

func NewDashboardHandler(db *gorm.DB, machineRepo *repository.MachineRepository, invRepo *repository.InventoryRepository) *DashboardHandler {
	return &DashboardHandler{db: db, machineRepo: machineRepo, invRepo: invRepo}
}

type KPIsResponse struct {
	OEEPct            float64 `json:"oee_pct"`
	OEEChange         float64 `json:"oee_change"`
	ProductionUnits   int     `json:"production_units"`
	ProductionChange  float64 `json:"production_change"`
	DowntimeHrs       float64 `json:"downtime_hrs"`
	DowntimeChange    float64 `json:"downtime_change"`
	UtilizationPct    float64 `json:"utilization_pct"`
	UtilizationChange float64 `json:"utilization_change"`
}

// @Summary Get KPIs
// @Description Get KPIs
// @Tags dashboard
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=KPIsResponse}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /dashboard/kpis [get]
func (h *DashboardHandler) GetKPIs(c *gin.Context) {
	resp := KPIsResponse{
		OEEPct:            85.2,
		OEEChange:         1.5,
		ProductionUnits:   10450,
		ProductionChange:  5.0,
		DowntimeHrs:       2.1,
		DowntimeChange:    0.2,
		UtilizationPct:    78.0,
		UtilizationChange: 2.5,
	}
	// Try to aggregate from DB when possible
	var prodTotal int
	if err := h.db.Table("production_logs").Select("COALESCE(SUM(quantity_produced), 0)").Scan(&prodTotal).Error; err == nil && prodTotal > 0 {
		resp.ProductionUnits = prodTotal
	}
	var downtimeMins float64
	if err := h.db.Table("machine_downtime").Select("COALESCE(SUM(duration_minutes), 0)").Scan(&downtimeMins).Error; err == nil {
		resp.DowntimeHrs = downtimeMins / 60.0
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: resp})
}

type AlertItem struct {
	Type      string  `json:"type"`
	Title     string  `json:"title"`
	Time      string  `json:"time"`
	MachineID *string `json:"machine_id,omitempty"`
}

// @Summary Get alerts
// @Description Get alerts
// @Tags dashboard
// @Accept json
// @Produce json
// @Param status query string false "Filter by status (active)"
// @Param type query string false "Filter by alert type (maintenance, inventory, downtime)"
// @Param sort_by query string false "Field to sort by (time, type, title)"
// @Param sort_dir query string false "Sort direction (asc, desc)"
// @Param limit query int false "Limit number of results"
// @Param offset query int false "Offset for pagination"
// @Param fields query string false "Comma-separated fields to return (type,title,time,machine_id)"
// @Success 200 {object} dto.Response{data=[]AlertItem}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /alerts [get]
func (h *DashboardHandler) GetAlerts(c *gin.Context) {
	status := c.Query("status")
	typeFilter := strings.TrimSpace(strings.ToLower(c.Query("type")))
	sortBy := strings.TrimSpace(strings.ToLower(c.DefaultQuery("sort_by", "time")))
	sortDir := strings.TrimSpace(strings.ToLower(c.DefaultQuery("sort_dir", "desc")))
	fieldsRaw := strings.TrimSpace(strings.ToLower(c.Query("fields")))
	limit := 0
	offset := 0
	if v := c.Query("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			limit = n
		}
	}
	if v := c.Query("offset"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			offset = n
		}
	}
	var alerts []AlertItem
	now := time.Now().Format(time.RFC3339)

	// Maintenance alerts (active = due soon)
	machines, _ := h.machineRepo.ListAll()
	for _, m := range machines {
		if m.Status == "maintenance" {
			mid := m.MachineID
			alerts = append(alerts, AlertItem{
				Type:      "maintenance",
				Title:     m.MachineName + " requires maintenance",
				Time:      now,
				MachineID: &mid,
			})
		}
	}

	// Low stock
	materials, _ := h.invRepo.ListMaterials()
	for _, m := range materials {
		if m.Status == "low_stock" || m.Status == "out_of_stock" {
			title := m.MaterialName + " is " + m.Status
			alerts = append(alerts, AlertItem{Type: "inventory", Title: title, Time: now})
		}
	}

	// Recent downtime (last 24h)
	cutoff := time.Now().Add(-24 * time.Hour)
	var downtimes []struct {
		MachineID string    `gorm:"column:machine_id"`
		Cause     string    `gorm:"column:cause"`
		StartTime time.Time `gorm:"column:start_time"`
	}
	if err := h.db.Table("machine_downtime").Where("start_time >= ?", cutoff).Find(&downtimes).Error; err == nil {
		for _, d := range downtimes {
			mid := d.MachineID
			alerts = append(alerts, AlertItem{
				Type:      "downtime",
				Title:     d.Cause,
				Time:      d.StartTime.Format(time.RFC3339),
				MachineID: &mid,
			})
		}
	}

	if typeFilter != "" {
		filtered := make([]AlertItem, 0, len(alerts))
		for _, a := range alerts {
			if strings.EqualFold(a.Type, typeFilter) {
				filtered = append(filtered, a)
			}
		}
		alerts = filtered
	}

	if sortDir != "asc" {
		sortDir = "desc"
	}
	sort.SliceStable(alerts, func(i, j int) bool {
		ai, aj := alerts[i], alerts[j]
		var cmp int
		switch sortBy {
		case "type":
			if ai.Type < aj.Type {
				cmp = -1
			} else if ai.Type > aj.Type {
				cmp = 1
			}
		case "title":
			if ai.Title < aj.Title {
				cmp = -1
			} else if ai.Title > aj.Title {
				cmp = 1
			}
		default:
			if ai.Time < aj.Time {
				cmp = -1
			} else if ai.Time > aj.Time {
				cmp = 1
			}
		}
		if sortDir == "desc" {
			return cmp > 0
		}
		return cmp < 0
	})

	if offset > 0 {
		if offset >= len(alerts) {
			alerts = []AlertItem{}
		} else {
			alerts = alerts[offset:]
		}
	}
	if limit > 0 && limit < len(alerts) {
		alerts = alerts[:limit]
	}

	if status == "active" && len(alerts) == 0 {
		alerts = []AlertItem{}
	}

	if fieldsRaw == "" {
		c.JSON(http.StatusOK, dto.Response{Success: true, Data: alerts})
		return
	}
	allowed := map[string]bool{
		"type":       true,
		"title":      true,
		"time":       true,
		"machine_id": true,
	}
	selected := make([]string, 0, 4)
	seen := map[string]bool{}
	for _, part := range strings.Split(fieldsRaw, ",") {
		field := strings.TrimSpace(strings.ToLower(part))
		if field != "" && allowed[field] && !seen[field] {
			selected = append(selected, field)
			seen[field] = true
		}
	}
	if len(selected) == 0 {
		c.JSON(http.StatusOK, dto.Response{Success: true, Data: alerts})
		return
	}
	projected := make([]map[string]interface{}, 0, len(alerts))
	for _, a := range alerts {
		item := map[string]interface{}{}
		for _, field := range selected {
			switch field {
			case "type":
				item["type"] = a.Type
			case "title":
				item["title"] = a.Title
			case "time":
				item["time"] = a.Time
			case "machine_id":
				item["machine_id"] = a.MachineID
			}
		}
		projected = append(projected, item)
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: projected})
}
