# Factory Agent Hard Query E2E Plan

> Goal: prove the Factory Agent can handle realistic hard natural-language queries across reads, sort/filter/limit/field projection, 3+ step workflows, approvals, rejection, no-op/partial mutation, RAG, and cross-entity cases without relying on prompt-specific or entity-specific hardcoded fixes.

This plan starts after Response Document Phase 37. It is intentionally separate from `RESPONSE_DOCUMENT_UX_PLAN.md` because the focus is broader than response rendering: planner routing, execution ordering, approval safety, DB truth, response-document contracts, and browser semantic proof must all agree.

## Principles

- Use natural hard queries, not only `Run Phase ...` fixture prompts.
- Every scenario must define an explicit oracle before implementation.
- Every scenario must prove backend state and browser semantic rendering.
- Bugs must be fixed in durable layers: semantic frame extraction, splitter, tool selection, planner state basis, approval bundle contract, response-document contract, or typed frontend renderer.
- Do not add runtime branches for exact prompts, `JOB-SEED-*`, `M-CNC-01`, or one entity label.
- Avoid text-only E2E assertions. Use typed attributes and backend snapshot evidence.
- Keep deterministic seeded tests safe: approvals must gate writes, rejected approvals must not mutate, and no unsupported destructive action should execute.

## Common Oracle Requirements

Each hard-query scenario should assert:

- The session reaches the expected terminal state or expected waiting-approval state.
- No planner/guard/tool loop, recursion-limit error, hidden continuation, or stale completion occurs.
- Backend step order matches the natural-language order.
- Tool arguments preserve filters, sort fields, sort direction, limits, and requested fields.
- Approval-required steps expose exactly the intended rows and fields.
- No mutation happens before approval.
- Rejected approvals do not mutate.
- Final DB state matches final answer.
- Response documents use typed contracts, not prose parsing.
- Browser semantic evidence matches backend snapshot evidence.
- Field projection is honored: status-only means identity plus status only.
- Large result sets are capped/collapsed by typed policy.
- No hardcoded product branches are introduced.

## Semantic Evidence To Check In Playwright

Use Playwright semantic assertions against DOM attributes and rendered blocks:

- `data-response-contract`
- `data-response-block-type`
- `data-requested-fields`
- `data-read-scope`
- `data-display-mode`
- `data-entity-count`
- `data-preview-limit`
- `data-details-collapsed`
- `data-field-change-count`
- `data-approval-id`
- row counts and visible table/card structure
- forbidden text checks for stale approval, fake success, unsupported field fallback, and extra projected fields

## Phase 1: Hard Query Oracle Harness

Goal: create the reusable hard-query test harness so later scenarios are data-driven and durable.

Must add:

- A scenario catalog, for example `eMas Front/e2e/support/hardQueryScenarios.js`.
- A generic Playwright runner, for example `eMas Front/e2e/specs/full-stack-hard-query.spec.js`.
- A scenario schema with:
  - `id`
  - `prompt`
  - expected terminal state
  - expected step sequence
  - expected tool names
  - expected tool args including filters, sort, limit, fields
  - expected response-document contracts
  - expected approval count
  - expected DB mutation or no-mutation proof
  - expected visible semantic blocks
  - forbidden visible/backend text
- Shared helpers to compare backend snapshot evidence with visible semantic evidence.
- At least three canary scenarios:
  - HQ-01 status-only machine projection
  - HQ-05 filtered/sorted/limited field projection
  - HQ-3S-01 three ordered read steps
- Guardrails that fail if product/runtime code branches on exact hard-query prompts or fixture IDs outside tests/fixtures.

Done when:

- The harness can run scenarios from data.
- The three canaries pass or reveal real bugs.
- Any revealed bug is fixed generically, not by exact prompt branching.

## Phase 2: Read Scope, Sort, Filter, Limit, And Fields

Goal: prove read-only requests preserve user-specified scope and result-shaping requirements.

Scenarios:

| ID | Query | Must Prove |
|---|---|---|
| HQ-01 | `Show status for machine M-CNC-01 only. Do not show other machine details.` | status-only fields, no extra machine attributes |
| HQ-02 | `Show full details for machine M-CNC-01, but put status first.` | details allowed, secondary fields collapsed |
| HQ-03 | `Find status for job JOB-SEED-001 and JOB-SEED-002.` | multi-status, no loop |
| HQ-04 | `Show status for JOB-SEED-001 and M-CNC-01 in one answer.` | mixed entity sections do not leak fields |
| HQ-05 | `List low priority jobs, only job id and deadline, sorted by deadline ascending, limit 3.` | filter + fields + sort + limit |
| HQ-06 | `List planned low priority jobs due soon, show job id, status, priority, deadline only, limit 5.` | multi-filter + projection |
| HQ-07 | `Show the 5 newest jobs, only job id and created date.` | descending sort + limit + fields |
| HQ-08 | `Show jobs sorted by banana field.` | typed unsupported sort, no loop |
| HQ-09 | `List all jobs with every field and no limit.` | enforced cap/preview, no huge UI |

Done when:

- Backend and Playwright semantic evidence agree for every scenario.
- Unsupported sort and unbounded list requests produce typed diagnostics or capped display, not random fallback behavior.

## Phase 3: Three-Plus-Step Read And Mixed Operation Workflows

Goal: prove the planner preserves order and context across 3+ read-only or mixed read/RAG workflows.

Scenarios:

| ID | Query | Must Prove |
|---|---|---|
| HQ-3S-01 | `Show M-CNC-01 status, then show JOB-SEED-001 status, then list the next 3 low priority jobs sorted by deadline.` | 3 ordered reads |
| HQ-5S-02 | `Find JOB-SEED-001 status, then tell me if OSHA has evidence for reenergizing notification, then list low priority jobs limit 2.` | read + RAG + filtered list, separate sections |
| HQ-RAG-03 | `Show M-CNC-01 status and OSHA lockout/tagout reenergizing notification guidance as separate sections.` | mixed operation + RAG, no source/entity leakage |

Done when:

- Step order is proven in backend timeline and visible blocks.
- RAG and operation sections stay separate.
- No old response body, source chip, or field projection leaks into later steps.

## Phase 4: Multi-Step Approval And Read-After-Write

Goal: prove approval-gated writes compose safely with read steps and final verification.

Scenarios:

| ID | Query | Must Prove |
|---|---|---|
| HQ-3S-02 | `List low priority jobs limited to 3 sorted by deadline, then change only those listed jobs to medium after approval, then show their new priorities.` | read -> approval/write -> verification read |
| HQ-3S-03 | `Show JOB-SEED-001 status, change its priority to high after approval, then show status and priority for JOB-SEED-001 only.` | read/write/read with field projection |
| HQ-4S-01 | `Show M-CNC-01 status, list planned low priority jobs due soon limit 5, change only those planned jobs to medium after approval, then summarize changed job ids.` | read machine -> filtered read -> approval/write -> summary |
| HQ-4S-02 | `List high priority jobs, change them to low after approval, then list remaining high priority jobs, then show a count summary.` | read -> write -> read-after-write -> count |
| HQ-4S-03 | `Find status for JOB-SEED-001 and JOB-SEED-002, then change JOB-SEED-002 to high after approval, then show both job statuses again.` | multi-read -> single write -> multi-read |

Done when:

- Every write is preceded by a matching approval.
- Read-after-write reflects DB state, not stale planner memory.
- Final response groups are typed and do not infer business facts from summary prose.

## Phase 5: Multi-Approval, State Basis, Rejection, And Partial Results

Goal: prove complex approval chains and partial outcomes are safe and truthful.

Scenarios:

| ID | Query | Must Prove |
|---|---|---|
| HQ-MA-01 | `Change all medium priority jobs to high, then change original high priority jobs to low.` | two approvals, original-state basis |
| HQ-MA-02 | `Change all medium priority jobs to high, then change high priority jobs to low.` | explicit current/original state rule, no ambiguous cascade |
| HQ-MA-03 | `List medium priority jobs limit 3, approve changing them to high, list high priority jobs limit 5, approve changing original high jobs to low, then show final grouped changes.` | 5-step, two approvals, grouped final |
| HQ-MA-04 | `Approve changing JOB-SEED-001 to high, then reject changing JOB-SEED-002 to high, then show both priorities.` | approved mutation only, rejected mutation not applied |
| HQ-NO-01 | `Change JOB-SEED-001 and JOB-SEED-002 to high priority, but skip any job already high.` | changed group + no-op group |
| HQ-NO-02 | `Change low priority planned jobs to medium, but only if status is planned.` | filter preserved through approval/mutation |
| HQ-NO-03 | `List low priority jobs, then use those jobs to update priority to medium.` | bounded selection or clarification, never hidden all-record update |
| HQ-FAIL-01 | `List low priority jobs limit 3, change those jobs to medium after approval, then sort by an invalid field banana.` | valid mutation, then typed unsupported diagnostic |
| HQ-REJECT-01 | `List low priority jobs limit 2, approve changing the first to medium, reject changing the second to high, then show both priorities.` | mixed approval outcome, correct DB state |

Done when:

- Approval IDs, row sets, and DB effects match exactly.
- Rejected and unsupported portions remain visible as typed outcomes.
- State basis is explicit for cascades.

## Phase 6: RAG Truth And Source Evidence

Goal: prove source-backed and insufficient-context RAG behavior still works inside the harder suite.

Scenarios:

| ID | Query | Must Prove |
|---|---|---|
| HQ-RAG-01 | `According to OSHA, what notification is required before reenergizing after removing LOTO devices?` | source-backed answer + PDF locator |
| HQ-RAG-02 | `According to OSHA, what notification is required before starting lockout?` | insufficient context, no fake policy source |
| HQ-5S-01 | `Show machine M-CNC-01 status, show OSHA reenergizing notification evidence, list low priority jobs limit 2, change those jobs to medium after approval, then show changed rows only.` | operation + RAG + read + approval/write + typed result |

Done when:

- Source chips, source drawer, and backend source locator agree.
- No synthetic policy-only source is invented for unsupported OSHA questions.
- Mixed operation/RAG/write flow stays ordered and safe.

## Phase 7: Cross-Entity Generic Coverage

Goal: prove the design is not job/machine-only.

Scenarios:

| ID | Query | Must Prove |
|---|---|---|
| HQ-GEN-01 | `Show product P-001 status and material MAT-002 inventory status.` | generic entity status beyond job/machine |
| HQ-GEN-02 | `Show work order JOB-SEED-001 status and product P-001 status in one response.` | mixed generic entity status |
| HQ-GEN-03 | `List materials below reorder level, only material id and quantity, limit 5.` | non-job list projection |
| HQ-NO-04 | `Put material MAT-002 on hold if inventory is below threshold, otherwise explain no change.` | non-job conditional/no-op |

Done when:

- Generic entity-status and collection contracts render beyond job/machine.
- Non-job no-op/conditional behavior is typed and safe.
- Product code still has no entity-label display/projection branches.

## Phase 8: Full Hard Query Release Gate

Goal: run the full hard-query suite as a release proof.

Must include:

- Backend contract tests for scenario parsing, tool args, state basis, approval rows, and DB truth.
- Playwright semantic tests for visible contract evidence.
- Seeded E2E for safe deterministic browser proof.
- Real LangGraph critical subset for at least:
  - one multi-approval cascade
  - one read-after-write verification
  - one mixed operation/RAG/read flow
- Hardcode guardrails.
- Artifact summary listing passed scenarios, skipped scenarios with reasons, and any accepted limitations.

Done when:

- The hard-query suite runs automatically.
- Failures point to generic contract/oracle mismatches rather than screenshot text drift.
- The suite is documented as the gate before broad agent behavior claims.
