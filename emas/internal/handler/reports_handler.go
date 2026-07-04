package handler

import (
	"bytes"
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"fmt"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/signintech/gopdf"
	"gorm.io/gorm"
)

const (
	reportDateLayout = "2006-01-02"
	reportFontFamily = "report"
)

type ReportsHandler struct {
	db *gorm.DB
}

func NewReportsHandler(db *gorm.DB) *ReportsHandler {
	return &ReportsHandler{db: db}
}

type ProductionOutputReportRow struct {
	SlotID           string `json:"slot_id"`
	MachineID        string `json:"machine_id"`
	JobID            string `json:"job_id"`
	ProductID        string `json:"product_id"`
	Date             string `json:"date"`
	QuantityPlanned  int    `json:"quantity_planned"`
	QuantityProduced int    `json:"quantity_produced"`
	QuantityScrap    int    `json:"quantity_scrap"`
}

type MachineUtilizationReportRow struct {
	MachineID       string  `json:"machine_id"`
	MachineName     string  `json:"machine_name"`
	TotalMinutes    float64 `json:"total_minutes"`
	DowntimeMinutes float64 `json:"downtime_minutes"`
	UtilizationPct  float64 `json:"utilization_pct"`
	SlotCount       int     `json:"slot_count"`
}

type JobCompletionReportRow struct {
	JobID             string  `json:"job_id"`
	SlotID            string  `json:"slot_id"`
	ProductID         string  `json:"product_id"`
	Status            string  `json:"status"`
	QuantityPlanned   int     `json:"quantity_planned"`
	QuantityProduced  int     `json:"quantity_produced"`
	QuantityTotal     int     `json:"quantity_total"`
	QuantityCompleted int     `json:"quantity_completed"`
	SlotCount         int     `json:"slot_count"`
	CompletionPct     float64 `json:"completion_pct"`
}

type InventoryTrendReportRow struct {
	MaterialID string  `json:"material_id"`
	Date       string  `json:"date"`
	NetQty     float64 `json:"net_qty"`
	TxCount    int     `json:"tx_count"`
}

type QualityTrendReportRow struct {
	Date      string  `json:"date"`
	PassCount int     `json:"pass_count"`
	FailCount int     `json:"fail_count"`
	DefectSum int     `json:"defect_sum"`
	PassRate  float64 `json:"pass_rate"`
}

type OEETrendReportRow struct {
	MachineID    string  `json:"machine_id"`
	ShiftName    string  `json:"shift_name"`
	Date         string  `json:"date"`
	Availability float64 `json:"availability"`
	Performance  float64 `json:"performance"`
	Quality      float64 `json:"quality"`
	OEE          float64 `json:"oee"`
}

type BottleneckReportRow struct {
	MachineID   string  `json:"machine_id"`
	StepID      string  `json:"step_id"`
	QueueCount  int     `json:"queue_count"`
	Utilization float64 `json:"utilization"`
	Forecast    string  `json:"forecast"`
}

type DowntimeReportRow struct {
	MachineID       string  `json:"machine_id"`
	Cause           string  `json:"cause"`
	Date            string  `json:"date"`
	DurationMinutes float64 `json:"duration_minutes"`
	DowntimeHours   float64 `json:"downtime_hours"`
	OccurrenceCount int     `json:"occurrence_count"`
}

type MaintenanceEfficiencyReportRow struct {
	MachineID          string  `json:"machine_id"`
	PlannedCount       int     `json:"planned_count"`
	CompletedCount     int     `json:"completed_count"`
	AvgDurationMinutes float64 `json:"avg_duration_minutes"`
}

type ProductionAnalyticsSummary struct {
	TotalOutput       int     `json:"total_output"`
	TotalScrap        int     `json:"total_scrap"`
	ScrapRate         float64 `json:"scrap_rate"`
	DowntimeHours     float64 `json:"downtime_hours"`
	AvgUtilizationPct float64 `json:"avg_utilization_pct"`
	TotalJobs         int     `json:"total_jobs"`
	CompletedJobs     int     `json:"completed_jobs"`
	InProgressJobs    int     `json:"in_progress_jobs"`
	ScheduledJobs     int     `json:"scheduled_jobs"`
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

func (h *ReportsHandler) parseDateRange(c *gin.Context) (start, end time.Time, ok bool) {
	startStr := c.Query("start")
	endStr := c.Query("end")
	end = time.Now().UTC()
	start = end.AddDate(0, 0, -30)
	var err error
	if startStr != "" {
		if start, err = time.Parse(time.RFC3339, startStr); err != nil {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid start date (RFC3339)"})
			return time.Time{}, time.Time{}, false
		}
	}
	if endStr != "" {
		if end, err = time.Parse(time.RFC3339, endStr); err != nil {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid end date (RFC3339)"})
			return time.Time{}, time.Time{}, false
		}
	}
	if !end.After(start) {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "end date must be after start date"})
		return time.Time{}, time.Time{}, false
	}
	return start.UTC(), end.UTC(), true
}

func round1(v float64) float64 {
	return math.Round(v*10) / 10
}

func pct(numerator, denominator float64) float64 {
	if denominator <= 0 {
		return 0
	}
	return round1((numerator / denominator) * 100)
}

func capPct(v float64) float64 {
	if v < 0 {
		return 0
	}
	if v > 100 {
		return 100
	}
	return round1(v)
}

func filterQuery(c *gin.Context, q *gorm.DB) *gorm.DB {
	if machineID := strings.TrimSpace(c.Query("machine_id")); machineID != "" {
		q = q.Where("job_step_schedule_slots.machine_id = ?", machineID)
	}
	if jobID := strings.TrimSpace(c.Query("job_id")); jobID != "" {
		q = q.Where("jobs.job_id = ?", jobID)
	}
	if productID := strings.TrimSpace(c.Query("product_id")); productID != "" {
		q = q.Where("jobs.product_id = ?", productID)
	}
	return q
}

func (h *ReportsHandler) productionOutputRows(c *gin.Context, start, end time.Time) ([]ProductionOutputReportRow, error) {
	var rows []ProductionOutputReportRow
	q := h.db.Table("production_logs").
		Select("production_logs.slot_id, job_step_schedule_slots.machine_id, jobs.job_id, jobs.product_id, DATE(production_logs.start_time) as date, MAX(job_step_schedule_slots.quantity_planned) as quantity_planned, COALESCE(SUM(production_logs.quantity_produced), 0) as quantity_produced, COALESCE(SUM(production_logs.quantity_scrap), 0) as quantity_scrap").
		Joins("JOIN job_step_schedule_slots ON job_step_schedule_slots.slot_id = production_logs.slot_id").
		Joins("JOIN job_steps ON job_steps.job_step_id = job_step_schedule_slots.job_step_id").
		Joins("JOIN jobs ON jobs.job_id = job_steps.job_id").
		Where("production_logs.start_time >= ? AND production_logs.start_time <= ?", start, end)
	q = filterQuery(c, q)
	err := q.Group("production_logs.slot_id, job_step_schedule_slots.machine_id, jobs.job_id, jobs.product_id, DATE(production_logs.start_time)").
		Order("date ASC, production_logs.slot_id ASC").
		Scan(&rows).Error
	return rows, err
}

func (h *ReportsHandler) machineUtilizationRows(c *gin.Context, start, end time.Time) ([]MachineUtilizationReportRow, error) {
	var raw []struct {
		MachineID       string  `json:"machine_id"`
		MachineName     string  `json:"machine_name"`
		TotalMinutes    float64 `json:"total_minutes"`
		DowntimeMinutes float64 `json:"downtime_minutes"`
		SlotCount       int     `json:"slot_count"`
	}
	q := h.db.Table("production_logs").
		Select("job_step_schedule_slots.machine_id, COALESCE(machines.machine_name, job_step_schedule_slots.machine_id) as machine_name, "+minuteDiffSumExpr(h.db, "production_logs.start_time", "production_logs.end_time")+" as total_minutes, COALESCE(SUM(production_logs.downtime_minutes), 0) as downtime_minutes, COUNT(DISTINCT production_logs.slot_id) as slot_count").
		Joins("JOIN job_step_schedule_slots ON job_step_schedule_slots.slot_id = production_logs.slot_id").
		Joins("JOIN job_steps ON job_steps.job_step_id = job_step_schedule_slots.job_step_id").
		Joins("JOIN jobs ON jobs.job_id = job_steps.job_id").
		Joins("LEFT JOIN machines ON machines.machine_id = job_step_schedule_slots.machine_id").
		Where("production_logs.start_time >= ? AND production_logs.start_time <= ?", start, end)
	q = filterQuery(c, q)
	if err := q.Group("job_step_schedule_slots.machine_id, machines.machine_name").
		Order("job_step_schedule_slots.machine_id ASC").
		Scan(&raw).Error; err != nil {
		return nil, err
	}
	rangeMinutes := end.Sub(start).Minutes()
	rows := make([]MachineUtilizationReportRow, 0, len(raw))
	for _, row := range raw {
		utilization := 0.0
		if rangeMinutes > 0 {
			utilization = pct(row.TotalMinutes, rangeMinutes)
		}
		rows = append(rows, MachineUtilizationReportRow{
			MachineID:       row.MachineID,
			MachineName:     row.MachineName,
			TotalMinutes:    round1(row.TotalMinutes),
			DowntimeMinutes: round1(row.DowntimeMinutes),
			UtilizationPct:  capPct(utilization),
			SlotCount:       row.SlotCount,
		})
	}
	return rows, nil
}

func (h *ReportsHandler) jobCompletionRows(c *gin.Context, start, end time.Time) ([]JobCompletionReportRow, error) {
	var raw []struct {
		JobID             string `json:"job_id"`
		SlotID            string `json:"slot_id"`
		ProductID         string `json:"product_id"`
		Status            string `json:"status"`
		QuantityTotal     int    `json:"quantity_total"`
		QuantityCompleted int    `json:"quantity_completed"`
		SlotCount         int    `json:"slot_count"`
	}
	q := h.db.Table("jobs").
		Select("jobs.job_id, MIN(job_step_schedule_slots.slot_id) as slot_id, jobs.product_id, jobs.status, jobs.quantity_total, jobs.quantity_completed, COUNT(DISTINCT job_step_schedule_slots.slot_id) as slot_count").
		Joins("JOIN job_steps ON job_steps.job_id = jobs.job_id").
		Joins("JOIN job_step_schedule_slots ON job_step_schedule_slots.job_step_id = job_steps.job_step_id").
		Joins("JOIN production_logs ON production_logs.slot_id = job_step_schedule_slots.slot_id").
		Where("production_logs.start_time >= ? AND production_logs.start_time <= ?", start, end)
	q = filterQuery(c, q)
	if err := q.Group("jobs.job_id, jobs.product_id, jobs.status, jobs.quantity_total, jobs.quantity_completed").
		Order("MAX(production_logs.start_time) ASC, jobs.job_id ASC").
		Scan(&raw).Error; err != nil {
		return nil, err
	}
	rows := make([]JobCompletionReportRow, 0, len(raw))
	for _, row := range raw {
		rows = append(rows, JobCompletionReportRow{
			JobID:             row.JobID,
			SlotID:            row.SlotID,
			ProductID:         row.ProductID,
			Status:            row.Status,
			QuantityPlanned:   row.QuantityTotal,
			QuantityProduced:  row.QuantityCompleted,
			QuantityTotal:     row.QuantityTotal,
			QuantityCompleted: row.QuantityCompleted,
			SlotCount:         row.SlotCount,
			CompletionPct:     capPct(pct(float64(row.QuantityCompleted), float64(row.QuantityTotal))),
		})
	}
	return rows, nil
}

func productionJobCompletionBucket(status string, planned, completed int) string {
	switch strings.ToLower(strings.TrimSpace(status)) {
	case domain.JobStatusCompleted:
		return domain.JobStatusCompleted
	case domain.JobStatusPlanned, domain.JobStatusScheduled:
		if completed > 0 {
			return domain.JobStatusRunning
		}
		return domain.JobStatusScheduled
	case domain.JobStatusRunning, domain.JobStatusPaused, domain.JobStatusBlocked:
		return domain.JobStatusRunning
	case domain.JobStatusCancelled:
		return domain.JobStatusCancelled
	}
	if planned > 0 && completed >= planned {
		return domain.JobStatusCompleted
	}
	if completed > 0 {
		return domain.JobStatusRunning
	}
	return domain.JobStatusScheduled
}

func (h *ReportsHandler) inventoryTrendRows(c *gin.Context, start, end time.Time) ([]InventoryTrendReportRow, error) {
	materialID := strings.TrimSpace(c.Query("material_id"))
	var rows []InventoryTrendReportRow
	q := h.db.Table("inventory_transactions").
		Select("material_id, DATE(timestamp) as date, SUM(CASE WHEN transaction_type = 'receive' THEN quantity ELSE -quantity END) as net_qty, COUNT(*) as tx_count").
		Where("timestamp >= ? AND timestamp <= ?", start, end)
	if materialID != "" {
		q = q.Where("material_id = ?", materialID)
	}
	err := q.Group("material_id, DATE(timestamp)").Order("date ASC, material_id ASC").Scan(&rows).Error
	return rows, err
}

func (h *ReportsHandler) qualityTrendRows(c *gin.Context, start, end time.Time) ([]QualityTrendReportRow, error) {
	var raw []struct {
		Date      string `json:"date"`
		PassCount int    `json:"pass_count"`
		FailCount int    `json:"fail_count"`
		DefectSum int    `json:"defect_sum"`
	}
	if err := h.db.Table("quality_inspection_records").
		Select("DATE(inspection_time) as date, SUM(CASE WHEN result = 'pass' THEN 1 ELSE 0 END) as pass_count, SUM(CASE WHEN result = 'fail' THEN 1 ELSE 0 END) as fail_count, COALESCE(SUM(defect_count), 0) as defect_sum").
		Where("inspection_time >= ? AND inspection_time <= ?", start, end).
		Group("DATE(inspection_time)").
		Order("date ASC").
		Scan(&raw).Error; err != nil {
		return nil, err
	}
	rows := make([]QualityTrendReportRow, 0, len(raw))
	for _, row := range raw {
		total := row.PassCount + row.FailCount
		rows = append(rows, QualityTrendReportRow{
			Date:      row.Date,
			PassCount: row.PassCount,
			FailCount: row.FailCount,
			DefectSum: row.DefectSum,
			PassRate:  capPct(pct(float64(row.PassCount), float64(total))),
		})
	}
	return rows, nil
}

func (h *ReportsHandler) oeeTrendRows(c *gin.Context, start, end time.Time) ([]OEETrendReportRow, error) {
	machineID := strings.TrimSpace(c.Query("machine_id"))
	shiftName := strings.TrimSpace(c.Query("shift"))
	var raw []struct {
		MachineID        string  `json:"machine_id"`
		ShiftName        string  `json:"shift_name"`
		Date             string  `json:"date"`
		SlotID           string  `json:"slot_id"`
		RuntimeMinutes   float64 `json:"runtime_minutes"`
		DowntimeMinutes  float64 `json:"downtime_minutes"`
		QuantityPlanned  int     `json:"quantity_planned"`
		QuantityProduced int     `json:"quantity_produced"`
		QuantityScrap    int     `json:"quantity_scrap"`
	}
	q := h.db.Table("production_logs").
		Select("job_step_schedule_slots.machine_id, COALESCE(machine_calendar.shift_name, '') as shift_name, DATE(production_logs.start_time) as date, production_logs.slot_id, "+minuteDiffSumExpr(h.db, "production_logs.start_time", "production_logs.end_time")+" as runtime_minutes, COALESCE(SUM(production_logs.downtime_minutes), 0) as downtime_minutes, MAX(job_step_schedule_slots.quantity_planned) as quantity_planned, COALESCE(SUM(production_logs.quantity_produced), 0) as quantity_produced, COALESCE(SUM(production_logs.quantity_scrap), 0) as quantity_scrap").
		Joins("JOIN job_step_schedule_slots ON job_step_schedule_slots.slot_id = production_logs.slot_id").
		Joins("LEFT JOIN machine_calendar ON machine_calendar.machine_id = job_step_schedule_slots.machine_id AND production_logs.start_time BETWEEN machine_calendar.start_time AND machine_calendar.end_time").
		Where("production_logs.start_time >= ? AND production_logs.start_time <= ?", start, end)
	if machineID != "" {
		q = q.Where("job_step_schedule_slots.machine_id = ?", machineID)
	}
	if shiftName != "" {
		q = q.Where("machine_calendar.shift_name = ?", shiftName)
	}
	if err := q.Group("job_step_schedule_slots.machine_id, shift_name, DATE(production_logs.start_time), production_logs.slot_id").
		Order("date ASC, job_step_schedule_slots.machine_id ASC").
		Scan(&raw).Error; err != nil {
		return nil, err
	}
	type agg struct {
		machineID string
		shiftName string
		date      string
		runtime   float64
		downtime  float64
		planned   int
		produced  int
		scrap     int
	}
	byKey := map[string]*agg{}
	order := []string{}
	for _, row := range raw {
		key := row.MachineID + "\x00" + row.ShiftName + "\x00" + row.Date
		if byKey[key] == nil {
			byKey[key] = &agg{machineID: row.MachineID, shiftName: row.ShiftName, date: row.Date}
			order = append(order, key)
		}
		a := byKey[key]
		a.runtime += row.RuntimeMinutes
		a.downtime += row.DowntimeMinutes
		a.planned += row.QuantityPlanned
		a.produced += row.QuantityProduced
		a.scrap += row.QuantityScrap
	}
	rows := make([]OEETrendReportRow, 0, len(order))
	for _, key := range order {
		a := byKey[key]
		availability := capPct(pct(a.runtime, a.runtime+a.downtime))
		performance := capPct(pct(float64(a.produced), float64(a.planned)))
		quality := capPct(pct(float64(a.produced), float64(a.produced+a.scrap)))
		oee := round1((availability * performance * quality) / 10000)
		rows = append(rows, OEETrendReportRow{
			MachineID:    a.machineID,
			ShiftName:    a.shiftName,
			Date:         a.date,
			Availability: availability,
			Performance:  performance,
			Quality:      quality,
			OEE:          oee,
		})
	}
	return rows, nil
}

func (h *ReportsHandler) bottleneckRows(c *gin.Context, start, end time.Time) ([]BottleneckReportRow, error) {
	var raw []struct {
		MachineID        string  `json:"machine_id"`
		StepID           string  `json:"step_id"`
		QueueCount       int     `json:"queue_count"`
		ScheduledMinutes float64 `json:"scheduled_minutes"`
	}
	q := h.db.Table("job_step_schedule_slots").
		Select("job_step_schedule_slots.machine_id, job_steps.step_id, COUNT(*) as queue_count, "+minuteDiffSumExpr(h.db, "job_step_schedule_slots.scheduled_start", "job_step_schedule_slots.scheduled_end")+" as scheduled_minutes").
		Joins("JOIN job_steps ON job_steps.job_step_id = job_step_schedule_slots.job_step_id").
		Joins("JOIN jobs ON jobs.job_id = job_steps.job_id").
		Where("job_step_schedule_slots.scheduled_start >= ? AND job_step_schedule_slots.scheduled_end <= ?", start, end).
		Where("job_step_schedule_slots.status IN ?", []string{"planned", "running", "paused"})
	q = filterQuery(c, q)
	if err := q.Group("job_step_schedule_slots.machine_id, job_steps.step_id").
		Order("queue_count DESC, scheduled_minutes DESC").
		Scan(&raw).Error; err != nil {
		return nil, err
	}
	rangeMinutes := end.Sub(start).Minutes()
	rows := make([]BottleneckReportRow, 0, len(raw))
	for _, row := range raw {
		utilization := 0.0
		if rangeMinutes > 0 {
			utilization = capPct(pct(row.ScheduledMinutes, rangeMinutes))
		}
		forecast := "normal"
		if row.QueueCount >= 4 || utilization >= 85 {
			forecast = "high"
		} else if row.QueueCount >= 2 || utilization >= 60 {
			forecast = "elevated"
		}
		rows = append(rows, BottleneckReportRow{
			MachineID:   row.MachineID,
			StepID:      row.StepID,
			QueueCount:  row.QueueCount,
			Utilization: utilization,
			Forecast:    forecast,
		})
	}
	return rows, nil
}

func (h *ReportsHandler) downtimeRows(c *gin.Context, start, end time.Time) ([]DowntimeReportRow, error) {
	machineID := strings.TrimSpace(c.Query("machine_id"))
	var raw []struct {
		MachineID       string  `json:"machine_id"`
		Cause           string  `json:"cause"`
		Date            string  `json:"date"`
		DurationMinutes float64 `json:"duration_minutes"`
		OccurrenceCount int     `json:"occurrence_count"`
	}
	q := h.db.Table("machine_downtime").
		Select("machine_id, COALESCE(NULLIF(cause, ''), 'Unspecified') as cause, DATE(start_time) as date, COALESCE(SUM(duration_minutes), 0) as duration_minutes, COUNT(*) as occurrence_count").
		Where("start_time >= ? AND end_time <= ?", start, end)
	if machineID != "" {
		q = q.Where("machine_id = ?", machineID)
	}
	if err := q.Group("machine_id, cause, DATE(start_time)").Order("date ASC, machine_id ASC").Scan(&raw).Error; err != nil {
		return nil, err
	}
	rows := make([]DowntimeReportRow, 0, len(raw))
	for _, row := range raw {
		rows = append(rows, DowntimeReportRow{
			MachineID:       row.MachineID,
			Cause:           row.Cause,
			Date:            row.Date,
			DurationMinutes: round1(row.DurationMinutes),
			DowntimeHours:   round1(row.DurationMinutes / 60),
			OccurrenceCount: row.OccurrenceCount,
		})
	}
	return rows, nil
}

func (h *ReportsHandler) maintenanceEfficiencyRows(c *gin.Context, start, end time.Time) ([]MaintenanceEfficiencyReportRow, error) {
	machineID := strings.TrimSpace(c.Query("machine_id"))
	var rows []MaintenanceEfficiencyReportRow
	q := h.db.Table("maintenance_records").
		Select("machine_id, COUNT(*) as planned_count, COUNT(*) as completed_count, "+minuteDiffAvgExpr(h.db, "start_time", "end_time")+" as avg_duration_minutes").
		Where("start_time >= ? AND end_time <= ?", start, end)
	if machineID != "" {
		q = q.Where("machine_id = ?", machineID)
	}
	err := q.Group("machine_id").Order("machine_id ASC").Scan(&rows).Error
	for i := range rows {
		rows[i].AvgDurationMinutes = round1(rows[i].AvgDurationMinutes)
	}
	return rows, err
}

func reportFilename(reportType string, start, end time.Time) string {
	return fmt.Sprintf("%s-%s-%s.pdf", reportType, start.Format(reportDateLayout), end.Format(reportDateLayout))
}

func reportDisposition(c *gin.Context, filename string) string {
	mode := "inline"
	download := strings.TrimSpace(strings.ToLower(c.Query("download")))
	if download == "1" || download == "true" || download == "yes" {
		mode = "attachment"
	}
	return fmt.Sprintf(`%s; filename="%s"`, mode, filename)
}

func reportFontPath() (string, error) {
	candidates := []string{
		filepath.Join(os.Getenv("WINDIR"), "Fonts", "arial.ttf"),
		"C:\\Windows\\Fonts\\arial.ttf",
		"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
		"/usr/share/fonts/dejavu/DejaVuSans.ttf",
		"/Library/Fonts/Arial.ttf",
	}
	for _, path := range candidates {
		if path == "" {
			continue
		}
		if _, err := os.Stat(path); err == nil {
			return path, nil
		}
	}
	return "", fmt.Errorf("no usable TTF font found for PDF reports")
}

func cleanPDFText(value string, max int) string {
	value = strings.TrimSpace(strings.NewReplacer("\r", " ", "\n", " ", "\t", " ").Replace(value))
	if value == "" {
		return "-"
	}
	if max > 0 && len(value) > max {
		return value[:max-1] + "."
	}
	return value
}

type reportChartPoint struct {
	Label   string
	Value   float64
	Display string
}

type reportChartSummary struct {
	Title       string
	ValueIndex  int
	IsPercent   bool
	Points      []reportChartPoint
	AllValues   []float64
	DisplayName string
}

type reportMetric struct {
	Label string
	Value string
}

func reportFormattedTime(t time.Time) string {
	return t.UTC().Format("02 Jan 2006 15:04 UTC")
}

func reportDateSpan(start, end time.Time) string {
	hours := end.Sub(start).Hours()
	if hours <= 0 {
		return "0 days"
	}
	days := int(math.Ceil(hours / 24))
	if days < 1 {
		days = 1
	}
	if days == 1 {
		return "1 day"
	}
	return fmt.Sprintf("%d days", days)
}

func parseReportFloat(value string) (float64, bool) {
	value = strings.TrimSpace(value)
	value = strings.TrimSuffix(value, "%")
	value = strings.ReplaceAll(value, ",", "")
	if value == "" || value == "-" {
		return 0, false
	}
	parsed, err := strconv.ParseFloat(value, 64)
	if err != nil || math.IsNaN(parsed) || math.IsInf(parsed, 0) {
		return 0, false
	}
	return parsed, true
}

func reportValueHeaderScore(header string) int {
	lower := strings.ToLower(header)
	switch {
	case strings.Contains(lower, "utilization"):
		return 110
	case strings.Contains(lower, "oee"):
		return 108
	case strings.Contains(lower, "complete"), strings.Contains(lower, "pass rate"):
		return 104
	case strings.Contains(lower, "availability"), strings.Contains(lower, "performance"), strings.Contains(lower, "quality"):
		return 100
	case strings.Contains(lower, "produced"), strings.Contains(lower, "output"):
		return 92
	case strings.Contains(lower, "net"):
		return 88
	case strings.Contains(lower, "minutes"), strings.Contains(lower, "hours"), strings.Contains(lower, "duration"):
		return 84
	case strings.Contains(lower, "completed"):
		return 78
	case strings.Contains(lower, "planned"):
		return 72
	case strings.Contains(lower, "scrap"), strings.Contains(lower, "defect"), strings.Contains(lower, "fail"):
		return 68
	case strings.Contains(lower, "events"), strings.Contains(lower, "transactions"), strings.Contains(lower, "slots"), strings.Contains(lower, "queue"):
		return 60
	case strings.Contains(lower, "qty"), strings.Contains(lower, "count"):
		return 55
	default:
		return 10
	}
}

func reportLabelHeaderScore(header string) int {
	lower := strings.ToLower(header)
	switch {
	case strings.Contains(lower, "cause"):
		return 105
	case strings.Contains(lower, "machine") && !strings.Contains(lower, "id"):
		return 100
	case strings.Contains(lower, "job") && !strings.Contains(lower, "id"):
		return 95
	case strings.Contains(lower, "job"):
		return 90
	case strings.Contains(lower, "product"):
		return 84
	case strings.Contains(lower, "material"):
		return 82
	case strings.Contains(lower, "date"):
		return 78
	case strings.Contains(lower, "step"):
		return 70
	case strings.Contains(lower, "slot"):
		return 65
	case strings.Contains(lower, "machine"):
		return 60
	default:
		return 25
	}
}

func reportPreferredValueColumn(headers []string, rows [][]string) (int, bool) {
	bestIndex := -1
	bestScore := -1
	for i, header := range headers {
		numericCount := 0
		for _, row := range rows {
			if i >= len(row) {
				continue
			}
			if _, ok := parseReportFloat(row[i]); ok {
				numericCount++
			}
		}
		if numericCount == 0 {
			continue
		}
		score := reportValueHeaderScore(header) + numericCount
		if score > bestScore {
			bestScore = score
			bestIndex = i
		}
	}
	return bestIndex, bestIndex >= 0
}

func reportPreferredLabelColumn(headers []string, rows [][]string, valueIndex int) int {
	bestIndex := -1
	bestScore := -1
	for i, header := range headers {
		if i == valueIndex {
			continue
		}
		textCount := 0
		for _, row := range rows {
			if i >= len(row) {
				continue
			}
			if _, ok := parseReportFloat(row[i]); !ok && strings.TrimSpace(row[i]) != "" {
				textCount++
			}
		}
		if textCount == 0 {
			continue
		}
		score := reportLabelHeaderScore(header) + textCount
		if score > bestScore {
			bestScore = score
			bestIndex = i
		}
	}
	return bestIndex
}

func buildReportChart(headers []string, rows [][]string) reportChartSummary {
	valueIndex, ok := reportPreferredValueColumn(headers, rows)
	if !ok || valueIndex >= len(headers) {
		return reportChartSummary{ValueIndex: -1}
	}
	labelIndex := reportPreferredLabelColumn(headers, rows, valueIndex)
	valueHeader := headers[valueIndex]
	isPercent := strings.Contains(strings.ToLower(valueHeader), "%") || strings.Contains(rowsValueSample(rows, valueIndex), "%") ||
		strings.Contains(strings.ToLower(valueHeader), "utilization") || strings.Contains(strings.ToLower(valueHeader), "rate") ||
		strings.Contains(strings.ToLower(valueHeader), "oee") || strings.Contains(strings.ToLower(valueHeader), "availability") ||
		strings.Contains(strings.ToLower(valueHeader), "performance") || strings.Contains(strings.ToLower(valueHeader), "quality") ||
		strings.Contains(strings.ToLower(valueHeader), "complete")
	points := make([]reportChartPoint, 0, 7)
	allValues := make([]float64, 0, len(rows))
	for rowIndex, row := range rows {
		if valueIndex >= len(row) {
			continue
		}
		value, ok := parseReportFloat(row[valueIndex])
		if !ok {
			continue
		}
		allValues = append(allValues, value)
		if len(points) >= 7 {
			continue
		}
		label := fmt.Sprintf("Row %d", rowIndex+1)
		if labelIndex >= 0 && labelIndex < len(row) {
			label = row[labelIndex]
		}
		points = append(points, reportChartPoint{
			Label:   cleanPDFText(label, 28),
			Value:   math.Max(value, 0),
			Display: cleanPDFText(row[valueIndex], 16),
		})
	}
	if len(points) == 0 || len(allValues) == 0 {
		return reportChartSummary{ValueIndex: -1}
	}
	return reportChartSummary{
		Title:       valueHeader,
		ValueIndex:  valueIndex,
		IsPercent:   isPercent,
		Points:      points,
		AllValues:   allValues,
		DisplayName: valueHeader,
	}
}

func rowsValueSample(rows [][]string, index int) string {
	for _, row := range rows {
		if index < len(row) && strings.TrimSpace(row[index]) != "" {
			return row[index]
		}
	}
	return ""
}

func reportSummaryMetrics(start, end time.Time, rows [][]string, chart reportChartSummary) []reportMetric {
	metrics := []reportMetric{
		{Label: "Records", Value: fmt.Sprintf("%d", len(rows))},
		{Label: "Period", Value: reportDateSpan(start, end)},
	}
	if len(chart.AllValues) > 0 {
		total := 0.0
		maxValue := chart.AllValues[0]
		for _, value := range chart.AllValues {
			total += value
			if value > maxValue {
				maxValue = value
			}
		}
		if chart.IsPercent {
			metrics = append(metrics, reportMetric{Label: "Average " + chart.DisplayName, Value: fmt.Sprintf("%.1f%%", total/float64(len(chart.AllValues)))})
		} else {
			metrics = append(metrics, reportMetric{Label: "Total " + chart.DisplayName, Value: fmt.Sprintf("%.1f", total)})
		}
		metrics = append(metrics, reportMetric{Label: "Peak " + chart.DisplayName, Value: reportMetricValue(maxValue, chart.IsPercent)})
	}
	if len(metrics) > 4 {
		return metrics[:4]
	}
	return metrics
}

func reportMetricValue(value float64, isPercent bool) string {
	if isPercent {
		return fmt.Sprintf("%.1f%%", value)
	}
	if math.Abs(value-math.Round(value)) < 0.05 {
		return fmt.Sprintf("%.0f", value)
	}
	return fmt.Sprintf("%.1f", value)
}

func reportColumnWidths(headers []string, totalWidth float64) []float64 {
	if len(headers) == 0 {
		return []float64{totalWidth}
	}
	weights := make([]float64, len(headers))
	totalWeight := 0.0
	for i, header := range headers {
		lower := strings.ToLower(header)
		weight := 1.0
		switch {
		case strings.Contains(lower, "forecast"), strings.Contains(lower, "cause"):
			weight = 1.65
		case strings.Contains(lower, "machine") && !strings.Contains(lower, "id"):
			weight = 1.55
		case strings.Contains(lower, "slot"), strings.Contains(lower, "job"), strings.Contains(lower, "product"), strings.Contains(lower, "material"), strings.Contains(lower, "shift"):
			weight = 1.18
		case strings.Contains(lower, "date"):
			weight = 1.05
		case strings.Contains(lower, "utilization"), strings.Contains(lower, "availability"), strings.Contains(lower, "performance"), strings.Contains(lower, "quality"), strings.Contains(lower, "complete"), strings.Contains(lower, "rate"):
			weight = 0.95
		case strings.Contains(lower, "planned"), strings.Contains(lower, "produced"), strings.Contains(lower, "scrap"), strings.Contains(lower, "pass"), strings.Contains(lower, "fail"), strings.Contains(lower, "defect"), strings.Contains(lower, "slots"), strings.Contains(lower, "events"), strings.Contains(lower, "queue"):
			weight = 0.78
		}
		weights[i] = weight
		totalWeight += weight
	}
	widths := make([]float64, len(headers))
	for i, weight := range weights {
		widths[i] = totalWidth * (weight / totalWeight)
	}
	return widths
}

func reportMaxChars(width float64, fontSize float64) int {
	return int(math.Max(4, math.Floor((width-8)/(fontSize*0.48))))
}

func reportCellAlign(header string, value string) int {
	if _, ok := parseReportFloat(value); ok {
		return gopdf.Right | gopdf.Middle
	}
	lower := strings.ToLower(header)
	if strings.Contains(lower, "planned") || strings.Contains(lower, "produced") || strings.Contains(lower, "scrap") ||
		strings.Contains(lower, "pass") || strings.Contains(lower, "fail") || strings.Contains(lower, "defect") ||
		strings.Contains(lower, "slots") || strings.Contains(lower, "events") || strings.Contains(lower, "queue") ||
		strings.Contains(lower, "min") || strings.Contains(lower, "hours") || strings.Contains(lower, "%") {
		return gopdf.Right | gopdf.Middle
	}
	return gopdf.Left | gopdf.Middle
}

func renderReportPDF(title string, start, end time.Time, headers []string, rows [][]string) ([]byte, error) {
	fontPath, err := reportFontPath()
	if err != nil {
		return nil, err
	}
	pdf := gopdf.GoPdf{}
	pdf.Start(gopdf.Config{PageSize: *gopdf.PageSizeA4})
	pdf.SetMargins(36, 36, 36, 36)
	pdf.AddPage()
	if err := pdf.AddTTFFont(reportFontFamily, fontPath); err != nil {
		return nil, err
	}
	pageW := gopdf.PageSizeA4.W
	pageH := gopdf.PageSizeA4.H
	left := 36.0
	right := 36.0
	bottom := 36.0
	contentW := pageW - left - right
	y := 34.0

	setFont := func(size int) error {
		return pdf.SetFont(reportFontFamily, "", size)
	}
	drawCell := func(x, cy, w, h float64, text string, size int, r, g, b uint8, align int, max int) error {
		if err := setFont(size); err != nil {
			return err
		}
		pdf.SetTextColor(r, g, b)
		pdf.SetXY(x, cy)
		return pdf.CellWithOption(&gopdf.Rect{W: w, H: h}, cleanPDFText(text, max), gopdf.CellOption{Align: align})
	}

	newPage := func() {
		pdf.AddPage()
		y = 36
	}
	ensureSpace := func(required float64) {
		if y+required > pageH-bottom {
			pdf.AddPage()
			y = 36
		}
	}

	pdf.SetFillColor(96, 103, 216)
	pdf.RectFromUpperLeftWithStyle(left, y, 5, 48, "F")
	if err := drawCell(left+14, y-3, contentW-160, 26, title, 20, 17, 24, 39, gopdf.Left|gopdf.Middle, 64); err != nil {
		return nil, err
	}
	if err := drawCell(left+14, y+24, contentW-160, 14, fmt.Sprintf("%s to %s", reportFormattedTime(start), reportFormattedTime(end)), 9, 91, 100, 116, gopdf.Left|gopdf.Middle, 96); err != nil {
		return nil, err
	}
	if err := drawCell(pageW-right-146, y+2, 146, 14, "Generated", 8, 105, 114, 128, gopdf.Right|gopdf.Middle, 24); err != nil {
		return nil, err
	}
	if err := drawCell(pageW-right-146, y+17, 146, 14, reportFormattedTime(time.Now()), 9, 55, 65, 81, gopdf.Right|gopdf.Middle, 36); err != nil {
		return nil, err
	}
	y += 66

	chart := buildReportChart(headers, rows)
	metrics := reportSummaryMetrics(start, end, rows, chart)
	cardGap := 8.0
	cardCount := len(metrics)
	if cardCount == 0 {
		cardCount = 1
	}
	cardW := (contentW - cardGap*float64(cardCount-1)) / float64(cardCount)
	cardH := 46.0
	for i, metric := range metrics {
		x := left + float64(i)*(cardW+cardGap)
		pdf.SetFillColor(247, 249, 252)
		pdf.SetStrokeColor(221, 226, 235)
		pdf.SetLineWidth(0.5)
		pdf.RectFromUpperLeftWithStyle(x, y, cardW, cardH, "FD")
		if err := drawCell(x+10, y+7, cardW-20, 12, metric.Label, 8, 105, 114, 128, gopdf.Left|gopdf.Middle, reportMaxChars(cardW-20, 8)); err != nil {
			return nil, err
		}
		if err := drawCell(x+10, y+22, cardW-20, 16, metric.Value, 14, 17, 24, 39, gopdf.Left|gopdf.Middle, reportMaxChars(cardW-20, 14)); err != nil {
			return nil, err
		}
	}
	y += cardH + 24

	if len(rows) == 0 {
		pdf.SetFillColor(248, 250, 252)
		pdf.SetStrokeColor(221, 226, 235)
		pdf.RectFromUpperLeftWithStyle(left, y, contentW, 86, "FD")
		pdf.SetFillColor(96, 103, 216)
		pdf.RectFromUpperLeftWithStyle(left+20, y+22, 8, 42, "F")
		if err := drawCell(left+42, y+20, contentW-70, 18, "No production data found", 14, 31, 41, 55, gopdf.Left|gopdf.Middle, 80); err != nil {
			return nil, err
		}
		if err := drawCell(left+42, y+43, contentW-70, 16, "Try a different date range or filter. The report will not invent placeholder values.", 9, 91, 100, 116, gopdf.Left|gopdf.Middle, 110); err != nil {
			return nil, err
		}
		var buf bytes.Buffer
		if err := pdf.Write(&buf); err != nil {
			return nil, err
		}
		return buf.Bytes(), nil
	}

	if len(chart.Points) > 0 {
		chartH := 28 + float64(len(chart.Points))*22 + 18
		ensureSpace(chartH)
		if err := drawCell(left, y, contentW, 16, "Visual Summary", 12, 31, 41, 55, gopdf.Left|gopdf.Middle, 40); err != nil {
			return nil, err
		}
		y += 22
		pdf.SetFillColor(248, 250, 252)
		pdf.SetStrokeColor(221, 226, 235)
		pdf.RectFromUpperLeftWithStyle(left, y, contentW, chartH-24, "FD")
		if err := drawCell(left+12, y+8, contentW-24, 14, chart.Title, 9, 91, 100, 116, gopdf.Left|gopdf.Middle, 60); err != nil {
			return nil, err
		}
		barX := left + 126
		barW := contentW - 186
		valueX := barX + barW + 10
		maxValue := 0.0
		for _, point := range chart.Points {
			if point.Value > maxValue {
				maxValue = point.Value
			}
		}
		if chart.IsPercent {
			maxValue = math.Max(maxValue, 100)
		}
		if maxValue <= 0 {
			maxValue = 1
		}
		rowY := y + 30
		for _, point := range chart.Points {
			if err := drawCell(left+12, rowY-2, 104, 14, point.Label, 8, 55, 65, 81, gopdf.Left|gopdf.Middle, reportMaxChars(104, 8)); err != nil {
				return nil, err
			}
			pdf.SetFillColor(226, 232, 240)
			pdf.RectFromUpperLeftWithStyle(barX, rowY+2, barW, 8, "F")
			fillW := math.Min(barW, barW*(point.Value/maxValue))
			if fillW > 0 {
				pdf.SetFillColor(96, 103, 216)
				pdf.RectFromUpperLeftWithStyle(barX, rowY+2, fillW, 8, "F")
			}
			if err := drawCell(valueX, rowY-2, 46, 14, point.Display, 8, 31, 41, 55, gopdf.Right|gopdf.Middle, 12); err != nil {
				return nil, err
			}
			rowY += 22
		}
		y += chartH
	}

	ensureSpace(46)
	if err := drawCell(left, y, contentW, 16, "Report Data", 12, 31, 41, 55, gopdf.Left|gopdf.Middle, 40); err != nil {
		return nil, err
	}
	y += 22

	colCount := len(headers)
	if colCount == 0 {
		colCount = 1
		headers = []string{"Value"}
	}
	tableW := contentW
	colWidths := reportColumnWidths(headers, tableW)
	headerH := 20.0
	rowH := 20.0

	drawTableHeader := func() error {
		pdf.SetFillColor(31, 41, 55)
		pdf.SetStrokeColor(31, 41, 55)
		pdf.RectFromUpperLeftWithStyle(left, y, tableW, headerH, "FD")
		x := left
		for i, header := range headers {
			if i > 0 {
				pdf.SetStrokeColor(75, 85, 99)
				pdf.SetLineWidth(0.35)
				pdf.Line(x, y, x, y+headerH)
			}
			if err := drawCell(x+5, y+1, colWidths[i]-10, headerH-2, header, 8, 255, 255, 255, gopdf.Left|gopdf.Middle, reportMaxChars(colWidths[i]-10, 8)); err != nil {
				return err
			}
			x += colWidths[i]
		}
		y += headerH
		return nil
	}
	if y+headerH+rowH > pageH-bottom {
		newPage()
	}
	if err := drawTableHeader(); err != nil {
		return nil, err
	}
	for rowIndex, row := range rows {
		if y+rowH > pageH-bottom {
			newPage()
			if err := drawCell(left, y, contentW, 14, "Report Data continued", 10, 55, 65, 81, gopdf.Left|gopdf.Middle, 60); err != nil {
				return nil, err
			}
			y += 20
			if err := drawTableHeader(); err != nil {
				return nil, err
			}
		}
		if rowIndex%2 == 0 {
			pdf.SetFillColor(255, 255, 255)
		} else {
			pdf.SetFillColor(249, 250, 251)
		}
		pdf.SetStrokeColor(226, 232, 240)
		pdf.SetLineWidth(0.35)
		pdf.RectFromUpperLeftWithStyle(left, y, tableW, rowH, "FD")
		x := left
		for i := 0; i < colCount; i++ {
			value := ""
			if i < len(row) {
				value = row[i]
			}
			if i > 0 {
				pdf.SetStrokeColor(226, 232, 240)
				pdf.Line(x, y, x, y+rowH)
			}
			align := reportCellAlign(headers[i], value)
			if err := drawCell(x+5, y+1, colWidths[i]-10, rowH-2, value, 7, 55, 65, 81, align, reportMaxChars(colWidths[i]-10, 7)); err != nil {
				return nil, err
			}
			x += colWidths[i]
		}
		y += rowH
	}
	var buf bytes.Buffer
	if err := pdf.Write(&buf); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func (h *ReportsHandler) writePDF(c *gin.Context, reportType, title string, headers []string, rows [][]string) {
	start, end, ok := h.parseDateRange(c)
	if !ok {
		return
	}
	pdfBytes, err := renderReportPDF(title, start, end, headers, rows)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	filename := reportFilename(reportType, start, end)
	c.Header("Content-Disposition", reportDisposition(c, filename))
	c.Data(http.StatusOK, "application/pdf", pdfBytes)
}

func (h *ReportsHandler) reportRange(c *gin.Context) (time.Time, time.Time, bool) {
	return h.parseDateRange(c)
}

func respondRows[T any](c *gin.Context, rows []T, err error) {
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: rows})
}

// @Summary Production analytics summary
// @Description Get production analytics summary metrics for visualization.
// @Tags production-analytics
// @Produce json
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /production-analytics/summary [get]
func (h *ReportsHandler) AnalyticsSummary(c *gin.Context) {
	start, end, ok := h.reportRange(c)
	if !ok {
		return
	}
	output, err := h.productionOutputRows(c, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	utilization, err := h.machineUtilizationRows(c, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	completion, err := h.jobCompletionRows(c, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	downtime, err := h.downtimeRows(c, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	summary := ProductionAnalyticsSummary{}
	for _, row := range output {
		summary.TotalOutput += row.QuantityProduced
		summary.TotalScrap += row.QuantityScrap
	}
	summary.ScrapRate = capPct(pct(float64(summary.TotalScrap), float64(summary.TotalOutput+summary.TotalScrap)))
	for _, row := range downtime {
		summary.DowntimeHours += row.DowntimeHours
	}
	summary.DowntimeHours = round1(summary.DowntimeHours)
	if len(utilization) > 0 {
		total := 0.0
		for _, row := range utilization {
			total += row.UtilizationPct
		}
		summary.AvgUtilizationPct = round1(total / float64(len(utilization)))
	}
	summary.TotalJobs = len(completion)
	for _, job := range completion {
		switch productionJobCompletionBucket(job.Status, job.QuantityTotal, job.QuantityCompleted) {
		case domain.JobStatusCompleted:
			summary.CompletedJobs++
		case domain.JobStatusRunning, domain.JobStatusPaused, domain.JobStatusBlocked:
			summary.InProgressJobs++
		case domain.JobStatusScheduled, domain.JobStatusPlanned:
			summary.ScheduledJobs++
		}
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: summary})
}

// @Summary Production output analytics
// @Description Get production output rows for visualization.
// @Tags production-analytics
// @Produce json
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /production-analytics/output [get]
func (h *ReportsHandler) AnalyticsProductionOutput(c *gin.Context) {
	start, end, ok := h.reportRange(c)
	if !ok {
		return
	}
	rows, err := h.productionOutputRows(c, start, end)
	respondRows(c, rows, err)
}

// @Summary Machine utilization analytics
// @Description Get machine utilization rows for visualization.
// @Tags production-analytics
// @Produce json
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /production-analytics/machine-utilization [get]
func (h *ReportsHandler) AnalyticsMachineUtilization(c *gin.Context) {
	start, end, ok := h.reportRange(c)
	if !ok {
		return
	}
	rows, err := h.machineUtilizationRows(c, start, end)
	respondRows(c, rows, err)
}

// @Summary Job completion analytics
// @Description Get job completion rows for visualization.
// @Tags production-analytics
// @Produce json
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /production-analytics/job-completion [get]
func (h *ReportsHandler) AnalyticsJobCompletion(c *gin.Context) {
	start, end, ok := h.reportRange(c)
	if !ok {
		return
	}
	rows, err := h.jobCompletionRows(c, start, end)
	respondRows(c, rows, err)
}

// @Summary Downtime analytics
// @Description Get downtime rows for visualization.
// @Tags production-analytics
// @Produce json
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /production-analytics/downtime [get]
func (h *ReportsHandler) AnalyticsDowntime(c *gin.Context) {
	start, end, ok := h.reportRange(c)
	if !ok {
		return
	}
	rows, err := h.downtimeRows(c, start, end)
	respondRows(c, rows, err)
}

// @Summary Production output PDF
// @Description Generate a PDF report for production output.
// @Tags reports
// @Accept json
// @Produce application/pdf
// @Success 200 {file} file
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/production-output [get]
func (h *ReportsHandler) ProductionOutputPerSlot(c *gin.Context) {
	start, end, ok := h.reportRange(c)
	if !ok {
		return
	}
	rows, err := h.productionOutputRows(c, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	out := make([][]string, 0, len(rows))
	for _, row := range rows {
		out = append(out, []string{row.Date, row.SlotID, row.MachineID, row.JobID, row.ProductID, fmt.Sprint(row.QuantityPlanned), fmt.Sprint(row.QuantityProduced), fmt.Sprint(row.QuantityScrap)})
	}
	pdfBytes, err := renderReportPDF("Production Output Report", start, end, []string{"Date", "Slot", "Machine", "Job", "Product", "Planned", "Produced", "Scrap"}, out)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.Header("Content-Disposition", reportDisposition(c, reportFilename("production-output", start, end)))
	c.Data(http.StatusOK, "application/pdf", pdfBytes)
}

// @Summary Machine utilization PDF
// @Description Generate a PDF report for machine utilization.
// @Tags reports
// @Accept json
// @Produce application/pdf
// @Success 200 {file} file
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/machine-utilization [get]
func (h *ReportsHandler) MachineUtilization(c *gin.Context) {
	start, end, ok := h.reportRange(c)
	if !ok {
		return
	}
	rows, err := h.machineUtilizationRows(c, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	out := make([][]string, 0, len(rows))
	for _, row := range rows {
		out = append(out, []string{row.MachineID, row.MachineName, fmt.Sprintf("%.1f", row.TotalMinutes), fmt.Sprintf("%.1f", row.DowntimeMinutes), fmt.Sprintf("%.1f%%", row.UtilizationPct), fmt.Sprint(row.SlotCount)})
	}
	pdfBytes, err := renderReportPDF("Machine Utilization Report", start, end, []string{"Machine ID", "Machine", "Run min", "Down min", "Utilization", "Slots"}, out)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.Header("Content-Disposition", reportDisposition(c, reportFilename("machine-utilization", start, end)))
	c.Data(http.StatusOK, "application/pdf", pdfBytes)
}

// @Summary Job completion PDF
// @Description Generate a PDF report for job completion.
// @Tags reports
// @Accept json
// @Produce application/pdf
// @Success 200 {file} file
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/job-completion [get]
func (h *ReportsHandler) JobCompletion(c *gin.Context) {
	start, end, ok := h.reportRange(c)
	if !ok {
		return
	}
	rows, err := h.jobCompletionRows(c, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	out := make([][]string, 0, len(rows))
	for _, row := range rows {
		out = append(out, []string{row.JobID, row.ProductID, row.Status, fmt.Sprint(row.QuantityTotal), fmt.Sprint(row.QuantityCompleted), fmt.Sprintf("%.1f%%", row.CompletionPct), fmt.Sprint(row.SlotCount)})
	}
	pdfBytes, err := renderReportPDF("Job Completion Report", start, end, []string{"Job", "Product", "Status", "Target", "Completed", "Complete", "Slots"}, out)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.Header("Content-Disposition", reportDisposition(c, reportFilename("job-completion", start, end)))
	c.Data(http.StatusOK, "application/pdf", pdfBytes)
}

// @Summary Inventory trends PDF
// @Description Generate a PDF report for inventory trends.
// @Tags reports
// @Accept json
// @Produce application/pdf
// @Success 200 {file} file
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/inventory-trends [get]
func (h *ReportsHandler) InventoryTrends(c *gin.Context) {
	start, end, ok := h.reportRange(c)
	if !ok {
		return
	}
	rows, err := h.inventoryTrendRows(c, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	out := make([][]string, 0, len(rows))
	for _, row := range rows {
		out = append(out, []string{row.Date, row.MaterialID, fmt.Sprintf("%.1f", row.NetQty), fmt.Sprint(row.TxCount)})
	}
	pdfBytes, err := renderReportPDF("Inventory Trends Report", start, end, []string{"Date", "Material", "Net qty", "Transactions"}, out)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.Header("Content-Disposition", reportDisposition(c, reportFilename("inventory-trends", start, end)))
	c.Data(http.StatusOK, "application/pdf", pdfBytes)
}

// @Summary Quality trends PDF
// @Description Generate a PDF report for quality trends.
// @Tags reports
// @Accept json
// @Produce application/pdf
// @Success 200 {file} file
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/quality-trends [get]
func (h *ReportsHandler) QualityTrends(c *gin.Context) {
	start, end, ok := h.reportRange(c)
	if !ok {
		return
	}
	rows, err := h.qualityTrendRows(c, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	out := make([][]string, 0, len(rows))
	for _, row := range rows {
		out = append(out, []string{row.Date, fmt.Sprint(row.PassCount), fmt.Sprint(row.FailCount), fmt.Sprint(row.DefectSum), fmt.Sprintf("%.1f%%", row.PassRate)})
	}
	pdfBytes, err := renderReportPDF("Quality Trends Report", start, end, []string{"Date", "Pass", "Fail", "Defects", "Pass rate"}, out)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.Header("Content-Disposition", reportDisposition(c, reportFilename("quality-trends", start, end)))
	c.Data(http.StatusOK, "application/pdf", pdfBytes)
}

// @Summary OEE trends PDF
// @Description Generate a PDF report for OEE trends.
// @Tags reports
// @Accept json
// @Produce application/pdf
// @Success 200 {file} file
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/oee [get]
func (h *ReportsHandler) OEETrends(c *gin.Context) {
	start, end, ok := h.reportRange(c)
	if !ok {
		return
	}
	rows, err := h.oeeTrendRows(c, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	out := make([][]string, 0, len(rows))
	for _, row := range rows {
		out = append(out, []string{row.Date, row.MachineID, row.ShiftName, fmt.Sprintf("%.1f%%", row.Availability), fmt.Sprintf("%.1f%%", row.Performance), fmt.Sprintf("%.1f%%", row.Quality), fmt.Sprintf("%.1f%%", row.OEE)})
	}
	pdfBytes, err := renderReportPDF("OEE Trends Report", start, end, []string{"Date", "Machine", "Shift", "Availability", "Performance", "Quality", "OEE"}, out)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.Header("Content-Disposition", reportDisposition(c, reportFilename("oee", start, end)))
	c.Data(http.StatusOK, "application/pdf", pdfBytes)
}

// @Summary Bottleneck PDF
// @Description Generate a PDF report for bottlenecks.
// @Tags reports
// @Accept json
// @Produce application/pdf
// @Success 200 {file} file
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/bottlenecks [get]
func (h *ReportsHandler) BottleneckForecast(c *gin.Context) {
	start, end, ok := h.reportRange(c)
	if !ok {
		return
	}
	rows, err := h.bottleneckRows(c, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	out := make([][]string, 0, len(rows))
	for _, row := range rows {
		out = append(out, []string{row.MachineID, row.StepID, fmt.Sprint(row.QueueCount), fmt.Sprintf("%.1f%%", row.Utilization), row.Forecast})
	}
	pdfBytes, err := renderReportPDF("Bottleneck Report", start, end, []string{"Machine", "Step", "Queue", "Utilization", "Forecast"}, out)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.Header("Content-Disposition", reportDisposition(c, reportFilename("bottlenecks", start, end)))
	c.Data(http.StatusOK, "application/pdf", pdfBytes)
}

// @Summary Downtime PDF
// @Description Generate a PDF report for downtime.
// @Tags reports
// @Accept json
// @Produce application/pdf
// @Success 200 {file} file
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/downtime [get]
func (h *ReportsHandler) Downtime(c *gin.Context) {
	start, end, ok := h.reportRange(c)
	if !ok {
		return
	}
	rows, err := h.downtimeRows(c, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	out := make([][]string, 0, len(rows))
	for _, row := range rows {
		out = append(out, []string{row.Date, row.MachineID, row.Cause, fmt.Sprintf("%.1f", row.DurationMinutes), fmt.Sprintf("%.1f", row.DowntimeHours), fmt.Sprint(row.OccurrenceCount)})
	}
	pdfBytes, err := renderReportPDF("Downtime Report", start, end, []string{"Date", "Machine", "Cause", "Minutes", "Hours", "Events"}, out)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.Header("Content-Disposition", reportDisposition(c, reportFilename("downtime", start, end)))
	c.Data(http.StatusOK, "application/pdf", pdfBytes)
}

// @Summary Maintenance efficiency PDF
// @Description Generate a PDF report for maintenance efficiency.
// @Tags reports
// @Accept json
// @Produce application/pdf
// @Success 200 {file} file
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reports/maintenance-efficiency [get]
func (h *ReportsHandler) MaintenanceEfficiency(c *gin.Context) {
	start, end, ok := h.reportRange(c)
	if !ok {
		return
	}
	rows, err := h.maintenanceEfficiencyRows(c, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	out := make([][]string, 0, len(rows))
	for _, row := range rows {
		out = append(out, []string{row.MachineID, fmt.Sprint(row.PlannedCount), fmt.Sprint(row.CompletedCount), fmt.Sprintf("%.1f", row.AvgDurationMinutes)})
	}
	pdfBytes, err := renderReportPDF("Maintenance Efficiency Report", start, end, []string{"Machine", "Planned", "Completed", "Avg min"}, out)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.Header("Content-Disposition", reportDisposition(c, reportFilename("maintenance-efficiency", start, end)))
	c.Data(http.StatusOK, "application/pdf", pdfBytes)
}
