package handler

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/internal/service"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

type InventoryHandler struct {
	inventoryService *service.InventoryService
}

func NewInventoryHandler(inventoryService *service.InventoryService) *InventoryHandler {
	return &InventoryHandler{inventoryService: inventoryService}
}

// @Summary Create a material
// @Description Create a material. material_id is generated with the MAT- prefix when omitted.
// @Tags inventory
// @Accept json
// @Produce json
// @Param request body dto.CreateMaterialRequest true "Create Material Request"
// @Success 201 {object} dto.Response{data=domain.InventoryMaterials}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /inventory/materials [post]
func (h *InventoryHandler) CreateMaterial(c *gin.Context) {
	var req dto.CreateMaterialRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	m, err := h.inventoryService.CreateMaterial(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: m})
}

// @Summary Consume a material
// @Description Consume a material
// @Tags inventory
// @Accept json
// @Produce json
// @Param request body dto.ConsumeMaterialRequest true "Consume Material Request"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /inventory/consume [post]
func (h *InventoryHandler) Consume(c *gin.Context) {
	var req dto.ConsumeMaterialRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	if err := h.inventoryService.ConsumeMaterial(req); err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true})
}

// @Summary Receive a material
// @Description Receive a material
// @Tags inventory
// @Accept json
// @Produce json
// @Param request body dto.ReceiveMaterialRequest true "Receive Material Request"
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /inventory/receive [post]
func (h *InventoryHandler) Receive(c *gin.Context) {
	var req dto.ReceiveMaterialRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	if err := h.inventoryService.ReceiveMaterial(req); err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true})
}

// @Summary Get a material by ID
// @Description Get a material by ID. Supports optional field selection.
// @Tags inventory
// @Accept json
// @Produce json
// @Param id path string true "Material ID"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=domain.InventoryMaterials}
// @Failure 404 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /inventory/materials/{id} [get]
func (h *InventoryHandler) GetMaterial(c *gin.Context) {
	id := c.Param("id")
	m, err := h.inventoryService.GetMaterial(id)
	if err != nil {
		c.JSON(http.StatusNotFound, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: m})
}

// @Summary List materials
// @Description List materials
// @Tags inventory
// @Accept json
// @Produce json
// @Param status query string false "Filter by status" Enums(in_stock,low_stock,out_of_stock)
// @Param q query string false "Search material name"
// @Param sort_by query string false "Field to sort by" Enums(material_name,current_stock,last_updated)
// @Param sort_dir query string false "Sort direction" Enums(asc,desc)
// @Param limit query int false "Limit number of results"
// @Param offset query int false "Offset for pagination"
// @Success 200 {object} dto.Response{data=[]domain.InventoryMaterials}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /inventory/materials [get]
func (h *InventoryHandler) ListMaterials(c *gin.Context) {
	var query dto.InventoryMaterialsListQuery
	if err := c.ShouldBindQuery(&query); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	var f repository.InventoryListFilter
	f.Status = string(query.Status)
	f.NameLike = query.Q
	f.SortBy = query.SortBy
	f.SortDir = string(query.SortDir)
	f.Limit = query.Limit
	f.Offset = query.Offset
	if f.SortBy == "" {
		f.SortBy = "material_name"
	}
	if f.SortDir == "" {
		f.SortDir = "asc"
	}

	materials, err := h.inventoryService.ListMaterialsFiltered(f)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: materials})
}

// @Summary Schedule an expected arrival
// @Description Schedule an expected arrival
// @Tags inventory
// @Accept json
// @Produce json
// @Param request body dto.ScheduleExpectedArrivalRequest true "Schedule Expected Arrival Request"
// @Success 201 {object} dto.Response{data=domain.InventoryExpectedArrival}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /inventory/expected-arrivals [post]
func (h *InventoryHandler) ScheduleExpectedArrival(c *gin.Context) {
	var req dto.ScheduleExpectedArrivalRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	a, err := h.inventoryService.ScheduleExpectedArrival(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: a})
}

// @Summary List expected arrivals
// @Description List expected arrivals
// @Tags inventory
// @Accept json
// @Produce json
// @Param material_id query string false "Filter by material ID"
// @Param status query string false "Filter by status" Enums(pending,received,cancelled)
// @Param from query string false "RFC3339 start"
// @Param to query string false "RFC3339 end"
// @Success 200 {object} dto.Response{data=[]domain.InventoryExpectedArrival}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /inventory/expected-arrivals [get]
func (h *InventoryHandler) ListExpectedArrivals(c *gin.Context) {
	var query dto.ExpectedArrivalListQuery
	if err := c.ShouldBindQuery(&query); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	materialID := query.MaterialID
	status := string(query.Status)
	if status == "" {
		status = domain.ExpectedArrivalStatusPending
	}
	var from, to *time.Time
	if v := query.From; v != "" {
		if t, err := time.Parse(time.RFC3339, v); err == nil {
			from = &t
		}
	}
	if v := query.To; v != "" {
		if t, err := time.Parse(time.RFC3339, v); err == nil {
			to = &t
		}
	}
	list, err := h.inventoryService.ListExpectedArrivals(materialID, status, from, to)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: list})
}

// @Summary Create a product inventory
// @Description Create a product inventory
// @Tags inventory
// @Accept json
// @Produce json
// @Param request body dto.CreateProductInventoryRequest true "Create Product Inventory Request"
// @Success 201 {object} dto.Response{data=domain.ProductInventory}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /inventory/product-stock [post]
func (h *InventoryHandler) CreateProductInventory(c *gin.Context) {
	var req dto.CreateProductInventoryRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	inv, err := h.inventoryService.CreateProductInventory(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: inv})
}

// @Summary List product inventory
// @Description List product inventory
// @Tags inventory
// @Accept json
// @Produce json
// @Param product_id query string false "Filter by product ID"
// @Param status query string false "Filter by status" Enums(available,reserved,blocked,planned)
// @Param sort_by query string false "Field to sort by" Enums(product_id,available_from,last_updated,quantity_on_hand,quantity_reserved,status)
// @Param sort_dir query string false "Sort direction (asc, desc)" Enums(asc,desc)
// @Param limit query int false "Limit number of results"
// @Param offset query int false "Offset for pagination"
// @Param fields query string false "Comma-separated fields to return"
// @Success 200 {object} dto.Response{data=[]domain.ProductInventory}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /inventory/product-stock [get]
func (h *InventoryHandler) ListProductInventory(c *gin.Context) {
	var query dto.ProductInventoryListQuery
	if err := c.ShouldBindQuery(&query); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	var f repository.ProductInventoryListFilter
	f.ProductID = query.ProductID
	f.Status = string(query.Status)
	f.SortBy = query.SortBy
	f.SortDir = string(query.SortDir)
	f.Fields = query.Fields
	f.Limit = query.Limit
	f.Offset = query.Offset
	if f.SortBy == "" {
		f.SortBy = "product_id"
	}
	if f.SortDir == "" {
		f.SortDir = "asc"
	}

	list, err := h.inventoryService.ListProductInventoryFiltered(f)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: list})
}

// @Summary Create a reservation
// @Description Create a reservation
// @Tags inventory
// @Accept json
// @Produce json
// @Param request body dto.CreateInventoryReservationRequest true "Create Reservation Request"
// @Success 201 {object} dto.Response{data=domain.InventoryReservation}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /inventory/reservations [post]
func (h *InventoryHandler) CreateReservation(c *gin.Context) {
	var req dto.CreateInventoryReservationRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	res, err := h.inventoryService.CreateReservation(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusCreated, dto.Response{Success: true, Data: res})
}

func (h *InventoryHandler) ListReservations(c *gin.Context) {
	var query dto.InventoryReservationListQuery
	if err := c.ShouldBindQuery(&query); err != nil {
		c.JSON(http.StatusBadRequest, dto.Response{Success: false, Error: err.Error()})
		return
	}
	materialID := query.MaterialID
	status := string(query.Status)
	if status == "" {
		status = domain.InventoryReservationStatusPending
	}
	list, err := h.inventoryService.ListReservations(materialID, status)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: list})
}
