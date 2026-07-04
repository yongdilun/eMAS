package service

import (
	"time"

	"emas/internal/domain"
	"emas/internal/handler/dto"

	"gorm.io/gorm"
)

type ProductionCatchUpOptions struct {
	AsOf      time.Time
	JobPrefix string
	DryRun    bool
}

type ProductionCatchUpResult struct {
	AsOf       time.Time                  `json:"as_of"`
	JobPrefix  string                     `json:"job_prefix,omitempty"`
	DryRun     bool                       `json:"dry_run"`
	Candidates int                        `json:"candidates"`
	Completed  int                        `json:"completed"`
	Skipped    int                        `json:"skipped"`
	Rows       []ProductionCatchUpSlotRow `json:"rows"`
}

type ProductionCatchUpSlotRow struct {
	SlotID           string    `json:"slot_id"`
	JobID            string    `json:"job_id"`
	JobStepID        string    `json:"job_step_id"`
	ScheduledStart   time.Time `json:"scheduled_start"`
	ScheduledEnd     time.Time `json:"scheduled_end"`
	QuantityPlanned  int       `json:"quantity_planned"`
	AlreadyAccounted int       `json:"already_accounted"`
	QuantityLogged   int       `json:"quantity_logged"`
	Action           string    `json:"action"`
	Error            string    `json:"error,omitempty"`
}

type ProductionCatchUpService struct {
	db         *gorm.DB
	logService *ProductionLogService
}

func NewProductionCatchUpService(db *gorm.DB, logService *ProductionLogService) *ProductionCatchUpService {
	return &ProductionCatchUpService{db: db, logService: logService}
}

func (s *ProductionCatchUpService) CatchUpDueSlots(opts ProductionCatchUpOptions) (*ProductionCatchUpResult, error) {
	asOf := opts.AsOf.UTC()
	if asOf.IsZero() {
		asOf = time.Now().UTC()
	}
	result := &ProductionCatchUpResult{
		AsOf:      asOf,
		JobPrefix: opts.JobPrefix,
		DryRun:    opts.DryRun,
	}
	slots, err := s.dueSlots(asOf, opts.JobPrefix)
	if err != nil {
		return nil, err
	}
	result.Candidates = len(slots)
	for _, slot := range slots {
		accounted, err := s.accountedQuantity(slot.SlotID)
		if err != nil {
			return nil, err
		}
		row := ProductionCatchUpSlotRow{
			SlotID:           slot.SlotID,
			JobID:            slot.JobID,
			JobStepID:        slot.JobStepID,
			ScheduledStart:   slot.ScheduledStart,
			ScheduledEnd:     slot.ScheduledEnd,
			QuantityPlanned:  slot.QuantityPlanned,
			AlreadyAccounted: accounted,
		}
		remaining := slot.QuantityPlanned - accounted
		if remaining <= 0 {
			row.Action = "skipped_already_logged"
			result.Skipped++
			result.Rows = append(result.Rows, row)
			continue
		}
		row.QuantityLogged = remaining
		if opts.DryRun {
			row.Action = "would_log"
			result.Rows = append(result.Rows, row)
			continue
		}
		if _, err := s.logService.LogProduction(dto.LogProductionRequest{
			SlotID:           slot.SlotID,
			StartTime:        slot.ScheduledStart,
			EndTime:          slot.ScheduledEnd,
			QuantityProduced: remaining,
			OperatorNotes:    "production catch-up simulator",
		}); err != nil {
			row.Action = "failed"
			row.Error = err.Error()
			result.Rows = append(result.Rows, row)
			return result, err
		}
		row.Action = "logged"
		result.Completed++
		result.Rows = append(result.Rows, row)
	}
	return result, nil
}

type productionCatchUpDueSlot struct {
	SlotID          string
	JobID           string
	JobStepID       string
	ScheduledStart  time.Time
	ScheduledEnd    time.Time
	QuantityPlanned int
}

func (s *ProductionCatchUpService) dueSlots(asOf time.Time, jobPrefix string) ([]productionCatchUpDueSlot, error) {
	q := s.db.Table("job_step_schedule_slots AS s").
		Select("s.slot_id, js.job_id, s.job_step_id, s.scheduled_start, s.scheduled_end, s.quantity_planned").
		Joins("JOIN job_steps js ON js.job_step_id = s.job_step_id").
		Joins("JOIN jobs j ON j.job_id = js.job_id").
		Where("s.scheduled_end <= ?", asOf).
		Where("s.status NOT IN ?", []string{domain.SlotStatusCompleted, domain.SlotStatusCancelled}).
		Order("s.scheduled_end ASC, s.slot_id ASC")
	if jobPrefix != "" {
		q = q.Where("j.job_id LIKE ?", jobPrefix+"%")
	}
	var rows []productionCatchUpDueSlot
	if err := q.Scan(&rows).Error; err != nil {
		return nil, err
	}
	return rows, nil
}

func (s *ProductionCatchUpService) accountedQuantity(slotID string) (int, error) {
	var total int
	err := s.db.Model(&domain.ProductionLogs{}).
		Where("slot_id = ?", slotID).
		Select("COALESCE(SUM(quantity_produced + quantity_scrap), 0)").
		Scan(&total).Error
	return total, err
}
