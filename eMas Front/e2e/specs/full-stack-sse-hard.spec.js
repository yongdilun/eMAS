import { expect, test } from '../support/seededArtifacts.js'
import {
  activeSessionId,
  factoryAgentJson,
  openChat,
  sendPrompt,
  snapshotForPage,
} from '../support/fullStackScenarios.js'

test.describe('L3 seeded hard SSE behavior @l3-hard @sse-order', () => {
  test('scenario 47: out-of-order and duplicate SSE events do not regress phase or duplicate visible activity', async ({ page }) => {
    const pageErrors = []
    const sseRequests = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    page.on('request', (request) => {
      const url = request.url()
      if (url.includes('/events')) sseRequests.push(url)
    })

    await openChat(page)
    await sendPrompt(page, 'Run Phase 9 out-of-order duplicate SSE seeded jobs workflow')

    await expect(page.getByText(/Phase 9 step 2 read seeded data/i).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)

    const snapshot = await snapshotForPage(page)
    const activityText = snapshot.activity_steps.map((step) => step.label || '').join('\n')
    expect((activityText.match(/Run complete/g) || [])).toHaveLength(1)
    expect(snapshot.session.status).toBe('COMPLETED')
    expect(new Set(snapshot.activity_steps.map((step) => step.id)).size).toBe(snapshot.activity_steps.length)
    expect(sseRequests.some((url) => url.includes('/events/activity'))).toBe(true)
    expect(pageErrors).toEqual([])
  })

  test('scenario 48: EventSource reconnect sends Last-Event-ID and avoids replaying rendered steps', async ({ page }) => {
    const notificationRequests = []
    page.on('request', (request) => {
      const url = request.url()
      if (/\/sessions\/[^/]+\/events(?:\?|$)/.test(url)) {
        notificationRequests.push({
          url,
          headers: request.headers(),
        })
      }
    })

    await openChat(page)
    await sendPrompt(page, 'Run Phase 9 Last-Event-ID reconnect seeded machine workflow')

    await expect.poll(() => activeSessionId(page)).not.toBeNull()
    const sessionId = await activeSessionId(page)
    await expect
      .poll(async () => {
        const data = await factoryAgentJson('/_playwright/sse-connections')
        return data.connections.some(
          (entry) => entry.stream === 'notification' && entry.session_id === sessionId && Boolean(entry.last_event_id),
        )
      }, { timeout: 15000 })
      .toBe(true)
    await expect(page.getByText(/Machine M-CNC-01/i).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()

    const snapshot = await snapshotForPage(page)
    const activityText = snapshot.activity_steps.map((step) => step.label || '').join('\n')
    expect((activityText.match(/Run complete/g) || [])).toHaveLength(1)
    const seenRequests = notificationRequests.filter((entry) => entry.url.includes(`/sessions/${sessionId}/events`))
    expect(seenRequests.length).toBeGreaterThan(0)
  })
})
