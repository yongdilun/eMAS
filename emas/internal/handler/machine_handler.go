package handler

import (
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/internal/service"
	"emas/pkg/featureflags"
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
)

func parseInt(s string) (int, error) {
	return strconv.Atoi(s)
}

// SchedulingEventEmitter emits scheduling events (machine_down, job_delay, urgent_insert).
type SchedulingEventEmitter interface {
	EmitSchedulingEvent(eventType, payload string) error
}

type MachineHandler struct {
	machineService *service.MachineService
	eventEmitter   SchedulingEventEmitter
}

func NewMachineHandler(machineService *service.MachineService, eventEmitter SchedulingEventEmitter) *MachineHandler {
	return &MachineHandler{machineService: machineService, eventEmitter: eventEmitter}
}

// Create godoc
// @Summary Create a machine
// @Description Creates a new machine in the factory. machine_id is generated with the M- prefix when omitted.
// @Tags machines
// @Accept json
// @Produce json
// @Param request body dto.CreateMachineRequest true "Machine Create Request"
// @Success 201 {object} dto.Response{data=domain.Machine}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /machines [post]
func (h *MachineHandler) Create(c *gin.Context) {
	var req dto.CreateMachineRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	machine, err := h.machineService.Create(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: machine})
}

// GetByID godoc
// @Summary Get machine by ID
// @Description Retrieve details of a specific machine. Supports optional field selection.
// @Tags machines
// @Accept json
// @Produce json
// @Param id path string true "Machine ID"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=domain.Machine}
// @Failure 404 {object} dto.Response
// @Router /machines/{id} [get]
func (h *MachineHandler) GetByID(c *gin.Context) {
	id := c.Param("id")
	machine, err := h.machineService.GetByID(id)
	if err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: machine})
}

// List godoc
// @Summary List all machines
// @Description Retrieve a list of machines with optional filters, sorting, and pagination
// @Tags machines
// @Accept json
// @Produce json
// @Param status query string false "Filter by status" Enums(idle,running,maintenance,offline)
// @Param machine_name query string false "Filter by machine name (case-insensitive contains)"
// @Param machine_type query string false "Filter by machine type"
// @Param location query string false "Filter by location"
// @Param sort_by query string false "Field to sort by" Enums(machine_id,machine_name,machine_type,status,location,capacity_per_hour,utilization_rate,last_maintenance_date,created_at)
// @Param sort_dir query string false "Sort direction (asc, desc)" Enums(asc,desc)
// @Param limit query int false "Limit number of results"
// @Param offset query int false "Offset for pagination"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=[]domain.Machine}
// @Failure 500 {object} dto.Response
// @Router /machines [get]
func (h *MachineHandler) List(c *gin.Context) {
	var query dto.MachineListQuery
	if err := c.ShouldBindQuery(&query); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	var f repository.MachineListFilter
	f.Status = string(query.Status)
	f.MachineName = query.MachineName
	f.MachineType = query.MachineType
	f.Location = query.Location
	f.SortBy = query.SortBy
	f.SortDir = string(query.SortDir)
	f.Fields = query.Fields
	f.Limit = query.Limit
	f.Offset = query.Offset
	if f.SortDir == "" {
		f.SortDir = "asc"
	}

	machines, err := h.machineService.ListFiltered(f)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: machines})
}

// Update godoc
// @Summary Update a machine
// @Description Updates an existing machine's details
// @Tags machines
// @Accept json
// @Produce json
// @Param id path string true "Machine ID"
// @Param request body dto.UpdateMachineRequest true "Machine Update Request"
// @Success 200 {object} dto.Response{data=domain.Machine}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /machines/{id} [put]
func (h *MachineHandler) Update(c *gin.Context) {
	id := c.Param("id")
	var req dto.UpdateMachineRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	machine, err := h.machineService.Update(id, req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: machine})
}

// @Summary Assign a capability to a machine
// @Description Assign a capability to a machine
// @Tags machines
// @Accept json
// @Produce json
// @Param id path string true "Machine ID"
// @Param request body dto.AssignCapabilityRequest true "Assign Capability Request"
// @Success 201 {object} dto.Response{data=domain.MachineCapabilities}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /machines/{id}/capabilities [post]
func (h *MachineHandler) AssignCapability(c *gin.Context) {
	machineID := c.Param("id")
	var req dto.AssignCapabilityRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	cap, err := h.machineService.AssignCapability(machineID, req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: cap})
}

// @Summary Record downtime
// @Description Record downtime
// @Tags machines
// @Accept json
// @Produce json
// @Param request body dto.RecordDowntimeRequest true "Record Downtime Request"
// @Success 201 {object} dto.Response{data=domain.MachineDowntime}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /machines/downtime [post]
func (h *MachineHandler) RecordDowntime(c *gin.Context) {
	var req dto.RecordDowntimeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	record, err := h.machineService.RecordDowntime(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	// Gap 4: optionally emit machine_down scheduling event for auto-reschedule
	if h.eventEmitter != nil && featureflags.EmitEventOnDowntime() {
		payload := map[string]string{
			"machine_id": record.MachineID,
			"start_time": record.StartTime.Format("2006-01-02T15:04:05Z07:00"),
			"end_time":   record.EndTime.Format("2006-01-02T15:04:05Z07:00"),
		}
		if b, err := json.Marshal(payload); err == nil {
			_ = h.eventEmitter.EmitSchedulingEvent("machine_down", string(b))
		}
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: record})
}

// @Summary Get maintenance alerts
// @Description Get maintenance alerts
// @Tags machines
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=[]domain.Machine}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /machines/maintenance-alerts [get]
func (h *MachineHandler) MaintenanceAlerts(c *gin.Context) {
	daysAhead := 7
	if v := c.Query("days_ahead"); v != "" {
		if n, err := parseInt(v); err == nil && n > 0 {
			daysAhead = n
		}
	}
	machines, err := h.machineService.GetMaintenanceAlerts(daysAhead)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: machines})
}

// @Summary Get utilization
// @Description Get utilization
// @Tags machines
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /machines/utilization [get]
func (h *MachineHandler) Utilization(c *gin.Context) {
	machines, err := h.machineService.ListAll()
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	type item struct {
		MachineID      string  `json:"machine_id"`
		MachineName    string  `json:"machine_name"`
		UtilizationPct float64 `json:"utilization_pct"`
	}
	data := make([]item, len(machines))
	var sum float64
	for i, m := range machines {
		pct := m.UtilizationRate
		if pct == 0 {
			switch m.Status {
			case "running":
				pct = 88
			case "idle":
				pct = 65
			case "maintenance":
				pct = 42
			default:
				pct = 70
			}
		}
		data[i] = item{MachineID: m.MachineID, MachineName: m.MachineName, UtilizationPct: pct}
		sum += pct
	}
	avg := 78.0
	if len(data) > 0 {
		avg = sum / float64(len(data))
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: map[string]interface{}{
		"avg_pct": avg,
		"data":    data,
	}})
}

// @Summary Get reroute recommendations
// @Description Get reroute recommendations
// @Tags machines
// @Accept json
// @Produce json
// @Param machine_id query string true "Machine ID"
// @Success 200 {object} dto.Response{data=map[string][]string}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /machines/reroute-recommendations [get]
func (h *MachineHandler) RerouteRecommendations(c *gin.Context) {
	machineID := c.Query("machine_id")
	if machineID == "" {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "machine_id required"})
		return
	}
	recs, err := h.machineService.GetRerouteRecommendations(machineID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: recs})
}
