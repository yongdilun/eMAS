# Chatbot Test Governance

Phase 12 retires routine manual chatbot regression only after every old manual check is mapped to automation, a bounded human-only review, or an accepted gap. This document does not claim production-grade hardening; that remains Phase 17.

## Scenario 80 Governance Audit

Scenario 80 is a checklist gate. It passes only when all rows in the replacement matrix have a disposition, an owner, and either an automated L0-L5 gate or an accepted-gap entry.

Before retiring routine manual chatbot regression, confirm:

- Every old manual chatbot check is listed in the replacement matrix.
- Each row is marked as `retired`, `automated`, `human semantic review`, `compliance/sign-off`, `exploratory discovery`, `emergency-only`, or `accepted gap`.
- All automated rows name the lowest routine gate that owns the check.
- Human-only rows are recorded in the accepted-gap register with owner, severity, risk, target review date or phase, reason, and temporary workaround.
- Default PR validation remains `npm test` plus `npm run test:e2e -- --project=chromium`.
- `chromium-seeded`, `chromium-release`, and `chromium-synthetic` remain opt-in.
- Production synthetic prompts are read-only.
- Failure artifact expectations are documented for every automated gate.
- Fixed defects have regression coverage at the lowest useful layer.

## Manual Replacement Matrix

| Old manual chatbot check | Disposition | Replacement gate | Owner | Evidence |
|---|---|---|---|---|
| Open the app and find the floating AI Assistant control. | automated | L0 PR mocked Chromium | Frontend E2E owner | `chat-baseline.spec.js`; `npm run test:e2e -- --project=chromium` |
| Open the chat modal and confirm empty state plus usable composer. | automated | L0 PR mocked Chromium | Frontend E2E owner | `chat-baseline.spec.js` |
| Type a machine-status prompt and verify a final answer. | automated | L1 PR mocked Chromium, L3 seeded | Frontend E2E owner, Seeded L3 owner | Scenario 5 and scenario 32 |
| Check low-priority job results render in a structured response. | automated | L3 seeded | Seeded L3 owner | Scenario 33 |
| Ask a RAG/LOTO question and verify source chrome renders. | automated | L3 seeded, L5 synthetic structural canary | Seeded L3 owner, Synthetic L5 owner | Scenarios 34 and 73 |
| Watch notification/activity streaming reach completion. | automated | L2 PR mocked Chromium, L3 seeded | Frontend E2E owner, Seeded L3 owner | Scenarios 11, 13, 14, 38 |
| Validate malformed stream, stream drop, timeout, retry, empty answer, cancel, and modal close recovery. | automated | L1/L2 PR mocked Chromium, L3 hard | Frontend E2E owner, Hard L3 owner | Scenarios 18-26, 47-51 |
| Approve/reject approval-gated chatbot flows. | automated | L3 seeded and L3 hard | Seeded L3 owner, Hard L3 owner | Scenarios 35, 36, 40, 41, 42 |
| Confirm seeded Go API and Factory Agent contracts still match the browser. | automated | L3 seeded | Seeded L3 owner | Scenarios 31-38 |
| Try multi-step, multi-approval, stale-session, duplicate-submit, large-result, and cross-session hazards. | automated | L3 hard | Hard L3 owner | Scenarios 39-52 |
| Validate production-like paths, auth fallback, CORS/preflight, slow network, mobile, keyboard, artifact, rollback, and cache behavior. | automated | L4 release | Release L4 owner | Scenarios 53-70 |
| Check after deploy that chatbot opens, progresses, completes, and alerts on outage. | automated | L5 synthetic | Synthetic L5 owner | Scenarios 71-79 |
| Manually judge nuanced answer quality, tone, or domain usefulness beyond structural assertions. | human semantic review | Human-only accepted gap AG-P12-001 | Product/SME review owner | Quarterly semantic sample or release-candidate review when requested |
| Manually sign off compliance, policy, or regulated operational wording. | compliance/sign-off | Human-only accepted gap AG-P12-002 | Compliance owner | Formal sign-off outside Playwright |
| Explore brand-new prompts, new workflows, or unmodeled operational risks. | exploratory discovery | Human-only accepted gap AG-P12-003 | QA/exploratory owner | Findings must become scenarios only when they expose new risk |
| Manually diagnose incidents when automation, test harnesses, or production telemetry are unavailable. | emergency-only | Human-only accepted gap AG-P12-004 | On-call owner | Emergency runbook action; backfill automation when incident reveals a regression |
| Keep routine manual chatbot regression as a PR, release, or post-deploy requirement. | retired | Replaced by L0-L5 gates | Frontend E2E owner | No routine manual browser checklist remains required |

## Owners

| Area | Owner | Responsibility |
|---|---|---|
| PR mocked Playwright E2E | Frontend E2E owner | Keep `chromium` deterministic, fast, and blocking for PR chatbot browser regression. |
| Seeded full-stack L3 | Seeded L3 owner | Maintain real Vite, Go API, Factory Agent, seeded DB, and deterministic provider compatibility. |
| Hard orchestration L3 | Hard L3 owner | Maintain scenarios 39-52 and block promotion on reproducible orchestration defects. |
| Release validation L4 | Release L4 owner | Maintain release paths, auth fallback, slow-network, mobile, keyboard, rollback, and artifact gates. |
| Production synthetic L5 | Synthetic L5 owner | Maintain read-only canaries, alert classification, token checks, provider outage signals, and redaction. |
| Accepted-gap review | QA governance owner | Review human-only gaps monthly and during quarterly scenario review. |

## Commands

PR/default mocked validation:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium
```

Seeded L3 validation:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-seeded --grep "@l3-foundation"
```

Hard L3 validation:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-seeded --grep "@l3-hard"
```

Release L4 validation:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-release
```

Synthetic L5 validation:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-synthetic
```

## Scenario Lifecycle Rules

- Add a scenario only for a new risk, new user-visible state, new backend contract, new deployment hazard, or a fixed defect that needs regression coverage.
- Remove or merge redundant scenarios when two tests prove the same risk with the same assertion and same backend evidence.
- Every scenario must define expected failure artifacts: trace, screenshot/video policy, service logs, request logs, monitor result, or release fingerprint as appropriate for its layer.
- Every fixed defect needs regression coverage at the lowest useful layer before the phase can be marked done.
- Production synthetic prompts must stay read-only and must not approve, reject, mutate, or execute destructive workflows.
- Default PR CI must stay on deterministic mocked Chromium unless the team explicitly changes the governance rule.
- L3, L4, and L5 gates remain opt-in or scheduled; they do not silently join default PR CI.

## Accepted-Gap Rules

An accepted gap must include owner, severity, risk, target date or phase, reason, and temporary workaround. Gaps are allowed only when a check cannot be automated responsibly or should remain human judgment.

Cadence:

- Review accepted gaps monthly while any Phase 12 human-only gap is open.
- Review all accepted gaps during quarterly scenario review.
- Reopen the relevant phase if a medium or higher gap starts affecting routine PR, release, or post-deploy regression confidence.
- No critical or high accepted gap can be used to claim Phase 17 production-grade operational readiness.

## Quarterly Scenario Review

Use this checklist once per quarter:

- Confirm owners are still current.
- Confirm `chromium` remains deterministic and PR-safe.
- Confirm `chromium-seeded`, `chromium-release`, and `chromium-synthetic` remain opt-in unless deliberately promoted.
- Remove or merge redundant scenarios.
- Add scenarios for new incidents, new product risk, or fixed defects missing regression coverage.
- Confirm failure artifacts still include enough evidence to debug without rerunning manually.
- Confirm synthetic prompts are still read-only.
- Review accepted gaps, target dates, workarounds, and whether any human-only check can now be automated.
- Confirm no routine manual chatbot regression has crept back into PR, release, or post-deploy smoke.
