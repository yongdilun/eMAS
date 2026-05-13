package handler

import (
	"emas/internal/handler/dto"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type ReportsHandler struct {
	db *gorm.DB
}

func NewReportsHandler(db *gorm.DB) *ReportsHandler {
	return &ReportsHandler{db: db}
}

func minuteDiffSumExpr(db *gorm.DB, startCol, endCol string) string {
	switch db.Dialector.Name() {
	case "sqlite":
		return "COALESCE(SUM((julianday(" + endCol + ") - julianday(" + startCol + ")) * 24 * 60), 0)"
	default:
		return "COALESCE(SUM(TIMESTAMPDIFF(MINUTE, " + startCol + ", " + endCol + ")), 0)"
	}
}

func minuteDiffAvgExpr(db *gorm.DB, startCol, endCol string) string {
	switch db.Dialector.Name() {
	case "sqlite":
		return "AVG((julianday(" + endCol + ") - julianday(" + startCol + ")) * 24 * 60)"
	default:
		return "AVG(TIMESTAMPDIFF(MINUTE, " + startCol + ", " + endCol + "))"
	}
}

// @Summary Parse date range
// @Description Parse date range
// @Tags reports
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=time.Time}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/parse-date-range [get]
func (h *ReportsHandler) parseDateRange(c *gin.Context) (start, end time.Time, ok bool) {
	startStr := c.Query("start")
	endStr := c.Query("end")
	if startStr == "" || endStr == "" {
		end = time.Now()
		start = end.AddDate(0, 0, -30)
	} else {
		var err error
		if start, err = time.Parse(time.RFC3339, startStr); err != nil {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid start date (RFC3339)"})
			return time.Time{}, time.Time{}, false
		}
		if end, err = time.Parse(time.RFC3339, endStr); err != nil {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid end date (RFC3339)"})
			return time.Time{}, time.Time{}, false
		}
	}
	return start, end, true
}

// @Summary Production output per slot
// @Description Production output per slot
// @Tags reports
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/production-output [get]
func (h *ReportsHandler) ProductionOutputPerSlot(c *gin.Context) {
	start, end, ok := h.parseDateRange(c)
	if !ok {
		return
	}
	machineID := c.Query("machine_id")

	var results []struct {
		SlotID           string `json:"slot_id"`
		MachineID        string `json:"machine_id"`
		Date             string `json:"date"`
		QuantityProduced int    `json:"quantity_produced"`
		QuantityScrap    int    `json:"quantity_scrap"`
	}
	q := h.db.Table("production_logs").
		Select("production_logs.slot_id, job_step_schedule_slots.machine_id, DATE(production_logs.start_time) as date, COALESCE(SUM(production_logs.quantity_produced), 0) as quantity_produced, COALESCE(SUM(production_logs.quantity_scrap), 0) as quantity_scrap").
		Joins("JOIN job_step_schedule_slots ON job_step_schedule_slots.slot_id = production_logs.slot_id").
		Where("production_logs.start_time >= ? AND production_logs.start_time <= ?", start, end)
	if machineID != "" {
		q = q.Where("job_step_schedule_slots.machine_id = ?", machineID)
	}
	if err := q.Group("production_logs.slot_id, job_step_schedule_slots.machine_id, DATE(production_logs.start_time)").Scan(&results).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: results})
}

// @Summary Machine utilization
// @Description Machine utilization
// @Tags reports
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/machine-utilization [get]
func (h *ReportsHandler) MachineUtilization(c *gin.Context) {
	start, end, ok := h.parseDateRange(c)
	if !ok {
		return
	}

	var results []struct {
		MachineID    string  `json:"machine_id"`
		StepID       string  `json:"step_id"`
		TotalMinutes float64 `json:"total_minutes"`
		SlotCount    int     `json:"slot_count"`
	}
	if err := h.db.Table("job_step_schedule_slots").
		Select("machine_id, job_steps.step_id, "+minuteDiffSumExpr(h.db, "scheduled_start", "scheduled_end")+" as total_minutes, COUNT(*) as slot_count").
		Joins("JOIN job_steps ON job_steps.job_step_id = job_step_schedule_slots.job_step_id").
		Where("scheduled_start >= ? AND scheduled_end <= ?", start, end).
		Group("machine_id, job_steps.step_id").
		Scan(&results).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: results})
}

// @Summary Job completion
// @Description Job completion
// @Tags reports
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/job-completion [get]
func (h *ReportsHandler) JobCompletion(c *gin.Context) {
	start, end, ok := h.parseDateRange(c)
	if !ok {
		return
	}

	var results []struct {
		JobID            string `json:"job_id"`
		SlotID           string `json:"slot_id"`
		QuantityPlanned  int    `json:"quantity_planned"`
		QuantityProduced int    `json:"quantity_produced"`
	}
	if err := h.db.Table("job_step_schedule_slots").
		Select("jobs.job_id, job_step_schedule_slots.slot_id, job_step_schedule_slots.quantity_planned, COALESCE(SUM(production_logs.quantity_produced), 0) as quantity_produced").
		Joins("JOIN job_steps ON job_steps.job_step_id = job_step_schedule_slots.job_step_id").
		Joins("JOIN jobs ON jobs.job_id = job_steps.job_id").
		Joins("LEFT JOIN production_logs ON production_logs.slot_id = job_step_schedule_slots.slot_id").
		Where("job_step_schedule_slots.scheduled_start >= ? AND job_step_schedule_slots.scheduled_end <= ?", start, end).
		Group("jobs.job_id, job_step_schedule_slots.slot_id").
		Scan(&results).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: results})
}

// @Summary Inventory trends
// @Description Inventory trends
// @Tags reports
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/inventory-trends [get]
func (h *ReportsHandler) InventoryTrends(c *gin.Context) {
	start, end, ok := h.parseDateRange(c)
	if !ok {
		return
	}
	materialID := c.Query("material_id")

	var results []struct {
		MaterialID string  `json:"material_id"`
		Date       string  `json:"date"`
		NetQty     float64 `json:"net_qty"`
		TxCount    int     `json:"tx_count"`
	}
	q := h.db.Table("inventory_transactions").
		Select("material_id, DATE(timestamp) as date, SUM(CASE WHEN transaction_type = 'receive' THEN quantity ELSE -quantity END) as net_qty, COUNT(*) as tx_count").
		Where("timestamp >= ? AND timestamp <= ?", start, end)
	if materialID != "" {
		q = q.Where("material_id = ?", materialID)
	}
	if err := q.Group("material_id, DATE(timestamp)").Scan(&results).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: results})
}

// @Summary Quality trends
// @Description Quality trends
// @Tags reports
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/quality-trends [get]
func (h *ReportsHandler) QualityTrends(c *gin.Context) {
	start, end, ok := h.parseDateRange(c)
	if !ok {
		return
	}

	var results []struct {
		Date      string `json:"date"`
		PassCount int    `json:"pass_count"`
		FailCount int    `json:"fail_count"`
		DefectSum int    `json:"defect_sum"`
	}
	if err := h.db.Table("quality_inspection_records").
		Select("DATE(inspection_time) as date, SUM(CASE WHEN result = 'pass' THEN 1 ELSE 0 END) as pass_count, SUM(CASE WHEN result = 'fail' THEN 1 ELSE 0 END) as fail_count, COALESCE(SUM(defect_count), 0) as defect_sum").
		Where("inspection_time >= ? AND inspection_time <= ?", start, end).
		Group("DATE(inspection_time)").
		Scan(&results).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: results})
}

// @Summary OEE trends
// @Description OEE trends
// @Tags reports
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/oee-trends [get]
func (h *ReportsHandler) OEETrends(c *gin.Context) {
	start, end, ok := h.parseDateRange(c)
	if !ok {
		return
	}
	machineID := c.Query("machine_id")
	shiftName := c.Query("shift")

	var results []struct {
		MachineID    string  `json:"machine_id"`
		ShiftName    string  `json:"shift_name"`
		Date         string  `json:"date"`
		Availability float64 `json:"availability"`
		Performance  float64 `json:"performance"`
		Quality      float64 `json:"quality"`
		OEE          float64 `json:"oee"`
	}
	q := h.db.Table("job_step_schedule_slots").
		Select("job_step_schedule_slots.machine_id, COALESCE(machine_calendar.shift_name, '') as shift_name, DATE(job_step_schedule_slots.scheduled_start) as date, 100.0 as availability, 80.0 as performance, 95.0 as quality, 76.0 as oee").
		Joins("LEFT JOIN machine_calendar ON machine_calendar.machine_id = job_step_schedule_slots.machine_id AND job_step_schedule_slots.scheduled_start BETWEEN machine_calendar.start_time AND machine_calendar.end_time").
		Where("job_step_schedule_slots.scheduled_start >= ? AND job_step_schedule_slots.scheduled_end <= ?", start, end)
	if machineID != "" {
		q = q.Where("job_step_schedule_slots.machine_id = ?", machineID)
	}
	if shiftName != "" {
		q = q.Where("machine_calendar.shift_name = ?", shiftName)
	}
	if err := q.Group("job_step_schedule_slots.machine_id, shift_name, DATE(job_step_schedule_slots.scheduled_start)").Scan(&results).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	if len(results) == 0 {
		results = []struct {
			MachineID    string  `json:"machine_id"`
			ShiftName    string  `json:"shift_name"`
			Date         string  `json:"date"`
			Availability float64 `json:"availability"`
			Performance  float64 `json:"performance"`
			Quality      float64 `json:"quality"`
			OEE          float64 `json:"oee"`
		}{}
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: results})
}

// @Summary Bottleneck forecast
// @Description Bottleneck forecast
// @Tags reports
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/bottleneck-forecast [get]
func (h *ReportsHandler) BottleneckForecast(c *gin.Context) {
	var results []struct {
		MachineID   string  `json:"machine_id"`
		StepID      string  `json:"step_id"`
		QueueCount  int     `json:"queue_count"`
		Utilization float64 `json:"utilization"`
		Forecast    string  `json:"forecast"`
	}
	if err := h.db.Table("machines").
		Select("machines.machine_id, machine_capabilities.step_id, 0 as queue_count, machines.utilization_rate as utilization, 'normal' as forecast").
		Joins("LEFT JOIN machine_capabilities ON machine_capabilities.machine_id = machines.machine_id").
		Scan(&results).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: results})
}

// @Summary Maintenance efficiency
// @Description Maintenance efficiency
// @Tags reports
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/maintenance-efficiency [get]
func (h *ReportsHandler) MaintenanceEfficiency(c *gin.Context) {
	start, end, ok := h.parseDateRange(c)
	if !ok {
		return
	}

	var results []struct {
		MachineID   string  `json:"machine_id"`
		Planned     int     `json:"planned_count"`
		Completed   int     `json:"completed_count"`
		AvgDuration float64 `json:"avg_duration_minutes"`
	}
	if err := h.db.Table("maintenance_records").
		Select("machine_id, COUNT(*) as planned_count, COUNT(*) as completed_count, "+minuteDiffAvgExpr(h.db, "start_time", "end_time")+" as avg_duration_minutes").
		Where("start_time >= ? AND end_time <= ?", start, end).
		Group("machine_id").
		Scan(&results).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: results})
}
