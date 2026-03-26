package repository

import (
	"emas/internal/domain"
	"strings"
	"time"

	"gorm.io/gorm"
)

type JobSlotRepository struct {
	db *gorm.DB
}

func NewJobSlotRepository(db *gorm.DB) *JobSlotRepository {
	return &JobSlotRepository{db: db}
}

func (r *JobSlotRepository) Create(s *domain.JobStepScheduleSlots) error {
	return r.db.Create(s).Error
}

func (r *JobSlotRepository) CreateBatch(slots []domain.JobStepScheduleSlots) error {
	if len(slots) == 0 {
		return nil
	}
	return r.db.Create(&slots).Error
}

func (r *JobSlotRepository) GetByID(id string) (*domain.JobStepScheduleSlots, error) {
	var s domain.JobStepScheduleSlots
	err := r.db.Where("slot_id = ?", id).First(&s).Error
	if err != nil {
		return nil, err
	}
	return &s, nil
}

func (r *JobSlotRepository) ListByJobStepID(jobStepID string) ([]domain.JobStepScheduleSlots, error) {
	var slots []domain.JobStepScheduleSlots
	err := r.db.Where("job_step_id = ?", jobStepID).Order("scheduled_start").Find(&slots).Error
	return slots, err
}

func (r *JobSlotRepository) ListByJobID(jobID string) ([]domain.JobStepScheduleSlots, error) {
	var slots []domain.JobStepScheduleSlots
	err := r.db.Table("job_step_schedule_slots").Select("job_step_schedule_slots.*").
		Joins("JOIN job_steps ON job_steps.job_step_id = job_step_schedule_slots.job_step_id").
		Where("job_steps.job_id = ?", jobID).Scan(&slots).Error
	return slots, err
}

func (r *JobSlotRepository) ListByMachineID(machineID string) ([]domain.JobStepScheduleSlots, error) {
	var slots []domain.JobStepScheduleSlots
	err := r.db.Where("machine_id = ?", machineID).Order("scheduled_start").Find(&slots).Error
	return slots, err
}

func (r *JobSlotRepository) ListByProposalID(proposalID string) ([]domain.JobStepScheduleSlots, error) {
	var slots []domain.JobStepScheduleSlots
	err := r.db.Where("proposal_id = ?", proposalID).Order("scheduled_start").Find(&slots).Error
	return slots, err
}

func (r *JobSlotRepository) Update(s *domain.JobStepScheduleSlots) error {
	return r.db.Save(s).Error
}

func (r *JobSlotRepository) Delete(id string) error {
	return r.db.Where("slot_id = ?", id).Delete(&domain.JobStepScheduleSlots{}).Error
}

func (r *JobSlotRepository) DeleteByJobStepID(jobStepID string) error {
	return r.db.Where("job_step_id = ?", jobStepID).Delete(&domain.JobStepScheduleSlots{}).Error
}

// ActiveSlotRow holds slot info with job_id for overlap verification
type ActiveSlotRow struct {
	SlotID         string
	JobID          string
	JobStepID      string
	ProposalID     string
	MachineID      string
	ScheduledStart time.Time
	ScheduledEnd   time.Time
}

// ListActiveByJobIDs returns slots with status planned or running, optionally filtered by job IDs.
// If jobIDs is nil or empty, returns all active slots.
func (r *JobSlotRepository) ListActiveByJobIDs(jobIDs []string) ([]ActiveSlotRow, error) {
	q := r.db.Table("job_step_schedule_slots").
		Select("job_step_schedule_slots.slot_id, job_steps.job_id, job_step_schedule_slots.job_step_id, job_step_schedule_slots.proposal_id, job_step_schedule_slots.machine_id, job_step_schedule_slots.scheduled_start, job_step_schedule_slots.scheduled_end").
		Joins("JOIN job_steps ON job_steps.job_step_id = job_step_schedule_slots.job_step_id").
		Where("job_step_schedule_slots.status IN ?", []string{domain.SlotStatusPlanned, domain.SlotStatusRunning})
	if len(jobIDs) > 0 {
		q = q.Where("job_steps.job_id IN ?", jobIDs)
	}
	var rows []ActiveSlotRow
	err := q.Order("job_step_schedule_slots.scheduled_start").Scan(&rows).Error
	return rows, err
}

func (r *JobSlotRepository) HasOverlap(machineID string, start, end time.Time, excludeSlotID string) (bool, []domain.JobStepScheduleSlots, error) {
	activeStatuses := []string{domain.SlotStatusPlanned, domain.SlotStatusRunning}
	q := r.db.Where("machine_id = ? AND status IN ? AND scheduled_start < ? AND scheduled_end > ?", machineID, activeStatuses, end, start)
	if strings.TrimSpace(excludeSlotID) != "" {
		q = q.Where("slot_id <> ?", excludeSlotID)
	}
	var slots []domain.JobStepScheduleSlots
	if err := q.Order("scheduled_start").Find(&slots).Error; err != nil {
		return false, nil, err
	}
	return len(slots) > 0, slots, nil
}

// LastSlotOnMachineRow holds slot and product for setup-time lookup
type LastSlotOnMachineRow struct {
	Slot      domain.JobStepScheduleSlots
	ProductID string
}

// GetLastSlotOnMachineBefore returns the most recent slot on machine ending before `before`, with the job's product_id.
// Excludes cancelled slots. Returns nil if no such slot exists.
func (r *JobSlotRepository) GetLastSlotOnMachineBefore(machineID string, before time.Time) (*LastSlotOnMachineRow, error) {
	type row struct {
		SlotID         string    `gorm:"column:slot_id"`
		JobStepID      string    `gorm:"column:job_step_id"`
		ProposalID     string    `gorm:"column:proposal_id"`
		MachineID      string    `gorm:"column:machine_id"`
		ScheduledStart time.Time `gorm:"column:scheduled_start"`
		ScheduledEnd   time.Time `gorm:"column:scheduled_end"`
		QuantityPlanned int      `gorm:"column:quantity_planned"`
		Status         string    `gorm:"column:status"`
		ProductID      string    `gorm:"column:product_id"`
	}
	var out row
	err := r.db.Table("job_step_schedule_slots").
		Select("job_step_schedule_slots.slot_id, job_step_schedule_slots.job_step_id, job_step_schedule_slots.proposal_id, job_step_schedule_slots.machine_id, job_step_schedule_slots.scheduled_start, job_step_schedule_slots.scheduled_end, job_step_schedule_slots.quantity_planned, job_step_schedule_slots.status, jobs.product_id").
		Joins("JOIN job_steps ON job_steps.job_step_id = job_step_schedule_slots.job_step_id").
		Joins("JOIN jobs ON jobs.job_id = job_steps.job_id").
		Where("job_step_schedule_slots.machine_id = ?", machineID).
		Where("job_step_schedule_slots.scheduled_end < ?", before).
		Where("job_step_schedule_slots.status <> ?", domain.SlotStatusCancelled).
		Order("job_step_schedule_slots.scheduled_end DESC").
		Limit(1).
		Scan(&out).Error
	if err != nil {
		return nil, err
	}
	if out.SlotID == "" {
		return nil, nil
	}
	slot := domain.JobStepScheduleSlots{
		SlotID:          out.SlotID,
		JobStepID:       out.JobStepID,
		ProposalID:      out.ProposalID,
		MachineID:       out.MachineID,
		ScheduledStart:  out.ScheduledStart,
		ScheduledEnd:    out.ScheduledEnd,
		QuantityPlanned: out.QuantityPlanned,
		Status:          out.Status,
	}
	return &LastSlotOnMachineRow{Slot: slot, ProductID: out.ProductID}, nil
}

// GetEarliestActiveStartByJobID returns the earliest scheduled_start among planned/running slots for a job.
// Returns (nil, nil) if the job has no active slots.
func (r *JobSlotRepository) GetEarliestActiveStartByJobID(jobID string) (*time.Time, error) {
	type row struct {
		ScheduledStart time.Time `gorm:"column:scheduled_start"`
	}
	var out row
	err := r.db.Table("job_step_schedule_slots").
		Select("job_step_schedule_slots.scheduled_start").
		Joins("JOIN job_steps ON job_steps.job_step_id = job_step_schedule_slots.job_step_id").
		Where("job_steps.job_id = ?", jobID).
		Where("job_step_schedule_slots.status IN ?", []string{domain.SlotStatusPlanned, domain.SlotStatusRunning}).
		Order("job_step_schedule_slots.scheduled_start").
		Limit(1).
		Scan(&out).Error
	if err != nil {
		return nil, err
	}
	if out.ScheduledStart.IsZero() {
		return nil, nil
	}
	t := out.ScheduledStart
	return &t, nil
}
