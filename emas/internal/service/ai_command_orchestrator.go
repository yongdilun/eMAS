package service

import (
	"context"
	"encoding/json"
	"regexp"
	"strconv"
	"strings"
	"time"
)

type AICommandPlan struct {
	Intent         string                 `json:"intent"`
	Action         string                 `json:"action"`
	Entities       map[string]interface{} `json:"entities"`
	Confidence     float64                `json:"confidence,omitempty"`
	Ambiguous      bool                   `json:"ambiguous,omitempty"`
	Clarifications []string               `json:"clarifications,omitempty"`
	Message        string                 `json:"message"`
}

type AICommandOrchestrator struct{}

func NewAICommandOrchestrator() *AICommandOrchestrator {
	return &AICommandOrchestrator{}
}

func (o *AICommandOrchestrator) Parse(raw string) AICommandPlan {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return AICommandPlan{
			Intent:     "unknown",
			Action:     "none",
			Entities:   map[string]interface{}{},
			Confidence: 0,
			Ambiguous:  true,
			Message:    "Empty command. Try: propose schedule for job JOB-1234.",
			Clarifications: []string{
				"Provide a concrete instruction, for example: `propose schedule for job JOB-1234`.",
			},
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	client := NewLLMParserClient()
	rawJSON, err := client.ParseCommand(ctx, raw)
	if err != nil || len(rawJSON) == 0 {
		// Deterministic fallback for common commands when the LLM is unavailable.
		if fb, ok := fallbackParse(raw); ok {
			return fb
		}
		return AICommandPlan{
			Intent:     "unknown",
			Action:     "none",
			Entities:   map[string]interface{}{},
			Confidence: 0,
			Ambiguous:  true,
			Message:    "LLM parser was unavailable or returned no result. Try again or use the structured endpoints directly.",
			Clarifications: []string{
				"Use explicit API calls like GET /api/v1/jobs or POST /api/v1/ai/scheduling/jobs/:id/proposals.",
			},
		}
	}

	dec := json.NewDecoder(strings.NewReader(string(rawJSON)))
	dec.DisallowUnknownFields()
	var plan AICommandPlan
	if err := dec.Decode(&plan); err != nil {
		if fb, ok := fallbackParse(raw); ok {
			return fb
		}
		return AICommandPlan{
			Intent:     "unknown",
			Action:     "none",
			Entities:   map[string]interface{}{},
			Confidence: 0,
			Ambiguous:  true,
			Message:    "LLM parser returned invalid JSON. Falling back to safe failure.",
			Clarifications: []string{
				"Try a simpler phrasing or use explicit job/proposal identifiers.",
			},
		}
	}

	// Ensure there are no trailing tokens beyond the single JSON object.
	var extra interface{}
	if err := dec.Decode(&extra); err == nil {
		return AICommandPlan{
			Intent:     "unknown",
			Action:     "none",
			Entities:   map[string]interface{}{},
			Confidence: 0,
			Ambiguous:  true,
			Message:    "LLM parser returned extra data beyond a single JSON object.",
			Clarifications: []string{
				"Try a simpler phrasing or use explicit job/proposal identifiers.",
			},
		}
	}

	validated, ok, missing := validatePlan(raw, &plan)
	if !ok {
		// One-shot repair: if JSON is valid but required entities are missing,
		// ask the LLM to fill them from the original text. Use a short timeout
		// to avoid cascading delays when the service is busy.
		if len(missing) > 0 {
			repairCtx, repairCancel := context.WithTimeout(ctx, 1*time.Second)
			defer repairCancel()
			if repairedJSON, err := client.RepairCommand(repairCtx, raw, missing); err == nil && len(repairedJSON) > 0 {
				dec2 := json.NewDecoder(strings.NewReader(string(repairedJSON)))
				dec2.DisallowUnknownFields()
				var plan2 AICommandPlan
				if err := dec2.Decode(&plan2); err == nil {
					var extra2 interface{}
					if err := dec2.Decode(&extra2); err != nil {
						if validated2, ok2, _ := validatePlan(raw, &plan2); ok2 {
							return validated2
						}
					}
				}
			}
		}
		return validated
	}

	// Final deterministic repairs (enterprise guardrails) for actions where
	// the LLM is correct on intent but may omit entities.
	if validated.Entities == nil {
		validated.Entities = map[string]interface{}{}
	}
	lowerRawFinal := strings.ToLower(raw)
	if validated.Action == "create_job" {
		repairEntitiesFromRaw(raw, "create_job", validated.Entities)
		normalizeEntityTypes(validated.Entities)
		// Clean up common trailing phrases accidentally included in LLM/product strings.
		if pv, ok := validated.Entities["product"].(string); ok {
			p := strings.TrimSpace(pv)
			if idx := strings.Index(p, "("); idx >= 0 {
				p = strings.TrimSpace(p[:idx])
			}
			lowerP := strings.ToLower(p)
			if idx := strings.Index(lowerP, "as a new job"); idx >= 0 {
				p = strings.TrimSpace(p[:idx])
			}
			if idx := strings.Index(lowerP, "as a job"); idx >= 0 {
				p = strings.TrimSpace(p[:idx])
			}
			suffixes := []string{" asap", " rush", " now", " immediately", " later today", " today", " tonight", " tomorrow", " as job", " as a job", " (rush order)", " (quantity tbd)"}
			for _, suf := range suffixes {
				if strings.HasSuffix(lowerP, suf) {
					p = strings.TrimSpace(p[:len(p)-len(suf)])
					lowerP = strings.ToLower(p)
				}
			}
			validated.Entities["product"] = strings.TrimSpace(p)
		}
	}
	// If user clearly wants to change the schedule, never keep delay_risk.
	if (strings.Contains(lowerRawFinal, "reschedule") ||
		strings.Contains(lowerRawFinal, "move job") ||
		strings.Contains(lowerRawFinal, "move ") ||
		strings.Contains(lowerRawFinal, "postpone") ||
		strings.Contains(lowerRawFinal, "push back") ||
		strings.Contains(lowerRawFinal, "later today")) &&
		validated.Action == "delay_risk" {
		validated.Intent = "reschedule"
		validated.Action = "reschedule"
	}
	// If the LLM produced an unknown/none plan, but the text matches a known
	// deterministic pattern, prefer the deterministic parse.
	if fb, ok := fallbackParse(raw); ok {
		lowerRaw := strings.ToLower(raw)
		// Always let explicit reschedule/cancel/schedule-all keywords override.
		if strings.Contains(lowerRaw, "reschedule") || strings.Contains(lowerRaw, "resched") || strings.Contains(lowerRaw, "move job") || strings.Contains(lowerRaw, "move ") || strings.Contains(lowerRaw, "postpone") || strings.Contains(lowerRaw, "push ") ||
			strings.Contains(lowerRaw, "cancel") || strings.Contains(lowerRaw, "remove job") || strings.Contains(lowerRaw, "delete job") ||
			strings.Contains(lowerRaw, "schedule all") || strings.Contains(lowerRaw, "batch schedule") ||
			((strings.Contains(lowerRaw, "create") || strings.Contains(lowerRaw, "add") || strings.Contains(lowerRaw, "job request")) && (strings.Contains(lowerRaw, "job") || strings.Contains(lowerRaw, "order"))) ||
			(strings.Contains(lowerRaw, "what") && (strings.Contains(lowerRaw, "going on") || strings.Contains(lowerRaw, "explain")) && (strings.Contains(lowerRaw, "job") || extractJobID(raw) != "")) ||
			((strings.Contains(lowerRaw, "gimme") || strings.Contains(lowerRaw, "recomendation") || (strings.Contains(lowerRaw, "need") && strings.Contains(lowerRaw, "recomendation"))) && (strings.Contains(lowerRaw, "schedule") || strings.Contains(lowerRaw, "plan")) && extractJobID(raw) != "") {
			return fb
		}
		if validated.Intent == "unknown" && validated.Action == "none" {
			return fb
		}
	}
	return validated
}

func (o *AICommandOrchestrator) finalize(intent, action, message string, entities map[string]interface{}) AICommandPlan {
	plan := AICommandPlan{
		Intent:     intent,
		Action:     action,
		Entities:   entities,
		Confidence: confidenceForIntent(intent, entities),
		Message:    message,
	}
	if plan.Confidence > 0 && plan.Confidence < 0.65 {
		plan.Ambiguous = true
		plan.Clarifications = clarificationsForIntent(intent, entities)
	}
	return plan
}

// validatePlan enforces allowed intents/actions and required entities. It
// returns a normalized plan and a boolean indicating whether the plan passed
// validation. On failure, it returns a safe unknown/none plan.
func validatePlan(raw string, plan *AICommandPlan) (AICommandPlan, bool, []string) {
	if plan == nil {
		return AICommandPlan{
			Intent:     "unknown",
			Action:     "none",
			Entities:   map[string]interface{}{},
			Ambiguous:  true,
			Message:    "No plan returned from parser.",
			Confidence: 0,
		}, false, nil
	}
	if plan.Entities == nil {
		plan.Entities = map[string]interface{}{}
	}

	intent := normalizeIntent(strings.TrimSpace(strings.ToLower(plan.Intent)))
	action := normalizeAction(strings.TrimSpace(strings.ToLower(plan.Action)))
	if intent == "" {
		intent = "unknown"
	}
	if action == "" && intent == "unknown" {
		action = "none"
	}

	// Guard override: if the LLM returns unknown/none but the text strongly
	// indicates a known intent, override to that action and proceed with repair.
	if (intent == "unknown" && action == "none") || action == "none" {
		if gi, ga := guardClassifyIntent(raw); ga != "" {
			intent = gi
			action = ga
		}
	}

	// Strong verb overrides: reschedule/cancel should win if explicitly present.
	lowerRaw0 := strings.ToLower(raw)
	if strings.Contains(lowerRaw0, "reschedule") || strings.Contains(lowerRaw0, "move job") || strings.Contains(lowerRaw0, "postpone") {
		// Avoid overriding explicit proposal actions.
		if action != "approve_proposal" && action != "reject_proposal" && action != "apply_proposal" && action != "create_job" {
			intent = "reschedule"
			action = "reschedule"
		}
	}
	if strings.Contains(lowerRaw0, "cancel") || strings.Contains(lowerRaw0, "remove job") || strings.Contains(lowerRaw0, "delete job") {
		if action != "approve_proposal" && action != "reject_proposal" && action != "apply_proposal" && action != "create_job" {
			intent = "cancel"
			action = "cancel"
		}
	}

	// Apply/Approve/Reject overrides: explicit verbs should win even if the LLM mislabels.
	getEntityString := func(entities map[string]interface{}, key string) string {
		if entities == nil {
			return ""
		}
		if v, ok := entities[key]; ok {
			switch vv := v.(type) {
			case string:
				return strings.TrimSpace(vv)
			case float64:
				if vv == float64(int(vv)) {
					return strconv.Itoa(int(vv))
				}
				return strings.TrimSpace(strconv.FormatFloat(vv, 'f', -1, 64))
			}
		}
		return ""
	}
	proposalID := getEntityString(plan.Entities, "proposal_id")
	jobID := getEntityString(plan.Entities, "job_id")
	hasApprove := regexp.MustCompile(`\bapprove\b`).MatchString(lowerRaw0)
	hasReject := regexp.MustCompile(`\b(reject|decline)\b`).MatchString(lowerRaw0)
	hasApply := regexp.MustCompile(`\b(apply|accept)\b`).MatchString(lowerRaw0)
	if hasApply && (proposalID != "" || jobID != "") {
		intent = "apply_proposal"
		action = "apply_proposal"
	} else if hasReject && proposalID != "" {
		intent = "reject_proposal"
		action = "reject_proposal"
	} else if hasApprove && proposalID != "" {
		intent = "approve_proposal"
		action = "approve_proposal"
	}

	// Whitelist allowed actions.
	allowed := map[string]struct{}{
		"propose_schedule":   {},
		"approve_proposal":   {},
		"reject_proposal":    {},
		"apply_proposal":     {},
		"explain_job":        {},
		"delay_risk":         {},
		"machine_ranking":    {},
		"create_job":         {},
		"reschedule":         {},
		"cancel":             {},
		"query_status":       {},
		"consume_material":   {},
		"receive_material":   {},
		"record_downtime":    {},
		"maintenance_alerts": {},
		"list_products":      {},
		"high_risk_jobs":     {},
		"dashboard_kpis":     {},
		"split_step":         {},
		"generate_report":    {},
		"schedule_all_jobs":  {},
		"none":               {},
	}
	if _, ok := allowed[action]; !ok {
		intent = "unknown"
		action = "none"
	}

	entities := plan.Entities
	getString := func(key string) string {
		if v, ok := entities[key]; ok {
			switch vv := v.(type) {
			case string:
				return strings.TrimSpace(vv)
			case float64:
				// JSON numbers decode as float64 in map[string]interface{}.
				if vv == float64(int(vv)) {
					return strconv.Itoa(int(vv))
				}
				return strings.TrimSpace(strconv.FormatFloat(vv, 'f', -1, 64))
			}
		}
		return ""
	}

	requireID := func(key string, pattern *regexp.Regexp) bool {
		id := getString(key)
		if id == "" || (pattern != nil && !pattern.MatchString(id)) {
			return false
		}
		return true
	}

	// Patterns for IDs (best-effort, not strict DB validation).
	jobIDPattern := regexp.MustCompile(`^[A-Z0-9\-]+$`)
	proposalIDPattern := regexp.MustCompile(`^[A-Z0-9\-]+$`)
	stepIDPattern := regexp.MustCompile(`^[A-Z0-9\-]+$`)

	clarifications := plan.Clarifications
	missing := make([]string, 0, 3)

	// Deterministic repair from raw input for critical IDs and common fields.
	repairEntitiesFromRaw(raw, action, entities)
	normalizeEntityTypes(entities)

	// Priority override based on explicit verbs in raw input.
	lowerRaw := strings.ToLower(raw)
	if (strings.Contains(lowerRaw, "reschedule") || strings.Contains(lowerRaw, "move job") || strings.Contains(lowerRaw, "postpone")) && action == "delay_risk" {
		intent = "reschedule"
		action = "reschedule"
	}
	if (strings.Contains(lowerRaw, "cancel") || strings.Contains(lowerRaw, "remove job") || strings.Contains(lowerRaw, "delete job")) && action == "delay_risk" {
		intent = "cancel"
		action = "cancel"
	}

	switch action {
	case "propose_schedule", "explain_job", "delay_risk":
		if !requireID("job_id", jobIDPattern) {
			missing = append(missing, "entities.job_id")
			clarifications = append(clarifications, "Specify the target job ID, for example: `job JOB-1234`.")
		}
	case "apply_proposal":
		if !requireID("proposal_id", proposalIDPattern) && !requireID("job_id", jobIDPattern) {
			missing = append(missing, "entities.proposal_id_or_job_id")
			clarifications = append(clarifications, "Specify either a persisted proposal ID like `proposal AIPROP-1234` or a target job ID like `job JOB-1234`.")
		}
	case "approve_proposal", "reject_proposal":
		if !requireID("proposal_id", proposalIDPattern) {
			missing = append(missing, "entities.proposal_id")
			clarifications = append(clarifications, "Specify the persisted proposal ID, for example: `proposal AIPROP-1234`.")
		}
	case "machine_ranking":
		if !requireID("job_step_id", stepIDPattern) {
			missing = append(missing, "entities.job_step_id")
			clarifications = append(clarifications, "Specify the job step ID, for example: `job step JS-1234`.")
		}
	case "create_job":
		q := getString("quantity")
		product := getString("product")
		if q == "" || product == "" {
			if q == "" {
				missing = append(missing, "entities.quantity")
			}
			if product == "" {
				missing = append(missing, "entities.product")
			}
			clarifications = append(clarifications, "Include both a quantity (e.g. `200 units`) and a product name for job creation.")
		}
	case "reschedule":
		if !requireID("job_id", jobIDPattern) {
			missing = append(missing, "entities.job_id")
			clarifications = append(clarifications, "Specify which job to reschedule, for example: `reschedule job JOB-1234`.")
		}
	case "cancel":
		if !requireID("job_id", jobIDPattern) {
			missing = append(missing, "entities.job_id")
			clarifications = append(clarifications, "Specify which job to cancel, for example: `cancel job JOB-1234`.")
		}
	case "query_status":
		// resource is optional; we default to general.
	case "consume_material":
		if getString("material") == "" || getString("quantity") == "" {
			if getString("material") == "" {
				missing = append(missing, "entities.material")
			}
			if getString("quantity") == "" {
				missing = append(missing, "entities.quantity")
			}
			clarifications = append(clarifications, "Specify both a quantity and a material, for example: `consume 5kg of resin`.")
		}
	case "generate_report":
		// report_type guidance is optional.
	case "schedule_all_jobs":
		// no required entities.
	case "receive_material":
		hasMat := getString("material") != "" || getString("material_id") != ""
		if !hasMat || getString("quantity") == "" {
			if !hasMat {
				missing = append(missing, "entities.material_id")
			}
			if getString("quantity") == "" {
				missing = append(missing, "entities.quantity")
			}
			clarifications = append(clarifications, "Specify material (e.g. MAT-001) and quantity, for example: `receive 100 kg of MAT-001`.")
		}
	case "record_downtime":
		if !requireID("machine_id", regexp.MustCompile(`^[A-Z0-9\-]+$`)) {
			missing = append(missing, "entities.machine_id")
			clarifications = append(clarifications, "Specify the machine ID, for example: `record downtime for M-CNC-01`.")
		}
	case "split_step":
		if !requireID("job_step_id", stepIDPattern) {
			missing = append(missing, "entities.job_step_id")
			clarifications = append(clarifications, "Specify the job step ID, for example: `split step JS-4001`.")
		}
	case "maintenance_alerts", "list_products", "high_risk_jobs", "dashboard_kpis":
		// no required entities.
	}

	ambiguous := plan.Ambiguous
	if len(clarifications) > 0 && action != "none" {
		ambiguous = true
	}

	final := AICommandPlan{
		Intent:         intent,
		Action:         action,
		Entities:       entities,
		Confidence:     plan.Confidence,
		Ambiguous:      ambiguous,
		Clarifications: clarifications,
		Message:        plan.Message,
	}

	// If we ended up with unknown/none and no entities, mark as ambiguous.
	if final.Intent == "unknown" && final.Action == "none" {
		if final.Clarifications == nil {
			final.Clarifications = []string{"Could not confidently parse the request. Try: create job, reschedule, cancel, status, consume, report."}
		}
		final.Ambiguous = true
		if final.Message == "" {
			final.Message = "Could not confidently parse the request. Rephrase with a concrete job, proposal, or job step reference."
		}
		return final, false, missing
	}
	// If required fields are missing we treat the plan as invalid for execution,
	// but still return the normalized/ambiguous plan.
	if len(missing) > 0 {
		return final, false, missing
	}
	return final, true, nil
}

func normalizeEntityTypes(entities map[string]interface{}) {
	if entities == nil {
		return
	}
	toString := func(v interface{}) (string, bool) {
		switch vv := v.(type) {
		case string:
			return strings.TrimSpace(vv), true
		case float64:
			if vv == float64(int(vv)) {
				return strconv.Itoa(int(vv)), true
			}
			return strconv.FormatFloat(vv, 'f', -1, 64), true
		case int:
			return strconv.Itoa(vv), true
		default:
			return "", false
		}
	}
	keys := []string{"job_id", "proposal_id", "job_step_id", "quantity", "product", "material", "material_id", "machine_id", "deadline", "resource", "report_type", "cause"}
	for _, k := range keys {
		if v, ok := entities[k]; ok {
			if s, ok2 := toString(v); ok2 && s != "" {
				entities[k] = s
			}
		}
	}
}

func normalizeAction(action string) string {
	a := strings.TrimSpace(strings.ToLower(action))
	switch a {
	case "schedule_all", "schedule_all_job", "schedule_alljobs", "batch_schedule":
		return "schedule_all_jobs"
	case "delayrisk", "delay-risk", "risk_delay":
		return "delay_risk"
	case "propose", "proposal", "propose_schedule_job":
		return "propose_schedule"
	case "apply", "applyschedule":
		return "apply_proposal"
	case "approve", "approve_proposal", "ok_proposal":
		return "approve_proposal"
	case "reject", "decline", "reject_proposal":
		return "reject_proposal"
	case "explain":
		return "explain_job"
	case "resched", "reschedule_job", "move_job", "push_job":
		return "reschedule"
	case "cancel_job", "remove_job", "delete_job":
		return "cancel"
	default:
		return a
	}
}

func normalizeIntent(intent string) string {
	// In this system intent == action conceptually; normalize similarly.
	return normalizeAction(intent)
}

func repairEntitiesFromRaw(raw, action string, entities map[string]interface{}) {
	if entities == nil {
		return
	}
	// Always attempt to repair canonical IDs.
	if _, ok := entities["job_id"]; !ok {
		if id := extractJobID(raw); id != "" {
			entities["job_id"] = id
		}
	}
	if _, ok := entities["proposal_id"]; !ok {
		if id := extractProposalID(raw); id != "" {
			entities["proposal_id"] = id
		}
	}
	if _, ok := entities["job_step_id"]; !ok {
		if id := extractJobStepID(raw); id != "" {
			entities["job_step_id"] = id
		}
	}

	// Create-job repair (best-effort): quantity + product phrase.
	// Run when action is create_job OR the raw text clearly indicates create job.
	lowerRaw := strings.ToLower(raw)
	if action == "create_job" || ((strings.Contains(lowerRaw, "create") || strings.Contains(lowerRaw, "add") || strings.Contains(lowerRaw, "new order")) && (strings.Contains(lowerRaw, "job") || strings.Contains(lowerRaw, "order") || strings.Contains(lowerRaw, "units"))) {
		if _, ok := entities["quantity"]; !ok {
			if m := regexp.MustCompile(`(?i)(\d+)\s*units?`).FindStringSubmatch(raw); len(m) > 1 {
				entities["quantity"] = m[1]
			} else if m := regexp.MustCompile(`(?i)(\d+)\s*x\b`).FindStringSubmatch(raw); len(m) > 1 {
				entities["quantity"] = m[1]
			}
		}
		if _, ok := entities["product"]; !ok {
			// Prefer "units of <product>" and similar constructs; stop at " (", ",", etc.
			term := `(?:\s*\(|\s+on\s|\s+deadline|,\s*|$)`
			if m := regexp.MustCompile(`(?i)units?\s+of\s+(.+?)` + term).FindStringSubmatch(raw); len(m) > 1 {
				entities["product"] = strings.TrimSpace(m[1])
			} else if m := regexp.MustCompile(`(?i)\bof\s+(.+?)` + term).FindStringSubmatch(raw); len(m) > 1 {
				entities["product"] = strings.TrimSpace(m[1])
			} else if m := regexp.MustCompile(`(?i)(?:\d+\s*x\s+)(.+?)(?:\s*\(|,|$)`).FindStringSubmatch(raw); len(m) > 1 {
				entities["product"] = strings.TrimSpace(m[1])
			} else if m := regexp.MustCompile(`(?i)(?:\d+)\s+units\s+(.+?)(?:\s*\(|,|$|\s+as\s|\s+on\s)`).FindStringSubmatch(raw); len(m) > 1 {
				entities["product"] = strings.TrimSpace(m[1])
			} else if id := extractProductID(raw); id != "" {
				entities["product"] = id
				entities["product_id"] = id
			}
		} else if id := extractProductID(raw); id != "" {
			entities["product_id"] = id
		}
	}

	// Consume-material repair.
	if action == "consume_material" {
		if _, ok := entities["quantity"]; !ok {
			if m := regexp.MustCompile(`(?i)\b(\d+(?:\.\d+)?)\b`).FindStringSubmatch(raw); len(m) > 1 {
				entities["quantity"] = m[1]
			}
		}
		if _, ok := entities["material"]; !ok {
			if m := regexp.MustCompile(`(?i)\bof\s+([a-z0-9][a-z0-9\s\-]+?)(?:\s+for\s+job|\s+slot|$)`).FindStringSubmatch(raw); len(m) > 1 {
				entities["material"] = strings.TrimSpace(m[1])
			}
		}
		if id := extractMaterialID(raw); id != "" {
			entities["material_id"] = id
		}
	}

	// Receive-material repair.
	if action == "receive_material" {
		if id := extractMaterialID(raw); id != "" {
			entities["material_id"] = id
			if _, ok := entities["material"]; !ok {
				entities["material"] = id
			}
		}
		if _, ok := entities["quantity"]; !ok {
			if m := regexp.MustCompile(`(?i)\b(\d+(?:\.\d+)?)\s*(?:kg|g|units?|L)?`).FindStringSubmatch(raw); len(m) > 1 {
				entities["quantity"] = m[1]
			}
		}
	}

	// Record-downtime repair.
	if action == "record_downtime" {
		if id := extractMachineID(raw); id != "" {
			entities["machine_id"] = id
		}
	}
}

// fallbackParse is a minimal deterministic parser used only when the LLM is
// unavailable or returns invalid output. It intentionally covers a small set
// of common commands to keep the API usable in degraded mode and to avoid
// brittle regex chains.
func fallbackParse(raw string) (AICommandPlan, bool) {
	q := strings.ToLower(strings.TrimSpace(raw))
	entities := map[string]interface{}{}
	lateWord := regexp.MustCompile(`\blate\b`).MatchString(q)

	// Helper: lift IDs from the raw string (preserve case where possible).
	if jobID := extractJobID(raw); jobID != "" {
		entities["job_id"] = jobID
	}
	if proposalID := extractProposalID(raw); proposalID != "" {
		entities["proposal_id"] = proposalID
	}
	if jobStepID := extractJobStepID(raw); jobStepID != "" {
		entities["job_step_id"] = jobStepID
	}

	mk := func(intent, action, message string) AICommandPlan {
		p := AICommandPlan{
			Intent:   intent,
			Action:   action,
			Entities: entities,
			Message:  message,
		}
		p.Confidence = confidenceForIntent(intent, entities)
		if p.Confidence > 0 && p.Confidence < 0.65 {
			p.Ambiguous = true
			p.Clarifications = clarificationsForIntent(intent, entities)
		}
		return p
	}

	// Propose schedule.
	proposeVerb := strings.Contains(q, "suggest") || strings.Contains(q, "propose") || strings.Contains(q, "recommend") || strings.Contains(q, "recomendation") ||
		strings.Contains(q, "gimme") || (strings.Contains(q, "need") && strings.Contains(q, "recomendation"))
	proposeCtx := strings.Contains(q, "schedule") || strings.Contains(q, "plan") || (strings.Contains(q, "for ") && extractJobID(raw) != "") || strings.Contains(q, "recomendation")
	if proposeVerb && proposeCtx && (strings.Contains(q, "job") || extractJobID(raw) != "") {
		return mk("propose_schedule", "propose_schedule", "Parsed: propose schedule."), true
	}
	// Explain job. "why is X delayed" = explain, not delay_risk.
	if (strings.Contains(q, "explain") || strings.Contains(q, "what is going on") || strings.Contains(q, "what's going on") || strings.Contains(q, "what's happening") || strings.Contains(q, "what is happening") || (strings.Contains(q, "why") && strings.Contains(q, "job"))) &&
		(strings.Contains(q, "job") || extractJobID(raw) != "") {
		return mk("explain_job", "explain_job", "Parsed: explain job."), true
	}
	// Delay risk.
	if (strings.Contains(q, "delay") || strings.Contains(q, "risk") || lateWord) && (strings.Contains(q, "job") || extractJobID(raw) != "") {
		return mk("delay_risk", "delay_risk", "Parsed: delay risk."), true
	}
	// Machine ranking.
	if (strings.Contains(q, "rank") || strings.Contains(q, "best")) && strings.Contains(q, "machine") {
		return mk("machine_ranking", "machine_ranking", "Parsed: machine ranking."), true
	}
	// Approve/Reject/Apply proposal with or without the word "proposal".
	hasApprove := regexp.MustCompile(`\bapprove\b`).MatchString(q)
	hasReject := regexp.MustCompile(`\b(reject|decline)\b`).MatchString(q)
	hasApply := regexp.MustCompile(`\b(apply|accept)\b`).MatchString(q)
	proposalID := ""
	if v, ok := entities["proposal_id"].(string); ok {
		proposalID = v
	}
	jobID := ""
	if v, ok := entities["job_id"].(string); ok {
		jobID = v
	}

	if hasReject && proposalID != "" {
		return mk("reject_proposal", "reject_proposal", "Parsed: reject proposal."), true
	}
	if hasApprove && proposalID != "" {
		return mk("approve_proposal", "approve_proposal", "Parsed: approve proposal."), true
	}
	if hasApply && (proposalID != "" || jobID != "") {
		return mk("apply_proposal", "apply_proposal", "Parsed: apply proposal."), true
	}
	// Create job.
	isCreatePhrase := strings.Contains(q, "create") || strings.Contains(q, "add") || strings.Contains(q, "new job") || strings.Contains(q, "job request") || strings.Contains(q, "new order")
	hasCreateContext := strings.Contains(q, "job") || strings.Contains(q, "order") || strings.Contains(q, "job:") || strings.Contains(q, "job request") || strings.Contains(q, "units")
	if isCreatePhrase && hasCreateContext {
		// Extract quantity/product best-effort.
		if _, ok := entities["quantity"]; !ok {
			if m := regexp.MustCompile(`(?i)(\d+)\s*units?`).FindStringSubmatch(raw); len(m) > 1 {
				entities["quantity"] = m[1]
			} else if m := regexp.MustCompile(`(?i)(\d+(?:\.\d+)?)\s*x\b`).FindStringSubmatch(raw); len(m) > 1 {
				entities["quantity"] = m[1]
			}
		}
		if _, ok := entities["product"]; !ok {
			term := `(?:\s*\(|\s+on\s|\s+deadline|,\s*|$|\s+(?:asap|now|rush|immediately|today|tonight|tomorrow)|\s+next\s+\w+|\s+as\s+a\s+new\s+job|\s+as\s+a\s+job| \bby\s+\w+\b)`
			if m := regexp.MustCompile(`(?i)units?\s+of\s+(.+?)` + term).FindStringSubmatch(raw); len(m) > 1 {
				entities["product"] = strings.TrimSpace(m[1])
			} else if m := regexp.MustCompile(`(?i)\bof\s+(.+?)` + term).FindStringSubmatch(raw); len(m) > 1 {
				entities["product"] = strings.TrimSpace(m[1])
			} else if m := regexp.MustCompile(`(?i)\b\d+(?:\.\d+)?\s*x\s+(.+?)(?:\s+as\s+job|,|$)`).FindStringSubmatch(raw); len(m) > 1 {
				entities["product"] = strings.TrimSpace(m[1])
			} else if m := regexp.MustCompile(`(?i)\bjob\s*(?:for|:)\s+(.+?)(?:\s*\(|,|$)`).FindStringSubmatch(raw); len(m) > 1 {
				entities["product"] = strings.TrimSpace(m[1])
			} else if m := regexp.MustCompile(`(?i)(?:\d+)\s+units\s+(.+?)(?:\s*\(|,|$| as | on )`).FindStringSubmatch(raw); len(m) > 1 {
				entities["product"] = strings.TrimSpace(m[1])
			}
		}
		return mk("create_job", "create_job", "Parsed: create job."), true
	}

	// Consume material.
	if (strings.Contains(q, "consume") || strings.Contains(q, "use")) && strings.Contains(q, " of ") {
		re := regexp.MustCompile(`(?i)\b(\d+(?:\.\d+)?)\s*(?:kg|g|units?|lbs|lb)?\s+of\s+(.+?)(?:\s+for\s+job|\s+for\s+slot|\s+for\s+\w+|,|$)`)
		if m := re.FindStringSubmatch(raw); len(m) > 2 {
			entities["quantity"] = strings.TrimSpace(m[1])
			entities["material"] = strings.TrimSpace(m[2])
			if entities["material"] != "" {
				return mk("consume_material", "consume_material", "Parsed: consume material."), true
			}
		}
	}

	// Generate report.
	if strings.Contains(q, "report") {
		if strings.Contains(q, "utilization report") {
			entities["report_type"] = "utilization"
		} else if strings.Contains(q, "daily report") {
			entities["report_type"] = "daily"
		} else if m := regexp.MustCompile(`(?i)report\s+on\s+(.+?)(?:[.!?]|$)`).FindStringSubmatch(raw); len(m) > 1 {
			rt := strings.TrimSpace(m[1])
			rt = strings.TrimRight(rt, ".!?")
			entities["report_type"] = rt
		} else if m := regexp.MustCompile(`(?i)(\w+)\s+report\b`).FindStringSubmatch(raw); len(m) > 1 && !strings.EqualFold(m[1], "generate") && !strings.EqualFold(m[1], "create") {
			entities["report_type"] = strings.TrimSpace(m[1])
		}
		return mk("generate_report", "generate_report", "Parsed: generate report."), true
	}

	// Cancel job.
	if (strings.Contains(q, "cancel") || strings.Contains(q, "remove") || strings.Contains(q, "delete")) && strings.Contains(q, "job") {
		return mk("cancel", "cancel", "Parsed: cancel job."), true
	}
	// Reschedule job.
	if (strings.Contains(q, "reschedule") || strings.Contains(q, "resched") || strings.Contains(q, "move") || strings.Contains(q, "postpone") || strings.Contains(q, "change") || strings.Contains(q, "push")) &&
		(strings.Contains(q, "job") || extractJobID(raw) != "") {
		return mk("reschedule", "reschedule", "Parsed: reschedule job."), true
	}
	// Query status.
	if strings.Contains(q, "status") || strings.Contains(q, "show") || strings.Contains(q, "list") {
		if strings.Contains(q, "job") {
			entities["resource"] = "jobs"
		} else if strings.Contains(q, "machine") {
			entities["resource"] = "machines"
		} else if strings.Contains(q, "inventory") || strings.Contains(q, "stock") {
			entities["resource"] = "inventory"
		} else {
			entities["resource"] = "general"
		}
		return mk("query_status", "query_status", "Parsed: query status."), true
	}
	// Schedule all jobs.
	if strings.Contains(q, "schedule all") || strings.Contains(q, "batch schedule") || strings.Contains(q, "auto schedule all") {
		return mk("schedule_all_jobs", "schedule_all_jobs", "Parsed: schedule all jobs."), true
	}

	// Receive material.
	if (strings.Contains(q, "receive") || strings.Contains(q, "received") || strings.Contains(q, "stock")) && strings.Contains(q, " of ") {
		re := regexp.MustCompile(`(?i)\b(\d+(?:\.\d+)?)\s*(?:kg|g|units?|L|Liters?)?\s+of\s+(.+?)(?:\s+into\s+inventory|,|$)`)
		if m := re.FindStringSubmatch(raw); len(m) > 2 {
			entities["quantity"] = strings.TrimSpace(m[1])
			entities["material"] = strings.TrimSpace(m[2])
			if id := extractMaterialID(raw); id != "" {
				entities["material_id"] = id
			}
			return mk("receive_material", "receive_material", "Parsed: receive material."), true
		}
	}

	// Record downtime.
	if (strings.Contains(q, "downtime") || strings.Contains(q, "machine down") || strings.Contains(q, "out of service")) && (strings.Contains(q, "machine") || extractMachineID(raw) != "") {
		if id := extractMachineID(raw); id != "" {
			entities["machine_id"] = id
		}
		return mk("record_downtime", "record_downtime", "Parsed: record downtime."), true
	}

	// Maintenance alerts.
	if strings.Contains(q, "maintenance") && (strings.Contains(q, "alert") || strings.Contains(q, "due") || strings.Contains(q, "overdue")) {
		return mk("maintenance_alerts", "maintenance_alerts", "Parsed: maintenance alerts."), true
	}

	// List products.
	if (strings.Contains(q, "list") || strings.Contains(q, "show") || strings.Contains(q, "all")) && strings.Contains(q, "product") {
		return mk("list_products", "list_products", "Parsed: list products."), true
	}

	// High risk jobs.
	if (strings.Contains(q, "high risk") || strings.Contains(q, "at risk") || strings.Contains(q, "risky jobs")) {
		return mk("high_risk_jobs", "high_risk_jobs", "Parsed: high risk jobs."), true
	}

	// Dashboard KPIs.
	if strings.Contains(q, "dashboard") || strings.Contains(q, "kpi") || strings.Contains(q, "key metric") {
		return mk("dashboard_kpis", "dashboard_kpis", "Parsed: dashboard KPIs."), true
	}

	// Split step.
	if (strings.Contains(q, "split") || strings.Contains(q, "divide")) && (strings.Contains(q, "step") || extractJobStepID(raw) != "") {
		if id := extractJobStepID(raw); id != "" {
			entities["job_step_id"] = id
		}
		return mk("split_step", "split_step", "Parsed: split step suggestion."), true
	}

	return AICommandPlan{}, false
}

// Legacy regex-based parse helpers have been removed in favor of the LLM
// interface and Go-level validation above.

func confidenceForIntent(intent string, entities map[string]interface{}) float64 {
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
	case "schedule_all_jobs":
		confidence += 0.4
	default:
		confidence += 0.1 * float64(len(entities))
	}
	if confidence > 0.99 {
		confidence = 0.99
	}
	return confidence
}

func clarificationsForIntent(intent string, entities map[string]interface{}) []string {
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

func extractJobID(q string) string {
	// Accept "job JOB-123", "job#JOB-123", "job:JOB-123", and standalone "JOB-123".
	matches := regexp.MustCompile(`(?i)(?:\bjob\b\s*[:#]?\s*)?((?:JOB|J)\-[A-Z0-9\-]+)\b`).FindAllStringSubmatch(q, -1)
	if len(matches) > 0 {
		return matches[len(matches)-1][1]
	}
	return ""
}

func extractJobStepID(q string) string {
	// Accept "job step JS-123", "job-step JS-123", "job step:JS-123", and standalone "JS-123".
	matches := regexp.MustCompile(`(?i)(?:\bjob[\s\-]*step\b\s*[:#]?\s*)?((?:JS|JSTEP)\-[A-Z0-9\-]+)\b`).FindAllStringSubmatch(q, -1)
	if len(matches) > 0 {
		return matches[len(matches)-1][1]
	}
	return ""
}

func extractProposalID(q string) string {
	// Accept "proposal AIPROP-123", "proposal: AIPROP-123", and standalone "AIPROP-123".
	matches := regexp.MustCompile(`(?i)(?:\bproposal\b\s*[:#]?\s*)?((?:AIPROP|PROP)\-[A-Z0-9\-]+)\b`).FindAllStringSubmatch(q, -1)
	if len(matches) > 0 {
		return matches[len(matches)-1][1]
	}
	return ""
}

func extractMachineID(q string) string {
	// Accept "machine M-CNC-01", "machine: M-CNC-01", and standalone "M-CNC-01".
	matches := regexp.MustCompile(`(?i)(?:\bmachine\b\s*[:#]?\s*)?((?:M)\-[A-Z0-9\-]+)\b`).FindAllStringSubmatch(q, -1)
	if len(matches) > 0 {
		return matches[len(matches)-1][1]
	}
	return ""
}

func extractMaterialID(q string) string {
	// Accept "material MAT-001", "MAT-001", etc.
	matches := regexp.MustCompile(`(?i)(?:\bmaterial\b\s*[:#]?\s*)?((?:MAT)\-[A-Z0-9\-]+)\b`).FindAllStringSubmatch(q, -1)
	if len(matches) > 0 {
		return matches[len(matches)-1][1]
	}
	return ""
}

func extractProductID(q string) string {
	// Accept "product P-001", "P-001", etc.
	matches := regexp.MustCompile(`(?i)(?:\bproduct\b\s*[:#]?\s*)?((?:P)\-[A-Z0-9\-]+)\b`).FindAllStringSubmatch(q, -1)
	if len(matches) > 0 {
		return matches[len(matches)-1][1]
	}
	return ""
}

func guardClassifyIntent(raw string) (intent, action string) {
	q := strings.ToLower(raw)
	// Explain before delay_risk: "why is X delayed" = explain
	if strings.Contains(q, "why") && (strings.Contains(q, "delayed") || strings.Contains(q, "late")) && (strings.Contains(q, "job") || extractJobID(raw) != "") {
		return "explain_job", "explain_job"
	}
	// Reschedule before delay_risk: "resched", "push", "later today" = reschedule, not delay.
	if (strings.Contains(q, "reschedule") || strings.Contains(q, "resched") || strings.Contains(q, "move ") || strings.Contains(q, "postpone") || strings.Contains(q, "push ") || strings.Contains(q, "later today")) &&
		(strings.Contains(q, "job") || extractJobID(raw) != "") {
		return "reschedule", "reschedule"
	}
	// Explain job: "what's going on", "what's happening", "why...delayed", "explain"
	if (strings.Contains(q, "explain") || strings.Contains(q, "going on") || strings.Contains(q, "happening") || (strings.Contains(q, "why") && strings.Contains(q, "delayed"))) && (strings.Contains(q, "job") || extractJobID(raw) != "") {
		return "explain_job", "explain_job"
	}
	// Propose for job
	if (strings.Contains(q, "propose") || strings.Contains(q, "suggest") || strings.Contains(q, "gimme") || strings.Contains(q, "recomendation") ||
		(strings.Contains(q, "need") && strings.Contains(q, "recomendation"))) &&
		(strings.Contains(q, "schedule") || strings.Contains(q, "plan") || strings.Contains(q, "job")) && extractJobID(raw) != "" {
		return "propose_schedule", "propose_schedule"
	}
	// Create job: "job request", "create" + "units"
	if strings.Contains(q, "job request") || (strings.Contains(q, "create") && strings.Contains(q, "units")) {
		return "create_job", "create_job"
	}
	// Delay risk (word-boundary "late" to avoid "later")
	lateWord := regexp.MustCompile(`\blate\b`).MatchString(q)
	if (strings.Contains(q, "delay") || strings.Contains(q, "risk") || lateWord) && (strings.Contains(q, "job") || extractJobID(raw) != "") {
		return "delay_risk", "delay_risk"
	}
	// Machine ranking
	if strings.Contains(q, "rank") && strings.Contains(q, "machine") {
		return "machine_ranking", "machine_ranking"
	}
	if strings.Contains(q, "best") && strings.Contains(q, "machine") {
		return "machine_ranking", "machine_ranking"
	}
	// Schedule all
	if strings.Contains(q, "schedule all") || strings.Contains(q, "batch schedule") || strings.Contains(q, "auto schedule all") {
		return "schedule_all_jobs", "schedule_all_jobs"
	}
	// Receive material
	if (strings.Contains(q, "receive") || strings.Contains(q, "received") || strings.Contains(q, "stock")) && (strings.Contains(q, "material") || strings.Contains(q, " of ")) {
		return "receive_material", "receive_material"
	}
	// Record downtime
	if (strings.Contains(q, "downtime") || strings.Contains(q, "machine down") || strings.Contains(q, "out of service")) && (strings.Contains(q, "machine") || extractMachineID(raw) != "") {
		return "record_downtime", "record_downtime"
	}
	// Maintenance alerts
	if strings.Contains(q, "maintenance") && (strings.Contains(q, "alert") || strings.Contains(q, "due") || strings.Contains(q, "overdue")) {
		return "maintenance_alerts", "maintenance_alerts"
	}
	// List products
	if (strings.Contains(q, "list") || strings.Contains(q, "show") || strings.Contains(q, "all")) && strings.Contains(q, "product") {
		return "list_products", "list_products"
	}
	// High risk jobs
	if (strings.Contains(q, "high risk") || strings.Contains(q, "at risk") || strings.Contains(q, "risky jobs")) && strings.Contains(q, "job") {
		return "high_risk_jobs", "high_risk_jobs"
	}
	// Dashboard KPIs
	if strings.Contains(q, "dashboard") || strings.Contains(q, "kpi") || strings.Contains(q, "key metric") {
		return "dashboard_kpis", "dashboard_kpis"
	}
	// Split step
	if (strings.Contains(q, "split") || strings.Contains(q, "divide")) && (strings.Contains(q, "step") || extractJobStepID(raw) != "") {
		return "split_step", "split_step"
	}
	return "", ""
}

func restoreEntityIDs(raw string, entities map[string]interface{}) {
	if entities == nil {
		return
	}
	if _, ok := entities["job_id"]; ok {
		if jobID := extractJobID(raw); jobID != "" {
			entities["job_id"] = jobID
		}
	}
	if _, ok := entities["job_step_id"]; ok {
		if jobStepID := extractJobStepID(raw); jobStepID != "" {
			entities["job_step_id"] = jobStepID
		}
	}
}

func restoreProposalID(raw string, entities map[string]interface{}) {
	if entities == nil {
		return
	}
	if _, ok := entities["proposal_id"]; ok {
		if proposalID := extractProposalID(raw); proposalID != "" {
			entities["proposal_id"] = proposalID
		}
	}
}
