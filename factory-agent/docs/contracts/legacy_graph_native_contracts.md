# Legacy vs Graph-Native API Contracts

Date: 2026-05-15

This matrix documents the Phase 3 compatibility boundary before route refactoring. Public paths stay stable, but legacy relational execution and step-based recovery flows are retired in favor of graph-native session execution, graph approvals, and snapshot projection.

## Active Graph-Native Contracts

| Contract area | Endpoint | Status | Notes |
|---|---|---|---|
| Session lifecycle | `POST /sessions` | Active | Creates the session record used by graph-native execution. |
| Messages | `POST /sessions/{session_id}/messages` | Active | Persists user and assistant messages for a session. |
| Planning | `POST /sessions/{session_id}/plans` | Active | Creates compatibility plan rows while graph-native checkpoint state remains execution truth. |
| Execution | `POST /sessions/{session_id}/execute` | Active | Runs or resumes graph-native sessions. Waiting graph approvals are returned as session state. |
| Snapshot | `GET /sessions/{session_id}/snapshot` | Active | Projects current session state from graph-native checkpoints when present. |
| Notifications | `GET /sessions/{session_id}/events` | Active | Preferred SSE stream. Emits cursor invalidations; clients re-fetch snapshots. |
| Activity stream | `GET /sessions/{session_id}/events/activity` | Deprecated but active | Compatibility stream for user-facing activity frames. Requires JWT when JWT is enabled. |
| Semantic stream | `GET /sessions/{session_id}/events/semantic` | Deprecated but active | Compatibility stream for semantic/debug frames. Requires JWT when JWT is enabled. |
| Graph approvals | `GET /approvals/pending`, `GET /approvals/{approval_id}`, `POST /approvals/{approval_id}/approve`, `POST /approvals/{approval_id}/reject` | Active for `subject_type=graph` | Legacy `plan` and `step` approvals are intentionally retired. |
| DLQ reads | `GET /dlq` | Active read contract | Requires JWT when JWT is enabled. |
| Metrics | `GET /metrics` | Active admin contract | Requires `X-Admin-Key`. |

## Retired Legacy Contracts

| Contract area | Endpoint | Status | Replacement |
|---|---|---|---|
| Plan approval decisions | `POST /approvals/{approval_id}/approve`, `POST /approvals/{approval_id}/reject` for `subject_type=plan` | Retired, returns `410` | Use graph approvals with `subject_type=graph`. |
| Step approval decisions | `POST /approvals/{approval_id}/approve`, `POST /approvals/{approval_id}/reject` for `subject_type=step` | Retired, returns `410` | Use graph approvals with `subject_type=graph`. |
| Step-based DLQ push | `POST /dlq/push` | Retired, returns `410` | Graph-native failures are recorded in graph/session state. |
| Step-based DLQ replay | `POST /dlq/{dlq_id}/replay` | Retired, returns `410` | Rerun graph-native sessions through `POST /sessions/{session_id}/execute`. |
| Step-based DLQ replay request | `POST /dlq/{dlq_id}/replay-request` | Retired, returns `410` | Rerun graph-native sessions through `POST /sessions/{session_id}/execute`. |

## Test Guards

The matrix is guarded by `tests/test_phase3_contract_coverage.py`:

- OpenAPI path and response-model snapshot coverage.
- OpenAPI auth header documentation for sensitive user and admin endpoints.
- Runtime `410` checks for retired legacy approval and DLQ write contracts.
- Runtime read contract check for graph-native approvals.
