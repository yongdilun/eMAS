package service

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/pkg/id"
)

type ProcessService struct {
	processRepo *repository.ProcessRepository
}

func NewProcessService(processRepo *repository.ProcessRepository) *ProcessService {
	return &ProcessService{processRepo: processRepo}
}

func (s *ProcessService) Create(req dto.CreateProcessRequest) (*domain.ProductProcess, error) {
	p := &domain.ProductProcess{
		ProcessID:   req.ProcessID,
		ProductID:   req.ProductID,
		ProcessName: req.ProcessName,
		Version:     req.Version,
		Description: req.Description,
	}
	if err := s.processRepo.Create(p); err != nil {
		return nil, err
	}
	return s.processRepo.GetProcessByID(req.ProcessID)
}

func (s *ProcessService) GetByID(id string) (*domain.ProductProcess, error) {
	return s.processRepo.GetProcessByID(id)
}

func (s *ProcessService) GetByProductID(productID string) (*domain.ProductProcess, error) {
	return s.processRepo.GetProcessByProductID(productID)
}

func (s *ProcessService) ListAll() ([]domain.ProductProcess, error) {
	return s.processRepo.ListAll()
}

func (s *ProcessService) ListSteps(processID string) ([]domain.ProcessSteps, error) {
	return s.processRepo.ListStepsByProcessID(processID)
}

func (s *ProcessService) AddStep(processID string, req dto.CreateProcessStepRequest) (*domain.ProcessSteps, error) {
	stepID := req.StepID
	if stepID == "" {
		stepID = id.NewPrefixed("STP-")
	}
	seq := req.StepSequence
	if seq <= 0 {
		steps, _ := s.processRepo.ListStepsByProcessID(processID)
		seq = len(steps) + 1
	}
	step := &domain.ProcessSteps{
		StepID:                 stepID,
		ProcessID:              processID,
		StepSequence:           seq,
		StepName:               req.StepName,
		StepType:               req.StepType,
		MachineTypeRequired:    req.MachineTypeRequired,
		DefaultPreparationTime: req.DefaultPreparationTime,
		DefaultProcessingTime:  req.DefaultProcessingTime,
		DefaultCleaningTime:    req.DefaultCleaningTime,
		DefaultChangeoverTime:  req.DefaultChangeoverTime,
		AllowParallelExecution: req.AllowParallelExecution,
		MaxParallelMachines:    req.MaxParallelMachines,
		MinSplitQty:            req.MinSplitQty,
		TransferBatchSize:      req.TransferBatchSize,
		QualityCheckRequired:   req.QualityCheckRequired,
		Notes:                  req.Notes,
	}
	if step.StepType == "" {
		step.StepType = req.StepName
	}
	if err := s.processRepo.CreateStep(step); err != nil {
		return nil, err
	}
	return step, nil
}

func (s *ProcessService) Delete(processID string) error {
	return s.processRepo.Delete(processID)
}
