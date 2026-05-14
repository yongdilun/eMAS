# Seed-Based AI Testing Pipeline

This folder contains the shared scenario contract for backend, chatbot, scheduling, approval, and `factory-agent` testing.

## Fast Checks

From repo root:

```powershell
go test ./internal/e2e
pytest factory-agent/tests/test_seed_pipeline_manifest.py
```

The fast checks validate the manifest, seed the canonical data through `internal/seeddata`, verify the seed fingerprint, and exercise the chatbot approval driver.
They also run the reliability edge checks for:

- pause/resume with live instruction update and stale approval rejection
- transient planner/model failure retry with session state preserved
- all-or-nothing transaction bundle rollback
- mixed RAG source metadata plus normal tool output in one agent snapshot

## Seeded Scenario Run

To run the checks and print a readable summary:

```powershell
.\tests\e2e\run_seed_pipeline.ps1
```

Useful options:

```powershell
.\tests\e2e\run_seed_pipeline.ps1 -ShowResponses
.\tests\e2e\run_seed_pipeline.ps1 -AgentApi
.\tests\e2e\run_seed_pipeline.ps1 -LiveAgent
.\tests\e2e\run_seed_pipeline.ps1 -SkipFast -SkipPython -SkipSeeded -AgentApi -AgentScenario factory-simple-read
.\tests\e2e\run_seed_pipeline.ps1 -SkipPython
.\tests\e2e\run_seed_pipeline.ps1 -SkipSeeded
```

`-AgentApi` starts a real seeded Go API server and a real `factory-agent` FastAPI server, then drives the `factory_agent` scenarios over HTTP. `-LiveAgent` also requires the planner path to use the configured LLM backend and fails if the plan falls back to the legacy planner.

The live `factory-agent` matrix is intentionally larger than the backend smoke set:

```text
factory_agent category scenarios: 52
factory_agent HTTP entrypoint scenarios: 55
```

Each live scenario includes `coverage_area`, `complexity`, and `difficulty` metadata. The runner writes grouped pass/fail totals by those fields into `factory-agent-summary.json`, so regressions can be read by capability area instead of only by scenario ID.

From `emas/`:

```powershell
$env:E2E_SEEDED='1'
go test ./internal/e2e -run TestSeedPipelineSeededScenariosOptIn -count=1
```

Artifacts are written to:

```text
test-artifacts/<run-id>/<scenario-id>.json
```

Each artifact records the input contract, HTTP status, response body, and skip/run reason.

Raw command output from the script is saved under:

```text
test-artifacts/logs/seed-pipeline-<run-id>.log
```

## Live LLM Evaluation

The existing Go parser corpus remains CI-safe by default. To use the real parser:

```powershell
$env:LLM_INTEGRATION='1'
go test ./internal/service -run TestAICommandOrchestrator_Fixtures_CISafe -count=1
```

The test logs per-action accuracy and fails below the 95% threshold.

## Live RAG Evaluation

For RAG + router evaluation against the real LLM (with structured per-case
JSON artifacts and manual review placeholders) see
[`tests/rag_eval/README.md`](../rag_eval/README.md). Artifacts land under
`test-artifacts/rag-eval/<run_id>/` and the pytest entrypoint is
[`factory-agent/tests/test_rag_live_llm.py`](../../factory-agent/tests/test_rag_live_llm.py)
(skipped unless `FACTORY_AGENT_LIVE_RAG=1`).

## Optional External Tools

- Testcontainers/MySQL should be used for a future CI job that needs exact MySQL behavior instead of SQLite-compatible handler coverage.
- Promptfoo can consume the same scenario inputs for prompt/rubric regression checks.
- Langfuse can be enabled separately to trace live LLM runs and attach cost/latency/eval metadata.
