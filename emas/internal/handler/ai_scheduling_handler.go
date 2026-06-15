package handler

import (
	"context"
	"emas/internal/handler/dto"
	"emas/internal/middleware"
	"emas/internal/service"
	"emas/pkg/featureflags"
	"encoding/json"
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

// @Summary Assist a job
// @Description Assist a job. Supports optional field selection.
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Job ID"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/jobs/{id}/assist [get]
func (h *AISchedulingHandler) Assist(c *gin.Context) {
	jobID := c.Param("id")
	data, err := h.service.BuildAssist(jobID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

// @Summary Generate a proposal
// @Description Generate a proposal. Supports optional field selection.
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Job ID"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/jobs/{id}/proposal [get]
func (h *AISchedulingHandler) Proposal(c *gin.Context) {
	jobID := c.Param("id")
	includeInventoryActions := true
	if v := strings.TrimSpace(strings.ToLower(c.Query("include_inventory_actions"))); v != "" {
		includeInventoryActions = v == "true" || v == "1"
	}
	data, err := h.service.BuildProposalWithOptions(jobID, includeInventoryActions)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

// @Summary Generate a proposal
// @Description Generate a proposal
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Job ID"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/jobs/{id}/proposals [post]
func (h *AISchedulingHandler) GenerateProposal(c *gin.Context) {
	jobID := c.Param("id")
	includeInventoryActions := true
	if v := strings.TrimSpace(strings.ToLower(c.Query("include_inventory_actions"))); v != "" {
		includeInventoryActions = v == "true" || v == "1"
	}
	data, err := h.service.GenerateProposalWithOptions(jobID, actorFromContext(c), includeInventoryActions)
	if err != nil {
		c.JSON(statusForSchedulingErr(err), dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: data})
}

// @Summary Generate batch proposals
// @Description Generate batch proposals
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param request body dto.BatchProposalsRequest true "Batch Proposals Request"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/batch-proposals [post]
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
	if !isAllowedBatchOrderBy(orderBy) {
		orderBy = featureflags.DefaultBatchOrderBy
	}
	opts := &service.ScheduleJobSetOpts{
		IncludeInventoryActions: req.IncludeInventoryActions,
	}
	proposals, summary, err := h.service.ScheduleJobSet(c.Request.Context(), jobIDs, actorFromContext(c), orderBy, opts)
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

// @Summary Reschedule all
// @Description Reschedule all
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param request body dto.RescheduleAllRequest true "Reschedule All Request"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/reschedule-all [post]
func (h *AISchedulingHandler) RescheduleAll(c *gin.Context) {
	var req dto.RescheduleAllRequest
	_ = c.ShouldBindJSON(&req)
	orderBy := strings.TrimSpace(strings.ToLower(req.OrderBy))
	if orderBy == "" {
		orderBy = featureflags.BatchOrderBy()
	}
	if !isAllowedBatchOrderBy(orderBy) {
		orderBy = featureflags.DefaultBatchOrderBy
	}
	proposals, summary, err := h.service.RescheduleAll(c.Request.Context(), orderBy, actorFromContext(c), req.DryRun)
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

func isAllowedBatchOrderBy(orderBy string) bool {
	switch orderBy {
	case "edd", "epo", "fifo", "readiness", "material_priority", "weighted_tardiness_material", "product_deadline_fifo":
		return true
	default:
		return false
	}
}

// @Summary Verify overlaps
// @Description Verify overlaps
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param request body dto.VerifyOverlapsRequest true "Verify Overlaps Request"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/verify-overlaps [post]
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

// @Summary List proposals
// @Description List proposals. Supports optional field selection.
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Job ID"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/jobs/{id}/proposals [get]
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

// @Summary Get a proposal
// @Description Get a proposal. Supports optional field selection.
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Proposal ID"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/proposals/{id} [get]
func (h *AISchedulingHandler) GetProposal(c *gin.Context) {
	proposalID := c.Param("id")
	data, err := h.service.GetProposal(proposalID)
	if err != nil {
		c.JSON(statusForSchedulingErr(err), dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

// @Summary Apply a proposal
// @Description Apply a proposal
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Job ID"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/jobs/{id}/apply-proposal [post]
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

// @Summary Approve a proposal
// @Description Approve a proposal
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Proposal ID"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/proposals/{id}/approve [post]
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

// @Summary Reject a proposal
// @Description Reject a proposal
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Proposal ID"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/proposals/{id}/reject [post]
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

// @Summary Apply a proposal by ID
// @Description Apply a proposal by ID
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Proposal ID"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/proposals/{id}/apply [post]
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

// @Summary Split suggestion
// @Description Split suggestion. Supports optional field selection.
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Job Step ID"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/job-steps/{id}/split-suggestion [get]
func (h *AISchedulingHandler) SplitSuggestion(c *gin.Context) {
	jobStepID := c.Param("id")
	data, err := h.service.SuggestSplit(jobStepID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

// @Summary Delay risk
// @Description Delay risk
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Job ID"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/jobs/{id}/delay-risk [get]
func (h *AISchedulingHandler) DelayRisk(c *gin.Context) {
	jobID := c.Param("id")
	data, err := h.service.GetDelayRisk(jobID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

// @Summary Machine ranking
// @Description Machine ranking
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Job Step ID"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/job-steps/{id}/machine-ranking [get]
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

// @Summary Bottleneck forecast
// @Description Bottleneck forecast
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param days_ahead query int true "Days ahead"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/bottleneck-forecast [get]
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

// @Summary Explanation
// @Description Explanation
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Job ID"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/jobs/{id}/explanation [get]
func (h *AISchedulingHandler) Explanation(c *gin.Context) {
	jobID := c.Param("id")
	data, err := h.service.ExplainJob(jobID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

// @Summary Metrics
// @Description Metrics
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/metrics [get]
func (h *AISchedulingHandler) Metrics(c *gin.Context) {
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: h.service.GetMetrics()})
}

// @Summary Shortage analysis
// @Description Shortage analysis
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Job ID"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/jobs/{id}/shortage-analysis [get]
func (h *AISchedulingHandler) ShortageAnalysis(c *gin.Context) {
	jobID := c.Param("id")
	proposal, err := h.service.AnalyzeShortagesForProposal(jobID)
	if err != nil {
		c.JSON(statusForSchedulingErr(err), dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{
		Success: true,
		Data: map[string]interface{}{
			"job_id":                    proposal.JobID,
			"shortages":                 proposal.MaterialShortages,
			"replenishment_suggestions": proposal.ShortageResolutions,
			"resolution_options":        proposal.ShortageResolutions,
			"global_score":              proposal.GlobalScore,
		},
	})
}

// @Summary Apply replenishment
// @Description Apply replenishment
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Job ID"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/proposals/{id}/apply-replenishment [post]
func (h *AISchedulingHandler) ApplyReplenishment(c *gin.Context) {
	var req dto.ApplyReplenishmentRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid request body"})
		return
	}
	items := make([]service.ReplenishmentArrivalInput, 0, len(req.Suggestions))
	for _, item := range req.Suggestions {
		var snapshot *service.InventorySnapshot
		if item.InventorySnapshot != nil {
			snapshot = &service.InventorySnapshot{
				MaterialID: item.InventorySnapshot.MaterialID,
				Version:    item.InventorySnapshot.Version,
				ComputedAt: item.InventorySnapshot.ComputedAt,
			}
		}
		items = append(items, service.ReplenishmentArrivalInput{
			OptionType:        item.OptionType,
			MaterialID:        item.MaterialID,
			Quantity:          item.Quantity,
			ArriveAt:          item.ArriveAt,
			Notes:             item.Notes,
			InventorySnapshot: snapshot,
		})
	}
	data, err := h.service.ApplyReplenishment(c.Request.Context(), items)
	if err != nil {
		c.JSON(statusForSchedulingErr(err), dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

// @Summary Apply replenishment batch
// @Description Apply replenishment batch
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param request body dto.ApplyReplenishmentBatchRequest true "Apply Replenishment Batch Request"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/apply-replenishment-batch [post]
func (h *AISchedulingHandler) ApplyReplenishmentBatch(c *gin.Context) {
	var req dto.ApplyReplenishmentBatchRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid request body"})
		return
	}
	raw := req.Suggestions
	if len(raw) == 0 {
		raw = req.Arrivals
	}
	if len(raw) == 0 {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "provide non-empty suggestions or arrivals array"})
		return
	}
	items := make([]service.ReplenishmentArrivalInput, 0, len(raw))
	for _, item := range raw {
		var snapshot *service.InventorySnapshot
		if item.InventorySnapshot != nil {
			snapshot = &service.InventorySnapshot{
				MaterialID: item.InventorySnapshot.MaterialID,
				Version:    item.InventorySnapshot.Version,
				ComputedAt: item.InventorySnapshot.ComputedAt,
			}
		}
		items = append(items, service.ReplenishmentArrivalInput{
			OptionType:        item.OptionType,
			MaterialID:        item.MaterialID,
			Quantity:          item.Quantity,
			ArriveAt:          item.ArriveAt,
			Notes:             item.Notes,
			InventorySnapshot: snapshot,
		})
	}
	data, err := h.service.ApplyReplenishment(c.Request.Context(), items)
	if err != nil {
		c.JSON(statusForSchedulingErr(err), dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

// @Summary Replenish and replan
// @Description Replenish and replan
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param id path string true "Job ID"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /ai/scheduling/jobs/{id}/replenish-and-replan [post]
func (h *AISchedulingHandler) ReplenishAndReplan(c *gin.Context) {
	jobID := c.Param("id")
	var req dto.ReplenishAndReplanRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid request body"})
		return
	}
	items := make([]service.ReplenishmentArrivalInput, 0, len(req.Arrivals))
	for _, item := range req.Arrivals {
		var snapshot *service.InventorySnapshot
		if item.InventorySnapshot != nil {
			snapshot = &service.InventorySnapshot{
				MaterialID: item.InventorySnapshot.MaterialID,
				Version:    item.InventorySnapshot.Version,
				ComputedAt: item.InventorySnapshot.ComputedAt,
			}
		}
		items = append(items, service.ReplenishmentArrivalInput{
			OptionType:        item.OptionType,
			MaterialID:        item.MaterialID,
			Quantity:          item.Quantity,
			ArriveAt:          item.ArriveAt,
			Notes:             item.Notes,
			InventorySnapshot: snapshot,
		})
	}
	data, err := h.service.ReplenishAndReplan(c.Request.Context(), jobID, actorFromContext(c), service.ReplenishAndReplanInput{
		Arrivals:            items,
		Attempt:             req.Attempt,
		PreviousDeficits:    req.PreviousDeficits,
		PreviousGlobalScore: req.PreviousGlobalScore,
		AllowPartial:        req.AllowPartial,
	})
	if err != nil {
		status := statusForSchedulingErr(err)
		c.JSON(status, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: data})
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

// @Summary Emit scheduling event
// @Description Emit scheduling event
// @Tags ai scheduling
// @Accept json
// @Produce json
// @Param request body dto.SchedulingEventRequest true "Scheduling Event Request"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /scheduling/events [post]
func (h *AISchedulingHandler) EmitSchedulingEvent(c *gin.Context) {
	var req dto.SchedulingEventRequest
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
