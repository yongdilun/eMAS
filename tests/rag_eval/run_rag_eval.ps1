<#
.SYNOPSIS
  Live RAG evaluation: ingest (optional), then run_eval or pytest against real LLM.

.DESCRIPTION
  Must be run from anywhere; script resolves repo root and sets cwd to repo root.
  Ingestion and vector/BM25 paths are relative to cwd — keep cwd at repo root.

.PARAMETER Ingest
  Run factory_agent.rag.ingestion first (rag_sources/source_register.json).

.PARAMETER Action
  RunEval = python -m tests.rag_eval.run_eval (default)
  Pytest   = pytest factory-agent/tests/test_rag_live_llm.py

.PARAMETER Filter
  Substring filter on case id (passed to run_eval; for Pytest sets FACTORY_AGENT_RAG_EVAL_FILTER).

.PARAMETER RunId
  Optional run id for artifact folder name.

.PARAMETER RetrievalTopN
  Chunks to log per case in retrieval_debug (default 10).

.PARAMETER Variant
  Run 1 variant ID to execute. Phase 2 supports V0, V1, V2, and V3.

.PARAMETER OpenAiBaseUrl
  LLM base URL (default http://127.0.0.1:900/v1).

.PARAMETER OpenAiApiKey
  API key for OpenAI-compatible endpoint (default local).

.PARAMETER PythonExe
  Override Python path; default is factory-agent\.venv\Scripts\python.exe if present.

.PARAMETER NoCleanup
  Do not remove FACTORY_AGENT_LIVE_RAG at exit.

.EXAMPLE
  .\tests\rag_eval\run_rag_eval.ps1 -Ingest

.EXAMPLE
  .\tests\rag_eval\run_rag_eval.ps1 -Filter loto-

.EXAMPLE
  .\tests\rag_eval\run_rag_eval.ps1 -Action Pytest -Filter loto-
#>

param(
  [switch]$Ingest,
  [ValidateSet("RunEval", "Pytest")]
  [string]$Action = "RunEval",
  [string]$Filter = "",
  [string]$RunId = "",
  [int]$RetrievalTopN = 10,
  [ValidateSet("V0", "V1", "V2", "V3", "V4", "V5", "V6", "V7", "V9", "V10", "V11", "V12")]
  [string]$Variant = "V3",
  [string]$OpenAiBaseUrl = "http://127.0.0.1:900/v1",
  [string]$OpenAiApiKey = "local",
  [string]$PythonExe = "",
  [switch]$NoCleanup
)

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptRoot "..\..")).Path

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
  $venvPython = Join-Path $RepoRoot "factory-agent\.venv\Scripts\python.exe"
  if (Test-Path $venvPython) {
    $PythonExe = $venvPython
  }
  else {
    $PythonExe = "python"
  }
}

Push-Location $RepoRoot
try {
  if ($Ingest) {
    Write-Host "==> Ingest (cwd=$RepoRoot)" -ForegroundColor Cyan
    $factoryAgentDir = Join-Path $RepoRoot "factory-agent"
    $prevPyPath = $env:PYTHONPATH
    if ([string]::IsNullOrWhiteSpace($prevPyPath)) {
      $env:PYTHONPATH = $factoryAgentDir
    }
    else {
      $env:PYTHONPATH = "$factoryAgentDir;$prevPyPath"
    }
    try {
      & $PythonExe -m factory_agent.rag.ingestion
      $ingestCode = $LASTEXITCODE
    }
    finally {
      if ($null -eq $prevPyPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
      }
      else {
        $env:PYTHONPATH = $prevPyPath
      }
    }
    if ($ingestCode -ne 0) { exit $ingestCode }
  }

  $env:FACTORY_AGENT_LIVE_RAG = "1"
  $env:OPENAI_BASE_URL = $OpenAiBaseUrl
  $env:OPENAI_API_KEY = $OpenAiApiKey

  if ($Action -eq "RunEval") {
    $runArgs = @("-m", "tests.rag_eval.run_eval")
    if (-not [string]::IsNullOrWhiteSpace($Filter)) {
      $runArgs += "--filter", $Filter
    }
    if (-not [string]::IsNullOrWhiteSpace($RunId)) {
      $runArgs += "--run-id", $RunId
    }
    if ($RetrievalTopN -ne 10) {
      $runArgs += "--retrieval-top-n", "$RetrievalTopN"
    }
    $runArgs += "--variant", $Variant
    Write-Host "==> tests.rag_eval.run_eval $($runArgs -join ' ')" -ForegroundColor Cyan
    & $PythonExe @runArgs
    exit $LASTEXITCODE
  }

  if (-not [string]::IsNullOrWhiteSpace($Filter)) {
    $env:FACTORY_AGENT_RAG_EVAL_FILTER = $Filter
  }
  $env:FACTORY_AGENT_RAG_EVAL_VARIANT = $Variant
  Write-Host "==> pytest test_rag_live_llm.py" -ForegroundColor Cyan
  & $PythonExe -m pytest (Join-Path $RepoRoot "factory-agent\tests\test_rag_live_llm.py") -v
  $code = $LASTEXITCODE
  if (Test-Path Env:FACTORY_AGENT_RAG_EVAL_FILTER) {
    Remove-Item Env:FACTORY_AGENT_RAG_EVAL_FILTER
  }
  if (Test-Path Env:FACTORY_AGENT_RAG_EVAL_VARIANT) {
    Remove-Item Env:FACTORY_AGENT_RAG_EVAL_VARIANT
  }
  exit $code
}
finally {
  Pop-Location
  if (-not $NoCleanup) {
    if (Test-Path Env:FACTORY_AGENT_LIVE_RAG) {
      Remove-Item Env:FACTORY_AGENT_LIVE_RAG
    }
  }
}
