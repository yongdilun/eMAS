package service

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/pkg/id"
	"encoding/json"
	"time"
)

type ProductionLogService struct {
	logRepo      *repository.ProductionLogRepository
	slotRepo     *repository.JobSlotRepository
	stepRepo     *repository.JobStepRepository
	jobRepo      *repository.JobRepository
	proposalRepo *repository.AIProposalRepository
}

func NewProductionLogService(
	logRepo *repository.ProductionLogRepository,
	slotRepo *repository.JobSlotRepository,
	stepRepo *repository.JobStepRepository,
	jobRepo *repository.JobRepository,
	proposalRepo *repository.AIProposalRepository,
) *ProductionLogService {
	return &ProductionLogService{
		logRepo:      logRepo,
		slotRepo:     slotRepo,
		stepRepo:     stepRepo,
		jobRepo:      jobRepo,
		proposalRepo: proposalRepo,
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
			step.QuantityCompleted += req.QuantityProduced
			if step.QuantityCompleted >= step.QuantityTarget {
				step.Status = domain.JobStepStatusCompleted
			} else if step.QuantityCompleted > 0 {
				step.Status = domain.JobStepStatusRunning
			}
			_ = s.stepRepo.Update(step)
			job, _ := s.jobRepo.GetByID(step.JobID)
			if job != nil {
				job.QuantityCompleted += req.QuantityProduced
				if job.QuantityCompleted >= job.QuantityTotal {
					job.Status = domain.JobStatusCompleted
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
	}
	return pl, nil
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
