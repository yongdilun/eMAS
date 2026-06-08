# evidence_observation_node first-run benchmark report

- Updated: 2026-06-08T04:44:22.131129+00:00
- Cases recorded: 6
- Passed: 4
- Failed/error: 2

| Case | Behavior | Status | First failure |
| --- | --- | --- | --- |
| `evidence-observation-001-api-normalization` | API evidence normalization | passed |  |
| `evidence-observation-002-rag-citation` | RAG citation evidence | passed |  |
| `evidence-observation-003-no-match` | no-match evidence | passed |  |
| `evidence-observation-004-stale-background-ignored` | stale background result ignored | failed | expected evidence path is empty: graph_diagnostics.stale_background_results_ignored |
| `evidence-observation-005-multi-entity-aggregation` | multi-entity aggregation | passed |  |
| `evidence-observation-006-child-requirement-expansion` | child requirement expansion | failed | expected evidence path is empty: graph_diagnostics.requirement_expansion |
