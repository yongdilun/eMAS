# Factory graph node autonomy scorecard

- Updated: 2026-06-20T07:37:34.737992+00:00
- Live LLM enabled: False
- Score version: 1

| Node | Score | Recommendation | Safety Cap | Pass Rate | Reasons |
| --- | ---: | --- | --- | ---: | --- |
| `approval_node` | 34 | do_not_autonomize | no_autonomous_action | 1.0 | Node owns execution or final authority; autonomous behavior should not bypass deterministic control. |
| `evidence_observation_node` | 63 | observe | deterministic_only | 1.0 | Node is a deterministic validation/projection layer; use score as observation signal only.; Scenario set has high complexity pressure. |
| `finalize_node` | 21 | do_not_autonomize | no_autonomous_action | 1.0 | Node owns execution or final authority; autonomous behavior should not bypass deterministic control. |
| `planner_choose_tool_node` | 81 | guarded_pilot | approval_required | 1.0 | Write or approval behavior requires a guarded pilot instead of direct autonomy.; Scenario set has high complexity pressure. |
| `planner_decision_node` | 86 | upgrade_candidate | read_only | 1.0 | Scenario set has high complexity pressure.; Deterministic path shows brittleness or shallow assertion pressure. |
| `requirement_ledger_node` | 53 | observe | deterministic_only | 1.0 | Node is a deterministic validation/projection layer; use score as observation signal only.; Scenario set has high complexity pressure. |
| `response_document_node` | 53 | do_not_autonomize | no_autonomous_action | 1.0 | Node owns execution or final authority; autonomous behavior should not bypass deterministic control.; Scenario set has high complexity pressure. |
| `satisfaction_node` | 67 | observe | deterministic_only | 1.0 | Node is a deterministic validation/projection layer; use score as observation signal only.; Scenario set has high complexity pressure. |
| `semantic_intake_node` | 77 | upgrade_candidate | read_only | 1.0 | Scenario set has high complexity pressure.; LLM lift signal is present through mocked or opt-in live diagnostics. |
| `tool_execution_node` | 52 | do_not_autonomize | no_autonomous_action | 1.0 | Node owns execution or final authority; autonomous behavior should not bypass deterministic control.; Scenario set has high complexity pressure. |
| `tool_retrieval_node` | 75 | upgrade_candidate | read_only | 1.0 | Scenario set has high complexity pressure.; LLM lift signal is present through mocked or opt-in live diagnostics. |
