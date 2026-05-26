import { expect, test } from '@playwright/test'
import { chatSelectors } from '../fixtures/selectors.js'
import {
  activitySseAnswer,
  activitySseDelayedFallbackPrompt,
  activitySseGraphDuplicatePrompt,
  activitySsePrompt,
  activitySseResponseDocumentPrompt,
} from '../fixtures/factoryAgentFixtures.js'

const mockBaseUrl = `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_FACTORY_AGENT_PORT || 8015)}`

async function getMockJson(path) {
  const response = await fetch(`${mockBaseUrl}${path}`)
  if (!response.ok) throw new Error(`Could not read mock ${path}: ${response.status}`)
  return response.json()
}

async function connectionsFor(query) {
  const params = new URLSearchParams(query)
  const body = await getMockJson(`/__test/sse-connections?${params}`)
  return body.connections || []
}

async function requestsFor(query) {
  const params = new URLSearchParams(query)
  const body = await getMockJson(`/__test/requests?${params}`)
  return body.requests || []
}

async function sseEventsFor(query) {
  const params = new URLSearchParams(query)
  const body = await getMockJson(`/__test/sse-events?${params}`)
  return body.events || []
}

async function activeSessionId(page) {
  return page.evaluate(() => window.localStorage.getItem('factory_agent_active_session_id'))
}

async function snapshotForPage(page) {
  const sessionId = await activeSessionId(page)
  if (!sessionId) throw new Error('No active Factory Agent session id')
  const response = await fetch(`${mockBaseUrl}/sessions/${sessionId}/snapshot`, {
    headers: { 'X-User-Id': 'frontend-operator' },
  })
  if (!response.ok) throw new Error(`Could not read snapshot: ${response.status}`)
  return response.json()
}

function assertMonotonicUniqueFrameIds(events) {
  const ids = events.map((entry) => Number(entry.id))
  expect(ids.every(Number.isFinite)).toBe(true)
  expect(ids).toEqual([...ids].sort((a, b) => a - b))
  expect(new Set(ids).size).toBe(ids.length)
}

function assertFrameLabels(events, expectedLabels) {
  expect(events.map((entry) => entry.data?.label)).toEqual(expectedLabels)
}

function assertTimelineOrder(snapshot, expectedTypes) {
  const types = snapshot.timeline.map((event) => event.event_type)
  for (const type of expectedTypes) {
    expect(types).toContain(type)
  }
  for (let index = 1; index < expectedTypes.length; index += 1) {
    expect(types.indexOf(expectedTypes[index - 1])).toBeLessThan(types.indexOf(expectedTypes[index]))
  }
}

async function openChat(page) {
  await page.goto('/')
  await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
  await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()
}

async function sendChatPrompt(page, prompt) {
  const composer = page.getByPlaceholder(chatSelectors.composerPlaceholder)
  await expect(composer).toBeEnabled()
  await composer.fill(prompt)
  await page.getByRole('button', { name: chatSelectors.sendButtonName }).click()
  await expect(page.getByText(prompt)).toBeVisible()
}

test.describe('Factory Agent chat SSE activity stream @sse', () => {
  test('activity stream shows ordered steps and gates the final answer until completed snapshot state', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, activitySsePrompt)

    await expect
      .poll(async () => {
        const connections = await connectionsFor({
          scenario: 'activitySseOrdered',
          stream: 'activity',
          event: 'open',
        })
        return connections.length
      })
      .toBeGreaterThan(0)

    await page.getByRole('button', { name: /Run complete[\s\S]*4 updates/i }).click()
    await expect(page.getByText('SSE understanding request')).toBeVisible()
    await expect(page.getByText('SSE checking machine telemetry')).toBeVisible()
    await expect(page.getByText('SSE validating result')).toBeVisible()

    const activityList = page.locator('ol').filter({ hasText: 'SSE understanding request' }).first()
    const activityText = await activityList.innerText()
    expect(activityText.indexOf('SSE understanding request')).toBeLessThan(
      activityText.indexOf('SSE checking machine telemetry'),
    )
    expect(activityText.indexOf('SSE checking machine telemetry')).toBeLessThan(
      activityText.indexOf('SSE validating result'),
    )

    await expect(page.getByText(/heartbeat/i)).toHaveCount(0)

    await expect(page.getByText(activitySseAnswer).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)

    const activityFrames = await sseEventsFor({
      scenario: 'activitySseOrdered',
      stream: 'activity',
      event: 'activity',
    })
    assertMonotonicUniqueFrameIds(activityFrames)
    assertFrameLabels(activityFrames, [
      'SSE understanding request',
      'SSE checking machine telemetry',
      'SSE validating result',
    ])

    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('COMPLETED')
    expect(snapshot.activity_steps.map((step) => step.label)).toEqual([
      'SSE understanding request',
      'SSE checking machine telemetry',
      'SSE validating result',
      'Run complete',
    ])
    assertTimelineOrder(snapshot, ['plan_created', 'execution_started', 'tool_result', 'session_completed'])

    const notificationConnections = await connectionsFor({
      scenario: 'activitySseOrdered',
      stream: 'notification',
      event: 'open',
    })
    expect(notificationConnections.length).toBeGreaterThan(0)

    const requests = await requestsFor({ scenario: 'activitySseOrdered' })
    expect(requests.some((entry) => entry.path.endsWith('/events/activity'))).toBe(true)
    expect(requests.some((entry) => entry.path.endsWith('/snapshot'))).toBe(true)

    expect(() => assertMonotonicUniqueFrameIds([{ id: 2 }, { id: 2 }])).toThrow()
    expect(() => assertFrameLabels(activityFrames.slice(1), [
      'SSE understanding request',
      'SSE checking machine telemetry',
      'SSE validating result',
    ])).toThrow()
  })

  test('response_document turns render live activity before final snapshot completion', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, activitySseResponseDocumentPrompt)

    await expect
      .poll(async () => {
        const activityFrames = await sseEventsFor({
          scenario: 'activitySseResponseDocument',
          stream: 'activity',
          event: 'activity',
        })
        return activityFrames.map((entry) => entry.data?.label)
      })
      .toContain('SSE checking machine telemetry')

    await expect(page.getByText('Session activity')).toBeVisible()
    const rdActivityList = page.locator('ol').filter({ hasText: 'SSE checking machine telemetry' }).first()
    await expect(rdActivityList.getByText('SSE checking machine telemetry', { exact: true })).toBeVisible()
    await expect(rdActivityList.getByText('Reading M-CNC-01 status and alarm records', { exact: true })).toBeVisible()
    await expect(page.getByText('Working on response-document activity stream.')).toBeVisible()
    await expect(page.getByText(activitySseAnswer).first()).not.toBeVisible()
    await expect(page.getByText('Run complete')).not.toBeVisible({ timeout: 250 })

    await expect
      .poll(async () => {
        const requests = await requestsFor({ scenario: 'activitySseResponseDocument' })
        return requests.filter((entry) => String(entry.path || '').endsWith('/snapshot')).length
      })
      .toBeGreaterThanOrEqual(3)

    await expect(rdActivityList.getByText('SSE checking machine telemetry', { exact: true })).toBeVisible()
    await expect(rdActivityList.getByText('Reading M-CNC-01 status and alarm records', { exact: true })).toBeVisible()
    await expect(page.getByText(activitySseAnswer).first()).not.toBeVisible()

    await expect
      .poll(async () => {
        const activityFrames = await sseEventsFor({
          scenario: 'activitySseResponseDocument',
          stream: 'activity',
          event: 'activity',
        })
        return activityFrames.map((entry) => entry.data?.label)
      })
      .toContain('SSE validating result')

    await expect
      .poll(async () => {
        const activityFrames = await sseEventsFor({
          scenario: 'activitySseResponseDocument',
          stream: 'activity',
          event: 'activity',
        })
        return activityFrames.map((entry) => entry.data?.label)
      })
      .toContain('Run complete')

    await expect(page.getByText('Working on response-document activity stream.')).toBeVisible()
    await expect(page.getByText(activitySseAnswer).first()).not.toBeVisible({ timeout: 250 })
    await expect(page.getByText('Run complete')).not.toBeVisible({ timeout: 250 })

    await expect(page.getByText(activitySseAnswer).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.getByText('Working on response-document activity stream.')).not.toBeVisible()
  })

  test('delayed server activity replaces one neutral client fallback without generic status spam', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, activitySseDelayedFallbackPrompt)

    await expect(page.getByText('This updates as the session progresses')).toHaveCount(0)
    await expect(page.getByText('Understanding...')).toHaveCount(0)
    await expect(page.getByText('Checking information...')).toHaveCount(0)
    await expect(page.getByText('Wrapping up…')).toHaveCount(0)
    await expect(page.getByText('Reviewing results...')).toHaveCount(0)
    await expect
      .poll(async () => page.getByText('Starting request...').count())
      .toBeLessThanOrEqual(1)

    await expect
      .poll(async () => {
        const activityFrames = await sseEventsFor({
          scenario: 'activitySseDelayedFallback',
          stream: 'activity',
          event: 'activity',
        })
        return activityFrames.map((entry) => entry.data?.label)
      })
      .toContain('SSE understanding request')

    const delayedActivityList = page.locator('ol').filter({ hasText: 'SSE understanding request' }).first()
    await expect(delayedActivityList.getByText('SSE understanding request', { exact: true })).toBeVisible()
    await expect(page.getByText('Starting request...')).toHaveCount(0)
    await expect(page.getByText('This updates as the session progresses')).toHaveCount(0)
    await expect(page.getByText('Understanding...')).toHaveCount(0)
    await expect(page.getByText('Checking information...')).toHaveCount(0)
    await expect(page.getByText('Wrapping up…')).toHaveCount(0)
    await expect(page.getByText('Reviewing results...')).toHaveCount(0)

    await expect
      .poll(async () => {
        const requests = await requestsFor({ scenario: 'activitySseDelayedFallback' })
        return requests.filter((entry) => String(entry.path || '').endsWith('/snapshot')).length
      })
      .toBeGreaterThanOrEqual(2)

    await expect(delayedActivityList.getByText('SSE understanding request', { exact: true })).toBeVisible()
    await expect(delayedActivityList.getByText('SSE checking machine telemetry', { exact: true })).toBeVisible()
    await expect(page.getByText(activitySseAnswer).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
  })

  test('graph activity does not duplicate understood rows and completed answer appears', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, activitySseGraphDuplicatePrompt)

    await expect
      .poll(async () => {
        const activityFrames = await sseEventsFor({
          scenario: 'activitySseGraphDuplicate',
          stream: 'activity',
          event: 'activity',
        })
        return activityFrames.map((entry) => entry.data?.label)
      })
      .toContain('Searching knowledge sources')

    await expect(page.getByText('Session activity')).toBeVisible()
    const activityList = page.locator('ol').filter({ hasText: 'Searching knowledge sources' }).first()
    await expect(activityList.getByText('Searching knowledge sources', { exact: true })).toBeVisible()
    await expect
      .poll(async () => activityList.getByText('Understood request', { exact: true }).count())
      .toBeLessThanOrEqual(1)
    await expect(activityList.getByText('Understanding your request', { exact: true })).toHaveCount(0)

    await expect(page.getByText(activitySseAnswer).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.getByText("I'm working on the request and waiting for the next backend update.")).toHaveCount(0)
    await expect(page.getByText('Working on response-document activity stream.')).toHaveCount(0)
  })
})
