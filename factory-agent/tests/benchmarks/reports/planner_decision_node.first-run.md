# planner_decision_node first-run benchmark report

- Updated: 2026-06-08T04:38:58.928859+00:00
- Cases recorded: 7
- Passed: 3
- Failed/error: 4

| Case | Behavior | Status | First failure |
| --- | --- | --- | --- |
| `planner-decision-001-retrieve-decision` | retrieve decision | passed |  |
| `planner-decision-002-revise-requirements` | revise requirements | passed |  |
| `planner-decision-003-request-clarification` | request clarification | failed | expected evidence path is empty: planner_decisions |
| `planner-decision-004-fail-closed` | fail closed | failed | expected evidence path is empty: planner_decisions |
| `planner-decision-005-malformed-planner-output` | malformed planner output | failed | expected evidence path is empty: planner_proposer_diagnostics |
| `planner-decision-006-no-llm-config` | no LLM config | passed |  |
| `planner-decision-007-dependency-blocked-requirement` | dependency-blocked requirement | failed | expected evidence path is empty: planner_diagnostics.planner_decision_node.blocked_by_dependency_plan |
