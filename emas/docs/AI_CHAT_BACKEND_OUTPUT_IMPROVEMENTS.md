# AI Chat Backend Output Improvements (Readable UX)

Purpose: reduce noisy/duplicated chat output and return only user-meaningful information.

---

## Current UX Problem

Users currently see:
- a generic parser message (for example, "Parsed: explain job")
- a rich card (good)
- then extra follow-up cards like "Fetched..." from GET calls that repeat similar info

This is technically correct but hard to read.

---

## Recommendation: Backend-First Summarization

For each intent, backend should return:
1. One concise `message` for chat bubble
2. One high-value `result_cards[]` set for display
3. `suggested_calls[]` only for actions user can/should take next

Frontend can still execute GET calls, but when `result_cards` already exists, avoid additional "fetched" cards.

---

## Response Guidelines

### 1) Keep `message` short and user-facing
- Good: "JOB-SEED-002 has high delay risk. Review machine allocation before approval."
- Avoid: "Parsed: explain job."

### 2) Return curated `result_cards`
- Include only the top metrics and 2-4 bullets.
- Do not dump raw model internals in cards unless explicitly requested.

### 3) Keep `suggested_calls` actionable
- For read-only intents where cards are already complete, optional:
  - include calls for auditability, but mark them low-priority for UI
  - or omit redundant calls

### 4) Add optional UI hint fields
Add these optional fields to each `suggested_call`:

```json
{
  "method": "GET",
  "path": "/api/v1/ai/scheduling/jobs/JOB-SEED-002/delay-risk",
  "requires_approval": false,
  "purpose": "Inspect explicit risk factors",
  "ui": {
    "display": "hidden_if_result_card_exists",
    "priority": "secondary"
  }
}
```

Suggested values:
- `display`: `primary` | `secondary` | `hidden_if_result_card_exists`
- `priority`: `high` | `normal` | `low`

---

## Intent-Specific Card Contracts

### explain_job
Return one primary card:

```json
{
  "kind": "job_explanation",
  "title": "Job Explanation",
  "tone": "warning",
  "summary": "Job has high schedule risk and should be reviewed before execution.",
  "metrics": [
    { "label": "Job", "value": "JOB-SEED-002" },
    { "label": "Risk", "value": "High" }
  ],
  "bullets": [
    "Best machine for Gear Blank Turning: Lathe 02",
    "Best machine for Hobbing: CNC Mill 01",
    "Review readiness and due-date pressure"
  ]
}
```

Do not send a second card with equivalent explanation text.

### delay_risk
Return one compact risk card:

```json
{
  "kind": "delay_risk",
  "title": "Delay Risk",
  "tone": "warning",
  "summary": "Projected delay: 120 mins",
  "metrics": [
    { "label": "Job", "value": "JOB-SEED-002" },
    { "label": "Risk", "value": "High" },
    { "label": "Score", "value": "51.4" }
  ],
  "bullets": ["Material readiness below threshold", "Machine contention on Lathe 02"]
}
```

### create_job (write intent)
- Keep one clear assistant message:
  - "I can create JOB for 100 units of P-001. Please approve to continue."
- Return one approval card/action; avoid generic "Parsed" warning lines.

---

## Proposed Backend Policy

1. If `result_cards` is non-empty and complete, do not emit additional read-only follow-up calls unless needed.
2. If read-only calls are emitted for traceability, tag them with `ui.display = hidden_if_result_card_exists`.
3. Avoid model/debug metadata in user-facing fields (for example, engine IDs) unless debug mode is enabled.

---

## Optional Debug Mode (for developers only)

Support request flag:

```json
{ "query": "...", "debug": true }
```

When `debug: true`, include:
- parser traces
- model metadata
- all secondary suggested calls

When false/default, return concise user-facing output only.

---

## Why this helps

- Reduces cognitive overload
- Keeps critical insight visible
- Preserves action safety (approval for writes)
- Still allows full traceability in debug mode

