# semantic_intake_node first-run benchmark report

- Updated: 2026-06-08T04:36:22.415932+00:00
- Cases recorded: 10
- Passed: 9
- Failed/error: 1

| Case | Behavior | Status | First failure |
| --- | --- | --- | --- |
| `semantic-intake-001-single-read` | single read | passed |  |
| `semantic-intake-002-filtered-list` | filtered list | passed |  |
| `semantic-intake-003-document-rag` | document/RAG | passed |  |
| `semantic-intake-004-mutation` | mutation | passed |  |
| `semantic-intake-005-multi-intent-cascade` | multi-intent cascade | passed |  |
| `semantic-intake-006-conditional-follow-up` | conditional follow-up | passed |  |
| `semantic-intake-007-formatting-instruction` | formatting instruction | passed |  |
| `semantic-intake-008-missing-entity` | missing entity | failed | expected evidence path is empty: requirement_ledger.requirements |
| `semantic-intake-009-pronoun-follow-up` | pronoun follow-up | passed |  |
| `semantic-intake-010-llm-repair-fallback` | LLM repair/fallback | passed |  |
