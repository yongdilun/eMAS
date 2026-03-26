package handler

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/service"
	"net/http"

	"github.com/gin-gonic/gin"
)

type MaintenanceHandler struct {
	maintenanceService *service.MaintenanceService
}

func NewMaintenanceHandler(maintenanceService *service.MaintenanceService) *MaintenanceHandler {
	return &MaintenanceHandler{maintenanceService: maintenanceService}
}

func (h *MaintenanceHandler) RecordMaintenance(c *gin.Context) {
	var req dto.RecordMaintenanceRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	mtype := req.MaintenanceType
	if mtype == "" {
		mtype = domain.MaintenanceTypePreventive
	}
	record, err := h.maintenanceService.RecordMaintenance(
		req.MachineID, mtype, req.Technician, req.Description, req.StartTime, req.EndTime)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: record})
}
