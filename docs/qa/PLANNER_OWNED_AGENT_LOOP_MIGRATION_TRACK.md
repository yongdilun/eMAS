# Planner-Owned Agent Loop Migration Progress Tracker

Branch: `codex/playwright-e2e-plan`
Created: 2026-05-20
Last updated: 2026-05-20

Primary plan: [`PLANNER_OWNED_AGENT_LOOP_MIGRATION.md`](PLANNER_OWNED_AGENT_LOOP_MIGRATION.md)

## Purpose

Track implementation progress for the planner-owned agent loop migration without turning the main plan into a work log.

Use the main plan for architecture, contracts, phase definitions, stop conditions, and acceptance criteria. Use this tracker for phase status, commits, verification commands, handoffs, and open follow-up notes.

## Current Status

Phase 1, Phase 2, and Phase 3 are complete. Phase 4 is the next implementation phase.

Important handoff for Phase 4: capability-map and source-of-truth helpers are contract-only. RAG/procedure/policy are represented as document-knowledge capability families, while the legacy RAG route remains explicitly named as `legacy_rag_route`; Phase 4 must wrap existing `ToolSelector` retrieval rather than building a second retriever.

## Phase Progress

| Phase | Name | Status | Owner | Commit / PR | Verification | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Boundary and baseline audit | Complete | Codex | `4eb425e0b36a32faca6af0ceabe2525a88523939` | `91 passed, 35 warnings`; `git diff --check` passed | Legacy scaffold, RAG shortcut, whole-query tool scope, intent-completion loop, pending-message gap, and ToolSelector reuse boundary documented. |
| 2 | Requirement ledger and v2 state contracts only | Complete | Codex | `feat: add planner-owned loop v2 state contracts` | Phase 1/2 contract suite: `11 passed, 1 warning`; route/splitter/selector suite: `88 passed, 35 warnings`; `git diff --check` passed | Contracts only. Added serializable v2 state, agenda patch locked-constraint guard, adapter trace contracts, and distinct legacy RAG route evidence. No runtime switch or v2/v2_shadow production claim. |
| 3 | Capability map and source-of-truth hints | Complete | Codex | `feat: add planner-owned loop capability map hints` | Phase 1/2/3 contract suite: `21 passed, 1 warning`; route/splitter/selector suite: `88 passed, 35 warnings`; `git diff --check` passed | Added compact metadata-driven capability map helpers, source-of-truth hints, document-knowledge families, field aliases, and requirement sketch/ledger locking. No runtime switch or v2/v2_shadow production claim. |
| 4 | Need-based tool retrieval and hydration | Planned | TBD | TBD | TBD | Wrap existing `ToolSelector`; do not build a second retriever. |
| 5 | Planner-owned v2 loop behind flag | Planned | TBD | TBD | TBD | Add trace-only `v2_shadow` first; production shadow must not mutate state. |
| 6 | Evidence satisfaction and replan | Planned | TBD | TBD | TBD | Deterministic satisfaction may close obvious read requirements only with typed evidence. |
| 7 | User interrupt and mid-execution replan | Planned | TBD | TBD | TBD | Convert `pending_user_message` into real interrupt/replan handling or retire it. |
| 8 | Legacy cleanup switch | Planned | TBD | TBD | TBD | Retire legacy authority only after v2 proofs pass. |
| 9 | Hard query release proof | Planned | TBD | TBD | TBD | Prove multi-step, mixed API/RAG, approval, interrupt, failure, and no-hardcode scenarios. |
| 10 | Legacy kill-switch removal | Planned | TBD | TBD | TBD | Remove normal legacy option only after release proof and cleanup guardrails pass. |

## Audit Notes

- Phase 1 is strongest as documentation and boundary inventory; the guard test is intentionally static and does not prove the future v2 runtime.
- Phase 2 should include `execution_trace` as a first-class contract even though the Phase 2 list in the main plan names only `engine_version`.
- Phase 2 should distinguish `rag_tool` evidence from the current `legacy_rag_route` empty-plan shortcut.
- Phase 2 should keep requirement, capability need, tool call, and evidence vocabularies separate.
- Phase 2 should avoid exact-prompt, seeded-ID, source fixture, or entity-label runtime branches.

## Update Checklist

When a phase is completed:

1. Update `Last updated`.
2. Change the phase status and fill in owner, commit/PR, verification, and notes.
3. Add any handoff notes that affect the next phase.
4. Keep architectural decisions in the main plan, not this tracker.
5. Run `git diff --check`.

## Progress Log

### 2026-05-20

- Phase 1 boundary audit completed and committed in `4eb425e0b36a32faca6af0ceabe2525a88523939`.
- Verification reported: `python -m pytest tests/test_route_to_execution_contract.py tests/test_intent_splitter.py tests/test_tool_selector.py tests/test_planner_owned_loop_phase1_boundary.py -q` passed with `91 passed, 35 warnings`.
- Auditor follow-up identified Phase 2 tracker note: add explicit `execution_trace` contract and legacy RAG shortcut trace support.
- Phase 2 contracts added in `factory_agent/planning/v2_contracts.py` with focused tests in `tests/test_planner_owned_loop_phase2_contracts.py`.
- Verification passed: `python -m pytest tests/test_planner_owned_loop_phase1_boundary.py tests/test_planner_owned_loop_phase2_contracts.py -q` reported `11 passed, 1 warning`; `python -m pytest tests/test_route_to_execution_contract.py tests/test_intent_splitter.py tests/test_tool_selector.py -q` reported `88 passed, 35 warnings`; `git diff --check` passed.
- Handoff for Phase 3: consume these contracts from metadata/generated capability-map work only; legacy RAG remains represented as `legacy_rag_route` evidence, not `rag_tool`, and production still must not claim `engine_version=v2` or `engine_version=v2_shadow`.
- Phase 3 capability-map helpers added in `factory_agent/planning/v2_capability_map.py` with focused tests in `tests/test_planner_owned_loop_phase3_capability_map.py`.
- Verification passed: `python -m pytest tests/test_planner_owned_loop_phase1_boundary.py tests/test_planner_owned_loop_phase2_contracts.py tests/test_planner_owned_loop_phase3_capability_map.py -q` reported `21 passed, 1 warning`; `python -m pytest tests/test_route_to_execution_contract.py tests/test_intent_splitter.py tests/test_tool_selector.py -q` reported `88 passed, 35 warnings`; `git diff --check` passed.
- Handoff for Phase 4: use the compact capability hints and requirement sketches as inputs, keep document knowledge as capability families until a real RAG tool retriever is implemented, and reuse the existing `ToolSelector` stack for need-based retrieval.
