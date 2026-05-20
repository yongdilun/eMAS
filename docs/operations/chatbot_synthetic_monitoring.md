# Chatbot Synthetic Monitoring

Owner: `chatbot-oncall`

Scope: Phase 17 operational readiness for safe, read-only Factory Agent chatbot monitoring. Synthetic checks must not approve, reject, or mutate production records.

## Alert Response Runbook

Every synthetic alert must include:

- `code`: machine-readable alert code such as `synthetic_timeout`, `backend_unavailable`, `auth_failure`, `provider_outage`, `missing_final_answer`, or `latency_burn_rate`.
- `owner`: accountable responder or rotation.
- `severity`: one of `critical`, `high`, `medium`, or `low`.
- `runbook_url`: this document or a team-owned replacement.

Severity rules:

| Severity | Operational rule |
|---|---|
| `critical` | Blocks release or requires rollback when production/staging is affected. Examples: synthetic timeout, backend unavailable, auth failure, provider outage, missing final answer, rollback validation failure, or unrecoverable recreated environment failure. |
| `high` | Blocks operational or production-grade signoff until fixed. Examples: alert has no owner, alert has no runbook, emergency disable path fails, or the gate command cannot run. |
| `medium` | Accepted only with owner, risk, target date/phase, reason, and temporary workaround. |
| `low` | Tracked but not release blocking. |

Triage:

1. Check whether the alert is from local release-harness mode or live synthetic mode.
2. Inspect `eMas Front/test-results/synthetic-monitor/synthetic-results.json` and `synthetic-alerts.ndjson`.
3. For `backend_unavailable`, probe `/agent/ready`, `/api/v1/health` or the deployment equivalent.
4. For `auth_failure`, rotate or reissue the synthetic token and rerun `npm run test:e2e -- --project=chromium-synthetic`.
5. For `provider_outage`, confirm model/RAG dependency health and keep the canary read-only.
6. For `missing_final_answer` or `synthetic_timeout`, inspect browser traces and release proxy logs, then run the rollback validation command from the release runbook.

Temporary monitor disable:

Pause alert delivery only when the monitor itself is faulty or generating confirmed false positives. Keep the result artifacts, record the gap in `TRACK.md`, and assign an owner and target date before signoff.
