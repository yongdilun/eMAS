package handler

import (
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/internal/service"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
)

type ProcessHandler struct {
	processService *service.ProcessService
}

func NewProcessHandler(processService *service.ProcessService) *ProcessHandler {
	return &ProcessHandler{processService: processService}
}

// @Summary Create a process
// @Description Create a process. process_id is generated with the PRC- prefix when omitted.
// @Tags process
// @Accept json
// @Produce json
// @Param request body dto.CreateProcessRequest true "Create Process Request"
// @Success 201 {object} dto.Response{data=domain.ProductProcess}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /processes [post]
func (h *ProcessHandler) Create(c *gin.Context) {
	var req dto.CreateProcessRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	p, err := h.processService.Create(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: p})
}

// @Summary Get a process by ID
// @Description Get a process by ID. Supports optional field selection.
// @Tags process
// @Accept json
// @Produce json
// @Param id path string true "Process ID"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=domain.ProductProcess}
// @Failure 404 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /processes/{id} [get]
func (h *ProcessHandler) GetByID(c *gin.Context) {
	id := c.Param("id")
	p, err := h.processService.GetByID(id)
	if err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: p})
}

// @Summary Get a process by product ID
// @Description Get a process by product ID. Supports optional field selection.
// @Tags process
// @Accept json
// @Produce json
// @Param id path string true "Product ID"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=domain.ProductProcess}
// @Failure 404 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /processes/product/{id} [get]
func (h *ProcessHandler) GetByProduct(c *gin.Context) {
	productID := c.Param("id")
	p, err := h.processService.GetByProductID(productID)
	if err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: p})
}

// @Summary List processes
// @Description List processes with optional filters, sorting, and pagination
// @Tags process
// @Accept json
// @Produce json
// @Param product_id query string false "Filter by product ID"
// @Param sort_by query string false "Field to sort by (process_id, product_id, sequence, version, created_at)"
// @Param sort_dir query string false "Sort direction (asc, desc)"
// @Param limit query int false "Limit number of results"
// @Param offset query int false "Offset for pagination"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=[]domain.ProductProcess}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /processes [get]
func (h *ProcessHandler) List(c *gin.Context) {
	var f repository.ProcessListFilter
	f.ProductID = c.Query("product_id")
	f.SortBy = c.Query("sort_by")
	f.SortDir = c.Query("sort_dir")
	f.Fields = c.Query("fields")
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

	list, err := h.processService.ListFiltered(f)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: list})
}

// @Summary List steps by process ID
// @Description List steps by process ID. Supports optional field selection.
// @Tags process
// @Accept json
// @Produce json
// @Param id path string true "Process ID"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=[]domain.ProcessSteps}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /processes/{id}/steps [get]
func (h *ProcessHandler) ListSteps(c *gin.Context) {
	id := c.Param("id")
	steps, err := h.processService.ListSteps(id)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: steps})
}

// @Summary Add a step to a process
// @Description Add a step to a process
// @Tags process
// @Accept json
// @Produce json
// @Param id path string true "Process ID"
// @Param request body dto.CreateProcessStepRequest true "Create Process Step Request"
// @Success 201 {object} dto.Response{data=domain.ProcessSteps}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /processes/{id}/steps [post]
func (h *ProcessHandler) AddStep(c *gin.Context) {
	id := c.Param("id")
	var req dto.CreateProcessStepRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	step, err := h.processService.AddStep(id, req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: step})
}

// @Summary Delete a process
// @Description Delete a process
// @Tags process
// @Accept json
// @Produce json
// @Param id path string true "Process ID"
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /processes/{id} [delete]
func (h *ProcessHandler) Delete(c *gin.Context) {
	id := c.Param("id")
	if err := h.processService.Delete(id); err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true})
}
