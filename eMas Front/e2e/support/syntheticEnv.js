import fs from 'node:fs'
import path from 'node:path'

import { releaseRuntimeEnv } from './releaseEnv.js'

const SECRET_PATTERNS = [
  /(authorization:\s*bearer\s+)[^\s"']+/gi,
  /(bearer\s+)[a-z0-9._~+/=-]{12,}/gi,
  /((?:api[_-]?key|token|secret|password)=)[^&\s"']+/gi,
  /((?:api[_-]?key|token|secret|password)["']?\s*:\s*["'])[^"']+/gi,
]

function requireLiveEnv(name) {
  const value = process.env[name]
  if (!value) throw new Error(`chromium-synthetic live mode requires ${name}`)
  return value
}

function normalizeBaseUrl(value) {
  return String(value || '').replace(/\/+$/, '')
}

export function syntheticArtifactDir(repoRoot = path.resolve(process.cwd(), '..')) {
  return path.resolve(
    process.env.PLAYWRIGHT_SYNTHETIC_ARTIFACT_DIR || path.join(repoRoot, 'eMas Front', 'test-results', 'synthetic-monitor'),
  )
}

export function redactSensitiveText(value) {
  let output = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  for (const pattern of SECRET_PATTERNS) {
    output = output.replace(pattern, '$1<redacted>')
  }
  return output
}

export function syntheticRuntimeEnv(options = {}) {
  const repoRoot = path.resolve(process.cwd(), '..')
  const artifactDir = syntheticArtifactDir(repoRoot)
  const live = process.env.PLAYWRIGHT_SYNTHETIC_LIVE === '1'
  const releaseEnv = releaseRuntimeEnv(repoRoot)
  const mode = live ? 'live' : 'local-release-harness'

  if (live && options.validate) {
    requireLiveEnv('PLAYWRIGHT_SYNTHETIC_BASE_URL')
    requireLiveEnv('PLAYWRIGHT_SYNTHETIC_AUTH_TOKEN')
    requireLiveEnv('PLAYWRIGHT_SYNTHETIC_OWNER')
  }

  const baseUrl = normalizeBaseUrl(live ? process.env.PLAYWRIGHT_SYNTHETIC_BASE_URL : releaseEnv.releaseBaseUrl)
  const resultPath = path.join(artifactDir, 'synthetic-results.json')
  const ndjsonPath = path.join(artifactDir, 'synthetic-results.ndjson')
  const alertPath = path.join(artifactDir, 'synthetic-alerts.ndjson')

  fs.mkdirSync(artifactDir, { recursive: true })

  return {
    repoRoot,
    artifactDir,
    resultPath,
    ndjsonPath,
    alertPath,
    mode,
    live,
    baseUrl,
    owner: process.env.PLAYWRIGHT_SYNTHETIC_OWNER || 'chatbot-oncall',
    runbookUrl:
      process.env.PLAYWRIGHT_SYNTHETIC_RUNBOOK_URL ||
      'docs/operations/chatbot_synthetic_monitoring.md#alert-response-runbook',
    authToken: process.env.PLAYWRIGHT_SYNTHETIC_AUTH_TOKEN || (live ? '' : releaseEnv.bearerToken),
    alertWebhook: process.env.PLAYWRIGHT_SYNTHETIC_ALERT_WEBHOOK || '',
    safePrompts: {
      machineStatus:
        process.env.PLAYWRIGHT_SYNTHETIC_MACHINE_STATUS_PROMPT ||
        'Production synthetic read-only canary: show status for machine M-CNC-01. Do not mutate production data.',
      ragSource:
        process.env.PLAYWRIGHT_SYNTHETIC_RAG_PROMPT ||
        'Production synthetic read-only canary: use LOTO guidance to explain hazardous energy lockout. Do not mutate production data.',
      progress:
        process.env.PLAYWRIGHT_SYNTHETIC_PROGRESS_PROMPT ||
        'Production synthetic read-only canary: run an SSE or polling progress check for machine M-CNC-01. Do not mutate production data.',
      providerOutage:
        process.env.PLAYWRIGHT_SYNTHETIC_PROVIDER_OUTAGE_PROMPT ||
        'Production synthetic read-only provider outage canary for LOTO/RAG dependency. Do not mutate production data.',
    },
    latencyBudgetsMs: {
      chatOpen: Number(process.env.PLAYWRIGHT_SYNTHETIC_CHAT_OPEN_BUDGET_MS || 10_000),
      firstProgress: Number(process.env.PLAYWRIGHT_SYNTHETIC_FIRST_PROGRESS_BUDGET_MS || 20_000),
      finalAnswer: Number(process.env.PLAYWRIGHT_SYNTHETIC_FINAL_ANSWER_BUDGET_MS || 45_000),
      burnRateWarning: Number(process.env.PLAYWRIGHT_SYNTHETIC_BURN_RATE_WARNING_MS || 30_000),
    },
    retention: {
      failureArtifacts: process.env.PLAYWRIGHT_SYNTHETIC_FAILURE_ARTIFACT_RETENTION || '7 days',
      resultHistory: process.env.PLAYWRIGHT_SYNTHETIC_RESULT_RETENTION || '90 days',
    },
    releaseHarness: releaseEnv,
  }
}
