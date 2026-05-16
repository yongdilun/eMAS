import fs from 'node:fs'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const frontendRoot = path.resolve(__dirname, '..', '..')
const repoRoot = path.resolve(frontendRoot, '..')
const defaultArtifactDir = path.join(frontendRoot, 'test-results', 'operational-gate')

export const gateSeverityRules = {
  critical: {
    blocks_release: true,
    blocks_operational_signoff: true,
    accepted_gap_allowed: false,
    examples: ['production synthetic outage', 'rollback validation failure', 'environment cannot be recreated'],
  },
  high: {
    blocks_release: false,
    blocks_operational_signoff: true,
    accepted_gap_allowed: false,
    examples: ['missing alert owner', 'missing runbook', 'emergency disable path unavailable'],
  },
  medium: {
    blocks_release: false,
    blocks_operational_signoff: false,
    accepted_gap_allowed: true,
    examples: ['non-blocking operational evidence gap with owner and target date'],
  },
  low: {
    blocks_release: false,
    blocks_operational_signoff: false,
    accepted_gap_allowed: true,
    examples: ['documentation cleanup or non-blocking evidence improvement'],
  },
}

export function alertRunbookUrlForCode() {
  return 'docs/operations/chatbot_synthetic_monitoring.md#alert-response-runbook'
}

export function runbookPathForUrl(runbookUrl, root = repoRoot) {
  if (/^https?:\/\//i.test(String(runbookUrl || ''))) return null
  const relativePath = String(runbookUrl || '').split('#')[0]
  if (!relativePath) return null
  return path.resolve(root, relativePath)
}

export function validateAlertContract(alert, options = {}) {
  const issues = []
  const expectedOwner = options.owner
  const runbookPath = runbookPathForUrl(alert?.runbook_url, options.repoRoot || repoRoot)

  if (!alert?.code) issues.push('Alert code is required.')
  if (!alert?.message) issues.push('Alert message is required.')
  if (!alert?.owner) issues.push('Alert owner is required.')
  if (expectedOwner && alert?.owner !== expectedOwner) {
    issues.push(`Alert owner must be ${expectedOwner}.`)
  }
  if (!gateSeverityRules[String(alert?.severity || '').toLowerCase()]) {
    issues.push('Alert severity must be one of critical, high, medium, or low.')
  }
  if (!alert?.runbook_url) {
    issues.push('Alert runbook_url is required.')
  } else if (runbookPath && !fs.existsSync(runbookPath)) {
    issues.push(`Alert runbook path does not exist: ${runbookPath}`)
  }

  return { ok: issues.length === 0, issues, runbookPath }
}

export function rollbackValidationCommand({ rollbackBaseUrl = '$env:PLAYWRIGHT_RELEASE_ROLLBACK_BASE_URL' } = {}) {
  return {
    label: 'rollback-known-good-release',
    severityOnFailure: 'critical',
    env: {
      PLAYWRIGHT_RELEASE_ROLLBACK_BASE_URL: rollbackBaseUrl,
    },
    command: 'npm run test:e2e -- --project=chromium-release --grep "scenario 68"',
    args: ['run', 'test:e2e', '--', '--project=chromium-release', '--grep', 'scenario 68'],
  }
}

export async function validateRollbackUrl({ baseUrl, fetchImpl = fetch } = {}) {
  if (!baseUrl) throw new Error('rollback baseUrl is required')
  const precheckUrl = new URL('/__release/precheck', baseUrl)
  const response = await fetchImpl(precheckUrl)
  const text = await response.text()
  let body = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = text
  }

  return {
    ok: response.ok,
    status: response.status,
    precheck_url: precheckUrl.toString(),
    body,
  }
}

function childOutputArgs(artifactDir, label) {
  return ['--output', path.join(artifactDir, 'child-results', label), '--reporter=list']
}

function npmArgsForPlaywright(playwrightArgs) {
  return ['run', 'test:e2e', '--', ...playwrightArgs]
}

export function operationalGateMatrix(options = {}) {
  const artifactDir = options.artifactDir || defaultArtifactDir
  return [
    {
      label: 'pr-unit',
      category: 'pr',
      severityOnFailure: 'critical',
      args: ['test'],
      timeoutMs: 120_000,
    },
    {
      label: 'pr-backend-oracles',
      category: 'pr',
      severityOnFailure: 'critical',
      args: ['run', 'test:backend-oracles'],
      timeoutMs: 120_000,
    },
    {
      label: 'pr-mocked-chromium',
      category: 'pr',
      severityOnFailure: 'critical',
      args: npmArgsForPlaywright(['--project=chromium', ...childOutputArgs(artifactDir, 'pr-mocked-chromium')]),
      timeoutMs: 180_000,
    },
    {
      label: 'seeded-foundation',
      category: 'seeded',
      severityOnFailure: 'critical',
      args: npmArgsForPlaywright([
        '--project=chromium-seeded',
        '--grep',
        '@l3-foundation',
        ...childOutputArgs(artifactDir, 'seeded-foundation'),
      ]),
      timeoutMs: 240_000,
    },
    {
      label: 'seeded-hard-orchestration',
      category: 'hard',
      severityOnFailure: 'critical',
      args: npmArgsForPlaywright([
        '--project=chromium-seeded',
        '--grep',
        '@l3-hard',
        ...childOutputArgs(artifactDir, 'seeded-hard-orchestration'),
      ]),
      timeoutMs: 300_000,
    },
    {
      label: 'seeded-stateful-oracles',
      category: 'seeded',
      severityOnFailure: 'critical',
      args: npmArgsForPlaywright([
        '--project=chromium-seeded',
        '--grep',
        '@data-integrity|@prompt-regression|@sse',
        ...childOutputArgs(artifactDir, 'seeded-stateful-oracles'),
      ]),
      timeoutMs: 420_000,
    },
    {
      label: 'real-langgraph-critical',
      category: 'real-langgraph',
      severityOnFailure: 'critical',
      args: npmArgsForPlaywright([
        '--project=chromium-real-langgraph',
        '--grep',
        '@critical',
        ...childOutputArgs(artifactDir, 'real-langgraph-critical'),
      ]),
      timeoutMs: 420_000,
    },
    {
      label: 'release-validation',
      category: 'release',
      severityOnFailure: 'critical',
      args: npmArgsForPlaywright(['--project=chromium-release', ...childOutputArgs(artifactDir, 'release-validation')]),
      timeoutMs: 420_000,
    },
    {
      label: 'synthetic-monitoring',
      category: 'synthetic',
      severityOnFailure: 'critical',
      args: npmArgsForPlaywright(['--project=chromium-synthetic', ...childOutputArgs(artifactDir, 'synthetic-monitoring')]),
      timeoutMs: 420_000,
    },
    {
      label: 'security-privacy-mocked',
      category: 'security/privacy',
      severityOnFailure: 'high',
      args: npmArgsForPlaywright([
        '--project=chromium',
        '--grep',
        '@security|@privacy',
        ...childOutputArgs(artifactDir, 'security-privacy-mocked'),
      ]),
      timeoutMs: 240_000,
    },
    {
      label: 'reliability-mocked',
      category: 'reliability',
      severityOnFailure: 'high',
      args: npmArgsForPlaywright([
        '--project=chromium',
        '--grep',
        '@reliability',
        ...childOutputArgs(artifactDir, 'reliability-mocked'),
      ]),
      timeoutMs: 420_000,
    },
    {
      label: 'reliability-seeded',
      category: 'reliability',
      severityOnFailure: 'high',
      args: npmArgsForPlaywright([
        '--project=chromium-seeded',
        '--grep',
        '@reliability',
        ...childOutputArgs(artifactDir, 'reliability-seeded'),
      ]),
      timeoutMs: 300_000,
    },
  ]
}

export function parseAcceptedGapsFromMarkdown(markdown) {
  const rows = []
  const lines = String(markdown || '').split(/\r?\n/)
  const headerIndex = lines.findIndex((line) => /^\|\s*ID\s*\|\s*Manual check\s*\|/.test(line))
  if (headerIndex < 0) return rows

  for (const line of lines.slice(headerIndex + 2)) {
    if (!line.startsWith('|')) break
    const cells = line
      .split('|')
      .slice(1, -1)
      .map((cell) => cell.trim())
    if (cells.length < 9 || !cells[0]) continue
    rows.push({
      id: cells[0],
      manual_check: cells[1],
      disposition: cells[2],
      owner: cells[3],
      severity: cells[4],
      risk: cells[5],
      target: cells[6],
      reason: cells[7],
      temporary_workaround: cells[8],
    })
  }
  return rows
}

export function validateAcceptedGaps(gaps) {
  const invalid = []
  const blocking = []
  for (const gap of gaps || []) {
    const missing = ['owner', 'severity', 'risk', 'target', 'reason', 'temporary_workaround'].filter(
      (field) => !String(gap?.[field] || '').trim(),
    )
    const severity = String(gap?.severity || '').trim().toLowerCase()
    if (missing.length) invalid.push({ id: gap.id, missing })
    if (['critical', 'high'].includes(severity)) blocking.push(gap)
    if (severity && !gateSeverityRules[severity]) invalid.push({ id: gap.id, invalid_severity: gap.severity })
  }
  return { invalid, blocking }
}

export function evaluateGateResults(results, options = {}) {
  const acceptedGapReview = validateAcceptedGaps(options.acceptedGaps || [])
  const failed = (results || []).filter((result) => result.exit_code !== 0 || result.timed_out || result.error)
  const bySeverity = (severity) =>
    failed.filter((result) => String(result.severityOnFailure || 'critical').toLowerCase() === severity)
  const criticalFailures = bySeverity('critical')
  const highFailures = bySeverity('high')

  return {
    kind: 'phase17-operational-gate-summary',
    passed: criticalFailures.length === 0 && highFailures.length === 0 && acceptedGapReview.blocking.length === 0 && acceptedGapReview.invalid.length === 0,
    total: (results || []).length,
    failed,
    critical_failures: criticalFailures,
    high_failures: highFailures,
    accepted_gap_review: acceptedGapReview,
  }
}

export function environmentRecreationPlan(options = {}) {
  const artifactRoot = path.resolve(options.artifactRoot || path.join(defaultArtifactDir, 'recreated-environment'))
  const syntheticOwner = options.syntheticOwner || 'chatbot-oncall'
  return {
    artifactRoot,
    seeded: {
      env: {
        PLAYWRIGHT_SEEDED_ARTIFACT_DIR: path.join(artifactRoot, 'seeded-stack'),
      },
      command: 'npm run test:e2e -- --project=chromium-seeded --grep "@l3-foundation|@l3-hard"',
    },
    release: {
      env: {
        PLAYWRIGHT_RELEASE_ARTIFACT_DIR: path.join(artifactRoot, 'release-stack'),
        PLAYWRIGHT_RELEASE_ROLLBACK_BASE_URL: options.rollbackBaseUrl || 'http://previous-known-good-build.example.invalid',
      },
      command: 'npm run test:e2e -- --project=chromium-release',
    },
    synthetic: {
      env: {
        PLAYWRIGHT_SYNTHETIC_ARTIFACT_DIR: path.join(artifactRoot, 'synthetic-monitor'),
        PLAYWRIGHT_SYNTHETIC_OWNER: syntheticOwner,
      },
      command: 'npm run test:e2e -- --project=chromium-synthetic',
    },
  }
}

export function prepareEnvironmentRecreationArtifacts(plan) {
  const root = path.resolve(plan.artifactRoot)
  fs.rmSync(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 })
  for (const section of ['seeded', 'release', 'synthetic']) {
    for (const value of Object.values(plan[section]?.env || {})) {
      if (String(value).includes(root)) fs.mkdirSync(value, { recursive: true })
    }
  }
  return root
}

export function validateEnvironmentRecreationPlan(plan) {
  const issues = []
  const requiredSections = ['seeded', 'release', 'synthetic']
  for (const section of requiredSections) {
    if (!plan?.[section]?.command) issues.push(`${section} command is required.`)
    if (!plan?.[section]?.env || Object.keys(plan[section].env).length === 0) {
      issues.push(`${section} environment overrides are required.`)
    }
  }
  if (!plan?.synthetic?.env?.PLAYWRIGHT_SYNTHETIC_OWNER) {
    issues.push('Synthetic account owner is required.')
  }
  if (!String(plan?.release?.env?.PLAYWRIGHT_RELEASE_ROLLBACK_BASE_URL || '').trim()) {
    issues.push('Rollback URL support is required.')
  }
  return { ok: issues.length === 0, issues }
}

function npmInvocation(args) {
  const npmCli =
    process.env.npm_execpath ||
    path.join(path.dirname(process.execPath), 'node_modules', 'npm', 'bin', 'npm-cli.js')
  return [process.execPath, [npmCli, ...args]]
}

function tail(value, max = 12_000) {
  const text = String(value || '')
  return text.length > max ? text.slice(text.length - max) : text
}

function displayArg(arg) {
  const text = String(arg)
  if (!/[\s|&;<>()"]/u.test(text)) return text
  return `"${text.replaceAll('"', '\\"')}"`
}

async function runCommand(command) {
  const [cmd, args] = npmInvocation(command.args)
  const startedAt = Date.now()
  let stdout = ''
  let stderr = ''
  let timedOut = false

  const child = spawn(cmd, args, {
    cwd: frontendRoot,
    env: { ...process.env, ...(command.env || {}) },
    shell: false,
    windowsHide: true,
  })

  const timeout = setTimeout(() => {
    timedOut = true
    if (process.platform === 'win32' && child.pid) {
      spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true })
      return
    }
    child.kill('SIGTERM')
  }, command.timeoutMs)

  child.stdout.on('data', (chunk) => {
    stdout += chunk.toString()
  })
  child.stderr.on('data', (chunk) => {
    stderr += chunk.toString()
  })

  const exit = await new Promise((resolve) => {
    child.on('exit', (code, signal) => resolve({ code, signal }))
    child.on('error', (error) => resolve({ code: null, signal: null, error }))
  })
  clearTimeout(timeout)

  return {
    label: command.label,
    category: command.category,
    severityOnFailure: command.severityOnFailure,
    duration_ms: Date.now() - startedAt,
    exit_code: exit.code,
    signal: exit.signal,
    timed_out: timedOut,
    error: exit.error?.message,
    stdout_tail: tail(stdout),
    stderr_tail: tail(stderr),
  }
}

export async function runOperationalGate(options = {}) {
  const artifactDir = path.resolve(options.artifactDir || defaultArtifactDir)
  fs.mkdirSync(artifactDir, { recursive: true })
  const matrix = operationalGateMatrix({ artifactDir })

  if (options.dryRun) {
    return {
      kind: 'phase17-operational-gate-plan',
      artifact_dir: artifactDir,
      commands: matrix.map(({ label, category, severityOnFailure, args, timeoutMs }) => ({
        label,
        category,
        severityOnFailure,
        command: `npm ${args.map(displayArg).join(' ')}`,
        timeoutMs,
      })),
    }
  }

  const results = []
  for (const command of matrix) {
    results.push(await runCommand(command))
  }

  const trackerPath = path.join(repoRoot, 'TRACK.md')
  const acceptedGaps = fs.existsSync(trackerPath)
    ? parseAcceptedGapsFromMarkdown(fs.readFileSync(trackerPath, 'utf8'))
    : []
  const summary = evaluateGateResults(results, { acceptedGaps })
  const output = {
    ...summary,
    artifact_dir: artifactDir,
    completed_at: new Date().toISOString(),
    results,
  }
  fs.writeFileSync(path.join(artifactDir, 'operational-gate-results.json'), JSON.stringify(output, null, 2))
  return output
}

function argValue(name, fallback = null) {
  const index = process.argv.indexOf(name)
  if (index >= 0 && process.argv[index + 1]) return process.argv[index + 1]
  const inline = process.argv.find((arg) => arg.startsWith(`${name}=`))
  return inline ? inline.slice(name.length + 1) : fallback
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  runOperationalGate({
    dryRun: process.argv.includes('--dry-run'),
    artifactDir: argValue('--artifact-dir', defaultArtifactDir),
  })
    .then((summary) => {
      console.log(JSON.stringify(summary, null, 2))
      process.exit(summary.passed === false ? 1 : 0)
    })
    .catch((err) => {
      console.error(err?.stack || err)
      process.exit(1)
    })
}
