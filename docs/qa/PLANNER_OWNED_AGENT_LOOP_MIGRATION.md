# Planner-Owned Agent Loop Migration Plan And Tracker

Branch: `codex/playwright-e2e-plan`
Created: 2026-05-20
Progress tracker: [`PLANNER_OWNED_AGENT_LOOP_MIGRATION_TRACK.md`](PLANNER_OWNED_AGENT_LOOP_MIGRATION_TRACK.md)

## Purpose

Migrate Factory Agent from a splitter-scaffolded planner loop to a planner-owned agent loop where requirements are explicit ledger state, the planner decides the next capability need, and a tool retriever finds a small set of matching API or RAG tools for that need.

The goal is to keep the LLM planner as the decision-making brain while making orchestration more durable, auditable, cheaper on obvious read paths, and safer for mixed API/RAG/write/approval workflows.

## Current Design Summary

Current high-level shape:

```text
User request
-> ToolSelector scopes tools once from the whole query
-> intent_splitter creates working_intents
-> planner_loop walks working_intents with intent_cursor
-> tool execution
-> relevance filter
-> planner_loop marks one intent_completed at a time
-> response_document
```

Current useful pieces to keep:

- `split_user_intents` extracts obvious clauses, entities, and hard constraints.
- `semantic_frame_for_text` helps distinguish operational state, document knowledge, approval, unsupported dangerous actions, and clarification cases.
- `ToolSelector` already has retrieval, deterministic scoring, optional reranking, candidate pool/top-k settings, and capability-aware helpers such as `CapabilitySelectionRequest`.
- Tool metadata and generated vocabulary already carry growing entity/capability information.
- Response documents already provide typed frontend rendering contracts.
- Approval, stale approval, cancel, and response-document evidence contracts already exist.

Current weak points to fix:

- `working_intents` is treated like an execution scaffold instead of only a proposal.
- Planner can mark intent state but cannot cleanly revise agenda structure.
- RAG is still partly route-short-circuited instead of being available as a first-class tool candidate.
- Read-only multi-intent flows can call the planner repeatedly only to emit `intent_completed`.
- New user messages during `EXECUTING` are stored in `pending_user_message`, but that is not yet a real interrupt/replan controller.
- It is easy for future work to claim "v2" while silently using legacy RAG or legacy intent-completion paths.

## Target Design

Target high-level shape:

```text
User request
-> semantic intake
-> requirement sketcher creates editable requirement ledger
-> deterministic hard-constraint guard locks IDs, filters, sort, limit, fields, approvals, and safety requirements
-> planner sees original goal, requirement ledger, evidence, and high-level capability map
-> planner declares the next capability need
-> V2CapabilityToolRetriever adapts that need into the existing ToolSelector retrieval/ranking path
-> planner receives a small hydrated candidate set
-> planner chooses exact tool and args
-> deterministic guard validates constraints, schema, safety, approval, and source-of-truth policy
-> execute one tool, RAG tool, or parallel read batch
-> observe typed evidence into evidence_ledger
-> requirement ledger updates statuses, evidence refs, revisions, and blockers
-> planner decides the next sub-goal or finalizes
-> final validator checks no required item remains open, dropped, or uncited
-> response_document renders from accepted requirements and evidence
```

Design principles:

- The splitter is an intake helper, not the agenda owner or the tool retrieval owner.
- The requirement sketcher proposes an editable ledger; it does not freeze the plan.
- The planner asks for the next capability; the retriever finds tools only for that capability need.
- V2 reuses the existing `ToolSelector` ranking/retrieval system through a thin adapter instead of creating a second retriever.
- RAG is a tool family with typed output contracts, not a special hidden response path.
- The planner owns next-step decisions and agenda/reasoning revisions.
- Deterministic guards own hard constraints, approvals, source-of-truth policy, and safety; the planner may revise requirements but cannot silently drop locked constraints.
- Deterministic satisfaction can close obvious read requirements, but uncertain evidence returns to the planner.
- Shadow/v2 mode must expose `engine_version` and execution path evidence so tests can prove which loop ran.
- New tools, entities, or RAG sources should require metadata/vocabulary/capability-map updates, not product-code branches for specific IDs, prompts, or source labels.

## Core V2 Concepts

| Concept | Meaning |
| --- | --- |
| `engine_version` | Explicit runtime label: `legacy`, `v2_shadow`, or `v2`. |
| `capability_map` | Compact high-level list of available capability families, not full schemas. |
| `capability_need` | Planner-declared next need, such as read machine status or search procedure documents. |
| `v2_capability_tool_retriever` | Thin adapter from planner `capability_need` to existing `ToolSelector` candidate retrieval. |
| `tool_selector_adapter_request` | Normalized request passed to `ToolSelector`, preserving entity, actions, safety, endpoint shape, requested fields, and constraints. |
| `tool_retrieval_slices` | Optional splitter output used as hints for requirements/source-of-truth, not as execution agenda. |
| `candidate_tool_window` | Small candidate API/RAG tool set retrieved for the current capability need. |
| `hydrated_tool_cards` | Full OpenAPI/RAG schemas only for the current small candidate window. |
| `source_of_truth` | `operational_state`, `document_knowledge`, `mixed`, or `unknown`. |
| `requirement_sketch` | Lightweight first pass over user goals, entities, constraints, requested fields, and source-of-truth hints. |
| `requirement_ledger` | Planner-editable list of required, optional, blocked, fulfilled, and superseded requirements. |
| `locked_constraints` | Deterministically protected user constraints such as IDs, filters, sort, limit, fields, approval, and safety. |
| `field_aliases` | Metadata-driven mapping from user words like status, deadline, due date, priority, or quantity to tool fields. |
| `requirement_type` | What the user is owed, such as `single_entity_status`, `filtered_collection`, `document_answer`, or `approval_request`. |
| `intent_operation` | User-facing operation label, such as `report_status` or `report_filtered_collection`; not an executable tool action. |
| `evidence_ledger` | Typed tool/RAG outputs used to satisfy requirements and render final response. |
| `satisfaction_state` | Deterministic state showing fulfilled, blocked, ambiguous, and pending requirements. |
| `agenda_patch` | Planner proposal to add, split, merge, remove dependency, or revise requirements. |
| `revision_history` | Audit trail for planner edits, guard rejections, user interruptions, and final validator decisions. |
| `execution_trace` | Per-run proof of engine version, generated-by path, planner calls, retrieval calls, selected tools, legacy bypass checks, and final validator status. |

## Locked Architecture Decisions

These decisions are already settled and should not be reopened without a new explicit design review:

1. Use trace-only `v2_shadow` first. Legacy returns the visible answer while v2 records planner actions, capability needs, retrieval windows, requirement/evidence state, and expected response contracts. Production shadow mode must not commit writes.
2. Use a two-pass deterministic guard around the LLM requirement sketcher. The pre-pass extracts hard constraints; the post-pass verifies the sketch preserved them before the ledger is accepted.
3. The sketcher vocabulary must come from a generated capability registry only. No normal handwritten runtime vocabulary overrides, exact-prompt branches, seeded-ID branches, or entity-label branches.
4. Reuse the current `ToolSelector` through a `V2CapabilityToolRetriever` adapter. Do not build a second retrieval/ranking stack.
5. The real planner owns execution and replanning. The sketcher and retriever are helpers, not hidden planners.

## Vocabulary Boundaries

Do not mix these layers:

| Layer | Meaning | Example values |
| --- | --- | --- |
| Requirement | What the user is owed. | `single_entity_status`, `filtered_collection`, `document_answer` |
| Capability need | What ability the planner needs next. | `read_one`, `list`, `search_documents`, `update` |
| Tool call | Exact executable API/RAG invocation. | `get__machines_{id}`, `get__jobs`, `rag_search_documents` |
| Evidence | What has been proven by a tool/RAG result. | `api_tool` result with matched entity id and requested fields |

Allowed `requirement_type` values:

```text
single_entity_status
multi_entity_status
filtered_collection
document_answer
mutation_request
approval_request
clarification_request
safety_refusal
diagnostic
```

Allowed requirement `status` values:

```text
open        = not yet attempted or not yet satisfied
blocked     = waiting on user input, approval, dependency, or safe precondition
satisfied   = evidence proves the requirement is fulfilled
skipped     = intentionally not executed because a condition was not met
impossible  = cannot be satisfied because tool, data, source, or policy support is unavailable
superseded  = replaced by a newer user revision or planner-approved ledger revision
failed      = attempted but failed unexpectedly
```

Capability/tool operation values should stay separate from requirement types. Examples:

```text
read_one
read_many
list
search_documents
update
create
approve
reject
cancel
```

## Requirement Sketcher And Ledger Contract

The requirement sketcher is a low-risk intake helper. It should extract obvious structure and hard constraints, but it should not decide execution order or final answers.

Example ledger state:

```json
{
  "user_goal": "Show M-CNC-01 status, then show JOB-SEED-001 status, then list the next 3 low priority jobs sorted by deadline.",
  "requirements": [
    {
      "id": "req-001",
      "goal": "Report machine status",
      "requirement_type": "single_entity_status",
      "entity": "machine",
      "intent_operation": "report_status",
      "source_of_truth": "operational_state",
      "constraints": {"machine_id": "M-CNC-01"},
      "requested_fields": ["status"],
      "locked_constraints": ["machine_id", "requested_fields"],
      "status": "open",
      "evidence_refs": [],
      "origin": {
        "goal": "llm_requirement_sketch",
        "constraints": "deterministic_extraction",
        "fields": "schema_normalization",
        "source_of_truth": "generated_capability_registry"
      }
    },
    {
      "id": "req-002",
      "goal": "Report job status",
      "requirement_type": "single_entity_status",
      "entity": "job",
      "intent_operation": "report_status",
      "source_of_truth": "operational_state",
      "constraints": {"job_id": "JOB-SEED-001"},
      "requested_fields": ["status"],
      "locked_constraints": ["job_id", "requested_fields"],
      "status": "open",
      "evidence_refs": [],
      "origin": {
        "goal": "llm_requirement_sketch",
        "constraints": "deterministic_extraction",
        "fields": "schema_normalization",
        "source_of_truth": "generated_capability_registry"
      }
    },
    {
      "id": "req-003",
      "goal": "List low-priority jobs sorted by deadline",
      "requirement_type": "filtered_collection",
      "entity": "job",
      "intent_operation": "report_filtered_collection",
      "source_of_truth": "operational_state",
      "constraints": {
        "priority": "low",
        "sort_by": "deadline",
        "sort_dir": "asc",
        "limit": 3
      },
      "requested_fields": ["id", "status", "priority", "deadline"],
      "locked_constraints": ["priority", "sort_by", "sort_dir", "limit", "requested_fields"],
      "status": "open",
      "evidence_refs": [],
      "origin": {
        "goal": "llm_requirement_sketch",
        "constraints": "deterministic_extraction",
        "fields": "schema_normalization",
        "source_of_truth": "generated_capability_registry"
      }
    }
  ],
  "revision": 1,
  "revision_history": []
}
```

The planner does not need to output the full plan on every turn. It should usually choose one current need:

```json
{
  "kind": "retrieve_tools",
  "requirement_id": "req-001",
  "reason": "Need a current operational read for the requested machine status.",
  "capability_need": {
    "source_of_truth": "operational_state",
    "entity": "machine",
    "action": "read_one",
    "known_args": {"machine_id": "M-CNC-01"},
    "requested_fields": ["status"]
  }
}
```

Requirement ledger rules:

- The planner may add, split, merge, reorder, or mark requirements blocked when evidence justifies it.
- The planner may not remove or weaken a locked constraint without a user correction or a recorded guard-approved reason.
- The final validator must fail if any required ledger item is still open, ambiguous, uncited, unapproved, or missing evidence.
- User interruptions create a new revision, supersede stale requirements when appropriate, and preserve the old revision in history.

## Evidence Ledger Shape

Define evidence before implementing deterministic satisfaction. Minimal shape:

```json
{
  "id": "ev-001",
  "requirement_id": "req-001",
  "source_type": "api_tool",
  "tool_name": "get__machines_{id}",
  "source_of_truth": "operational_state",
  "args": {
    "id": "M-CNC-01",
    "fields": "status"
  },
  "result_ref": "tool_result_001",
  "normalized_result": {
    "entity": "machine",
    "entity_id": "M-CNC-01",
    "fields": {
      "status": "running"
    }
  },
  "satisfies": ["locked_constraints", "requested_fields"],
  "confidence": "deterministic"
}
```

Evidence rules:

- `source_type` should be `api_tool`, `rag_tool`, `approval`, `user_input`, `system_guard`, or `diagnostic`.
- `confidence` should be `deterministic`, `planner_inferred`, or `ambiguous`.
- Deterministic satisfaction can only finalize evidence with `confidence=deterministic`.
- RAG evidence must include typed source/citation locator fields before it can satisfy `document_answer`.
- Response documents must render from `normalized_result` and contract metadata, not from prose summaries.

## Satisfaction Proof Shape

Do not mark a requirement `satisfied` with only a vague flag. The ledger update must include checks that prove how the evidence satisfies the requirement.

Example satisfaction proof:

```json
{
  "requirement_id": "req-003",
  "status": "satisfied",
  "evidence_refs": ["ev-003"],
  "satisfaction_checks": [
    {
      "check": "priority_filter",
      "expected": "low",
      "actual": "low",
      "passed": true
    },
    {
      "check": "sort_by",
      "expected": "deadline",
      "passed": true
    },
    {
      "check": "limit",
      "expected": 3,
      "actual_count": 3,
      "passed": true
    },
    {
      "check": "requested_fields",
      "expected": ["job_id", "status", "priority", "deadline"],
      "actual": ["job_id", "status", "priority", "deadline"],
      "passed": true
    }
  ]
}
```

Required check families:

- `locked_constraint`: every user-locked ID, filter, sort, limit, field, approval, and safety constraint is preserved.
- `entity_match`: returned entity IDs match requested entity IDs.
- `filter_match`: returned collection rows satisfy requested filters.
- `sort_match`: returned collection ordering satisfies requested sort.
- `limit_match`: returned collection count satisfies requested limit.
- `requested_fields`: response contract contains only expected/requested fields unless the contract explicitly allows a supporting field.
- `source_citation`: document answers have typed source/citation evidence.
- `approval_state`: mutation requirements are not applied without approval.
- `failure_state`: impossible/failed/blocked requirements include a typed reason.

## Tool Retrieval Reuse Strategy

V2 should reuse the current retrieval system rather than replacing it.

Current reusable pieces:

- `ToolSelector.select_tools(...)` already returns ranked tool names with retrieval and optional reranking.
- `CapabilitySelectionRequest` already expresses entity, actions, safety, endpoint shape, and fallback names.
- `_capability_candidates(...)`, `_top_candidates(...)`, `score_tool(...)`, `profile_match_score(...)`, and `vocabulary_for_tools(...)` already provide deterministic ranking and vocabulary-aware scoring.
- Settings such as `tool_selector_top_k`, `tool_selector_candidate_pool`, `tool_selector_reranker_enabled`, and reranker timeout already exist.

V2 adapter shape:

```text
planner capability_need
-> V2CapabilityToolRetriever
-> generated retrieval phrase/profile
-> existing ToolSelector.select_tools(...)
-> small candidate_tool_window
-> hydrated_tool_cards for only that window
-> planner execute_tool decision
```

Example adapter request:

```json
{
  "requirement_id": "req-003",
  "entity": "job",
  "actions": ["list", "read"],
  "safety": "read_only",
  "endpoint_shape": "collection",
  "source_of_truth": "operational_state",
  "constraints": {
    "priority": "low",
    "sort_by": "deadline",
    "sort_dir": "asc",
    "limit": 3
  },
  "requested_fields": ["id", "status", "priority", "deadline"]
}
```

The adapter may create a retrieval phrase like:

```text
job list read low priority sorted by deadline limit 3 fields id status priority deadline
```

Rules:

- The adapter may use existing capability tags, generated vocabulary, tool intent profiles, OpenAPI metadata, and RAG registry metadata.
- The adapter must not contain exact prompt, seeded ID, entity fixture, or source fixture branches.
- Candidate caps are per current capability need, not a one-time global cap for the full user request.
- V2 returns and hydrates at most 5 candidate tools per capability need.
- Phase 4 must not add a planner-controlled "show me more tool cards" upgrade path; missing coverage is handled as a typed retrieval failure or revised capability need.
- Long workflows can request new candidate windows as the planner chooses later capability needs.
- Hydration must preserve full schema details for the selected window: required args, enums, filters, sort, limit, fields, output contracts, read/write/approval metadata, and RAG source contract metadata.
- Trace must record adapter input, selected candidate names, backend used, LLM reranker call count, and whether any compatibility fallback was used.

## Planner Actions

V2 planner decisions should be explicit and auditable:

```text
execute_tool
execute_parallel_read_batch
retrieve_tools
request_clarification
request_approval
revise_requirements
finalize
fail
```

The planner may propose requirement changes, but deterministic guards must reject changes that drop hard user constraints or bypass safety/approval policy.

The planner should usually emit `retrieve_tools` before `execute_tool` unless a valid hydrated tool card for the current capability need is already present.

Example capability need:

```json
{
  "kind": "retrieve_tools",
  "capability_need": {
    "source_of_truth": "operational_state",
    "entity": "machine",
    "action": "read",
    "fields": ["status"],
    "constraints": {"machine_id": "M-CNC-01"}
  }
}
```

Example exact execution after retrieval:

```json
{
  "kind": "execute_tool",
  "tool_name": "get__machines_{id}",
  "args": {
    "id": "M-CNC-01",
    "fields": "status"
  }
}
```

## RAG As Tool Policy

RAG tools should advertise metadata like:

```text
source_of_truth=document_knowledge
side_effect=read
output_contract=knowledge_answer_v1
```

Operational API tools should advertise metadata like:

```text
source_of_truth=operational_state
side_effect=read | write | approval_required
output_contract=entity_status_v1 | business_change_v1 | result_collection_v1
```

Routing rule:

```text
Live/current operational facts -> planner should request operational API capability.
Document/policy/manual/procedure facts -> planner should request RAG/document capability.
Mixed requests -> planner should create separate capability needs and may use both.
Unknown source of truth -> planner asks clarification or requests a cautious retrieval window.
```

The planner must receive prompt/tool guidance that explains source-of-truth policy:

```text
Use operational API tools for live/current database state, counts, lists, updates, approvals, schedules, inventory, and machine/job status.
Use RAG tools for document, SOP, policy, manual, OSHA, procedure, definition, and cited knowledge.
Use both when the user asks for live state plus document guidance.
```

V2 must still preserve rich tool schemas. The retriever narrows breadth, but hydrated candidate tool cards must include required args, path params, query params, enum values, filter/sort/limit/fields support, output contracts, and approval/read-write metadata.

## Cleanup Discipline

This migration uses a shadow-v2 path first, but each phase must say which legacy paths are still allowed and which are retired.

Never allow vague shared names like `newPlanner` or `enhancedMode`. Use explicit names:

```text
legacy_graph_loop
v2_planner_loop
legacy_rag_route
v2_rag_tool
legacy_working_intents
v2_requirements
legacy_tool_selector_route
v2_capability_retrieval
```

Anti-pretend guardrails must fail if:

- `engine_version=v2` still uses the legacy RAG answer shortcut.
- `engine_version=v2` still advances by planner `intent_completed` calls only to walk splitter slices.
- V2 RAG answers do not create a RAG tool/evidence item.
- V2 hard-query tests pass only through `working_intents` as final agenda.
- Read-only three-intent queries make one planner call per completion after all evidence is already available.
- V2 planner receives a broad full OpenAPI catalog instead of a small hydrated candidate window.
- V2 hydrated candidates omit required params, enum values, filter/sort/limit/fields support, output contracts, or approval metadata.
- V2 repeats the same `retrieve_tools` capability need without progress.

## No-Hardcode Maintainability Rules

This migration must fix generic layers, not individual prompts.

Forbidden in production/runtime code:

- exact prompt branches such as matching the full text of one test query;
- seeded ID branches such as `M-CNC-01`, `JOB-SEED-001`, `JOB-SEED-002`, or one specific RAG source id outside fixtures, docs, and tests;
- entity-label branches that special-case one entity when the same behavior belongs in capability metadata, vocabulary, source-of-truth policy, or response-document contracts;
- prose parsing to recover typed facts when tool/RAG contracts already provide structured fields;
- fallback RAG or API answers that invent unsupported facts only to keep a happy path green;
- frontend rendering decisions based only on visible text instead of response-document contract type and typed fields.

Required maintainability pattern:

- New API tool behavior is added through OpenAPI metadata, generated vocabulary, capability-map entries, and hydrated tool cards.
- New entity behavior is added through entity metadata, field aliases, requirement types, and response-document contracts.
- New RAG behavior is added through ingestion/source locator metadata and typed RAG output contracts.
- New display behavior is added through contract type and evidence shape, not entity name or fixture label.
- Any temporary exception needs an explicit allowlist entry with owner, reason, expiry/removal phase, and a regression test that fails when the exception leaks into generic behavior.

Guardrail tests should include:

- static scans blocking seeded IDs, exact prompts, and hardcoded source ids in runtime paths;
- swapped-fixture or non-seed-id tests proving behavior generalizes beyond `M-CNC-01` and `JOB-SEED-*`;
- parameterized requirement tests across at least two entities for status/read flows;
- tests proving requested fields are respected, so a status-only query does not render unrelated machine attributes;
- tests proving multi-ID/multi-step reads do not loop on planner completion after evidence exists;
- tests proving source-of-truth selection uses metadata and ledger state, not prompt text only.

## Critical Review Additions

The plan must explicitly cover these details before implementation can be considered reliable:

- Ownership boundaries: requirement sketcher creates draft ledger state; planner chooses next action; retriever only finds candidates; final validator blocks incomplete work; response-document service only renders accepted evidence.
- Vocabulary boundaries: requirements describe what the user is owed, capability needs describe the next ability, tool calls describe exact executable actions, and evidence describes what has been proven.
- Prompt contracts: planner prompts must describe capability-need output, source-of-truth policy, locked constraints, allowed actions, and when to call `retrieve_tools` versus `execute_tool`.
- Schema hydration: v2 must prove the planner sees enough detail for filters, field selection, sort, limit, enums, approval state, and output contracts after retrieval.
- Field projection: response documents must render requested fields from typed contracts, so status-only requests do not show unrelated attributes from a full object response.
- Failure taxonomy: no tool, many tools, low retrieval confidence, missing args, failed tool, ambiguous evidence, unsupported write, missing approval, RAG insufficient context, and user interruption each need a typed status.
- Observability: every v2 run needs an execution trace with planner-call count, retrieval-call count, selected tools, evidence refs, final validator result, and legacy-path detector flags.
- Performance budget: hard-query tests should assert that read-only multi-step queries do not do one planner call per completed sub-intent after evidence exists.
- Cleanup proof: each cleanup phase must prove the old path is unavailable or test-only before marking it retired.
- Frontend proof: frontend tests should assert response-document contract evidence and layout choice, not just visible strings.
- No-hardcode proof: static guardrails plus swapped-fixture tests must fail if runtime code uses seeded IDs, exact prompts, fixture source ids, or entity-name display branches.

## Testing Migration Impact Map

The existing QA plans remain release requirements. This migration changes what those tests should prove: legacy route, splitter, cursor, and prose assertions must move toward v2 requirement-ledger, capability-need, tool-call, evidence, satisfaction, response-document, and execution-trace assertions.

| Existing test family | Source plan | Required post-migration proof | Migration coverage |
| --- | --- | --- | --- |
| Hard natural-language E2E scenarios | `FACTORY_AGENT_HARD_QUERY_E2E_PLAN.md` | Hard read/write/RAG/approval/interrupt queries run through v2 capability needs, small hydrated candidate windows, typed evidence, and final satisfaction. | Phase 8 switched normal API/RAG defaults to v2 and migrated or marked affected backend legacy tests; Phase 9 still owns the hard-query release proof. |
| Read filter/sort/limit/fields | `FACTORY_AGENT_HARD_QUERY_E2E_PLAN.md`, `HARDCODE_REDUCTION_PLAN.md` | Requested filters, sort, limit, and field projections survive sketching, locking, tool selection, execution, evidence, and response-document rendering. | Phases 2, 3, 4, 6, and 9 cover the contract. Tests should assert locked constraints and evidence fields, not final prose. |
| Multi-step read termination | `FACTORY_AGENT_HARD_QUERY_E2E_PLAN.md`, `STATEFUL_ORACLE_TESTING_PLAN.md` | Obvious read requirements close by deterministic satisfaction instead of planner calls whose only purpose is legacy `intent_completed` advancement. | Phase 6 owns deterministic satisfaction; Phase 8 asserts v2 does not require planner `intent_completed` calls to walk splitter slices; Phase 9 expands this to hard-query release proof. |
| Stateful oracle and operation ledger | `STATEFUL_ORACLE_TESTING_PLAN.md` | Existing state oracles map to v2 requirement revisions, capability retrieval events, evidence ledger entries, satisfaction state, final validator decisions, and response-document revisions. | Phase 8 maps this through `test_event_stream_runtime`, `test_snapshot_timeline_final_response_contract`, `test_approval_atomicity`, `test_phase7_api_ui_alignment`, and `test_approval_bundle_ui`; Phase 9 expands real hard-query coverage. |
| Approval, rejection, stale approval, and read-after-write | `STATEFUL_ORACLE_TESTING_PLAN.md`, `FACTORY_AGENT_HARD_QUERY_E2E_PLAN.md` | Approval payloads bind to newest ledger revisions, locked constraints, staged write evidence, and post-approval read evidence; stale approvals cannot commit. | Phases 6, 7, 8, and 9 cover this. Phase 5 proves shadow mode does not execute or commit write candidates. |
| User interruption and `pending_user_message` | `STATEFUL_ORACLE_TESTING_PLAN.md` | New messages during execution or approval create ledger revisions, supersede stale requirements/evidence, and either consume or retire `pending_user_message`. | Phase 7 implemented the interrupt controller; Phase 8 reverified interrupt, cancel, approval wait/resume, and stale approval rejection suites after defaulting to v2. |
| RAG source and insufficient-context UX | `FACTORY_AGENT_HARD_QUERY_E2E_PLAN.md`, `RESPONSE_DOCUMENT_UX_PLAN.md` | RAG answers use `rag_tool` capability/evidence with source locators, citations, insufficient-context state, and no fake sources. Legacy RAG shortcut traces stay explicit while they exist. | Phase 8 adds the v2 `rag_search_documents` tool/evidence path and verifies backend RAG policy plus source-chip, evidence drawer, PDF locator, mixed API/RAG, and insufficient-context frontend cases. |
| Response-document frontend rendering | `RESPONSE_DOCUMENT_UX_PLAN.md` | The frontend renders typed response-document blocks from accepted evidence and layout contracts, not legacy `presentation`, phrase matching, or entity-specific branches. | Phase 8 verified backend response-document contracts, frontend unit/component tests, and the mocked Playwright response-document lane. Phase 9 expands to hard-query release proof. |
| SSE, timeline, snapshot, and revision ordering | `STATEFUL_ORACLE_TESTING_PLAN.md`, `RESPONSE_DOCUMENT_UX_PLAN.md` | Engine trace, requirement revisions, evidence updates, approval waits/resumes, interrupts, cancel, stale approval rejection, and final response revisions appear in coherent order. | Phase 8 verifies normal completion, approval wait/resume, interrupt, cancel, stale approval rejection, and event-storm convergence through backend SSE/revision suites and Playwright semantic tests. |
| Hardcode guardrails and seeded fixtures | `HARDCODE_REDUCTION_PLAN.md` | V2 code paths are covered by static and swapped-fixture tests that reject exact prompts, seeded IDs, fixture source IDs, and entity-label branches in runtime code. | Phase 8 adds v2 cleanup guard coverage and re-runs `test_hardcode_guardrails.py`; each new v2 module remains in guardrail scope. |
| Seeded adapters and real/direct planner coverage | `STATEFUL_ORACLE_TESTING_PLAN.md`, `FACTORY_AGENT_HARD_QUERY_E2E_PLAN.md` | Seeded tests must not bypass the planner-owned loop in ways that hide regressions; direct v2 and real LangGraph subsets must prove the same contracts. | Phase 8 marks legacy seeded adapter coverage as `legacy_compatibility` with Phase 10 removal where it still exercises the legacy planner; Phase 9 owns real hard-query release proof. |
| CI and release lanes | `STATEFUL_ORACLE_TESTING_PLAN.md`, `FACTORY_AGENT_HARD_QUERY_E2E_PLAN.md` | CI separates fast contract tests, backend oracle tests, shadow/direct v2 tests, frontend semantic tests, hard-query release gates, and real LangGraph smoke coverage. | Phase 8 command anchors are full backend pytest, Phase 1-8 focused pytest, route/splitter/selector, API/response/SSE/RAG focused suites, frontend `npm test`, mocked Playwright response-document lane, and hardcode guardrails. Phase 9 adds release-lane hard queries. |

Before Phase 8 is marked complete, each affected legacy test should be in one of three states: migrated to v2 contract assertions, explicitly marked legacy-only with a removal phase, or replaced by a stronger v2 test. Tests must not pass merely because legacy RAG, legacy whole-query tool scoping, `working_intents`, `intent_cursor`, or seeded adapters produced the answer. Phase 8 migrated the normal API/RAG and no-op assertions to v2 contracts and marked remaining legacy planner-adapter memory/reliability/API tests as Phase 10 legacy compatibility coverage.

## Full Pipeline Verification Gates

Focused phase tests are acceptable for Phases 1-5 because those phases are contract, metadata, retriever, and shadow plumbing. Starting at Phase 6, v2 changes can affect behavioral correctness, so verification must widen at defined gates.

| Gate | Required verification | Notes |
| --- | --- | --- |
| Phase 6 completion | Phase 1-6 focused suite, route/splitter/selector suite, and the full backend pytest suite. | Phase 6 adds deterministic satisfaction and final validation, so run the full backend suite unless an environmental blocker is documented. |
| Phase 7 completion | Phase 1-7 focused suite plus affected interrupt, approval, stateful oracle, SSE/timeline, and response-document contract tests. | Run the full backend suite if Phase 7 touches shared execution/session/approval plumbing beyond the interrupt controller. |
| Phase 8 completion | Full backend suite, frontend unit/component tests, mocked Playwright semantic tests, response-document E2E, seeded oracle E2E, and relevant lint/build checks for touched frontend code. | Phase 8 starts retiring legacy authority, so this is the main pre-release regression gate. |
| Phase 9 completion | Full release pipeline: backend, frontend, hard-query E2E, stateful oracle, response-document UX, RAG/source UX, approval/write, no-hardcode guardrails, seeded oracle, and real LangGraph critical smoke. | Phase 9 is the release proof. Do not mark complete with only focused tests. |
| Phase 10 completion | Full release pipeline again after legacy kill-switch removal. | Proves the product no longer depends on legacy fallback paths. |

Known local command anchors:

```text
Backend full suite from factory-agent:
python -m pytest -q

Backend full suite with project-local temp directory if Windows temp permissions fail:
$env:TMP='.pytest-phase6'; $env:TEMP='.pytest-phase6'; python -m pytest -q

Frontend unit/component tests from eMas Front:
npm test

Frontend Playwright gates from eMas Front:
npm run test:e2e:mocked
npm run test:e2e:response-document
npm run test:e2e:seeded-oracles
npm run test:e2e:real-langgraph
npm run test:e2e:release
```

Each phase handoff must record which gate was run, the exact commands, pass/fail counts, skipped/xfailed counts, and any environmental blocker. If a full gate is deferred, the tracker must say why, what narrower suite was run instead, and which later phase must pick up the deferred verification.

## Phase Readiness Gates

Apply the migration in controlled order:

- Phase 1 is ready to start.
- Phase 2 is ready only after the requirement vocabulary, requirement status enum, origin shape, and evidence ledger shape in this document are treated as the initial contract.
- Phase 3 is mostly ready, but capability-map generation must prove it is generated from metadata and not handwritten runtime vocabulary.
- Phase 4 is ready only after the `V2CapabilityToolRetriever` adapter input/output schema is fixed and tests prove it wraps `ToolSelector` rather than replacing it.
- Phase 5 and later must wait until Phases 1-4 prove there is no legacy bypass, no second retriever, and no hardcoded prompt/entity/source behavior.

Most important design separation:

```text
Requirement = what the user is owed.
Capability need = what ability the planner needs next.
Tool call = exact executable API/RAG invocation.
Evidence = what has been proven.
```

## Phase Sequence And Status Pointer

Use this table for architecture sequence only. Live phase status, commits, verification commands, and handoff notes are tracked in [`PLANNER_OWNED_AGENT_LOOP_MIGRATION_TRACK.md`](PLANNER_OWNED_AGENT_LOOP_MIGRATION_TRACK.md).

| Phase | Name | Notes |
| --- | --- | --- |
| 1 | Boundary and baseline audit | Legacy scaffold, RAG shortcut, whole-query tool scope, interrupt gap, and ToolSelector reuse boundary documented. |
| 2 | Requirement ledger and v2 state contracts only | Add serializable contracts without changing production behavior. |
| 3 | Capability map and source-of-truth hints | Add compact capability map and deterministic source-of-truth hints. |
| 4 | Need-based tool retrieval and hydration | Planner declares capability need; retriever returns a small hydrated tool window. |
| 5 | Planner-owned v2 loop behind flag | Add `v2_shadow`, direct v2 test path, and explicit engine trace. |
| 6 | Evidence satisfaction and replan | Close obvious read evidence deterministically and return uncertain cases to planner. |
| 7 | User interrupt and mid-execution replan | Convert `pending_user_message` into real interrupt/replan handling. |
| 8 | Legacy cleanup switch | Switch default to v2 and retire legacy RAG/scaffold/tool-routing authority. |
| 9 | Hard query release proof | Prove hard API/RAG/read/write/approval/interrupt cases end to end. |
| 10 | Legacy kill-switch removal | Remove legacy option after v2 release proof and cleanup guardrails pass. |

## Phase 1: Boundary And Baseline Audit

Goal: prove the current system behavior and define the v2 migration boundary.

### Phase 1 Evidence (2026-05-20)

Scope note: this phase did not implement the v2 runtime, did not remove legacy behavior, and did not claim `engine_version=v2`. The only code change is a static Phase 1 guard test proving the boundary is named and not confused with v2 execution.

#### Legacy scaffold locations

- `factory-agent/factory_agent/graph/state.py:84` defines the legacy LangGraph state. `working_intents` and `intent_cursor` live at `AgentState` lines 98-100 as mutable execution state, while `intents` remains the append-only trace at lines 126-128.
- `factory-agent/factory_agent/graph/planner_graph.py:127` creates initial state with empty `working_intents` and `intent_cursor=0` at lines 145-148 before invoking the graph at lines 251-258.
- `factory-agent/factory_agent/graph/builder.py:42` wires `input_layer -> intent_splitter -> prepare -> planner` at lines 57-60, then routes planner/tool/relevance back to planner at lines 62-96. This makes the splitter output part of the live control loop.
- `factory-agent/factory_agent/graph/nodes/intent_split.py:18` calls `split_user_intents`, writes `intents`, clones that payload into `working_intents`, sets `intent_cursor=0`, and sets `current_intent` from the first split item at lines 21-31.
- `factory-agent/factory_agent/graph/nodes/planner_loop.py:879` is the main legacy controller. It reads and mutates `working_intents` and `intent_cursor` at lines 885-906 for staged writes, lines 921-983 for normal iteration, lines 1002-1028 for deterministic bulk decisions, lines 1049-1070 for read-not-found completion, and lines 1182-1227 for `intent_completed` / `intent_failed` advancement.
- `factory-agent/factory_agent/graph/nodes/tool_pipeline.py:415` returns read results through `pending_relevance_batch`, appends useful rows to `tool_outputs`, and routes back to planner. `route_after_relevance` sends non-staged read flows to `continue_planner` at lines 592-606.

Boundary decision: in v2, `split_user_intents` may remain an intake hint, but `working_intents` and `intent_cursor` must be legacy-only execution authority. V2 must use a requirement ledger and planner-owned agenda state instead.

#### Legacy RAG shortcut locations

- `factory-agent/factory_agent/planning/intent.py:13` defines semantic routes including `rag.loto_procedure`, `rag.procedure`, and `rag.safety_policy`. The routing branches for document and safety questions are at lines 852-889 and 949-977; `should_route_loto_to_rag` confirms the RAG family at lines 1032-1034.
- `factory-agent/factory_agent/services/plan_creation_service.py:297` implements `_answer_knowledge_question_as_plan`. It calls `RAGPipeline.run(..., route="RAG_ONLY")` at line 315, applies the knowledge policy at lines 327-339, and persists an empty execution plan with sources at lines 344-354.
- `factory-agent/factory_agent/services/plan_creation_service.py:871` routes document answers before normal planner/tool selection. `create_plan` takes the RAG branch for semantic RAG routes at lines 921-936 and the non-operations knowledge branch at lines 938-949, both before the normal `ToolSelector.select_tools` call at lines 967-972.
- `factory-agent/factory_agent/planning/tool_selector.py:993` returns no selected tools for RAG and clarification routes at lines 1000-1009, so RAG answers currently do not pass through normal tool execution.
- Tests preserving this behavior include `factory-agent/tests/test_route_to_execution_contract.py:326` and `factory-agent/tests/test_route_to_execution_contract.py:370`, plus RAG knowledge-policy evidence tests in `factory-agent/tests/test_rag_knowledge_policy.py`.

Boundary decision: v2 must not reuse `_answer_knowledge_question_as_plan` as a hidden answer path. RAG must appear as a first-class tool/capability family with typed evidence. Until legacy cleanup, traces must mark this shortcut explicitly.

#### Legacy whole-query tool-scope locations

- `factory-agent/factory_agent/services/execution_service.py:40` scopes tools once from the full `sess.current_intent` through `ToolSelector.select_tools(intent=intent, ...)` at lines 46-61, then passes the selected catalog to the planner at lines 72-76.
- `factory-agent/factory_agent/services/plan_creation_service.py:811` repeats full-intent scoping when promoting discovery to execution at lines 818-824.
- `factory-agent/factory_agent/services/plan_creation_service.py:871` does the same for normal plan creation at lines 967-972 before `generate_plan` receives `scoped_tools` at lines 991-995.
- `factory-agent/factory_agent/planning/tool_selector.py:728` begins with whole-intent semantic routing and compound semantic route selection at lines 737-747, then contextualizes the whole intent and calls `_top_candidates` at lines 753-760.
- `factory-agent/factory_agent/planning/tool_selector.py:820` can split a compound whole query and union clause-level semantic tool names at lines 829-853, still before the planner has declared a current capability need.
- `factory-agent/factory_agent/planning/tool_selector.py:99` calls `filter_tools_for_intent` and `_retrieve_candidates` from the effective whole intent at lines 108-129 and caps results through `tool_selector_candidate_pool` and `tool_selector_top_k` at lines 151-155.
- `factory-agent/factory_agent/planning/tool_scope.py:129` performs legacy clause-level ranking inside `filter_tools_for_intent`, using `score_tool` at lines 75-126 and `vocabulary_for_tools` at lines 141-164.
- `factory-agent/tests/test_route_to_execution_contract.py:308` proves the hard multi-read query currently gets a unioned candidate set from whole-query scoping.

Boundary decision: v2 must not let whole-query tool scoping be execution authority. It may wrap existing `ToolSelector` pieces only after the planner emits a structured capability need.

#### Read-only completion loop

- `factory-agent/factory_agent/graph/nodes/tool_pipeline.py:415` appends read outputs and routes to `continue_planner` at lines 454-461 and 592-606.
- `factory-agent/factory_agent/graph/nodes/planner_loop.py:678` instructs the planner that when tool results already satisfy the current intent, it should emit `intent_completed` at lines 711-712.
- `factory-agent/factory_agent/graph/nodes/planner_loop.py:1182` handles `intent_completed` by marking the current `working_intent` complete and advancing `intent_cursor` at lines 1182-1191.
- `factory-agent/tests/test_route_to_execution_contract.py:94` proves the route contract by faking a second planner response that only emits `intent_completed` once recent `tool_outputs` exist at lines 110-121.

Boundary decision: v2 should allow deterministic satisfaction to close obvious read requirements without an LLM call whose only job is `intent_completed`. Ambiguous evidence, writes, approvals, failures, and mixed source-of-truth cases still return to the planner.

#### Pending user message boundary

- `factory-agent/factory_agent/persistence/models.py:31`, `factory-agent/factory_agent/schemas.py:236`, and `factory-agent/factory_agent/api/response_mappers.py:41` store and expose `pending_user_message`.
- `factory-agent/factory_agent/api/routers/messages.py:146` handles `WAITING_APPROVAL` as a real replan/invalidation path at lines 146-191.
- `factory-agent/factory_agent/api/routers/messages.py:192` stores `sess.pending_user_message = req.content[:5000]` during `EXECUTING` at lines 192-194.
- `factory-agent/factory_agent/services/plan_creation_service.py:614` clears `pending_user_message` when a plan is persisted. No inspected execution or graph path consumes this value as a controller.

Boundary decision: Phase 7 must either consume `pending_user_message` into an interrupt/replan state transition or retire it. V2 must not leave it as a dead storage field.

#### ToolSelector reuse boundary

V2 must wrap these existing pieces instead of duplicating retrieval/ranking:

- `ToolSelector.select_tools` at `factory-agent/factory_agent/planning/tool_selector.py:728`.
- `CapabilitySelectionRequest` at `factory-agent/factory_agent/planning/tool_selector.py:64`.
- `_top_candidates` at `factory-agent/factory_agent/planning/tool_selector.py:99`.
- `_capability_candidates` at `factory-agent/factory_agent/planning/tool_selector.py:910`.
- `_select_capability_tools` at `factory-agent/factory_agent/planning/tool_selector.py:974`.
- `filter_tools_for_intent` at `factory-agent/factory_agent/planning/tool_scope.py:129`.
- `score_tool` at `factory-agent/factory_agent/planning/tool_scope.py:75`.
- `profile_match_score` at `factory-agent/factory_agent/planning/tool_intent_profile.py:388`.
- `vocabulary_for_tools` at `factory-agent/factory_agent/planning/tool_intent_profile.py:190`.
- Settings in `factory-agent/factory_agent/config.py`: `tool_selector_model` line 61, `tool_selector_top_k` line 68, `tool_selector_candidate_pool` line 69, `tool_selector_max_score_gap` line 70, `tool_selector_path_token_weight` line 78, `tool_selector_reranker_enabled` line 79, `tool_selector_reranker_timeout_s` line 80, `tool_selector_reranker_max_tokens` line 81, `embedding_backend` line 87, `force_llm_trace_all` line 101, and `tool_selector_openai_base_url` line 107.
- Existing tests in `factory-agent/tests/test_tool_selector.py:729` and `factory-agent/tests/test_tool_selector.py:1042` already cover reranker skip/disable behavior and capability metadata selection.

Boundary decision: the v2 adapter should translate a planner-owned capability need into `CapabilitySelectionRequest` plus a retrieval phrase/profile, call `ToolSelector.select_tools` or the capability helpers, and trace the selected candidate window. It must not create a second retriever.

#### Proposed Trace Schema

Initial persisted location: `Session.replan_context.intent_contract`, because legacy graph validation already emits `intent_contract` in `factory-agent/factory_agent/graph/nodes/validate.py:391` and plan creation already copies it into `sess.replan_context` in `factory-agent/factory_agent/services/execution_service.py:105` and `factory-agent/factory_agent/services/plan_creation_service.py:999`. Response documents may mirror the same fields under response metadata later, but the canonical run trace should stay in the intent contract.

- `engine_version`: located at `intent_contract.engine_version`. Allowed values: `legacy`, `v2_shadow`, `v2`. Phase 1 must not emit `v2` or `v2_shadow`.
- `execution_trace.generated_by`: located at `intent_contract.execution_trace.generated_by`. Allowed values: `legacy_graph_loop`, `legacy_rag_route`, `legacy_working_intents`, `v2_shadow_planner_loop`, `v2_planner_loop`.
- `execution_trace.planner.call_count`: integer count of planner model calls for this run. Legacy RAG shortcut should record `0`.
- `execution_trace.tool_retrieval.call_count`: integer count of calls into tool retrieval/selection.
- `execution_trace.tool_retrieval.selected_candidate_tool_names`: ordered list of tool names returned to the planner/retriever boundary.
- `execution_trace.tool_retrieval.reranker.call_count`: integer count of LLM reranker calls from ToolSelector.
- `execution_trace.tool_retrieval.backend_used`: ToolSelector backend value such as `retrieval` or `langchain`.
- `execution_trace.detectors.legacy_rag_shortcut.used`: boolean. Also record `execution_trace.detectors.legacy_rag_shortcut.route`, `source_function`, and `policy_id` when available.
- `execution_trace.detectors.legacy_working_intent_execution.used`: boolean. Also record `working_intents_count`, `intent_cursor_start`, and `intent_cursor_final`.
- `execution_trace.detectors.legacy_whole_query_tool_scope.used`: boolean. Also record `source_function`, `selector_intent_scope` with value `whole_user_query`, and `selected_candidate_tool_names`.
- `execution_trace.detectors.legacy_intent_completion_loop.used`: boolean. Also record `intent_completed_count` and `planner_completion_only_call_count`.

Guard added: `factory-agent/tests/test_planner_owned_loop_phase1_boundary.py` checks that this schema is documented, that legacy boundary sources remain explicit, and that runtime code does not claim `engine_version=v2` or `execution_trace.generated_by=v2_planner_loop` before the v2 loop exists.

Read/check:

- `factory-agent/factory_agent/services/execution_service.py`
- `factory-agent/factory_agent/graph/builder.py`
- `factory-agent/factory_agent/graph/nodes/intent_split.py`
- `factory-agent/factory_agent/planning/intent.py`
- `factory-agent/factory_agent/planning/tool_selector.py`
- `factory-agent/factory_agent/graph/nodes/planner_loop.py`
- `factory-agent/factory_agent/graph/nodes/tool_pipeline.py`
- `factory-agent/factory_agent/services/plan_creation_service.py`
- current route/planner/tool/RAG tests

Acceptance criteria:

- Document where current code uses `working_intents` as execution scaffold.
- Document where RAG is routed before normal planner/tool execution.
- Document where read-only results return to planner for `intent_completed`.
- Decide the exact names and locations for `engine_version` trace fields.
- Add at least one test or static guard proving v2 paths cannot be confused with legacy paths once implemented.
- Record the reusable `ToolSelector` methods, capability helpers, and settings that v2 must wrap rather than duplicate.

Verification:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_route_to_execution_contract.py tests/test_intent_splitter.py tests/test_tool_selector.py -q

Set-Location ".."
git diff --check
git status --short --branch
```

## Phase 2: Requirement Ledger And V2 State Contracts Only

Goal: add v2 state contracts without changing runtime behavior.

Add contracts for:

- `tool_retrieval_slices`
- `capability_map`
- `capability_need`
- `candidate_tool_window`
- `hydrated_tool_cards`
- `tool_selector_adapter_request`
- `source_of_truth`
- `requirement_sketch`
- `requirement_ledger`
- `requirement_type`
- `intent_operation`
- `locked_constraints`
- `field_aliases`
- fixed requirement `status` enum
- `revision_history`
- `evidence_ledger`
- `satisfaction_state`
- `engine_version`

Acceptance criteria:

- Contracts serialize and validate.
- Legacy execution still passes unchanged.
- No production path claims v2 execution yet.
- Tests prove hard constraints can be represented without loss.
- Tests prove the requirement vocabulary is separate from capability/tool action vocabulary.
- Tests prove only the fixed `requirement_type` and requirement `status` enums are accepted.
- Tests prove planner agenda patches cannot drop `locked_constraints`.
- Tests prove status-only/read-field requirements can be represented without carrying unrelated output fields into the response contract.
- Tests prove adapter traces can be represented without executing the v2 runtime.
- Tests prove minimal evidence records can represent API, RAG, approval, diagnostic, and user-input evidence without relying on prose summaries.

## Phase 3: Capability Map And Source-Of-Truth Hints

Goal: expose a compact high-level capability map, field aliases, and deterministic source-of-truth hints without sending full tool schemas to the first planner step.

Capability map examples:

```json
{
  "capability_id": "machine.read.status",
  "source_of_truth": "operational_state",
  "entity": "machine",
  "actions": ["read"],
  "supports": ["fields"]
}
```

```json
{
  "capability_id": "knowledge.rag.procedure",
  "source_of_truth": "document_knowledge",
  "entity": "procedure",
  "actions": ["read"],
  "output_contract": "knowledge_answer_v1"
}
```

RAG/procedure/policy answerers are represented as capability families and later as retrievable tools.

Acceptance criteria:

- LOTO/procedure query receives a document-knowledge capability hint.
- Machine status query receives an operational-state capability hint.
- Mixed API/RAG query receives separate capability hints.
- Requirement sketcher locks explicit IDs, fields, filters, sorts, limits, approvals, and safety constraints before planner execution.
- Field aliases are metadata-driven, so `status`, `deadline`, `due date`, `priority`, and `quantity` do not require prompt-specific branches.
- Planner prompt guidance explains when to request API capability, RAG capability, or both.
- Legacy RAG route remains temporarily available and clearly named.
- RAG output contract remains typed as knowledge/source evidence, not markdown-only text.

## Phase 4: Need-Based Tool Retrieval And Hydration

Goal: retrieve tools only after the planner declares a current capability need, while reusing the existing `ToolSelector`.

Rules:

- Planner first sees the original request, open requirements, evidence, and compact capability map.
- Planner emits `retrieve_tools` with a structured `capability_need`.
- `V2CapabilityToolRetriever` converts the current capability need into a `ToolSelector` intent/profile.
- `V2CapabilityToolRetriever` reuses existing `ToolSelector.select_tools(...)`, capability scoring, vocabulary scoring, and optional reranking.
- Retriever returns a small `candidate_tool_window`, max 5 per capability need.
- Adapter input/output schema must be fixed before coding: input is `capability_need` plus ledger requirement refs; output is candidate names, scores/ranks when available, backend used, hydration refs, reranker calls, and fallback flags.
- Hydrated tool cards include full selected schemas: required args, path/query params, enum values, filter/sort/limit/fields support, output contracts, read/write/approval metadata.
- All returned v2 candidates are hydrated, with an absolute max of 5 hydrated tool cards.
- Do not send the full OpenAPI catalog to the planner.
- If no tool matches, planner must clarify, revise requirements, or fail gracefully.
- If the same capability need is requested repeatedly with no state change, guard blocks the loop.
- Compatibility fallback names are allowed only through existing `ToolSelector` metadata-compatible fallback behavior and must be traced.
- Do not implement a "top 3 then ask planner whether to hydrate more" flow in Phase 4.

Acceptance criteria:

- Machine status capability need retrieves machine status API candidates.
- OSHA/procedure capability need retrieves RAG candidates.
- Low-priority job list capability need retrieves list job candidates with filter/sort/limit/fields schema.
- Adapter tests prove `ToolSelector` is called with the capability-derived retrieval profile rather than the whole user query.
- Candidate windows are per capability need and do not starve workflows with more than five steps.
- Candidate-window tests prove v2 hydrates no more than 5 tools for one capability need.
- Retrieval-failure tests prove no-match, low-confidence, and missing-required-schema cases return typed failure state instead of expanding indefinitely.
- Hydrated cards preserve enum/filter/sort/limit/fields information.
- Multi-step workflows can retrieve new tool windows on later planner turns, so long workflows are not killed by a one-time global cap.
- Tests fail if v2 sends a broad full catalog or omits schema details needed for correct args.

## Phase 5: Planner-Owned V2 Loop Behind Flag

Goal: add the v2 loop behind an explicit flag.

Modes:

```text
FACTORY_AGENT_ENGINE=legacy
FACTORY_AGENT_ENGINE=v2_shadow
FACTORY_AGENT_ENGINE=v2
```

Locked first behavior:

```text
v2_shadow = trace-only shadow
legacy returns user-visible answer
v2 records capability map, capability needs, tool retrieval windows, planner actions, evidence plan, and expected response contract
v2 never commits writes in shadow mode
```

Separate execution paths:

```text
v2_shadow = production-safe trace-only path; no visible v2 answer, no state mutation, no committed writes.
v2_direct_test = test-only execution path; may run the v2 loop and execute read tools; writes must be staged/dry-run only unless an explicit test approval harness is used.
v2 = eventual production path after release proof.
```

Direct v2 tests may run the v2 loop with read tools, but production `v2_shadow` remains trace-only and never mutates state.

Acceptance criteria:

- Direct v2 tests call v2 without legacy wrappers.
- Shadow traces prove whether v2 used RAG tool/evidence or legacy RAG route.
- Planner sees original request, high-level capability map, requirements, and evidence before requesting tools.
- Trace records planner-call count, tool-retrieval count, repeated-retrieval guard status, legacy intent-completion-loop detection, and legacy RAG-shortcut detection.
- Shadow trace records whether v2 used `V2CapabilityToolRetriever` and existing `ToolSelector`, including selected candidate names and reranker call count.
- `execution_trace.generated_by` is `v2_planner_loop` for v2 direct tests and never reports `legacy_graph_loop`, `legacy_rag_route`, or `legacy_working_intents` as execution authority.

## Phase 6: Evidence Satisfaction And Replan

Goal: avoid planner calls that only confirm already-clear read evidence while keeping the planner responsible for uncertain or changing goals.

Rule-based satisfaction can close:

- requested entity id matches returned entity id;
- requested field exists;
- list filter/sort/limit/fields are respected;
- RAG answer has cited source evidence;
- no-match result is explicit and typed.

Fallback to planner when:

- evidence is missing;
- evidence is ambiguous;
- a tool failed;
- request involves write/approval;
- source of truth is mixed or unclear;
- guardrails reject the satisfaction result.

Acceptance criteria:

- Three-read query avoids extra planner completion calls after successful evidence.
- Missing/ambiguous evidence returns to planner.
- Writes and approvals never fast-path to final answer.
- Repeated retrieval for the same capability need is blocked unless new evidence or requirement changes justify it.
- Requirement ledger status changes are auditable and include evidence refs.
- Final validator blocks final response if a required ledger item is still open, a locked constraint was dropped, or typed evidence is missing.
- Evidence satisfaction must not infer business facts from prose summaries when typed fields exist.
- Every `satisfied`, `skipped`, `impossible`, `blocked`, or `failed` ledger update includes a satisfaction proof or typed failure proof with check names, expected values, actual values where applicable, and pass/fail state.

## Phase 7: User Interrupt And Mid-Execution Replan

Goal: make user changes during active execution a real control path.

Interruption types:

```text
cancel_current_run
replace_goal
append_requirement
modify_requirement
answer_clarification
reject_approval
approve_approval
```

Examples:

```text
Original: Show M-CNC-01 status.
Interrupt: Actually also include maintenance date.
Expected: create a new ledger revision and append/modify requirements; do not blindly cancel.
```

```text
Original: Change high-priority jobs to medium and ask approval.
Interrupt: Do not include blocked jobs.
Expected: modify the mutation requirement and invalidate stale approval payloads.
```

Acceptance criteria:

- Cancel during execution stops safely.
- New user message during `WAITING_APPROVAL` continues to supersede stale approvals.
- New user message during `EXECUTING` can interrupt or create a replan checkpoint.
- Append/modify/replace interrupts create a new requirement-ledger revision with superseded requirements preserved in `revision_history`.
- Approval interrupts invalidate stale staged writes unless the approval payload still matches the newest ledger revision.
- `pending_user_message` is consumed or retired; it must not be a dead field.

## Phase 8: Legacy Cleanup Switch

Goal: switch default to v2 and begin retiring legacy authority.

Cleanup items:

- Retire legacy RAG short-circuit once `v2_rag_tool` is proven.
- Retire `working_intents` as execution agenda once `v2_requirements` is proven.
- Retire `intent_cursor` completion loop as the main controller.
- Retire semantic-route-as-tool-selection authority; keep semantic frame as hints.
- Retire whole-query full-catalog tool scoping as the v2 planner's primary context; keep it only for legacy mode or compact capability map generation.
- Mark legacy-only tests explicitly or migrate them.

Acceptance criteria:

- Normal API path records `engine_version=v2`.
- V2 response documents are not built from legacy RAG route.
- V2 does not require planner `intent_completed` calls to walk splitter slices.
- V2 planner does not receive the broad full catalog before declaring a capability need.
- Runtime code contains no second parallel retriever that duplicates `ToolSelector` ranking.
- Response-document contract tests pass for API, RAG, mixed API/RAG, mutation, approval, no-op, insufficient-context, and failure states.
- SSE/revision ordering tests pass for normal completion, approval wait/resume, interrupt, cancel, and stale approval rejection.
- Approval UI tests pass with staged/dry-run payloads and newest ledger revision checks.
- RAG citation rendering tests pass with source chips, evidence drawer/PDF locator behavior, and insufficient-context display.

### Phase 8 Evidence (2026-05-20)

- Normal default engine resolution is `v2`; before Phase 10, `FACTORY_AGENT_ENGINE=legacy` remained as the kill switch.
- Direct v2 RAG answers use `rag_search_documents` evidence with `source_type=rag_tool`; response documents are not generated from `legacy_rag_route`.
- V2 cleanup tests assert no planner `intent_completed` loop is needed, no whole-query full-catalog selection is used as v2 authority, and runtime retrieval continues to wrap `ToolSelector` instead of duplicating it.
- Affected API/no-op/RAG tests were migrated to v2 response-document and execution-trace assertions; remaining legacy planner adapter tests are marked `legacy_compatibility` with Phase 10 removal.
- Verification for Phase 8 is recorded in the progress tracker.

## Phase 9: Hard Query Release Proof

Goal: prove the v2 loop with hard realistic cases.

Required scenarios:

- multi-step read;
- multi-ID read;
- sort + limit + fields;
- mixed API + RAG;
- conditional branch;
- approval branch;
- user interruption;
- RAG insufficient context;
- tool failure fallback;
- no exact prompt/id/source/entity hardcode.

Example hard query:

```text
Show M-CNC-01 status, show JOB-SEED-001 and JOB-SEED-002 status, then list the next 3 low-priority jobs sorted by deadline with only job id, status, priority, and deadline. If any listed job is blocked, explain why before suggesting any update.
```

Write/approval hard query:

```text
Change all high-priority jobs due this week to medium, but do not update blocked jobs. Show what would change and ask approval before applying.
```

Expected proof:

- planner declares capability needs for machine lookup, job lookup/list, and any needed RAG only when source of truth requires it;
- retriever returns small hydrated tool windows for each capability need;
- planner owns the conditional branch;
- read satisfaction closes obvious read evidence;
- blocked-job explanation triggers a planner continuation only if evidence requires it;
- final response renders from typed response-document contracts.
- requested fields are honored, so status-only queries do not expose unrelated attributes;
- multi-ID reads terminate without planner-completion loops;
- UI layout selection follows response-document contract shape and result cardinality, not entity-specific hardcoding.
- evidence traces prove v2 used `V2CapabilityToolRetriever` and did not use whole-query global tool scoping as the execution authority.
- write/approval proof stages the mutation, excludes blocked jobs, preserves due-this-week and high-priority locked constraints, asks approval, and does not commit before approval.

## Phase 10: Legacy Kill-Switch Removal

Goal: remove legacy option only after v2 release proof is strong.

Rollback policy:

```text
Legacy runtime is removed from normal product paths.
If an emergency fallback remains, it must be isolated, disabled by default, monitored, and scheduled for deletion.
Emergency fallback must not be represented as normal legacy mode.
```

Acceptance criteria:

- `FACTORY_AGENT_ENGINE=legacy` is removed or test-only.
- Legacy RAG route code is gone or impossible in production.
- Legacy intent-completion loop is gone or test-only.
- Docs and generated tool vocabulary describe v2 architecture.
- All hard-query release tests pass in v2-only mode.
- Any emergency fallback is disabled by default, emits telemetry when touched, and has a dated removal issue/phase.

### Phase 10 Evidence (2026-05-20)

- Normal `FACTORY_AGENT_ENGINE=legacy` values now normalize to `v2`. Legacy planner/scaffold behavior requires the non-environment `test_only_legacy_engine_enabled` setting and is limited to marked compatibility tests.
- Non-seeded, non-client-draft plan creation runs the direct planner-owned v2 path; direct RAG answers use `rag_search_documents` evidence and do not route through `legacy_rag_route`.
- The old 21 legacy xfails were removed from the normal backend suite and converted to explicit test-only legacy compatibility skips with deletion rationale where they only documented retired relational PlanStep behavior.
- `v2_shadow` remains only as an explicit emergency shadow fallback, disabled by default, with warning telemetry and a next-cleanup-milestone removal target. It is not represented as normal `legacy` mode.
- Generated `tool_intent_vocabulary.json` now carries `architecture=planner_owned_v2` and the capability-need-to-ToolSelector retrieval contract.
- Phase 10 verification is recorded in the progress tracker, including full backend and the frontend release pipeline.

## Stop Conditions

Stop and fix before phase completion if:

- V2 claims to run but legacy path produces the result.
- `engine_version=v2` response lacks `execution_trace.generated_by=v2_planner_loop`.
- `engine_version=v2` response includes `legacy_graph_loop`, `legacy_rag_route`, or `legacy_working_intents` as execution authority.
- A hard user ID, filter, sort, limit, field list, approval requirement, or safety constraint is dropped.
- A status-only/read-field query renders unrelated fields because a tool returned a full object.
- RAG answers appear without typed source evidence or insufficient-context state.
- API/RAG source-of-truth classification relies only on exact prompt text.
- Product/runtime code contains seeded IDs, exact prompt strings, fixture-only source ids, or entity-label branches outside approved fixtures/tests/docs.
- A new entity/tool/source requires product-code branches instead of metadata, vocabulary, capability-map, or contract updates.
- Planner is removed from complex/conditional decisions.
- Planner receives broad full schemas before declaring a capability need.
- V2 implements a second independent tool ranking stack instead of wrapping the existing `ToolSelector`.
- Tool retriever starves a long workflow because candidates were capped only once at request start.
- A selected hydrated tool card lacks enum, required arg, filter, sort, limit, fields, output contract, read/write, or approval metadata.
- V2 repeats `retrieve_tools` for the same capability need without new evidence, revised requirements, or a recorded fallback reason.
- Deterministic satisfaction finalizes ambiguous evidence.
- A user message during execution is stored but never acted on.
- Frontend tests pass only by checking visible text and not response-document contract evidence.

## Resolved Grill-Me Decisions

- Use trace-only `v2_shadow` first.
- Use a generated capability registry as the only long-term sketcher vocabulary source.
- Use a two-pass deterministic guard around the LLM requirement sketcher.
- Reuse the current `ToolSelector` through `V2CapabilityToolRetriever`.
- Keep the real planner as the execution/replanning brain; requirement sketcher and tool retriever only prepare state and candidates.
