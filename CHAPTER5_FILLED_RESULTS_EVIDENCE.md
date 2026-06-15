# Chapter 5 Filled Results Evidence

This file contains report-ready Chapter 5 result text and tables using data already available in the repository. Use this as the source for filling Chapter 5. The pass-rate wording is intentionally limited to the executed final gates recorded in the project evidence.

## Evidence Sources Used

| Evidence item | Source |
|---|---|
| Current test surface count | `TEST_INVENTORY_AND_PRIORITY.md` and static repo count |
| Final frontend and E2E pass evidence | `docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md`, Phase 12.1 waiver removal evidence |
| Phase 6 integration, seed runner, overlap and tool metadata evidence | `docs/QA_UPGRADE_INTEGRATION_TRACKER.md` |
| Scheduler scenario expectations | `emas/testdata/scheduler_eval/v1_scenario_expectations.json` |
| Canonical simulated factory dataset | `emas/internal/seeddata/canonical.go` and `emas/internal/seeddata/bom_spec.go` |

## Safe 100 Percent Wording

Use this wording:

> The final executed frontend unit/component and Playwright E2E gates achieved a 100% pass rate, with 0 failed tests reported in the recorded evidence. The 100% result refers to the executed final verification gates, not to unexecuted or optional future test combinations.

Do not write:

> Every possible test in the entire repository passed.

That second statement is too broad because the repository contains old, optional, historical, and environment-dependent test artifacts.

## 5.2 Filled Evaluation Data Paragraph

The evaluation used both simulated manufacturing data and automated test evidence. The simulated dataset contained 26 root production jobs, 10 machines, 9 products, 14 inventory materials, 9 expected material arrivals, 4 product inventory records, 3 inventory reservation records, 27 process steps, and 26 input BOM relationships. These records were generated from the canonical seed data used by the system. The dataset was designed to represent a realistic manufacturing environment while avoiding the confidentiality issues of using live factory data.

In addition to the simulated data, the evaluation used automated test results from the backend, frontend, Factory Agent, and browser-based E2E workflows. The current project contains 57 Go backend test files, 94 Factory Agent pytest files, 13 frontend component/unit test files under the frontend source directory, and 33 Playwright E2E specification files. Static counting also identified 225 Go test functions, 1005 Factory Agent pytest definitions, 176 frontend source test declarations, and 188 Playwright test declarations. These numbers show that the evaluation was supported by a broad automated testing surface rather than only manual inspection.

## Table 5.2 Filled Dataset Summary

| Data Category | Quantity | Evidence |
|---|---:|---|
| Root production jobs | 26 | Canonical seed jobs `JOB-SEED-001` to `JOB-SEED-026` |
| Machines | 10 | Canonical machine seed data |
| Products and subproducts | 9 | Product seed data `P-001` to `P-009` |
| Inventory materials | 14 | Material seed data `MAT-001` to `MAT-014` |
| Expected material arrivals | 9 | Arrival seed data `ARR-SEED-001` to `ARR-SEED-009` |
| Product inventory records | 4 | Product inventory seed records |
| Inventory reservation records | 3 | Material reservation seed records |
| Process steps | 27 | Product process and routing seed data |
| Input BOM relationships | 26 | Canonical BOM input relationships |
| Seed AI proposal | 1 | `AIPROP-SEED-001` |
| Seed pipeline manifest scenarios | 124 | QA integration tracker |
| Factory Agent generated API tools | 138 | Tool metadata regeneration evidence |

## 5.5 Filled Scheduling and Shortage Result Paragraph

The scheduling and shortage-resolution functions were evaluated using seeded manufacturing scenarios and automated verification gates. The scheduler scenario expectations include canonical seed scheduling, true material shortage, delayed material wait, child BOM shortage, no-shortage control, resource overload, and one-shot resolution. These scenarios check important correctness gates such as zero machine overlap, zero invalid time ranges, zero missing slots, zero duplicate slots, zero step-order violations, no feasible proposal without slots, no infeasible proposal without reason, no material shortage without evidence, and no silently excluded jobs.

The Phase 6 overlap check also supports the scheduling result. The recorded verification found 26 jobs and 26 proposal IDs. Proposal validation returned `valid: true`, `total_slots: 89`, and `overlap_count: 0`. This indicates that the generated proposal slots did not contain machine-overlap conflicts in the tested seeded proposal set.

## Table 5.4 Filled Scheduling Scenario Results

| Scenario | Expected Behaviour | Result |
|---|---|---|
| Canonical seed schedule | Jobs should not contain overlap, invalid time ranges, missing slots, duplicate slots, or step-order violations | Passed in scheduler hard-gate expectations and proposal overlap verification |
| True material shortage | System should identify material shortage only when supported by shortage evidence | Passed as executable scheduler scenario expectation |
| Delayed material wait | Jobs with later material arrival should wait for arrival instead of being falsely marked infeasible | Passed as executable scheduler scenario expectation |
| Child BOM shortage | Parent product shortage should trace to material or subproduct evidence | Passed as executable scheduler scenario expectation |
| No-shortage control | System should avoid false shortage rows | Passed as executable scheduler scenario expectation |
| Resource overload | Resource pressure should not be misclassified as material shortage | Passed as executable scheduler scenario expectation |
| One-shot shortage resolution | Applying recommended material rows and rerunning should remove or reduce material infeasibility | Passed as executable scheduler scenario expectation |
| Proposal overlap validation | Proposed schedule should not contain machine overlap | Passed: 89 proposal slots, overlap count 0 |

## 5.8 Filled Automated Testing Result Paragraph

Automated testing provides the strongest reliability evidence for the final eMAS system. The recorded final verification gates show 100% pass rate for the executed frontend unit/component and Playwright E2E gates. The frontend unit/component suite recorded 133 passed tests, 0 failed tests, and 0 skipped tests. The Playwright E2E gates recorded 30 response-document tests passed, 35 seeded-oracle tests passed, 3 real-LangGraph tests passed, and 21 release tests passed, all with 0 failed tests. Therefore, the final executed E2E gate total was 89 passed tests and 0 failed tests, giving a 100% pass rate for the executed E2E verification gates.

The Factory Agent backend also had strong automated evidence. The recorded pytest run reported 1025 passed tests, 0 failed tests, 3 skipped tests, and 0 expected failures. Additional focused Factory Agent gates also passed, including 88 planner-owned graph phase tests and 56 route/tool-selector related tests. Backend and integration evidence from the QA tracker also records that `go test ./...` passed for all Go packages and that the full seeded scenario runner passed after the authentication-header manifest fix.

## Table 5.7 Filled Automated Testing Evidence

| Test Category | Evidence Surface | Final Recorded Result | Pass Rate |
|---|---:|---|---:|
| Frontend unit/component tests | `npm test` | 133 passed, 0 failed, 0 skipped | 100% |
| Playwright response-document E2E | `npm run test:e2e:response-document` | 30 passed, 0 failed, 0 skipped | 100% |
| Playwright seeded-oracle E2E | `npm run test:e2e:seeded-oracles` | 35 passed, 0 failed, 0 skipped | 100% |
| Playwright real-LangGraph E2E | `npm run test:e2e:real-langgraph` | 3 passed, 0 failed, 0 skipped | 100% |
| Playwright release E2E | `npm run test:e2e:release` | 21 passed, 0 failed, 0 skipped | 100% |
| Combined final Playwright E2E gates | Four final E2E commands above | 89 passed, 0 failed, 0 skipped | 100% |
| Factory Agent pytest | `python -m pytest -q` | 1025 passed, 0 failed, 3 skipped | 100% of executed tests |
| Factory Agent graph phase tests | Planner-owned graph phase suite | 88 passed, 0 failed, 0 skipped | 100% |
| Factory Agent route/tool-selector tests | Legacy cleanup, route contract, tool selector | 56 passed, 0 failed, 0 skipped | 100% |
| Go backend aggregate tests | `go test ./...` | All Go packages passed or had no test files | Passed |
| Seed pipeline runner | `run_seed_pipeline.ps1` | 124 manifest scenarios, 52 HTTP scenarios, 2 approval proofs, 0 other/needs check | Passed |

## 5.9 Filled End-to-End Workflow Result Paragraph

End-to-end testing was included because eMAS depends on the frontend, backend API, database, Factory Agent, approval workflow, and scheduling logic working together. The final E2E evidence shows that the executed browser-based verification gates passed with 0 failures. The response-document E2E gate confirmed that assistant responses, approval-related messages, and final response rendering behaved correctly. The seeded-oracle gate confirmed important seeded workflows such as data integrity, prompt regression, and SSE-related behaviours. The real-LangGraph gate confirmed that critical workflows were tested against the actual Factory Agent graph rather than only a mocked adapter. The release E2E gate confirmed release-harness workflows after the previous waiver was removed.

Based on these results, the final executed E2E gates achieved 89 passed tests and 0 failed tests. This supports the claim that the current eMAS prototype is not only implemented at component level but also verified through full workflow testing.

## Table 5.8 Filled E2E Workflow Results

| E2E Workflow | Test Evidence | Result |
|---|---|---|
| Response-document and final-answer rendering | `npm run test:e2e:response-document` | 30 passed, 0 failed |
| Seeded data-integrity and prompt-regression workflows | `npm run test:e2e:seeded-oracles` | 35 passed, 0 failed |
| Real Factory Agent graph critical workflows | `npm run test:e2e:real-langgraph` | 3 passed, 0 failed |
| Release-harness browser workflows | `npm run test:e2e:release` | 21 passed, 0 failed |
| Combined final E2E gates | Four E2E gates above | 89 passed, 0 failed, 100% pass rate |

## 5.6 Filled Factory Agent Result Paragraph

The Factory Agent was evaluated through automated graph, tool-routing, API alignment, and browser workflow tests. The final evidence shows that the full Factory Agent pytest suite passed with 1025 passed tests, 0 failed tests, and 3 skipped tests. The skipped tests were not failures; they represent tests not executed under the selected environment. Additional focused Factory Agent checks also passed, including 88 planner-owned graph phase tests and 56 route/tool-selector related tests.

The Factory Agent also regenerated 138 API tools from the current Swagger definition. This supports the alignment between the Go backend API and the AI assistant tool layer. The result indicates that the AI assistant was evaluated not only by reading its output manually but also by checking whether its graph runtime, tool selection, response document, approval handling, and API metadata remained consistent.

## Table 5.5 Filled Factory Agent Results

| Test Area | Evidence | Result |
|---|---|---|
| Agent graph runtime | Planner-owned graph phase suite | 88 passed, 0 failed |
| Tool selection and route contracts | Route contract and tool selector suite | 56 passed, 0 failed |
| Full Factory Agent pytest | Full pytest suite | 1025 passed, 0 failed, 3 skipped |
| Backend tool metadata alignment | Generated tools from Swagger | 138 tools generated |
| Real graph browser workflow | Playwright real-LangGraph gate | 3 passed, 0 failed |
| Seeded oracle workflow | Playwright seeded-oracle gate | 35 passed, 0 failed |

## 5.11 Filled Summary of Findings

The results show that the final eMAS system has strong supporting evidence from both simulated factory data and automated testing. The system was evaluated using 26 seeded jobs, 10 machines, 9 products, 14 materials, 9 expected arrivals, and 26 input BOM relationships. This simulated manufacturing dataset was sufficient to test scheduling, inventory, BOM dependency, shortage, and reporting workflows without requiring confidential live factory data.

The automated testing results also support the reliability of the system. The final recorded frontend unit/component suite achieved 133 passed tests with 0 failures. The final executed Playwright E2E gates achieved 89 passed tests with 0 failures, giving a 100% pass rate for the executed E2E verification gates. The Factory Agent pytest suite recorded 1025 passed tests with 0 failures, and the full seeded scenario runner passed with 124 manifest scenarios and 52 HTTP scenarios. These results show that eMAS has been evaluated across component, backend, AI-agent, and end-to-end workflow levels.

Overall, the results support the conclusion that eMAS is a working AI-assisted manufacturing management prototype. The strongest results are in automated reliability, integrated workflow testing, Factory Agent graph verification, and scheduling/shortage-resolution validation. The main remaining limitation is that the evaluation still uses simulated factory data rather than live factory deployment data. Therefore, future work should validate the system with real manufacturing users and production data after confidentiality and deployment constraints are resolved.
