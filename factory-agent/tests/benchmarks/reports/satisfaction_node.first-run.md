# satisfaction_node first-run benchmark report

- Updated: 2026-06-08T04:45:36.141696+00:00
- Cases recorded: 9
- Passed: 7
- Failed/error: 2

| Case | Behavior | Status | First failure |
| --- | --- | --- | --- |
| `satisfaction-001-satisfied` | satisfied | passed |  |
| `satisfaction-002-impossible-no-match` | impossible/no-match | passed |  |
| `satisfaction-003-failed-tool` | failed tool API 500 | passed |  |
| `satisfaction-004-wrong-source` | wrong source | passed |  |
| `satisfaction-005-ambiguous-evidence` | ambiguous evidence | passed |  |
| `satisfaction-006-stale-evidence-excluded` | stale evidence excluded | failed | expected evidence path is empty: graph_diagnostics.phase9_active_revision_evidence.historical_evidence_refs |
| `satisfaction-007-write-deferral` | write deferral | passed |  |
| `satisfaction-008-replan` | replan | failed | expected evidence path is empty: graph_diagnostics.planner_owned_replan_spine |
| `satisfaction-009-replan-limit` | replan limit | passed |  |
