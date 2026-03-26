package handler

import (
	"emas/internal/handler/dto"
	"emas/internal/service"
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

type SchedulingHandler struct {
	schedulingService *service.SchedulingService
}

func NewSchedulingHandler(schedulingService *service.SchedulingService) *SchedulingHandler {
	return &SchedulingHandler{schedulingService: schedulingService}
}

func (h *SchedulingHandler) Explosion(c *gin.Context) {
	var req dto.SchedulingExplosionRequest
	if c.Request.Method == http.MethodGet {
		req.ProductID = c.Param("id")
		req.Quantity = 1
		if qty := c.Query("quantity"); qty != "" {
			var parsed float64
			_, _ = fmt.Sscanf(qty, "%f", &parsed)
			if parsed > 0 {
				req.Quantity = parsed
			}
		}
	} else if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	data, err := h.schedulingService.ExplodeDemand(req.ProductID, req.Quantity)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *SchedulingHandler) Readiness(c *gin.Context) {
	productID := c.Query("product_id")
	if productID == "" {
		productID = c.Param("id")
	}
	qty := 1.0
	if v := c.Query("quantity"); v != "" {
		_, _ = fmt.Sscanf(v, "%f", &qty)
	}
	data, err := h.schedulingService.CheckReadiness(productID, qty)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *SchedulingHandler) CandidateMachines(c *gin.Context) {
	stepID := c.Param("id")
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
	data, err := h.schedulingService.CandidateMachinesForStep(stepID, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *SchedulingHandler) ValidateSlot(c *gin.Context) {
	var req dto.SchedulingSlotValidationRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	data, err := h.schedulingService.ValidateSlot(req.JobStepID, req.MachineID, req.ScheduledStart, req.ScheduledEnd, req.Quantity, req.ExcludeSlotID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *SchedulingHandler) EstimateJobCompletion(c *gin.Context) {
	jobID := c.Param("id")
	data, err := h.schedulingService.EstimateJobEarliestCompletion(jobID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *SchedulingHandler) TrainingDataset(c *gin.Context) {
	data, err := h.schedulingService.ExportTrainingDataset()
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *SchedulingHandler) SolverPreview(c *gin.Context) {
	jobID := c.Param("id")
	data, err := h.schedulingService.BuildSolverPreview(jobID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: data})
}

func (h *SchedulingHandler) RefreshWorkCalendars(c *gin.Context) {
	if err := h.schedulingService.RefreshWorkCalendarsFromSettings(); err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: map[string]string{"message": "work calendars refreshed from scheduling settings"}})
}
