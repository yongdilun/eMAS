import { attachReleaseStackArtifacts, expect, test } from '../support/releaseArtifacts.js'
import {
  factoryAgentJson,
  openChat,
  pendingApprovalsForPage,
  proxyLogText,
  releaseEnv,
  releaseJson,
  resetReleaseFaults,
  sendPrompt,
  setReleaseFaults,
} from '../support/releaseScenarios.js'

test.setTimeout(90_000)

test.describe('L4 production-like release validation @l4-release', () => {
  test.beforeEach(async () => {
    await resetReleaseFaults()
  })

  test('scenario 53: release path opens app at / and routes Factory Agent through /agent', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Show status for machine M-CNC-01 through the Phase 10 release proxy')

    await expect(page.getByText(/Machine M-CNC-01/i).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()

    const logs = await proxyLogText()
    expect(logs).toContain('"/agent/sessions')
    expect(logs).toMatch(/"kind"\s*:\s*"proxy"/)
  })

  test('scenario 54: release path routes Go API through /api/v1', async ({ page }) => {
    await page.goto('/')
    const result = await page.evaluate(async () => {
      const response = await fetch('/api/v1/machines')
      return {
        ok: response.ok,
        status: response.status,
        releaseBuildId: response.headers.get('x-release-build-id'),
        body: await response.json(),
      }
    })

    expect(result.ok).toBe(true)
    expect(result.status).toBe(200)
    expect(result.releaseBuildId).toBe(releaseEnv.releaseBuildId)
    expect(JSON.stringify(result.body)).toContain('M-CNC-01')
  })

  test('SO-017 scenario 55: static bearer release mode disables EventSource and uses polling fallback', async ({ page }) => {
    const eventSourceRequests = []
    page.on('request', (request) => {
      if (request.url().includes('/events')) eventSourceRequests.push(request.url())
    })

    await openChat(page)
    await sendPrompt(page, 'Show status for machine M-CNC-01 with static bearer polling fallback')

    await expect(page.getByText(/EventSource cannot attach Authorization headers/i).first()).toBeVisible()
    await expect(page.getByText(/Snapshot polling remains enabled/i).first()).toBeVisible()
    await expect(page.getByText(/Machine M-CNC-01/i).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    expect(eventSourceRequests).toHaveLength(0)
  })

  test('scenario 56: CORS preflight and browser requests succeed for Factory Agent and Go API', async ({ page }) => {
    await page.goto('/')
    const result = await page.evaluate(async () => {
      const agentOptions = await fetch('/agent/ready', {
        method: 'OPTIONS',
        headers: { 'Access-Control-Request-Method': 'GET' },
      })
      const apiOptions = await fetch('/api/v1/machines', {
        method: 'OPTIONS',
        headers: { 'Access-Control-Request-Method': 'GET' },
      })
      const agentReady = await fetch('/agent/ready')
      const machines = await fetch('/api/v1/machines')
      return {
        agentOptions: agentOptions.status,
        apiOptions: apiOptions.status,
        agentCors: agentOptions.headers.get('access-control-allow-origin'),
        apiCors: apiOptions.headers.get('access-control-allow-origin'),
        agentReady: agentReady.status,
        machines: machines.status,
      }
    })

    expect(result).toEqual({
      agentOptions: 204,
      apiOptions: 204,
      agentCors: '*',
      apiCors: '*',
      agentReady: 200,
      machines: 200,
    })
  })

  test('scenario 57: controlled release failure drill archives trace, video, report, logs, and fingerprint evidence', async ({ page }, testInfo) => {
    await page.goto('/')
    await testInfo.attach('controlled-release-failure-drill.txt', {
      body: [
        'This is the Phase 10 controlled failure artifact drill.',
        'The red assertion is simulated so the normal release gate can still pass.',
        `releaseBaseUrl=${releaseEnv.releaseBaseUrl}`,
        `releaseBuildId=${releaseEnv.releaseBuildId}`,
      ].join('\n'),
      contentType: 'text/plain',
    })
    await testInfo.attach('controlled-release-page.png', {
      body: await page.screenshot({ fullPage: true }),
      contentType: 'image/png',
    })
    await attachReleaseStackArtifacts(testInfo)

    const { body } = await releaseJson('/__release/fingerprint')
    expect(body.kind).toBe('playwright-release-stack')
    expect(body.urls.releaseFactoryAgentBaseUrl).toBe(`${releaseEnv.releaseBaseUrl}/agent`)
    expect(body.urls.releaseGoApiBaseUrl).toBe(`${releaseEnv.releaseBaseUrl}/api/v1`)
  })

  test('scenario 58: release validation checks chat-open, first-progress, and final-answer latency budgets', async ({ page }) => {
    const start = Date.now()
    await openChat(page)
    const openedAt = Date.now()
    expect(openedAt - start).toBeLessThan(releaseEnv.latencyBudgetsMs.chatOpen)

    await sendPrompt(page, 'Run Phase 10 release latency budget machine status')
    await expect(page.getByText(/Understanding your request|Gathering information|Run complete/i).first()).toBeVisible({
      timeout: releaseEnv.latencyBudgetsMs.firstProgress,
    })
    const progressAt = Date.now()
    expect(progressAt - openedAt).toBeLessThan(releaseEnv.latencyBudgetsMs.firstProgress)

    await expect(page.getByText(/Machine M-CNC-01/i).first()).toBeVisible({
      timeout: releaseEnv.latencyBudgetsMs.finalAnswer,
    })
    await expect(page.getByText('Run complete')).toBeVisible()
    expect(Date.now() - openedAt).toBeLessThan(releaseEnv.latencyBudgetsMs.finalAnswer)
  })

  test('scenario 59: real LLM connectivity smoke is explicitly opt-in and structural only', async () => {
    const enabled = process.env.PLAYWRIGHT_RELEASE_REAL_LLM_SMOKE === '1'
    if (!enabled) {
      expect(process.env.PLAYWRIGHT_RELEASE_REAL_LLM_SMOKE || '').not.toBe('1')
      return
    }

    const { body } = await releaseJson('/agent/ready')
    expect(body.status).toBe('ready')
    expect(typeof body.checks).toBe('object')
  })

  test('scenario 62: bad frontend API env precheck fails fast with a visible release diagnostic', async ({ page }) => {
    await page.goto('/__release/precheck?factoryAgentBaseUrl=http%3A%2F%2F127.0.0.1%3A8000&apiBaseUrl=/api/v1')
    await expect(page.getByRole('heading', { name: 'Release precheck failed' })).toBeVisible()
    await expect(page.getByText(/VITE_FACTORY_AGENT_BASE_URL must be \/agent/i)).toBeVisible()
  })

  test('scenario 63: migration or schema mismatch fails the release gate before browser success is claimed', async ({ page }) => {
    await setReleaseFaults({ schemaMismatch: true })
    await page.goto('/__release/precheck')
    await expect(page.getByRole('heading', { name: 'Release precheck failed' })).toBeVisible()
    await expect(page.getByText(/migration\/schema mismatch|backend readiness failure/i)).toBeVisible()
  })

  test('scenario 68: rollback candidate can run the same smoke check against the previous build URL', async () => {
    const rollback = new URL('/__release/precheck', releaseEnv.rollbackBaseUrl)
    const response = await fetch(rollback)
    const body = await response.json()
    expect(response.ok).toBe(true)
    expect(body.message).toBe('Release precheck passed.')
  })

  test('scenario 69: cache/version mismatch rejects stale frontend against incompatible backend schema', async ({ page }) => {
    await page.goto('/')
    const current = await page.evaluate(async () => {
      const response = await fetch('/__release/version')
      return { ok: response.ok, status: response.status, body: await response.json() }
    })
    expect(current.ok).toBe(true)
    expect(current.body.releaseBuildId).toBe(releaseEnv.releaseBuildId)

    const stale = await page.evaluate(async () => {
      const response = await fetch('/__release/version?frontendBuildId=stale-build')
      return { ok: response.ok, status: response.status, body: await response.json() }
    })
    expect(stale.ok).toBe(false)
    expect(stale.status).toBe(409)
    expect(stale.body.message).toMatch(/stale frontend build|backend schema/i)
  })
})
