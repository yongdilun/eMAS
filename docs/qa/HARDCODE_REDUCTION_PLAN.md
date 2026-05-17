# Hardcoded Logic Reduction Plan

Branch: `codex/playwright-e2e-plan`
Baseline commit observed: `3e50209 test: add semantic routing contract`

## Purpose

The chatbot test pipeline is now strong enough to reveal product bugs, but the next risk is architectural: some production and test Modules still encode behavior through prompt strings, fixture IDs, phase names, and user-visible text. Adding more defensive scenarios before reducing these hardcoded paths will create more coverage volume without enough leverage.

This plan pauses broad new scenario growth and focuses on replacing hardcoded logic with deeper Modules, clearer Interfaces, and testable seams. After these phases are complete, return to discovering more scenarios and product bugs.

## Answer To The Main Question

Do not fix every hardcoded value now.

Fix or isolate hardcodes in this order:

1. Product logic that can affect real users.
2. Runtime test hooks mixed into production routes.
3. Test adapters that are becoming duplicate product implementations.
4. Frontend text inference that decides state from wording.
5. Fixture constants that are explicit seeded data.

Some hardcodes should remain: seeded job IDs, canonical test prompts, known fixture rows, and expected visible text in tests. Those are acceptable when they live in fixture files and do not drive production behavior.

## Current State

Semantic routing contract has been implemented:

- `factory-agent/factory_agent/planning/intent.py` now exposes `SemanticFrame` and `semantic_frame_for_text`.
- `factory-agent/factory_agent/planning/tool_selector.py` uses semantic route hints before fallback selection.
- `factory-agent/factory_agent/services/plan_creation_service.py` uses semantic frames for clarifications and RAG/procedure routing.
- Phase 19 prompt workflow regression tests and frontend unit tests passed after the semantic routing commit.

Remaining hardcoded risk is concentrated in these Modules:

| Area | Files | Risk |
| --- | --- | --- |
| Semantic route implementation | `factory-agent/factory_agent/planning/intent.py` | Route families are still implemented as Python regex branches. Good short-term Interface, but future document terms could become more prompt-specific code. |
| Tool selection | `factory-agent/factory_agent/planning/tool_selector.py` | Semantic routes map to literal endpoint names like `get__jobs`, `put__jobs_{id}`, and `get__machines_{id}`. This can drift when OpenAPI tools change. |
| Knowledge fallback | `factory-agent/factory_agent/services/plan_creation_service.py` | OSHA/LOTO fallback answer and source metadata are embedded in service code. |
| Seeded planner adapter | `factory-agent/factory_agent/testing_seeded_adapters.py` | Large branch tree selects behavior from phase prompt text and fixture IDs. Test-only, but it is becoming a second planner. |
| Runtime SSE faults | `factory-agent/factory_agent/api/routers/events.py` | Playwright seeded fault behavior is mixed into the production SSE router. |
| Snapshot/final-response projection | `factory-agent/factory_agent/services/session_snapshot_service.py` | Backend infers plan, approval, success, and failure meaning from user-visible strings. |
| Frontend chat rendering | `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`, `eMas Front/src/components/features/chat/turns/turnAssembler.js`, `eMas Front/src/components/features/chat/factory-agent/activityTimelineUtils.js` | UI still infers state from phrases like `please approve`, `risk summary`, and `will be updated from`. |
| Playwright mock fixtures | `eMas Front/e2e/mock-server/fixtureStore.js`, `eMas Front/e2e/support/*.js` | Many phase strings and seeded IDs are acceptable as fixtures, but should not become hidden product logic. |

## Architecture Principles

- The Interface is the test surface. Tests should assert typed state, route evidence, approval evidence, and presentation blocks, not only final text.
- Product Modules should not branch on Playwright phase names or fixture IDs.
- Test-only fixture hardcodes are acceptable when isolated behind an Adapter seam.
- A route family should be represented once, then tested many times through data.
- Browser tests should prove user-visible divergence only. Parser/route wording matrices should stay at lower layers.
- Every hardcode removal phase must include a regression that would fail if the old hardcoded behavior returned.

## Target Architecture

### Semantic Routing Registry

The semantic frame should remain the main Interface:

```json
{
  "domain_intent": "loto_procedure",
  "route": "rag.loto_procedure",
  "normalized_entities": { "machine_id": ["M-CNC-01"] },
  "missing_required_entities": [],
  "confidence": 0.93,
  "negative_route_assertions": ["tool.read.machine_status"]
}
```

Future improvement: move route family definitions, aliases, required entities, clarification messages, and negative routes into a data registry so adding a new document family does not require more branch logic.

### Tool Capability Selection

Tool selection should choose by capability profile:

- entity: `job`, `machine`, `approval`, `session`
- action: `read`, `write`, `approve`, `reject`, `cancel`
- operation safety: `read_only`, `approval_required`, `dangerous_unsupported`
- endpoint shape: collection, item, mutation

Literal endpoint names may remain as final candidates, but not as the primary semantic route contract.

### Knowledge Policy Registry

Curated fallback answers and source metadata should live in a registry or fixture pack:

- policy id
- matching route family
- required source metadata
- answer template or safe fallback
- safety disclaimer
- allowed environments

`PlanCreationService` should call this registry instead of embedding OSHA/LOTO copy.

### Seeded Scenario Engine

The seeded planner should use scenario definitions, not prompt substring branches:

- scenario id
- trigger prompt or test metadata
- operation graph
- approval steps
- fixture rows
- fault injection
- expected snapshot/final response evidence

The seeded Adapter should interpret scenario data. It should not contain one Python branch per phase.

### SSE Fault Injection Adapter

Production SSE routes should expose stable stream behavior. Test-only drop, duplicate, and out-of-order behavior should move to a fault Adapter enabled only in seeded/test mode.

### Typed Presentation Contract

Backend snapshots should expose typed presentation blocks:

- `presentation.kind`: `answer`, `approval_required`, `mutation_result`, `partial_failure`, `diagnostic`, `cancelled`, `rejected`, `expired`, `knowledge_answer`
- `presentation.state`: `pending`, `completed`, `failed`, `blocked`, `rejected`, `expired`, `cancelled`
- `presentation.operation_id`
- `presentation.approval_id`
- `presentation.rows`
- `presentation.sources`
- `presentation.summary`
- `presentation.diagnostics`
- `presentation.invariants` including stale/full-success guard evidence

Frontend should render this contract instead of detecting state from text.

## Phased Plan

### Phase 0: Hardcode Inventory And Classification

Goal: Create a precise inventory before changing behavior.

Files likely touched:

- `docs/qa/HARDCODE_REDUCTION_TRACK.md`
- Optional new inventory file under `docs/qa/`

Implementation steps:

- Search product, backend test, and frontend test code for phase names, seeded IDs, prompt substrings, fallback strings, and user-visible state phrases.
- Classify each item as `product-risk`, `runtime-test-hook`, `test-infra-risk`, or `acceptable-fixture`.
- Mark the owner Module and the desired seam.
- Decide which items are not worth refactoring.

Acceptance criteria:

- Tracker contains an inventory table with priority, classification, and decision.
- No behavior changes.
- No test changes except optional inventory verification.

Verification command:

```powershell
git status --short --branch
rg -n "phase 9|phase 10|phase 14|M-CNC-01|JOB-SEED|playwright_seeded|fallback|please approve|will be updated from|risk summary" factory-agent/factory_agent "eMas Front/src/components/features/chat" "eMas Front/e2e"
```

Risks or unknowns:

- Search results include many valid fixture constants.

Rollback notes:

- Documentation-only phase. Revert docs if classification is wrong.

### Phase 1: Guard Semantic Routing Against Overfitting

Goal: Keep the new semantic frame, but prevent it from becoming another pile of prompt-specific branches.

Files likely touched:

- `factory-agent/factory_agent/planning/intent.py`
- `factory-agent/tests/test_intent_splitter.py`
- `factory-agent/tests/test_phase19_prompt_workflow_regression.py`
- `tests/e2e/scenarios/manual_prompt_regressions.json`

Implementation steps:

- Add route-family regression tests that use varied wording without adding one-off production branches.
- Add negative route assertions for procedure vs live status vs mutation vs unsafe action.
- Add one route-family contract test that proves unknown document terms produce clarification or safe unknown, not fake success.
- Add a hardcode guard test that fails if new `phase N` prompt branches are added to semantic routing.

Acceptance criteria:

- Semantic frame is stable across route families.
- No missing machine ID defaults to `M-CNC-01`.
- New wording variants are represented in tests or route data, not ad hoc product branches.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_intent_splitter.py tests/test_phase19_prompt_workflow_regression.py -q
```

Risks or unknowns:

- Too strict a route contract can over-clarify real user prompts.

Rollback notes:

- Keep old helper wrappers while replacing internals so callers are not broken.

### Phase 2: Replace Literal Tool Mapping With Capability Selection

Goal: Make semantic routes select tools by capability profile instead of hardcoded endpoint names.

Files likely touched:

- `factory-agent/factory_agent/planning/tool_selector.py`
- `factory-agent/factory_agent/planning/tool_intent_profile.py`
- `factory-agent/factory_agent/planning/tool_scope.py`
- `factory-agent/tests/test_tool_selector.py` or equivalent selector tests

Implementation steps:

- Define a small capability selection Interface for semantic route to candidate tools.
- Use generated tool vocabulary/capability tags first.
- Keep endpoint-name fallback only when capability tags are missing.
- Add tests that rename or replace a fake endpoint while keeping capability tags, proving route selection still works.

Acceptance criteria:

- Semantic routes can select read/write job, machine, approval, and cancel tools without relying on one exact endpoint name.
- Existing direct lookup and fallback rerank behavior still works.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_intent_splitter.py tests/test_phase19_prompt_workflow_regression.py tests/test_tool_selector.py -q
```

Risks or unknowns:

- Tool metadata may be incomplete or inconsistent.

Rollback notes:

- Preserve literal endpoint fallback behind the capability selector until metadata coverage is proven.

### Phase 3: Move Knowledge Fallbacks Into A Policy Registry

Goal: Remove embedded OSHA/LOTO fallback answer/source copy from `PlanCreationService`.

Files likely touched:

- `factory-agent/factory_agent/services/plan_creation_service.py`
- New `factory-agent/factory_agent/rag/knowledge_policy.py` or similar
- New fixture/registry file if needed
- `factory-agent/tests/test_phase19_prompt_workflow_regression.py`
- `factory-agent/tests/test_rag_*`

Implementation steps:

- Create a knowledge policy registry Adapter.
- Move OSHA/LOTO fallback answer, sources, and safety content into registry data.
- Make `PlanCreationService` ask the registry by semantic route and query context.
- Add tests for source metadata, safety copy, and no fake answer when no policy applies.

Acceptance criteria:

- `PlanCreationService` no longer embeds OSHA/LOTO answer text.
- LOTO still returns source-backed fallback when RAG is empty.
- Non-LOTO unknown document prompts do not borrow the OSHA fallback.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_phase19_prompt_workflow_regression.py tests/test_rag_* -q
```

Risks or unknowns:

- Current tests may assert exact fallback text.

Rollback notes:

- Keep old fallback content as registry data so behavior remains stable.

### Phase 4: Extract Runtime SSE Fault Injection

Goal: Remove Playwright seeded fault branches from production SSE router logic.

Files likely touched:

- `factory-agent/factory_agent/api/routers/events.py`
- New `factory-agent/factory_agent/testing/fault_injection.py` or similar
- `factory-agent/tests/test_event_stream_runtime.py`
- `eMas Front/e2e/specs/full-stack-sse-hard.spec.js`

Implementation steps:

- Define a fault injection Interface with a production no-op Adapter.
- Move seeded drop, duplicate, and out-of-order logic behind the Adapter.
- Select the test Adapter only in seeded Playwright mode.
- Keep `/ _playwright / sse-connections` behavior test-only.

Acceptance criteria:

- Production event router does not contain prompt text checks for `phase 9` or `phase 14`.
- Seeded SSE tests still cover duplicate, out-of-order, reconnect, drop, and disconnect behavior.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_event_stream_runtime.py -q
Set-Location "..\eMas Front"
npm run test:e2e -- --project=chromium-seeded --grep "@sse|stream drop|Last-Event-ID"
```

Risks or unknowns:

- Browser reconnect behavior is sensitive to timing.

Rollback notes:

- Re-enable old seeded branches only as a temporary test Adapter if the seam breaks seeded flakes.

### Phase 5: Convert Seeded Planner Branch Tree To Scenario Data

Goal: Stop adding one Python branch per scenario in `testing_seeded_adapters.py`.

Files likely touched:

- `factory-agent/factory_agent/testing_seeded_adapters.py`
- `tests/e2e/scenarios/stateful_oracles/*.json`
- New seeded scenario interpreter Module
- `factory-agent/tests/test_stateful_oracle_schema.py`
- `eMas Front/e2e/specs/full-stack-*.spec.js`

Implementation steps:

- Define a seeded operation scenario schema.
- Move phase/scenario prompt matching into scenario metadata.
- Implement a generic interpreter for:
  - read-only result
  - approval chain
  - partial failure
  - stale/expired approval
  - SSE fault request
  - large result
- Migrate one high-risk scenario first, then migrate the rest in batches.
- Add a guard test that fails on new `if "phase ..."` branches in the seeded planner.

Acceptance criteria:

- New seeded scenarios can be added by JSON/fixture data plus assertions, not planner code branches.
- Existing seeded oracle suite still passes.
- `testing_seeded_adapters.py` becomes smaller and acts as an Adapter, not a scenario catalog.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_stateful_oracle_schema.py tests/test_langgraph_state_machine_oracles.py tests/test_snapshot_timeline_final_response_contract.py -q
Set-Location "..\eMas Front"
npm run test:e2e:seeded-oracles
```

Risks or unknowns:

- This is the highest migration effort. Do it incrementally.

Rollback notes:

- Keep legacy branch handling for unmigrated scenarios until each batch passes.

### Phase 6: Introduce Typed Snapshot Presentation Contract

Goal: Stop backend final-response and timeline projection from relying on visible text phrases.

Files likely touched:

- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/schemas.py`
- `factory-agent/factory_agent/analysis/summary_backend.py`
- `factory-agent/tests/test_snapshot_timeline_final_response_contract.py`
- `factory-agent/tests/support/operation_assertions.py`

Implementation steps:

- Add typed `presentation` blocks to snapshot/final response payloads.
- Include operation state, approval state, row-level mutation state, source state, and diagnostic state.
- Include rejected, expired, cancelled, and source-backed knowledge-answer states explicitly.
- Preserve existing text fields for compatibility.
- Add contract tests that use typed fields first and reject stale text-only state.

Acceptance criteria:

- Final response correctness can be asserted without phrase matching.
- Approval pending/rejected/expired/completed state is explicit.
- Partial failure and multi-approval summaries include typed row evidence.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_snapshot_timeline_final_response_contract.py tests/test_phase7_api_ui_alignment.py -q
```

Risks or unknowns:

- Frontend still needs old text fields until Phase 7.

Rollback notes:

- Additive schema change first. Do not remove old fields until frontend migration passes.

### Phase 7: Render Frontend From Typed Presentation

Goal: Remove frontend state decisions based on phrases like `please approve` and `will be updated from`.

Files likely touched:

- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `eMas Front/src/components/features/chat/turns/turnAssembler.js`
- `eMas Front/src/components/features/chat/factory-agent/activityTimelineUtils.js`
- frontend component tests
- Playwright seeded/browser specs

Implementation steps:

- Teach turn assembler to prefer typed presentation blocks.
- Keep text heuristics only as legacy fallback.
- Add tests where visible text wording changes but typed state stays the same.
- Add tests where stale text exists in hidden details but typed state prevents wrong UI.

Acceptance criteria:

- UI approval cards, activity timeline, source chrome, and final result render from typed state.
- Closing/collapsing UI does not auto-expand because of stale text events.
- Existing browser oracle coverage remains green.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e:mocked
npm run test:e2e:seeded-oracles
```

Risks or unknowns:

- The UI may depend on current text cleanup for old sessions.

Rollback notes:

- Keep fallback text parser for legacy sessions until production data confirms typed presentation is always present.

### Phase 8: Hardcode Guardrails In CI

Goal: Prevent regression back to one-off prompt branches after cleanup.

Files likely touched:

- `factory-agent/tests/test_hardcode_guardrails.py`
- `eMas Front/e2e/README.md`
- `docs/qa/HARDCODE_REDUCTION_TRACK.md`
- CI/package scripts as needed

Implementation steps:

- Add allowlisted hardcode guard tests.
- Fail when product code adds new Playwright phase prompt branches.
- Fail when production routes branch on seeded scenario names.
- Allow fixture files through explicit path/reason allowlists rather than warning-only checks.
- Document how to add a legitimate fixture hardcode.
- Wire the guard into `npm run test:backend-oracles` when the allowlist is focused enough to avoid false positives.

Acceptance criteria:

- CI catches new product hardcodes.
- Fixture constants remain allowed in known fixture files.
- Frontend phrase-based legacy fallbacks are count/reason allowlisted and typed `presentation` remains the preferred state contract.
- New scenario work resumes only after guardrails are in place.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_hardcode_guardrails.py -q
```

Risks or unknowns:

- Guardrail false positives can block useful work.
- Keep broad fixture prompt banks out of product/runtime scans; promote any new legitimate fixture hardcode by adding it to scenario data, test data, or docs with an explicit reason.

Rollback notes:

- Start with warnings or targeted allowlist, then promote to blocking.

## Extra Tests Needed

These tests should be added before or during the refactor phases:

| Test | Layer | Purpose |
| --- | --- | --- |
| Hardcode inventory guard | Pytest | Detect new phase-string branches in product code. |
| Semantic route property matrix | Pytest | Prove route families survive wording variation without new branches. |
| Capability selector contract | Pytest | Prove semantic routes select tools by capability, not endpoint name. |
| Knowledge policy registry test | Pytest | Prove curated fallback sources are data-backed and route-scoped. |
| SSE fault Adapter test | Pytest + Playwright | Prove production router is clean while seeded faults still work. |
| Seeded scenario interpreter test | Pytest | Prove scenario JSON drives seeded behavior. |
| Snapshot typed presentation contract | Pytest | Prove final/timeline state does not depend on text phrases. |
| Frontend wording-insensitive render test | Vitest/node | Prove UI renders state correctly when text wording changes. |
| Browser stale-text negative test | Playwright | Prove hidden stale approval/success text cannot override typed state. |

## Stop Conditions

Stop and fix before proceeding when:

- A product behavior bug is found.
- A refactor removes evidence used by current oracle tests.
- A typed contract cannot represent an existing valid state.
- A route family starts requiring one-off prompt code again.
- A browser test passes only because seeded fixtures no longer exercise the real backend contract.

## Resume Criteria For More Scenario Discovery

Return to new scenario hunting only after:

- Phases 0 through 8 are either complete or explicitly accepted as partial.
- Product hardcode guardrails are active.
- Seeded planner additions are data-driven or justified in the tracker.
- Frontend no longer needs text phrases as the primary state Interface.
- The tracker lists remaining accepted hardcodes with owners.
