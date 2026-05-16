# Manual Prompt Regression Bank

Phase 18 started the deterministic bank for manual chatbot prompt misses. Phase 19 expands it into a permanent prompt/workflow regression program. Every new prompt miss should be added to `tests/e2e/scenarios/manual_prompt_regressions.json` before the defect is closed, with parser expectations, route expectations, owner/severity, the lowest useful automated coverage, and a browser coverage flag.

## Phase 8 Manual Failure Promotion Workflow

Use this workflow whenever a manual check, exploratory session, support report, or weak automated test finds a chatbot failure. The failure is not closed until it is represented by an oracle-backed regression or by an accepted gap approved in the tracker.

1. Capture the failure before changing product code.
2. Fill the intake template below in the issue, PR, or bug note.
3. Pick an existing oracle such as `SO-001` or propose a new `SO-xxx` oracle entry.
4. Add the failing regression at the lowest useful layer.
5. Run the failing command and link the artifact that proves it fails for the captured bug.
6. Fix the product or test bug.
7. Rerun the same regression command and any touched focused checks.
8. Update `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md` with files changed, commands run, test results, decisions, blockers/open questions, and next action.

Lowest useful layer means the cheapest layer that would have caught the defect without relying on weaker downstream signals:

| Failure shape | Lowest useful layer |
|---|---|
| Entity extraction or wording miss | Parser or route pytest. |
| Wrong route or unsupported clarification | Route pytest, then seeded browser only if UI projection matters. |
| Approval, mutation, audit, or idempotency defect | Stateful graph/API pytest or seeded full-stack oracle. |
| Snapshot, timeline, final response, or stale-turn mismatch | Snapshot/frontend unit oracle. |
| SSE ordering, reconnect, malformed payload, or disconnect defect | SSE pytest or focused Playwright SSE. |
| Browser-only layout, visibility, or interaction defect | Mocked or seeded Playwright at the narrowest project that reproduces it. |
| Seeded adapter hides real planner behavior | Real LangGraph graph or `chromium-real-langgraph` opt-in browser proof. |

## Manual Failure Intake Template

Copy this template exactly. If a field is unknown, fill it with `unknown` plus the owner who will supply it. Do not close the failure while any closure-gate item is unchecked.

```markdown
## Manual Failure Intake

- Intake ID:
- Date found:
- Reporter:
- Owner:
- Severity: critical | high | medium | low
- Exact prompt or user action:
- Preconditions/test data/user/route:
- Artifact/log/screenshot/trace link:
- Observed behavior:
- Expected behavior:
- Reproduction steps:
- Existing oracle selected: SO-xxx or none
- Proposed new oracle: SO-xxx title or none
- Lowest useful test layer:
- Regression test file:
- Failing regression command:
- Failing regression evidence link:
- Passing command after fix:

## Closure Gate

- [ ] Exact prompt or user action is captured.
- [ ] Artifact, log, screenshot, or trace link is attached.
- [ ] Observed and expected behavior are concrete and testable.
- [ ] Existing oracle is selected or a proposed new oracle is named.
- [ ] Lowest useful test layer is named.
- [ ] Owner and severity are assigned.
- [ ] A regression test fails before or with the fix.
- [ ] The same regression passes after the fix.
- [ ] Regression bank or stateful oracle file maps the bug to the test file and command.
- [ ] Tracker is updated with files changed, commands run, test results, decisions, blockers/open questions, and next action.
```

Closure rule: `tested manually only` is never an acceptable terminal state for a fixed chatbot failure. A new manual failure must close as one of these outcomes:

| Outcome | Required evidence |
|---|---|
| `promoted_regression` | Bank or oracle entry, failing-before-fix evidence, passing-after-fix evidence, test file, and command. |
| `accepted_gap` | Tracker entry with owner, severity, risk, workaround, target phase/date, reason, and explicit blocking status. Critical or high mutating gaps block phase promotion unless the owner records an approved release exception. |

Review cadence: the QA regression bank owner reviews new entries and accepted gaps weekly until two consecutive release cycles complete without a new manual prompt/workflow miss.

## Phase 18 Seed

| ID | Prompt | Expected deterministic behavior | Coverage |
|---|---|---|---|
| `phase18-loto-m-cnc-01` | `What LOTO procedure applies before working on M-CNC-01?` | Extract `M-CNC-01`, route to the LOTO/RAG path, complete without asking for the machine ID again, and return source metadata tied to `LOTO-M-CNC-01`. | Parser unit, mocked browser smoke, seeded fake-provider browser gate |

## Phase 19 LOTO Wording Matrix

| ID | Prompt | Expected deterministic behavior | Coverage |
|---|---|---|---|
| `phase19-loto-before-service-m-cnc-01` | `Before servicing M-CNC-01, which LOTO procedure applies?` | Same M-CNC-01 LOTO/RAG route and source metadata as the original manual miss. | Parser unit, route matrix, seeded fake-provider browser gate |
| `phase19-loto-lockout-tagout-m-cnc-01` | `Need the lockout/tagout SOP for m-cnc-01 before maintenance.` | Normalize lowercase machine ID and route to LOTO/RAG without clarification. | Parser unit, route matrix, seeded fake-provider browser gate |
| `phase19-loto-parenthesized-m-cnc-01` | `For machine (M-CNC-01), what lockout procedure should I follow?` | Extract the parenthesized ID and route to LOTO/RAG without asking which machine. | Parser unit, route matrix, seeded fake-provider browser gate |
| `phase19-loto-markdown-m-cnc-01` | `### Safety check` / `LOTO for \`M-CNC-01\` before touching the spindle.` | Extract the markdown-formatted ID and return the same controlled LOTO/RAG answer. | Parser unit, route matrix, seeded fake-provider browser gate |

## Required Bank Schema

Every bank entry must include `source_prompt`, `observed_failure`, `expected_behavior`, `owner`, `severity`, `lowest_test_layer`, and `browser_coverage`. Compatibility fields `prompt`, `expected`, and `coverage` remain present so older Phase 18 gates and Playwright support helpers can read the same bank.

Phase 8 adds promotion fields to every bank entry:

| Field | Required content |
|---|---|
| `artifact_link` | Link to a log, screenshot, trace, issue, or historical note that explains the captured miss. |
| `selected_oracle` | Existing `SO-xxx` oracle that covers the failure, or `null` when a new oracle is needed. |
| `proposed_oracle` | Proposed `SO-xxx` title when no existing oracle fits, or `null` when `selected_oracle` is set. |
| `regression.test_file` | Test file that now catches the failure. |
| `regression.command` | Focused command for the regression. |
| `regression.failing_before_closure_required` | Must be `true`; the issue or PR must link the actual failing run for new findings. |
| `regression.failure_evidence` | Link or note for the failing-before-fix proof. |
| `regression.passing_evidence` | Link or note for the passing-after-fix proof. |

## Triage Rule

When an operator finds a new prompt or workflow miss, classify it as parser, route, seeded workflow, browser, or accepted-gap coverage. Close the miss only after the bank entry has deterministic coverage, a failing regression before closure, and a passing run after the fix. If coverage is deferred, record an accepted gap in `STATEFUL_ORACLE_TESTING_TRACK.md` with owner, severity, risk, target date/phase, reason, temporary workaround, and blocking status.

## Accepted Gap Format

Accepted gaps are allowed only when the team deliberately defers automated coverage for a known miss. They are not a substitute for an oracle on critical or high-risk mutating behavior.

Each accepted gap must include:

| Field | Required content |
|---|---|
| `gap_id` | Stable ID such as `AG-001`. |
| `source_prompt` | Exact prompt or workflow that exposed the miss. |
| `observed_failure` | What the product did incorrectly, with artifact link when available. |
| `expected_behavior` | Concrete behavior the future oracle or test must enforce. |
| `severity` | `critical`, `high`, `medium`, or `low`. |
| `owner` | Person or team accountable for closing the gap. |
| `risk` | What real defect can still escape while the gap is open. |
| `workaround` | Temporary operator or release workaround. |
| `target_phase_or_date` | Phase or date when the gap must be revisited. |
| `lowest_required_layer` | Lowest useful future coverage layer. |
| `blocking_status` | Whether this blocks phase promotion or release. |

Use this shape when recording a gap:

```json
{
  "gap_id": "AG-001",
  "source_prompt": "exact operator prompt or workflow",
  "observed_failure": "what failed and where the artifact lives",
  "expected_behavior": "specific behavior the future test must enforce",
  "severity": "medium",
  "owner": "qa-platform",
  "risk": "defect that can still escape",
  "workaround": "manual check or release constraint while open",
  "target_phase_or_date": "Phase 4",
  "lowest_required_layer": "pytest_snapshot",
  "blocking_status": "does_not_block_phase_1"
}
```

Critical or high gaps in mutating workflows block phase promotion unless the tracker explicitly documents a temporary release exception approved by the owner.
