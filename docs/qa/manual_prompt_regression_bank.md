# Manual Prompt Regression Bank

Phase 18 started the deterministic bank for manual chatbot prompt misses. Phase 19 expands it into a permanent prompt/workflow regression program. Every new prompt miss should be added to `tests/e2e/scenarios/manual_prompt_regressions.json` before the defect is closed, with parser expectations, route expectations, owner/severity, the lowest useful automated coverage, and a browser coverage flag.

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

## Required Schema

Every bank entry must include `source_prompt`, `observed_failure`, `expected_behavior`, `owner`, `severity`, `lowest_test_layer`, and `browser_coverage`. Compatibility fields `prompt`, `expected`, and `coverage` remain present so older Phase 18 gates and Playwright support helpers can read the same bank.

## Triage Rule

When an operator finds a new prompt or workflow miss, classify it as parser, route, seeded workflow, browser, or accepted-gap coverage. Close the miss only after the bank entry has deterministic coverage or an accepted gap in `TRACK.md` with owner, severity, risk, target date/phase, reason, and temporary workaround.

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
