package service

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/pkg/id"
)

type MachineService struct {
	machineRepo     *repository.MachineRepository
	capRepo         *repository.MachineCapabilityRepository
	downtimeRepo    *repository.MachineDowntimeRepository
	maintenanceRepo *repository.MaintenanceRepository
}

func NewMachineService(
	machineRepo *repository.MachineRepository,
	capRepo *repository.MachineCapabilityRepository,
	downtimeRepo *repository.MachineDowntimeRepository,
	maintenanceRepo *repository.MaintenanceRepository,
) *MachineService {
	return &MachineService{
		machineRepo:     machineRepo,
		capRepo:         capRepo,
		downtimeRepo:    downtimeRepo,
		maintenanceRepo: maintenanceRepo,
	}
}

func (s *MachineService) Create(req dto.CreateMachineRequest) (*domain.Machine, error) {
	m := &domain.Machine{
		MachineID:               req.MachineID,
		MachineName:             req.MachineName,
		MachineType:             req.MachineType,
		Location:                req.Location,
		Status:                  domain.MachineStatusIdle,
		CapacityPerHour:         req.CapacityPerHour,
		DefaultSetupTime:        req.DefaultSetupTime,
		DefaultCleaningTime:     req.DefaultCleaningTime,
		DefaultChangeoverTime:   req.DefaultChangeoverTime,
		MaintenanceIntervalDays: req.MaintenanceIntervalDays,
	}
	if err := s.machineRepo.Create(m); err != nil {
		return nil, err
	}
	return s.machineRepo.GetByID(req.MachineID)
}

func (s *MachineService) GetByID(id string) (*domain.Machine, error) {
	return s.machineRepo.GetByID(id)
}

func (s *MachineService) ListAll() ([]domain.Machine, error) {
	return s.machineRepo.ListAll()
}

func (s *MachineService) Update(id string, req dto.UpdateMachineRequest) (*domain.Machine, error) {
	m, err := s.machineRepo.GetByID(id)
	if err != nil {
		return nil, err
	}
	if req.MachineName != nil {
		m.MachineName = *req.MachineName
	}
	if req.MachineType != nil {
		m.MachineType = *req.MachineType
	}
	if req.Location != nil {
		m.Location = *req.Location
	}
	if req.Status != nil {
		m.Status = *req.Status
	}
	if req.CapacityPerHour != nil {
		m.CapacityPerHour = *req.CapacityPerHour
	}
	if req.DefaultSetupTime != nil {
		m.DefaultSetupTime = *req.DefaultSetupTime
	}
	if req.DefaultCleaningTime != nil {
		m.DefaultCleaningTime = *req.DefaultCleaningTime
	}
	if req.DefaultChangeoverTime != nil {
		m.DefaultChangeoverTime = *req.DefaultChangeoverTime
	}
	if req.MaintenanceIntervalDays != nil {
		m.MaintenanceIntervalDays = *req.MaintenanceIntervalDays
	}
	if err := s.machineRepo.Update(m); err != nil {
		return nil, err
	}
	return s.machineRepo.GetByID(id)
}

func (s *MachineService) AssignCapability(machineID string, req dto.AssignCapabilityRequest) (*domain.MachineCapabilities, error) {
	eff := req.EfficiencyFactor
	if eff <= 0 {
		eff = 1.0
	}
	c := &domain.MachineCapabilities{
		CapabilityID:     id.NewPrefixed("CAP-"),
		MachineID:        machineID,
		StepID:           req.StepID,
		EfficiencyFactor: eff,
	}
	if err := s.capRepo.Create(c); err != nil {
		return nil, err
	}
	return c, nil
}

func (s *MachineService) RecordDowntime(req dto.RecordDowntimeRequest) (*domain.MachineDowntime, error) {
	dur := int(req.EndTime.Sub(req.StartTime).Minutes())
	d := &domain.MachineDowntime{
		DowntimeID:      id.NewPrefixed("DT-"),
		MachineID:       req.MachineID,
		JobStepSlotID:   req.JobStepSlotID,
		Cause:           req.Cause,
		StartTime:       req.StartTime,
		EndTime:         req.EndTime,
		DurationMinutes: dur,
	}
	if err := s.downtimeRepo.Create(d); err != nil {
		return nil, err
	}
	return d, nil
}

func (s *MachineService) GetMaintenanceAlerts(daysAhead int) ([]domain.Machine, error) {
	if daysAhead <= 0 {
		daysAhead = 7
	}
	return s.machineRepo.ListDueForMaintenance(daysAhead)
}

func (s *MachineService) GetRerouteRecommendations(downMachineID string) (map[string][]string, error) {
	stepIDs, err := s.capRepo.ListStepIDsByMachineID(downMachineID)
	if err != nil || len(stepIDs) == 0 {
		return map[string][]string{}, nil
	}
	result := make(map[string][]string)
	for _, stepID := range stepIDs {
		machines, _ := s.capRepo.ListMachinesByStepID(stepID)
		var alt []string
		for _, m := range machines {
			if m != downMachineID {
				alt = append(alt, m)
			}
		}
		if len(alt) > 0 {
			result[stepID] = alt
		}
	}
	return result, nil
}
