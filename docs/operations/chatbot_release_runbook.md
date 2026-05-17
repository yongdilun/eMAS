# Chatbot Release And Rollback Runbook

Owner: release operator / `chatbot-oncall`

Scope: opt-in production-like and operational readiness gates for the Factory Agent chatbot. This does not replace Phase 18-19 prompt/workflow robustness signoff.

## Fast PR Gate

From `eMas Front`:

```powershell
npm run test:backend-oracles
npm test
npm run test:e2e:mocked
```

This is the default pull-request gate. It blocks broken fast Factory Agent oracle/schema/manual-bank coverage, frontend unit regressions, and deterministic mocked Chromium browser regressions without starting seeded full-stack services, real LangGraph browser proof, live synthetic monitoring, or an LLM provider.

GitHub Actions equivalent: `Chatbot Oracle Gates` runs this gate on pull requests and pushes.

## Release And Pre-Merge Oracle Gates

Run seeded stateful oracles before release signoff or from the `Chatbot Oracle Gates` workflow dispatch input:

```powershell
npm run test:e2e:seeded-oracles
```

Run the real LangGraph browser proof only when explicitly requested or as part of release signoff:

```powershell
npm run test:e2e:real-langgraph
```

Run production-like release validation before release signoff:

```powershell
npm run test:e2e:release
```

Run synthetic monitoring as a read-only gate. The default command uses the local release harness; live production/staging mode requires explicit read-only synthetic credentials and read-only prompts.

```powershell
npm run test:e2e:synthetic
```

## Production-Grade Gate

From `eMas Front`:

```powershell
npm run operational:gate
```

The command runs the Phase 17 matrix:

- frontend unit tests,
- fast backend stateful oracles,
- deterministic mocked Chromium PR suite,
- seeded L3 foundation,
- seeded hard orchestration,
- seeded stateful data/prompt/SSE oracles,
- real LangGraph critical browser proof,
- release validation,
- read-only synthetic monitoring,
- security/privacy checks,
- reliability checks.

Use a dry run to print the matrix without executing child checks:

```powershell
npm run operational:gate -- --dry-run
```

GitHub Actions equivalent: manually dispatch `Playwright Operational Readiness`. For narrower release lanes, manually dispatch `Chatbot Oracle Gates` with the seeded, real LangGraph, release validation, or read-only synthetic input selected.

## Rollback Validation

Set the previous known-good build URL, then run the release rollback smoke:

```powershell
$env:PLAYWRIGHT_RELEASE_ROLLBACK_BASE_URL = "https://previous-known-good.example.com"
npm run test:e2e:release -- --grep "scenario 68"
```

The rollback URL must answer `/__release/precheck` with a successful release precheck before the candidate can be used as the rollback target.

## Emergency Disable

If the chatbot must be disabled while the rest of eMAS remains online, build or start the frontend with:

```powershell
$env:VITE_FACTORY_AGENT_EMERGENCY_DISABLED = "1"
$env:VITE_FACTORY_AGENT_EMERGENCY_DISABLED_REASON = "Factory Agent chat is temporarily disabled during incident response."
```

The floating assistant control stays visible, reports a clear diagnostic, and does not open a Factory Agent session. Core app navigation and pages remain usable.

## Clean Environment Recreation

Use fresh artifact directories for seeded, release, and synthetic gates when validating recovery:

```powershell
$env:PLAYWRIGHT_SEEDED_ARTIFACT_DIR = "eMas Front/test-results/operational-gate/recreated-environment/seeded-stack"
$env:PLAYWRIGHT_RELEASE_ARTIFACT_DIR = "eMas Front/test-results/operational-gate/recreated-environment/release-stack"
$env:PLAYWRIGHT_SYNTHETIC_ARTIFACT_DIR = "eMas Front/test-results/operational-gate/recreated-environment/synthetic-monitor"
$env:PLAYWRIGHT_SYNTHETIC_OWNER = "chatbot-oncall"
```

Then rerun release and synthetic gates from scratch:

```powershell
npm run test:e2e:release
npm run test:e2e:synthetic
```

Record any non-automated recovery item as an accepted gap in `TRACK.md` with owner, severity, risk, target date/phase, reason, and temporary workaround.
