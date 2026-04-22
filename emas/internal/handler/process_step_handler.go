package handler

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/pkg/id"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

// ProcessStepHandler handles process-step-specific endpoints (e.g. materials per step).
type ProcessStepHandler struct {
	psmRepo   *repository.ProcessStepMaterialRepository
	invRepo   *repository.InventoryRepository
	processRepo *repository.ProcessRepository
}

func NewProcessStepHandler(psmRepo *repository.ProcessStepMaterialRepository, invRepo *repository.InventoryRepository, processRepo *repository.ProcessRepository) *ProcessStepHandler {
	return &ProcessStepHandler{psmRepo: psmRepo, invRepo: invRepo, processRepo: processRepo}
}

// @Summary ProcessStepMaterialResponse is the DTO for process step material.
// @Description ProcessStepMaterialResponse is the DTO for process step material.
// @Tags process-step
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=ProcessStepMaterialResponse}
type ProcessStepMaterialResponse struct {
	ID             string  `json:"id"`
	MaterialID     string  `json:"material_id"`
	ProductID      string  `json:"product_id,omitempty"`
	Role           string  `json:"role"`
	QuantityPerUnit float64 `json:"quantity_per_unit"`
	Unit           string  `json:"unit"`
	MaterialName   string  `json:"material_name,omitempty"`
}

// @Summary List materials for a step
// @Description List materials for a step
// @Tags process-step
// @Accept json
// @Produce json
// @Param step_id path string true "Step ID"
// @Param role query string true "Role"
// @Success 200 {object} dto.Response{data=[]domain.ProcessStepMaterial}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /process-steps/{step_id}/materials [get]
// Query ?role=input|output|all — default "input" for JobDetailsPanel; "all" for Process Routing edit.
func (h *ProcessStepHandler) ListMaterials(c *gin.Context) {
	stepID := c.Param("step_id")
	if stepID == "" {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "step_id required"})
		return
	}
	roleFilter := strings.ToLower(strings.TrimSpace(c.DefaultQuery("role", "input")))
	var list []domain.ProcessStepMaterial
	var err error
	switch roleFilter {
	case "all":
		list, err = h.psmRepo.ListByStepID(stepID)
	default:
		list, err = h.psmRepo.ListInputsByStepID(stepID)
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	resp := make([]ProcessStepMaterialResponse, 0, len(list))
	for _, m := range list {
		r := ProcessStepMaterialResponse{
			ID:              m.ID,
			Role:            m.Role,
			QuantityPerUnit: m.QuantityPerUnit,
			Unit:            m.Unit,
		}
		if m.MaterialID != nil {
			r.MaterialID = *m.MaterialID
			if h.invRepo != nil {
				if mat, err := h.invRepo.GetMaterialByID(*m.MaterialID); err == nil {
					r.MaterialName = mat.MaterialName
				}
			}
		}
		if m.ProductID != nil {
			r.ProductID = *m.ProductID
		}
		resp = append(resp, r)
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: resp})
}

// @Summary Add a material to a step
// @Description Add a material to a step
// @Tags process-step
// @Accept json
// @Produce json
// @Param step_id path string true "Step ID"
// @Param request body dto.AddProcessStepMaterialRequest true "Add Process Step Material Request"
// @Success 201 {object} dto.Response{data=domain.ProcessStepMaterial}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /process-steps/{step_id}/materials [post]
func (h *ProcessStepHandler) AddMaterial(c *gin.Context) {
	stepID := c.Param("step_id")
	if stepID == "" {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "step_id required"})
		return
	}
	var req dto.AddProcessStepMaterialRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	matID, prodID := strings.TrimSpace(req.MaterialID), strings.TrimSpace(req.ProductID)
	if (matID == "" && prodID == "") || (matID != "" && prodID != "") {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "exactly one of material_id or product_id required"})
		return
	}
	role := strings.ToLower(strings.TrimSpace(req.Role))
	if role != domain.ProcessStepMaterialRoleInput && role != domain.ProcessStepMaterialRoleOutput {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "role must be input or output"})
		return
	}
	if req.QuantityPerUnit <= 0 {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "quantity_per_unit must be > 0"})
		return
	}
	// Verify step exists
	if _, err := h.processRepo.GetStepByID(stepID); err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: "step not found"})
			return
		}
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	m := &domain.ProcessStepMaterial{
		ID:              id.NewPrefixed("PSM-"),
		StepID:          stepID,
		Role:            role,
		QuantityPerUnit: req.QuantityPerUnit,
		Unit:            strings.TrimSpace(req.Unit),
	}
	if matID != "" {
		m.MaterialID = &matID
	} else {
		m.ProductID = &prodID
	}
	if err := h.psmRepo.Create(m); err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: m})
}

// @Summary Delete a material from a step
// @Description Delete a material from a step
// @Tags process-step
// @Accept json
// @Produce json
// @Param step_id path string true "Step ID"
// @Param id path string true "Material ID"
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /process-steps/{step_id}/materials/{id} [delete]
func (h *ProcessStepHandler) DeleteMaterial(c *gin.Context) {
	stepID := c.Param("step_id")
	materialID := c.Param("id")
	if stepID == "" || materialID == "" {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "step_id and material id required"})
		return
	}
	existing, err := h.psmRepo.GetByID(materialID)
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: "process step material not found"})
			return
		}
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	if existing.StepID != stepID {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "material does not belong to this step"})
		return
	}
	if err := h.psmRepo.Delete(materialID); err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true})
}
