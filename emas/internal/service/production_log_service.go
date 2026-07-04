package service

import (
	"emas/internal/apperror"
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/pkg/id"
	"emas/pkg/productionexec"
	"encoding/json"
	"fmt"
	"time"

	"gorm.io/gorm"
)

type ProductionLogService struct {
	db             *gorm.DB
	logRepo        *repository.ProductionLogRepository
	slotRepo       *repository.JobSlotRepository
	stepRepo       *repository.JobStepRepository
	jobRepo        *repository.JobRepository
	proposalRepo   *repository.AIProposalRepository
	scheduling     *SchedulingService
	inventoryRepo  *repository.InventoryRepository
	wipRepo        *repository.WIPRepository
	psmRepo        *repository.ProcessStepMaterialRepository
	dependencyRepo *repository.JobDependencyRepository
}

func NewProductionLogService(
	db *gorm.DB,
	logRepo *repository.ProductionLogRepository,
	slotRepo *repository.JobSlotRepository,
	stepRepo *repository.JobStepRepository,
	jobRepo *repository.JobRepository,
	proposalRepo *repository.AIProposalRepository,
	scheduling *SchedulingService,
) *ProductionLogService {
	return &ProductionLogService{
		db:             db,
		logRepo:        logRepo,
		slotRepo:       slotRepo,
		stepRepo:       stepRepo,
		jobRepo:        jobRepo,
		proposalRepo:   proposalRepo,
		scheduling:     scheduling,
		inventoryRepo:  repository.NewInventoryRepository(db),
		wipRepo:        repository.NewWIPRepository(db),
		psmRepo:        repository.NewProcessStepMaterialRepository(db),
		dependencyRepo: repository.NewJobDependencyRepository(db),
	}
}

func (s *ProductionLogService) LogProduction(req dto.LogProductionRequest) (*domain.ProductionLogs, error) {
	var created *domain.ProductionLogs
	err := s.db.Transaction(func(tx *gorm.DB) error {
		var scheduling *SchedulingService
		if s.scheduling != nil {
			scheduling = s.scheduling.WithTransaction(tx)
		}
		txSvc := &ProductionLogService{
			db:             tx,
			logRepo:        repository.NewProductionLogRepository(tx),
			slotRepo:       repository.NewJobSlotRepository(tx),
			stepRepo:       repository.NewJobStepRepository(tx),
			jobRepo:        repository.NewJobRepository(tx),
			proposalRepo:   repository.NewAIProposalRepository(tx),
			scheduling:     scheduling,
			inventoryRepo:  repository.NewInventoryRepository(tx),
			wipRepo:        repository.NewWIPRepository(tx),
			psmRepo:        repository.NewProcessStepMaterialRepository(tx),
			dependencyRepo: repository.NewJobDependencyRepository(tx),
		}
		pl, err := txSvc.logProduction(req)
		if err != nil {
			return err
		}
		created = pl
		return nil
	})
	if err != nil {
		return nil, err
	}
	return created, nil
}

func (s *ProductionLogService) logProduction(req dto.LogProductionRequest) (*domain.ProductionLogs, error) {
	slot, err := s.slotRepo.GetByID(req.SlotID)
	if err != nil {
		return nil, err
	}
	pl, err := productionexec.LogProduction(s.db, productionexec.LogProductionRequest{
		SlotID:           req.SlotID,
		StartTime:        req.StartTime,
		EndTime:          req.EndTime,
		QuantityProduced: req.QuantityProduced,
		QuantityScrap:    req.QuantityScrap,
		OperatorNotes:    req.OperatorNotes,
		DowntimeMinutes:  req.DowntimeMinutes,
	}, productionexec.Options{
		StepResolver: s.resolveProcessStepID,
	})
	if err != nil {
		if productionexec.IsConflict(err) {
			return nil, apperror.Conflict(err.Error())
		}
		return nil, err
	}
	updatedSlot, err := s.slotRepo.GetByID(slot.SlotID)
	if err != nil {
		return nil, err
	}
	if updatedSlot.ProposalID != "" && s.proposalRepo != nil {
		if err := s.refreshProposalOutcome(updatedSlot.ProposalID); err != nil {
			return nil, err
		}
	}
	if s.scheduling != nil {
		if err := s.scheduling.CaptureMLTrainingEventForSlot(updatedSlot.SlotID); err != nil {
			return nil, err
		}
	}
	return pl, nil
}

func (s *ProductionLogService) resolveProcessStepID(jobStepID string) (string, error) {
	if s.scheduling == nil {
		step, err := s.stepRepo.GetByID(jobStepID)
		if err != nil || step == nil {
			return "", err
		}
		return step.StepID, nil
	}
	processStep, err := s.scheduling.GetProcessStepForJobStep(jobStepID)
	if err != nil || processStep == nil {
		return "", err
	}
	return processStep.StepID, nil
}

func (s *ProductionLogService) syncInventoryFromLog(slot *domain.JobStepScheduleSlots, step *domain.JobSteps, req dto.LogProductionRequest) error {
	if slot == nil || step == nil || s.psmRepo == nil || s.inventoryRepo == nil {
		return nil
	}
	processStepID := step.StepID
	if processStepID == "" {
		return nil
	}
	inputs, err := s.psmRepo.ListInputsByStepID(processStepID)
	if err != nil {
		return err
	}
	outputs, err := s.psmRepo.ListOutputsByStepID(processStepID)
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
			wipConsumed, err := s.consumeWIP(step.JobID, productID, required)
			if err != nil {
				return err
			}
			remaining := required - wipConsumed
			if remaining > 0 {
				if err := s.consumeProductInventory(step.JobID, step.JobStepID, productID, remaining); err != nil {
					return err
				}
				if err := s.consumePendingProductReservations(step.JobID, step.JobStepID, productID, remaining); err != nil {
					return err
				}
			}
			continue
		}
		if input.MaterialID != nil {
			if err := s.consumeMaterialStock(step.JobID, step.JobStepID, slot.SlotID, *input.MaterialID, required, req); err != nil {
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
		if s.outputStaysInWIP(step.JobID, step.StepSequence, productID) {
			if err := s.wipRepo.UpsertWIP(&domain.WIPInventory{
				ID:        id.NewPrefixed("WIP-"),
				JobStepID: step.JobStepID,
				ProductID: &productID,
				Quantity:  qty,
				Unit:      output.Unit,
				Location:  "WIP",
				UpdatedAt: time.Now().UTC(),
			}); err != nil {
				return err
			}
			continue
		}
		inventory := &domain.ProductInventory{
			InventoryID:      id.NewPrefixed("PINV-"),
			ProductID:        productID,
			QuantityOnHand:   qty,
			QuantityReserved: 0,
			Status:           domain.ProductInventoryStatusAvailable,
			StorageLocation:  "FG",
			AvailableFrom:    alignSuccessorStart(req.EndTime.UTC()),
			LastUpdated:      time.Now().UTC(),
		}
		if err := s.inventoryRepo.CreateProductInventory(inventory); err != nil {
			return err
		}
	}
	if req.QuantityProduced < slot.QuantityPlanned {
		if err := s.blockDependentConsumers(step.JobID, step.JobStepID); err != nil {
			return err
		}
	}
	return nil
}

func normalizeProductionLogRequest(req dto.LogProductionRequest, slot *domain.JobStepScheduleSlots) dto.LogProductionRequest {
	if req.StartTime.IsZero() && slot != nil {
		req.StartTime = slot.ScheduledStart
	}
	if req.EndTime.IsZero() && slot != nil {
		req.EndTime = slot.ScheduledEnd
	}
	return req
}

func (s *ProductionLogService) consumeMaterialStock(jobID, jobStepID, slotID, materialID string, qty float64, req dto.LogProductionRequest) error {
	if qty <= 0 {
		return nil
	}
	material, err := s.inventoryRepo.GetMaterialByIDForUpdate(materialID)
	if err != nil {
		return err
	}
	if material.CurrentStock+0.000001 < qty {
		return apperror.Conflict(fmt.Sprintf("insufficient stock for material %s: requested %.2f, available %.2f", materialID, qty, material.CurrentStock))
	}
	material.CurrentStock -= qty
	material.Status = productionMaterialStatus(material.CurrentStock, material.MinStock)
	material.LastUpdated = time.Now().UTC()
	if err := s.inventoryRepo.UpdateMaterial(material); err != nil {
		return err
	}
	ts := req.EndTime.UTC()
	if ts.IsZero() {
		ts = time.Now().UTC()
	}
	if err := s.inventoryRepo.CreateTransaction(&domain.InventoryTransactions{
		TransactionID:   id.NewPrefixed("TXN-"),
		MaterialID:      materialID,
		TransactionType: domain.TransactionTypeConsume,
		Quantity:        qty,
		ReferenceJobID:  jobID,
		Timestamp:       ts,
		Notes:           fmt.Sprintf("production log slot=%s job_step=%s", slotID, jobStepID),
	}); err != nil {
		return err
	}
	return s.consumePendingMaterialReservations(jobID, jobStepID, materialID, qty)
}

func productionMaterialStatus(currentStock, minStock float64) string {
	if currentStock <= 0 {
		return domain.InventoryStatusOutOfStock
	}
	if currentStock < minStock {
		return domain.InventoryStatusLowStock
	}
	return domain.InventoryStatusInStock
}

func (s *ProductionLogService) consumeWIP(jobID, productID string, qty float64) (float64, error) {
	if s.wipRepo == nil || qty <= 0 {
		return 0, nil
	}
	items, err := s.wipRepo.ListWIPByJobID(jobID)
	if err != nil {
		return 0, err
	}
	consumed := 0.0
	for _, item := range items {
		if item.ProductID == nil || *item.ProductID != productID || item.Quantity <= 0 {
			continue
		}
		available := item.Quantity
		used := mathMinFloat(available, qty-consumed)
		if used <= 0 {
			continue
		}
		item.Quantity -= used
		item.UpdatedAt = time.Now().UTC()
		if err := s.wipRepo.UpsertWIP(&item); err != nil {
			return consumed, err
		}
		consumed += used
		if consumed >= qty {
			break
		}
	}
	return consumed, nil
}

func (s *ProductionLogService) consumeProductInventory(jobID, jobStepID, productID string, qty float64) error {
	if s.inventoryRepo == nil || qty <= 0 {
		return nil
	}
	items, err := s.inventoryRepo.ListProductInventoryByProductID(productID)
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
		return apperror.Conflict(fmt.Sprintf("insufficient product inventory for %s: requested %.2f, available %.2f", productID, qty, available))
	}
	remaining := qty
	for _, item := range items {
		if remaining <= 0 {
			break
		}
		if item.Status != domain.ProductInventoryStatusAvailable || item.QuantityOnHand <= 0 {
			continue
		}
		used := mathMinFloat(item.QuantityOnHand, remaining)
		item.QuantityOnHand -= used
		item.LastUpdated = time.Now().UTC()
		if err := s.inventoryRepo.UpdateProductInventory(&item); err != nil {
			return err
		}
		remaining -= used
	}
	_ = jobID
	_ = jobStepID
	return nil
}

func (s *ProductionLogService) consumePendingMaterialReservations(jobID, jobStepID, materialID string, qty float64) error {
	reservations, err := s.inventoryRepo.ListReservations(materialID, domain.InventoryReservationStatusPending)
	if err != nil {
		return err
	}
	return s.consumeMaterialReservations(reservations, jobID, jobStepID, qty)
}

func (s *ProductionLogService) consumeMaterialReservations(reservations []domain.InventoryReservation, jobID, jobStepID string, qty float64) error {
	remaining := qty
	for _, reservation := range reservations {
		if remaining <= 0 {
			break
		}
		if reservation.JobID != jobID || reservation.JobStepID != jobStepID || reservation.ReservedQty <= 0 {
			continue
		}
		used := mathMinFloat(reservation.ReservedQty, remaining)
		reservation.ReservedQty -= used
		reservation.UpdatedAt = time.Now().UTC()
		if reservation.ReservedQty <= 0 {
			reservation.Status = domain.InventoryReservationStatusConsumed
		}
		if err := s.inventoryRepo.UpdateReservation(&reservation); err != nil {
			return err
		}
		remaining -= used
	}
	return nil
}

func (s *ProductionLogService) consumePendingProductReservations(jobID, jobStepID, productID string, qty float64) error {
	reservations, err := s.inventoryRepo.ListProductReservations(productID, domain.InventoryReservationStatusPending)
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
		used := mathMinFloat(reservation.ReservedQty, remaining)
		reservation.ReservedQty -= used
		reservation.UpdatedAt = time.Now().UTC()
		if reservation.ReservedQty <= 0 {
			reservation.Status = domain.InventoryReservationStatusConsumed
		}
		if err := s.inventoryRepo.UpdateProductReservation(&reservation); err != nil {
			return err
		}
		remaining -= used
	}
	return nil
}

func (s *ProductionLogService) outputStaysInWIP(jobID string, currentSequence int, productID string) bool {
	steps, err := s.stepRepo.ListByJobID(jobID)
	if err != nil {
		return false
	}
	for _, step := range steps {
		if step.StepSequence <= currentSequence {
			continue
		}
		stepID := step.StepID
		if s.scheduling != nil {
			processStep, err := s.scheduling.GetProcessStepForJobStep(step.JobStepID)
			if err == nil && processStep != nil && processStep.StepID != "" {
				stepID = processStep.StepID
			}
		}
		if stepID == "" {
			continue
		}
		inputs, err := s.psmRepo.ListInputsByStepID(stepID)
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

func (s *ProductionLogService) refreshSlotExecution(slot *domain.JobStepScheduleSlots) error {
	logs, err := s.logRepo.ListBySlotID(slot.SlotID)
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
	return s.slotRepo.Update(slot)
}

func (s *ProductionLogService) refreshStepExecution(step *domain.JobSteps) error {
	slots, err := s.slotRepo.ListByJobStepID(step.JobStepID)
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
		logs, err := s.logRepo.ListBySlotID(slot.SlotID)
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
	return s.stepRepo.Update(step)
}

func (s *ProductionLogService) refreshJobExecution(jobID string) error {
	job, err := s.jobRepo.GetByID(jobID)
	if err != nil {
		return err
	}
	steps, err := s.stepRepo.ListByJobID(jobID)
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
	job.UpdatedAt = time.Now().UTC()
	return s.jobRepo.Update(job)
}

func (s *ProductionLogService) blockDependentConsumers(parentJobID, parentJobStepID string) error {
	if s.dependencyRepo == nil {
		return nil
	}
	deps, err := s.dependencyRepo.ListByConsumerJobStepID(parentJobStepID)
	if err != nil || len(deps) == 0 {
		deps, err = s.dependencyRepo.ListByParentJobID(parentJobID)
		if err != nil {
			return err
		}
	}
	for _, dep := range deps {
		step, err := s.stepRepo.GetByID(dep.ConsumerJobStepID)
		if err == nil && step != nil {
			step.Status = domain.JobStepStatusBlocked
			if err := s.stepRepo.Update(step); err != nil {
				return err
			}
			job, jobErr := s.jobRepo.GetByID(step.JobID)
			if jobErr == nil && job != nil {
				job.Status = domain.JobStatusBlocked
				job.UpdatedAt = time.Now().UTC()
				job.Notes = schedulerNoteAppend(job.Notes, "reason_code="+reasonCodeInsufficientOutput)
				if err := s.jobRepo.Update(job); err != nil {
					return err
				}
			}
		} else if err != nil {
			return err
		}
	}
	return nil
}

func mathMinFloat(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

func (s *ProductionLogService) refreshProposalOutcome(proposalID string) error {
	proposal, err := s.proposalRepo.GetByID(proposalID)
	if err != nil {
		return err
	}
	slots, err := s.slotRepo.ListByProposalID(proposalID)
	if err != nil || len(slots) == 0 {
		return err
	}
	totalProduced := 0
	totalScrap := 0
	completedSlots := 0
	var actualCompletion *time.Time
	for _, slot := range slots {
		logs, err := s.logRepo.ListBySlotID(slot.SlotID)
		if err != nil {
			return err
		}
		for _, log := range logs {
			totalProduced += log.QuantityProduced
			totalScrap += log.QuantityScrap
			if actualCompletion == nil || log.EndTime.After(*actualCompletion) {
				end := log.EndTime
				actualCompletion = &end
			}
		}
		if slot.Status == domain.SlotStatusCompleted {
			completedSlots++
		}
	}
	outcome := map[string]interface{}{
		"proposal_id":          proposalID,
		"completed_slots":      completedSlots,
		"total_slots":          len(slots),
		"quantity_produced":    totalProduced,
		"quantity_scrap":       totalScrap,
		"actual_completion_at": actualCompletion,
	}
	estimateDeviation := 0
	if proposal.EstimatedCompletionAt != nil && actualCompletion != nil {
		estimateDeviation = int(actualCompletion.Sub(*proposal.EstimatedCompletionAt).Minutes())
		outcome["estimate_deviation_mins"] = estimateDeviation
	}
	raw, err := json.Marshal(outcome)
	if err != nil {
		return err
	}
	now := time.Now().UTC()
	proposal.OutcomeJSON = string(raw)
	proposal.ActualProducedQty = totalProduced
	proposal.ActualScrapQty = totalScrap
	proposal.ActualCompletionAt = actualCompletion
	proposal.EstimateDeviationMins = estimateDeviation
	if completedSlots >= len(slots) && len(slots) > 0 {
		proposal.OutcomeStatus = "completed"
	} else {
		proposal.OutcomeStatus = "in_progress"
	}
	proposal.LastOutcomeRecordedAt = &now
	proposal.UpdatedAt = now
	return s.proposalRepo.Update(proposal)
}
