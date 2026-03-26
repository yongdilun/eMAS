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

// --- Machine Types ---

func (h *ReferenceHandler) ListMachineTypes(c *gin.Context) {
	var items []domain.ReferenceMachineType
	if err := h.db.Order("name ASC").Find(&items).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: items})
}

func (h *ReferenceHandler) CreateMachineType(c *gin.Context) {
	var req struct {
		Name        string `json:"name" binding:"required"`
		Description string `json:"description"`
	}
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

func (h *ReferenceHandler) UpdateMachineType(c *gin.Context) {
	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: "invalid id"})
		return
	}
	var req struct {
		Name        *string `json:"name"`
		Description *string `json:"description"`
	}
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

// --- Product Types ---

func (h *ReferenceHandler) ListProductTypes(c *gin.Context) {
	var items []domain.ReferenceProductType
	if err := h.db.Order("name ASC").Find(&items).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: items})
}

func (h *ReferenceHandler) CreateProductType(c *gin.Context) {
	var req struct {
		Name string `json:"name" binding:"required"`
	}
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

// --- Locations ---

func displayForLocation(zone string, bay *string) string {
	if bay == nil || *bay == "" {
		return zone
	}
	return zone + " – " + *bay
}

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

func (h *ReferenceHandler) CreateLocation(c *gin.Context) {
	var req struct {
		Zone string  `json:"zone" binding:"required"`
		Bay  *string `json:"bay"`
	}
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

// --- Storage Locations ---

func (h *ReferenceHandler) ListStorageLocations(c *gin.Context) {
	var items []domain.ReferenceStorageLocation
	if err := h.db.Order("name ASC").Find(&items).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: items})
}

func (h *ReferenceHandler) CreateStorageLocation(c *gin.Context) {
	var req struct {
		Name string `json:"name" binding:"required"`
		Type string `json:"type"`
	}
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

// --- Step Types ---

func (h *ReferenceHandler) ListStepTypes(c *gin.Context) {
	var items []domain.ReferenceStepType
	if err := h.db.Order("name ASC").Find(&items).Error; err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: items})
}

func (h *ReferenceHandler) CreateStepType(c *gin.Context) {
	var req struct {
		Name               string  `json:"name" binding:"required"`
		DefaultMachineType *string `json:"default_machine_type"`
	}
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
