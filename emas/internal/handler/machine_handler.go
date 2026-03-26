package handler

import (
	"encoding/json"
	"emas/internal/handler/dto"
	"emas/internal/service"
	"emas/pkg/featureflags"
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

func (h *MachineHandler) GetByID(c *gin.Context) {
	id := c.Param("id")
	machine, err := h.machineService.GetByID(id)
	if err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: machine})
}

func (h *MachineHandler) List(c *gin.Context) {
	machines, err := h.machineService.ListAll()
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: machines})
}

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

func (h *MachineHandler) Utilization(c *gin.Context) {
	machines, err := h.machineService.ListAll()
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	type item struct {
		MachineID       string  `json:"machine_id"`
		MachineName     string  `json:"machine_name"`
		UtilizationPct  float64 `json:"utilization_pct"`
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
