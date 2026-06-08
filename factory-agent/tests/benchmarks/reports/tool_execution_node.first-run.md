# tool_execution_node first-run benchmark report

- Updated: 2026-06-08T04:43:26.943372+00:00
- Cases recorded: 9
- Passed: 7
- Failed/error: 2

| Case | Behavior | Status | First failure |
| --- | --- | --- | --- |
| `tool-execution-001-api-success` | API success | passed |  |
| `tool-execution-002-api-404-no-match` | API 404/no-match | passed |  |
| `tool-execution-003-api-500` | API 500 | passed |  |
| `tool-execution-004-missing-tool` | missing tool | passed |  |
| `tool-execution-005-rag-success` | RAG success | passed |  |
| `tool-execution-006-rag-insufficient-context` | RAG insufficient context | passed |  |
| `tool-execution-007-rag-exception` | RAG exception | passed |  |
| `tool-execution-008-parallel-read-batch` | parallel read batch | error | PlannerDecisionValidationError: capability need must reference the planner decision requirement; selected tool is not in the hydrated candidate window: get__jobs_{id}; selected too |
| `tool-execution-009-approval-required-write-staging` | approval-required write staging | failed | expected evidence path is empty: pending_approval.approval_id |
