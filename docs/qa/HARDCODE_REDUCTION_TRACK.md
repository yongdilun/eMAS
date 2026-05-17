# Hardcoded Logic Reduction Tracker

Branch: `codex/playwright-e2e-plan`
Baseline commit observed: `3e50209 test: add semantic routing contract`

## Phase Status

| Phase | Name | Status | Owner | Notes |
| --- | --- | --- | --- | --- |
| 0 | Hardcode inventory and classification | Complete | Codex | Completed as docs-only inventory. No product or test behavior changes. Next action is Phase 1. |
| 1 | Guard semantic routing against overfitting | Complete | Codex | Added route-family semantic contract matrix, production hardcode guard, and fixed job-id fragment entity leakage. |
| 2 | Capability-based tool selection | Complete | Codex | Semantic route tool selection now uses capability metadata before legacy endpoint-name fallback. |
| 3 | Knowledge policy registry | Complete | Codex | Moved OSHA/LOTO fallback answer, sources, and safety content into a route-scoped RAG knowledge policy registry. |
| 4 | SSE fault injection Adapter | Complete | Codex | Seeded duplicate/out-of-order/drop/reconnect hooks now live behind `factory_agent.testing.fault_injection`; production router uses the no-op adapter by default. |
| 5 | Data-driven seeded scenario engine | Not Started | Next agent | Highest effort. Migrate scenario branches incrementally. |
| 6 | Typed snapshot presentation contract | Not Started | Next agent | Backend contract needed before frontend cleanup. |
| 7 | Frontend typed presentation rendering | Not Started | Next agent | Remove primary dependence on text phrase inference. |
| 8 | Hardcode guardrails in CI | Not Started | Next agent | Resume scenario growth after this. |

## Current Blockers

- None confirmed.
- None confirmed for Phase 2. Capability metadata is sufficient for the semantic route families covered here; endpoint fallback remains for untagged legacy tools.
- Potential blocker: frontend may need legacy text parsing for old sessions until typed presentation is fully deployed.

## Open Questions

- Should route-family definitions live in Python data structures first or external JSON/YAML registry?
- Should curated knowledge fallbacks eventually be product-owned content in external data instead of Python registry data?
- What typed presentation schema should be considered stable enough for frontend use?
- Which seeded planner scenarios should migrate first: approval chains, SSE faults, or RAG/source flows?
- Should hardcode guardrails start as blocking CI or warning-only?

## Decisions Made

- Do not fix every hardcoded value blindly.
- Product hardcodes and runtime test hooks are higher priority than fixture constants.
- Seeded IDs such as `JOB-SEED-*` and `M-CNC-01` are acceptable in fixture/test data when not driving production behavior.
- New scenario discovery should pause except for regressions found while reducing hardcodes.
- Browser tests should only be added when visible UI can diverge from lower-layer route/state evidence.
- Phase 0 is complete as a documentation-only inventory: no product code and no test behavior were changed.
- Fixture constants remain accepted only when they live in fixture/spec support paths and do not drive product routing.
- Phase 1 found and fixed a product routing bug where a hyphenated job id such as `JOB-ABC-123` could leak an inner `ABC-123` machine id into `normalized_entities`.
- Phase 2 found and fixed product routing bugs where individual job deletes were classified as dangerous bulk deletes, `JOB-*` IDs without digits were not normalized, create-job shorthand such as `create job P-005` did not preserve the product id, and read-style schedule explanation prompts were treated as incomplete job mutations.
- Phase 3 keeps curated OSHA/LOTO fallback knowledge product-owned behind `factory_agent.rag.knowledge_policy`; the first policy is route-scoped to LOTO/safety RAG routes and does not apply to unrelated procedure prompts.
- Phase 4 keeps normal SSE stream semantics in `factory_agent.api.routers.events`; seeded Playwright SSE diagnostics and fault behavior are isolated behind `factory_agent.testing.fault_injection`.
- Phase 4 exposed and fixed related product bugs: bare `run` wording no longer implies a job mutation without a write verb; synthetic completion projection now preserves operator-facing tool result messages, uses step index as a tie-breaker for same-timestamp tool results, and the frontend sorts same-timestamp tool rows plus surfaces extra answer-model fields beside tables.

## Phase 0 Inventory

Inventory command families used:

- `rg -n -i "phase 9|phase 14|phase 19|M-CNC-01|JOB-SEED|playwright_seeded|seeded_playwright|fallback|please approve|will be updated from|risk summary|run complete|get__jobs|put__jobs_\{id\}" ...`
- `rg -n -i "if .*lower|in lowered|includes\(|current_intent|prompt|semantic_frame|_semantic_route_tool_names|_fallback_knowledge_answer|_snapshot_intent_contains|approvalWaitSummary|isApprovalWaitText|isPlanLikeAnswer" ...`

### Inventory Summary

| Classification | Count | Meaning |
| --- | ---: | --- |
| `product-risk` | 10 | Production code branches on wording, literal endpoint names, or embedded answer content. |
| `runtime-test-hook` | 2 | Playwright seeded behavior is reachable from production router code paths, gated by environment. |
| `test-infra-risk` | 3 | Test adapters/mock servers are intentionally deterministic but are becoming duplicate product implementations. |
| `acceptable-fixture` | 5 | Fixture constants or assertions are isolated in test data/specs and should remain explicit. |

### Product And Runtime Risks

| ID | Priority | Classification | File/module | Evidence | Why it matters | Desired seam or replacement | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P0-01 | Critical | `product-risk` | `factory-agent/factory_agent/services/session_snapshot_service.py` | `_is_plan_like_completion_text`, `_is_approval_wait_text`, `_is_success_like_plan_text`, and `_is_failure_guidance_text` branch on `risk summary:`, `please approve`, `will be updated from`, `run complete`, `failed`, and `please retry` at lines 111-163; completion projection re-selects content from those helpers at lines 1387-1400. | Backend snapshot/final-response meaning can change when visible prose changes, creating stale approval or false success risk. | Typed presentation contract with explicit `kind`, `state`, operation id, approval id, row outcomes, and source state; text only as display copy. | Defer to Phase 6. |
| P0-02 | Critical | `product-risk` | `eMas Front/src/components/features/chat/turns/turnAssembler.js` | `isPlanLikeAnswer`, `isApprovalWaitText`, and `stripApprovalWaitPhrases` inspect `risk summary:`, `please approve`, `will be updated from`, and `waiting for your approval` at lines 40-58 and 426-435; final summary routing uses those helpers at lines 503-516. | Frontend can render the wrong final answer or hide/show approval copy based on text wording instead of backend state. | Render from typed presentation/activity state first; retain phrase parsing only for legacy sessions. | Defer to Phase 7 after Phase 6. |
| P0-03 | High | `product-risk` | `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx` | `isPlanLikeAnswer` filters `risk summary:` at lines 43-49; `approvalWaitSummary` checks `please approve` and `will be updated from` at lines 335-340; table hiding uses text-vs-table contradiction heuristics at lines 374-454. | UI presentation can be driven by narrative wording, causing stale approval bundles or stale tables to win over actual operation state. | Use typed write-bundle/table presentation metadata with explicit stale-state flags and operation ids. | Defer to Phase 7. |
| P0-04 | High | `product-risk` | `eMas Front/src/components/features/chat/factory-agent/activityTimelineUtils.js` | Activity state maps `session_completed` to visible `Run complete` at line 164 and line 588; active-session cleanup drops rows whose label is `run complete` at line 83; later fallback injects `Run complete` from session status at line 839. | Timeline truth depends partly on display labels, so wording changes or stale terminal rows can change activity state. | Use backend-provided typed activity steps as authoritative; keep local timeline builder as a compatibility fallback. | Defer to Phase 7. |
| P0-05 | High | `product-risk` | `factory-agent/factory_agent/planning/tool_selector.py` | `_semantic_route_tool_names` maps semantic routes directly to endpoint names such as `get__machines_{id}`, `get__jobs`, `get__jobs_{id}`, `put__jobs_{id}`, and `patch__jobs_{id}` at lines 802-840. | Semantic routing can break when OpenAPI operation names change even when capabilities remain equivalent. | Capability selector keyed by entity/action/safety/endpoint shape, with endpoint-name fallback only for incomplete metadata. | Defer to Phase 2. |
| P0-06 | High | `product-risk` | `factory-agent/factory_agent/planning/tool_selector.py` | `_diagnostic_tool_names` contains prompt substring shortcuts for `network` + `timeout`, `404` + `read`, low/medium/high/urgent priority job mutations, and `create job` at lines 850-883. | These are production fast paths that can overfit test prompts and bypass broader retrieval/rerank scoring. | Move diagnostic scenario handling behind capability/profile tests or a data-driven diagnostic registry. | Defer; include guard in Phase 1/2 tests. |
| P0-07 | Medium | `product-risk` | `factory-agent/factory_agent/planning/intent.py` | Route-family behavior is encoded in regex constants such as `_ACTION_PATTERNS`, `_LOTO_HINT_RE`, priority-change regexes, and semantic branches; representative hits at lines 73, 104, 137-145, 559-587, and 871. | The semantic frame is useful, but adding new document families can become more Python branch sprawl. | Route-family registry for aliases, required entities, clarification copy, negative routes, and confidence policy. | Defer to Phase 1. |
| P0-08 | Medium | `product-risk` | `factory-agent/factory_agent/services/plan_creation_service.py` | `_fallback_knowledge_answer` embeds OSHA/LOTO answer text, `29 CFR 1910.147`, source metadata, and safety copy at lines 259-289; fallback is merged into RAG responses at lines 350-370. | Product content and source policy are hidden in service logic, making safety/source changes code changes. | Knowledge policy registry with policy id, route family, source metadata, answer template, and allowed environments. | Defer to Phase 3. |
| P0-09 | Medium | `product-risk` | `factory-agent/factory_agent/services/plan_creation_service.py` | Clarification replies are hardcoded in service methods at lines 307-318, including exact LOTO and live-status machine-id prompts. | Prompt copy is part of routing policy and can drift from semantic missing-entity rules. | Store clarification templates alongside semantic route/required-entity policy. | Defer to Phase 1 or Phase 3 depending on registry shape. |
| P0-10 | Medium | `product-risk` | `factory-agent/factory_agent/graph/nodes/planner_loop.py`, `factory-agent/factory_agent/graph/planner_graph_helpers.py`, `factory-agent/factory_agent/graph/planner_graph.py` | Additional production graph paths reference literal `get__jobs`, `get__jobs_{id}`, and `put__jobs_{id}` in search hits such as `graph/nodes/planner_loop.py` lines 421, 475, 491, 565, 568; `graph/planner_graph_helpers.py` lines 724-731 and 795-830; `graph/planner_graph.py` lines 88-112. | Capability-based selection will be incomplete if graph execution keeps independent endpoint-name contracts. | Reuse the same capability/tool-profile seam as Phase 2 for graph planner helpers. | Defer to Phase 2 follow-up scope. |
| P0-11 | High | `runtime-test-hook` | `factory-agent/factory_agent/api/routers/events.py` | Production router defines `_seeded_playwright_mode`, `_playwright/sse-connections`, and records `playwright_seeded_sse_connections` at lines 24-74. | Test-only observability endpoint and state live in the production router, even though gated by environment. | Fault/connection recording adapter installed only for seeded/test runtime. | Defer to Phase 4. |
| P0-12 | Critical | `runtime-test-hook` | `factory-agent/factory_agent/api/routers/events.py` | Activity and notification streams branch on seeded mode and prompt text: `phase 9 out-of-order duplicate sse` at lines 285-286, `phase 9 last-event-id reconnect`, `phase 9 stream drop recovery`, and `phase 14 stream drop commit recovery` at lines 358-369. | Runtime stream behavior can diverge by user prompt content in a production route. | Production no-op fault adapter plus seeded Playwright fault adapter; no prompt substring checks in route loops. | Defer to Phase 4. |

### Test Infrastructure Risks

| ID | Priority | Classification | File/module | Evidence | Why it matters | Desired seam or replacement | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P0-13 | High | `test-infra-risk` | `factory-agent/factory_agent/testing_seeded_adapters.py` | `SeededPlaywrightPlanner.generate_plan` branches on many prompt substrings including `phase 9 multi-step ordered`, `phase 9 stream drop recovery`, `phase 14 bulk partial failure`, `phase 14 go api 500 commit failure`, and `phase 19` at lines 155-391. | Test-only, but it is becoming a second planner whose behavior is encoded in Python branches. | Data-driven seeded scenario engine and generic interpreter. | Defer to Phase 5. |
| P0-14 | High | `test-infra-risk` | `factory-agent/factory_agent/testing_seeded_adapters.py` | Seeded planner falls back to fixture IDs such as `M-CNC-01` and `JOB-SEED-001` at lines 633 and 650; phase-specific write scenarios hardcode `JOB-SEED-005`, `JOB-SEED-009`, and `JOB-SEED-MISSING-014` at lines 1155, 1230-1243, 1454-1489, and 1517-1584. | Valid for seeded tests, but fallback IDs inside planner code can mask missing entity extraction if reused outside seeded mode. | Move fixture IDs into scenario data; interpreter must require explicit scenario fixtures. | Defer to Phase 5. |
| P0-15 | Medium | `test-infra-risk` | `eMas Front/e2e/mock-server/fixtureStore.js` | Mock server routes scenarios from prompt constants and prompt banks, with `prompts:` arrays and `phase19UnknownPrompt` hits at lines 52-58, 871-884, 965-984, and 1007-1035. | Mock browser tests rely on prompt-string routing; acceptable for mocks, but it should stay visibly outside product and not guide production behavior. | Keep in mock adapter; prefer scenario ids/fixture metadata for new mocked cases. | Keep for now; revisit with Phase 5 guardrails. |

### Accepted Fixture Constants

| ID | Priority | Classification | File/module | Evidence | Why it matters | Desired seam or replacement | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P0-16 | Low | `acceptable-fixture` | `eMas Front/e2e/fixtures/factoryAgentFixtures.js` | Canonical happy-path prompt/answer uses `M-CNC-01` at lines 1-4; SSE/retry prompts use the same fixture machine at lines 13-31 and 43; fixture activity rows include `Run complete` at lines 278 and 318. | These are explicit browser fixture rows, not product routing. | Keep in fixture module; do not copy into product code. | Accepted fixture. |
| P0-17 | Low | `acceptable-fixture` | `eMas Front/e2e/support/dataIntegrityScenarios.js`, `eMas Front/e2e/support/realLangGraphScenarios.js` | Canonical `JOB-SEED-001` through `JOB-SEED-026` priority maps appear at lines 9-34 in both support files. | Seeded data integrity checks need stable expected DB rows. | Keep as canonical fixture data; reference by scenario id where possible. | Accepted fixture. |
| P0-18 | Low | `acceptable-fixture` | `eMas Front/e2e/support/intentEntityScenarios.js`, `tests/e2e/scenarios/manual_prompt_regressions.json` | LOTO prompt variants and expected source metadata use `M-CNC-01`, `JOB-SEED-001`, and `LOTO-M-CNC-01` at lines 16-42. | Manual regression bank needs fixed prompts and expected source evidence. | Keep as prompt-bank fixture; product route coverage should be asserted through semantic frame tests. | Accepted fixture. |
| P0-19 | Low | `acceptable-fixture` | `eMas Front/e2e/support/promptRegressionScenarios.js`, `eMas Front/e2e/specs/full-stack-prompt-workflow-regression.spec.js` | Phase 19 prompts and assertions include `Phase 19 prompt regression`, `M-CNC-01`, `JOB-SEED-LARGE-080`, and `Run complete` hits at support lines 13-60 and spec lines 283-377. | End-to-end regression specs intentionally assert user-visible outcomes. | Keep in Playwright fixtures/specs; do not use phase names in product routing. | Accepted fixture. |
| P0-20 | Low | `acceptable-fixture` | `eMas Front/e2e/support/syntheticEnv.js`, `eMas Front/e2e/specs/production-synthetic.spec.js` | Read-only production synthetic canary prompts use `M-CNC-01` at support lines 72-83 and specs assert `Run complete` structurally at lines 42-84 and 167. | Synthetic checks need stable read-only canary text but are not production logic. | Keep as explicit synthetic fixture; maintain read-only wording. | Accepted fixture. |

## Tasks

### Phase 0: Hardcode Inventory And Classification

- [x] Run product-code hardcode searches.
- [x] Run test-fixture hardcode searches.
- [x] Classify every high-signal result as `product-risk`, `runtime-test-hook`, `test-infra-risk`, or `acceptable-fixture`.
- [x] Add owner Module and target seam for each non-acceptable item.
- [x] Record no-refactor decision for acceptable fixture constants.
- [x] Update this tracker with inventory results.

### Phase 1: Guard Semantic Routing Against Overfitting

- [x] Add semantic route matrix cases for procedure/RAG, machine status, job read, job write, approval, cancel, and unsafe action.
- [x] Add negative route assertions for each family.
- [x] Add missing-entity clarification cases that prove no seeded default is invented.
- [x] Add route-family test for unknown document terms.
- [x] Add guardrail preventing new phase-prompt routing branches in production intent code.
- [x] Run backend route tests.

### Phase 2: Capability-Based Tool Selection

- [x] Inspect generated tool vocabulary and capability tags.
- [x] Define semantic route to capability selection rules.
- [x] Preserve endpoint fallback while capability coverage is incomplete.
- [x] Add fake-tool tests proving endpoint names can change when capabilities remain.
- [x] Run tool selector and prompt workflow tests.

### Phase 3: Knowledge Policy Registry

- [x] Create knowledge policy registry Interface.
- [x] Move OSHA/LOTO fallback answer/source/safety content into registry data.
- [x] Refactor `PlanCreationService` to call the registry.
- [x] Add tests for route-scoped fallback behavior.
- [x] Add tests proving unrelated unknown document prompts do not get OSHA/LOTO fallback.

### Phase 4: SSE Fault Injection Adapter

- [x] Define production no-op fault Adapter.
- [x] Define seeded Playwright fault Adapter.
- [x] Move duplicate/out-of-order/drop logic out of main event stream loops.
- [x] Keep test-only connection recording behind seeded mode.
- [x] Run backend SSE runtime tests.
- [x] Run focused seeded Playwright SSE tests.

### Phase 5: Data-Driven Seeded Scenario Engine

- [ ] Define seeded scenario schema.
- [ ] Implement generic interpreter for read-only result scenario.
- [ ] Migrate one simple scenario.
- [ ] Implement approval-chain interpreter.
- [ ] Migrate one approval-chain scenario.
- [ ] Implement partial failure/stale approval interpreters.
- [ ] Migrate remaining high-risk branches in batches.
- [ ] Add guardrail against new phase-prompt branches in `testing_seeded_adapters.py`.
- [ ] Run seeded oracle suite after each batch.

### Phase 6: Typed Snapshot Presentation Contract

- [ ] Define backend typed presentation payload.
- [ ] Add typed operation/final/approval/source/diagnostic states to snapshot.
- [ ] Preserve legacy text fields.
- [ ] Add contract tests that assert typed state and reject stale text-only state.
- [ ] Run snapshot/final response and API/UI alignment tests.

### Phase 7: Frontend Typed Presentation Rendering

- [ ] Teach turn assembler to prefer typed presentation blocks.
- [ ] Teach activity timeline to prefer typed state.
- [ ] Keep legacy text parser as fallback.
- [ ] Add component tests with changed wording but same typed state.
- [ ] Add browser test proving stale hidden text cannot override typed state.
- [ ] Run frontend unit and seeded browser suites.

### Phase 8: Hardcode Guardrails In CI

- [ ] Add hardcode guard pytest.
- [ ] Add fixture allowlist.
- [ ] Add product-code denylist for phase prompt branches and seeded mode branches.
- [ ] Decide warning vs blocking mode.
- [ ] Wire into backend oracle command or documented release gate.
- [ ] Update README/QA docs with hardcode policy.

## Commands Run

```powershell
git status --short --branch
rg --files -g "CONTEXT.md" -g "docs/adr/**" -g "ADR*.md"
git log --oneline -5
rg -n "phase 9|phase 10|phase 13|phase 14|phase 15|phase 16|phase 18|phase 19|M-CNC-01|JOB-SEED|_scenario_by_session|seeded|playwright_seeded|fallback|hardcod|if .* in lowered|includes\(|will be updated from|please approve|risk summary|executing the following plan|run complete|text/event-stream|Last-Event-ID" "factory-agent/factory_agent" "eMas Front/src/components/features/chat" "eMas Front/e2e" -g "!factory-agent/factory_agent/tools.md" -g "!**/node_modules/**"
rg -n "SemanticFrame|semantic_frame_for_text|route=|negative_route_assertions|missing_required_entities|_semantic_route_tool_names|_fallback_knowledge_answer|_seeded_playwright_mode|_snapshot_intent_contains" "factory-agent/factory_agent/planning/intent.py" "factory-agent/factory_agent/planning/tool_selector.py" "factory-agent/factory_agent/services/plan_creation_service.py" "factory-agent/factory_agent/api/routers/events.py"
rg -n -i "phase 9|phase 14|phase 19|M-CNC-01|JOB-SEED|playwright_seeded|seeded_playwright|fallback|please approve|will be updated from|risk summary|run complete|get__jobs|put__jobs_\{id\}" "factory-agent/factory_agent" -g "!factory-agent/factory_agent/tools.md"
rg -n -i "phase 9|phase 14|phase 19|M-CNC-01|JOB-SEED|playwright_seeded|seeded_playwright|fallback|please approve|will be updated from|risk summary|run complete|get__jobs|put__jobs_\{id\}" "eMas Front/src/components/features/chat"
rg -n -i "phase 9|phase 14|phase 19|M-CNC-01|JOB-SEED|playwright_seeded|seeded_playwright|fallback|please approve|will be updated from|risk summary|run complete|get__jobs|put__jobs_\{id\}" "eMas Front/e2e" -g "!**/node_modules/**"
rg -n "phase 9 multi|phase 9 approval|phase 9 partial|phase 9 schema|phase 9 duplicate|phase 9 out-of-order|phase 9 last-event-id|phase 9 stream drop|phase 14 cascading|phase 14 bulk|phase 14 idempotent|phase 14 refresh|phase 14 stream drop|phase 14 go api|phase 14 stale|phase 14 expired|phase 19|M-CNC-01|JOB-SEED-001|JOB-SEED-005|JOB-SEED-009" "factory-agent/factory_agent/testing_seeded_adapters.py"
git status --short --branch
git diff --check
python -m pytest tests/test_intent_splitter.py tests/test_phase19_prompt_workflow_regression.py -q
python -m pytest tests/test_intent_splitter.py -q
python -m pytest tests/test_tool_selector.py -q
python -m pytest tests/test_tool_intent_profile.py -q
python -m pytest tests/test_intent_splitter.py tests/test_phase19_prompt_workflow_regression.py -q
python -m pytest tests/test_rag_knowledge_policy.py -q
python -m pytest tests/test_api_endpoints.py::test_create_plan_answers_osha_loto_knowledge_question_without_tool_plan tests/test_api_endpoints.py::test_create_plan_uses_osha_loto_policy_fallback_when_rag_is_empty tests/test_api_endpoints.py::test_create_plan_unknown_non_loto_procedure_does_not_borrow_osha_policy -q
python -m pytest tests/test_phase19_prompt_workflow_regression.py -q
python -m pytest tests/test_rag_* -q
python -m pytest tests/test_rag_generation.py tests/test_rag_ingestion.py tests/test_rag_live_llm.py tests/test_rag_retrieval.py tests/test_rag_reranking.py tests/test_rag_knowledge_policy.py -q
python -m pytest tests/test_event_stream_runtime.py -q
python -m pytest tests/test_event_stream_runtime.py tests/test_intent_splitter.py tests/test_snapshot_timeline_final_response_contract.py -q
npm test -- --runInBand
npm run test:e2e -- --project=chromium-seeded --grep "@sse|stream drop|Last-Event-ID|out-of-order"
git status --short --branch
git diff --check
```

## Test Results

- `git status --short --branch`: confirmed branch `codex/playwright-e2e-plan`; only the two QA docs were untracked/changed during Phase 0.
- `git diff --check`: passed for the documentation-only working tree.
- Product tests were not run because Phase 0 is documentation-only and does not change product or test behavior.
- Phase 1 focused verification:
  - `python -m pytest tests/test_intent_splitter.py -q`: 35 passed, 1 warning.
  - `python -m pytest tests/test_intent_splitter.py tests/test_phase19_prompt_workflow_regression.py -q`: 77 passed, 1 warning.
- Phase 2 focused verification:
  - `python -m pytest tests/test_tool_selector.py -q`: 21 passed, 12 warnings.
  - `python -m pytest tests/test_tool_intent_profile.py -q`: 10 passed, 1 warning.
  - `python -m pytest tests/test_intent_splitter.py tests/test_phase19_prompt_workflow_regression.py -q`: 77 passed, 1 warning.
- Phase 3 focused verification:
  - `python -m pytest tests/test_rag_knowledge_policy.py -q`: 4 passed, 3 warnings.
  - `python -m pytest tests/test_api_endpoints.py::test_create_plan_answers_osha_loto_knowledge_question_without_tool_plan tests/test_api_endpoints.py::test_create_plan_uses_osha_loto_policy_fallback_when_rag_is_empty tests/test_api_endpoints.py::test_create_plan_unknown_non_loto_procedure_does_not_borrow_osha_policy -q`: 3 passed, 42 warnings.
  - `python -m pytest tests/test_phase19_prompt_workflow_regression.py -q`: 42 passed, 3 warnings.
  - `python -m pytest tests/test_rag_* -q`: failed before collection because PowerShell passed the wildcard literally; pytest reported `file or directory not found: tests/test_rag_*`.
  - `python -m pytest tests/test_rag_generation.py tests/test_rag_ingestion.py tests/test_rag_live_llm.py tests/test_rag_retrieval.py tests/test_rag_reranking.py tests/test_rag_knowledge_policy.py -q`: first run hit `WinError 5` creating pytest temp dirs under the user temp path; rerun with `TMP`/`TEMP` pointed at a workspace temp dir passed with 29 passed, 1 skipped, 3 warnings.
  - `git diff --check`: passed with CRLF normalization warnings only.
  - No Phase 3 product bug was found.
- Phase 4 focused verification:
  - `python -m pytest tests/test_event_stream_runtime.py -q`: 10 passed, 3 warnings.
  - `python -m pytest tests/test_event_stream_runtime.py tests/test_intent_splitter.py tests/test_snapshot_timeline_final_response_contract.py -q`: 90 passed, 3 warnings.
  - `npm test -- --runInBand`: 66 passed.
  - `npm run test:e2e -- --project=chromium-seeded --grep "@sse|stream drop|Last-Event-ID|out-of-order"`: 5 passed.
  - New coverage proves the production/no-op adapter does not inject seeded activity faults, the seeded Playwright adapter injects duplicate/out-of-order activity frames, notification stream drop happens once, Last-Event-ID reconnect continues with snapshot invalidation, and `events.py` no longer contains seeded phase prompt branches.
- Baseline reported by user for semantic routing commit:
  - `python -m pytest tests/test_intent_splitter.py tests/test_phase19_prompt_workflow_regression.py -q`: 63 passed
  - Compatibility checks: 20 passed
  - `npm test`: 64 passed
  - Seeded Chromium grep: 4 passed
  - `git diff --check`: passed with CRLF warnings

## Files Changed

- `docs/qa/HARDCODE_REDUCTION_PLAN.md`
- `docs/qa/HARDCODE_REDUCTION_TRACK.md`
- `factory-agent/factory_agent/planning/intent.py`
- `factory-agent/factory_agent/rag/knowledge_policy.py`
- `factory-agent/factory_agent/planning/tool_intent_profile.py`
- `factory-agent/factory_agent/planning/tool_selector.py`
- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/factory_agent/api/routers/events.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/testing/__init__.py`
- `factory-agent/factory_agent/testing/fault_injection.py`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `eMas Front/src/components/features/chat/turns/turnAssembler.js`
- `eMas Front/src/components/features/chat/turns/turnAssembler.test.mjs`
- `factory-agent/tests/test_intent_splitter.py`
- `factory-agent/tests/test_api_endpoints.py`
- `factory-agent/tests/test_event_stream_runtime.py`
- `factory-agent/tests/test_rag_knowledge_policy.py`
- `factory-agent/tests/test_snapshot_timeline_final_response_contract.py`
- `factory-agent/tests/test_tool_selector.py`

## Next Action

Start Phase 5. Migrate seeded planner scenario branches into data-driven scenario definitions.
