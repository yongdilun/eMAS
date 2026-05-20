import {
  assertNoSensitiveArtifactLeaks,
  findSensitiveArtifactLeaks,
  redactSensitiveArtifactText,
  sensitiveArtifactSamples,
} from '../support/artifactRedaction.js'
import { expect, test } from '../support/releaseArtifacts.js'
import {
  openChat,
  proxyLogText,
  releaseEnv,
  releaseJson,
  resetReleaseFaults,
  setReleaseFaults,
} from '../support/releaseScenarios.js'

const activeSessionStorageKey = 'factory_agent_active_session_id'

test.setTimeout(90_000)

test.describe('Phase 16 release security and privacy cross-checks @security @privacy', () => {
  test.beforeEach(async () => {
    await resetReleaseFaults()
  })

  test('scenario 96 release: tampered local storage resolves to a safe missing-session diagnostic', async ({ page }) => {
    await page.addInitScript(
      ({ key }) => window.localStorage.setItem(key, 'phase16-other-user-session-id'),
      { key: activeSessionStorageKey },
    )

    await openChat(page)

    await expect(page.getByText(/Session not found|Requested resource was not found|Factory Agent needs attention/i).first()).toBeVisible()
    await expect(page.getByText(/PHASE16_OTHER_USER_SECRET|maintenance override for another operator/i)).toHaveCount(0)
    await expect
      .poll(() => page.evaluate((key) => window.localStorage.getItem(key), activeSessionStorageKey))
      .not.toBe('phase16-other-user-session-id')
  })

  test('scenario 97 release: unauthenticated REST, polling, and EventSource probes are denied', async ({ page }) => {
    await page.goto('/')
    const denied = await page.evaluate(async () => {
      const read = async (response) => ({ status: response.status, text: await response.text() })
      return {
        rest: await read(await fetch('/agent/sessions')),
        polling: await read(await fetch('/agent/sessions/phase16-missing/snapshot')),
        eventSource: await read(await fetch('/agent/sessions/phase16-missing/events')),
      }
    })

    expect(denied.rest.status).toBe(401)
    expect(denied.polling.status).toBe(401)
    expect(denied.eventSource.status).toBe(401)
    expect(`${denied.rest.text}\n${denied.polling.text}\n${denied.eventSource.text}`).not.toContain(releaseEnv.bearerToken)

    await setReleaseFaults({ authFailure: true })
    await openChat(page)
    await expect(page.getByText(/auth token expired|revoked|Authentication failed|Factory Agent needs attention/i).first()).toBeVisible()
  })

  test('scenario 98 release: release logs and attached reports redact tokens and operational ids', async ({ page }, testInfo) => {
    await page.goto('/')
    await releaseJson(`/agent/ready?token=${sensitiveArtifactSamples.queryToken}`, { allowFailure: true })
    const logs = await proxyLogText()

    assertNoSensitiveArtifactLeaks(expect, logs)
    expect(logs).toContain('<redacted>')

    const report = redactSensitiveArtifactText({
      releaseBaseUrl: releaseEnv.releaseBaseUrl,
      bearer: sensitiveArtifactSamples.bearer,
      session_id: sensitiveArtifactSamples.sessionId,
      operation_id: sensitiveArtifactSamples.operationId,
      api_key: sensitiveArtifactSamples.apiKey,
    })
    await testInfo.attach('phase16-release-redacted-report.json', {
      body: report,
      contentType: 'application/json',
    })

    assertNoSensitiveArtifactLeaks(expect, report)
    expect(findSensitiveArtifactLeaks(logs)).toEqual([])
  })
})
