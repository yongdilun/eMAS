package service

import (
	"emas/internal/domain"
	"emas/internal/repository"
	"emas/pkg/id"
	"time"
)

type MaintenanceService struct {
	maintenanceRepo *repository.MaintenanceRepository
	machineRepo     *repository.MachineRepository
}

func NewMaintenanceService(
	maintenanceRepo *repository.MaintenanceRepository,
	machineRepo *repository.MachineRepository,
) *MaintenanceService {
	return &MaintenanceService{
		maintenanceRepo: maintenanceRepo,
		machineRepo:     machineRepo,
	}
}

func (s *MaintenanceService) RecordMaintenance(machineID, mtype, technician, description string, start, end time.Time) (*domain.MaintenanceRecords, error) {
	m := &domain.MaintenanceRecords{
		MaintenanceID:   id.NewPrefixed("MNT-"),
		MachineID:       machineID,
		MaintenanceType: mtype,
		StartTime:       start,
		EndTime:         end,
		Technician:      technician,
		Description:     description,
	}
	if m.MaintenanceType == "" {
		m.MaintenanceType = domain.MaintenanceTypePreventive
	}
	if err := s.maintenanceRepo.Create(m); err != nil {
		return nil, err
	}
	machine, _ := s.machineRepo.GetByID(machineID)
	if machine != nil {
		machine.LastMaintenanceDate = &end
		_ = s.machineRepo.Update(machine)
	}
	return m, nil
}
