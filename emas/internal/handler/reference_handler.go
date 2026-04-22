package handler

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

// ReferenceHandler handles reference/lookup CRUD
type ReferenceHandler struct {
	db *gorm.DB
}

func NewReferenceHandler(db *gorm.DB) *ReferenceHandler {
	return &ReferenceHandler{db: db}
}

// @Summary List machine types
// @Description List machine types
// @Tags reference
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=[]domain.ReferenceMachineType}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/machine-types [get]
func (h *ReferenceHandler) ListMachineTypes(c *gin.Context) {
	var items []domain.ReferenceMachineType
	if err := h.db.Order("name ASC").Find(&items).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: items})
}

// @Summary Create a machine type
// @Description Create a machine type
// @Tags reference
// @Accept json
// @Produce json
// @Param request body dto.CreateMachineTypeRequest true "Create Machine Type Request"
// @Success 201 {object} dto.Response{data=domain.ReferenceMachineType}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/machine-types [post]
func (h *ReferenceHandler) CreateMachineType(c *gin.Context) {
	var req dto.CreateMachineTypeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	req.Name = strings.TrimSpace(req.Name)
	if req.Name == "" {
		c.JSON(http.StatusUnprocessableEntity, dto.Response{Success: false, Error: "name is required and cannot be blank"})
		return
	}
	var exists int64
	h.db.Model(&domain.ReferenceMachineType{}).Where("name = ?", req.Name).Count(&exists)
	if exists > 0 {
		c.JSON(http.StatusConflict, dto.Response{Success: false, Error: "name already exists"})
		return
	}
	item := domain.ReferenceMachineType{Name: req.Name, Description: req.Description}
	if err := h.db.Create(&item).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: item})
}

// @Summary Update a machine type
// @Description Update a machine type
// @Tags reference
// @Accept json
// @Produce json
// @Param id path string true "Machine Type ID"
// @Param request body dto.UpdateMachineTypeRequest true "Update Machine Type Request"
// @Success 200 {object} dto.Response{data=domain.ReferenceMachineType}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/machine-types/{id} [put]
func (h *ReferenceHandler) UpdateMachineType(c *gin.Context) {
	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid id"})
		return
	}
	var req dto.UpdateMachineTypeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	var item domain.ReferenceMachineType
	if err := h.db.First(&item, id).Error; err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: "machine type not found"})
		return
	}
	updates := map[string]interface{}{}
	if req.Name != nil {
		name := strings.TrimSpace(*req.Name)
		if name == "" {
			c.JSON(http.StatusUnprocessableEntity, dto.Response{Success: false, Error: "name cannot be blank"})
			return
		}
		var exists int64
		h.db.Model(&domain.ReferenceMachineType{}).Where("name = ? AND id != ?", name, id).Count(&exists)
		if exists > 0 {
			c.JSON(http.StatusConflict, dto.Response{Success: false, Error: "name already exists"})
			return
		}
		updates["name"] = name
	}
	if req.Description != nil {
		updates["description"] = *req.Description
	}
	if len(updates) > 0 {
		if err := h.db.Model(&item).Updates(updates).Error; err != nil {
			c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
			return
		}
	}
	h.db.First(&item, id)
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: item})
}

// @Summary Delete a machine type
// @Description Delete a machine type
// @Tags reference
// @Accept json
// @Produce json
// @Param id path string true "Machine Type ID"
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/machine-types/{id} [delete]
func (h *ReferenceHandler) DeleteMachineType(c *gin.Context) {
	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid id"})
		return
	}
	var item domain.ReferenceMachineType
	if err := h.db.First(&item, id).Error; err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: "machine type not found"})
		return
	}
	var count int64
	h.db.Table("machines").Where("machine_type = ?", item.Name).Count(&count)
	if count > 0 {
		c.JSON(http.StatusConflict, dto.Response{Success: false, Error: "machine type is in use by machines"})
		return
	}
	h.db.Table("process_steps").Where("machine_type_required = ?", item.Name).Count(&count)
	if count > 0 {
		c.JSON(http.StatusConflict, dto.Response{Success: false, Error: "machine type is in use by process steps"})
		return
	}
	if err := h.db.Delete(&item).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true})
}

// @Summary List product types
// @Description List product types
// @Tags reference
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=[]domain.ReferenceProductType}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/product-types [get]
func (h *ReferenceHandler) ListProductTypes(c *gin.Context) {
	var items []domain.ReferenceProductType
	if err := h.db.Order("name ASC").Find(&items).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: items})
}

// @Summary Create a product type
// @Description Create a product type
// @Tags reference
// @Accept json
// @Produce json
// @Param request body dto.CreateProductTypeRequest true "Create Product Type Request"
// @Success 201 {object} dto.Response{data=domain.ReferenceProductType}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/product-types [post]
func (h *ReferenceHandler) CreateProductType(c *gin.Context) {
	var req dto.CreateProductTypeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	req.Name = strings.TrimSpace(req.Name)
	if req.Name == "" {
		c.JSON(http.StatusUnprocessableEntity, dto.Response{Success: false, Error: "name is required"})
		return
	}
	var exists int64
	h.db.Model(&domain.ReferenceProductType{}).Where("name = ?", req.Name).Count(&exists)
	if exists > 0 {
		c.JSON(http.StatusConflict, dto.Response{Success: false, Error: "name already exists"})
		return
	}
	item := domain.ReferenceProductType{Name: req.Name}
	if err := h.db.Create(&item).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: item})
}

// @Summary Delete a product type
// @Description Delete a product type
// @Tags reference
// @Accept json
// @Produce json
// @Param id path string true "Product Type ID"
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/product-types/{id} [delete]
func (h *ReferenceHandler) DeleteProductType(c *gin.Context) {
	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid id"})
		return
	}
	var item domain.ReferenceProductType
	if err := h.db.First(&item, id).Error; err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: "product type not found"})
		return
	}
	var count int64
	h.db.Table("products").Where("product_type = ?", item.Name).Count(&count)
	if count > 0 {
		c.JSON(http.StatusConflict, dto.Response{Success: false, Error: "product type is in use by products"})
		return
	}
	if err := h.db.Delete(&item).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true})
}

func displayForLocation(zone string, bay *string) string {
	if bay == nil || *bay == "" {
		return zone
	}
	return zone + " – " + *bay
}

// @Summary List locations
// @Description List locations
// @Tags reference
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=[]domain.ReferenceLocation}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/locations [get]
func (h *ReferenceHandler) ListLocations(c *gin.Context) {
	var items []domain.ReferenceLocation
	if err := h.db.Order("zone ASC, bay ASC").Find(&items).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	type out struct {
		ID      int    `json:"id"`
		Zone    string `json:"zone"`
		Bay     *string `json:"bay"`
		Display string `json:"display"`
	}
	result := make([]out, len(items))
	for i, loc := range items {
		result[i] = out{ID: loc.ID, Zone: loc.Zone, Bay: loc.Bay, Display: displayForLocation(loc.Zone, loc.Bay)}
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: result})
}

// @Summary Create a location
// @Description Create a location
// @Tags reference
// @Accept json
// @Produce json
// @Param request body dto.CreateLocationRequest true "Create Location Request"
// @Success 201 {object} dto.Response{data=domain.ReferenceLocation}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/locations [post]
func (h *ReferenceHandler) CreateLocation(c *gin.Context) {
	var req dto.CreateLocationRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	req.Zone = strings.TrimSpace(req.Zone)
	if req.Zone == "" {
		c.JSON(http.StatusUnprocessableEntity, dto.Response{Success: false, Error: "zone is required"})
		return
	}
	item := domain.ReferenceLocation{Zone: req.Zone, Bay: req.Bay}
	if err := h.db.Create(&item).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: map[string]interface{}{
		"id": item.ID, "zone": item.Zone, "bay": item.Bay, "display": displayForLocation(item.Zone, item.Bay),
	}})
}

// @Summary Delete a location
// @Description Delete a location
// @Tags reference
// @Accept json
// @Produce json
// @Param id path string true "Location ID"
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/locations/{id} [delete]
func (h *ReferenceHandler) DeleteLocation(c *gin.Context) {
	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid id"})
		return
	}
	var item domain.ReferenceLocation
	if err := h.db.First(&item, id).Error; err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: "location not found"})
		return
	}
	display := displayForLocation(item.Zone, item.Bay)
	var count int64
	h.db.Table("machines").Where("location = ?", display).Count(&count)
	if count > 0 {
		c.JSON(http.StatusConflict, dto.Response{Success: false, Error: "location is in use by machines"})
		return
	}
	if err := h.db.Delete(&item).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true})
}

// @Summary List storage locations
// @Description List storage locations
// @Tags reference
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=[]domain.ReferenceStorageLocation}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/storage-locations [get]
func (h *ReferenceHandler) ListStorageLocations(c *gin.Context) {
	var items []domain.ReferenceStorageLocation
	if err := h.db.Order("name ASC").Find(&items).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: items})
}

// @Summary Create a storage location
// @Description Create a storage location
// @Tags reference
// @Accept json
// @Produce json
// @Param request body dto.CreateStorageLocationRequest true "Create Storage Location Request"
// @Success 201 {object} dto.Response{data=domain.ReferenceStorageLocation}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/storage-locations [post]
func (h *ReferenceHandler) CreateStorageLocation(c *gin.Context) {
	var req dto.CreateStorageLocationRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	req.Name = strings.TrimSpace(req.Name)
	if req.Name == "" {
		c.JSON(http.StatusUnprocessableEntity, dto.Response{Success: false, Error: "name is required"})
		return
	}
	if req.Type == "" {
		req.Type = "shelf"
	}
	var exists int64
	h.db.Model(&domain.ReferenceStorageLocation{}).Where("name = ?", req.Name).Count(&exists)
	if exists > 0 {
		c.JSON(http.StatusConflict, dto.Response{Success: false, Error: "name already exists"})
		return
	}
	item := domain.ReferenceStorageLocation{Name: req.Name, Type: req.Type}
	if err := h.db.Create(&item).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: item})
}

// @Summary Delete a storage location
// @Description Delete a storage location
// @Tags reference
// @Accept json
// @Produce json
// @Param id path string true "Storage Location ID"
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/storage-locations/{id} [delete]
func (h *ReferenceHandler) DeleteStorageLocation(c *gin.Context) {
	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid id"})
		return
	}
	var item domain.ReferenceStorageLocation
	if err := h.db.First(&item, id).Error; err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: "storage location not found"})
		return
	}
	var count int64
	h.db.Table("inventory_materials").Where("storage_location = ?", item.Name).Count(&count)
	if count > 0 {
		c.JSON(http.StatusConflict, dto.Response{Success: false, Error: "storage location is in use by materials"})
		return
	}
	if err := h.db.Delete(&item).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true})
}

// @Summary List step types
// @Description List step types
// @Tags reference
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=[]domain.ReferenceStepType}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/step-types [get]

func (h *ReferenceHandler) ListStepTypes(c *gin.Context) {
	var items []domain.ReferenceStepType
	if err := h.db.Order("name ASC").Find(&items).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: items})
}

// @Summary Create a step type
// @Description Create a step type
// @Tags reference
// @Accept json
// @Produce json
// @Param request body dto.CreateStepTypeRequest true "Create Step Type Request"
// @Success 201 {object} dto.Response{data=domain.ReferenceStepType}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/step-types [post]
func (h *ReferenceHandler) CreateStepType(c *gin.Context) {
	var req dto.CreateStepTypeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	req.Name = strings.TrimSpace(req.Name)
	if req.Name == "" {
		c.JSON(http.StatusUnprocessableEntity, dto.Response{Success: false, Error: "name is required"})
		return
	}
	var exists int64
	h.db.Model(&domain.ReferenceStepType{}).Where("name = ?", req.Name).Count(&exists)
	if exists > 0 {
		c.JSON(http.StatusConflict, dto.Response{Success: false, Error: "name already exists"})
		return
	}
	item := domain.ReferenceStepType{Name: req.Name, DefaultMachineType: req.DefaultMachineType}
	if err := h.db.Create(&item).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: item})
}

// @Summary Delete a step type
// @Description Delete a step type
// @Tags reference
// @Accept json
// @Produce json
// @Param id path string true "Step Type ID"
// @Success 200 {object} dto.Response
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /reference/step-types/{id} [delete]
func (h *ReferenceHandler) DeleteStepType(c *gin.Context) {
	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid id"})
		return
	}
	var item domain.ReferenceStepType
	if err := h.db.First(&item, id).Error; err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: "step type not found"})
		return
	}
	if err := h.db.Delete(&item).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true})
}
