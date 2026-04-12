package featureflags

import (
	"os"
	"strings"
)

func envBool(key string, defaultValue bool) bool {
	v := strings.TrimSpace(strings.ToLower(os.Getenv(key)))
	if v == "" {
		return defaultValue
	}
	return v == "1" || v == "true" || v == "yes" || v == "on"
}

func envString(key, defaultValue string) string {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return defaultValue
	}
	return v
}

func SchedulingWriteAuthRequired() bool {
	return envBool("AI_AUTH_REQUIRED", true)
}

func ProposalEngineMode() string {
	return strings.ToLower(envString("AI_PROPOSAL_ENGINE", "heuristic"))
}

func SolverShadowMode() bool {
	return envBool("AI_SOLVER_SHADOW_MODE", false)
}

func SolverDefaultEnabled() bool {
	return envBool("AI_SOLVER_DEFAULT", false)
}

func SolverTimeoutMs() int {
	v := envString("AI_SOLVER_TIMEOUT_MS", "2000")
	if parsed := strings.TrimSpace(v); parsed != "" {
		if n := atoiDefault(parsed, 2000); n > 0 {
			return n
		}
	}
	return 2000
}

// BatchTimeoutMs returns timeout for batch-proposals and reschedule-all.
// Set AI_BATCH_TIMEOUT_MS (default 60000 = 60s) so 18+ jobs can complete.
// SolverTimeoutMs (2s) is per-job; batch needs much longer.
func BatchTimeoutMs() int {
	v := envString("AI_BATCH_TIMEOUT_MS", "60000")
	if parsed := strings.TrimSpace(v); parsed != "" {
		if n := atoiDefault(parsed, 60000); n > 0 {
			return n
		}
	}
	return 60000
}

// AdaptiveBatchTimeoutMs returns the batch context deadline length in milliseconds.
// When jobCount > 0, enforces at least 30s + 3s per job so large batches do not
// hit a flat AI_BATCH_TIMEOUT_MS cap mid-run (reschedule-all and scope=all_unscheduled
// resolve jobs inside ScheduleJobSet and must use this count, not handler job_ids length).
func AdaptiveBatchTimeoutMs(configuredMs int, jobCount int) int {
	timeoutMs := configuredMs
	if timeoutMs <= 0 {
		timeoutMs = 60000
	}
	if jobCount > 0 {
		minByBatch := 30000 + (jobCount * 3000)
		if minByBatch > timeoutMs {
			timeoutMs = minByBatch
		}
	}
	return timeoutMs
}

func CompatibilityApplyEnabled() bool {
	return envBool("AI_COMPAT_APPLY_ENABLED", false)
}

func ProposalApplyRequiresApproval() bool {
	return envBool("AI_PROPOSAL_APPLY_REQUIRES_APPROVAL", true)
}

func RolloutState() string {
	return strings.ToLower(envString("AI_ROLLOUT_STATE", "heuristic-only"))
}

func SolverKpiGateEnabled() bool {
	return envBool("AI_SOLVER_KPI_GATE", false)
}

func BatchOrderBy() string {
	return strings.ToLower(envString("AI_BATCH_ORDER_BY", "epo"))
}

// ApplySkipStalenessCheck when true skips staleness validation on apply (for eval scripts / batch apply).
func ApplySkipStalenessCheck() bool {
	return envBool("AI_APPLY_SKIP_STALENESS_CHECK", false)
}

// SplitStrategy returns "equal"|"min_time"|"priority" for quantity allocation across parallel machines.
func SplitStrategy() string {
	return strings.ToLower(envString("AI_SPLIT_STRATEGY", "equal"))
}

// SchedulingObjective returns "minimize_tardiness"|"minimize_makespan"|"maximize_utilization".
func SchedulingObjective() string {
	return strings.ToLower(envString("AI_OBJECTIVE", "minimize_tardiness"))
}

// AutoRescheduleOnEvent when true triggers reschedule when scheduling events are received.
func AutoRescheduleOnEvent() bool {
	return envBool("AI_AUTO_RESCHEDULE_ON_EVENT", false)
}

// EmitEventOnDowntime when true, RecordDowntime handler emits machine_down scheduling event (Gap 4).
func EmitEventOnDowntime() bool {
	return envBool("AI_EMIT_EVENT_ON_DOWNTIME", true)
}

func atoiDefault(v string, defaultValue int) int {
	n := 0
	for _, ch := range v {
		if ch < '0' || ch > '9' {
			return defaultValue
		}
		n = n*10 + int(ch-'0')
	}
	if n <= 0 {
		return defaultValue
	}
	return n
}
