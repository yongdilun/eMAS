package service

import (
	"emas/internal/domain"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
)

// KeywordChatPlanner is a deterministic planner for phase 0.
// It maps common phrasing to the approved read-only tool set.
type KeywordChatPlanner struct{}

func NewKeywordChatPlanner() *KeywordChatPlanner {
	return &KeywordChatPlanner{}
}

func (p *KeywordChatPlanner) Name() string {
	return "keyword-chat-planner-v1"
}

func (p *KeywordChatPlanner) Plan(query string, _ []domain.AIChatMessage, registry ToolRegistry) (*ChatPlan, error) {
	raw := strings.TrimSpace(query)
	if raw == "" {
		return &ChatPlan{
			IntentSummary:       "Need clarification",
			Action:              "clarify",
			Confidence:          0,
			Ambiguous:           true,
			ClarificationPrompt: []string{"Ask about jobs, machines, inventory, dashboard KPIs, or provide a job ID like JOB-1234."},
			PlanExplanation:     "The message was empty, so no read-only tools were selected.",
		}, nil
	}

	lower := strings.ToLower(raw)
	jobID := chatbotExtractJobID(raw)

	plan := &ChatPlan{
		IntentSummary:   "Read-only operational lookup",
		Action:          "query_status",
		Confidence:      0.72,
		PlanExplanation: "Use read-only tools to answer the operational question without changing scheduling state.",
	}

	switch {
	case jobID != "" && containsAny(lower, "delay", "late", "risk"):
		plan.Action = "delay_risk"
		plan.IntentSummary = "Inspect delay risk for one job"
		plan.ToolCalls = []ChatToolCall{
			{Name: "jobs.get", Args: map[string]interface{}{"job_id": jobID}},
			{Name: "ai_scheduling.delay_risk", Args: map[string]interface{}{"job_id": jobID}},
		}
		plan.Confidence = 0.93
	case jobID != "" && containsAny(lower, "assist", "help schedule", "scheduling assist"):
		plan.Action = "scheduling_assist"
		plan.IntentSummary = "Load scheduling assist for one job"
		plan.ToolCalls = []ChatToolCall{
			{Name: "jobs.get", Args: map[string]interface{}{"job_id": jobID}},
			{Name: "ai_scheduling.assist", Args: map[string]interface{}{"job_id": jobID}},
		}
		plan.Confidence = 0.91
	case jobID != "" && containsAny(lower, "explain", "why", "going on", "happening", "status"):
		plan.Action = "explain_job"
		plan.IntentSummary = "Explain one job using read-only evidence"
		plan.ToolCalls = []ChatToolCall{
			{Name: "jobs.get", Args: map[string]interface{}{"job_id": jobID}},
			{Name: "ai_scheduling.explanation", Args: map[string]interface{}{"job_id": jobID}},
		}
		plan.Confidence = 0.94
	case containsAny(lower, "dashboard", "kpi", "metric", "overview"):
		plan.Action = "dashboard_kpis"
		plan.IntentSummary = "Load dashboard KPIs and alerts"
		plan.ToolCalls = []ChatToolCall{
			{Name: "dashboard.kpis", Args: map[string]interface{}{}},
			{Name: "dashboard.alerts", Args: map[string]interface{}{}},
		}
		plan.Confidence = 0.88
	case containsAny(lower, "maintenance alert", "maintenance due", "overdue maintenance"):
		plan.Action = "maintenance_alerts"
		plan.IntentSummary = "Load maintenance alerts"
		plan.ToolCalls = []ChatToolCall{
			{Name: "machines.maintenance_alerts", Args: map[string]interface{}{}},
		}
		plan.Confidence = 0.87
	case containsAny(lower, "machine", "machines", "utilization", "capacity"):
		plan.Action = "machine_overview"
		plan.IntentSummary = "Load machine overview"
		plan.ToolCalls = []ChatToolCall{
			{Name: "machines.list", Args: map[string]interface{}{}},
		}
		if containsAny(lower, "alert", "maintenance") {
			plan.ToolCalls = append(plan.ToolCalls, ChatToolCall{Name: "machines.maintenance_alerts", Args: map[string]interface{}{}})
		}
		plan.Confidence = 0.84
	case containsAny(lower, "inventory", "stock", "material", "materials"):
		plan.Action = "inventory_visibility"
		plan.IntentSummary = "Load inventory visibility"
		plan.ToolCalls = []ChatToolCall{
			{Name: "inventory.materials", Args: map[string]interface{}{}},
		}
		plan.Confidence = 0.86
	case jobID != "":
		plan.Action = "job_status"
		plan.IntentSummary = "Load one job status"
		plan.ToolCalls = []ChatToolCall{
			{Name: "jobs.get", Args: map[string]interface{}{"job_id": jobID}},
		}
		plan.Confidence = 0.84
	case containsAny(lower, "jobs", "queue", "orders", "work orders"):
		plan.Action = "jobs_overview"
		plan.IntentSummary = "Load job overview"
		plan.ToolCalls = []ChatToolCall{
			{Name: "jobs.list", Args: map[string]interface{}{}},
		}
		plan.Confidence = 0.78
	case containsAny(lower, "create job", "new job", "add job"):
		// Basic parsing for args just for demonstration of Phase 1 capabilities
		// Example: "Create a job for PRD-A, qty 100"
		productID := "PRD-DEFAULT"
		if matches := regexp.MustCompile(`(?i)prd-[a-z0-9]+`).FindString(raw); matches != "" {
			productID = strings.ToUpper(matches)
		}
		// If product isn't explicitly mentioned, it's ambiguous
		if productID == "PRD-DEFAULT" && !containsAny(lower, "prd-") {
			plan.Action = "clarify"
			plan.IntentSummary = "Need product ID for new job"
			plan.Ambiguous = true
			plan.Confidence = 0.5
			plan.ClarificationPrompt = []string{
				"Please specify the product ID (e.g., PRD-A) and quantity for the new job.",
			}
			plan.PlanExplanation = "Product ID is missing for job creation."
		} else {
			plan.Action = "create_job"
			plan.IntentSummary = "Create a new job"
			plan.ToolCalls = []ChatToolCall{
				{
					Name: "jobs.create",
					Args: map[string]interface{}{
						"product_id": productID,
						"quantity":   100, // Hardcoded for simplicity in Phase 1 demo
					},
				},
			}
			plan.Confidence = 0.85
		}
	default:
		plan.Action = "clarify"
		plan.IntentSummary = "Need clarification"
		plan.Ambiguous = true
		plan.Confidence = 0.31
		plan.ClarificationPrompt = []string{
			"Ask about jobs, machines, inventory, dashboard KPIs, or provide a job ID like JOB-1234.",
		}
		plan.PlanExplanation = "The request did not map cleanly to the approved read-only tool set."
	}

	if err := validateChatPlan(plan, registry); err != nil {
		return nil, err
	}
	return plan, nil
}

func validateChatPlan(plan *ChatPlan, registry ToolRegistry) error {
	if plan == nil {
		return fmt.Errorf("plan is nil")
	}
	if plan.Ambiguous {
		return nil
	}
	for _, call := range plan.ToolCalls {
		tool, ok := registry.Get(call.Name)
		if !ok {
			return fmt.Errorf("unknown tool: %s", call.Name)
		}
		if !tool.ReadOnly && !tool.RequiresApproval {
			// Phase 1: We allow write tools, but they MUST require approval
			return fmt.Errorf("write tool %s must require approval", call.Name)
		}
		for _, key := range tool.RequiredArgs {
			if call.Args == nil || strings.TrimSpace(chatArgString(call.Args, key)) == "" {
				return fmt.Errorf("missing required arg %s for tool %s", key, call.Name)
			}
		}
	}
	_, err := json.Marshal(plan)
	return err
}

func chatbotExtractJobID(raw string) string {
	matches := regexp.MustCompile(`(?i)(?:\bjob\b\s*[:#]?\s*)?((?:JOB|J)\-[A-Z0-9\-]+)\b`).FindAllStringSubmatch(raw, -1)
	if len(matches) == 0 {
		return ""
	}
	return matches[len(matches)-1][1]
}

func containsAny(raw string, values ...string) bool {
	for _, value := range values {
		if strings.Contains(raw, value) {
			return true
		}
	}
	return false
}
