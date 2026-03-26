package handler

import (
	"context"
	"encoding/json"
	"emas/internal/handler/dto"
	"emas/internal/middleware"
	"emas/internal/service"
	"emas/pkg/featureflags"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type AISchedulingHandler struct {
	service *service.AIPredictiveService
}

func NewAISchedulingHandler(service *service.AIPredictiveService) *AISchedulingHandler {
	return &AISchedulingHandler{service: service}
}

func (h *AISchedulingHandler) Assist(c *gin.Context) {
	jobID := c.Param("id")
	data, err := h.service.BuildAssist(jobID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) Proposal(c *gin.Context) {
	jobID := c.Param("id")
	data, err := h.service.BuildProposal(jobID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) GenerateProposal(c *gin.Context) {
	jobID := c.Param("id")
	data, err := h.service.GenerateProposal(jobID, actorFromContext(c))
	if err != nil {
		c.JSON(statusForSchedulingErr(err), dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) GenerateBatchProposals(c *gin.Context) {
	var req dto.BatchProposalsRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid request body"})
		return
	}
	jobIDs := req.JobIDs
	if req.Scope == "all_unscheduled" && len(req.JobIDs) == 0 {
		jobIDs = nil
	} else if len(req.JobIDs) == 0 && req.Scope != "all_unscheduled" {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "provide job_ids or scope: \"all_unscheduled\""})
		return
	}
	orderBy := strings.TrimSpace(strings.ToLower(req.OrderBy))
	if orderBy == "" {
		orderBy = featureflags.BatchOrderBy()
	}
	if orderBy != "edd" && orderBy != "epo" && orderBy != "fifo" && orderBy != "readiness" {
		orderBy = "epo"
	}
	timeoutMs := featureflags.BatchTimeoutMs()
	if timeoutMs <= 0 {
		timeoutMs = 60000
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), time.Duration(timeoutMs)*time.Millisecond)
	defer cancel()
	proposals, summary, err := h.service.ScheduleJobSet(ctx, jobIDs, actorFromContext(c), orderBy, nil)
	if err != nil {
		if (errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled)) && len(proposals) > 0 {
			c.JSON(http.StatusOK, dto.Response{
				Success: true,
				Data: map[string]interface{}{
					"proposals": proposals,
					"summary":   summary,
					"partial":   true,
					"message":   "Request timed out or cancelled; partial results returned. Consider increasing client timeout for full results.",
				},
			})
			return
		}
		if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
			c.JSON(http.StatusRequestTimeout, dto.Response{
				Success: false,
				Error:   "Request timed out. For batch-proposals, use a client timeout of at least 30 seconds.",
			})
			return
		}
		c.JSON(statusForSchedulingErr(err), dto.Response{Success: false, Error: err.Error()})
		return
	}
	data := map[string]interface{}{
		"proposals": proposals,
		"summary":   summary,
	}
	if summary != nil && summary.LateCount > 0 && summary.Generated > 0 {
		data["message"] = buildLateJobsMessage(summary.LateCount, summary.Generated)
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) RescheduleAll(c *gin.Context) {
	var req dto.RescheduleAllRequest
	_ = c.ShouldBindJSON(&req)
	orderBy := strings.TrimSpace(strings.ToLower(req.OrderBy))
	if orderBy == "" {
		orderBy = featureflags.BatchOrderBy()
	}
	if orderBy != "edd" && orderBy != "epo" && orderBy != "fifo" && orderBy != "readiness" {
		orderBy = "epo"
	}
	timeoutMs := featureflags.BatchTimeoutMs()
	if timeoutMs <= 0 {
		timeoutMs = 60000
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), time.Duration(timeoutMs)*time.Millisecond)
	defer cancel()
	proposals, summary, err := h.service.RescheduleAll(ctx, orderBy, actorFromContext(c), req.DryRun)
	if err != nil {
		if (errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled)) && len(proposals) > 0 {
			c.JSON(http.StatusOK, dto.Response{
				Success: true,
				Data: map[string]interface{}{
					"proposals": proposals,
					"summary":   summary,
					"partial":   true,
					"message":   "Request timed out or cancelled; partial results returned. Consider increasing client timeout for full results.",
				},
			})
			return
		}
		if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
			c.JSON(http.StatusRequestTimeout, dto.Response{
				Success: false,
				Error:   "Request timed out. For reschedule-all, use a client timeout of at least 30 seconds.",
			})
			return
		}
		c.JSON(statusForSchedulingErr(err), dto.Response{Success: false, Error: err.Error()})
		return
	}
	data := map[string]interface{}{
		"proposals": proposals,
		"summary":   summary,
	}
	if summary != nil && summary.LateCount > 0 && summary.Generated > 0 {
		data["message"] = buildLateJobsMessage(summary.LateCount, summary.Generated)
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) VerifyOverlaps(c *gin.Context) {
	var req dto.VerifyOverlapsRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid request body"})
		return
	}
	scope := strings.TrimSpace(strings.ToLower(req.Scope))
	if scope == "" {
		scope = "proposals"
	}
	if scope == "applied" {
		// scope=applied: verify job_step_schedule_slots (planned/running) - proposal_ids/proposals not required
		data, err := h.service.VerifyOverlapsFromAppliedSlots(req.JobIDs)
		if err != nil {
			c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
			return
		}
		c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
		return
	}
	// scope=proposals (default): require proposal_ids or proposals
	if len(req.ProposalIDs) == 0 && len(req.Proposals) == 0 {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "provide proposal_ids or proposals"})
		return
	}
	var svcProposals []service.VerifyOverlapsInput
	for _, p := range req.Proposals {
		slots := make([]service.VerifySlotInput, 0, len(p.ProposedSlots))
		for _, s := range p.ProposedSlots {
			slots = append(slots, service.VerifySlotInput{
				JobStepID:      s.JobStepID,
				MachineID:      s.MachineID,
				ScheduledStart: s.ScheduledStart,
				ScheduledEnd:   s.ScheduledEnd,
			})
		}
		svcProposals = append(svcProposals, service.VerifyOverlapsInput{
			ProposalID:    p.ProposalID,
			JobID:         p.JobID,
			ProposedSlots: slots,
		})
	}
	data, err := h.service.VerifyOverlaps(req.ProposalIDs, svcProposals)
	if err != nil {
		c.JSON(statusForSchedulingErr(err), dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) ListProposals(c *gin.Context) {
	jobID := c.Param("id")
	includeStale := c.Query("include_stale") == "true"
	data, err := h.service.ListProposals(jobID, includeStale)
	if err != nil {
		c.JSON(statusForSchedulingErr(err), dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) GetProposal(c *gin.Context) {
	proposalID := c.Param("id")
	data, err := h.service.GetProposal(proposalID)
	if err != nil {
		c.JSON(statusForSchedulingErr(err), dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) ApplyProposal(c *gin.Context) {
	c.Header("X-Deprecated", "true")
	jobID := c.Param("id")
	data, err := h.service.ApplyProposal(jobID)
	if err != nil {
		c.JSON(statusForSchedulingErr(err), dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) ApproveProposal(c *gin.Context) {
	proposalID := c.Param("id")
	var req dto.ProposalDecisionRequest
	if c.Request.ContentLength > 0 {
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid request body"})
			return
		}
	}
	data, err := h.service.ApproveProposalWithOpts(proposalID, actorFromContext(c), req.Notes, req.SkipStalenessCheck)
	if err != nil {
		c.JSON(statusForSchedulingErr(err), dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) RejectProposal(c *gin.Context) {
	proposalID := c.Param("id")
	var req dto.ProposalDecisionRequest
	_ = c.ShouldBindJSON(&req)
	data, err := h.service.RejectProposal(proposalID, actorFromContext(c), req.Reason)
	if err != nil {
		c.JSON(statusForSchedulingErr(err), dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) ApplyProposalByID(c *gin.Context) {
	proposalID := c.Param("id")
	var req dto.ProposalDecisionRequest
	if c.Request.ContentLength > 0 {
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid request body"})
			return
		}
	}
	data, err := h.service.ApplyProposalByIDWithOpts(proposalID, actorFromContext(c), req.IdempotencyKey, req.SkipStalenessCheck)
	if err != nil {
		c.JSON(statusForSchedulingErr(err), dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) SplitSuggestion(c *gin.Context) {
	jobStepID := c.Param("id")
	data, err := h.service.SuggestSplit(jobStepID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) DelayRisk(c *gin.Context) {
	jobID := c.Param("id")
	data, err := h.service.GetDelayRisk(jobID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) MachineRanking(c *gin.Context) {
	jobStepID := c.Param("id")
	start := time.Now()
	end := start.Add(8 * time.Hour)
	if v := c.Query("start"); v != "" {
		if parsed, err := time.Parse(time.RFC3339, v); err == nil {
			start = parsed
		}
	}
	if v := c.Query("end"); v != "" {
		if parsed, err := time.Parse(time.RFC3339, v); err == nil {
			end = parsed
		}
	}
	data, err := h.service.RankMachinesForJobStep(jobStepID, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) BottleneckForecast(c *gin.Context) {
	daysAhead := 7
	if v := c.Query("days_ahead"); v != "" {
		if parsed, err := strconv.Atoi(v); err == nil && parsed > 0 {
			daysAhead = parsed
		}
	}
	data, err := h.service.ForecastBottlenecks(daysAhead)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) Explanation(c *gin.Context) {
	jobID := c.Param("id")
	data, err := h.service.ExplainJob(jobID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *AISchedulingHandler) Metrics(c *gin.Context) {
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: h.service.GetMetrics()})
}

func buildLateJobsMessage(lateCount, totalGenerated int) string {
	return fmt.Sprintf("%d of %d jobs are estimated to complete after their deadline. Higher-priority jobs were scheduled first; lower-priority jobs may be late.", lateCount, totalGenerated)
}

func actorFromContext(c *gin.Context) string {
	if v, ok := c.Get(middleware.ContextUserIDKey); ok {
		if s, ok := v.(string); ok && s != "" {
			return s
		}
	}
	return c.GetHeader("X-User-Id")
}

func statusForSchedulingErr(err error) int {
	var actionErr *service.SchedulingActionError
	if errors.As(err, &actionErr) {
		return actionErr.StatusCode
	}
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return http.StatusNotFound
	}
	return http.StatusInternalServerError
}

// EmitSchedulingEvent handles POST /scheduling/events - emits machine_down, job_delay, urgent_insert.
// Gap 5: validates payload shape by type. Payload must be a JSON string.
func (h *AISchedulingHandler) EmitSchedulingEvent(c *gin.Context) {
	var req struct {
		Type    string `json:"type"`
		Payload string `json:"payload"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid request body"})
		return
	}
	eventType := strings.TrimSpace(strings.ToLower(req.Type))
	if eventType != "machine_down" && eventType != "job_delay" && eventType != "urgent_insert" {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "type must be machine_down, job_delay, or urgent_insert"})
		return
	}
	if err := validateEventPayload(eventType, req.Payload); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	if err := h.service.EmitSchedulingEvent(eventType, req.Payload); err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: map[string]interface{}{"message": "event emitted"}})
}

// validateEventPayload checks payload has required fields per event type.
func validateEventPayload(eventType, payload string) error {
	var m map[string]interface{}
	if err := json.Unmarshal([]byte(payload), &m); err != nil {
		return fmt.Errorf("payload must be valid JSON: %w", err)
	}
	switch eventType {
	case "machine_down":
		if _, ok := m["machine_id"]; !ok {
			return fmt.Errorf("machine_down payload requires machine_id")
		}
		if _, ok := m["start_time"]; !ok {
			return fmt.Errorf("machine_down payload requires start_time")
		}
		if _, ok := m["end_time"]; !ok {
			return fmt.Errorf("machine_down payload requires end_time")
		}
	case "job_delay":
		if _, ok := m["job_id"]; !ok {
			return fmt.Errorf("job_delay payload requires job_id")
		}
		if _, ok := m["delay_minutes"]; !ok {
			return fmt.Errorf("job_delay payload requires delay_minutes")
		}
	case "urgent_insert":
		if _, ok := m["job_id"]; !ok {
			return fmt.Errorf("urgent_insert payload requires job_id")
		}
		if p, ok := m["priority"].(string); ok && p != "" {
			pl := strings.ToLower(p)
			if pl != "high" && pl != "critical" {
				return fmt.Errorf("urgent_insert priority must be high or critical")
			}
		}
	}
	return nil
}
