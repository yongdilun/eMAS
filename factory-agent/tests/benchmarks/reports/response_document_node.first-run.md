# response_document_node first-run benchmark report

- Updated: 2026-06-08T04:49:17.652799+00:00
- Cases recorded: 10
- Passed: 8
- Failed/error: 2

| Case | Behavior | Status | First failure |
| --- | --- | --- | --- |
| `response-document-001-status-result` | status result | passed |  |
| `response-document-002-result-table` | result table | passed |  |
| `response-document-003-document-answer` | document answer | passed |  |
| `response-document-004-insufficient-context` | insufficient context | passed |  |
| `response-document-005-no-record` | no record | passed |  |
| `response-document-006-approval-required` | approval required | passed |  |
| `response-document-007-mutation-result` | mutation result | passed |  |
| `response-document-008-approval-decision` | approval decision | passed |  |
| `response-document-009-replan-limit-diagnostic` | replan-limit diagnostic | failed | expected evidence path is empty: response_document_context.diagnostics.blocks |
| `response-document-010-stale-evidence-not-reused` | stale evidence not reused | failed | expected evidence path is empty: response_document_context.diagnostics.historical_evidence_refs |
