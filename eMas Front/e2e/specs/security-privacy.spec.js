import { expect, test } from '@playwright/test'

import { chatSelectors } from '../fixtures/selectors.js'
import {
  assertNoSensitiveArtifactLeaks,
  findSensitiveArtifactLeaks,
  redactSensitiveArtifactText,
  sensitiveArtifactSamples,
} from '../support/artifactRedaction.js'
import {
  securityAuthFailureTargetAnswer,
  securityCrossSessionLeakApproval,
  securityCrossSessionLeakAudit,
  securityCrossSessionLeakFinal,
  securityCrossSessionLeakHidden,
  securityCrossSessionLeakSource,
  securityLargeUnsafePrefix,
  securityLargeUnsafePrompt,
  securityOtherUserSecret,
  securitySafeOwnAnswer,
  securityUnsupportedDangerousPrompts,
  securityUnsafeActionBlocked,
  securityUnsafeActionPrompt,
  securityUnsafeJavascriptLink,
  securityUnsafeActionRisk,
  securityUnsafeMarkdownAnswer,
} from '../support/securityScenarios.js'

const mockBaseUrl = `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_FACTORY_AGENT_PORT || 8015)}`
const activeSessionStorageKey = 'factory_agent_active_session_id'

async function mockJson(path, options = {}) {
  const response = await fetch(`${mockBaseUrl}${path}`, {
    method: options.method || 'GET',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  const text = await response.text()
  const body = text ? JSON.parse(text) : null
  if (!response.ok) throw new Error(`Mock ${options.method || 'GET'} ${path} failed: ${response.status} ${text}`)
  return body
}

async function requestsFor(query) {
  const params = new URLSearchParams(query)
  const body = await mockJson(`/__test/requests?${params}`)
  return body.requests || []
}

async function seedSecuritySessions(testInfo) {
  return mockJson('/__test/security-sessions', {
    method: 'POST',
    body: { run_id: `w${testInfo.workerIndex}-${Date.now()}` },
  })
}

async function openChat(page) {
  await page.goto('/')
  await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
  await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()
}

async function sendPrompt(page, prompt, visibleText = prompt) {
  const composer = page.getByPlaceholder(chatSelectors.composerPlaceholder)
  await expect(composer).toBeEnabled()
  await composer.fill(prompt)
  await page.getByRole('button', { name: chatSelectors.sendButtonName }).click()
  await expect(page.getByText(visibleText).first()).toBeVisible()
}

async function expectComposerReady(page) {
  await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)
  await expect(page.getByRole('dialog', { name: chatSelectors.dialogName }).getByRole('combobox')).toHaveCount(0)
  await expect(page.getByPlaceholder(chatSelectors.composerPlaceholder)).toBeEnabled()
}

async function dialogDoesNotOverflow(page) {
  return page.getByRole('dialog').evaluate((dialog) => dialog.scrollWidth <= dialog.clientWidth + 1)
}

async function waitForDialogText(page, expected) {
  await expect
    .poll(async () => {
      const text = await page.getByRole('dialog').textContent().catch(() => '')
      return text.includes(expected)
    }, { timeout: 20_000 })
    .toBe(true)
}

async function activeSessionId(page) {
  return page.evaluate((key) => window.localStorage.getItem(key), activeSessionStorageKey)
}

async function sessionSnapshot(sessionId) {
  return mockJson(`/sessions/${sessionId}/snapshot`, {
    headers: { 'X-User-Id': 'frontend-operator' },
  })
}

async function expectNoCrossSessionLeakage(page) {
  await expect(page.getByText(securityCrossSessionLeakFinal)).toHaveCount(0)
  await expect(page.getByText(securityCrossSessionLeakApproval)).toHaveCount(0)
  await expect(page.getByText(securityCrossSessionLeakSource)).toHaveCount(0)
  await expect(page.getByText(securityCrossSessionLeakAudit)).toHaveCount(0)
  await expect(page.getByText(securityCrossSessionLeakHidden)).toHaveCount(0)
  await expect(page.getByText('Approval required')).toHaveCount(0)
}

test.describe('Phase 17 security, privacy, and abuse hardening @security @privacy', () => {
  test('scenario 96: tampered local storage cannot expose another user session', async ({ page }, testInfo) => {
    const seeded = await seedSecuritySessions(testInfo)
    await page.addInitScript(
      ({ key, value }) => window.localStorage.setItem(key, value),
      { key: activeSessionStorageKey, value: seeded.other.session_id },
    )

    await openChat(page)

    await expect(page.getByText(/Session not found|Requested resource was not found|Factory Agent needs attention/i).first()).toBeVisible()
    await expect(page.getByText(securityOtherUserSecret)).toHaveCount(0)
    await expect(page.getByText(securitySafeOwnAnswer)).toHaveCount(0)
    await expect
      .poll(() => page.evaluate((key) => window.localStorage.getItem(key), activeSessionStorageKey))
      .not.toBe(seeded.other.session_id)

    const denied = await requestsFor({ session_id: seeded.other.session_id })
    expect(denied.some((entry) => entry.status === 404)).toBe(true)
  })

  test('scenario 101: switching, refreshing, and restoring history do not leak another session', async ({ page }, testInfo) => {
    const seeded = await seedSecuritySessions(testInfo)

    await page.goto('/')
    await page.evaluate(
      ({ key, value }) => window.localStorage.setItem(key, value),
      { key: activeSessionStorageKey, value: seeded.cross_session_final.session_id },
    )
    await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()
    await waitForDialogText(page, securityCrossSessionLeakFinal)
    await waitForDialogText(page, securityCrossSessionLeakAudit)
    await waitForDialogText(page, securityCrossSessionLeakSource)

    await page.getByRole('button', { name: `Open session ${seeded.owner.name}` }).click()
    await waitForDialogText(page, securitySafeOwnAnswer)
    await expectNoCrossSessionLeakage(page)

    const detailsToggle = page.getByText('Show details').first()
    if (await detailsToggle.count()) await detailsToggle.click()
    await expect(page.getByText(securityCrossSessionLeakHidden)).toHaveCount(0)

    await page.reload()
    await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
    await waitForDialogText(page, securitySafeOwnAnswer)
    await expectNoCrossSessionLeakage(page)

    await page.getByRole('button', { name: `Open session ${seeded.cross_session_approval.name}` }).click()
    await expect(page.getByText('Approval required').first()).toBeVisible()
    await expect(page.getByText(securityCrossSessionLeakApproval).first()).toBeVisible()

    await page.getByRole('button', { name: `Open session ${seeded.owner.name}` }).click()
    await waitForDialogText(page, securitySafeOwnAnswer)
    await expectNoCrossSessionLeakage(page)
  })

  test('scenario 97: unauthorized REST, polling, and EventSource access are denied safely', async ({ page }, testInfo) => {
    const seeded = await seedSecuritySessions(testInfo)

    const apiMisuse = await page.evaluate(async ({ baseUrl, streamSessionId, ownerSessionId }) => {
      const readText = async (response) => ({ status: response.status, text: await response.text() })
      const rest = await readText(await fetch(`${baseUrl}/sessions`))
      const polling = await readText(
        await fetch(`${baseUrl}/sessions/${ownerSessionId}/snapshot`, { headers: { 'X-User-Id': 'intruder' } }),
      )
      const eventSourceOutcome = await new Promise((resolve) => {
        const es = new EventSource(`${baseUrl}/sessions/${streamSessionId}/events`)
        const timer = window.setTimeout(() => {
          es.close()
          resolve('timeout')
        }, 2500)
        es.onopen = () => {
          window.clearTimeout(timer)
          es.close()
          resolve('opened')
        }
        es.onerror = () => {
          window.clearTimeout(timer)
          es.close()
          resolve('denied')
        }
      })
      return { rest, polling, eventSourceOutcome }
    }, {
      baseUrl: mockBaseUrl,
      ownerSessionId: seeded.owner.session_id,
      streamSessionId: seeded.stream_auth.session_id,
    })

    expect(apiMisuse.rest.status).toBe(401)
    expect(apiMisuse.polling.status).toBe(404)
    expect(apiMisuse.eventSourceOutcome).toBe('denied')
    expect(apiMisuse.rest.text).not.toContain(securityOtherUserSecret)
    expect(apiMisuse.polling.text).not.toContain(securityOtherUserSecret)

    await page.addInitScript(
      ({ key, value }) => window.localStorage.setItem(key, value),
      { key: activeSessionStorageKey, value: seeded.owner.session_id },
    )
    await openChat(page)
    await waitForDialogText(page, securitySafeOwnAnswer)

    await page.route(`${mockBaseUrl}/sessions/${seeded.auth_failure_target.session_id}/snapshot`, async (route) => {
      const headers = { ...route.request().headers() }
      delete headers['x-user-id']
      await route.continue({ headers })
    })
    await page.getByRole('button', { name: `Open session ${seeded.auth_failure_target.name}` }).click()
    await expect(page.getByText(/Authentication required|Authentication failed|Factory Agent needs attention/i).first()).toBeVisible()
    await expect(page.getByText(securitySafeOwnAnswer)).toHaveCount(0)
    await expect(page.getByText(securityAuthFailureTargetAnswer)).toHaveCount(0)
    await expect(page.getByText(securityOtherUserSecret)).toHaveCount(0)
    await expectComposerReady(page)

    await page.route(`${mockBaseUrl}/**`, async (route) => {
      const headers = { ...route.request().headers() }
      delete headers['x-user-id']
      await route.continue({ headers })
    })
    await page.addInitScript(
      ({ key, value }) => window.localStorage.setItem(key, value),
      { key: activeSessionStorageKey, value: seeded.owner.session_id },
    )
    await openChat(page)
    await expect(page.getByText(/Authentication required|Factory Agent needs attention/i).first()).toBeVisible()
    await expect(page.getByText(securityOtherUserSecret)).toHaveCount(0)
    await expect(page.getByText(securitySafeOwnAnswer)).toHaveCount(0)

    const streamRequests = await requestsFor({ session_id: seeded.stream_auth.session_id })
    expect(streamRequests.some((entry) => entry.path.endsWith('/events') && entry.status === 401)).toBe(true)
  })

  test('scenario 98: logs, traces, screenshots, and reports redact sensitive fields', async ({ page }, testInfo) => {
    await page.goto('/')
    const rawArtifact = {
      kind: 'phase16-artifact-redaction-proof',
      log: `authorization: ${sensitiveArtifactSamples.bearer}`,
      trace: {
        url: `${mockBaseUrl}/sessions/${sensitiveArtifactSamples.sessionId}/snapshot?token=${sensitiveArtifactSamples.queryToken}`,
        operation_id: sensitiveArtifactSamples.operationId,
      },
      screenshot: {
        masking: ['chat dialog', 'operator transcript'],
        auth_token: sensitiveArtifactSamples.queryToken,
      },
      report: {
        api_key: sensitiveArtifactSamples.apiKey,
        session_id: sensitiveArtifactSamples.sessionId,
      },
    }

    const redacted = redactSensitiveArtifactText(rawArtifact)
    await testInfo.attach('phase16-redacted-artifact-proof.json', {
      body: redacted,
      contentType: 'application/json',
    })

    assertNoSensitiveArtifactLeaks(expect, redacted)
    expect(findSensitiveArtifactLeaks(rawArtifact)).toEqual(
      expect.arrayContaining(['bearer', 'queryToken', 'apiKey', 'sessionId', 'operationId']),
    )
    expect(redacted).toContain('<redacted>')
  })

  test('scenario 99: large pasted input and unsafe markdown render inertly without layout collapse', async ({ page }) => {
    test.setTimeout(60_000)
    await page.setViewportSize({ width: 390, height: 844 })
    await openChat(page)
    await page.evaluate(() => {
      window.__phase16_xss = undefined
    })

    await sendPrompt(page, securityLargeUnsafePrompt, securityLargeUnsafePrefix)
    await waitForDialogText(page, 'Run complete')
    await waitForDialogText(page, 'Phase 16 unsafe markdown was rendered as text, not executable content.')
    await waitForDialogText(page, '<script>window.__phase16_xss = "answer-script-executed"</script>')
    await waitForDialogText(page, `<a href="${securityUnsafeJavascriptLink}" target="_blank">unsafe html link</a>`)
    await waitForDialogText(page, `[unsafe markdown link](${securityUnsafeJavascriptLink})`)
    await expectComposerReady(page)

    const dialogText = await page.getByRole('dialog').textContent()
    expect(dialogText).toContain('Phase 16 unsafe markdown was rendered as text, not executable content.')
    expect(dialogText).toContain('<script>window.__phase16_xss = "answer-script-executed"</script>')
    expect(dialogText).toContain(`<a href="${securityUnsafeJavascriptLink}" target="_blank">unsafe html link</a>`)
    expect(dialogText).toContain(`[unsafe markdown link](${securityUnsafeJavascriptLink})`)
    expect(await page.evaluate(() => window.__phase16_xss)).toBeUndefined()
    expect(await page.evaluate(() => window.__phase17_xss)).toBeUndefined()
    await expect(page.locator('script').filter({ hasText: 'phase16_xss' })).toHaveCount(0)
    await expect(page.getByRole('dialog').locator('a[href^="javascript:"], a[target="_blank"]:not([rel~="noopener"])')).toHaveCount(0)
    await expect(page.getByPlaceholder(chatSelectors.composerPlaceholder)).toHaveValue('')
    expect(securityLargeUnsafePrompt.length).toBeGreaterThan(8_000)
    const largeRequests = await requestsFor({ contains: securityLargeUnsafePrefix })
    expect(largeRequests.some((entry) => String(entry.prompt || entry.body?.content || '').length === securityLargeUnsafePrompt.length)).toBe(true)
    await expect(page.getByText(securitySafeOwnAnswer)).toHaveCount(0)
    expect(await dialogDoesNotOverflow(page)).toBe(true)
    expect(securityUnsafeMarkdownAnswer).toContain('UNBROKEN_ANSWER_')
  })

  test('scenario 100: tool allowlist and approval gates block unsupported unsafe actions', async ({ page }) => {
    await openChat(page)

    const tools = await page.evaluate(async (baseUrl) => {
      const response = await fetch(`${baseUrl}/tools?intent=delete_production_records`, {
        headers: { 'X-User-Id': 'frontend-operator' },
      })
      return response.json()
    }, mockBaseUrl)
    expect(tools.every((tool) => tool.is_read_only)).toBe(true)
    expect(tools.some((tool) => tool.name === 'phase16_unsafe_delete_production_jobs')).toBe(false)

    for (const [index, prompt] of [securityUnsafeActionPrompt, ...securityUnsupportedDangerousPrompts].entries()) {
      if (index > 0) {
        await page.getByRole('button', { name: 'New Session' }).click()
        await expect(page.getByText('Start a session from the sidebar.')).toBeVisible()
      }

      await sendPrompt(page, prompt)
      await expect(page.getByText('Approval required').first()).toBeVisible()
      await expect(page.getByText(securityUnsafeActionRisk).first()).toBeVisible()
      await expect(page.getByText('Run complete')).toHaveCount(0)

      const sessionId = await activeSessionId(page)
      const before = await sessionSnapshot(sessionId)
      expect(before.pending_approval?.status).toBe('PENDING')
      expect(before.timeline.some((event) => event.event_type === 'tool_result')).toBe(false)

      await page.getByRole('button', { name: 'Approve' }).click()
      await expect(page.getByText(securityUnsafeActionBlocked).first()).toBeVisible()
      await expect(page.getByText('Run complete')).toHaveCount(0)
      await expect(page.getByText(/Approved request to change record|deleted production/i)).toHaveCount(0)
      await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)

      const after = await sessionSnapshot(sessionId)
      expect(after.session.status).toBe('FAILED')
      expect(after.pending_approval).toBeNull()
      expect(after.timeline.some((event) => event.event_type === 'tool_result')).toBe(false)
      expect(JSON.stringify(after)).not.toContain('audit_row')

      const sessionRequests = await requestsFor({ session_id: sessionId })
      expect(sessionRequests.some((entry) => entry.method === 'DELETE')).toBe(false)
    }
  })
})
