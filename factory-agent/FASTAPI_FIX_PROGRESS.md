# Factory Agent FastAPI Fix Progress

Purpose: Track cleanup progress for the FastAPI backend without losing rollback safety.

Status key:

- Not Started
- In Progress
- Blocked
- Done
- Deferred

## Baseline

| Item | Status | Owner | Notes |
|---|---|---|---|
| Create cleanup branch | Done | Codex | Created `codex/phase-0-fastapi-safety` from current `origin/main` on 2026-05-15 after deleting merged temporary branch `recover-execution-refactor`. |
| Run `pytest --collect-only -q` | Done | Codex | 487 tests collected on 2026-05-15. |
| Run full test suite | Done | Codex | `pytest`: 464 passed, 3 skipped, 20 xfailed on 2026-05-15. |
| Capture OpenAPI snapshot | Done | Codex | Saved `docs/baselines/openapi.phase0.json` with 33 paths and 26 component schemas. |
| Capture Docker build/import baseline | Done | Codex | `docker build -t factory-agent-phase0-baseline .` passed; container `import main` smoke passed. |
| Record current frontend/API behavior | Done | Codex | Recorded in `docs/baselines/phase0_behavior.md`; no runtime behavior changes made. |

## Issue Tracker

| ID | Issue | Severity | Phase | Status | Verification | Rollback |
|---|---|---|---|---|---|---|
| FA-001 | Protect unauthenticated SSE, DLQ, and metrics reads | High | 2 | Done | Auth contract tests for SSE, DLQ, and metrics passed; full `pytest` passed | Temporary local-only compatibility flag |
| FA-002 | Fail unsafe production auth/admin defaults | High | 2 | Done | Production config tests passed; full `pytest` passed | Strict-mode flag rollback |
| FA-003 | Make plan persistence atomic | High | 2 | Done | Injected failure rollback test and approval resume regression passed; full `pytest` passed | Restore old helper behind flag |
| FA-004 | Move startup schema mutation to migrations | High | 5 | Done | Startup compatibility flag/read-only drift tests, migration script coverage, and full `pytest -q` passed | Re-enable startup compat with `ENABLE_STARTUP_SCHEMA_COMPAT=1` |
| FA-005 | Split mixed-responsibility API router | High | 4 | Done | OpenAPI contract guard, endpoint/admin/DLQ/approval/session tests, and full `pytest -q` passed | Revert one extracted router/module |
| FA-006 | Reduce SSE database polling risk | Medium | 5 | Done | Short-lived poll session tests, concurrent stream tests, endpoint stream auth tests, and full `pytest -q` passed | Revert event router polling-session change |
| FA-007 | Strengthen relational constraints/session cleanup | Medium | 4 | Done | Session deletion contract covers session-owned rows; full `pytest -q` passed | Revert session cleanup service extraction |
| FA-008 | Document legacy vs graph-native API contracts | Medium | 3 | Done | `tests/test_phase3_contract_coverage.py`; full `pytest -q` passed | Keep retired endpoints returning 410 |
| FA-009 | Align dependency and Docker packaging | Medium | 1 | Done | `docker build -t factory-agent-phase1-cleanup .`; container `import main` smoke passed | Revert ignore/dependency edits |
| FA-010 | Replace mutable JSON defaults | Low/Medium | 1 | Done | `tests/test_model_json_defaults.py`; full `pytest` passed with project-local temp dir | Revert model default change |
| FA-011 | Add missing auth/contract coverage | Medium | 3 | Done | `tests/test_phase3_contract_coverage.py`; related auth/rollback tests; full `pytest -q` passed | Revert tests independently |
| FA-012 | Extract graph-sensitive orchestration services from `routes.py` | High | 6 | Done | Graph/checkpoint/approval regression suite plus full `pytest -q` | Revert one service extraction at a time |

## Phase Progress

### Phase 0: Safety Preparation

- Status: Done
- Goal: Freeze current behavior and make rollback easy.
- Next actions:
  - Completed on `codex/phase-0-fastapi-safety`.
  - Use this baseline before starting Phase 1 cleanup.

### Phase 1: Low-Risk Cleanup

- Status: Done
- Goal: Reduce repository and deployment noise without changing behavior.
- Completed:
  - Created `codex/phase-1-fastapi-cleanup` from `codex/phase-0-fastapi-safety`.
  - Expanded `.dockerignore` for local databases, logs, caches, scratch folders, vector DBs, and pickle artifacts.
  - Identified tracked local artifacts (`factory_agent.db`, scratch scripts, `factory_agent/rag/bm25_index.pkl`) as Docker packaging exclusions; the RAG retriever handles a missing BM25 pickle by falling back without keyword results.
  - Aligned package metadata to use `requirements.txt` as the single runtime dependency source via dynamic setuptools dependencies.
  - Replaced mutable JSON ORM defaults with callable defaults and added isolation tests.
- Deferred:
  - Moving pure helper functions from `routes.py`; route/helper extraction is safer after Phase 3 contract coverage and belongs with Phase 4 router refactoring.
- Verification:
  - `pytest tests/test_model_json_defaults.py -q`: 2 passed.
  - `pytest tests/test_model_json_defaults.py tests/test_mysql_schema.py tests/test_schema_compatibility.py -q`: 3 passed, 1 skipped.
  - `pytest`: 466 passed, 3 skipped, 20 xfailed after setting `TMP`/`TEMP` to a project-local temp directory; default Windows temp root was inaccessible.
  - `docker build -t factory-agent-phase1-cleanup .`: passed.
  - `docker run --rm factory-agent-phase1-cleanup python -c "import main; print('import main ok')"`: passed.

### Phase 2: Bug Fixes and Contract Fixes

- Status: Done
- Goal: Fix security and data-integrity risks.
- Completed:
  - Added JWT enforcement to session event streams and DLQ reads.
  - Protected metrics behind the admin API key policy.
  - Added production startup validation for JWT/admin defaults, with an explicit unsafe override for rollback.
  - Made plan row, step row, session pointer, and plan message persistence commit atomically.
  - Preserved approved graph resume snapshots so completed writes expose their tool result before completion is accepted by tests.
- Verification:
  - `pytest tests/test_config_app_mode.py tests/test_api_endpoints.py::test_stream_dlq_and_metrics_reads_require_auth tests/test_api_endpoints.py::test_metrics_endpoint_exposes_prometheus_format tests/test_api_endpoints.py::test_admin_dashboard_requires_x_admin_key tests/test_api_endpoints.py::test_create_plan_rolls_back_when_plan_message_persistence_fails tests/test_api_endpoints.py::test_create_plan_persists_plan_and_steps tests/test_tool_output_alignment.py tests/test_reliability_e2e.py::test_pause_resume_live_instruction_update_rejects_stale_approval_and_completes -q`: 19 passed.
  - `pytest tests/test_config_app_mode.py tests/test_approval_atomicity.py -q`: 15 passed.
  - `pytest tests/test_reliability_e2e.py -q`: 3 passed.
  - `pytest tests/test_api_endpoints.py -q`: 46 passed, 20 xfailed.
  - `pytest -q`: 472 passed, 4 skipped, 20 xfailed after setting `TMP`/`TEMP` to a project-local temp directory.
- Remaining:
  - None for Phase 2.

### Phase 3: Test Coverage Improvement

- Status: Done
- Goal: Add tests that make refactoring safe.
- Completed:
  - Added `docs/contracts/legacy_graph_native_contracts.md` documenting active graph-native contracts, deprecated SSE compatibility streams, and retired legacy approval/DLQ write contracts.
  - Added `tests/test_phase3_contract_coverage.py` with an OpenAPI path/response snapshot for route-refactor safety.
  - Added OpenAPI auth documentation checks for sensitive JWT-protected user endpoints and admin-key-protected operational endpoints.
  - Added legacy/graph-native compatibility matrix tests covering retired `plan` and `step` approval decisions returning `410`, retired DLQ write/replay endpoints returning `410`, and active graph-native approval reads.
  - Reused existing Phase 2 coverage for SSE/DLQ/metrics auth and plan persistence rollback because those gaps are already closed and passing.
- Verification:
  - `pytest tests/test_phase3_contract_coverage.py -q`: 10 passed.
  - `pytest tests/test_phase3_contract_coverage.py tests/test_api_endpoints.py::test_stream_dlq_and_metrics_reads_require_auth tests/test_api_endpoints.py::test_metrics_endpoint_exposes_prometheus_format tests/test_api_endpoints.py::test_create_plan_rolls_back_when_plan_message_persistence_fails tests/test_api_endpoints.py::test_create_plan_persists_plan_and_steps tests/test_planner_service_phase6.py::test_graph_native_snapshot_uses_checkpoint_projection_not_legacy_steps tests/test_planner_service_phase6.py::test_legacy_step_reject_cannot_mutate_graph_native_session tests/test_phase8_legacy_retirement.py -q`: 18 passed.
  - `pytest -q`: 482 passed, 4 skipped, 20 xfailed after setting `TMP`/`TEMP` to a project-local temp directory.
- Remaining:
  - None for Phase 3.

### Phase 4: Architecture Refactoring

- Status: Done
- Goal: Improve locality by separating route, service, and projection responsibilities.
- Started:
  - Began FA-005 on 2026-05-15 with a small router/service extraction slice guarded by Phase 3 OpenAPI and compatibility tests.
  - Began FA-007 on 2026-05-15 by centralizing session-owned row cleanup behind a service and expanding session deletion contract coverage.
  - Continued FA-005 on 2026-05-15 with the next safe domain split for session message routes.
  - Completed FA-005 safe route-split scope on 2026-05-15 by extracting operational, stream, approval, and session-control route groups while keeping graph-native plan/execution orchestration in place.
- Completed:
  - Centralized JWT and admin dependency factories in `factory_agent/api/dependencies.py`.
  - Split session lifecycle routes (`POST/GET/PATCH/DELETE /sessions`) into `factory_agent/api/routers/sessions.py`.
  - Split session message routes (`POST/GET /sessions/{session_id}/messages`) into `factory_agent/api/routers/messages.py`.
  - Split session-control routes (`POST /sessions/{session_id}/confirm`, `GET /sessions/{session_id}/steps`, `POST /sessions/{session_id}/cancel`) into `factory_agent/api/routers/session_controls.py`.
  - Split snapshot route wrapper (`GET /sessions/{session_id}/snapshot`) into `factory_agent/api/routers/snapshots.py` without moving checkpoint/timeline projection logic.
  - Split SSE route wrappers (`GET /sessions/{session_id}/events`, `/events/activity`, `/events/semantic`) into `factory_agent/api/routers/events.py` without changing polling, heartbeat, or payload semantics.
  - Split approval routes (`GET /approvals/pending`, `GET/POST /approvals/{approval_id}...`) into `factory_agent/api/routers/approvals.py` while keeping approval resume task handling injected from the existing orchestration code.
  - Split DLQ routes (`GET /dlq`, retired DLQ write/replay contracts, and `POST /dlq/{dlq_id}/dismiss`) into `factory_agent/api/routers/dlq.py`.
  - Split admin and metrics routes into `factory_agent/api/routers/admin.py`.
  - Split tool listing route (`GET /tools`) into `factory_agent/api/routers/tools.py`.
  - Moved session response mapping into `factory_agent/api/response_mappers.py` so extracted routers do not import the mixed route module.
  - Moved message response mapping into `factory_agent/api/response_mappers.py` for the extracted message router.
  - Moved approval and dead-letter response mapping into `factory_agent/api/response_mappers.py` for extracted routers.
  - Moved session deletion cleanup into `factory_agent/services/session_cleanup.py`.
  - Expanded the session deletion contract test to cover messages, plans, steps, approvals, dead letters, execution snapshots, workflow checkpoints, and session-scoped vector memories.
- Verification:
  - Baseline before route code changes: `pytest tests/test_phase3_contract_coverage.py -q`: 10 passed.
  - `pytest tests/test_api_endpoints.py::test_create_session_and_message_updates_intent tests/test_api_endpoints.py::test_delete_session_removes_session_and_related_rows tests/test_api_endpoints.py::test_admin_dashboard_requires_x_admin_key tests/test_api_endpoints.py::test_stream_dlq_and_metrics_reads_require_auth tests/test_phase3_contract_coverage.py -q`: 14 passed.
  - `pytest tests/test_api_endpoints.py tests/test_approval_atomicity.py tests/test_session_manager.py -q`: 57 passed, 20 xfailed.
  - `pytest tests/test_planner_service_phase6.py::test_graph_native_snapshot_uses_checkpoint_projection_not_legacy_steps tests/test_planner_service_phase6.py::test_legacy_step_reject_cannot_mutate_graph_native_session tests/test_reliability_e2e.py::test_pause_resume_live_instruction_update_rejects_stale_approval_and_completes -q`: 3 passed.
  - Required contract guard after changes: `pytest tests/test_phase3_contract_coverage.py -q`: 10 passed.
  - Full suite: `pytest -q`: 482 passed, 4 skipped, 20 xfailed.
  - Message router baseline before this slice: `pytest tests/test_phase3_contract_coverage.py -q`: 10 passed.
  - `pytest tests/test_api_endpoints.py::test_create_session_and_message_updates_intent tests/test_api_endpoints.py::test_waiting_approval_user_message_triggers_replan_context tests/test_reliability_e2e.py::test_pause_resume_live_instruction_update_rejects_stale_approval_and_completes tests/test_phase3_contract_coverage.py -q`: 13 passed.
  - `pytest tests/test_api_endpoints.py tests/test_approval_atomicity.py tests/test_session_manager.py -q`: 57 passed, 20 xfailed.
  - Required contract guard after message router split: `pytest tests/test_phase3_contract_coverage.py -q`: 10 passed.
  - Full suite after message router split: `pytest -q`: 482 passed, 4 skipped, 20 xfailed.
  - Final Phase 4 baseline before this completion slice: `pytest tests/test_phase3_contract_coverage.py -q`: 10 passed.
  - Operational/admin/DLQ/tools split guard: `pytest tests/test_phase3_contract_coverage.py tests/test_api_endpoints.py::test_stream_dlq_and_metrics_reads_require_auth tests/test_api_endpoints.py::test_metrics_endpoint_exposes_prometheus_format tests/test_api_endpoints.py::test_admin_dashboard_requires_x_admin_key tests/test_api_endpoints.py::test_admin_dashboard_html_renders tests/test_api_endpoints.py::test_dlq_dismiss_and_replay_endpoints tests/test_api_endpoints.py::test_get_tools_lists_and_scopes -q`: 15 passed, 1 xfailed.
  - Snapshot/events split guard: `pytest tests/test_phase3_contract_coverage.py tests/test_api_endpoints.py::test_stream_dlq_and_metrics_reads_require_auth tests/test_api_endpoints.py::test_session_snapshot_returns_plan_steps_pending_approval_and_timeline tests/test_api_endpoints.py::test_graph_approval_returns_before_resume_and_keeps_one_activity_operation tests/test_planner_service_phase6.py::test_graph_native_snapshot_uses_checkpoint_projection_not_legacy_steps tests/test_planner_service_phase6.py::test_legacy_step_reject_cannot_mutate_graph_native_session -q`: 15 passed.
  - Approval split guard: `pytest tests/test_phase3_contract_coverage.py tests/test_api_endpoints.py::test_pending_approval_read_endpoints_require_jwt_and_support_session_filter tests/test_api_endpoints.py::test_reject_approval_sets_session_idle_and_step_skipped tests/test_api_endpoints.py::test_graph_approval_returns_before_resume_and_keeps_one_activity_operation tests/test_api_endpoints.py::test_approve_endpoint_allows_overriding_args_before_execution tests/test_approval_atomicity.py -q`: 20 passed, 2 xfailed.
  - Session-control split guard: `pytest tests/test_phase3_contract_coverage.py tests/test_api_endpoints.py::test_predicate_confirmation_round_trip_resumes_with_selected_filter tests/test_api_endpoints.py::test_cancel_marks_remaining_steps_skipped tests/test_api_endpoints.py::test_session_snapshot_returns_plan_steps_pending_approval_and_timeline tests/test_api_endpoints.py::test_create_session_and_message_updates_intent -q`: 13 passed, 1 xfailed.
  - Broad endpoint/session/approval guard: `pytest tests/test_api_endpoints.py tests/test_approval_atomicity.py tests/test_session_manager.py -q`: 57 passed, 20 xfailed.
  - Required contract guard after final Phase 4 slice: `pytest tests/test_phase3_contract_coverage.py -q`: 10 passed.
  - Full suite after final Phase 4 slice: `pytest -q`: 482 passed, 4 skipped, 20 xfailed.
- Remaining:
  - None for Phase 4 safe route-split scope.
- Deferred:
  - DB-level foreign key/cascade changes are deferred to migration-backed work so Phase 4 does not introduce implicit schema mutation outside the Phase 5 migration plan.
  - Graph-native plan creation and execution handlers remain in `factory_agent/api/routes.py` as the core orchestration bundle. Moving them would also move plan persistence and graph execution semantics, so this is deferred until a dedicated service extraction is clearly safe and separately covered.
  - Snapshot/timeline projection internals were not moved; only route wrappers were split. Projection service extraction remains deferred because it is checkpoint-sensitive.
  - Approval resume task handling was not moved; the extracted approval router injects existing callbacks so resume behavior stays unchanged.
- Candidate changes:
  - Completed for this phase. Deferred service extractions above may be revisited only with dedicated graph/checkpoint regression coverage.

### Phase 5: Long-Term Improvements

- Status: Done
- Goal: Improve deployment, observability, and runtime scalability.
- Started:
  - Began FA-004 on 2026-05-15 with a narrow startup schema compatibility safety slice.
- Completed:
  - Added explicit `ENABLE_STARTUP_SCHEMA_COMPAT` startup compatibility flag, defaulting to enabled for rollback-safe behavior.
  - Split startup schema compatibility into read-only action detection plus an optional mutation path.
  - Added structured startup logs for compatibility checks and startup compatibility DDL mutations.
  - Added read-only drift failure behavior when `ENABLE_STARTUP_SCHEMA_COMPAT=0` and compatibility DDL is still pending.
  - Avoided repeated best-effort MySQL `tools.capability_tags` DDL when the column already reports a text type.
  - Documented the transition flag and staging rollout flow in `runbooks/STARTUP_SCHEMA_COMPATIBILITY.md`.
  - Wired the MySQL safe migration script to run the shared startup compatibility migration actions explicitly.
  - Disabled startup compatibility DDL by default; `ENABLE_STARTUP_SCHEMA_COMPAT=1` remains as a rollback bridge.
  - Made production `Base.metadata.create_all` opt-in through `ENABLE_STARTUP_CREATE_ALL`; local development remains enabled by default for fresh DBs.
  - Added `/ready` readiness reporting for database connectivity, Redis state when configured, and tool registry initialization.
  - Reduced SSE polling risk by closing the request dependency session before streaming and opening short-lived DB sessions per snapshot poll.
  - Added stream polling/disconnect metrics and graph compile/checkpoint latency metrics.
- Verification:
  - Pre-change guard: `pytest tests/test_phase3_contract_coverage.py -q`: 10 passed.
  - Targeted schema/config guard: `pytest tests/test_schema_compatibility.py tests/test_config_app_mode.py tests/test_mysql_schema.py -q`: 11 passed, 1 skipped.
  - Required contract guard after changes: `pytest tests/test_phase3_contract_coverage.py -q`: 10 passed.
  - Full suite first attempt with default Windows temp root hit existing `PermissionError` for `C:\Users\dilun\AppData\Local\Temp\pytest-of-dilun`.
  - Full suite after setting `TMP`/`TEMP` to project-local `.tmp`: `pytest -q`: 485 passed, 4 skipped, 20 xfailed.
  - Phase 5 focused guard: `pytest tests/test_schema_compatibility.py tests/test_schema_migration_script.py tests/test_config_app_mode.py tests/test_readiness.py tests/test_event_stream_runtime.py tests/test_phase3_contract_coverage.py tests/test_planner_service_phase6.py tests/test_reliability_e2e.py -q`: 34 passed.
  - Stream/API guard: `pytest tests/test_api_endpoints.py::test_stream_dlq_and_metrics_reads_require_auth tests/test_api_endpoints.py::test_metrics_endpoint_exposes_prometheus_format tests/test_api_endpoints.py::test_session_snapshot_returns_plan_steps_pending_approval_and_timeline tests/test_api_endpoints.py::test_graph_approval_returns_before_resume_and_keeps_one_activity_operation -q`: 4 passed.
  - Final config/schema/readiness/stream/contract guard: `pytest tests/test_config_app_mode.py tests/test_schema_compatibility.py tests/test_schema_migration_script.py tests/test_readiness.py tests/test_event_stream_runtime.py tests/test_phase3_contract_coverage.py -q`: 28 passed.
  - Final full suite with `TMP`/`TEMP` set to project-local `.tmp`: `pytest -q`: 492 passed, 4 skipped, 20 xfailed.
- Remaining:
  - None for Phase 5.
- Deferred:
  - Phase 6 / FA-012 graph orchestration service extraction was Not Started and out of scope for Phase 5.
- Candidate changes:
  - Replace startup schema mutation with migrations.
  - Add readiness checks.
  - Optimize event delivery.
  - Profile graph compilation and checkpointing.

### Phase 6: Graph Orchestration Service Extraction

- Status: Done
- Goal: Reduce `factory_agent/api/routes.py` by moving graph-sensitive orchestration behind tested services after Phase 5 runtime/deployment safety work.
- Started:
  - Began FA-012 on 2026-05-15 after confirming Phases 0 through 5 were Done and Phase 6 was Not Started.
- Completed:
  - Moved checkpoint-backed session snapshot, timeline, activity-step, and semantic-event projection internals into `factory_agent/services/session_snapshot_service.py`.
  - Moved plan creation orchestration, compatibility plan persistence, graph interrupt approval persistence, registry health checks, confirmation/no-op plan handling, and RAG answer plan handling into `factory_agent/services/plan_creation_service.py`.
  - Moved graph session execution and background execution orchestration into `factory_agent/services/execution_service.py`.
  - Moved approved graph approval resume coordination, event publishing, active resume task tracking, and inline/background resume selection into `factory_agent/services/approval_resume_service.py`.
  - Added thin plan and execution routers while keeping `factory_agent/api/routes.py` as the service/route composition root.
  - Moved plan and step response mapping into `factory_agent/api/response_mappers.py`.
  - Preserved the existing `factory_agent.api.routes.generate_uuid` monkeypatch seam used by rollback coverage through an injected UUID factory.
- What not to change:
  - Public API paths, request bodies, response models, status codes, or auth behavior.
  - Planner routing, checkpoint semantics, graph approval behavior, plan persistence semantics, or runtime execution behavior.
- Verification:
  - Baseline before Phase 6 code changes:
    - `pytest tests/test_phase3_contract_coverage.py -q`: 10 passed.
    - `pytest tests/test_approval_atomicity.py tests/test_planner_service_phase6.py tests/test_reliability_e2e.py -q`: 16 passed.
  - Post-extraction focused guards:
    - `pytest tests/test_phase3_contract_coverage.py tests/test_planner_service_phase6.py -q`: 15 passed.
    - `pytest tests/test_approval_atomicity.py tests/test_reliability_e2e.py -q`: first run found a missed closure reference, then 11 passed after patching.
    - `pytest tests/test_api_endpoints.py::test_create_plan_rolls_back_when_plan_message_persistence_fails -q`: 1 passed after preserving the route-level UUID monkeypatch seam.
    - `pytest tests/test_api_endpoints.py tests/test_event_stream_runtime.py tests/test_phase7_api_ui_alignment.py -q`: 58 passed, 20 xfailed.
  - Final required verification:
    - `pytest tests/test_phase3_contract_coverage.py -q`: 10 passed.
    - `pytest tests/test_approval_atomicity.py -q`: 8 passed.
    - `pytest tests/test_planner_service_phase6.py -q`: 5 passed.
    - `pytest tests/test_reliability_e2e.py -q`: 3 passed.
    - `pytest -q`: default Windows temp root hit `PermissionError` for `C:\Users\dilun\AppData\Local\Temp\pytest-of-dilun` after 489 passed, 4 skipped, 20 xfailed.
    - `TMP=.tmp TEMP=.tmp pytest -q`: 492 passed, 4 skipped, 20 xfailed.
- Remaining:
  - None for Phase 6.
- Blockers/deferred:
  - No Phase 6 code blockers remain.
  - Windows default temp-root permission issue remains an environment blocker for default full-suite runs; project-local `TMP`/`TEMP` passes.
  - Phase 7 and future work were not started.
- Rollback:
  - Extract one service at a time so each move can be reverted independently.

## Decision Log

| Date | Decision | Reason | Follow-up |
|---|---|---|---|
| 2026-05-15 | Scope cleanup to `factory-agent` FastAPI backend | User requested FastAPI-only cleanup | Avoid touching frontend or Go API unless needed for contracts |
| 2026-05-15 | Do not start with a rewrite | Current behavior has broad tests and migration history | Prefer phased, rollback-safe changes |
| 2026-05-15 | Fix security/data integrity before router splitting | These reduce risk fastest | Add tests first |

## Current Next Step

Phase 6 / FA-012 is complete. Phase 7 and future work remain out of scope unless explicitly requested.
