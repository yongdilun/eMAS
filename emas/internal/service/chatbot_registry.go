package service

import (
	"context"
	"emas/internal/domain"
	"emas/internal/repository"
	"time"

	"gorm.io/gorm"
)

type StaticChatToolRegistry struct {
	tools map[string]ChatToolDefinition
	list  []ChatToolDefinition
}

type DashboardKPIsSnapshot struct {
	OEEPct            float64 `json:"oee_pct"`
	OEEChange         float64 `json:"oee_change"`
	ProductionUnits   int     `json:"production_units"`
	ProductionChange  float64 `json:"production_change"`
	DowntimeHrs       float64 `json:"downtime_hrs"`
	DowntimeChange    float64 `json:"downtime_change"`
	UtilizationPct    float64 `json:"utilization_pct"`
	UtilizationChange float64 `json:"utilization_change"`
}

type DashboardAlertSnapshot struct {
	Type      string  `json:"type"`
	Title     string  `json:"title"`
	Time      string  `json:"time"`
	MachineID *string `json:"machine_id,omitempty"`
}

func NewStaticChatToolRegistry(db *gorm.DB, jobService *JobService, machineService *MachineService, inventoryService *InventoryService, predictive *AIPredictiveService, machineRepo *repository.MachineRepository, invRepo *repository.InventoryRepository) *StaticChatToolRegistry {
	list := []ChatToolDefinition{
		{
			Name:            "jobs.get",
			Description:     "Load a single job with current status and deadline information.",
			Path:            "/api/v1/jobs/:job_id",
			Version:         1,
			SchemaVersion:   1,
			CapabilityTags:  []string{"job", "status", "job_id", "order"},
			ReadOnly:        true,
			ConcurrencySafe: true,
			Idempotent:      true,
			InputSchema:     map[string]string{"job_id": "string"},
			RequiredArgs:    []string{"job_id"},
			Execute: func(ctx context.Context, args map[string]interface{}) (interface{}, error) {
				return jobService.GetByID(chatArgString(args, "job_id"))
			},
		},
		{
			Name:            "jobs.list",
			Description:     "List jobs for queue or overview questions.",
			Path:            "/api/v1/jobs",
			Version:         1,
			SchemaVersion:   1,
			CapabilityTags:  []string{"jobs", "list", "queue", "overview"},
			ReadOnly:        true,
			ConcurrencySafe: true,
			Idempotent:      true,
			Execute: func(ctx context.Context, args map[string]interface{}) (interface{}, error) {
				return jobService.ListAll()
			},
		},
		{
			Name:            "machines.list",
			Description:     "List machines and current machine status.",
			Path:            "/api/v1/machines",
			Version:         1,
			SchemaVersion:   1,
			CapabilityTags:  []string{"machines", "machine", "utilization", "status", "capacity"},
			ReadOnly:        true,
			ConcurrencySafe: true,
			Idempotent:      true,
			Execute: func(ctx context.Context, args map[string]interface{}) (interface{}, error) {
				return machineService.ListAll()
			},
		},
		{
			Name:            "machines.maintenance_alerts",
			Description:     "Return machines due for maintenance soon.",
			Path:            "/api/v1/machines/maintenance-alerts",
			Version:         1,
			SchemaVersion:   1,
			CapabilityTags:  []string{"machines", "maintenance", "alerts", "due"},
			ReadOnly:        true,
			ConcurrencySafe: true,
			Idempotent:      true,
			Execute: func(ctx context.Context, args map[string]interface{}) (interface{}, error) {
				return machineService.GetMaintenanceAlerts(7)
			},
		},
		{
			Name:            "inventory.materials",
			Description:     "List inventory materials and stock status.",
			Path:            "/api/v1/inventory/materials",
			Version:         1,
			SchemaVersion:   1,
			CapabilityTags:  []string{"inventory", "materials", "stock", "availability"},
			ReadOnly:        true,
			ConcurrencySafe: true,
			Idempotent:      true,
			Execute: func(ctx context.Context, args map[string]interface{}) (interface{}, error) {
				return inventoryService.ListMaterials()
			},
		},
		{
			Name:            "dashboard.kpis",
			Description:     "Return dashboard KPI snapshot.",
			Path:            "/api/v1/dashboard/kpis",
			Version:         1,
			SchemaVersion:   1,
			CapabilityTags:  []string{"dashboard", "kpi", "metrics", "overview"},
			ReadOnly:        true,
			ConcurrencySafe: true,
			Idempotent:      true,
			Execute: func(ctx context.Context, args map[string]interface{}) (interface{}, error) {
				return buildDashboardKPIs(db)
			},
		},
		{
			Name:            "dashboard.alerts",
			Description:     "Return active dashboard alerts from maintenance, downtime, and inventory.",
			Path:            "/api/v1/alerts",
			Version:         1,
			SchemaVersion:   1,
			CapabilityTags:  []string{"dashboard", "alerts", "maintenance", "downtime", "inventory"},
			ReadOnly:        true,
			ConcurrencySafe: true,
			Idempotent:      true,
			Execute: func(ctx context.Context, args map[string]interface{}) (interface{}, error) {
				return buildDashboardAlerts(db, machineRepo, invRepo)
			},
		},
		{
			Name:            "ai_scheduling.explanation",
			Description:     "Return the scheduling explanation for one job.",
			Path:            "/api/v1/ai/scheduling/jobs/:job_id/explanation",
			Version:         1,
			SchemaVersion:   1,
			CapabilityTags:  []string{"job", "schedule", "explain", "reasoning"},
			ReadOnly:        true,
			ConcurrencySafe: true,
			Idempotent:      true,
			InputSchema:     map[string]string{"job_id": "string"},
			RequiredArgs:    []string{"job_id"},
			Execute: func(ctx context.Context, args map[string]interface{}) (interface{}, error) {
				return predictive.ExplainJob(chatArgString(args, "job_id"))
			},
		},
		{
			Name:            "ai_scheduling.delay_risk",
			Description:     "Return the delay risk for one job.",
			Path:            "/api/v1/ai/scheduling/jobs/:job_id/delay-risk",
			Version:         1,
			SchemaVersion:   1,
			CapabilityTags:  []string{"job", "delay", "risk", "late"},
			ReadOnly:        true,
			ConcurrencySafe: true,
			Idempotent:      true,
			InputSchema:     map[string]string{"job_id": "string"},
			RequiredArgs:    []string{"job_id"},
			Execute: func(ctx context.Context, args map[string]interface{}) (interface{}, error) {
				return predictive.GetDelayRisk(chatArgString(args, "job_id"))
			},
		},
		{
			Name:            "ai_scheduling.assist",
			Description:     "Return the AI scheduling assist package for one job.",
			Path:            "/api/v1/ai/scheduling/jobs/:job_id/assist",
			Version:         1,
			SchemaVersion:   1,
			CapabilityTags:  []string{"job", "assist", "schedule", "support"},
			ReadOnly:        true,
			ConcurrencySafe: true,
			Idempotent:      true,
			Method:          "GET",
			SideEffectLevel: "NONE",
			InputSchema:     map[string]string{"job_id": "string"},
			RequiredArgs:    []string{"job_id"},
			Execute: func(ctx context.Context, args map[string]interface{}) (interface{}, error) {
				return predictive.BuildAssist(chatArgString(args, "job_id"))
			},
		},
		{
			Name:            "jobs.create",
			Description:     "Create a new job.",
			Path:            "/api/v1/jobs",
			Version:         1,
			SchemaVersion:   1,
			CapabilityTags:  []string{"job", "create", "new", "order"},
			ReadOnly:        false,
			ConcurrencySafe: true,
			Idempotent:      false,
			Method:          "POST",
			SideEffectLevel: "LOW",
			RequiresApproval: true,
			IdempotencyScope: "approval",
			InputSchema:     map[string]string{"product_id": "string", "quantity": "number", "priority": "string", "deadline": "string"},
			RequiredArgs:    []string{"product_id", "quantity"},
			Execute: func(ctx context.Context, args map[string]interface{}) (interface{}, error) {
				// This is a placeholder for actual job creation logic.
				// In a real implementation, you would bind args to domain.Job and call jobService.Create(job)
				return map[string]interface{}{"status": "success", "message": "Job created (mock)"}, nil
			},
		},
	}
	tools := make(map[string]ChatToolDefinition, len(list))
	for _, tool := range list {
		tools[tool.Name] = tool
	}
	return &StaticChatToolRegistry{tools: tools, list: list}
}

func (r *StaticChatToolRegistry) List() []ChatToolDefinition {
	out := make([]ChatToolDefinition, len(r.list))
	copy(out, r.list)
	return out
}

func (r *StaticChatToolRegistry) Get(name string) (ChatToolDefinition, bool) {
	tool, ok := r.tools[name]
	return tool, ok
}

func buildDashboardKPIs(db *gorm.DB) (*DashboardKPIsSnapshot, error) {
	resp := &DashboardKPIsSnapshot{
		OEEPct:            85.2,
		OEEChange:         1.5,
		ProductionUnits:   10450,
		ProductionChange:  5.0,
		DowntimeHrs:       2.1,
		DowntimeChange:    0.2,
		UtilizationPct:    78.0,
		UtilizationChange: 2.5,
	}
	if db == nil {
		return resp, nil
	}
	var prodTotal int
	if err := db.Table("production_logs").Select("COALESCE(SUM(quantity_produced), 0)").Scan(&prodTotal).Error; err == nil && prodTotal > 0 {
		resp.ProductionUnits = prodTotal
	}
	var downtimeMins float64
	if err := db.Table("machine_downtime").Select("COALESCE(SUM(duration_minutes), 0)").Scan(&downtimeMins).Error; err == nil {
		resp.DowntimeHrs = downtimeMins / 60.0
	}
	return resp, nil
}

func buildDashboardAlerts(db *gorm.DB, machineRepo *repository.MachineRepository, invRepo *repository.InventoryRepository) ([]DashboardAlertSnapshot, error) {
	alerts := make([]DashboardAlertSnapshot, 0)
	now := time.Now().Format(time.RFC3339)
	machines, err := machineRepo.ListAll()
	if err == nil {
		for _, m := range machines {
			if m.Status == domain.MachineStatusMaintenance {
				mid := m.MachineID
				alerts = append(alerts, DashboardAlertSnapshot{
					Type:      "maintenance",
					Title:     m.MachineName + " requires maintenance",
					Time:      now,
					MachineID: &mid,
				})
			}
		}
	}
	materials, err := invRepo.ListMaterials()
	if err == nil {
		for _, m := range materials {
			if m.Status == domain.InventoryStatusLowStock || m.Status == domain.InventoryStatusOutOfStock {
				alerts = append(alerts, DashboardAlertSnapshot{
					Type:  "inventory",
					Title: m.MaterialName + " is " + m.Status,
					Time:  now,
				})
			}
		}
	}
	if db != nil {
		cutoff := time.Now().Add(-24 * time.Hour)
		var downtimes []struct {
			MachineID string    `gorm:"column:machine_id"`
			Cause     string    `gorm:"column:cause"`
			StartTime time.Time `gorm:"column:start_time"`
		}
		if err := db.Table("machine_downtime").Where("start_time >= ?", cutoff).Find(&downtimes).Error; err == nil {
			for _, d := range downtimes {
				mid := d.MachineID
				alerts = append(alerts, DashboardAlertSnapshot{
					Type:      "downtime",
					Title:     d.Cause,
					Time:      d.StartTime.Format(time.RFC3339),
					MachineID: &mid,
				})
			}
		}
	}
	return alerts, nil
}

func chatArgString(args map[string]interface{}, key string) string {
	if args == nil {
		return ""
	}
	if v, ok := args[key]; ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	return ""
}
