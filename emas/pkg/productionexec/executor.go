package productionexec

import (
	"emas/internal/domain"
	"emas/internal/repository"
	"emas/pkg/id"
	"errors"
	"fmt"
	"strings"
	"time"

	"gorm.io/gorm"
)

type LogProductionRequest struct {
	SlotID           string
	StartTime        time.Time
	EndTime          time.Time
	QuantityProduced int
	QuantityScrap    int
	OperatorNotes    string
	DowntimeMinutes  *int
}

type Options struct {
	ProductionID           string
	ProductStorageLocation string
	Now                    func() time.Time
	StepResolver           func(jobStepID string) (string, error)
	TransactionID          func(slotID, jobStepID, materialID string) string
	ProductInventoryID     func(slotID, productID string) string
	WIPID                  func(slotID, productID string) string
	ConsumeNotes           func(slotID, jobStepID, materialID string) string
}

type ConflictError struct {
	Message string
}

func (e *ConflictError) Error() string {
	if e == nil {
		return ""
	}
	return e.Message
}

func IsConflict(err error) bool {
	var conflict *ConflictError
	return errors.As(err, &conflict)
}

type Executor struct {
	db             *gorm.DB
	opts           Options
	logRepo        *repository.ProductionLogRepository
	slotRepo       *repository.JobSlotRepository
	stepRepo       *repository.JobStepRepository
	jobRepo        *repository.JobRepository
	inventoryRepo  *repository.InventoryRepository
	wipRepo        *repository.WIPRepository
	psmRepo        *repository.ProcessStepMaterialRepository
	dependencyRepo *repository.JobDependencyRepository
}

func LogProduction(db *gorm.DB, req LogProductionRequest, opts Options) (*domain.ProductionLogs, error) {
	exec := New(db, opts)
	return exec.LogProduction(req)
}

func New(db *gorm.DB, opts Options) *Executor {
	return &Executor{
		db:             db,
		opts:           opts.withDefaults(),
		logRepo:        repository.NewProductionLogRepository(db),
		slotRepo:       repository.NewJobSlotRepository(db),
		stepRepo:       repository.NewJobStepRepository(db),
		jobRepo:        repository.NewJobRepository(db),
		inventoryRepo:  repository.NewInventoryRepository(db),
		wipRepo:        repository.NewWIPRepository(db),
		psmRepo:        repository.NewProcessStepMaterialRepository(db),
		dependencyRepo: repository.NewJobDependencyRepository(db),
	}
}

func (opts Options) withDefaults() Options {
	if opts.ProductStorageLocation == "" {
		opts.ProductStorageLocation = "FG"
	}
	if opts.Now == nil {
		opts.Now = func() time.Time { return time.Now().UTC() }
	}
	if opts.TransactionID == nil {
		opts.TransactionID = func(_, _, _ string) string { return id.NewPrefixed("TXN-") }
	}
	if opts.ProductInventoryID == nil {
		opts.ProductInventoryID = func(_, _ string) string { return id.NewPrefixed("PINV-") }
	}
	if opts.WIPID == nil {
		opts.WIPID = func(_, _ string) string { return id.NewPrefixed("WIP-") }
	}
	if opts.ConsumeNotes == nil {
		opts.ConsumeNotes = func(slotID, jobStepID, _ string) string {
			return fmt.Sprintf("production log slot=%s job_step=%s", slotID, jobStepID)
		}
	}
	return opts
}

func (e *Executor) LogProduction(req LogProductionRequest) (*domain.ProductionLogs, error) {
	slot, err := e.slotRepo.GetByID(req.SlotID)
	if err != nil {
		return nil, err
	}
	step, err := e.stepRepo.GetByID(slot.JobStepID)
	if err != nil {
		return nil, err
	}
	req = normalizeRequest(req, slot)

	productionID := e.opts.ProductionID
	if productionID == "" {
		productionID = id.NewPrefixed("PL-")
	}
	pl := &domain.ProductionLogs{
		ProductionID:     productionID,
		SlotID:           req.SlotID,
		StartTime:        req.StartTime,
		EndTime:          req.EndTime,
		QuantityProduced: req.QuantityProduced,
		QuantityScrap:    req.QuantityScrap,
		OperatorNotes:    req.OperatorNotes,
		DowntimeMinutes:  req.DowntimeMinutes,
	}
	if err := e.logRepo.Create(pl); err != nil {
		return nil, err
	}
	if err := e.syncInventoryFromLog(slot, step, req); err != nil {
		return nil, err
	}
	if err := e.refreshSlotExecution(slot); err != nil {
		return nil, err
	}
	if err := e.refreshStepExecution(step); err != nil {
		return nil, err
	}
	if err := e.refreshJobExecution(step.JobID); err != nil {
		return nil, err
	}
	return pl, nil
}

func normalizeRequest(req LogProductionRequest, slot *domain.JobStepScheduleSlots) LogProductionRequest {
	if req.StartTime.IsZero() && slot != nil {
		req.StartTime = slot.ScheduledStart
	}
	if req.EndTime.IsZero() && slot != nil {
		req.EndTime = slot.ScheduledEnd
	}
	return req
}

func (e *Executor) syncInventoryFromLog(slot *domain.JobStepScheduleSlots, step *domain.JobSteps, req LogProductionRequest) error {
	if slot == nil || step == nil {
		return nil
	}
	processStepID, err := e.resolveStepID(step)
	if err != nil || processStepID == "" {
		return err
	}
	inputs, err := e.psmRepo.ListInputsByStepID(processStepID)
	if err != nil {
		return err
	}
	outputs, err := e.psmRepo.ListOutputsByStepID(processStepID)
	if err != nil {
		return err
	}
	inputUnits := float64(req.QuantityProduced + req.QuantityScrap)
	outputUnits := float64(req.QuantityProduced)

	for _, input := range inputs {
		required := inputUnits * input.QuantityPerUnit
		if required <= 0 {
			continue
		}
		if input.ProductID != nil {
			productID := *input.ProductID
			wipConsumed, err := e.consumeWIP(step.JobID, productID, required)
			if err != nil {
				return err
			}
			remaining := required - wipConsumed
			if remaining > 0 {
				if err := e.consumeProductInventory(productID, remaining); err != nil {
					return err
				}
				if err := e.consumePendingProductReservations(step.JobID, step.JobStepID, productID, remaining); err != nil {
					return err
				}
			}
			continue
		}
		if input.MaterialID != nil {
			if err := e.consumeMaterialStock(step.JobID, step.JobStepID, slot.SlotID, *input.MaterialID, required, req); err != nil {
				return err
			}
		}
	}

	for _, output := range outputs {
		if output.ProductID == nil {
			continue
		}
		productID := *output.ProductID
		qty := outputUnits * output.QuantityPerUnit
		if qty <= 0 {
			continue
		}
		if e.outputStaysInWIP(step.JobID, step.StepSequence, productID) {
			if err := e.wipRepo.UpsertWIP(&domain.WIPInventory{
				ID:        e.opts.WIPID(slot.SlotID, productID),
				JobStepID: step.JobStepID,
				ProductID: &productID,
				Quantity:  qty,
				Unit:      output.Unit,
				Location:  "WIP",
				UpdatedAt: e.opts.Now(),
			}); err != nil {
				return err
			}
			continue
		}
		inventory := &domain.ProductInventory{
			InventoryID:      e.opts.ProductInventoryID(slot.SlotID, productID),
			ProductID:        productID,
			QuantityOnHand:   qty,
			QuantityReserved: 0,
			Status:           domain.ProductInventoryStatusAvailable,
			StorageLocation:  e.opts.ProductStorageLocation,
			AvailableFrom:    alignAvailableFrom(req.EndTime.UTC()),
			LastUpdated:      e.opts.Now(),
		}
		if err := e.inventoryRepo.CreateProductInventory(inventory); err != nil {
			return err
		}
	}
	if req.QuantityProduced < slot.QuantityPlanned {
		if err := e.blockDependentConsumers(step.JobID, step.JobStepID); err != nil {
			return err
		}
	}
	return nil
}

func (e *Executor) resolveStepID(step *domain.JobSteps) (string, error) {
	if step.StepID != "" {
		return step.StepID, nil
	}
	if e.opts.StepResolver == nil {
		return "", nil
	}
	return e.opts.StepResolver(step.JobStepID)
}

func (e *Executor) consumeMaterialStock(jobID, jobStepID, slotID, materialID string, qty float64, req LogProductionRequest) error {
	if qty <= 0 {
		return nil
	}
	material, err := e.inventoryRepo.GetMaterialByIDForUpdate(materialID)
	if err != nil {
		return err
	}
	if material.CurrentStock+0.000001 < qty {
		return &ConflictError{Message: fmt.Sprintf("insufficient stock for material %s: requested %.2f, available %.2f", materialID, qty, material.CurrentStock)}
	}
	material.CurrentStock -= qty
	material.Status = materialStatus(material.CurrentStock, material.MinStock)
	material.LastUpdated = e.opts.Now()
	if err := e.inventoryRepo.UpdateMaterial(material); err != nil {
		return err
	}
	ts := req.EndTime.UTC()
	if ts.IsZero() {
		ts = e.opts.Now()
	}
	if err := e.inventoryRepo.CreateTransaction(&domain.InventoryTransactions{
		TransactionID:   e.opts.TransactionID(slotID, jobStepID, materialID),
		MaterialID:      materialID,
		TransactionType: domain.TransactionTypeConsume,
		Quantity:        qty,
		ReferenceJobID:  jobID,
		Timestamp:       ts,
		Notes:           e.opts.ConsumeNotes(slotID, jobStepID, materialID),
	}); err != nil {
		return err
	}
	return e.consumePendingMaterialReservations(jobID, jobStepID, materialID, qty)
}

func materialStatus(currentStock, minStock float64) string {
	if currentStock <= 0 {
		return domain.InventoryStatusOutOfStock
	}
	if currentStock < minStock {
		return domain.InventoryStatusLowStock
	}
	return domain.InventoryStatusInStock
}

func (e *Executor) consumeWIP(jobID, productID string, qty float64) (float64, error) {
	if qty <= 0 {
		return 0, nil
	}
	items, err := e.wipRepo.ListWIPByJobID(jobID)
	if err != nil {
		return 0, err
	}
	consumed := 0.0
	for _, item := range items {
		if item.ProductID == nil || *item.ProductID != productID || item.Quantity <= 0 {
			continue
		}
		used := minFloat(item.Quantity, qty-consumed)
		if used <= 0 {
			continue
		}
		item.Quantity -= used
		item.UpdatedAt = e.opts.Now()
		if err := e.wipRepo.UpsertWIP(&item); err != nil {
			return consumed, err
		}
		consumed += used
		if consumed >= qty {
			break
		}
	}
	return consumed, nil
}

func (e *Executor) consumeProductInventory(productID string, qty float64) error {
	if qty <= 0 {
		return nil
	}
	items, err := e.inventoryRepo.ListProductInventoryByProductID(productID)
	if err != nil {
		return err
	}
	available := 0.0
	for _, item := range items {
		if item.Status == domain.ProductInventoryStatusAvailable && item.QuantityOnHand > 0 {
			available += item.QuantityOnHand
		}
	}
	if available+0.000001 < qty {
		return &ConflictError{Message: fmt.Sprintf("insufficient product inventory for %s: requested %.2f, available %.2f", productID, qty, available)}
	}
	remaining := qty
	for _, item := range items {
		if remaining <= 0 {
			break
		}
		if item.Status != domain.ProductInventoryStatusAvailable || item.QuantityOnHand <= 0 {
			continue
		}
		used := minFloat(item.QuantityOnHand, remaining)
		item.QuantityOnHand -= used
		item.LastUpdated = e.opts.Now()
		if err := e.inventoryRepo.UpdateProductInventory(&item); err != nil {
			return err
		}
		remaining -= used
	}
	return nil
}

func (e *Executor) consumePendingMaterialReservations(jobID, jobStepID, materialID string, qty float64) error {
	reservations, err := e.inventoryRepo.ListReservations(materialID, domain.InventoryReservationStatusPending)
	if err != nil {
		return err
	}
	remaining := qty
	for _, reservation := range reservations {
		if remaining <= 0 {
			break
		}
		if reservation.JobID != jobID || reservation.JobStepID != jobStepID || reservation.ReservedQty <= 0 {
			continue
		}
		used := minFloat(reservation.ReservedQty, remaining)
		reservation.ReservedQty -= used
		reservation.UpdatedAt = e.opts.Now()
		if reservation.ReservedQty <= 0 {
			reservation.Status = domain.InventoryReservationStatusConsumed
		}
		if err := e.inventoryRepo.UpdateReservation(&reservation); err != nil {
			return err
		}
		remaining -= used
	}
	return nil
}

func (e *Executor) consumePendingProductReservations(jobID, jobStepID, productID string, qty float64) error {
	reservations, err := e.inventoryRepo.ListProductReservations(productID, domain.InventoryReservationStatusPending)
	if err != nil {
		return err
	}
	remaining := qty
	for _, reservation := range reservations {
		if remaining <= 0 {
			break
		}
		if reservation.JobID != jobID || reservation.JobStepID != jobStepID || reservation.ReservedQty <= 0 {
			continue
		}
		used := minFloat(reservation.ReservedQty, remaining)
		reservation.ReservedQty -= used
		reservation.UpdatedAt = e.opts.Now()
		if reservation.ReservedQty <= 0 {
			reservation.Status = domain.InventoryReservationStatusConsumed
		}
		if err := e.inventoryRepo.UpdateProductReservation(&reservation); err != nil {
			return err
		}
		remaining -= used
	}
	return nil
}

func (e *Executor) outputStaysInWIP(jobID string, currentSequence int, productID string) bool {
	steps, err := e.stepRepo.ListByJobID(jobID)
	if err != nil {
		return false
	}
	for _, step := range steps {
		if step.StepSequence <= currentSequence {
			continue
		}
		stepID := step.StepID
		if e.opts.StepResolver != nil {
			resolved, err := e.opts.StepResolver(step.JobStepID)
			if err == nil && resolved != "" {
				stepID = resolved
			}
		}
		if stepID == "" {
			continue
		}
		inputs, err := e.psmRepo.ListInputsByStepID(stepID)
		if err != nil {
			continue
		}
		for _, input := range inputs {
			if input.ProductID != nil && *input.ProductID == productID {
				return true
			}
		}
	}
	return false
}

func (e *Executor) refreshSlotExecution(slot *domain.JobStepScheduleSlots) error {
	logs, err := e.logRepo.ListBySlotID(slot.SlotID)
	if err != nil {
		return err
	}
	totalAccounted := 0
	var actualStart *time.Time
	var actualEnd *time.Time
	for _, log := range logs {
		totalAccounted += log.QuantityProduced + log.QuantityScrap
		if !log.StartTime.IsZero() && (actualStart == nil || log.StartTime.Before(*actualStart)) {
			t := log.StartTime
			actualStart = &t
		}
		if !log.EndTime.IsZero() && (actualEnd == nil || log.EndTime.After(*actualEnd)) {
			t := log.EndTime
			actualEnd = &t
		}
	}
	if totalAccounted > 0 {
		slot.ActualStart = actualStart
		slot.ActualEnd = actualEnd
		if totalAccounted >= slot.QuantityPlanned {
			slot.Status = domain.SlotStatusCompleted
		} else {
			slot.Status = domain.SlotStatusRunning
		}
	}
	return e.slotRepo.Update(slot)
}

func (e *Executor) refreshStepExecution(step *domain.JobSteps) error {
	slots, err := e.slotRepo.ListByJobStepID(step.JobStepID)
	if err != nil {
		return err
	}
	totalProduced := 0
	totalAccounted := 0
	totalPlanned := 0
	for _, slot := range slots {
		if slot.Status == domain.SlotStatusCancelled {
			continue
		}
		totalPlanned += slot.QuantityPlanned
		logs, err := e.logRepo.ListBySlotID(slot.SlotID)
		if err != nil {
			return err
		}
		for _, log := range logs {
			totalProduced += log.QuantityProduced
			totalAccounted += log.QuantityProduced + log.QuantityScrap
		}
	}
	step.QuantityCompleted = minInt(totalProduced, step.QuantityTarget)
	switch {
	case step.QuantityCompleted >= step.QuantityTarget && step.QuantityTarget > 0:
		step.Status = domain.JobStepStatusCompleted
	case totalPlanned > 0 && totalAccounted >= totalPlanned:
		step.Status = domain.JobStepStatusBlocked
	case totalAccounted > 0:
		step.Status = domain.JobStepStatusRunning
	}
	return e.stepRepo.Update(step)
}

func (e *Executor) refreshJobExecution(jobID string) error {
	job, err := e.jobRepo.GetByID(jobID)
	if err != nil {
		return err
	}
	steps, err := e.stepRepo.ListByJobID(jobID)
	if err != nil {
		return err
	}
	if len(steps) == 0 {
		return nil
	}
	minCompleted := steps[0].QuantityCompleted
	allCompleted := true
	anyBlocked := false
	anyProgress := false
	for _, step := range steps {
		if step.QuantityCompleted < minCompleted {
			minCompleted = step.QuantityCompleted
		}
		if step.Status != domain.JobStepStatusCompleted {
			allCompleted = false
		}
		if step.Status == domain.JobStepStatusBlocked {
			anyBlocked = true
		}
		if step.QuantityCompleted > 0 || step.Status == domain.JobStepStatusRunning {
			anyProgress = true
		}
	}
	job.QuantityCompleted = minInt(minCompleted, job.QuantityTotal)
	if job.QuantityCompleted < 0 {
		job.QuantityCompleted = 0
	}
	switch {
	case allCompleted && job.QuantityCompleted >= job.QuantityTotal && job.QuantityTotal > 0:
		job.Status = domain.JobStatusCompleted
	case anyBlocked:
		job.Status = domain.JobStatusBlocked
	case anyProgress:
		job.Status = domain.JobStatusRunning
	}
	job.UpdatedAt = e.opts.Now()
	return e.jobRepo.Update(job)
}

func (e *Executor) blockDependentConsumers(parentJobID, parentJobStepID string) error {
	deps, err := e.dependencyRepo.ListByConsumerJobStepID(parentJobStepID)
	if err != nil || len(deps) == 0 {
		deps, err = e.dependencyRepo.ListByParentJobID(parentJobID)
		if err != nil {
			return err
		}
	}
	for _, dep := range deps {
		step, err := e.stepRepo.GetByID(dep.ConsumerJobStepID)
		if err != nil {
			return err
		}
		if step == nil {
			continue
		}
		step.Status = domain.JobStepStatusBlocked
		if err := e.stepRepo.Update(step); err != nil {
			return err
		}
		job, jobErr := e.jobRepo.GetByID(step.JobID)
		if jobErr == nil && job != nil {
			job.Status = domain.JobStatusBlocked
			job.UpdatedAt = e.opts.Now()
			job.Notes = noteAppend(job.Notes, "reason_code=insufficient_production_output")
			if err := e.jobRepo.Update(job); err != nil {
				return err
			}
		}
	}
	return nil
}

func alignAvailableFrom(ts time.Time) time.Time {
	if ts.IsZero() {
		return ts
	}
	base := ts.Truncate(30 * time.Minute)
	if base.Equal(ts) {
		return ts
	}
	return base.Add(30 * time.Minute)
}

func noteAppend(existing, note string) string {
	existing = strings.TrimSpace(existing)
	if existing == "" {
		return note
	}
	return existing + "\n" + note
}

func minFloat(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
