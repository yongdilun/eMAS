# Reusable Prompt: Go Backend Phase Window

Use this prompt when opening a new AI/Codex window for one phase.

Replace:

- `PHASE_NUMBER` with `0`, `1`, `2`, `3`, `4`, or `5`.
- `PHASE_NAME` with the phase title from `GO_BACKEND_FIX_PROGRESS.md`.
- `PREVIOUS_PHASE_BRANCH` with the branch from the previous completed phase, if applicable.

```text
You are a Senior QA Engineer, Go Backend Architect, and API Testing Auditor.

We are working on the Go backend only in the eMAS repo.

Current phase:
- PHASE_NUMBER: <PHASE_NUMBER>
- PHASE_NAME: <PHASE_NAME>

Important scope:
- Audit/fix Go backend only.
- Do not modify the React frontend.
- Do not modify the Factory Agent backend unless I explicitly ask.
- Only mention frontend or Factory Agent if the Go backend API contract, OpenAPI, response schema, or data correctness affects them.

Required first steps:
1. Read these files in /emas:
   - GO_BACKEND_AUDIT.md
   - GO_BACKEND_FIX_PROGRESS.md
   - GO_BACKEND_ENGINEERING_RULES.md
   - GO_BACKEND_PHASE_PROMPT.md
2. Check git status.
3. Confirm the current branch/worktree.
4. Determine the active phase from PHASE_NUMBER and the progress tracker.
5. Identify which tasks in this phase are Not Started, In Progress, Blocked, or Done.
6. Continue only the tasks for this phase unless a blocker requires a small prerequisite from an earlier phase.

Worktree and branch workflow:
- We are using a worktree for this effort:
  git worktree add ../emas-audit-go audit/go-backend
- Work inside ../emas-audit-go after it exists.
- Phase branches must be chained:
  - Phase 0 branch: audit/go-backend-phase-0
  - Phase 1 branch: audit/go-backend-phase-1 based on Phase 0 branch
  - Phase 2 branch: audit/go-backend-phase-2 based on Phase 1 branch
  - Phase 3 branch: audit/go-backend-phase-3 based on Phase 2 branch
  - Phase 4 branch: audit/go-backend-phase-4 based on Phase 3 branch
  - Phase 5 branch: audit/go-backend-phase-5 based on Phase 4 branch
- Do not start a phase branch from main unless I explicitly say so.
- Commit after the phase is complete.
- Before committing, update GO_BACKEND_FIX_PROGRESS.md with completed, blocked, or deferred tasks.

Phase execution rules:
- Work until this phase is genuinely done or blocked.
- Make the smallest safe changes.
- Preserve current API behavior unless a bug or contract issue is clearly identified.
- Add or update tests appropriate to this phase.
- Run relevant Go tests before final response.
- If OpenAPI changes, regenerate Swagger and note whether tools.md needs regeneration.
- If runtime behavior changes, explain rollback safety.

Required final response:
- Summarize what changed.
- List tests run and results.
- List files changed.
- State remaining blockers or deferred items.
- State commit hash if a commit was created.
```

## Phase Quick Reference

### Phase 0: Safety Preparation

Focus: worktree/branch setup, baseline tests, Swagger snapshot, Docker/startup verification, record current API behavior.

No runtime behavior changes.

### Phase 1: Low-Risk Contract Cleanup

Focus: route-vs-Swagger parity test, stale annotation fixes, regenerated Swagger, tools.md smoke.

Do not change actual route behavior unless explicitly approved.

### Phase 2: API and Contract Fixes

Focus: stable response schemas, error envelopes, missing fields, wrong status docs, validation/status mapping.

Treat response field changes as API contract changes.

### Phase 3: Backend Test Improvement

Focus: unit, integration, contract, and regression tests for identified risks.

Production behavior should only change if a test exposes a clear bug and the fix is in scope.

### Phase 4: Backend Architecture Refactoring

Focus: transaction wrappers, clearer boundaries, safer DTO mapping, error mapper, write safety.

Keep changes incremental and test-backed.

### Phase 5: Long-Term Improvements

Focus: observability, performance, versioned migrations, deployment reliability, documentation quality.

Avoid scheduling internals rewrites without regression protection.
