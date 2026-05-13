param(
  [switch]$SkipFast,
  [switch]$SkipPython,
  [switch]$SkipSeeded,
  [switch]$AgentApi,
  [switch]$LiveAgent,
  [string[]]$AgentScenario = @(),
  [int]$AgentGoPort = 18080,
  [int]$AgentPort = 18081,
  [string]$PythonExe = "",
  [switch]$KeepGoing,
  [switch]$ShowResponses,
  [switch]$SkipRAG
)

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot "..\..")
$EmasRoot = Join-Path $RepoRoot "emas"
$ArtifactRoot = Join-Path $RepoRoot "test-artifacts"
$LogRoot = Join-Path $ArtifactRoot "logs"
$RunStamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$LogPath = Join-Path $LogRoot "seed-pipeline-$RunStamp.log"
$StartedAt = Get-Date
$script:ManagedProcesses = @()
$script:SavedEnv = @{}

if ($LiveAgent) {
  $AgentApi = $true
}

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
  $venvPython = Join-Path $RepoRoot "factory-agent\.venv\Scripts\python.exe"
  if (Test-Path $venvPython) {
    $PythonExe = $venvPython
  } else {
    $PythonExe = "python"
  }
}

New-Item -ItemType Directory -Force -Path $ArtifactRoot, $LogRoot | Out-Null
$script:ExistingArtifactDirs = @{}
Get-ChildItem $ArtifactRoot -Directory |
  Where-Object { $_.Name -ne "logs" } |
  ForEach-Object { $script:ExistingArtifactDirs[$_.FullName] = $true }
$script:LogWriter = [System.IO.StreamWriter]::new($LogPath, $true, [System.Text.UTF8Encoding]::new($false))
$script:LogWriter.AutoFlush = $true

function Add-LogLine {
  param([string]$Value)
  $script:LogWriter.WriteLine($Value)
}

function Set-RunEnv {
  param([string]$Name, [string]$Value)
  if (-not $script:SavedEnv.ContainsKey($Name)) {
    $script:SavedEnv[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
  }
  [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
}

function Restore-RunEnv {
  foreach ($name in $script:SavedEnv.Keys) {
    [Environment]::SetEnvironmentVariable($name, $script:SavedEnv[$name], "Process")
  }
}

function Write-Step {
  param([string]$Message)
  $line = ""
  Write-Host $line
  Add-LogLine $line
  $line = "==> $Message"
  Write-Host $line -ForegroundColor Cyan
  Add-LogLine $line
}

function Invoke-LoggedCommand {
  param(
    [string]$Name,
    [string]$WorkingDirectory,
    [string]$FilePath,
    [string[]]$Arguments
  )

  Write-Step $Name
  Add-LogLine ("cwd: " + $WorkingDirectory)
  Add-LogLine ("cmd: " + $FilePath + " " + ($Arguments -join " "))

  Push-Location $WorkingDirectory
  $oldErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & $FilePath @Arguments 2>&1 | ForEach-Object {
      $text = $_.ToString()
      Write-Host $text
      Add-LogLine $text
    }
    $code = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $oldErrorActionPreference
    Pop-Location
  }

  if ($null -eq $code) {
    $code = 0
  }
  Add-LogLine ("exit_code: " + $code)

  if ($code -ne 0 -and -not $KeepGoing) {
    throw "$Name failed with exit code $code. Full log: $LogPath"
  }
  return [int]$code
}

function Import-AgentLLMEnv {
  $envPath = Join-Path $RepoRoot "factory-agent\.env"
  if (-not (Test-Path $envPath)) {
    return
  }
  $allowed = @{
    "OPENAI_BASE_URL" = $true
    "OPENAI_API_KEY" = $true
    "LLM_BASE_URL" = $true
    "LLM_API_KEY" = $true
    "PLANNER_MODEL" = $true
    "SUMMARY_MODEL" = $true
    "TOOL_RESULT_SUMMARY_MODEL" = $true
    "TOOL_SELECTOR_MODEL" = $true
    "LLM_MODEL" = $true
    "SMALL_LLM_MODEL" = $true
    "AGENT_RUNTIME" = $true
    "PLANNER_BACKEND" = $true
    "PLANNER_FALLBACK_TO_LEGACY" = $true
    "LANGSMITH_TRACING" = $true
    "LANGSMITH_ENDPOINT" = $true
    "LANGSMITH_API_KEY" = $true
    "LANGSMITH_PROJECT" = $true
    "LLM_JSON_TIMEOUT_S" = $true
    "LLM_JSON_MAX_TOKENS" = $true
  }
  Get-Content $envPath | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
      return
    }
    $parts = $line.Split("=", 2)
    $name = $parts[0].Trim()
    if (-not $allowed.ContainsKey($name)) {
      return
    }
    if ([Environment]::GetEnvironmentVariable($name, "Process")) {
      return
    }
    $value = $parts[1].Trim().Trim('"').Trim("'")
    Set-RunEnv $name $value
  }
}

function Wait-HttpHealth {
  param(
    [string]$Url,
    [int]$TimeoutSeconds = 60,
    [System.Diagnostics.Process]$Process = $null
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $lastError = ""
  while ((Get-Date) -lt $deadline) {
    if ($null -ne $Process -and $Process.HasExited) {
      throw "Process exited before $Url became healthy. Last error: $lastError"
    }
    try {
      $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
        return
      }
      $lastError = "status " + $response.StatusCode
    } catch {
      $lastError = $_.Exception.Message
    }
    Start-Sleep -Milliseconds 500
  }
  throw "Timed out waiting for $Url. Last error: $lastError"
}

function Get-PortListeners {
  param([int[]]$Ports)
  $listeners = @()
  foreach ($port in $Ports) {
    $listeners += Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  }
  return @($listeners)
}

function Assert-PortsAvailable {
  param([int[]]$Ports)
  $listeners = @(Get-PortListeners -Ports $Ports)
  if ($listeners.Count -eq 0) {
    return
  }

  $details = $listeners | ForEach-Object {
    $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    $name = if ($proc) { $proc.ProcessName } else { "unknown" }
    "127.0.0.1:$($_.LocalPort) pid=$($_.OwningProcess) process=$name"
  }
  throw "Required e2e port(s) already in use: $($details -join '; '). Stop those processes or choose -AgentGoPort/-AgentPort."
}

function Stop-PortListeners {
  param([int[]]$Ports)
  foreach ($listener in @(Get-PortListeners -Ports $Ports)) {
    $proc = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    $name = if ($proc) { $proc.ProcessName } else { "unknown" }
    Write-Host ("Stopping leftover listener on 127.0.0.1:" + $listener.LocalPort + " (pid " + $listener.OwningProcess + ", " + $name + ")") -ForegroundColor DarkCyan
    try {
      Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    } catch {
    }
  }
}

function Start-ManagedProcess {
  param(
    [string]$Name,
    [string]$WorkingDirectory,
    [string]$FilePath,
    [string[]]$Arguments,
    [int[]]$Ports = @(),
    [string]$StdoutPath,
    [string]$StderrPath
  )
  Write-Step "Starting $Name"
  Add-LogLine ("cwd: " + $WorkingDirectory)
  Add-LogLine ("cmd: " + $FilePath + " " + ($Arguments -join " "))
  Add-LogLine ("stdout: " + $StdoutPath)
  Add-LogLine ("stderr: " + $StderrPath)
  $proc = Start-Process `
    -FilePath $FilePath `
    -ArgumentList $Arguments `
    -WorkingDirectory $WorkingDirectory `
    -RedirectStandardOutput $StdoutPath `
    -RedirectStandardError $StderrPath `
    -WindowStyle Hidden `
    -PassThru
  $script:ManagedProcesses += [pscustomobject]@{
    Name = $Name
    Process = $proc
    Ports = $Ports
    StdoutPath = $StdoutPath
    StderrPath = $StderrPath
  }
  return $proc
}

function Stop-ManagedProcesses {
  foreach ($entry in @($script:ManagedProcesses | Sort-Object { $_.Process.StartTime } -Descending)) {
    $proc = $entry.Process
    if ($null -ne $proc -and -not $proc.HasExited) {
      Write-Host ("Stopping " + $entry.Name + " (pid " + $proc.Id + ")") -ForegroundColor DarkCyan
      try {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
      } catch {
      }
    }
    if ($entry.Ports -and $entry.Ports.Count -gt 0) {
      Stop-PortListeners -Ports $entry.Ports
    }
    foreach ($path in @($entry.StdoutPath, $entry.StderrPath)) {
      if (Test-Path $path) {
        Add-LogLine ""
        Add-LogLine ("----- " + $entry.Name + " log: " + $path + " -----")
        Get-Content $path -Tail 200 | ForEach-Object { Add-LogLine $_ }
      }
    }
  }
}

function Get-NewArtifactDirs {
  Get-ChildItem $ArtifactRoot -Directory |
    Where-Object { $_.Name -ne "logs" -and -not $script:ExistingArtifactDirs.ContainsKey($_.FullName) } |
    Sort-Object LastWriteTime
}

function Get-ScenarioCount {
  $manifestPath = Join-Path $RepoRoot "tests\e2e\scenarios\seed_pipeline.json"
  if (Test-Path $manifestPath) {
    return @((Get-Content $manifestPath -Raw | ConvertFrom-Json)).Count
  }
  return 0
}

function Show-ArtifactSummary {
  $dirs = @(Get-NewArtifactDirs)
  if ($dirs.Count -eq 0) {
    Write-Host ""
    Write-Host "No new artifact directory was found for this run." -ForegroundColor Yellow
    return
  }

  Write-Host ""
  Write-Host "Artifact folders:" -ForegroundColor Cyan
  foreach ($dir in $dirs) {
    Write-Host ("  " + $dir.FullName)
  }

  $rows = @()
  foreach ($dir in $dirs) {
    foreach ($file in Get-ChildItem $dir.FullName -Filter "*.json" -File) {
      try {
        $json = Get-Content $file.FullName -Raw | ConvertFrom-Json
        if ($null -eq $json.scenario -or $null -eq $json.result) {
          continue
        }
        $status = $json.result.status
        if ([string]::IsNullOrWhiteSpace($status) -and $json.result.passed -eq $true) {
          $status = "passed"
        }
        if ([string]::IsNullOrWhiteSpace($status)) {
          $status = "unknown"
        }
        $rows += [pscustomobject]@{
          File       = $file.Name
          Scenario   = $json.scenario.id
          Category   = $json.scenario.category
          Entrypoint = $json.scenario.entrypoint
          Status     = $status
          HttpStatus = $json.result.http_status
          Passed     = $json.result.passed
          Response   = $json.result.response_body
        }
      } catch {
        $rows += [pscustomobject]@{
          File       = $file.Name
          Scenario   = ""
          Category   = ""
          Entrypoint = ""
          Status     = "invalid_json"
          HttpStatus = ""
          Passed     = $false
          Response   = $_.Exception.Message
        }
      }
    }
  }

  if ($rows.Count -eq 0) {
    Write-Host "No JSON artifacts found." -ForegroundColor Yellow
    return
  }

  $ran = @($rows | Where-Object { $_.Status -eq "ran" }).Count
  $passed = @($rows | Where-Object { $_.Status -eq "passed" -or $_.Passed -eq $true }).Count
  $skipped = @($rows | Where-Object { $_.Status -eq "skipped" }).Count
  $other = @($rows | Where-Object { $_.Status -notin @("ran", "passed", "skipped") -and $_.Passed -ne $true }).Count

  Write-Host ""
  Write-Host "Result summary:" -ForegroundColor Cyan
  Write-Host ("  Manifest scenarios: " + (Get-ScenarioCount))
  Write-Host ("  Artifact files:      " + $rows.Count)
  Write-Host ("  Ran HTTP scenarios:  " + $ran)
  Write-Host ("  Approval proofs:     " + $passed)
  Write-Host ("  Skipped contracts:   " + $skipped)
  Write-Host ("  Other/needs check:   " + $other)

  Write-Host ""
  Write-Host "Scenario table:" -ForegroundColor Cyan
  $rows |
    Sort-Object Category, Scenario, File |
    Select-Object Scenario, Category, Entrypoint, Status, HttpStatus |
    Format-Table -AutoSize

  if ($ShowResponses) {
    Write-Host ""
    Write-Host "Response bodies:" -ForegroundColor Cyan
    foreach ($row in $rows | Where-Object { -not [string]::IsNullOrWhiteSpace($_.Response) }) {
      Write-Host ""
      Write-Host ("[" + $row.Scenario + "] " + $row.File) -ForegroundColor Yellow
      Write-Host $row.Response
    }
  }
}

$exitCodes = @()

try {
  Write-Host "Seed pipeline run: $RunStamp" -ForegroundColor Green
  Write-Host "Log: $LogPath"

  # Ensure Python can find the factory_agent package even if run from the root
  $env:PYTHONPATH = "$RepoRoot\factory-agent;$env:PYTHONPATH"

  if (-not $SkipFast) {
    $exitCodes += Invoke-LoggedCommand `
      -Name "Go fast e2e checks and approval driver" `
      -WorkingDirectory $EmasRoot `
      -FilePath "go" `
      -Arguments @("test", "./internal/e2e", "-count=1", "-v")
  }

  if (-not $SkipPython) {
    $oldPythonWarnings = $env:PYTHONWARNINGS
    $oldPytestDisablePluginAutoload = $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD
    $env:PYTHONWARNINGS = "ignore"
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
    try {
      $exitCodes += Invoke-LoggedCommand `
        -Name "Python manifest contract checks" `
        -WorkingDirectory $RepoRoot `
        -FilePath $PythonExe `
        -Arguments @("-m", "pytest", "factory-agent/tests/test_seed_pipeline_manifest.py", "-q")
    } finally {
      if ($null -eq $oldPythonWarnings) {
        Remove-Item Env:PYTHONWARNINGS -ErrorAction SilentlyContinue
      } else {
        $env:PYTHONWARNINGS = $oldPythonWarnings
      }
      if ($null -eq $oldPytestDisablePluginAutoload) {
        Remove-Item Env:PYTEST_DISABLE_PLUGIN_AUTOLOAD -ErrorAction SilentlyContinue
      } else {
        $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = $oldPytestDisablePluginAutoload
      }
    }
  }

  if (-not $SkipSeeded) {
    $oldE2E = $env:E2E_SEEDED
    $env:E2E_SEEDED = "1"
    try {
      $exitCodes += Invoke-LoggedCommand `
        -Name "Full seeded scenario suite" `
        -WorkingDirectory $EmasRoot `
        -FilePath "go" `
        -Arguments @("test", "./internal/e2e", "-run", "TestSeedPipelineSeededScenariosOptIn", "-count=1", "-v")
    } finally {
      if ($null -eq $oldE2E) {
        Remove-Item Env:E2E_SEEDED -ErrorAction SilentlyContinue
      } else {
        $env:E2E_SEEDED = $oldE2E
      }
    }
  }

  if ($AgentApi) {
    Import-AgentLLMEnv
    $agentArtifactDir = Join-Path $ArtifactRoot ($RunStamp + "-factory-agent")
    New-Item -ItemType Directory -Force -Path $agentArtifactDir | Out-Null
    $goApiBase = "http://127.0.0.1:$AgentGoPort"
    $agentBase = "http://127.0.0.1:$AgentPort"
    $agentWorkDir = Join-Path ([System.IO.Path]::GetTempPath()) ("emas-seed-pipeline\" + $RunStamp)
    New-Item -ItemType Directory -Force -Path $agentWorkDir | Out-Null
    Add-LogLine ("agent work dir: " + $agentWorkDir)
    $sqlitePath = (Join-Path $agentWorkDir "factory_agent.db").Replace("\", "/")
    $goSqlitePath = (Join-Path $agentWorkDir "go_seeded_api.db").Replace("\", "/")

    if (-not $SkipRAG) {
        $ragIngestionScript = Join-Path $RepoRoot "factory-agent\factory_agent\rag\ingestion.py"
        $registerPath = Join-Path $RepoRoot "rag_sources\00_metadata_templates\source_register.json"
        if (Test-Path $ragIngestionScript) {
            Invoke-LoggedCommand `
                -Name "RAG Knowledge Ingestion" `
                -WorkingDirectory $RepoRoot `
                -FilePath $PythonExe `
                -Arguments @($ragIngestionScript, "--register", $registerPath)
        }
    }

    Assert-PortsAvailable -Ports @($AgentGoPort, $AgentPort)

    Set-RunEnv "E2E_SERVER_ADDR" ("127.0.0.1:" + $AgentGoPort)
    Set-RunEnv "E2E_SQLITE_PATH" $goSqlitePath
    $goProc = Start-ManagedProcess `
      -Name "seeded Go API" `
      -WorkingDirectory $EmasRoot `
      -FilePath "go" `
      -Arguments @("run", "./cmd/e2e_server") `
      -Ports @($AgentGoPort) `
      -StdoutPath (Join-Path $LogRoot "seeded-go-api-$RunStamp.out.log") `
      -StderrPath (Join-Path $LogRoot "seeded-go-api-$RunStamp.err.log")
    Wait-HttpHealth -Url ($goApiBase + "/health") -TimeoutSeconds 90 -Process $goProc

    Set-RunEnv "DATABASE_URL" ("sqlite+aiosqlite:///" + $sqlitePath)
    Set-RunEnv "REDIS_URL" ""
    Set-RunEnv "GO_API_BASE_URL" ($goApiBase + "/api/v1")
    Set-RunEnv "OPENAPI_URL" ($goApiBase + "/swagger/doc.json")
    Set-RunEnv "OPENAPI_LOCAL" "1"
    Set-RunEnv "ADMIN_API_KEY" "seed-pipeline-admin"
    Set-RunEnv "JWT_REQUIRED" "0"
    Set-RunEnv "MAX_CONCURRENT" "0"
    Set-RunEnv "HTTP_TIMEOUT_S" "45"
    Set-RunEnv "GRAPH_CHECKPOINT_BACKEND" "auto"
    Set-RunEnv "ENFORCE_TOOL_REGISTRY_HEALTH" "1"
    Set-RunEnv "AUTO_REPAIR_TOOL_REGISTRY" "1"
    if ($LiveAgent) {
      Set-RunEnv "AGENT_RUNTIME" "langgraph_agent"
      Set-RunEnv "PLANNER_BACKEND" "langgraph"
      Set-RunEnv "PLANNER_FALLBACK_TO_LEGACY" "0"
      Set-RunEnv "TOOL_SELECTOR_BACKEND" "langchain"
      Set-RunEnv "SUMMARY_BACKEND" "langchain"
      Set-RunEnv "TOOL_RESULT_SUMMARY_BACKEND" "langchain"
      if (-not ([Environment]::GetEnvironmentVariable("OPENAI_BASE_URL", "Process") -or [Environment]::GetEnvironmentVariable("OPENAI_API_KEY", "Process"))) {
        throw "-LiveAgent requires OPENAI_BASE_URL or OPENAI_API_KEY. Put it in factory-agent/.env or set it in this shell."
      }
    }

    $agentProc = Start-ManagedProcess `
      -Name "factory-agent API" `
      -WorkingDirectory (Join-Path $RepoRoot "factory-agent") `
      -FilePath $PythonExe `
      -Arguments @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", [string]$AgentPort) `
      -Ports @($AgentPort) `
      -StdoutPath (Join-Path $LogRoot "factory-agent-api-$RunStamp.out.log") `
      -StderrPath (Join-Path $LogRoot "factory-agent-api-$RunStamp.err.log")
    Wait-HttpHealth -Url ($agentBase + "/health") -TimeoutSeconds 90 -Process $agentProc

    $agentArgs = @(
      "tests/e2e/run_factory_agent_api.py",
      "--base-url", $agentBase,
      "--scenarios", "tests/e2e/scenarios/seed_pipeline.json",
      "--artifact-dir", $agentArtifactDir
    )
    foreach ($scenario in $AgentScenario) {
      $agentArgs += @("--scenario", $scenario)
    }
    if ($LiveAgent) {
      $agentArgs += "--require-llm"
    }
    $exitCodes += Invoke-LoggedCommand `
      -Name "Real factory-agent API scenarios" `
      -WorkingDirectory $RepoRoot `
      -FilePath $PythonExe `
      -Arguments $agentArgs
  }
} finally {
  Stop-ManagedProcesses
  Restore-RunEnv
  Show-ArtifactSummary
  Write-Host ""
  Write-Host "Important log saved to: $LogPath" -ForegroundColor Green
  if ($null -ne $script:LogWriter) {
    $script:LogWriter.Dispose()
  }
}

if (@($exitCodes | Where-Object { $_ -ne 0 }).Count -gt 0) {
  exit 1
}
exit 0
