package service

import (
	"context"
	"emas/internal/domain"
	"emas/internal/repository"
	"emas/pkg/featureflags"
	"emas/pkg/id"
	"emas/pkg/logger"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"go.uber.org/zap"
)

func logBatchTiming(stage string, fields ...zap.Field) {
	base := []zap.Field{zap.String("stage", stage)}
	base = append(base, fields...)
	logger.L().Info("batch_reschedule_timing", base...)
}

// RescheduleAll cancels active slots and deletes proposals for planned/scheduled
// jobs, then regenerates proposals via ScheduleJobSet. Returns same shape as batch-proposals.
// When dryRun is true: no cancel, no delete, no persist; returns proposals as preview only.
func (s *AIPredictiveService) RescheduleAll(ctx context.Context, orderBy, generatedBy string, dryRun bool) ([]*SchedulingProposal, *BatchProposalSummary, error) {
	jobs, err := s.resolveJobsForReschedule()
	if err != nil {
		return nil, nil, err
	}
	jobIDs := make([]string, 0, len(jobs))
	for _, j := range jobs {
		jobIDs = append(jobIDs, j.JobID)
	}
	if !dryRun {
		for _, jobID := range jobIDs {
			slots, _ := s.slotRepo.ListByJobID(jobID)
			for _, slot := range slots {
				if slot.Status == domain.SlotStatusPlanned || slot.Status == domain.SlotStatusRunning {
					slot.Status = domain.SlotStatusCancelled
					_ = s.slotRepo.Update(&slot)
				}
			}
		}
		if s.proposalRepo != nil {
			for _, jobID := range jobIDs {
				_ = s.proposalRepo.DeleteByJobID(jobID)
			}
		}
	}
	lockFloor := s.rescheduleLockFloor()
	return s.ScheduleJobSet(ctx, jobIDs, generatedBy, orderBy, &ScheduleJobSetOpts{
		IncludeJobsWithActiveSlots: dryRun,
		PersistProposals:           !dryRun,
		EarliestStartFloor:         lockFloor,
	})
}

func (s *AIPredictiveService) resolveJobsForReschedule() ([]domain.Job, error) {
	all, err := s.jobRepo.ListAll()
	if err != nil {
		return nil, err
	}
	// DB-backed lock-in window (minutes). Default: 4h.
	const lockInKey = "scheduling.lock_in_window_minutes"
	lockMins := 240
	if s.settingsRepo != nil {
		if v, err := s.settingsRepo.GetInt(lockInKey, lockMins); err == nil {
			lockMins = v
		}
	}
	lockUntil := time.Now().Add(time.Duration(lockMins) * time.Minute)

	result := make([]domain.Job, 0)
	for _, job := range all {
		if job.Status == domain.JobStatusPlanned || job.Status == domain.JobStatusScheduled {
			earliest, _ := s.slotRepo.GetEarliestActiveStartByJobID(job.JobID)
			if earliest != nil && !earliest.After(lockUntil) {
				// Lock-in: do not reshuffle imminent jobs with active slots starting soon.
				continue
			}
			result = append(result, job)
		}
	}
	return result, nil
}

func (s *AIPredictiveService) rescheduleLockFloor() *time.Time {
	const lockInKey = "scheduling.lock_in_window_minutes"
	lockMins := 240
	if s.settingsRepo != nil {
		if v, err := s.settingsRepo.GetInt(lockInKey, lockMins); err == nil {
			lockMins = v
		}
	}
	floor := roundUpToHalfHour(time.Now().UTC().Add(time.Duration(lockMins) * time.Minute))
	return &floor
}

// ScheduleJobSetOpts configures ScheduleJobSet behavior.
type ScheduleJobSetOpts struct {
	IncludeJobsWithActiveSlots bool // when true, include jobs that have planned/running slots (for preview)
	PersistProposals           bool // when false, do not write to DB (preview mode)
	EarliestStartFloor         *time.Time
	IncludeInventoryActions    bool
}

// ScheduleJobSet schedules a set of jobs in priority order, using shared machine
// state (tentative slots from earlier jobs in the batch). Jobs are filtered to
// planned/scheduled with no active slots (unless opts.IncludeJobsWithActiveSlots),
// sorted by orderBy (edd/epo/fifo/readiness/material_priority/weighted_tardiness_material/product_deadline_fifo), and each proposal is persisted
// (unless opts.PersistProposals is false).
func (s *AIPredictiveService) ScheduleJobSet(ctx context.Context, jobIDs []string, generatedBy, orderBy string, opts *ScheduleJobSetOpts) ([]*SchedulingProposal, *BatchProposalSummary, error) {
	batchStarted := time.Now()
	if s != nil && s.batchMu != nil {
		s.batchMu.Lock()
		defer s.batchMu.Unlock()
	}
	if s.scheduling != nil {
		cloned := *s
		cloned.scheduling = s.scheduling.WithRuntimeCache()
		s = &cloned
	}
	if opts == nil {
		opts = &ScheduleJobSetOpts{PersistProposals: true}
	}
	if opts.PersistProposals && s.proposalRepo == nil {
		return nil, nil, newSchedulingActionError(500, "proposal repository is not configured")
	}

	jobs, err := s.resolveAndFilterJobs(jobIDs, opts.IncludeJobsWithActiveSlots)
	if err != nil {
		return nil, nil, err
	}

	timeoutMs := featureflags.AdaptiveBatchTimeoutMs(featureflags.BatchTimeoutMs(), len(jobs))
	ctx, cancel := context.WithTimeout(ctx, time.Duration(timeoutMs)*time.Millisecond)
	defer cancel()

	summary := &BatchProposalSummary{Generated: 0, Blocked: 0, Skipped: len(jobs)}
	readinessAt := computeReadinessForJobs(s.scheduling, jobs)
	sortJobsByOrder(jobs, orderBy, readinessAt)

	deadlineByJobID := make(map[string]time.Time, len(jobs))
	selectedJobIDs := make(map[string]bool, len(jobs))
	for _, j := range jobs {
		deadlineByJobID[j.JobID] = j.Deadline
		selectedJobIDs[j.JobID] = true
	}

	tentativeSlots := make([]TentativeSlot, 0)
	// Reserve machine time from active slots of jobs that are NOT in this scheduling set
	// so generated proposals do not conflict with lock-in/running jobs.
	activeRows, err := s.slotRepo.ListActiveByJobIDs(nil)
	if err != nil {
		return nil, nil, err
	}
	baseTentativeSlots := tentativeSlotsFromActiveRows(activeRows, selectedJobIDs)
	tentativeSlots = append(tentativeSlots, baseTentativeSlots...)
	proposals := make([]*SchedulingProposal, 0, len(jobs))
	completionTargets := computeCompletionTargets(s, jobs)
	batchState := newSubproductBatchState(s)

	// Ensure that material availability calculations exclude existing reservations
	// for jobs currently being re-planned in this batch. Failure to do so leads to
	// double-counting their demand (once from the legacy DB row and once from the batch plan).
	var excludedList []string
	for jid := range selectedJobIDs {
		excludedList = append(excludedList, jid)
	}
	batchState.ledger.excludedJobIDs = excludedList

	// Material feasibility must be driven by real on-hand stock, pending arrivals,
	// and reservations in the shared batch ledger. Do not seed virtual stock here:
	// it hides genuine shortages and lets lower-priority jobs consume material that
	// does not exist anywhere in the planning timeline.
	for rootIndex, job := range jobs {
		select {
		case <-ctx.Done():
			return proposals, summary, ctx.Err()
		default:
		}

		jobStarted := time.Now()
		previewStarted := time.Now()

		preview, snapshotJSON, snapshotHash, err := s.buildProposalSnapshotWithTentative(job.JobID, tentativeSlots, opts.EarliestStartFloor)
		if err != nil {
			summary.Blocked++
			logger.L().Warn("batch_proposal_preview_failed", zap.String("job_id", job.JobID), zap.Error(err))
			continue
		}
		previewElapsed := time.Since(previewStarted)

		targetCompletion := completionTargets[job.JobID]
		proposalStarted := time.Now()
		proposal, err := s.buildProposalForPreview(&job, preview, tentativeSlots, targetCompletion)
		if err != nil {
			summary.Blocked++
			logger.L().Warn("batch_proposal_build_failed", zap.String("job_id", job.JobID), zap.Error(err))
			continue
		}
		proposalElapsed := time.Since(proposalStarted)
		finalizeStarted := time.Now()
		proposal, err = s.finalizeProposalPlan(&job, preview, proposal, proposalBuildOptions{
			BatchState:              batchState,
			RootOrderIndex:          rootIndex,
			IncludeInventoryActions: true,
			TargetCompletion:        targetCompletion,
			TentativeSlots:          tentativeSlots,
		})
		if err != nil {
			summary.Blocked++
			logger.L().Warn("batch_subproduct_plan_failed", zap.String("job_id", job.JobID), zap.Error(err))
			continue
		}
		finalizeElapsed := time.Since(finalizeStarted)
		enrichStarted := time.Now()
		snapshotJSON, snapshotHash, err = enrichSnapshotWithProposalPlan(snapshotJSON, proposal)
		if err != nil {
			summary.Blocked++
			logger.L().Warn("batch_snapshot_enrich_failed", zap.String("job_id", job.JobID), zap.Error(err))
			continue
		}
		enrichElapsed := time.Since(enrichStarted)
		validateStarted := time.Now()
		if err := s.validateProposalSlotsStrict(job.JobID, proposal); err != nil {
			// buildProposalForPreview can emit slots that drift past the global work template (e.g. 17:05
			// vs settings 08:00–17:00) or past shift after heuristics. Repair before failing the batch.
			targetByJob := map[string]*time.Time{}
			if targetCompletion != nil {
				targetByJob[proposal.JobID] = targetCompletion
			}
			if rerr := s.chainAwareForwardRepair([]*SchedulingProposal{proposal}, chainRepairPassBudget([]*SchedulingProposal{proposal}), tentativeSlots, targetByJob); rerr != nil {
				return nil, nil, rerr
			}
			if err := s.validateProposalSlotsStrict(job.JobID, proposal); err != nil {
				return nil, nil, err
			}
		}
		validateElapsed := time.Since(validateStarted)

		version := 1
		persistElapsed := time.Duration(0)
		persistStarted := time.Time{}
		if opts.PersistProposals && s.proposalRepo != nil {
			persistStarted = time.Now()
			var verErr error
			version, verErr = s.proposalRepo.NextVersion(job.JobID)
			if verErr != nil {
				summary.Blocked++
				logger.L().Warn("batch_proposal_version_failed", zap.String("job_id", job.JobID), zap.Error(verErr))
				continue
			}
		}

		proposalID := id.NewPrefixed(id.PrefixAIProposal)
		proposal.ProposalID = proposalID
		proposal.Version = version
		proposal.Status = domain.AIProposalStatusDraft
		proposal.SnapshotHash = snapshotHash

		if opts.PersistProposals && s.proposalRepo != nil {
			now := time.Now().UTC()
			record := &domain.AIProposal{
				ProposalID:            proposalID,
				JobID:                 job.JobID,
				Version:               version,
				Status:                domain.AIProposalStatusDraft,
				RolloutState:          featureflags.RolloutState(),
				Engine:                proposal.Engine,
				EngineVersion:         proposal.EngineVersion,
				ObjectiveScore:        proposal.ObjectiveScore,
				ShadowEngine:          proposal.ShadowEngine,
				ShadowObjectiveScore:  proposal.ShadowObjectiveScore,
				FallbackReason:        proposal.FallbackReason,
				InputHash:             snapshotHash,
				SummaryText:           joinStrings(proposal.Summary),
				GeneratedBy:           defaultActor(generatedBy),
				GeneratedAt:           now,
				CreatedAt:             now,
				UpdatedAt:             now,
				SnapshotJSON:          snapshotJSON,
				ProposalJSON:          mustJSON(canonicalProposalForPersistence(proposal)),
				ShadowProposalJSON:    "",
				EstimatedCompletionAt: proposal.EstimatedCompletion,
				OutcomeStatus:         "pending_execution",
			}

			if err := s.proposalRepo.Create(record); err != nil {
				summary.Blocked++
				logger.L().Warn("batch_proposal_create_failed", zap.String("job_id", job.JobID), zap.Error(err))
				continue
			}

			if err := s.proposalRepo.MarkOtherDraftsStale(job.JobID, proposalID, now); err != nil {
				// non-fatal
				logger.L().Warn("batch_proposal_stale_mark_failed", zap.String("job_id", job.JobID), zap.Error(err))
			}
			persistElapsed = time.Since(persistStarted)
		}

		proposals = append(proposals, proposal)
		summary.Generated++
		summary.Skipped--

		for _, ps := range proposal.ProposedSlots {
			tentativeSlots = append(tentativeSlots, TentativeSlot{
				MachineID:      ps.MachineID,
				ScheduledStart: ps.ScheduledStart,
				ScheduledEnd:   ps.ScheduledEnd,
			})
		}
		for _, dep := range proposal.DependentJobs {
			for _, ps := range dep.ProposedSlots {
				tentativeSlots = append(tentativeSlots, TentativeSlot{
					MachineID:      ps.MachineID,
					ScheduledStart: ps.ScheduledStart,
					ScheduledEnd:   ps.ScheduledEnd,
				})
			}
		}

		if s.metrics != nil {
			s.metrics.Inc(&s.metrics.ProposalGenerated)
		}

		logger.L().Info("batch_proposal_generated",
			zap.String("proposal_id", proposalID),
			zap.String("job_id", job.JobID),
			zap.String("engine", proposal.Engine),
			zap.String("generated_by", defaultActor(generatedBy)),
		)
		logBatchTiming("job_pipeline",
			zap.String("job_id", job.JobID),
			zap.Int("root_order_index", rootIndex),
			zap.Int("preview_steps", len(preview.Steps)),
			zap.Int("proposed_slots", len(proposal.ProposedSlots)),
			zap.Int("dependent_jobs", len(proposal.DependentJobs)),
			zap.Duration("preview_elapsed", previewElapsed),
			zap.Duration("proposal_elapsed", proposalElapsed),
			zap.Duration("finalize_elapsed", finalizeElapsed),
			zap.Duration("enrich_elapsed", enrichElapsed),
			zap.Duration("validate_elapsed", validateElapsed),
			zap.Duration("persist_elapsed", persistElapsed),
			zap.Duration("job_elapsed", time.Since(jobStarted)),
			zap.Int("tentative_slots_after", len(tentativeSlots)),
		)
	}
	generationBlocked := summary.Blocked

	// Rebalance by deadline pressure before final conflict repair.
	rebalanceStarted := time.Now()
	rebalanceByDeadlinePressure(proposals, deadlineByJobID)
	logBatchTiming("rebalance_by_deadline_pressure",
		zap.Int("proposal_count", len(proposals)),
		zap.Duration("elapsed", time.Since(rebalanceStarted)),
	)
	// Repair any machine overlaps (safety net when workload is high).
	repairStarted := time.Now()
	if repaired := repairOverlapsInProposals(proposals); repaired {
		if err := s.repairAndValidateBatchProposals(proposals); err != nil {
			return nil, nil, err
		}
	}
	logBatchTiming("repair_overlaps",
		zap.Int("proposal_count", len(proposals)),
		zap.Duration("elapsed", time.Since(repairStarted)),
	)
	if opts.PersistProposals && s.proposalRepo != nil {
		updateStarted := time.Now()
		for _, p := range proposals {
			record, err := s.proposalRepo.GetByID(p.ProposalID)
			if err != nil {
				return nil, nil, err
			}
			record.ProposalJSON = mustJSON(p)
			record.UpdatedAt = time.Now().UTC()
			if err := s.proposalRepo.Update(record); err != nil {
				return nil, nil, err
			}
			if s.scheduling != nil {
				if err := s.scheduling.CaptureMLTrainingEventForProposalRecord(record, p); err != nil {
					logger.L().Warn("batch_proposal_ml_training_capture_failed",
						zap.String("proposal_id", p.ProposalID),
						zap.String("job_id", p.JobID),
						zap.Error(err),
					)
				}
			}
		}
		logBatchTiming("persist_final_proposal_updates",
			zap.Int("proposal_count", len(proposals)),
			zap.Duration("elapsed", time.Since(updateStarted)),
		)
	}
	if machines := overlappingMachinesInProposals(proposals); len(machines) > 0 {
		logProposalStage(proposals, "pre_linearize")
		linearizeOverlapsByMachine(proposals)
		logProposalStage(proposals, "post_linearize")
	}
	if err := s.repairAndValidateBatchProposals(proposals); err != nil {
		return nil, nil, err
	}
	if machines := overlappingMachinesInProposals(proposals); len(machines) > 0 {
		return nil, nil, newSchedulingActionError(422, "internal scheduling validation failed (reason_code=overlap_unresolved): proposal overlaps remain on machines "+strings.Join(machines, ", "))
	}
	if err := s.refreshInventoryPlansForFinalSlots(proposals, jobs, baseTentativeSlots, completionTargets, excludedList); err != nil {
		return nil, nil, err
	}
	tentativeSlots = rebuildTentativeSlots(baseTentativeSlots, proposals)

	enrichProposalsWithDeadlineStatus(proposals, summary, deadlineByJobID)
	// Run the convergence loop: up to maxConvergencePasses full re-evaluations
	// using the real planner pipeline so the returned aggregates are stable and
	// one-shot apply by the frontend drives infeasible_count to 0.
	var convPasses int
	summary.MaterialReplenishmentAggregate, convPasses =
		s.convergeBatchShortageAggregates(proposals, tentativeSlots, completionTargets, excludedList)
	// Defensive promotion: the UI should never need to fall back to per-proposal
	// material cards when proposals still carry actionable material shortage
	// resolutions. This also catches stable convergence states where the final
	// proposal pass exposes a child-material shortage after the aggregate pass.
	if proposalMaterialAgg := s.buildBatchMaterialAggregateFromResolutionOptions(proposals); len(proposalMaterialAgg) > 0 {
		summary.MaterialReplenishmentAggregate = mergeMatAggMax(summary.MaterialReplenishmentAggregate, proposalMaterialAgg)
	}
	summary.MaterialAccelerationAggregate = s.buildBatchMaterialAggregateFromAccelerationNeeds(proposals)
	summary.Blocked = generationBlocked + countInfeasibleBatchProposals(proposals)
	// #region agent log
	{
		infeasibleIDs := make([]string, 0)
		detail := make([]map[string]any, 0, len(proposals))
		for _, p := range proposals {
			if p == nil || p.Feasible {
				continue
			}
			infeasibleIDs = append(infeasibleIDs, p.JobID)
			optTypes := make(map[string]struct{})
			for _, r := range p.ShortageResolutions {
				optTypes[strings.ToLower(strings.TrimSpace(r.OptionType))] = struct{}{}
			}
			typeList := make([]string, 0, len(optTypes))
			for t := range optTypes {
				typeList = append(typeList, t)
			}
			sort.Strings(typeList)
			matIDs := make([]string, 0, len(p.MaterialShortages))
			for _, sh := range p.MaterialShortages {
				matIDs = append(matIDs, sh.MaterialID)
			}
			detail = append(detail, map[string]any{
				"job_id":                           p.JobID,
				"blocked_reasons":                  p.BlockedReasons,
				"shortage_resolution_option_types": typeList,
				"material_shortage_material_ids":   matIDs,
				"shortage_resolutions_len":         len(p.ShortageResolutions),
			})
		}
		sort.Strings(infeasibleIDs)
		matLines := make([]map[string]any, 0, len(summary.MaterialReplenishmentAggregate))
		for _, m := range summary.MaterialReplenishmentAggregate {
			matLines = append(matLines, map[string]any{
				"material_id":              m.MaterialID,
				"recommended_qty":          m.RecommendedQty,
				"suggested_arrive_rfc3339": m.SuggestedArriveAt.UTC().Format(time.RFC3339),
				"affected_job_count":       len(m.AffectedJobIDs),
			})
		}
		agentDebugNDJSON("BATCH", "multi_job_scheduler.ScheduleJobSet", "batch_infeasible_and_aggregates", map[string]any{
			"generated":                        summary.Generated,
			"blocked":                          summary.Blocked,
			"infeasible_count":                 len(infeasibleIDs),
			"infeasible_job_ids":               infeasibleIDs,
			"material_replenishment_aggregate": matLines,
			"material_acceleration_count":      len(summary.MaterialAccelerationAggregate),
			"infeasible_detail":                detail,
			"convergence_passes":               convPasses,
		})
	}
	// #endregion
	sort.SliceStable(proposals, func(i, j int) bool {
		if proposals[i] == nil || proposals[j] == nil {
			return false
		}
		if proposals[i].Feasible != proposals[j].Feasible {
			return proposals[i].Feasible && !proposals[j].Feasible
		}
		di := deadlineByJobID[proposals[i].JobID]
		dj := deadlineByJobID[proposals[j].JobID]
		if !di.Equal(dj) {
			return di.Before(dj)
		}
		return proposals[i].JobID < proposals[j].JobID
	})
	response := make([]*SchedulingProposal, 0, len(proposals))
	for _, proposal := range proposals {
		response = append(response, stripInventoryActionsForResponse(proposal, opts.IncludeInventoryActions))
	}
	logBatchTiming("schedule_job_set_total",
		zap.Int("requested_jobs", len(jobIDs)),
		zap.Int("resolved_jobs", len(jobs)),
		zap.Int("generated", summary.Generated),
		zap.Int("blocked", summary.Blocked),
		zap.Int("skipped", summary.Skipped),
		zap.Int("final_tentative_slots", len(tentativeSlots)),
		zap.Duration("elapsed", time.Since(batchStarted)),
	)
	return response, summary, nil
}

func countInfeasibleBatchProposals(proposals []*SchedulingProposal) int {
	n := 0
	for _, p := range proposals {
		if p != nil && !p.Feasible {
			n++
		}
	}
	return n
}

func (s *AIPredictiveService) refreshInventoryPlansForFinalSlots(proposals []*SchedulingProposal, jobs []domain.Job, baseTentative []TentativeSlot, completionTargets map[string]*time.Time, excludedJobIDs []string) error {
	if s == nil || s.scheduling == nil || len(proposals) == 0 {
		return nil
	}
	sortProposalsByJobOrder(proposals, jobs)
	jobsByID := make(map[string]*domain.Job, len(jobs))
	for i := range jobs {
		jobsByID[jobs[i].JobID] = &jobs[i]
	}
	batchState := newSubproductBatchState(s)
	batchState.ledger.excludedJobIDs = append([]string(nil), excludedJobIDs...)
	committedTentatives := append([]TentativeSlot(nil), baseTentative...)
	previewCache := make(map[string]*SolverPreview, len(proposals))

	for i, proposal := range proposals {
		if proposal == nil {
			continue
		}
		job := jobsByID[proposal.JobID]
		if job == nil {
			loaded, err := s.scheduling.getJobByID(proposal.JobID)
			if err != nil || loaded == nil {
				continue
			}
			job = loaded
		}
		preview := previewCache[proposal.JobID]
		if preview == nil {
			loaded, err := s.scheduling.BuildSolverPreviewWithTentativeSlotsAndFloor(proposal.JobID, committedTentatives, nil)
			if err != nil || loaded == nil {
				continue
			}
			preview = loaded
			previewCache[proposal.JobID] = preview
		}

		candidate := shallowCloneProposal(proposal)
		candidate.BlockedReasons = materialIndependentBlockedReasons(candidate.BlockedReasons)
		candidate.Feasible = len(candidate.BlockedReasons) == 0
		targetCompletion := completionTargets[proposal.JobID]
		attemptState := batchState.clone()
		analysisLedger := attemptState.ledger.clone()

		if err := s.decorateProposalWithInventoryPlan(job, preview, candidate, committedTentatives, attemptState, i, targetCompletion); err != nil {
			return err
		}
		shortages, resolutions, score, err := s.analyzeProposalMaterialShortages(candidate, analysisLedger)
		if err != nil {
			return err
		}
		candidate.MaterialShortages = shortages
		candidate.ShortageResolutions = resolutions
		candidate.GlobalScore = score

		nonMaterialBlocked := materialIndependentBlockedReasons(candidate.BlockedReasons)
		candidate.Feasible = len(nonMaterialBlocked) == 0
		for _, sh := range shortages {
			if !sh.AllStepMaterialsFeasible {
				candidate.Feasible = false
				nonMaterialBlocked = appendUniqueString(nonMaterialBlocked, "reason_code=material_shortage")
				break
			}
		}
		candidate.BlockedReasons = nonMaterialBlocked
		candidate.InventoryActionCount = len(candidate.InventoryActions)
		proposals[i] = candidate

		if candidate.Feasible {
			batchState.ledger = attemptState.ledger
			batchState.totalGeneratedNodes = attemptState.totalGeneratedNodes
		}
		committedTentatives = append(committedTentatives, proposedSlotsToTentatives(candidate.ProposedSlots)...)
		for _, dep := range candidate.DependentJobs {
			committedTentatives = append(committedTentatives, proposedSlotsToTentatives(dep.ProposedSlots)...)
		}
	}
	return nil
}

func sortProposalsByJobOrder(proposals []*SchedulingProposal, jobs []domain.Job) {
	if len(proposals) == 0 || len(jobs) == 0 {
		return
	}
	order := make(map[string]int, len(jobs))
	for i := range jobs {
		order[jobs[i].JobID] = i
	}
	missingBase := len(jobs) + len(proposals)
	sort.SliceStable(proposals, func(i, j int) bool {
		if proposals[i] == nil || proposals[j] == nil {
			return proposals[i] != nil
		}
		oi, ok := order[proposals[i].JobID]
		if !ok {
			oi = missingBase + i
		}
		oj, ok := order[proposals[j].JobID]
		if !ok {
			oj = missingBase + j
		}
		if oi != oj {
			return oi < oj
		}
		return proposals[i].JobID < proposals[j].JobID
	})
}

func materialIndependentBlockedReasons(reasons []string) []string {
	out := make([]string, 0, len(reasons))
	for _, reason := range reasons {
		if strings.Contains(reason, "material_shortage") {
			continue
		}
		out = appendUniqueString(out, reason)
	}
	return out
}

func rebuildTentativeSlots(base []TentativeSlot, proposals []*SchedulingProposal) []TentativeSlot {
	out := append([]TentativeSlot(nil), base...)
	for _, proposal := range proposals {
		if proposal == nil {
			continue
		}
		out = append(out, proposedSlotsToTentatives(proposal.ProposedSlots)...)
		for _, dep := range proposal.DependentJobs {
			out = append(out, proposedSlotsToTentatives(dep.ProposedSlots)...)
		}
	}
	return out
}

func (s *AIPredictiveService) validateProposalSlotsStrict(jobID string, proposal *SchedulingProposal) error {
	if proposal == nil {
		return nil
	}
	ignoreMinSplitByStep := temporalSliceProposalStepIDs(proposal)
	slots := make([]ProposedSlot, len(proposal.ProposedSlots))
	copy(slots, proposal.ProposedSlots)
	sort.SliceStable(slots, func(i, j int) bool {
		if slots[i].ScheduledStart.Equal(slots[j].ScheduledStart) {
			return slots[i].JobStepID < slots[j].JobStepID
		}
		return slots[i].ScheduledStart.Before(slots[j].ScheduledStart)
	})
	var prevEnd time.Time
	for _, slot := range slots {
		if slot.JobStepID == "" || slot.MachineID == "" {
			continue
		}
		processStep, err := s.scheduling.GetProcessStepForJobStep(slot.JobStepID)
		if err != nil {
			return newSchedulingActionError(422, fmt.Sprintf("proposal slot validation failed (job_id=%s, step=%s): %v", jobID, slot.JobStepID, err))
		}
		if !prevEnd.IsZero() && slot.ScheduledStart.Before(prevEnd) {
			return newSchedulingActionError(422, fmt.Sprintf("reason_code=calendar_or_constraint_blocked proposal slot invalid (job_id=%s, step=%s, machine=%s, start=%s, end=%s): step precedence violated in proposal chain", jobID, slot.JobStepID, slot.MachineID, slot.ScheduledStart.In(time.Local).Format(time.RFC3339), slot.ScheduledEnd.In(time.Local).Format(time.RFC3339)))
		}
		validation, err := s.scheduling.validateSlotCoreResultForStepWithOptions(processStep, slot.MachineID, slot.ScheduledStart, slot.ScheduledEnd, maxInt(slot.QuantityPlanned, 1), "", SlotValidationOptions{IgnoreMinSplitQty: ignoreMinSplitByStep[slot.JobStepID]})
		if err != nil {
			return newSchedulingActionError(422, fmt.Sprintf("proposal slot validation failed (job_id=%s, step=%s, machine=%s, start=%s, end=%s): %v", jobID, slot.JobStepID, slot.MachineID, slot.ScheduledStart.UTC().Format(time.RFC3339), slot.ScheduledEnd.UTC().Format(time.RFC3339), err))
		}
		if !validation.Valid {
			reason := "invalid slot (core validation)"
			if len(validation.Reasons) > 0 {
				reason = validation.Reasons[0]
			}
			return newSchedulingActionError(422, fmt.Sprintf("reason_code=calendar_or_constraint_blocked proposal slot invalid (job_id=%s, step=%s, machine=%s, start=%s, end=%s): %s", jobID, slot.JobStepID, slot.MachineID, slot.ScheduledStart.In(time.Local).Format(time.RFC3339), slot.ScheduledEnd.In(time.Local).Format(time.RFC3339), reason))
		}
		if slot.ScheduledEnd.After(prevEnd) {
			prevEnd = slot.ScheduledEnd
		}
	}
	return nil
}

func temporalSliceProposalStepIDs(proposal *SchedulingProposal) map[string]bool {
	ignore := make(map[string]bool)
	if proposal == nil || len(proposal.ProposedSlots) <= 1 {
		return ignore
	}
	type stepGroup struct {
		count       int
		hasParallel bool
	}
	groups := make(map[string]stepGroup)
	for _, slot := range proposal.ProposedSlots {
		if slot.JobStepID == "" {
			continue
		}
		group := groups[slot.JobStepID]
		group.count++
		group.hasParallel = group.hasParallel || slot.IsParallel
		groups[slot.JobStepID] = group
	}
	for jobStepID, group := range groups {
		if group.count > 1 && !group.hasParallel {
			ignore[jobStepID] = true
		}
	}
	return ignore
}

func (s *AIPredictiveService) firstProposalConflict(proposal *SchedulingProposal, allProposals []*SchedulingProposal, extraTentative []TentativeSlot) (int, string, error) {
	if proposal == nil {
		return -1, "", nil
	}
	ignoreMinSplitByStep := temporalSliceProposalStepIDs(proposal)
	prevEnd := time.Time{}
	for i := range proposal.ProposedSlots {
		slot := proposal.ProposedSlots[i]
		if slot.JobStepID == "" || slot.MachineID == "" {
			if slot.ScheduledEnd.After(prevEnd) {
				prevEnd = slot.ScheduledEnd
			}
			continue
		}
		processStep, err := s.scheduling.GetProcessStepForJobStep(slot.JobStepID)
		if err != nil {
			return i, "missing process step", err
		}
		if !prevEnd.IsZero() && slot.ScheduledStart.Before(prevEnd) {
			return i, "step precedence violated in proposal chain", nil
		}

		// NEW: Explicitly check against other in-memory proposals
		repairBusy := tentativesForChainRepair(extraTentative, allProposals, proposal, i)
		for _, busy := range repairBusy {
			if slot.MachineID == busy.MachineID && slot.ScheduledStart.Before(busy.ScheduledEnd) && slot.ScheduledEnd.After(busy.ScheduledStart) {
				return i, "overlaps with another in-memory slot in the batch", nil
			}
		}

		validation, err := s.scheduling.validateSlotCoreResultForStepWithOptions(processStep, slot.MachineID, slot.ScheduledStart, slot.ScheduledEnd, maxInt(slot.QuantityPlanned, 1), "", SlotValidationOptions{IgnoreMinSplitQty: ignoreMinSplitByStep[slot.JobStepID]})
		if err != nil {
			return i, "slot validation failed", err
		}
		if !validation.Valid {
			reason := "invalid slot (core validation)"
			if len(validation.Reasons) > 0 {
				reason = validation.Reasons[0]
			}
			return i, reason, nil
		}
		if slot.ScheduledEnd.After(prevEnd) {
			prevEnd = slot.ScheduledEnd
		}
	}
	return -1, "", nil
}

func (s *AIPredictiveService) validateBatchProposalSlotsStrict(proposals []*SchedulingProposal) error {
	for _, p := range proposals {
		if p == nil {
			continue
		}
		if err := s.validateProposalSlotsStrict(p.JobID, p); err != nil {
			return err
		}
	}
	return nil
}

func (s *AIPredictiveService) repairAndValidateBatchProposals(proposals []*SchedulingProposal) error {
	if err := s.validateBatchProposalSlotsStrict(proposals); err == nil {
		return nil
	}
	if err := s.chainAwareForwardRepair(proposals, chainRepairPassBudget(proposals), nil, nil); err != nil {
		return err
	}
	if err := s.validateBatchProposalSlotsStrict(proposals); err != nil {
		return err
	}
	return nil
}

// tentativesForChainRepair returns extra tentative occupancy plus already-fixed proposal slots
// that should block the slot currently being repaired.
//
// For the proposal under repair, only slots before currentIndex are treated as fixed blockers.
// Downstream slots in the same proposal are intentionally excluded because they will be shifted
// later in the same repair pass.
func tentativesForChainRepair(extra []TentativeSlot, proposals []*SchedulingProposal, currentProposal *SchedulingProposal, currentIndex int) []TentativeSlot {
	n := len(extra)
	for _, p := range proposals {
		if p == nil {
			continue
		}
		limit := len(p.ProposedSlots)
		if p == currentProposal {
			if currentIndex < 0 {
				limit = 0
			} else if currentIndex < limit {
				limit = currentIndex
			}
		}
		for i := 0; i < limit; i++ {
			ps := &p.ProposedSlots[i]
			if ps.MachineID == "" {
				continue
			}
			n++
		}
	}
	out := make([]TentativeSlot, 0, n)
	out = append(out, extra...)
	for _, p := range proposals {
		if p == nil {
			continue
		}
		limit := len(p.ProposedSlots)
		if p == currentProposal {
			if currentIndex < 0 {
				limit = 0
			} else if currentIndex < limit {
				limit = currentIndex
			}
		}
		for i := 0; i < limit; i++ {
			ps := &p.ProposedSlots[i]
			if ps.MachineID == "" {
				continue
			}
			out = append(out, TentativeSlot{
				MachineID:      ps.MachineID,
				ScheduledStart: ps.ScheduledStart,
				ScheduledEnd:   ps.ScheduledEnd,
			})
		}
	}
	return out
}

func (s *AIPredictiveService) chainAwareForwardRepair(proposals []*SchedulingProposal, maxPasses int, batchExtraTentative []TentativeSlot, targetCompletionByJob map[string]*time.Time) error {
	if maxPasses <= 0 {
		maxPasses = chainRepairPassBudget(proposals)
	}
	minStart := map[string]time.Time{}
	signatures := map[string]bool{}
	lastConflict := ""
	s.sortProposalsForRepair(proposals)
	for pass := 0; pass < maxPasses; pass++ {
		signature := proposalStateSignature(proposals)
		if signatures[signature] {
			return newSchedulingActionError(422, "reason_code="+repairLimitExceededReasonCode+" chain repair cycle detected")
		}
		signatures[signature] = true
		changed := false
		for _, p := range proposals {
			if p == nil || len(p.ProposedSlots) == 0 {
				continue
			}
			sort.SliceStable(p.ProposedSlots, func(i, j int) bool {
				if p.ProposedSlots[i].ScheduledStart.Equal(p.ProposedSlots[j].ScheduledStart) {
					return p.ProposedSlots[i].StepID < p.ProposedSlots[j].StepID
				}
				return p.ProposedSlots[i].ScheduledStart.Before(p.ProposedSlots[j].ScheduledStart)
			})
			conflictIdx, conflictReason, err := s.firstProposalConflict(p, proposals, batchExtraTentative)
			if err != nil {
				return err
			}
			if conflictIdx < 0 {
				continue
			}
			ignoreMinSplitByStep := temporalSliceProposalStepIDs(p)
			slot := p.ProposedSlots[conflictIdx]
			lastConflict = fmt.Sprintf("job_id=%s step=%s machine=%s start=%s end=%s", p.JobID, slot.JobStepID, slot.MachineID, slot.ScheduledStart.In(time.Local).Format(time.RFC3339), slot.ScheduledEnd.In(time.Local).Format(time.RFC3339))
			if strings.TrimSpace(conflictReason) != "" {
				lastConflict += " reason=" + conflictReason
			}
			var predecessorEnd *time.Time
			if conflictIdx > 0 {
				pe := p.ProposedSlots[conflictIdx-1].ScheduledEnd
				predecessorEnd = &pe
			}
			for i := conflictIdx; i < len(p.ProposedSlots); i++ {
				slot := &p.ProposedSlots[i]
				beforeStart := slot.ScheduledStart
				beforeEnd := slot.ScheduledEnd
				duration := slot.ScheduledEnd.Sub(slot.ScheduledStart)
				lbKey := slot.JobStepID + "|" + slot.MachineID
				searchStart := slot.ScheduledStart
				if lb, ok := minStart[lbKey]; ok && lb.After(searchStart) {
					searchStart = lb
				}
				if predecessorEnd != nil && predecessorEnd.After(searchStart) {
					searchStart = *predecessorEnd
				}
				processStep, err := s.scheduling.GetProcessStepForJobStep(slot.JobStepID)
				if err != nil || processStep == nil {
					return newSchedulingActionError(422, fmt.Sprintf("reason_code=no_feasible_window missing process step for job_step=%s", slot.JobStepID))
				}
				repairBusy := tentativesForChainRepair(batchExtraTentative, proposals, p, i)
				repairHorizonEnd := chainRepairHorizonEnd(p, slot.ScheduledStart, targetCompletionByJob[p.JobID])
				var (
					start   time.Time
					ok      bool
					reasons []string
					diag    map[string]interface{}
				)
				tryStart := searchStart
				maxRetries := 3
				for retry := 0; retry < maxRetries; retry++ {
					start, ok, reasons, diag = s.scheduling.findFeasibleMachineStartWithOptions(
						slot.JobStepID,
						slot.MachineID,
						processStep,
						tryStart,
						duration,
						maxInt(slot.QuantityPlanned, 1),
						"",
						repairBusy,
						predecessorEnd,
						repairHorizonEnd,
						SlotValidationOptions{IgnoreMinSplitQty: ignoreMinSplitByStep[slot.JobStepID]},
					)
					if ok {
						break
					}
					tryStart = s.scheduling.nextWorkWindowStartFromSettings(tryStart.Add(schedulerSlotGranularity))
				}
				if !ok {
					details := ""
					if len(reasons) > 0 {
						details = reasons[0]
					}
					return newSchedulingActionError(422, fmt.Sprintf("reason_code=%s chain-repair failed (job_id=%s, step=%s, machine=%s, details=%s, attempted_horizon=%v)", repairLimitExceededReasonCode, p.JobID, slot.JobStepID, slot.MachineID, details, diag))
				}
				// Never clamp start back to the old ScheduledStart without re-searching: that can force
				// [start, start+duration] outside machine shift / global template while staying "feasible"
				// in the repairer's eyes, causing apply-time calendar_outside_shift.
				chosen := start
				if chosen.Before(slot.ScheduledStart) {
					anchored, ok2, _, _ := s.scheduling.findFeasibleMachineStartWithOptions(
						slot.JobStepID,
						slot.MachineID,
						processStep,
						slot.ScheduledStart,
						duration,
						maxInt(slot.QuantityPlanned, 1),
						"",
						repairBusy,
						predecessorEnd,
						repairHorizonEnd,
						SlotValidationOptions{IgnoreMinSplitQty: ignoreMinSplitByStep[slot.JobStepID]},
					)
					if ok2 {
						chosen = anchored
					}
					// else keep first feasible `start` (valid calendar) even if slightly earlier than prior proposal
				}
				slot.ScheduledStart = chosen
				slot.ScheduledEnd = chosen.Add(ceilDurationTo30Min(duration))
				if okVal, vErr := s.scheduling.validateSlotCoreForStepWithOptions(processStep, slot.MachineID, slot.ScheduledStart, slot.ScheduledEnd, maxInt(slot.QuantityPlanned, 1), "", SlotValidationOptions{IgnoreMinSplitQty: ignoreMinSplitByStep[slot.JobStepID]}); vErr != nil || !okVal {
					// Fall back to first search result if anchor produced invalid slot (should be rare).
					slot.ScheduledStart = start
					slot.ScheduledEnd = start.Add(ceilDurationTo30Min(duration))
				}
				logger.L().Debug("proposal_stage_chain_repair",
					zap.String("job_id", p.JobID),
					zap.String("job_step_id", slot.JobStepID),
					zap.String("machine_id", slot.MachineID),
					zap.String("before_start", beforeStart.In(time.Local).Format(time.RFC3339)),
					zap.String("before_end", beforeEnd.In(time.Local).Format(time.RFC3339)),
					zap.String("after_start", slot.ScheduledStart.In(time.Local).Format(time.RFC3339)),
					zap.String("after_end", slot.ScheduledEnd.In(time.Local).Format(time.RFC3339)),
				)
				minStart[lbKey] = slot.ScheduledStart
				nextPred := slot.ScheduledEnd
				predecessorEnd = &nextPred
				changed = true
			}
			recomputeProposalBounds(p)
		}
		if !changed {
			return nil
		}
	}
	if lastConflict != "" {
		return newSchedulingActionError(422, fmt.Sprintf("reason_code=%s chain repair exceeded maximum passes (passes=%d proposals=%d slots=%d last_conflict=%s)", repairLimitExceededReasonCode, maxPasses, countNonNilProposals(proposals), countProposalSlots(proposals), lastConflict))
	}
	return newSchedulingActionError(422, fmt.Sprintf("reason_code=%s chain repair exceeded maximum passes (passes=%d proposals=%d slots=%d)", repairLimitExceededReasonCode, maxPasses, countNonNilProposals(proposals), countProposalSlots(proposals)))
}

func chainRepairHorizonEnd(proposal *SchedulingProposal, slotStart time.Time, targetCompletion *time.Time) time.Time {
	horizonEnd := alignSuccessorStart(slotStart.UTC().Add(21 * 24 * time.Hour))
	if latest, ok := proposalLatestSlotEnd(proposal); ok {
		candidate := alignSuccessorStart(latest.UTC().Add(30 * 24 * time.Hour))
		if candidate.After(horizonEnd) {
			horizonEnd = candidate
		}
	}
	if targetCompletion != nil && !targetCompletion.IsZero() {
		candidate := alignSuccessorStart(targetCompletion.UTC().Add(30 * 24 * time.Hour))
		if candidate.After(horizonEnd) {
			horizonEnd = candidate
		}
	}
	absoluteCap := alignSuccessorStart(time.Now().UTC().Add(time.Duration(maxHorizonDays) * 24 * time.Hour))
	if horizonEnd.After(absoluteCap) {
		horizonEnd = absoluteCap
	}
	return horizonEnd
}

func proposalLatestSlotEnd(proposal *SchedulingProposal) (time.Time, bool) {
	if proposal == nil || len(proposal.ProposedSlots) == 0 {
		return time.Time{}, false
	}
	latest := proposal.ProposedSlots[0].ScheduledEnd
	for i := 1; i < len(proposal.ProposedSlots); i++ {
		if proposal.ProposedSlots[i].ScheduledEnd.After(latest) {
			latest = proposal.ProposedSlots[i].ScheduledEnd
		}
	}
	return latest, true
}

func chainRepairPassBudget(proposals []*SchedulingProposal) int {
	slots := countProposalSlots(proposals)
	if slots == 0 {
		return 6
	}
	budget := slots + countNonNilProposals(proposals) + 2
	if budget < 6 {
		budget = 6
	}
	if budget > 64 {
		budget = 64
	}
	return budget
}

func countProposalSlots(proposals []*SchedulingProposal) int {
	count := 0
	for _, proposal := range proposals {
		if proposal == nil {
			continue
		}
		count += len(proposal.ProposedSlots)
	}
	return count
}

func countNonNilProposals(proposals []*SchedulingProposal) int {
	count := 0
	for _, proposal := range proposals {
		if proposal != nil {
			count++
		}
	}
	return count
}

func (s *AIPredictiveService) sortProposalsForRepair(proposals []*SchedulingProposal) {
	priorityRank := func(jobID string) int {
		job, err := s.jobRepo.GetByID(jobID)
		if err != nil || job == nil {
			return 99
		}
		switch strings.ToLower(strings.TrimSpace(job.Priority)) {
		case strings.ToLower(domain.JobPriorityUrgent):
			return 0
		case strings.ToLower(domain.JobPriorityHigh):
			return 1
		case strings.ToLower(domain.JobPriorityMedium):
			return 2
		case strings.ToLower(domain.JobPriorityLow):
			return 3
		default:
			return 4
		}
	}
	sort.SliceStable(proposals, func(i, j int) bool {
		if proposals[i] == nil || proposals[j] == nil {
			return i < j
		}
		pi := priorityRank(proposals[i].JobID)
		pj := priorityRank(proposals[j].JobID)
		if pi != pj {
			return pi < pj
		}
		if !proposals[i].EarliestStart.Equal(proposals[j].EarliestStart) {
			return proposals[i].EarliestStart.Before(proposals[j].EarliestStart)
		}
		return proposals[i].JobID < proposals[j].JobID
	})
}

func proposalStateSignature(proposals []*SchedulingProposal) string {
	b := strings.Builder{}
	for _, p := range proposals {
		if p == nil {
			continue
		}
		b.WriteString(p.JobID)
		b.WriteString("|")
		for _, s := range p.ProposedSlots {
			b.WriteString(s.JobStepID)
			b.WriteString("@")
			b.WriteString(s.MachineID)
			b.WriteString("@")
			b.WriteString(strconv.FormatInt(s.ScheduledStart.Unix(), 10))
			b.WriteString("@")
			b.WriteString(strconv.FormatInt(s.ScheduledEnd.Unix(), 10))
			b.WriteString(";")
		}
		b.WriteString("\n")
	}
	return b.String()
}

func logProposalStage(proposals []*SchedulingProposal, stage string) {
	for _, p := range proposals {
		if p == nil {
			continue
		}
		for _, s := range p.ProposedSlots {
			logger.L().Info("proposal_stage_trace",
				zap.String("stage", stage),
				zap.String("job_id", p.JobID),
				zap.String("job_step_id", s.JobStepID),
				zap.String("machine_id", s.MachineID),
				zap.String("scheduled_start", s.ScheduledStart.In(time.Local).Format(time.RFC3339)),
				zap.String("scheduled_end", s.ScheduledEnd.In(time.Local).Format(time.RFC3339)),
			)
		}
	}
}

// BatchProposalSummary summarizes batch proposal generation results.
type BatchProposalSummary struct {
	Generated        int          `json:"generated"`
	Blocked          int          `json:"blocked"`
	Skipped          int          `json:"skipped"`
	OnTimeCount      int          `json:"on_time_count"`       // proposals with !is_late
	LateCount        int          `json:"late_count"`          // proposals with is_late
	LateJobs         []LateJobRef `json:"late_jobs,omitempty"` // for quick frontend filtering
	MaxDelayRatio    float64      `json:"max_delay_ratio,omitempty"`
	StarvedJobsCount int          `json:"starved_jobs_count,omitempty"`
	// MaterialReplenishmentAggregate: one line per raw material for bulk apply-replenishment.
	MaterialReplenishmentAggregate []BatchMaterialReplenishmentLine `json:"material_replenishment_aggregate,omitempty"`
	// MaterialAccelerationAggregate: optional raw-material arrivals that may reduce lateness
	// for already-feasible jobs waiting on future supply. These are not shortage fixes.
	MaterialAccelerationAggregate []BatchMaterialReplenishmentLine `json:"material_acceleration_aggregate,omitempty"`
}

// LateJobRef references a job that is late; used in batch summary.
type LateJobRef struct {
	JobID         string `json:"job_id"`
	TardinessMins int    `json:"tardiness_mins"`
	LateBy        string `json:"late_by"`
}

// enrichProposalsWithDeadlineStatus sets DeadlineStatus on each proposal and populates summary late-job stats.
func enrichProposalsWithDeadlineStatus(proposals []*SchedulingProposal, summary *BatchProposalSummary, deadlineByJobID map[string]time.Time) {
	summary.OnTimeCount = 0
	summary.LateCount = 0
	summary.LateJobs = nil
	summary.MaxDelayRatio = 0
	summary.StarvedJobsCount = 0
	for _, p := range proposals {
		deadline, ok := deadlineByJobID[p.JobID]
		if !ok || p.EstimatedCompletion == nil {
			p.DeadlineStatus = &DeadlineStatus{Deadline: deadline, IsLate: false, TardinessMins: 0, LateBy: ""}
			summary.OnTimeCount++
			continue
		}
		comp := *p.EstimatedCompletion
		tardinessMins := 0
		if comp.After(deadline) {
			tardinessMins = int(comp.Sub(deadline).Minutes())
		}
		isLate := tardinessMins > 0
		lateBy := formatLateBy(tardinessMins)
		p.DeadlineStatus = &DeadlineStatus{
			Deadline:      deadline,
			IsLate:        isLate,
			TardinessMins: tardinessMins,
			LateBy:        lateBy,
		}
		if isLate {
			summary.LateCount++
			delayRatio := 0.0
			if !deadline.IsZero() {
				baseline := deadline.Sub(p.EarliestStart).Minutes()
				if baseline > 0 {
					delayRatio = float64(tardinessMins) / baseline
				}
			}
			if delayRatio > summary.MaxDelayRatio {
				summary.MaxDelayRatio = delayRatio
			}
			if tardinessMins >= 240 {
				summary.StarvedJobsCount++
			}
			summary.LateJobs = append(summary.LateJobs, LateJobRef{
				JobID:         p.JobID,
				TardinessMins: tardinessMins,
				LateBy:        lateBy,
			})
		} else {
			summary.OnTimeCount++
		}
	}
}

func rebalanceByDeadlinePressure(proposals []*SchedulingProposal, deadlineByJobID map[string]time.Time) {
	sort.SliceStable(proposals, func(i, j int) bool {
		pi := proposals[i]
		pj := proposals[j]
		if pi == nil || pj == nil {
			return false
		}
		if pi.EstimatedCompletion == nil || pj.EstimatedCompletion == nil {
			return false
		}
		di := deadlineByJobID[pi.JobID]
		dj := deadlineByJobID[pj.JobID]
		ti := int(pi.EstimatedCompletion.Sub(di).Minutes())
		tj := int(pj.EstimatedCompletion.Sub(dj).Minutes())
		if ti == tj {
			return di.Before(dj)
		}
		return ti > tj
	})
}

// formatLateBy returns human-readable tardiness: "45 minutes", "3 hours", "2 days 5 hours".
func formatLateBy(tardinessMins int) string {
	if tardinessMins <= 0 {
		return ""
	}
	hours := tardinessMins / 60
	mins := tardinessMins % 60
	if hours < 1 {
		if mins == 1 {
			return "1 minute"
		}
		return fmt.Sprintf("%d minutes", mins)
	}
	if hours < 24 {
		if mins == 0 {
			if hours == 1 {
				return "1 hour"
			}
			return fmt.Sprintf("%d hours", hours)
		}
		if hours == 1 {
			return fmt.Sprintf("1 hour %d minutes", mins)
		}
		return fmt.Sprintf("%d hours %d minutes", hours, mins)
	}
	days := hours / 24
	remainHours := hours % 24
	if remainHours == 0 && mins == 0 {
		if days == 1 {
			return "1 day"
		}
		return fmt.Sprintf("%d days", days)
	}
	parts := []string{}
	if days == 1 {
		parts = append(parts, "1 day")
	} else if days > 1 {
		parts = append(parts, fmt.Sprintf("%d days", days))
	}
	if remainHours > 0 {
		if remainHours == 1 {
			parts = append(parts, "1 hour")
		} else {
			parts = append(parts, fmt.Sprintf("%d hours", remainHours))
		}
	}
	if mins > 0 {
		if mins == 1 {
			parts = append(parts, "1 minute")
		} else {
			parts = append(parts, fmt.Sprintf("%d minutes", mins))
		}
	}
	return strings.Join(parts, " ")
}

func (s *AIPredictiveService) resolveAndFilterJobs(jobIDs []string, includeJobsWithActiveSlots bool) ([]domain.Job, error) {
	var candidates []domain.Job

	if len(jobIDs) == 0 {
		all, err := s.jobRepo.ListAll()
		if err != nil {
			return nil, err
		}
		candidates = all
	} else {
		candidates = make([]domain.Job, 0, len(jobIDs))
		for _, id := range jobIDs {
			job, err := s.jobRepo.GetByID(id)
			if err != nil {
				continue
			}
			candidates = append(candidates, *job)
		}
	}

	result := make([]domain.Job, 0, len(candidates))
	for _, job := range candidates {
		if job.Status != domain.JobStatusPlanned && job.Status != domain.JobStatusScheduled {
			continue
		}
		if !includeJobsWithActiveSlots {
			slots, err := s.slotRepo.ListByJobID(job.JobID)
			if err != nil {
				continue
			}
			hasActive := false
			for _, slot := range slots {
				if slot.Status == domain.SlotStatusPlanned || slot.Status == domain.SlotStatusRunning {
					hasActive = true
					break
				}
			}
			if hasActive {
				continue
			}
		}
		result = append(result, job)
	}
	return result, nil
}

func computeReadinessForJobs(sched *SchedulingService, jobs []domain.Job) map[string]time.Time {
	result := make(map[string]time.Time, len(jobs))
	now := time.Now()
	for _, job := range jobs {
		r, err := sched.CheckReadiness(job.ProductID, float64(job.QuantityTotal))
		if err != nil || r == nil || r.EarliestReadyAt == nil {
			result[job.JobID] = now
			continue
		}
		result[job.JobID] = *r.EarliestReadyAt
	}
	return result
}

func sortJobsByOrder(jobs []domain.Job, orderBy string, readinessAt map[string]time.Time) {
	orderBy = strings.TrimSpace(strings.ToLower(orderBy))
	ready := func(jobID string) time.Time {
		if readinessAt == nil {
			return time.Now()
		}
		if t, ok := readinessAt[jobID]; ok {
			return t
		}
		return time.Now()
	}
	priorityOrder := map[string]int{
		domain.JobPriorityUrgent: 4,
		domain.JobPriorityHigh:   3,
		domain.JobPriorityMedium: 2,
		domain.JobPriorityLow:    1,
	}
	priority := func(value string) int {
		p := priorityOrder[value]
		if p == 0 {
			return 1
		}
		return p
	}
	switch orderBy {
	case "readiness":
		sort.Slice(jobs, func(i, j int) bool {
			ri, rj := ready(jobs[i].JobID), ready(jobs[j].JobID)
			if !ri.Equal(rj) {
				return ri.Before(rj)
			}
			pi, pj := priority(jobs[i].Priority), priority(jobs[j].Priority)
			if pi != pj {
				return pi > pj
			}
			return jobs[i].Deadline.Before(jobs[j].Deadline)
		})
	case "material_priority":
		sort.Slice(jobs, func(i, j int) bool {
			pi, pj := priority(jobs[i].Priority), priority(jobs[j].Priority)
			if pi != pj {
				return pi > pj
			}
			ri, rj := ready(jobs[i].JobID), ready(jobs[j].JobID)
			if !ri.Equal(rj) {
				return ri.Before(rj)
			}
			if !jobs[i].Deadline.Equal(jobs[j].Deadline) {
				return jobs[i].Deadline.Before(jobs[j].Deadline)
			}
			if !jobs[i].CreatedAt.Equal(jobs[j].CreatedAt) {
				return jobs[i].CreatedAt.Before(jobs[j].CreatedAt)
			}
			return jobs[i].JobID < jobs[j].JobID
		})
	case "weighted_tardiness_material":
		sort.SliceStable(jobs, func(i, j int) bool {
			if !jobs[i].CreatedAt.Equal(jobs[j].CreatedAt) {
				return jobs[i].CreatedAt.Before(jobs[j].CreatedAt)
			}
			ri, rj := ready(jobs[i].JobID), ready(jobs[j].JobID)
			if !ri.Equal(rj) {
				return ri.Before(rj)
			}
			return false
		})
	case "product_deadline_fifo":
		sort.SliceStable(jobs, func(i, j int) bool {
			if !jobs[i].CreatedAt.Equal(jobs[j].CreatedAt) {
				return jobs[i].CreatedAt.Before(jobs[j].CreatedAt)
			}
			if jobs[i].ProductID == jobs[j].ProductID && !jobs[i].Deadline.Equal(jobs[j].Deadline) {
				return jobs[i].Deadline.Before(jobs[j].Deadline)
			}
			ri, rj := ready(jobs[i].JobID), ready(jobs[j].JobID)
			if !ri.Equal(rj) {
				return ri.Before(rj)
			}
			return false
		})
	case "edd":
		sort.Slice(jobs, func(i, j int) bool {
			if !jobs[i].Deadline.Equal(jobs[j].Deadline) {
				return jobs[i].Deadline.Before(jobs[j].Deadline)
			}
			return ready(jobs[i].JobID).Before(ready(jobs[j].JobID))
		})
	case "fifo":
		sort.Slice(jobs, func(i, j int) bool {
			if !jobs[i].CreatedAt.Equal(jobs[j].CreatedAt) {
				return jobs[i].CreatedAt.Before(jobs[j].CreatedAt)
			}
			return ready(jobs[i].JobID).Before(ready(jobs[j].JobID))
		})
	case "epo":
		fallthrough
	default:
		sort.Slice(jobs, func(i, j int) bool {
			pi := priority(jobs[i].Priority)
			pj := priority(jobs[j].Priority)
			if pi != pj {
				return pi > pj
			}
			if !jobs[i].Deadline.Equal(jobs[j].Deadline) {
				return jobs[i].Deadline.Before(jobs[j].Deadline)
			}
			return ready(jobs[i].JobID).Before(ready(jobs[j].JobID))
		})
	}
}

// computeCompletionTargets returns per-job target completion times when workload exceeds
// the planning horizon. High-priority jobs get target = deadline; lower-priority get
// deadline + minimal extension, in priority order.
func computeCompletionTargets(s *AIPredictiveService, jobs []domain.Job) map[string]*time.Time {
	if len(jobs) == 0 {
		return nil
	}
	// Estimate per-job duration from preview (with empty tentative)
	jobDurations := make(map[string]time.Duration, len(jobs))
	horizon := jobs[0].Deadline
	for _, job := range jobs {
		if job.Deadline.Before(horizon) {
			horizon = job.Deadline
		}
		preview, err := s.scheduling.BuildSolverPreview(job.JobID)
		if err != nil || preview == nil {
			jobDurations[job.JobID] = 2 * time.Hour
			continue
		}
		var total time.Duration
		for _, step := range preview.Steps {
			total += time.Duration(maxInt(step.EstimatedDurationMins, 1)) * time.Minute
		}
		if total == 0 {
			total = time.Hour
		}
		jobDurations[job.JobID] = total
	}
	now := time.Now()
	horizonSpan := horizon.Sub(now)
	if horizonSpan <= 0 {
		return nil
	}
	var totalDuration time.Duration
	for _, d := range jobDurations {
		totalDuration += d
	}
	if totalDuration <= horizonSpan {
		return nil
	}
	// Workload exceeds horizon: assign targets
	priorityOrder := map[string]int{
		domain.JobPriorityUrgent: 4,
		domain.JobPriorityHigh:   3,
		domain.JobPriorityMedium: 2,
		domain.JobPriorityLow:    1,
	}
	sorted := make([]domain.Job, len(jobs))
	copy(sorted, jobs)
	sort.Slice(sorted, func(i, j int) bool {
		pi := priorityOrder[sorted[i].Priority]
		if pi == 0 {
			pi = 1
		}
		pj := priorityOrder[sorted[j].Priority]
		if pj == 0 {
			pj = 1
		}
		if pi != pj {
			return pi > pj
		}
		return sorted[i].Deadline.Before(sorted[j].Deadline)
	})
	targets := make(map[string]*time.Time, len(jobs))
	cursor := now
	for _, job := range sorted {
		dur := jobDurations[job.JobID]
		pri := priorityOrder[job.Priority]
		if pri == 0 {
			pri = 1
		}
		var target time.Time
		if pri >= 3 {
			target = job.Deadline
			cursor = job.Deadline
		} else {
			target = cursor.Add(dur)
			cursor = target
		}
		targets[job.JobID] = &target
	}
	return targets
}

func joinStrings(ss []string) string {
	if len(ss) == 0 {
		return ""
	}
	result := ss[0]
	for i := 1; i < len(ss); i++ {
		result += "\n" + ss[i]
	}
	return result
}

// repairOverlapsInProposals fixes machine overlaps by shifting later slots/proposals.
// Returns true if any proposal was modified. Modifies proposals in place.
func repairOverlapsInProposals(proposals []*SchedulingProposal) bool {
	if len(proposals) == 0 {
		return false
	}
	modified := false
	occupied := make(map[string][]slotWindow)
	sort.SliceStable(proposals, func(i, j int) bool {
		if proposals[i] == nil || proposals[j] == nil {
			return i < j
		}
		if !proposals[i].EarliestStart.Equal(proposals[j].EarliestStart) {
			return proposals[i].EarliestStart.Before(proposals[j].EarliestStart)
		}
		return proposals[i].JobID < proposals[j].JobID
	})
	// Enforce deterministic non-overlap by proposal order.
	for _, p := range proposals {
		if p == nil || len(p.ProposedSlots) == 0 {
			continue
		}
		// First, eliminate same-proposal overlaps on the same machine.
		if normalizeIntraProposalMachineOverlaps(p) {
			modified = true
		}
		// Then shift whole proposal until it no longer overlaps already-placed proposals.
		seen := map[int64]bool{}
		maxIterations := 64
		for iter := 0; iter < maxIterations; iter++ {
			delta := requiredProposalShift(p, occupied)
			if delta <= 0 {
				break
			}
			sig := delta.Milliseconds()
			if seen[sig] {
				break
			}
			seen[sig] = true
			shiftProposalSlots(p, delta)
			modified = true
		}
		for _, ps := range p.ProposedSlots {
			if ps.MachineID == "" {
				continue
			}
			occupied[ps.MachineID] = append(occupied[ps.MachineID], slotWindow{
				start: ps.ScheduledStart,
				end:   ps.ScheduledEnd,
			})
		}
		for machineID := range occupied {
			occupied[machineID] = mergeSlotWindows(occupied[machineID])
		}
	}
	return modified
}

type slotWindow struct {
	start time.Time
	end   time.Time
}

func normalizeIntraProposalMachineOverlaps(p *SchedulingProposal) bool {
	type idxRange struct {
		slotIdx int
		start   time.Time
		end     time.Time
	}
	byMachine := make(map[string][]idxRange)
	for i, ps := range p.ProposedSlots {
		if ps.MachineID == "" {
			continue
		}
		byMachine[ps.MachineID] = append(byMachine[ps.MachineID], idxRange{
			slotIdx: i,
			start:   ps.ScheduledStart,
			end:     ps.ScheduledEnd,
		})
	}
	changed := false
	for _, slots := range byMachine {
		sort.Slice(slots, func(i, j int) bool { return slots[i].start.Before(slots[j].start) })
		for i := 1; i < len(slots); i++ {
			prev := slots[i-1]
			curr := slots[i]
			if !curr.start.Before(prev.end) {
				continue
			}
			delta := prev.end.Sub(curr.start)
			ps := &p.ProposedSlots[curr.slotIdx]
			duration := ceilDurationTo30Min(ps.ScheduledEnd.Sub(ps.ScheduledStart))
			ps.ScheduledStart = alignSuccessorStart(ps.ScheduledStart.Add(delta))
			ps.ScheduledEnd = ps.ScheduledStart.Add(duration)
			slots[i].start = ps.ScheduledStart
			slots[i].end = ps.ScheduledEnd
			changed = true
		}
	}
	if changed {
		recomputeProposalBounds(p)
	}
	return changed
}

func requiredProposalShift(p *SchedulingProposal, occupied map[string][]slotWindow) time.Duration {
	var maxDelta time.Duration
	for _, ps := range p.ProposedSlots {
		if ps.MachineID == "" {
			continue
		}
		for _, w := range occupied[ps.MachineID] {
			if ps.ScheduledStart.Before(w.end) && ps.ScheduledEnd.After(w.start) {
				delta := w.end.Sub(ps.ScheduledStart)
				delta = ceilDurationTo30Min(delta)
				if delta > maxDelta {
					maxDelta = delta
				}
			}
		}
	}
	return maxDelta
}

func mergeSlotWindows(in []slotWindow) []slotWindow {
	if len(in) <= 1 {
		return in
	}
	sort.Slice(in, func(i, j int) bool { return in[i].start.Before(in[j].start) })
	merged := make([]slotWindow, 0, len(in))
	curr := in[0]
	for i := 1; i < len(in); i++ {
		if !in[i].start.After(curr.end) {
			if in[i].end.After(curr.end) {
				curr.end = in[i].end
			}
			continue
		}
		merged = append(merged, curr)
		curr = in[i]
	}
	merged = append(merged, curr)
	return merged
}

func shiftProposalSlots(p *SchedulingProposal, delta time.Duration) {
	for i := range p.ProposedSlots {
		duration := ceilDurationTo30Min(p.ProposedSlots[i].ScheduledEnd.Sub(p.ProposedSlots[i].ScheduledStart))
		p.ProposedSlots[i].ScheduledStart = alignSuccessorStart(p.ProposedSlots[i].ScheduledStart.Add(delta))
		p.ProposedSlots[i].ScheduledEnd = p.ProposedSlots[i].ScheduledStart.Add(duration)
	}
	recomputeProposalBounds(p)
}

func recomputeProposalBounds(p *SchedulingProposal) {
	if p == nil || len(p.ProposedSlots) == 0 {
		return
	}
	earliest := p.ProposedSlots[0].ScheduledStart
	latest := p.ProposedSlots[0].ScheduledEnd
	for i := 1; i < len(p.ProposedSlots); i++ {
		if p.ProposedSlots[i].ScheduledStart.Before(earliest) {
			earliest = p.ProposedSlots[i].ScheduledStart
		}
		if p.ProposedSlots[i].ScheduledEnd.After(latest) {
			latest = p.ProposedSlots[i].ScheduledEnd
		}
	}
	p.EarliestStart = earliest
	p.EstimatedCompletion = &latest
}

func linearizeOverlapsByMachine(proposals []*SchedulingProposal) {
	machineCursor := map[string]time.Time{}
	for _, p := range proposals {
		if p == nil {
			continue
		}
		sort.SliceStable(p.ProposedSlots, func(i, j int) bool {
			return p.ProposedSlots[i].ScheduledStart.Before(p.ProposedSlots[j].ScheduledStart)
		})
		for i := range p.ProposedSlots {
			slot := &p.ProposedSlots[i]
			cursor := machineCursor[slot.MachineID]
			if cursor.IsZero() || !slot.ScheduledStart.Before(cursor) {
				if slot.ScheduledEnd.After(cursor) {
					machineCursor[slot.MachineID] = slot.ScheduledEnd
				}
				continue
			}
			delta := cursor.Sub(slot.ScheduledStart)
			duration := ceilDurationTo30Min(slot.ScheduledEnd.Sub(slot.ScheduledStart))
			slot.ScheduledStart = alignSuccessorStart(slot.ScheduledStart.Add(delta))
			slot.ScheduledEnd = slot.ScheduledStart.Add(duration)
			machineCursor[slot.MachineID] = slot.ScheduledEnd
		}
		recomputeProposalBounds(p)
	}
}

func overlappingMachinesInProposals(proposals []*SchedulingProposal) []string {
	type slotRef struct {
		start time.Time
		end   time.Time
	}
	byMachine := make(map[string][]slotRef)
	for _, p := range proposals {
		for _, ps := range p.ProposedSlots {
			if ps.MachineID == "" {
				continue
			}
			byMachine[ps.MachineID] = append(byMachine[ps.MachineID], slotRef{
				start: ps.ScheduledStart,
				end:   ps.ScheduledEnd,
			})
		}
	}
	var overlapped []string
	for machineID, slots := range byMachine {
		sort.Slice(slots, func(i, j int) bool { return slots[i].start.Before(slots[j].start) })
		for i := 1; i < len(slots); i++ {
			if slots[i].start.Before(slots[i-1].end) {
				overlapped = append(overlapped, machineID)
				break
			}
		}
	}
	sort.Strings(overlapped)
	return overlapped
}

func tentativeSlotsFromActiveRows(rows []repository.ActiveSlotRow, excludedJobIDs map[string]bool) []TentativeSlot {
	result := make([]TentativeSlot, 0, len(rows))
	for _, r := range rows {
		if excludedJobIDs != nil && excludedJobIDs[r.JobID] {
			continue
		}
		result = append(result, TentativeSlot{
			MachineID:      r.MachineID,
			ScheduledStart: r.ScheduledStart,
			ScheduledEnd:   r.ScheduledEnd,
		})
	}
	return result
}
