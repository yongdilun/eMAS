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

type JobService struct {
	jobRepo     *repository.JobRepository
	stepRepo    *repository.JobStepRepository
	slotRepo    *repository.JobSlotRepository
	processRepo *repository.ProcessRepository
	productRepo *repository.ProductRepository
	scheduling  *SchedulingService
}

func NewJobService(
	jobRepo *repository.JobRepository,
	stepRepo *repository.JobStepRepository,
	slotRepo *repository.JobSlotRepository,
	processRepo *repository.ProcessRepository,
	productRepo *repository.ProductRepository,
	scheduling *SchedulingService,
) *JobService {
	return &JobService{
		jobRepo:     jobRepo,
		stepRepo:    stepRepo,
		slotRepo:    slotRepo,
		processRepo: processRepo,
		productRepo: productRepo,
		scheduling:  scheduling,
	}
}

func (s *JobService) Create(req dto.CreateJobRequest) (*domain.Job, error) {
	deadline, _ := time.Parse(time.RFC3339, req.Deadline)
	if deadline.IsZero() {
		deadline = time.Now().Add(24 * time.Hour)
	}
	if req.Priority == "" {
		req.Priority = domain.JobPriorityMedium
	}

	job := &domain.Job{
		JobID:         id.NewPrefixed("JOB-"),
		ProductID:     req.ProductID,
		QuantityTotal: req.QuantityTotal,
		Priority:      req.Priority,
		Deadline:      deadline,
		Status:        domain.JobStatusPlanned,
		CreatedAt:     time.Now(),
		UpdatedAt:     time.Now(),
		Notes:         req.Notes,
	}
	if err := s.jobRepo.Create(job); err != nil {
		return nil, err
	}

	process, err := s.processRepo.GetProcessByProductIDAsOf(req.ProductID, time.Now())
	if err != nil {
		if len(req.Slots) == 0 {
			return s.jobRepo.GetByID(job.JobID)
		}
		return nil, err
	}
	steps, err := s.processRepo.ListStepsByProcessID(process.ProcessID)
	if err != nil {
		return nil, err
	}
	jobSteps := make([]domain.JobSteps, 0, len(steps))
	for i, ps := range steps {
		js := domain.JobSteps{
			JobStepID:      id.NewPrefixed("JS-"),
			JobID:          job.JobID,
			StepID:         ps.StepID,
			StepSequence:   i + 1,
			QuantityTarget: req.QuantityTotal,
			Status:         domain.JobStepStatusPending,
		}
		jobSteps = append(jobSteps, js)
	}
	if err := s.stepRepo.CreateBatch(jobSteps); err != nil {
		return nil, err
	}

	if len(req.Slots) > 0 {
		if err := s.createSlotsFromRequest(job.JobID, jobSteps, req.Slots); err != nil {
			return nil, err
		}
	}

	return s.jobRepo.GetByID(job.JobID)
}

func (s *JobService) createSlotsFromRequest(jobID string, jobSteps []domain.JobSteps, slots []dto.CreateSlotRequest) error {
	stepByID := make(map[string]domain.JobSteps, len(jobSteps))
	totalByStep := make(map[string]int, len(jobSteps))
	resolvedSlots := make([]dto.CreateSlotRequest, 0, len(slots))
	groupedByStep := make(map[string][]dto.CreateSlotRequest)
	for _, step := range jobSteps {
		stepByID[step.JobStepID] = step
		totalByStep[step.JobStepID] = 0
	}
	for idx, rs := range slots {
		resolvedJobStepID := rs.JobStepID
		if resolvedJobStepID == "" {
			if idx >= len(jobSteps) {
				return errors.New("slot is missing job_step_id and cannot be mapped to a routing step")
			}
			resolvedJobStepID = jobSteps[idx].JobStepID
		}
		if _, ok := stepByID[resolvedJobStepID]; !ok {
			return errors.New("job_step_id does not belong to this job")
		}
		rs.JobStepID = resolvedJobStepID
		resolvedSlots = append(resolvedSlots, rs)
		groupedByStep[resolvedJobStepID] = append(groupedByStep[resolvedJobStepID], rs)
	}
	for _, rs := range resolvedSlots {
		resolvedJobStepID := rs.JobStepID
		jobStep, ok := stepByID[resolvedJobStepID]
		if !ok {
			return errors.New("job_step_id does not belong to this job")
		}
		totalByStep[resolvedJobStepID] += rs.Quantity
		if totalByStep[resolvedJobStepID] > jobStep.QuantityTarget {
			return errors.New("total planned slot quantity exceeds job step target")
		}
		start, _ := time.Parse(time.RFC3339, rs.StartTime)
		end := start.Add(time.Duration(rs.DurationMins) * time.Minute)
		if s.scheduling != nil {
			validation, err := s.scheduling.ValidateSlotWithOptions(resolvedJobStepID, rs.MachineID, start, end, rs.Quantity, "", SlotValidationOptions{IgnoreMinSplitQty: isTemporalSliceRequestGroup(groupedByStep[resolvedJobStepID])})
			if err != nil {
				return err
			}
			if !validation.Valid {
				return errors.New(strings.Join(validation.Reasons, "; "))
			}
		}
		allocationPercent := rs.AllocationPercent
		if allocationPercent == 0 && jobStep.QuantityTarget > 0 {
			allocationPercent = (float64(rs.Quantity) / float64(jobStep.QuantityTarget)) * 100
		}
		slot := &domain.JobStepScheduleSlots{
			SlotID:                 id.NewPrefixed("SLOT-"),
			JobStepID:              resolvedJobStepID,
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
			slot.SplitGroupID = "SG-" + resolvedJobStepID
		}
		if err := s.slotRepo.Create(slot); err != nil {
			return err
		}
		jobStep.Status = domain.JobStepStatusScheduled
		stepByID[resolvedJobStepID] = jobStep
		if err := s.stepRepo.Update(&jobStep); err != nil {
			return err
		}
	}
	job, err := s.jobRepo.GetByID(jobID)
	if err != nil {
		return err
	}
	if job.Status == domain.JobStatusPlanned {
		job.Status = domain.JobStatusScheduled
		job.UpdatedAt = time.Now()
		if err := s.jobRepo.Update(job); err != nil {
			return err
		}
	}
	return nil
}

func (s *JobService) GetByID(id string) (*domain.Job, error) {
	job, err := s.jobRepo.GetByID(id)
	if err != nil {
		return nil, err
	}
	s.enrichJobWithDeadlineStatus(job)
	return job, nil
}

func (s *JobService) ListStepsByJobID(jobID string) ([]domain.JobSteps, error) {
	return s.stepRepo.ListByJobID(jobID)
}

func (s *JobService) ListAll() ([]domain.Job, error) {
	return s.jobRepo.ListAll()
}

func (s *JobService) ListFiltered(f repository.JobListFilter) ([]domain.Job, error) {
	jobs, err := s.jobRepo.ListFiltered(f)
	if err != nil {
		return nil, err
	}
	s.enrichJobsWithDeadlineStatus(jobs)
	return jobs, nil
}

// enrichJobWithDeadlineStatus sets job.DeadlineStatus when job has a deadline and active slots.
// Uses max(slot.scheduled_end) vs job.deadline.
func (s *JobService) enrichJobWithDeadlineStatus(job *domain.Job) {
	if job == nil || job.Deadline.IsZero() {
		return
	}
	slots, err := s.slotRepo.ListByJobID(job.JobID)
	if err != nil {
		return
	}
	var maxEnd time.Time
	for _, slot := range slots {
		if slot.Status != domain.SlotStatusPlanned && slot.Status != domain.SlotStatusRunning {
			continue
		}
		if slot.ScheduledEnd.After(maxEnd) {
			maxEnd = slot.ScheduledEnd
		}
	}
	if maxEnd.IsZero() {
		return
	}
	tardinessMins := 0
	if maxEnd.After(job.Deadline) {
		tardinessMins = int(maxEnd.Sub(job.Deadline).Minutes())
	}
	job.DeadlineStatus = &domain.JobDeadlineStatus{
		IsLate: tardinessMins > 0,
		LateBy: formatLateByForJob(tardinessMins),
	}
}

// enrichJobsWithDeadlineStatus enriches each job with deadline_status; batches slot queries.
func (s *JobService) enrichJobsWithDeadlineStatus(jobs []domain.Job) {
	jobIDs := make([]string, 0, len(jobs))
	jobMap := make(map[string]*domain.Job)
	for i := range jobs {
		j := &jobs[i]
		if j.Deadline.IsZero() {
			continue
		}
		jobIDs = append(jobIDs, j.JobID)
		jobMap[j.JobID] = j
	}
	if len(jobIDs) == 0 {
		return
	}
	rows, err := s.slotRepo.ListActiveByJobIDs(jobIDs)
	if err != nil {
		return
	}
	maxEndByJob := make(map[string]time.Time)
	for _, r := range rows {
		if r.ScheduledEnd.After(maxEndByJob[r.JobID]) {
			maxEndByJob[r.JobID] = r.ScheduledEnd
		}
	}
	for _, j := range jobMap {
		maxEnd, ok := maxEndByJob[j.JobID]
		if !ok || maxEnd.IsZero() {
			continue
		}
		tardinessMins := 0
		if maxEnd.After(j.Deadline) {
			tardinessMins = int(maxEnd.Sub(j.Deadline).Minutes())
		}
		j.DeadlineStatus = &domain.JobDeadlineStatus{
			IsLate: tardinessMins > 0,
			LateBy: formatLateByForJob(tardinessMins),
		}
	}
}

// formatLateByForJob returns human-readable tardiness or "on time" when not late.
func formatLateByForJob(tardinessMins int) string {
	if tardinessMins <= 0 {
		return "on time"
	}
	return formatLateBy(tardinessMins)
}

func (s *JobService) Update(id string, req dto.UpdateJobRequest) (*domain.Job, error) {
	job, err := s.jobRepo.GetByID(id)
	if err != nil {
		return nil, err
	}
	if req.QuantityTotal != nil {
		job.QuantityTotal = *req.QuantityTotal
	}
	if req.Priority != nil {
		job.Priority = *req.Priority
	}
	if req.Deadline != nil {
		job.Deadline = *req.Deadline
	}
	if req.Status != nil {
		job.Status = *req.Status
	}
	if req.Notes != nil {
		job.Notes = *req.Notes
	}
	job.UpdatedAt = time.Now()
	if err := s.jobRepo.Update(job); err != nil {
		return nil, err
	}
	return s.jobRepo.GetByID(id)
}

func (s *JobService) Delete(id string) error {
	steps, _ := s.stepRepo.ListByJobID(id)
	for _, st := range steps {
		_ = s.slotRepo.DeleteByJobStepID(st.JobStepID)
	}
	_ = s.stepRepo.DeleteByJobID(id)
	return s.jobRepo.Delete(id)
}

func (s *JobService) Duplicate(jobID string, newDeadline time.Time, newQty int) (*domain.Job, error) {
	job, err := s.jobRepo.GetByID(jobID)
	if err != nil {
		return nil, err
	}
	newJob := &domain.Job{
		JobID:             id.NewPrefixed("JOB-"),
		ProductID:         job.ProductID,
		QuantityTotal:     newQty,
		QuantityCompleted: 0,
		Priority:          job.Priority,
		Deadline:          newDeadline,
		Status:            domain.JobStatusPlanned,
		CreatedAt:         time.Now(),
		UpdatedAt:         time.Now(),
		Notes:             job.Notes,
	}
	if newQty <= 0 {
		newJob.QuantityTotal = job.QuantityTotal
	}
	if newDeadline.IsZero() {
		newJob.Deadline = job.Deadline
	}
	if err := s.jobRepo.Create(newJob); err != nil {
		return nil, err
	}
	steps, _ := s.stepRepo.ListByJobID(jobID)
	for _, st := range steps {
		newStep := domain.JobSteps{
			JobStepID:      id.NewPrefixed("JS-"),
			JobID:          newJob.JobID,
			StepID:         st.StepID,
			StepSequence:   st.StepSequence,
			QuantityTarget: newJob.QuantityTotal,
			Status:         domain.JobStepStatusPending,
		}
		_ = s.stepRepo.Create(&newStep)
		slots, _ := s.slotRepo.ListByJobStepID(st.JobStepID)
		for _, sl := range slots {
			newSlot := domain.JobStepScheduleSlots{
				SlotID:                 id.NewPrefixed("SLOT-"),
				JobStepID:              newStep.JobStepID,
				MachineID:              sl.MachineID,
				ScheduledStart:         sl.ScheduledStart,
				ScheduledEnd:           sl.ScheduledEnd,
				QuantityPlanned:        sl.QuantityPlanned,
				PreparationTimeMinutes: sl.PreparationTimeMinutes,
				ProcessingTimeMinutes:  sl.ProcessingTimeMinutes,
				CleaningTimeMinutes:    sl.CleaningTimeMinutes,
				ChangeoverTimeMinutes:  sl.ChangeoverTimeMinutes,
				BufferTimeMinutes:      sl.BufferTimeMinutes,
				Status:                 domain.SlotStatusPlanned,
			}
			_ = s.slotRepo.Create(&newSlot)
		}
	}
	return s.jobRepo.GetByID(newJob.JobID)
}
