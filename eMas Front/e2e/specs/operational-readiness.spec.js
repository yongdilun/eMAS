import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'

import { expect, test } from '@playwright/test'

import { chatSelectors } from '../fixtures/selectors.js'
import {
  alertRunbookUrlForCode,
  environmentRecreationPlan,
  evaluateGateResults,
  gateSeverityRules,
  operationalGateMatrix,
  parseAcceptedGapsFromMarkdown,
  prepareEnvironmentRecreationArtifacts,
  rollbackValidationCommand,
  validateAlertContract,
  validateEnvironmentRecreationPlan,
  validateRollbackUrl,
} from '../support/operationalGate.js'
import { classifySyntheticSignal } from '../support/syntheticReporter.js'

const repoRoot = path.resolve(process.cwd(), '..')

function listen(server) {
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      resolve(`http://127.0.0.1:${address.port}`)
    })
  })
}

test.describe('Phase 17 production-grade operational readiness @operational', () => {
  test('scenario 101: synthetic failure creates expected alert, owner, severity, and runbook link', async () => {
    const alerts = classifySyntheticSignal({
      timeout: true,
      backendUnavailable: true,
      owner: 'chatbot-oncall',
      runbookUrl: alertRunbookUrlForCode('synthetic_timeout'),
    })
    const timeoutAlert = alerts.find((alert) => alert.code === 'synthetic_timeout')

    expect(timeoutAlert).toMatchObject({
      owner: 'chatbot-oncall',
      severity: 'critical',
      runbook_url: 'docs/operations/chatbot_synthetic_monitoring.md#alert-response-runbook',
    })
    expect(gateSeverityRules.critical.blocks_release).toBe(true)
    expect(gateSeverityRules.critical.blocks_operational_signoff).toBe(true)

    const validation = validateAlertContract(timeoutAlert, { owner: 'chatbot-oncall', repoRoot })
    expect(validation.issues).toEqual([])
    expect(fs.existsSync(validation.runbookPath)).toBe(true)
  })

  test('scenario 102: rollback validation command passes against previous known-good build URL', async () => {
    const server = http.createServer((req, res) => {
      if (req.url === '/__release/precheck') {
        res.writeHead(200, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ ok: true, code: 'ok', message: 'Release precheck passed.' }))
        return
      }
      res.writeHead(404, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ ok: false }))
    })

    const baseUrl = await listen(server)
    try {
      const result = await validateRollbackUrl({ baseUrl })
      expect(result).toMatchObject({
        ok: true,
        status: 200,
      })
      expect(result.body.message).toBe('Release precheck passed.')

      const command = rollbackValidationCommand({ rollbackBaseUrl: baseUrl })
      expect(command.env.PLAYWRIGHT_RELEASE_ROLLBACK_BASE_URL).toBe(baseUrl)
      expect(command.command).toContain('--project=chromium-release')
      expect(command.command).toContain('scenario 68')
      expect(command.severityOnFailure).toBe('critical')
    } finally {
      await new Promise((resolve) => server.close(resolve))
    }
  })

  test('scenario 103: emergency disable path leaves the rest of the app usable with a clear diagnostic', async ({ page }) => {
    const factoryAgentRequests = []
    page.on('request', (request) => {
      if (request.url().includes('/sessions')) factoryAgentRequests.push(request.url())
    })

    await page.goto('/')
    await expect(page.getByText('Dashboard Overview')).toBeVisible()

    const openAssistant = page.getByRole('button', { name: chatSelectors.openAssistantButtonName })
    await expect(openAssistant).toHaveAttribute('data-emergency-disabled', 'true')
    await openAssistant.click()
    await expect(page.getByRole('status').filter({ hasText: 'AI Assistant disabled' })).toBeVisible()
    await expect(page.getByText(/emergency feature flag/i)).toBeVisible()
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toHaveCount(0)
    expect(factoryAgentRequests).toEqual([])

    await page.getByRole('link', { name: 'Reports' }).click()
    await expect(page).toHaveURL(/\/reports$/)
    await expect(page.getByRole('button', { name: chatSelectors.openAssistantButtonName })).toBeVisible()
  })

  test('scenario 104: recreated seeded environment and synthetic account can run release/synthetic gates from scratch', async ({}, testInfo) => {
    const plan = environmentRecreationPlan({
      artifactRoot: testInfo.outputPath('phase17-recreated-environment'),
      rollbackBaseUrl: 'http://previous-known-good-build.example.invalid',
      syntheticOwner: 'chatbot-oncall',
    })
    const root = prepareEnvironmentRecreationArtifacts(plan)
    const validation = validateEnvironmentRecreationPlan(plan)

    await testInfo.attach('phase17-environment-recreation-plan.json', {
      body: JSON.stringify(plan, null, 2),
      contentType: 'application/json',
    })

    expect(validation.issues).toEqual([])
    expect(fs.existsSync(root)).toBe(true)
    expect(plan.seeded.command).toContain('chromium-seeded')
    expect(plan.release.command).toContain('chromium-release')
    expect(plan.synthetic.command).toContain('chromium-synthetic')
    expect(plan.synthetic.env.PLAYWRIGHT_SYNTHETIC_OWNER).toBe('chatbot-oncall')
    expect(plan.release.env.PLAYWRIGHT_RELEASE_ROLLBACK_BASE_URL).toContain('previous-known-good-build')
  })

  test('scenario 105: production-grade gate matrix covers all required checks with no critical failures', async ({}, testInfo) => {
    const matrix = operationalGateMatrix({ artifactDir: testInfo.outputPath('phase17-gate-matrix') })
    const categories = new Set(matrix.map((entry) => entry.category))

    expect(categories).toEqual(
      new Set(['pr', 'seeded', 'hard', 'release', 'synthetic', 'security/privacy', 'reliability']),
    )
    expect(matrix.some((entry) => entry.args.includes('--project=chromium'))).toBe(true)
    expect(matrix.some((entry) => entry.args.includes('--project=chromium-seeded'))).toBe(true)
    expect(matrix.some((entry) => entry.args.includes('--project=chromium-release'))).toBe(true)
    expect(matrix.some((entry) => entry.args.includes('--project=chromium-synthetic'))).toBe(true)
    expect(matrix.every((entry) => gateSeverityRules[entry.severityOnFailure])).toBe(true)

    const tracker = fs.readFileSync(path.join(repoRoot, 'TRACK.md'), 'utf8')
    const acceptedGaps = parseAcceptedGapsFromMarkdown(tracker)
    const passingResults = matrix.map((entry) => ({
      label: entry.label,
      category: entry.category,
      severityOnFailure: entry.severityOnFailure,
      exit_code: 0,
      timed_out: false,
    }))
    const summary = evaluateGateResults(passingResults, { acceptedGaps })

    await testInfo.attach('phase17-gate-summary.json', {
      body: JSON.stringify(summary, null, 2),
      contentType: 'application/json',
    })

    expect(summary.passed).toBe(true)
    expect(summary.critical_failures).toEqual([])
    expect(summary.high_failures).toEqual([])
    expect(summary.accepted_gap_review.blocking).toEqual([])
    expect(summary.accepted_gap_review.invalid).toEqual([])
  })
})
