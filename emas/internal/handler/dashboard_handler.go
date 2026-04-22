package handler

import (
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"net/http"
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
	OEEPct           float64 `json:"oee_pct"`
	OEEChange        float64 `json:"oee_change"`
	ProductionUnits  int     `json:"production_units"`
	ProductionChange float64 `json:"production_change"`
	DowntimeHrs      float64 `json:"downtime_hrs"`
	DowntimeChange   float64 `json:"downtime_change"`
	UtilizationPct   float64 `json:"utilization_pct"`
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
		OEEPct:           85.2,
		OEEChange:        1.5,
		ProductionUnits:  10450,
		ProductionChange: 5.0,
		DowntimeHrs:      2.1,
		DowntimeChange:   0.2,
		UtilizationPct:   78.0,
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
// @Success 200 {object} dto.Response{data=[]AlertItem}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /dashboard/alerts [get]
func (h *DashboardHandler) GetAlerts(c *gin.Context) {
	status := c.Query("status")
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

	if status == "active" && len(alerts) == 0 {
		alerts = []AlertItem{}
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: alerts})
}
