package service

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/pkg/id"
	"encoding/json"
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
	pl := &domain.ProductionLogs{
		ProductionID:     id.NewPrefixed("PL-"),
		SlotID:           req.SlotID,
		StartTime:        req.StartTime,
		EndTime:          req.EndTime,
		QuantityProduced: req.QuantityProduced,
		QuantityScrap:    req.QuantityScrap,
		OperatorNotes:    req.OperatorNotes,
		DowntimeMinutes:  req.DowntimeMinutes,
	}
	if err := s.logRepo.Create(pl); err != nil {
		return nil, err
	}
	slot, _ := s.slotRepo.GetByID(req.SlotID)
	if slot != nil {
		step, _ := s.stepRepo.GetByID(slot.JobStepID)
		if step != nil {
			_ = s.syncInventoryFromLog(slot, step, req)
			step.QuantityCompleted += req.QuantityProduced
			if step.QuantityCompleted >= step.QuantityTarget {
				step.Status = domain.JobStepStatusCompleted
			} else if req.QuantityProduced+req.QuantityScrap < slot.QuantityPlanned {
				step.Status = domain.JobStepStatusBlocked
			} else if step.QuantityCompleted > 0 {
				step.Status = domain.JobStepStatusRunning
			}
			_ = s.stepRepo.Update(step)
			job, _ := s.jobRepo.GetByID(step.JobID)
			if job != nil {
				job.QuantityCompleted += req.QuantityProduced
				if job.QuantityCompleted >= job.QuantityTotal {
					job.Status = domain.JobStatusCompleted
				} else if req.QuantityProduced+req.QuantityScrap < slot.QuantityPlanned {
					job.Status = domain.JobStatusBlocked
				} else if job.QuantityCompleted > 0 {
					job.Status = domain.JobStatusRunning
				}
				_ = s.jobRepo.Update(job)
			}
		}
		totalProduced, _ := s.logRepo.SumProducedBySlotID(req.SlotID)
		if totalProduced >= slot.QuantityPlanned {
			slot.Status = domain.SlotStatusCompleted
		} else {
			slot.Status = domain.SlotStatusRunning
		}
		_ = s.slotRepo.Update(slot)
		if slot.ProposalID != "" && s.proposalRepo != nil {
			s.refreshProposalOutcome(slot.ProposalID)
		}
		if s.scheduling != nil {
			_ = s.scheduling.CaptureMLTrainingEventForSlot(slot.SlotID)
		}
	}
	return pl, nil
}

func (s *ProductionLogService) syncInventoryFromLog(slot *domain.JobStepScheduleSlots, step *domain.JobSteps, req dto.LogProductionRequest) error {
	if slot == nil || step == nil || s.psmRepo == nil || s.inventoryRepo == nil {
		return nil
	}
	processStep, err := s.scheduling.GetProcessStepForJobStep(step.JobStepID)
	if err != nil || processStep == nil {
		return nil
	}
	inputs, _ := s.psmRepo.ListInputsByStepID(processStep.StepID)
	outputs, _ := s.psmRepo.ListOutputsByStepID(processStep.StepID)
	inputUnits := float64(req.QuantityProduced + req.QuantityScrap)
	outputUnits := float64(req.QuantityProduced)

	for _, input := range inputs {
		required := inputUnits * input.QuantityPerUnit
		if required <= 0 {
			continue
		}
		if input.ProductID != nil {
			productID := *input.ProductID
			wipConsumed := s.consumeWIP(step.JobID, productID, required)
			remaining := required - wipConsumed
			if remaining > 0 {
				_ = s.consumePendingProductReservations(step.JobID, step.JobStepID, productID, remaining)
			}
			continue
		}
		if input.MaterialID != nil {
			_ = s.consumePendingMaterialReservations(step.JobID, step.JobStepID, *input.MaterialID, required)
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
		if s.outputStaysInWIP(step.JobID, processStep.StepSequence, productID) {
			_ = s.wipRepo.UpsertWIP(&domain.WIPInventory{
				ID:        id.NewPrefixed("WIP-"),
				JobStepID: step.JobStepID,
				ProductID: &productID,
				Quantity:  qty,
				Unit:      output.Unit,
				Location:  "WIP",
				UpdatedAt: time.Now().UTC(),
			})
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
		_ = s.blockDependentConsumers(step.JobID, step.JobStepID)
	}
	return nil
}

func (s *ProductionLogService) consumeWIP(jobID, productID string, qty float64) float64 {
	if s.wipRepo == nil || qty <= 0 {
		return 0
	}
	items, err := s.wipRepo.ListWIPByJobID(jobID)
	if err != nil {
		return 0
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
		_ = s.wipRepo.UpsertWIP(&item)
		consumed += used
		if consumed >= qty {
			break
		}
	}
	return consumed
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
		processStep, err := s.scheduling.GetProcessStepForJobStep(step.JobStepID)
		if err != nil || processStep == nil {
			continue
		}
		inputs, err := s.psmRepo.ListInputsByStepID(processStep.StepID)
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
			_ = s.stepRepo.Update(step)
			job, jobErr := s.jobRepo.GetByID(step.JobID)
			if jobErr == nil && job != nil {
				job.Status = domain.JobStatusBlocked
				job.UpdatedAt = time.Now().UTC()
				job.Notes = schedulerNoteAppend(job.Notes, "reason_code="+reasonCodeInsufficientOutput)
				_ = s.jobRepo.Update(job)
			}
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

func (s *ProductionLogService) refreshProposalOutcome(proposalID string) {
	proposal, err := s.proposalRepo.GetByID(proposalID)
	if err != nil {
		return
	}
	slots, err := s.slotRepo.ListByProposalID(proposalID)
	if err != nil || len(slots) == 0 {
		return
	}
	totalProduced := 0
	totalScrap := 0
	completedSlots := 0
	var actualCompletion *time.Time
	for _, slot := range slots {
		logs, err := s.logRepo.ListBySlotID(slot.SlotID)
		if err != nil {
			continue
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
	raw, _ := json.Marshal(outcome)
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
	_ = s.proposalRepo.Update(proposal)
}
