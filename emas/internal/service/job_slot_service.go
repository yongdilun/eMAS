package service

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/pkg/id"
	"errors"
	"strings"
	"time"
)

func parseTime(s string) (time.Time, error) {
	return time.Parse(time.RFC3339, s)
}

type JobSlotService struct {
	slotRepo    *repository.JobSlotRepository
	stepRepo    *repository.JobStepRepository
	processRepo *repository.ProcessRepository
	jobRepo     *repository.JobRepository
	scheduling  *SchedulingService
}

func NewJobSlotService(
	slotRepo *repository.JobSlotRepository,
	stepRepo *repository.JobStepRepository,
	processRepo *repository.ProcessRepository,
	jobRepo *repository.JobRepository,
	scheduling *SchedulingService,
) *JobSlotService {
	return &JobSlotService{
		slotRepo:    slotRepo,
		stepRepo:    stepRepo,
		processRepo: processRepo,
		jobRepo:     jobRepo,
		scheduling:  scheduling,
	}
}

func (s *JobSlotService) CreateJobStepsFromRouting(jobID string) ([]domain.JobSteps, error) {
	steps, _ := s.stepRepo.ListByJobID(jobID)
	if len(steps) > 0 {
		return steps, nil
	}
	job, err := s.jobRepo.GetByID(jobID)
	if err != nil {
		return nil, err
	}
	process, err := s.processRepo.GetProcessByProductID(job.ProductID)
	if err != nil {
		return nil, err
	}
	processSteps, err := s.processRepo.ListStepsByProcessID(process.ProcessID)
	if err != nil {
		return nil, err
	}
	jobSteps := make([]domain.JobSteps, 0, len(processSteps))
	for i, ps := range processSteps {
		js := domain.JobSteps{
			JobStepID:      id.NewPrefixed("JS-"),
			JobID:          jobID,
			StepID:         ps.StepID,
			StepSequence:   i + 1,
			QuantityTarget: job.QuantityTotal,
			Status:         domain.JobStepStatusPending,
		}
		if err := s.stepRepo.Create(&js); err != nil {
			return nil, err
		}
		jobSteps = append(jobSteps, js)
	}
	return jobSteps, nil
}

func (s *JobSlotService) SplitStep(jobStepID string, splits []dto.CreateSlotRequest) ([]domain.JobStepScheduleSlots, error) {
	jobStep, err := s.stepRepo.GetByID(jobStepID)
	if err != nil {
		return nil, err
	}
	processStep, err := s.processRepo.GetStepByID(jobStep.StepID)
	if err != nil {
		return nil, err
	}
	existing, err := s.slotRepo.ListByJobStepID(jobStepID)
	if err != nil {
		return nil, err
	}
	totalPlanned := 0
	for _, slot := range existing {
		if slot.Status != domain.SlotStatusCancelled {
			totalPlanned += slot.QuantityPlanned
		}
	}
	ignoreMinSplitQty := isTemporalSliceRequestGroup(splits)
	var created []domain.JobStepScheduleSlots
	for _, rs := range splits {
		start, _ := parseTime(rs.StartTime)
		end := start.Add(time.Duration(rs.DurationMins) * time.Minute)
		if !ignoreMinSplitQty && processStep.MinSplitQty > 0 && rs.Quantity < processStep.MinSplitQty {
			return nil, errors.New("split quantity is below min_split_qty")
		}
		totalPlanned += rs.Quantity
		if totalPlanned > jobStep.QuantityTarget {
			return nil, errors.New("total split quantity exceeds job step target")
		}
		if s.scheduling != nil {
			validation, err := s.scheduling.ValidateSlotWithOptions(jobStepID, rs.MachineID, start, end, rs.Quantity, "", SlotValidationOptions{IgnoreMinSplitQty: ignoreMinSplitQty})
			if err != nil {
				return nil, err
			}
			if !validation.Valid {
				return nil, errors.New(strings.Join(validation.Reasons, "; "))
			}
		}
		allocationPercent := rs.AllocationPercent
		if allocationPercent == 0 && jobStep.QuantityTarget > 0 {
			allocationPercent = (float64(rs.Quantity) / float64(jobStep.QuantityTarget)) * 100
		}
		slot := &domain.JobStepScheduleSlots{
			SlotID:                 id.NewPrefixed("SLOT-"),
			JobStepID:              jobStepID,
			ProposalID:             rs.ProposalID,
			MachineID:              rs.MachineID,
			ScheduledStart:         start,
			ScheduledEnd:           end,
			QuantityPlanned:        rs.Quantity,
			SplitGroupID:           rs.SplitGroupID,
			AllocationPercent:      allocationPercent,
			IsParallel:             rs.IsParallel,
			BatchSequence:          rs.BatchSequence,
			PreparationTimeMinutes: rs.PrepMins,
			ProcessingTimeMinutes:  rs.ProcessingMins,
			CleaningTimeMinutes:    rs.CleaningMins,
			BufferTimeMinutes:      rs.BufferMins,
			Status:                 domain.SlotStatusPlanned,
		}
		if slot.SplitGroupID == "" {
			slot.SplitGroupID = "SG-" + jobStepID
		}
		if err := s.slotRepo.Create(slot); err != nil {
			return nil, err
		}
		created = append(created, *slot)
	}
	if len(created) > 0 && jobStep.Status == domain.JobStepStatusPending {
		jobStep.Status = domain.JobStepStatusScheduled
		if err := s.stepRepo.Update(jobStep); err != nil {
			return nil, err
		}
		job, err := s.jobRepo.GetByID(jobStep.JobID)
		if err == nil && job.Status == domain.JobStatusPlanned {
			job.Status = domain.JobStatusScheduled
			job.UpdatedAt = time.Now()
			if err := s.jobRepo.Update(job); err != nil {
				return nil, err
			}
		}
	}
	return created, nil
}

func isTemporalSliceRequestGroup(splits []dto.CreateSlotRequest) bool {
	if len(splits) <= 1 {
		return false
	}
	for _, rs := range splits {
		if rs.IsParallel {
			return false
		}
	}
	return true
}

var validSlotStatuses = map[string]bool{
	domain.SlotStatusPlanned:   true,
	domain.SlotStatusRunning:   true,
	domain.SlotStatusPaused:    true,
	domain.SlotStatusCompleted: true,
	domain.SlotStatusCancelled: true,
}

func (s *JobSlotService) UpdateSlot(id string, req dto.UpdateSlotRequest) (*domain.JobStepScheduleSlots, error) {
	slot, err := s.slotRepo.GetByID(id)
	if err != nil {
		return nil, err
	}
	if req.MachineID != nil {
		slot.MachineID = *req.MachineID
	}
	if req.ScheduledStart != nil {
		slot.ScheduledStart = *req.ScheduledStart
	}
	if req.ScheduledEnd != nil {
		slot.ScheduledEnd = *req.ScheduledEnd
	}
	if req.QuantityPlanned != nil {
		slot.QuantityPlanned = *req.QuantityPlanned
	}
	if req.AllocationPercent != nil {
		slot.AllocationPercent = *req.AllocationPercent
	}
	if req.IsParallel != nil {
		slot.IsParallel = *req.IsParallel
	}
	if req.BatchSequence != nil {
		slot.BatchSequence = *req.BatchSequence
	}
	// Gap 2: actual_start, actual_end, status (Start/Pause/Resume/Complete)
	if req.Status != nil {
		st := strings.TrimSpace(strings.ToLower(*req.Status))
		if !validSlotStatuses[st] {
			return nil, errors.New("status must be planned, running, paused, completed, or cancelled")
		}
		slot.Status = st
		if st == domain.SlotStatusRunning && req.ActualStart == nil && slot.ActualStart == nil {
			now := time.Now().UTC()
			slot.ActualStart = &now
		}
		if st == domain.SlotStatusCompleted && req.ActualEnd == nil && slot.ActualEnd == nil {
			now := time.Now().UTC()
			slot.ActualEnd = &now
		}
	}
	if req.ActualStart != nil {
		slot.ActualStart = req.ActualStart
	}
	if req.ActualEnd != nil {
		slot.ActualEnd = req.ActualEnd
	}
	jobStep, err := s.stepRepo.GetByID(slot.JobStepID)
	if err != nil {
		return nil, err
	}
	siblings, err := s.slotRepo.ListByJobStepID(slot.JobStepID)
	if err != nil {
		return nil, err
	}
	totalPlanned := 0
	for _, sibling := range siblings {
		if sibling.SlotID == slot.SlotID || sibling.Status == domain.SlotStatusCancelled {
			continue
		}
		totalPlanned += sibling.QuantityPlanned
	}
	totalPlanned += slot.QuantityPlanned
	if totalPlanned > jobStep.QuantityTarget {
		return nil, errors.New("total planned slot quantity exceeds job step target")
	}
	if s.scheduling != nil {
		validation, err := s.scheduling.ValidateSlot(slot.JobStepID, slot.MachineID, slot.ScheduledStart, slot.ScheduledEnd, slot.QuantityPlanned, slot.SlotID)
		if err != nil {
			return nil, err
		}
		if !validation.Valid {
			return nil, errors.New(strings.Join(validation.Reasons, "; "))
		}
	}
	if err := s.slotRepo.Update(slot); err != nil {
		return nil, err
	}
	return s.slotRepo.GetByID(id)
}

func (s *JobSlotService) GetSlot(id string) (*domain.JobStepScheduleSlots, error) {
	return s.slotRepo.GetByID(id)
}

func (s *JobSlotService) ListSlotsByJobStepID(jobStepID string) ([]domain.JobStepScheduleSlots, error) {
	return s.slotRepo.ListByJobStepID(jobStepID)
}

func (s *JobSlotService) ListSlotsByJobID(jobID string) ([]domain.JobStepScheduleSlots, error) {
	return s.slotRepo.ListByJobID(jobID)
}

func (s *JobSlotService) CancelSlot(id string) error {
	slot, err := s.slotRepo.GetByID(id)
	if err != nil {
		return err
	}
	slot.Status = domain.SlotStatusCancelled
	return s.slotRepo.Update(slot)
}
