package service

import (
	"strconv"
	"strings"
)

// ExecutableCall describes a full API call the frontend can execute directly.
type ExecutableCall struct {
	Method  string                 `json:"method"`
	Path    string                 `json:"path"`
	Body    map[string]interface{} `json:"body,omitempty"`
	Purpose string                 `json:"purpose"`
}

// ResolveAction returns executable API calls for the given intent and entities.
func ResolveAction(intent string, entities map[string]interface{}) []ExecutableCall {
	getStr := func(k string) string {
		if v, ok := entities[k]; ok {
			if s, ok := v.(string); ok {
				return s
			}
			if n, ok := v.(float64); ok {
				return strconv.FormatFloat(n, 'f', -1, 64)
			}
		}
		return ""
	}
	getFloat := func(k string) float64 {
		if v, ok := entities[k]; ok {
			if f, ok := v.(float64); ok {
				return f
			}
			if s, ok := v.(string); ok {
				f, _ := strconv.ParseFloat(s, 64)
				return f
			}
		}
		return 0
	}
	getInt := func(k string) int {
		f := getFloat(k)
		return int(f)
	}

	base := "/api/v1"
	calls := []ExecutableCall{}

	switch intent {
	case "propose_schedule":
		if j := getStr("job_id"); j != "" {
			calls = append(calls,
				ExecutableCall{Method: "GET", Path: base + "/ai/scheduling/jobs/" + j + "/assist", Purpose: "AI assist payload."},
				ExecutableCall{Method: "POST", Path: base + "/ai/scheduling/jobs/" + j + "/proposals", Purpose: "Persist proposal."},
			)
		}
	case "approve_proposal":
		if p := getStr("proposal_id"); p != "" {
			calls = append(calls, ExecutableCall{Method: "POST", Path: base + "/ai/scheduling/proposals/" + p + "/approve", Purpose: "Approve proposal."})
		}
	case "reject_proposal":
		if p := getStr("proposal_id"); p != "" {
			calls = append(calls, ExecutableCall{Method: "POST", Path: base + "/ai/scheduling/proposals/" + p + "/reject", Purpose: "Reject proposal."})
		}
	case "apply_proposal":
		if p := getStr("proposal_id"); p != "" {
			calls = append(calls, ExecutableCall{Method: "POST", Path: base + "/ai/scheduling/proposals/" + p + "/apply", Purpose: "Apply proposal."})
		} else if j := getStr("job_id"); j != "" {
			calls = append(calls, ExecutableCall{Method: "POST", Path: base + "/ai/scheduling/jobs/" + j + "/proposals", Purpose: "Generate proposal for job."})
		}
	case "schedule_all_jobs":
		calls = append(calls, ExecutableCall{
			Method: "POST", Path: base + "/ai/scheduling/batch-proposals",
			Body:    map[string]interface{}{"scope": "all_unscheduled"},
			Purpose: "Batch schedule all unscheduled jobs.",
		})
	case "explain_job":
		if j := getStr("job_id"); j != "" {
			calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/ai/scheduling/jobs/" + j + "/explanation", Purpose: "Job reasoning."})
		}
	case "delay_risk":
		if j := getStr("job_id"); j != "" {
			calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/ai/scheduling/jobs/" + j + "/delay-risk", Purpose: "Delay risk evaluation."})
		}
	case "machine_ranking":
		if js := getStr("job_step_id"); js != "" {
			calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/ai/scheduling/job-steps/" + js + "/machine-ranking", Purpose: "Machine ranking for job step."})
		}
	case "create_job":
		prod := getStr("product")
		if prod == "" {
			prod = getStr("product_id")
		}
		qty := getInt("quantity")
		if qty <= 0 {
			qty = 1
		}
		body := map[string]interface{}{"product_id": prod, "quantity_total": qty}
		if p := getStr("priority"); p != "" {
			body["priority"] = p
		}
		if d := getStr("deadline"); d != "" {
			body["deadline"] = d
		}
		calls = append(calls, ExecutableCall{Method: "POST", Path: base + "/jobs", Body: body, Purpose: "Create job."})
	case "reschedule", "reschedule_job":
		if j := getStr("job_id"); j != "" {
			calls = append(calls,
				ExecutableCall{Method: "GET", Path: base + "/ai/scheduling/jobs/" + j + "/assist", Purpose: "Review assist before reschedule."},
				ExecutableCall{Method: "POST", Path: base + "/ai/scheduling/jobs/" + j + "/proposals", Purpose: "Generate new proposal for reschedule."},
			)
		}
	case "cancel", "cancel_job":
		if j := getStr("job_id"); j != "" {
			calls = append(calls, ExecutableCall{Method: "DELETE", Path: base + "/jobs/" + j, Purpose: "Cancel job."})
		}
	case "query_status":
		resource := strings.ToLower(getStr("resource"))
		switch resource {
		case "jobs":
			if j := getStr("job_id"); j != "" {
				calls = append(calls,
					ExecutableCall{Method: "GET", Path: base + "/jobs/" + j, Purpose: "Job record."},
					ExecutableCall{Method: "GET", Path: base + "/ai/scheduling/jobs/" + j + "/explanation", Purpose: "Job explanation."},
				)
			} else {
				calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/jobs", Purpose: "List jobs."})
			}
		case "machines":
			calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/machines", Purpose: "List machines."})
		case "inventory":
			calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/inventory/materials", Purpose: "List materials."})
		default:
			calls = append(calls,
				ExecutableCall{Method: "GET", Path: base + "/dashboard/kpis", Purpose: "Dashboard KPIs."},
				ExecutableCall{Method: "GET", Path: base + "/alerts", Purpose: "Active alerts."},
			)
		}
	case "consume_material":
		mat := getStr("material")
		if mat == "" {
			mat = getStr("material_id")
		}
		qty := getFloat("quantity")
		if mat != "" && qty > 0 {
			body := map[string]interface{}{"material_id": mat, "quantity": qty}
			if j := getStr("job_id"); j != "" {
				body["reference_job_id"] = j
			}
			calls = append(calls, ExecutableCall{Method: "POST", Path: base + "/inventory/consume", Body: body, Purpose: "Consume material."})
		}
	case "receive_material":
		mat := getStr("material_id")
		if mat == "" {
			mat = getStr("material")
		}
		qty := getFloat("quantity")
		if mat != "" && qty > 0 {
			calls = append(calls, ExecutableCall{
				Method:  "POST",
				Path:    base + "/inventory/receive",
				Body:    map[string]interface{}{"material_id": mat, "quantity": qty},
				Purpose: "Receive material into inventory.",
			})
		}
	case "record_downtime":
		if m := getStr("machine_id"); m != "" {
			body := map[string]interface{}{"machine_id": m}
			if c := getStr("cause"); c != "" {
				body["cause"] = c
			}
			calls = append(calls, ExecutableCall{Method: "POST", Path: base + "/machines/downtime", Body: body, Purpose: "Record machine downtime."})
		}
	case "maintenance_alerts":
		calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/machines/maintenance-alerts", Purpose: "Maintenance alerts."})
	case "list_products":
		calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/products", Purpose: "List products."})
	case "high_risk_jobs":
		calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/predictive/high-risk-jobs", Purpose: "High-risk jobs forecast."})
	case "dashboard_kpis":
		calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/dashboard/kpis", Purpose: "Dashboard KPIs."})
	case "generate_report":
		rt := strings.ToLower(getStr("report_type"))
		switch rt {
		case "bottleneck", "bottlenecks":
			calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/ai/scheduling/bottleneck-forecast", Purpose: "Bottleneck forecast."})
		case "utilization":
			calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/reports/machine-utilization", Purpose: "Machine utilization report."})
		case "oee":
			calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/reports/oee", Purpose: "OEE report."})
		case "completion", "job", "jobs":
			calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/reports/job-completion", Purpose: "Job completion report."})
		case "inventory":
			calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/reports/inventory-trends", Purpose: "Inventory trends."})
		case "quality":
			calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/reports/quality-trends", Purpose: "Quality trends."})
		case "maintenance":
			calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/reports/maintenance-efficiency", Purpose: "Maintenance efficiency."})
		default:
			calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/reports/production-output", Purpose: "Production output report."})
		}
	case "split_step":
		if js := getStr("job_step_id"); js != "" {
			calls = append(calls, ExecutableCall{Method: "GET", Path: base + "/ai/scheduling/job-steps/" + js + "/split-suggestion", Purpose: "Split suggestion for job step."})
		}
	}
	return calls
}

