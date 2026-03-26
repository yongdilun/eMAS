package handler

import (
	"emas/internal/handler/dto"
	"emas/internal/service"
	"net/http"

	"github.com/gin-gonic/gin"
)

type JobSlotHandler struct {
	slotService *service.JobSlotService
}

func NewJobSlotHandler(slotService *service.JobSlotService) *JobSlotHandler {
	return &JobSlotHandler{slotService: slotService}
}

func (h *JobSlotHandler) CreateJobSteps(c *gin.Context) {
	var req dto.CreateJobStepsRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	steps, err := h.slotService.CreateJobStepsFromRouting(req.JobID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: steps})
}

func (h *JobSlotHandler) SplitStep(c *gin.Context) {
	var req dto.SplitStepRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	slots, err := h.slotService.SplitStep(req.JobStepID, req.Splits)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: slots})
}

func (h *JobSlotHandler) UpdateSlot(c *gin.Context) {
	id := c.Param("id")
	var req dto.UpdateSlotRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	slot, err := h.slotService.UpdateSlot(id, req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: slot})
}

func (h *JobSlotHandler) GetSlot(c *gin.Context) {
	id := c.Param("id")
	slot, err := h.slotService.GetSlot(id)
	if err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: slot})
}

func (h *JobSlotHandler) ListSlotsByJobStep(c *gin.Context) {
	jobStepID := c.Param("id")
	slots, err := h.slotService.ListSlotsByJobStepID(jobStepID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: slots})
}

func (h *JobSlotHandler) ListSlotsByJob(c *gin.Context) {
	jobID := c.Param("id")
	slots, err := h.slotService.ListSlotsByJobID(jobID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: slots})
}

func (h *JobSlotHandler) CancelSlot(c *gin.Context) {
	id := c.Param("id")
	if err := h.slotService.CancelSlot(id); err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true})
}
