package handler

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/internal/service"
	"errors"
	"net/http"
	"strings"
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

// @Summary List jobs
// @Description List jobs with filters
// @Tags job
// @Accept json
// @Produce json
// @Param product_id query string false "Filter by product"
// @Param status query string false "Filter by status" Enums(planned,scheduled,running,blocked,paused,completed,cancelled)
// @Param priority query string false "Filter by priority" Enums(low,medium,high,urgent)
// @Param machine_id query string false "Filter by machine"
// @Param start query string false "RFC3339 start"
// @Param end query string false "RFC3339 end"
// @Param sort_by query string false "created_at|deadline|priority|quantity_total|completion"
// @Param sort_dir query string false "asc|desc" Enums(asc,desc)
// @Param limit query int false "Page size"
// @Param offset query int false "Offset"
// @Param fields query string false "Comma-separated fields to return (job_id,priority,product_id,status,deadline)"
// @Success 200 {object} dto.Response{data=[]domain.Job}
// @Failure 500 {object} dto.Response
// @Router /jobs [get]
func (h *JobHandler) List(c *gin.Context) {
	var query dto.JobListQuery
	if err := c.ShouldBindQuery(&query); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	var f repository.JobListFilter
	f.ProductID = query.ProductID
	f.Status = string(query.Status)
	f.Priority = string(query.Priority)
	f.MachineID = query.MachineID
	f.SortBy = query.SortBy
	f.SortDir = string(query.SortDir)
	f.Fields = parseJobFields(query.Fields)

	if v := query.Start; v != "" {
		if t, err := time.Parse(time.RFC3339, v); err == nil {
			f.Start = &t
		}
	}
	if v := query.End; v != "" {
		if t, err := time.Parse(time.RFC3339, v); err == nil {
			f.End = &t
		}
	}
	f.Limit = query.Limit
	f.Offset = query.Offset
	if f.SortBy == "" {
		f.SortBy = "created_at"
	}
	if f.SortDir == "" {
		f.SortDir = "desc"
	}

	jobs, err := h.jobService.ListFiltered(f)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	if len(f.Fields) > 0 {
		c.JSON(http.StatusOK, dto.Response{Success: true, Data: projectJobs(jobs, f.Fields)})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: jobs})
}

func parseJobFields(raw string) []string {
	if strings.TrimSpace(raw) == "" {
		return nil
	}
	allowed := map[string]string{
		"id":                 "job_id",
		"job_id":             "job_id",
		"product_id":         "product_id",
		"quantity_total":     "quantity_total",
		"quantity_completed": "quantity_completed",
		"priority":           "priority",
		"deadline":           "deadline",
		"status":             "status",
		"created_at":         "created_at",
		"updated_at":         "updated_at",
		"notes":              "notes",
	}
	fields := make([]string, 0)
	seen := make(map[string]bool)
	for _, token := range strings.Split(raw, ",") {
		normalized := strings.ToLower(strings.TrimSpace(token))
		field, ok := allowed[normalized]
		if !ok || seen[field] {
			continue
		}
		seen[field] = true
		fields = append(fields, field)
	}
	return fields
}

func projectJobs(jobs []domain.Job, fields []string) []map[string]interface{} {
	out := make([]map[string]interface{}, 0, len(jobs))
	for _, job := range jobs {
		row := make(map[string]interface{}, len(fields))
		for _, field := range fields {
			switch field {
			case "job_id":
				row["job_id"] = job.JobID
			case "product_id":
				row["product_id"] = job.ProductID
			case "quantity_total":
				row["quantity_total"] = job.QuantityTotal
			case "quantity_completed":
				row["quantity_completed"] = job.QuantityCompleted
			case "priority":
				row["priority"] = job.Priority
			case "deadline":
				row["deadline"] = job.Deadline
			case "status":
				row["status"] = job.Status
			case "created_at":
				row["created_at"] = job.CreatedAt
			case "updated_at":
				row["updated_at"] = job.UpdatedAt
			case "notes":
				row["notes"] = job.Notes
			}
		}
		out = append(out, row)
	}
	return out
}

// @Summary Update a job
// @Description Update mutable job fields
// @Tags job
// @Accept json
// @Produce json
// @Param id path string true "Job ID"
// @Param request body dto.UpdateJobRequest true "Update Job Request"
// @Success 200 {object} dto.Response{data=domain.Job}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /jobs/{id} [put]
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

// @Summary Delete a job
// @Description Delete a job and clear all slot assignments tied to this job
// @Tags job
// @Accept json
// @Produce json
// @Param id path string true "Job ID"
// @Success 200 {object} dto.Response
// @Failure 404 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /jobs/{id} [delete]
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
