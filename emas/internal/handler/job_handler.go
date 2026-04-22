package handler

import (
	"errors"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/internal/service"
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type JobHandler struct {
	jobService *service.JobService
}

func NewJobHandler(jobService *service.JobService) *JobHandler {
	return &JobHandler{jobService: jobService}
}

// @Summary Create a job
// @Description Create a job
// @Tags job
// @Accept json
// @Produce json
// @Param request body dto.CreateJobRequest true "Create Job Request"
// @Success 201 {object} dto.Response{data=domain.Job}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /jobs [post]
func (h *JobHandler) Create(c *gin.Context) {
	var req dto.CreateJobRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	job, err := h.jobService.Create(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: job})
}

// @Summary Get a job by ID
// @Description Get a job by ID
// @Tags job
// @Accept json
// @Produce json
// @Param id path string true "Job ID"
// @Success 200 {object} dto.Response{data=domain.Job}
// @Failure 404 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /jobs/{id} [get]
func (h *JobHandler) GetByID(c *gin.Context) {
	id := c.Param("id")
	job, err := h.jobService.GetByID(id)
	if err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: job})
}

func (h *JobHandler) ListSteps(c *gin.Context) {
	id := c.Param("id")
	steps, err := h.jobService.ListStepsByJobID(id)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: steps})
}

func (h *JobHandler) List(c *gin.Context) {
	var f repository.JobListFilter
	f.ProductID = c.Query("product_id")
	f.Status = c.Query("status")
	f.Priority = c.Query("priority")
	f.MachineID = c.Query("machine_id")
	f.SortBy = c.DefaultQuery("sort_by", "created_at")
	f.SortDir = c.DefaultQuery("sort_dir", "desc")

	if v := c.Query("start"); v != "" {
		if t, err := time.Parse(time.RFC3339, v); err == nil {
			f.Start = &t
		}
	}
	if v := c.Query("end"); v != "" {
		if t, err := time.Parse(time.RFC3339, v); err == nil {
			f.End = &t
		}
	}
	if v := c.Query("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			f.Limit = n
		}
	}
	if v := c.Query("offset"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			f.Offset = n
		}
	}

	jobs, err := h.jobService.ListFiltered(f)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: jobs})
}

func (h *JobHandler) Update(c *gin.Context) {
	id := c.Param("id")
	var req dto.UpdateJobRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	job, err := h.jobService.Update(id, req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: job})
}

func (h *JobHandler) Delete(c *gin.Context) {
	id := c.Param("id")
	if err := h.jobService.Delete(id); err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: "job not found"})
			return
		}
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true})
}

func (h *JobHandler) Duplicate(c *gin.Context) {
	id := c.Param("id")
	var req struct {
		Deadline string `json:"deadline"`
		Quantity int    `json:"quantity"`
	}
	_ = c.ShouldBindJSON(&req)
	deadline, _ := time.Parse(time.RFC3339, req.Deadline)
	job, err := h.jobService.Duplicate(id, deadline, req.Quantity)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: job})
}
