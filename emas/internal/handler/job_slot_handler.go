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

// @Summary Create job steps from routing
// @Description Create job steps from routing
// @Tags job slot
// @Accept json
// @Produce json
// @Param request body dto.CreateJobStepsRequest true "Create Job Steps Request"
// @Success 201 {object} dto.Response{data=[]domain.JobSteps}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /job-steps [post]
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

// @Summary Split a step
// @Description Split a step
// @Tags job slot
// @Accept json
// @Produce json
// @Param request body dto.SplitStepRequest true "Split Step Request"
// @Success 201 {object} dto.Response{data=[]domain.JobStepScheduleSlots}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /job-steps/split [post]
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

// @Summary Update a slot
// @Description Update a slot
// @Tags job slot
// @Accept json
// @Produce json
// @Param id path string true "Slot ID"
// @Param request body dto.UpdateSlotRequest true "Update Slot Request"
// @Success 200 {object} dto.Response{data=domain.JobStepScheduleSlots}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /slots/{id} [put]
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

// @Summary Get a slot by ID
// @Description Get a slot by ID. Supports optional field selection.
// @Tags job slot
// @Accept json
// @Produce json
// @Param id path string true "Slot ID"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=domain.JobStepScheduleSlots}
// @Failure 404 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /slots/{id} [get]
func (h *JobSlotHandler) GetSlot(c *gin.Context) {
	id := c.Param("id")
	slot, err := h.slotService.GetSlot(id)
	if err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: slot})
}

// @Summary List slots by job step ID
// @Description List slots by job step ID
// @Tags job slot
// @Accept json
// @Produce json
// @Param id path string true "Job Step ID"
// @Success 200 {object} dto.Response{data=[]domain.JobStepScheduleSlots}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /job-steps/{id}/slots [get]
func (h *JobSlotHandler) ListSlotsByJobStep(c *gin.Context) {
	jobStepID := c.Param("id")
	slots, err := h.slotService.ListSlotsByJobStepID(jobStepID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: slots})
}

// @Summary List slots by job ID
// @Description List slots by job ID
// @Tags job slot
// @Accept json
// @Produce json
// @Param id path string true "Job ID"
// @Success 200 {object} dto.Response{data=[]domain.JobStepScheduleSlots}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /jobs/{id}/slots [get]
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
