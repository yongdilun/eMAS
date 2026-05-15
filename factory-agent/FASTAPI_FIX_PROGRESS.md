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
| FA-004 | Move startup schema mutation to migrations | High | 5 | Not Started | Migration smoke tests | Keep startup compat under explicit flag |
| FA-005 | Split mixed-responsibility API router | High | 4 | Not Started | OpenAPI diff plus endpoint tests | Revert one extracted router/module |
| FA-006 | Reduce SSE database polling risk | Medium | 5 | Not Started | Disconnect and concurrent stream tests | Keep old implementation path |
| FA-007 | Strengthen relational constraints/session cleanup | Medium | 4 | Not Started | Session deletion contract tests | Keep manual cleanup fallback |
| FA-008 | Document legacy vs graph-native API contracts | Medium | 3 | Not Started | Contract matrix tests | Keep retired endpoints returning 410 |
| FA-009 | Align dependency and Docker packaging | Medium | 1 | Done | `docker build -t factory-agent-phase1-cleanup .`; container `import main` smoke passed | Revert ignore/dependency edits |
| FA-010 | Replace mutable JSON defaults | Low/Medium | 1 | Done | `tests/test_model_json_defaults.py`; full `pytest` passed with project-local temp dir | Revert model default change |
| FA-011 | Add missing auth/contract coverage | Medium | 3 | Not Started | New tests fail before fix, pass after fix | Revert tests independently |

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

- Status: Not Started
- Goal: Add tests that make refactoring safe.
- Candidate changes:
  - API/OpenAPI contract snapshot.
  - SSE auth and disconnect tests.
  - DLQ and metrics auth tests.
  - Plan persistence rollback tests.
  - Legacy/graph-native compatibility matrix tests.

### Phase 4: Architecture Refactoring

- Status: Not Started
- Goal: Improve locality by separating route, service, and projection responsibilities.
- Candidate changes:
  - Split routers by domain.
  - Move snapshot/timeline projection to a service.
  - Move approval resume task handling to a service.
  - Move plan persistence to a transaction-focused service.
  - Centralize auth/admin dependencies.

### Phase 5: Long-Term Improvements

- Status: Not Started
- Goal: Improve deployment, observability, and runtime scalability.
- Candidate changes:
  - Replace startup schema mutation with migrations.
  - Add readiness checks.
  - Optimize event delivery.
  - Profile graph compilation and checkpointing.

## Decision Log

| Date | Decision | Reason | Follow-up |
|---|---|---|---|
| 2026-05-15 | Scope cleanup to `factory-agent` FastAPI backend | User requested FastAPI-only cleanup | Avoid touching frontend or Go API unless needed for contracts |
| 2026-05-15 | Do not start with a rewrite | Current behavior has broad tests and migration history | Prefer phased, rollback-safe changes |
| 2026-05-15 | Fix security/data integrity before router splitting | These reduce risk fastest | Add tests first |

## Current Next Step

Phase 1 is complete. Next cleanup window should start Phase 2 unless explicitly directed otherwise:

1. Add auth contract tests for SSE, DLQ, and metrics policy.
2. Protect exposed read endpoints according to the chosen auth policy.
3. Add production config safety tests before enforcing production auth/admin defaults.
4. Add rollback tests before making plan persistence transactional.
