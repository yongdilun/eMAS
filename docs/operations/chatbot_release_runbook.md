# Chatbot Release And Rollback Runbook

Owner: release operator / `chatbot-oncall`

Scope: opt-in production-like and operational readiness gates for the Factory Agent chatbot. This does not replace Phase 18-19 prompt/workflow robustness signoff.

## Production-Grade Gate

From `eMas Front`:

```powershell
npm run operational:gate
```

The command runs the Phase 17 matrix:

- frontend unit tests,
- deterministic mocked Chromium PR suite,
- seeded L3 foundation,
- seeded hard orchestration,
- release validation,
- synthetic monitoring,
- security/privacy checks,
- reliability checks.

Use a dry run to print the matrix without executing child checks:

```powershell
npm run operational:gate -- --dry-run
```

GitHub Actions equivalent: manually dispatch `Playwright Operational Readiness`.

## Rollback Validation

Set the previous known-good build URL, then run the release rollback smoke:

```powershell
$env:PLAYWRIGHT_RELEASE_ROLLBACK_BASE_URL = "https://previous-known-good.example.com"
npm run test:e2e -- --project=chromium-release --grep "scenario 68"
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
npm run test:e2e -- --project=chromium-release
npm run test:e2e -- --project=chromium-synthetic
```

Record any non-automated recovery item as an accepted gap in `TRACK.md` with owner, severity, risk, target date/phase, reason, and temporary workaround.
