package repository

import (
	"emas/internal/domain"
	"time"

	"gorm.io/gorm"
)

type MachineRepository struct {
	db *gorm.DB
}

func NewMachineRepository(db *gorm.DB) *MachineRepository {
	return &MachineRepository{db: db}
}

func (r *MachineRepository) Create(m *domain.Machine) error {
	return r.db.Create(m).Error
}

func (r *MachineRepository) GetByID(id string) (*domain.Machine, error) {
	var m domain.Machine
	err := r.db.Where("machine_id = ?", id).First(&m).Error
	if err != nil {
		return nil, err
	}
	return &m, nil
}

func (r *MachineRepository) ListAll() ([]domain.Machine, error) {
	var machines []domain.Machine
	err := r.db.Find(&machines).Error
	return machines, err
}

func (r *MachineRepository) Update(m *domain.Machine) error {
	return r.db.Save(m).Error
}

func (r *MachineRepository) Delete(id string) error {
	return r.db.Where("machine_id = ?", id).Delete(&domain.Machine{}).Error
}

func (r *MachineRepository) ListDueForMaintenance(daysAhead int) ([]domain.Machine, error) {
	var all []domain.Machine
	if err := r.db.Where("status != ?", domain.MachineStatusOffline).Find(&all).Error; err != nil {
		return nil, err
	}
	cutoff := time.Now().AddDate(0, 0, daysAhead)
	list := make([]domain.Machine, 0)
	for _, machine := range all {
		base := time.Date(1970, 1, 1, 0, 0, 0, 0, time.UTC)
		if machine.LastMaintenanceDate != nil {
			base = *machine.LastMaintenanceDate
		}
		dueAt := base.AddDate(0, 0, machine.MaintenanceIntervalDays)
		if !dueAt.After(cutoff) {
			list = append(list, machine)
		}
	}
	return list, nil
}

func (r *MachineRepository) ListCalendarByMachineID(machineID string) ([]domain.MachineCalendar, error) {
	var list []domain.MachineCalendar
	err := r.db.Where("machine_id = ?", machineID).Order("start_time").Find(&list).Error
	return list, err
}

func (r *MachineRepository) DeleteCalendarByMachineID(machineID string) error {
	return r.db.Where("machine_id = ?", machineID).Delete(&domain.MachineCalendar{}).Error
}

func (r *MachineRepository) CreateCalendar(cal domain.MachineCalendar) error {
	return r.db.Create(&cal).Error
}
