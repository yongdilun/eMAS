from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDef:
    metric_type: str
    help_text: str


METRIC_DEFS: dict[str, MetricDef] = {
    "plan_generation_latency_ms": MetricDef("histogram", "Latency of plan generation in milliseconds."),
    "plan_backend_used_total": MetricDef("counter", "Count of planner backend selections."),
    "plan_validation_failure_rate": MetricDef("counter", "Plan validation failure events."),
    "plan_validation_failure_total": MetricDef("counter", "Count of plan validation failures."),
    "replan_rate": MetricDef("counter", "Replan events."),
    "replan_total": MetricDef("counter", "Total replans."),
    "steps_per_session": MetricDef("histogram", "Distribution of steps executed per session."),
    "session_completion_rate": MetricDef("counter", "Session completions."),
    "session_completed_total": MetricDef("counter", "Completed sessions."),
    "session_failed_total": MetricDef("counter", "Failed sessions."),
    "step_execution_latency_ms": MetricDef("histogram", "Latency of step execution per tool in milliseconds."),
    "tool_error_rate": MetricDef("counter", "Tool error events."),
    "tool_error_total": MetricDef("counter", "Tool execution errors by tool and type."),
    "retry_rate": MetricDef("counter", "Retry events."),
    "retry_total": MetricDef("counter", "Retry attempts by tool."),
    "approval_wait_time_ms": MetricDef("histogram", "Approval wait time in milliseconds."),
    "approval_rejection_rate": MetricDef("counter", "Approval rejection events."),
    "approval_rejected_total": MetricDef("counter", "Rejected approvals."),
    "idempotent_replay_rate": MetricDef("counter", "Idempotent replay events."),
    "idempotent_replay_total": MetricDef("counter", "Idempotent replay hits."),
    "payload_mismatch_409_rate": MetricDef("counter", "Payload mismatch events."),
    "payload_mismatch_409_total": MetricDef("counter", "Payload mismatch 409 responses."),
    "ambiguous_step_count": MetricDef("gauge", "Current number of steps in AMBIGUOUS state."),
    "dlq_push_rate": MetricDef("counter", "DLQ push events."),
    "dlq_push_total": MetricDef("counter", "DLQ push count."),
    "dlq_pending_count": MetricDef("gauge", "Current pending DLQ count."),
    "dlq_replay_success_rate": MetricDef("counter", "DLQ replay success events."),
    "dlq_replay_total": MetricDef("counter", "DLQ replay requests."),
    "dlq_replay_success_total": MetricDef("counter", "Successful DLQ replays."),
    "sessions_rate_limited_total": MetricDef("counter", "Sessions rate limited."),
    "limit_type_distribution": MetricDef("counter", "Distribution of which limit types were hit."),
    "session_queue_depth": MetricDef("gauge", "Session queue depth."),
    "worker_pool_utilization": MetricDef("gauge", "Worker pool utilization ratio."),
    "sessions_rejected_429_total": MetricDef("counter", "Sessions rejected with 429."),
    "active_sessions": MetricDef("gauge", "Active sessions."),
    "pending_approvals": MetricDef("gauge", "Pending approvals."),
    "redis_event_queue_depth": MetricDef("gauge", "Redis event queue depth estimate."),
    "db_connection_pool_usage": MetricDef("gauge", "Database connection pool usage ratio."),
    "db_query_total": MetricDef("counter", "Total SQL queries executed."),
    "db_slow_query_total": MetricDef("counter", "Total slow SQL queries executed."),
    "memory_compaction_total": MetricDef("counter", "Memory compaction runs."),
    "memory_retrieval_total": MetricDef("counter", "Memory retrieval attempts."),
    "memory_retrieval_empty_total": MetricDef("counter", "Memory retrievals with no hits."),
    "checkpoint_save_total": MetricDef("counter", "Checkpoint save attempts."),
    "checkpoint_load_total": MetricDef("counter", "Checkpoint load attempts."),
    "checkpoint_error_total": MetricDef("counter", "Checkpoint save/load errors."),
    "checkpoint_load_latency_ms": MetricDef("histogram", "Latency of durable checkpoint load operations."),
    "checkpoint_save_latency_ms": MetricDef("histogram", "Latency of durable checkpoint save operations."),
    "graph_compile_latency_ms": MetricDef("histogram", "Latency of LangGraph planner graph compilation."),
    "graph_checkpointer_selected_total": MetricDef("counter", "Selected LangGraph checkpointer backend count."),
    "stream_snapshot_poll_total": MetricDef("counter", "SSE snapshot poll attempts by stream type."),
    "stream_disconnect_total": MetricDef("counter", "SSE client disconnects detected by stream type."),
}

DEFAULT_HIST_BUCKETS = (
    5.0,
    10.0,
    25.0,
    50.0,
    100.0,
    250.0,
    500.0,
    1000.0,
    2500.0,
    5000.0,
    10000.0,
)


def _labels_key(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def _format_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    values = ",".join(f'{k}="{v}"' for k, v in labels)
    return "{" + values + "}"


class AgentMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, defaultdict[tuple[tuple[str, str], ...], float]] = {}
        self._gauges: dict[str, defaultdict[tuple[tuple[str, str], ...], float]] = {}
        self._hist_sum: dict[str, defaultdict[tuple[tuple[str, str], ...], float]] = {}
        self._hist_count: dict[str, defaultdict[tuple[tuple[str, str], ...], int]] = {}
        self._hist_buckets: dict[str, defaultdict[tuple[tuple[str, str], ...], list[int]]] = {}
        for name, meta in METRIC_DEFS.items():
            if meta.metric_type == "counter":
                self._counters[name] = defaultdict(float)
            elif meta.metric_type == "gauge":
                self._gauges[name] = defaultdict(float)
            elif meta.metric_type == "histogram":
                self._hist_sum[name] = defaultdict(float)
                self._hist_count[name] = defaultdict(int)
                self._hist_buckets[name] = defaultdict(lambda: [0] * len(DEFAULT_HIST_BUCKETS))

    def inc(self, name: str, amount: float = 1.0, *, labels: dict[str, str] | None = None) -> None:
        key = _labels_key(labels)
        with self._lock:
            self._counters.setdefault(name, defaultdict(float))[key] += amount

    def set_gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        key = _labels_key(labels)
        with self._lock:
            self._gauges.setdefault(name, defaultdict(float))[key] = value

    def observe(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        key = _labels_key(labels)
        with self._lock:
            sums = self._hist_sum.setdefault(name, defaultdict(float))
            counts = self._hist_count.setdefault(name, defaultdict(int))
            buckets = self._hist_buckets.setdefault(name, defaultdict(lambda: [0] * len(DEFAULT_HIST_BUCKETS)))
            sums[key] += value
            counts[key] += 1
            bucket_counts = buckets[key]
            for idx, bound in enumerate(DEFAULT_HIST_BUCKETS):
                if value <= bound:
                    bucket_counts[idx] += 1

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for name, meta in METRIC_DEFS.items():
                lines.append(f"# HELP {name} {meta.help_text}")
                lines.append(f"# TYPE {name} {meta.metric_type}")
                if meta.metric_type == "counter":
                    for labels, value in self._counters.get(name, {}).items():
                        lines.append(f"{name}{_format_labels(labels)} {value}")
                elif meta.metric_type == "gauge":
                    for labels, value in self._gauges.get(name, {}).items():
                        lines.append(f"{name}{_format_labels(labels)} {value}")
                elif meta.metric_type == "histogram":
                    sums = self._hist_sum.get(name, {})
                    counts = self._hist_count.get(name, {})
                    buckets = self._hist_buckets.get(name, {})
                    all_keys = set(sums.keys()) | set(counts.keys()) | set(buckets.keys())
                    for labels in all_keys:
                        bucket_counts = buckets.get(labels, [0] * len(DEFAULT_HIST_BUCKETS))
                        running = 0
                        base_labels = dict(labels)
                        for idx, bound in enumerate(DEFAULT_HIST_BUCKETS):
                            running += bucket_counts[idx]
                            bucket_labels = dict(base_labels)
                            bucket_labels["le"] = str(bound)
                            bucket_key = tuple(sorted(bucket_labels.items()))
                            lines.append(f"{name}_bucket{_format_labels(bucket_key)} {running}")
                        plus_inf_labels = dict(base_labels)
                        plus_inf_labels["le"] = "+Inf"
                        plus_inf_key = tuple(sorted(plus_inf_labels.items()))
                        lines.append(f"{name}_bucket{_format_labels(plus_inf_key)} {counts.get(labels, 0)}")
                        lines.append(f"{name}_sum{_format_labels(labels)} {sums.get(labels, 0.0)}")
                        lines.append(f"{name}_count{_format_labels(labels)} {counts.get(labels, 0)}")
        return "\n".join(lines) + "\n"


metrics = AgentMetrics()
