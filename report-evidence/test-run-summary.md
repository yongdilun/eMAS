# eMAS Current Test Run Summary

Generated on 2026-06-20 after the latest fixes.

## Current Passing Gates

| Gate | Command | Result | Evidence log |
| --- | --- | --- | --- |
| Frontend unit/component tests | `npm test` in `eMas Front` | 197 passed, 0 failed | `report-evidence/frontend-npm-test.txt` |
| Frontend mocked Playwright E2E | `npm run test:e2e:mocked` in `eMas Front` | 62 passed, 0 failed | `report-evidence/frontend-e2e-mocked.txt` |
| Frontend response-document Playwright E2E | `npm run test:e2e:response-document` in `eMas Front` | 35 passed, 0 failed | `report-evidence/frontend-e2e-response-document.txt` |
| Frontend seeded oracle Playwright E2E | `npm run test:e2e:seeded-oracles` in `eMas Front` | 48 passed, 0 failed | `report-evidence/frontend-e2e-seeded-oracles.txt` |
| Factory Agent Python tests | `python -m pytest -q` in `factory-agent` | 1319 passed, 6 skipped, 0 failed | `report-evidence/factory-agent-pytest.txt` |
| Factory Agent node benchmark tests | `python -m pytest -q tests/benchmarks` with benchmark env enabled | 87 passed, 0 failed | `report-evidence/factory-agent-node-benchmarks.txt` |
| Go backend tests | `go test ./... -timeout=30m` in `emas` | All tested Go packages passed | `report-evidence/go-test-all.txt` |
| Frontend/backend oracle contract tests | `npm run test:backend-oracles` in `eMas Front` | 185 passed, 0 failed | `report-evidence/frontend-backend-oracles.txt` |

## Notes

- Current rerun result is 100% pass for the listed executable gates.
- Python and browser logs contain deprecation or tooling warnings, but the recorded command exit codes are `0` in the matching `.meta.txt` files.
- Some earlier failed/focused investigation logs are also kept in `report-evidence` for traceability; use the files listed above as the current final evidence.
