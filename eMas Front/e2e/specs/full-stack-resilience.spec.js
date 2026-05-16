import { expect, test } from '../support/seededArtifacts.js'
import {
  activeSessionId,
  activeSessionStorageKey,
  factoryAgentJson,
  openChat,
  sendPrompt,
  snapshotForPage,
} from '../support/fullStackScenarios.js'

test.describe('L3 seeded hard resilience @l3-hard @resilience', () => {
  test('scenario 46: stale local storage deleted session recovers to a new safe state', async ({ page }) => {
    const stale = await factoryAgentJson('/sessions', {
      method: 'POST',
      body: { user_id: 'frontend-operator', name: 'Phase 9 deleted stale session' },
    })
    await factoryAgentJson(`/sessions/${stale.session_id}`, { method: 'DELETE' })
    await page.addInitScript(
      ({ key, value }) => window.localStorage.setItem(key, value),
      { key: activeSessionStorageKey, value: stale.session_id },
    )

    await openChat(page)
    await expect
      .poll(() => page.evaluate((key) => window.localStorage.getItem(key), activeSessionStorageKey))
      .toBeNull()
    await expect(page.getByText(/session not found|Could not restore active session|Requested resource was not found/i).first()).toBeVisible()
    await expect(page.getByText('Start a session from the sidebar.')).toBeVisible()

    await sendPrompt(page, 'Show status for machine M-CNC-01 after stale session recovery')
    await expect(page.getByText(/Machine M-CNC-01/i).first()).toBeVisible()
    const recoveredSessionId = await activeSessionId(page)
    expect(recoveredSessionId).toBeTruthy()
    expect(recoveredSessionId).not.toBe(stale.session_id)
  })

  test('scenario 49: large structured result renders without freezing, overlap, or losing completion', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'List jobs for Phase 9 large structured result')

    await expect(page.getByText(/Phase 9 large structured result rendered 80 seeded rows/i).first()).toBeVisible()
    await expect(page.getByRole('table').first()).toBeVisible()
    await expect(page.getByText('Showing 20 of 80 rows.')).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)

    const dialogOverflows = await page.getByRole('dialog').evaluate((dialog) => dialog.scrollWidth > dialog.clientWidth + 1)
    expect(dialogOverflows).toBe(false)
    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('COMPLETED')
    expect(snapshot.steps[0].result.data).toHaveLength(80)
    expect(snapshot.steps[0].result.data.at(-1).job_id).toBe('JOB-SEED-LARGE-080')
  })

  test('scenario 50: two browser contexts run isolated sessions without cross-session leakage', async ({ browser }) => {
    const contextA = await browser.newContext()
    const contextB = await browser.newContext()
    const pageA = await contextA.newPage()
    const pageB = await contextB.newPage()

    try {
      await Promise.all([openChat(pageA), openChat(pageB)])
      await Promise.all([
        sendPrompt(pageA, 'Run Phase 9 isolation alpha machine status'),
        sendPrompt(pageB, 'Run Phase 9 isolation beta machine status'),
      ])

      await expect(pageA.getByText(/Phase 9 isolation alpha session completed without beta data/i).first()).toBeVisible()
      await expect(pageB.getByText(/Phase 9 isolation beta session completed without alpha data/i).first()).toBeVisible()
      await expect(pageA.getByText(/isolation beta session completed/i)).toHaveCount(0)
      await expect(pageB.getByText(/isolation alpha session completed/i)).toHaveCount(0)

      const sessionA = await activeSessionId(pageA)
      const sessionB = await activeSessionId(pageB)
      expect(sessionA).toBeTruthy()
      expect(sessionB).toBeTruthy()
      expect(sessionA).not.toBe(sessionB)
    } finally {
      await contextA.close()
      await contextB.close()
    }
  })

  test('scenario 51: Factory Agent stream drop mid-run recovers by polling to a safe final state', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 9 stream drop recovery seeded machine workflow')

    await expect.poll(() => activeSessionId(page)).not.toBeNull()
    const sessionId = await activeSessionId(page)
    await expect
      .poll(async () => {
        const data = await factoryAgentJson('/_playwright/sse-connections')
        return data.connections.some((entry) => entry.stream === 'notification' && entry.session_id === sessionId)
      })
      .toBe(true)
    await expect(page.getByText(/Phase 9 stream drop recovered by snapshot polling/i).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)

    const snapshot = await snapshotForPage(page)
    expect(['COMPLETED', 'FAILED']).toContain(snapshot.session.status)
    expect(snapshot.session.status).toBe('COMPLETED')
  })

  test('scenario 52: RAG no-source fallback is honest and does not invent citations', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'What is the Phase 9 no-source maintenance procedure fallback?')

    await expect(page.getByText(/Controlled seeded RAG fallback/i).first()).toBeVisible()
    await expect(page.getByText(/do not have an available cited source/i).first()).toBeVisible()
    await expect(page.getByText(/No retrievable seeded source was available/i).first()).toBeVisible()
    await expect(page.getByText('Knowledge sources')).toHaveCount(0)
    await expect(page.getByText('Run complete')).toBeVisible()

    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('COMPLETED')
    const completed = snapshot.timeline.findLast((event) => event.event_type === 'session_completed')
    expect(completed?.details?.sources || []).toEqual([])
  })
})
