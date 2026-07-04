package handler

import (
	"bytes"
	"emas/internal/handler/dto"
	"fmt"
	"math"
	"net/http"
	"os"
	"path/filepath"
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
	JobID            string  `json:"job_id"`
	SlotID           string  `json:"slot_id"`
	ProductID        string  `json:"product_id"`
	QuantityPlanned  int     `json:"quantity_planned"`
	QuantityProduced int     `json:"quantity_produced"`
	CompletionPct    float64 `json:"completion_pct"`
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
		JobID            string `json:"job_id"`
		SlotID           string `json:"slot_id"`
		ProductID        string `json:"product_id"`
		QuantityPlanned  int    `json:"quantity_planned"`
		QuantityProduced int    `json:"quantity_produced"`
	}
	q := h.db.Table("job_step_schedule_slots").
		Select("jobs.job_id, job_step_schedule_slots.slot_id, jobs.product_id, job_step_schedule_slots.quantity_planned, COALESCE(SUM(production_logs.quantity_produced), 0) as quantity_produced").
		Joins("JOIN job_steps ON job_steps.job_step_id = job_step_schedule_slots.job_step_id").
		Joins("JOIN jobs ON jobs.job_id = job_steps.job_id").
		Joins("LEFT JOIN production_logs ON production_logs.slot_id = job_step_schedule_slots.slot_id").
		Where("job_step_schedule_slots.scheduled_start >= ? AND job_step_schedule_slots.scheduled_end <= ?", start, end)
	q = filterQuery(c, q)
	if err := q.Group("jobs.job_id, job_step_schedule_slots.slot_id, jobs.product_id, job_step_schedule_slots.quantity_planned").
		Order("jobs.job_id ASC, job_step_schedule_slots.slot_id ASC").
		Scan(&raw).Error; err != nil {
		return nil, err
	}
	rows := make([]JobCompletionReportRow, 0, len(raw))
	for _, row := range raw {
		rows = append(rows, JobCompletionReportRow{
			JobID:            row.JobID,
			SlotID:           row.SlotID,
			ProductID:        row.ProductID,
			QuantityPlanned:  row.QuantityPlanned,
			QuantityProduced: row.QuantityProduced,
			CompletionPct:    capPct(pct(float64(row.QuantityProduced), float64(row.QuantityPlanned))),
		})
	}
	return rows, nil
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
	value = strings.TrimSpace(strings.ReplaceAll(value, "\n", " "))
	if value == "" {
		return "-"
	}
	if max > 0 && len(value) > max {
		return value[:max-1] + "."
	}
	return value
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
	if err := pdf.SetFont(reportFontFamily, "", 16); err != nil {
		return nil, err
	}
	pdf.SetTextColor(20, 24, 32)
	pdf.SetXY(36, 36)
	if err := pdf.Cell(nil, title); err != nil {
		return nil, err
	}
	if err := pdf.SetFont(reportFontFamily, "", 9); err != nil {
		return nil, err
	}
	pdf.SetTextColor(90, 96, 110)
	pdf.SetXY(36, 58)
	if err := pdf.Cell(nil, fmt.Sprintf("Date range: %s to %s", start.Format(time.RFC3339), end.Format(time.RFC3339))); err != nil {
		return nil, err
	}
	pdf.SetXY(36, 72)
	if err := pdf.Cell(nil, fmt.Sprintf("Generated: %s", time.Now().UTC().Format(time.RFC3339))); err != nil {
		return nil, err
	}
	y := 98.0
	if len(rows) == 0 {
		if err := pdf.SetFont(reportFontFamily, "", 11); err != nil {
			return nil, err
		}
		pdf.SetTextColor(90, 96, 110)
		pdf.SetXY(36, y)
		if err := pdf.Cell(nil, "No production data found for this filter."); err != nil {
			return nil, err
		}
		var buf bytes.Buffer
		if err := pdf.Write(&buf); err != nil {
			return nil, err
		}
		return buf.Bytes(), nil
	}
	colCount := len(headers)
	if colCount == 0 {
		colCount = 1
	}
	pageW := gopdf.PageSizeA4.W
	pageH := gopdf.PageSizeA4.H
	left := 36.0
	right := 36.0
	bottom := 36.0
	tableW := pageW - left - right
	colW := tableW / float64(colCount)
	rowH := 16.0
	drawHeader := func() error {
		if err := pdf.SetFont(reportFontFamily, "", 8); err != nil {
			return err
		}
		pdf.SetTextColor(20, 24, 32)
		pdf.SetFillColor(236, 239, 244)
		for i, header := range headers {
			pdf.SetXY(left+float64(i)*colW, y)
			if err := pdf.CellWithOption(&gopdf.Rect{W: colW, H: rowH}, cleanPDFText(header, 18), gopdf.CellOption{Align: gopdf.Left | gopdf.Middle, Border: gopdf.AllBorders, Float: gopdf.Right}); err != nil {
				return err
			}
		}
		y += rowH
		return nil
	}
	if err := drawHeader(); err != nil {
		return nil, err
	}
	if err := pdf.SetFont(reportFontFamily, "", 7); err != nil {
		return nil, err
	}
	pdf.SetTextColor(40, 45, 55)
	for _, row := range rows {
		if y+rowH > pageH-bottom {
			pdf.AddPage()
			y = 36
			if err := drawHeader(); err != nil {
				return nil, err
			}
			if err := pdf.SetFont(reportFontFamily, "", 7); err != nil {
				return nil, err
			}
			pdf.SetTextColor(40, 45, 55)
		}
		for i := 0; i < colCount; i++ {
			value := ""
			if i < len(row) {
				value = row[i]
			}
			pdf.SetXY(left+float64(i)*colW, y)
			if err := pdf.CellWithOption(&gopdf.Rect{W: colW, H: rowH}, cleanPDFText(value, 22), gopdf.CellOption{Align: gopdf.Left | gopdf.Middle, Border: gopdf.AllBorders, Float: gopdf.Right}); err != nil {
				return nil, err
			}
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
	byJob := map[string]struct {
		planned  int
		produced int
	}{}
	for _, row := range completion {
		job := byJob[row.JobID]
		job.planned += row.QuantityPlanned
		job.produced += row.QuantityProduced
		byJob[row.JobID] = job
	}
	summary.TotalJobs = len(byJob)
	for _, job := range byJob {
		if job.planned > 0 && job.produced >= job.planned {
			summary.CompletedJobs++
		} else if job.produced > 0 {
			summary.InProgressJobs++
		} else {
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
		out = append(out, []string{row.JobID, row.SlotID, row.ProductID, fmt.Sprint(row.QuantityPlanned), fmt.Sprint(row.QuantityProduced), fmt.Sprintf("%.1f%%", row.CompletionPct)})
	}
	pdfBytes, err := renderReportPDF("Job Completion Report", start, end, []string{"Job", "Slot", "Product", "Planned", "Produced", "Complete"}, out)
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
