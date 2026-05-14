package service

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/pkg/id"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// AICommandProcessor processes natural language commands and optionally executes read-only insights.
type AICommandProcessor struct {
	orchestrator *AICommandOrchestrator
	predictive   *AIPredictiveService
	jobService   *JobService
}

// NewAICommandProcessor creates a new processor.
func NewAICommandProcessor(orchestrator *AICommandOrchestrator, predictive *AIPredictiveService, jobService *JobService) *AICommandProcessor {
	return &AICommandProcessor{
		orchestrator: orchestrator,
		predictive:   predictive,
		jobService:   jobService,
	}
}

// ProcessCommand parses the query, optionally executes read-only insights, and returns the response.
func (p *AICommandProcessor) ProcessCommand(query string, executeReadonly bool, debug bool) (*dto.AICommandResponse, error) {
	raw := strings.TrimSpace(query)
	plan := p.orchestrator.Parse(raw)
	turnID := id.NewPrefixed("AITURN-")
	res := &dto.AICommandResponse{
		TurnID:         turnID,
		Intent:         plan.Intent,
		Action:         plan.Action,
		Entities:       plan.Entities,
		Confidence:     plan.Confidence,
		Ambiguous:      plan.Ambiguous,
		Clarifications: plan.Clarifications,
		Message:        plan.Message,
		ExecutionMode:  "suggest_only",
	}

	// Apply confidence and clarifications
	if res.Confidence > 0 && res.Confidence < 0.65 {
		res.Ambiguous = true
		res.Clarifications = procClarificationsForIntent(res.Intent, res.Entities)
	}
	if res.Confidence == 0 {
		res.Confidence = procConfidenceForIntent(res.Intent, res.Entities)
	}

	switch plan.Action {
	case "propose_schedule":
		p.handleProposeSchedule(res, raw, executeReadonly)
	case "approve_proposal":
		p.handleApproveProposal(res, executeReadonly)
	case "reject_proposal":
		p.handleRejectProposal(res, executeReadonly)
	case "apply_proposal":
		p.handleApplyProposal(res, executeReadonly)
	case "schedule_all_jobs":
		p.handleScheduleAllJobs(res, executeReadonly)
	case "explain_job":
		p.handleExplainJob(res, raw, executeReadonly, debug)
	case "delay_risk":
		p.handleDelayRisk(res, raw, executeReadonly)
	case "machine_ranking":
		p.handleMachineRanking(res, raw, executeReadonly)
	case "create_job":
		p.handleCreateJob(res, executeReadonly)
	case "reschedule", "reschedule_job":
		p.handleRescheduleJob(res, raw, executeReadonly)
	case "cancel", "cancel_job":
		p.handleCancelJob(res, executeReadonly)
	case "query_status":
		p.handleQueryStatus(res, raw, executeReadonly)
	case "consume_material":
		p.handleConsumeMaterial(res, executeReadonly)
	case "generate_report":
		p.handleGenerateReport(res, raw, executeReadonly)
	case "receive_material":
		p.handleReceiveMaterial(res, executeReadonly)
	case "record_downtime":
		p.handleRecordDowntime(res, executeReadonly)
	case "maintenance_alerts":
		p.handleMaintenanceAlerts(res, executeReadonly)
	case "list_products":
		p.handleListProducts(res, executeReadonly)
	case "high_risk_jobs":
		p.handleHighRiskJobs(res, executeReadonly)
	case "dashboard_kpis":
		p.handleDashboardKPIs(res, executeReadonly)
	case "split_step":
		p.handleSplitStep(res, raw, executeReadonly)
	default:
		if res.Intent == "" {
			res.Intent = "unknown"
			res.Action = "none"
			res.Message = "Could not parse command. Try: create job, reschedule, cancel, status, consume, receive material, record downtime, maintenance alerts, list products, high risk jobs, dashboard, report."
		}
	}

	// Set requires_approval on each suggested call: GET = no approval; POST/PUT/PATCH/DELETE = approval required
	for i := range res.SuggestedCalls {
		res.SuggestedCalls[i].RequiresApproval = res.SuggestedCalls[i].Method != "GET"
	}

	// Build BDI result
	res.BDIResult = buildBDIResult(res)

	// Build result cards
	res.ResultCards = p.buildResultCards(res)
	p.normalizeUserMessage(res)

	// Unified UI helpers (optional; frontend can ignore)
	res.HumanMessage = res.Message
	res.MessageKind = "answer"
	res.StatusLabel = res.ExecutionMode
	if res.Ambiguous {
		res.MessageKind = "clarification"
		res.StatusLabel = "Needs clarification"
	} else if res.ExecutionMode == "blocked_write_action" {
		res.MessageKind = "approval_required"
		res.StatusLabel = "Waiting for approval"
	} else if res.ExecutionMode == "executed_readonly" {
		res.StatusLabel = "Done"
	} else if res.ExecutionMode == "readonly_execution_failed" {
		res.MessageKind = "error"
		res.StatusLabel = "Failed"
	} else if res.ExecutionMode == "suggest_only" {
		res.StatusLabel = "Suggested"
	}
	res.UIBlocks = []map[string]interface{}{
		{
			"type":  "thinking",
			"title": "Thinking",
			"payload": map[string]interface{}{
				"intent":         res.Intent,
				"confidence":     res.Confidence,
				"ambiguous":      res.Ambiguous,
				"clarifications": res.Clarifications,
				"entities":       res.Entities,
				"guidance":       res.Guidance,
			},
		},
	}
	res.DebugPayload = map[string]interface{}{
		"execution_mode":  res.ExecutionMode,
		"executed":        res.Executed,
		"suggested_calls": res.SuggestedCalls,
		"guidance":        res.Guidance,
		"entities":        res.Entities,
	}
	return res, nil
}

func (p *AICommandProcessor) handleProposeSchedule(res *dto.AICommandResponse, raw string, executeReadonly bool) {
	res.Guidance = []string{
		"Read-only proposal preview is transient unless you explicitly persist it.",
		"Persist a proposal when you want approval, history, stale detection, and apply-by-ID.",
		"Review readiness and machine ranking before dispatching production.",
	}
	if jobID, ok := res.Entities["job_id"].(string); ok && jobID != "" {
		res.SuggestedCalls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/ai/scheduling/jobs/" + jobID + "/assist", Purpose: "Open the full hybrid AI assist payload."},
			{Method: "POST", Path: "/api/v1/ai/scheduling/jobs/" + jobID + "/proposals", Purpose: "Persist a proposal for approval and lifecycle tracking."},
			{Method: "GET", Path: "/api/v1/scheduling/jobs/" + jobID + "/solver-preview", Purpose: "Inspect normalized scheduling inputs."},
		}
		if executeReadonly && p.predictive != nil {
			p.executeReadonly(res, dto.AISuggestedCall{
				Method:  "GET",
				Path:    "/api/v1/ai/scheduling/jobs/" + jobID + "/proposal",
				Purpose: "Return the current draft schedule proposal.",
			}, func() (interface{}, error) {
				return p.predictive.BuildProposal(jobID)
			})
		}
	}
}

func (p *AICommandProcessor) handleApproveProposal(res *dto.AICommandResponse, executeReadonly bool) {
	res.Guidance = []string{
		"Approval should target a persisted proposal ID.",
		"Use the proposal details endpoint to verify engine, score, and stale state before approval.",
	}
	if executeReadonly {
		res.ExecutionMode = "blocked_write_action"
		res.Guidance = append(res.Guidance, "Proposal approval is not executed from POST /api/v1/ai/command.")
	}
	if proposalID, ok := res.Entities["proposal_id"].(string); ok && proposalID != "" {
		res.SuggestedCalls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/ai/scheduling/proposals/" + proposalID, Purpose: "Review the proposal before approval."},
			{Method: "POST", Path: "/api/v1/ai/scheduling/proposals/" + proposalID + "/approve", Purpose: "Approve the proposal."},
		}
	}
}

func (p *AICommandProcessor) handleRejectProposal(res *dto.AICommandResponse, executeReadonly bool) {
	res.Guidance = []string{
		"Reject persisted proposals when the plan should not be used.",
		"Capture rejection reason so later evaluation can distinguish bad plans from process exceptions.",
	}
	if executeReadonly {
		res.ExecutionMode = "blocked_write_action"
		res.Guidance = append(res.Guidance, "Proposal rejection is not executed from POST /api/v1/ai/command.")
	}
	if proposalID, ok := res.Entities["proposal_id"].(string); ok && proposalID != "" {
		res.SuggestedCalls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/ai/scheduling/proposals/" + proposalID, Purpose: "Review the proposal before rejection."},
			{Method: "POST", Path: "/api/v1/ai/scheduling/proposals/" + proposalID + "/reject", Purpose: "Reject the proposal with planner reason."},
		}
	}
}

func (p *AICommandProcessor) handleApplyProposal(res *dto.AICommandResponse, executeReadonly bool) {
	res.Guidance = []string{
		"Apply-proposal currently supports jobs without existing active slots.",
		"Review the proposal endpoint before applying.",
	}
	if executeReadonly {
		res.ExecutionMode = "blocked_write_action"
		res.Guidance = append(res.Guidance, "Write actions are not executed from POST /api/v1/ai/command. Call the write endpoint explicitly after approval.")
	}
	if proposalID, ok := res.Entities["proposal_id"].(string); ok && proposalID != "" {
		res.SuggestedCalls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/ai/scheduling/proposals/" + proposalID, Purpose: "Review the persisted proposal details."},
			{Method: "POST", Path: "/api/v1/ai/scheduling/proposals/" + proposalID + "/approve", Purpose: "Approve the proposal before apply."},
			{Method: "POST", Path: "/api/v1/ai/scheduling/proposals/" + proposalID + "/apply", Purpose: "Apply the persisted proposal after approval."},
		}
	} else if jobID, ok := res.Entities["job_id"].(string); ok && jobID != "" {
		// Resolve job_id -> proposal_id when user says "Apply proposal for job JOB-X"
		var pID string
		if p.predictive != nil {
			pID, _ = p.predictive.GetLatestProposalIDForJob(jobID)
		}
		if pID != "" {
			res.SuggestedCalls = []dto.AISuggestedCall{
				{Method: "GET", Path: "/api/v1/ai/scheduling/proposals/" + pID, Purpose: "Review the proposal before apply."},
				{Method: "POST", Path: "/api/v1/ai/scheduling/proposals/" + pID + "/approve", Purpose: "Approve the proposal (if still draft)."},
				{Method: "POST", Path: "/api/v1/ai/scheduling/proposals/" + pID + "/apply", Purpose: "Apply the proposal to the job plan."},
			}
		} else {
			res.SuggestedCalls = []dto.AISuggestedCall{
				{Method: "POST", Path: "/api/v1/ai/scheduling/jobs/" + jobID + "/proposals", Purpose: "Generate and persist a proposal for approval."},
				{Method: "GET", Path: "/api/v1/ai/scheduling/jobs/" + jobID + "/proposals", Purpose: "Review proposal history for the job."},
				{Method: "GET", Path: "/api/v1/ai/scheduling/jobs/" + jobID + "/proposal", Purpose: "Inspect the transient preview before creating a persisted proposal."},
			}
		}
	}
}

func (p *AICommandProcessor) handleScheduleAllJobs(res *dto.AICommandResponse, executeReadonly bool) {
	res.Guidance = []string{
		"Batch proposal generation creates draft proposals for all unscheduled jobs (planned/scheduled, no active slots).",
		"Jobs are scheduled in priority order with shared machine state; each proposal is persisted for approval and apply.",
	}
	if executeReadonly {
		res.ExecutionMode = "blocked_write_action"
		res.Guidance = append(res.Guidance, "Batch proposal generation is a write action. Call the batch-proposals endpoint explicitly.")
	}
	res.SuggestedCalls = []dto.AISuggestedCall{
		{Method: "POST", Path: "/api/v1/ai/scheduling/batch-proposals", Body: map[string]interface{}{"scope": "all_unscheduled"}, Purpose: "Generate proposals for all unscheduled jobs."},
	}
}

func (p *AICommandProcessor) handleExplainJob(res *dto.AICommandResponse, raw string, executeReadonly bool, debug bool) {
	if jobID, ok := res.Entities["job_id"].(string); ok && jobID != "" {
		res.SuggestedCalls = []dto.AISuggestedCall{{
			Method:  "GET",
			Path:    "/api/v1/ai/scheduling/jobs/" + jobID + "/explanation",
			Purpose: "Planner-readable job reasoning.",
			UI:      &dto.AISuggestedCallUI{Display: "hidden_if_result_card_exists", Priority: "low"},
		}}
		if debug {
			res.SuggestedCalls = append(res.SuggestedCalls, dto.AISuggestedCall{
				Method:  "GET",
				Path:    "/api/v1/ai/scheduling/jobs/" + jobID + "/delay-risk",
				Purpose: "Inspect explicit risk factors.",
				UI:      &dto.AISuggestedCallUI{Display: "secondary", Priority: "low"},
			})
		}
		if executeReadonly && p.predictive != nil {
			p.executeReadonly(res, dto.AISuggestedCall{
				Method:  "GET",
				Path:    "/api/v1/ai/scheduling/jobs/" + jobID + "/explanation",
				Purpose: "Return planner-readable reasoning for the job.",
			}, func() (interface{}, error) {
				return p.predictive.ExplainJob(jobID)
			})
		}
	}
}

func (p *AICommandProcessor) normalizeUserMessage(res *dto.AICommandResponse) {
	if res == nil {
		return
	}
	if strings.HasPrefix(strings.ToLower(strings.TrimSpace(res.Message)), "parsed:") || strings.TrimSpace(res.Message) == "" {
		switch res.Action {
		case "explain_job":
			if jobID, ok := res.Entities["job_id"].(string); ok && jobID != "" {
				res.Message = "Here is a concise explanation for " + jobID + "."
			} else {
				res.Message = "Here is the job explanation."
			}
		case "delay_risk":
			if jobID, ok := res.Entities["job_id"].(string); ok && jobID != "" {
				res.Message = jobID + " delay risk is ready for review."
			} else {
				res.Message = "Delay risk is ready for review."
			}
		case "create_job":
			res.Message = "I can create this job. Please approve to continue."
		default:
			res.Message = "I prepared the next best action for your request."
		}
	}
}

func (p *AICommandProcessor) handleDelayRisk(res *dto.AICommandResponse, raw string, executeReadonly bool) {
	if jobID, ok := res.Entities["job_id"].(string); ok && jobID != "" {
		res.SuggestedCalls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/ai/scheduling/jobs/" + jobID + "/delay-risk", Purpose: "Structured delay-risk evaluation."},
		}
		if executeReadonly && p.predictive != nil {
			p.executeReadonly(res, dto.AISuggestedCall{
				Method:  "GET",
				Path:    "/api/v1/ai/scheduling/jobs/" + jobID + "/delay-risk",
				Purpose: "Return the structured delay-risk breakdown.",
			}, func() (interface{}, error) {
				return p.predictive.GetDelayRisk(jobID)
			})
		}
	}
}

func (p *AICommandProcessor) handleMachineRanking(res *dto.AICommandResponse, raw string, executeReadonly bool) {
	if jobStepID, ok := res.Entities["job_step_id"].(string); ok && jobStepID != "" {
		res.SuggestedCalls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/ai/scheduling/job-steps/" + jobStepID + "/machine-ranking", Purpose: "Rank machine choices for a job step."},
		}
		if executeReadonly && p.predictive != nil {
			p.executeReadonly(res, dto.AISuggestedCall{
				Method:  "GET",
				Path:    "/api/v1/ai/scheduling/job-steps/" + jobStepID + "/machine-ranking",
				Purpose: "Return ranked machine candidates for the job step.",
			}, func() (interface{}, error) {
				return p.predictive.RankMachinesForJobStep(jobStepID, time.Now(), time.Now().Add(8*time.Hour))
			})
		}
	}
}

func (p *AICommandProcessor) handleCreateJob(res *dto.AICommandResponse, executeReadonly bool) {
	if res.Ambiguous {
		return // Do not add suggested_calls until user provides missing info (quantity, product)
	}
	if executeReadonly {
		res.ExecutionMode = "blocked_write_action"
		res.Guidance = append(res.Guidance, "Job creation is a write action and is not executed from POST /api/v1/ai/command.")
	}
	body := buildCreateJobBody(res.Entities)
	res.SuggestedCalls = []dto.AISuggestedCall{
		{Method: "POST", Path: "/api/v1/jobs", Body: body, Purpose: "Create a job using the extracted entities."},
	}
}

func (p *AICommandProcessor) handleRescheduleJob(res *dto.AICommandResponse, raw string, executeReadonly bool) {
	if executeReadonly {
		res.ExecutionMode = "blocked_write_action"
		res.Guidance = append(res.Guidance, "Rescheduling is a write action and is not executed from POST /api/v1/ai/command.")
	}
	if jobID, ok := res.Entities["job_id"].(string); ok && jobID != "" {
		res.SuggestedCalls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/ai/scheduling/jobs/" + jobID + "/assist", Purpose: "Review AI scheduling assist before rescheduling."},
			{Method: "GET", Path: "/api/v1/scheduling/jobs/" + jobID + "/solver-preview", Purpose: "Inspect current scheduling model inputs."},
		}
	}
}

func (p *AICommandProcessor) handleCancelJob(res *dto.AICommandResponse, executeReadonly bool) {
	if executeReadonly {
		res.ExecutionMode = "blocked_write_action"
		res.Guidance = append(res.Guidance, "Cancellation is a write action and is not executed from POST /api/v1/ai/command.")
	}
	if jobID, ok := res.Entities["job_id"].(string); ok && jobID != "" {
		res.SuggestedCalls = []dto.AISuggestedCall{
			{Method: "DELETE", Path: "/api/v1/jobs/" + jobID, Purpose: "Cancel the job."},
		}
	}
}

func (p *AICommandProcessor) handleQueryStatus(res *dto.AICommandResponse, raw string, executeReadonly bool) {
	resource, _ := res.Entities["resource"].(string)
	jobID, hasJobID := res.Entities["job_id"].(string)

	if resource == "jobs" || (resource == "" && hasJobID) {
		if hasJobID && jobID != "" {
			res.SuggestedCalls = []dto.AISuggestedCall{
				{Method: "GET", Path: "/api/v1/jobs/" + jobID, Purpose: "Load the raw job record."},
				{Method: "GET", Path: "/api/v1/ai/scheduling/jobs/" + jobID + "/explanation", Purpose: "Explain current schedule state."},
			}
			if executeReadonly && p.jobService != nil {
				p.executeReadonly(res, dto.AISuggestedCall{
					Method:  "GET",
					Path:    "/api/v1/jobs/" + jobID,
					Purpose: "Return the raw job plus AI explanation.",
				}, func() (interface{}, error) {
					job, err := p.jobService.GetByID(jobID)
					if err != nil {
						return nil, err
					}
					result := map[string]interface{}{"job": job}
					if p.predictive != nil {
						if explanation, err := p.predictive.ExplainJob(jobID); err == nil {
							result["explanation"] = explanation
						}
					}
					return result, nil
				})
			}
			return
		}
		if resource == "jobs" {
			if route, ok := queryRoutes["jobs"]; ok {
				val := ValidateQueryEntities(res.Entities, route.ParamsMeta)
				path := buildQueryParams(route.Path, val.AcceptedParams)
				res.SuggestedCalls = []dto.AISuggestedCall{
					{Method: "GET", Path: path, Purpose: "List all jobs."},
				}
				if len(val.RejectedParams) > 0 {
					res.Message += generateRejectionMessage(val.RejectedParams)
				}
			}
			return
		}
	}

	if route, ok := queryRoutes[resource]; ok {
		val := ValidateQueryEntities(res.Entities, route.ParamsMeta)
		path := buildQueryParams(route.Path, val.AcceptedParams)
		res.SuggestedCalls = []dto.AISuggestedCall{
			{Method: "GET", Path: path, Purpose: "List " + resource + " and their status."},
		}
		if len(val.RejectedParams) > 0 {
			res.Message += generateRejectionMessage(val.RejectedParams)
		}
		return
	}
	if resource == "inventory" {
		res.SuggestedCalls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/inventory/materials", Purpose: "List inventory materials and stock levels."},
		}
		return
	}
	if resource == "general" || resource == "" {
		res.SuggestedCalls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/dashboard/kpis", Purpose: "Dashboard KPIs."},
			{Method: "GET", Path: "/api/v1/alerts", Purpose: "Active alerts."},
		}
	}
}

func (p *AICommandProcessor) handleConsumeMaterial(res *dto.AICommandResponse, executeReadonly bool) {
	if res.Ambiguous {
		return // Do not add suggested_calls until user provides material and quantity
	}
	if executeReadonly {
		res.ExecutionMode = "blocked_write_action"
		res.Guidance = append(res.Guidance, "Material consumption is a write action and is not executed from POST /api/v1/ai/command.")
	}
	body := buildConsumeMaterialBody(res.Entities)
	res.SuggestedCalls = []dto.AISuggestedCall{
		{Method: "POST", Path: "/api/v1/inventory/consume", Body: body, Purpose: "Apply material consumption."},
	}
}

func (p *AICommandProcessor) handleGenerateReport(res *dto.AICommandResponse, raw string, executeReadonly bool) {
	reportType, _ := res.Entities["report_type"].(string)
	reportType = strings.ToLower(reportType)

	var calls []dto.AISuggestedCall
	var readonlyPath string
	var readonlyFn func() (interface{}, error)

	switch reportType {
	case "bottleneck", "bottlenecks":
		calls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/ai/scheduling/bottleneck-forecast", Purpose: "AI-oriented bottleneck forecast."},
			{Method: "GET", Path: "/api/v1/reports/bottlenecks", Purpose: "Bottleneck report."},
		}
		if p.predictive != nil {
			readonlyPath = "/api/v1/ai/scheduling/bottleneck-forecast"
			readonlyFn = func() (interface{}, error) { return p.predictive.ForecastBottlenecks(7) }
		}
	case "utilization":
		calls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/reports/machine-utilization", Purpose: "Machine utilization report."},
		}
	case "oee":
		calls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/reports/oee", Purpose: "OEE trends report."},
		}
	case "completion", "job", "jobs":
		calls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/reports/job-completion", Purpose: "Job completion report."},
		}
	case "inventory":
		calls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/reports/inventory-trends", Purpose: "Inventory trends report."},
		}
	case "quality":
		calls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/reports/quality-trends", Purpose: "Quality trends report."},
		}
	case "maintenance":
		calls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/reports/maintenance-efficiency", Purpose: "Maintenance efficiency report."},
		}
	default:
		calls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/reports/production-output", Purpose: "Production output report."},
		}
	}

	res.SuggestedCalls = calls
	if executeReadonly && readonlyFn != nil && readonlyPath != "" {
		p.executeReadonly(res, dto.AISuggestedCall{Method: "GET", Path: readonlyPath, Purpose: "Return the report data."}, readonlyFn)
	}
}

func (p *AICommandProcessor) handleReceiveMaterial(res *dto.AICommandResponse, executeReadonly bool) {
	if res.Ambiguous {
		return // Do not add suggested_calls until user provides material_id and quantity
	}
	if executeReadonly {
		res.ExecutionMode = "blocked_write_action"
		res.Guidance = append(res.Guidance, "Receiving material is a write action.")
	}
	mat := entityStr(res.Entities, "material_id", "material")
	qty := entityFloat(res.Entities, "quantity")
	if mat != "" && qty > 0 {
		res.SuggestedCalls = []dto.AISuggestedCall{
			{Method: "POST", Path: "/api/v1/inventory/receive", Body: map[string]interface{}{"material_id": mat, "quantity": qty}, Purpose: "Receive material into inventory."},
		}
	}
}

func (p *AICommandProcessor) handleRecordDowntime(res *dto.AICommandResponse, executeReadonly bool) {
	if res.Ambiguous {
		return // Do not add suggested_calls until user provides machine_id
	}
	if executeReadonly {
		res.ExecutionMode = "blocked_write_action"
		res.Guidance = append(res.Guidance, "Recording downtime is a write action.")
	}
	if m := entityStr(res.Entities, "machine_id"); m != "" {
		body := map[string]interface{}{"machine_id": m}
		if c := entityStr(res.Entities, "cause"); c != "" {
			body["cause"] = c
		}
		res.SuggestedCalls = []dto.AISuggestedCall{
			{Method: "POST", Path: "/api/v1/machines/downtime", Body: body, Purpose: "Record machine downtime."},
		}
	}
}

func (p *AICommandProcessor) handleMaintenanceAlerts(res *dto.AICommandResponse, executeReadonly bool) {
	res.SuggestedCalls = []dto.AISuggestedCall{
		{Method: "GET", Path: "/api/v1/machines/maintenance-alerts", Purpose: "Maintenance alerts."},
	}
}

func (p *AICommandProcessor) handleListProducts(res *dto.AICommandResponse, executeReadonly bool) {
	res.SuggestedCalls = []dto.AISuggestedCall{
		{Method: "GET", Path: "/api/v1/products", Purpose: "List products."},
	}
}

func (p *AICommandProcessor) handleHighRiskJobs(res *dto.AICommandResponse, executeReadonly bool) {
	res.SuggestedCalls = []dto.AISuggestedCall{
		{Method: "GET", Path: "/api/v1/predictive/high-risk-jobs", Purpose: "High-risk jobs forecast."},
	}
}

func (p *AICommandProcessor) handleDashboardKPIs(res *dto.AICommandResponse, executeReadonly bool) {
	res.SuggestedCalls = []dto.AISuggestedCall{
		{Method: "GET", Path: "/api/v1/dashboard/kpis", Purpose: "Dashboard KPIs."},
	}
}

func (p *AICommandProcessor) handleSplitStep(res *dto.AICommandResponse, raw string, executeReadonly bool) {
	if js := entityStr(res.Entities, "job_step_id"); js != "" {
		res.SuggestedCalls = []dto.AISuggestedCall{
			{Method: "GET", Path: "/api/v1/ai/scheduling/job-steps/" + js + "/split-suggestion", Purpose: "Split suggestion for job step."},
		}
	}
}

func (p *AICommandProcessor) executeReadonly(res *dto.AICommandResponse, call dto.AISuggestedCall, fn func() (interface{}, error)) {
	if res == nil || fn == nil {
		return
	}
	result, err := fn()
	if err != nil {
		res.ExecutionMode = "readonly_execution_failed"
		res.Guidance = append(res.Guidance, "Read-only execution failed: "+err.Error())
		return
	}
	res.ExecutionMode = "executed_readonly"
	res.Executed = true
	res.ExecutedCall = &call
	res.Insights = result
	if p.predictive != nil {
		p.predictive.RecordReadonlyExecution()
	}
}

func (p *AICommandProcessor) buildResultCards(res *dto.AICommandResponse) []dto.AIResultCard {
	if res.Ambiguous {
		return []dto.AIResultCard{{
			Kind:    "clarification_required",
			Title:   "Clarification Required",
			Tone:    "warning",
			Summary: res.Message,
			Bullets: res.Clarifications,
			Actions: res.SuggestedCalls,
		}}
	}
	if res.ExecutionMode == "blocked_write_action" {
		return []dto.AIResultCard{{
			Kind:    "approval_required",
			Title:   "Manual Approval Required",
			Tone:    "warning",
			Summary: res.Message,
			Bullets: res.Guidance,
			Actions: res.SuggestedCalls,
		}}
	}
	if !res.Executed {
		return nil
	}

	switch insight := res.Insights.(type) {
	case *SchedulingProposal:
		if insight == nil {
			return nil
		}
		metrics := []dto.AIResultMetric{
			{Label: "Job", Value: insight.JobID},
			{Label: "Feasible", Value: boolLabel(insight.Feasible)},
			{Label: "Proposed Slots", Value: fmt.Sprintf("%d", len(insight.ProposedSlots))},
			{Label: "Earliest Start", Value: formatTime(insight.EarliestStart)},
		}
		if insight.EstimatedCompletion != nil {
			metrics = append(metrics, dto.AIResultMetric{Label: "Estimated Completion", Value: formatTime(*insight.EstimatedCompletion)})
		}
		bullets := append([]string{}, insight.Summary...)
		bullets = append(bullets, insight.BlockedReasons...)
		return []dto.AIResultCard{{
			Kind:    "schedule_proposal",
			Title:   "Schedule Proposal",
			Tone:    proposalTone(insight.Feasible),
			Summary: proposalSummary(insight),
			Metrics: metrics,
			Bullets: limitStrings(bullets, 6),
			Actions: res.SuggestedCalls,
		}}
	case *SchedulingExplanation:
		if insight == nil {
			return nil
		}
		bullets := append([]string{}, insight.KeyPoints...)
		bullets = append(bullets, insight.RecommendedActions...)
		return []dto.AIResultCard{{
			Kind:    "job_explanation",
			Title:   "Job Explanation",
			Tone:    "info",
			Summary: insight.Summary,
			Metrics: []dto.AIResultMetric{
				{Label: "Job", Value: insight.JobID},
				{Label: "Generated At", Value: formatTime(insight.GeneratedAt)},
			},
			Bullets: limitStrings(bullets, 6),
			Actions: res.SuggestedCalls,
		}}
	case *DelayRiskDetail:
		if insight == nil {
			return nil
		}
		return []dto.AIResultCard{{
			Kind:    "delay_risk",
			Title:   "Delay Risk",
			Tone:    riskTone(insight.RiskLevel),
			Summary: insight.Issue,
			Metrics: []dto.AIResultMetric{
				{Label: "Job", Value: insight.JobID},
				{Label: "Risk Level", Value: insight.RiskLevel},
				{Label: "Risk Score", Value: fmt.Sprintf("%.1f", insight.RiskScore)},
				{Label: "Projected Delay", Value: fmt.Sprintf("%d min", insight.DelayMinutes)},
			},
			Bullets: limitStrings(insight.Reasons, 6),
			Actions: res.SuggestedCalls,
		}}
	case *MachineRankingResult:
		if insight == nil {
			return nil
		}
		summary := "No candidate machines ranked."
		bullets := []string{}
		if len(insight.Candidates) > 0 {
			best := insight.Candidates[0]
			summary = fmt.Sprintf("Best candidate is %s with score %.1f.", best.MachineName, best.Score)
			bullets = append(bullets, best.Explanation...)
		}
		return []dto.AIResultCard{{
			Kind:    "machine_ranking",
			Title:   "Machine Ranking",
			Tone:    "info",
			Summary: summary,
			Metrics: []dto.AIResultMetric{
				{Label: "Job Step", Value: insight.JobStepID},
				{Label: "Candidates", Value: fmt.Sprintf("%d", len(insight.Candidates))},
				{Label: "Window Start", Value: formatTime(insight.WindowStart)},
				{Label: "Window End", Value: formatTime(insight.WindowEnd)},
			},
			Bullets: limitStrings(bullets, 5),
			Actions: res.SuggestedCalls,
		}}
	case *BottleneckForecastResult:
		if insight == nil {
			return nil
		}
		atRisk := 0
		bullets := make([]string, 0, len(insight.Entries))
		for _, entry := range insight.Entries {
			if entry.AtRisk {
				atRisk++
				bullets = append(bullets, fmt.Sprintf("%s load %.1f with %d upcoming slots.", entry.MachineName, entry.LoadScore, entry.UpcomingSlots))
			}
		}
		if len(bullets) == 0 {
			bullets = append(bullets, "No high-risk bottlenecks detected in the forecast window.")
		}
		return []dto.AIResultCard{{
			Kind:    "bottleneck_forecast",
			Title:   "Bottleneck Forecast",
			Tone:    forecastTone(atRisk),
			Summary: fmt.Sprintf("%d machine(s) flagged at risk over the next %d day(s).", atRisk, insight.DaysAhead),
			Metrics: []dto.AIResultMetric{
				{Label: "Days Ahead", Value: fmt.Sprintf("%d", insight.DaysAhead)},
				{Label: "At Risk", Value: fmt.Sprintf("%d", atRisk)},
				{Label: "Generated At", Value: formatTime(insight.GeneratedAt)},
			},
			Bullets: limitStrings(bullets, 5),
			Actions: res.SuggestedCalls,
		}}
	case map[string]interface{}:
		return p.buildMapInsightCards(insight, res)
	default:
		return nil
	}
}

func (p *AICommandProcessor) buildMapInsightCards(insight map[string]interface{}, res *dto.AICommandResponse) []dto.AIResultCard {
	jobAny, hasJob := insight["job"]
	if !hasJob {
		return nil
	}
	job, ok := jobAny.(*domain.Job)
	if !ok || job == nil {
		return nil
	}
	bullets := []string{}
	if explanationAny, ok := insight["explanation"]; ok {
		if explanation, ok := explanationAny.(*SchedulingExplanation); ok && explanation != nil {
			bullets = append(bullets, explanation.KeyPoints...)
		}
	}
	return []dto.AIResultCard{{
		Kind:    "job_status",
		Title:   "Job Status",
		Tone:    statusTone(job.Status),
		Summary: fmt.Sprintf("Job %s is currently %s.", job.JobID, job.Status),
		Metrics: []dto.AIResultMetric{
			{Label: "Product", Value: job.ProductID},
			{Label: "Priority", Value: job.Priority},
			{Label: "Quantity", Value: fmt.Sprintf("%d", job.QuantityTotal)},
			{Label: "Deadline", Value: formatTime(job.Deadline)},
		},
		Bullets: limitStrings(bullets, 5),
		Actions: res.SuggestedCalls,
	}}
}

func entityStr(entities map[string]interface{}, keys ...string) string {
	for _, k := range keys {
		if v, ok := entities[k]; ok {
			if s, ok := v.(string); ok && s != "" {
				return s
			}
			if n, ok := v.(float64); ok {
				return strconv.FormatFloat(n, 'f', -1, 64)
			}
		}
	}
	return ""
}

func buildQueryParams(basePath string, accepted map[string]string) string {
	u, err := url.Parse(basePath)
	if err != nil {
		return basePath
	}
	q := u.Query()
	for k, v := range accepted {
		q.Add(k, v)
	}
	u.RawQuery = q.Encode()
	return u.String()
}

func generateRejectionMessage(rejected []RejectedParam) string {
	var msgs []string
	for _, rp := range rejected {
		msg := fmt.Sprintf("\n- '%s' is not supported.", rp.Field)
		if rp.Reason == "Invalid value" && len(rp.AllowedValues) > 0 {
			msg = fmt.Sprintf("\n- '%s' must be one of: %s.", rp.Field, strings.Join(rp.AllowedValues, ", "))
		}
		msgs = append(msgs, msg)
	}
	return "\n\nNote: The following filters could not be applied:" + strings.Join(msgs, "")
}

func entityFloat(entities map[string]interface{}, k string) float64 {
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

func buildCreateJobBody(entities map[string]interface{}) map[string]interface{} {
	product := entityStr(entities, "product", "product_id")
	qty := int(entityFloat(entities, "quantity"))
	if qty <= 0 {
		qty = 1
	}
	body := map[string]interface{}{"product_id": product, "quantity_total": qty}
	if p := entityStr(entities, "priority"); p != "" {
		body["priority"] = p
	}
	if d := entityStr(entities, "deadline"); d != "" {
		body["deadline"] = d
	}
	return body
}

func buildConsumeMaterialBody(entities map[string]interface{}) map[string]interface{} {
	material := entityStr(entities, "material", "material_id")
	qty := entityFloat(entities, "quantity")
	body := map[string]interface{}{"material_id": material, "quantity": qty}
	if j := entityStr(entities, "job_id"); j != "" {
		body["reference_job_id"] = j
	}
	return body
}

func buildBDIResult(res *dto.AICommandResponse) *dto.BDIResult {
	if res.Intent == "unknown" || res.Action == "none" {
		return nil
	}
	calls := ResolveAction(res.Action, res.Entities)
	execCalls := make([]dto.BDIExecutableCall, len(calls))
	for i, c := range calls {
		execCalls[i] = dto.BDIExecutableCall{
			Method:           c.Method,
			Path:             c.Path,
			Body:             c.Body,
			Purpose:          c.Purpose,
			RequiresApproval: c.Method != "GET",
		}
	}
	resource, _ := res.Entities["resource"].(string)
	return &dto.BDIResult{
		Beliefs: dto.BDIBeliefs{
			Entities: res.Entities,
			Resource: resource,
		},
		Desire: dto.BDIDesire{
			Intent:     res.Intent,
			Confidence: res.Confidence,
		},
		Intention: dto.BDIIntention{
			Action:          res.Action,
			ExecutableCalls: execCalls,
		},
	}
}

func procConfidenceForIntent(intent string, entities map[string]interface{}) float64 {
	confidence := 0.55
	switch intent {
	case "propose_schedule", "explain_job", "delay_risk":
		if _, ok := entities["job_id"]; ok {
			confidence += 0.35
		}
	case "apply_proposal":
		if _, ok := entities["proposal_id"]; ok {
			confidence += 0.35
		} else if _, ok := entities["job_id"]; ok {
			confidence += 0.3
		}
	case "approve_proposal", "reject_proposal":
		if _, ok := entities["proposal_id"]; ok {
			confidence += 0.4
		}
	case "machine_ranking":
		if _, ok := entities["job_step_id"]; ok {
			confidence += 0.35
		}
	case "query_status":
		confidence += 0.15
		if _, ok := entities["job_id"]; ok {
			confidence += 0.2
		}
	default:
		confidence += 0.1 * float64(len(entities))
	}
	if confidence > 0.99 {
		confidence = 0.99
	}
	return confidence
}

func procClarificationsForIntent(intent string, entities map[string]interface{}) []string {
	switch intent {
	case "propose_schedule", "apply_proposal", "explain_job", "delay_risk":
		if _, ok := entities["job_id"]; !ok {
			if intent == "apply_proposal" {
				return []string{
					"Specify either a persisted proposal ID like `proposal AIPROP-1234` or a target job ID like `job JOB-1234`.",
				}
			}
			return []string{"Specify the target job ID, for example: `job JOB-1234`."}
		}
	case "machine_ranking":
		if _, ok := entities["job_step_id"]; !ok {
			return []string{"Specify the job step ID, for example: `job step JS-1234`."}
		}
	case "approve_proposal", "reject_proposal":
		if _, ok := entities["proposal_id"]; !ok {
			return []string{"Specify the persisted proposal ID, for example: `proposal AIPROP-1234`."}
		}
	}
	return nil
}

func limitStrings(values []string, max int) []string {
	if len(values) <= max {
		return values
	}
	return values[:max]
}

func formatTime(v time.Time) string {
	if v.IsZero() {
		return ""
	}
	return v.UTC().Format(time.RFC3339)
}

func boolLabel(v bool) string {
	if v {
		return "Yes"
	}
	return "No"
}

func proposalTone(feasible bool) string {
	if feasible {
		return "positive"
	}
	return "warning"
}

func proposalSummary(proposal *SchedulingProposal) string {
	if proposal == nil {
		return ""
	}
	if proposal.Feasible {
		return fmt.Sprintf("Feasible proposal with %d slot(s) ready for planner review.", len(proposal.ProposedSlots))
	}
	if len(proposal.BlockedReasons) > 0 {
		return "Proposal is blocked: " + proposal.BlockedReasons[0]
	}
	return "Proposal is not currently feasible."
}

func riskTone(level string) string {
	switch strings.ToLower(level) {
	case "high":
		return "critical"
	case "medium":
		return "warning"
	default:
		return "positive"
	}
}

func forecastTone(atRisk int) string {
	if atRisk > 0 {
		return "warning"
	}
	return "positive"
}

func statusTone(status string) string {
	switch strings.ToLower(status) {
	case "completed":
		return "positive"
	case "cancelled", "paused":
		return "warning"
	default:
		return "info"
	}
}
