import { expect, test } from '@playwright/test'
import { chatSelectors } from '../fixtures/selectors.js'
import {
  notificationSseAnswer,
  notificationSsePrompt,
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

function assertMonotonicUniqueFrameIds(events) {
  const ids = events.map((entry) => Number(entry.id))
  expect(ids.every(Number.isFinite)).toBe(true)
  expect(ids).toEqual([...ids].sort((a, b) => a - b))
  expect(new Set(ids).size).toBe(ids.length)
}

function assertSnapshotRefreshAfterInvalidation(notificationFrames, snapshotRequests) {
  const invalidation = notificationFrames.find((entry) => entry.data?.type === 'snapshot_invalidated')
  expect(invalidation, 'expected notification SSE snapshot_invalidated frame').toBeTruthy()
  expect(snapshotRequests.some((entry) => String(entry.at) >= String(invalidation.at))).toBe(true)
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

test.describe('Factory Agent chat SSE notification stream @sse', () => {
  test('notification hello opens the stream, invalidates the snapshot, and reaches final completion', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, notificationSsePrompt)

    await expect(page.locator('[role="status"][aria-busy="true"]')).toBeVisible()

    await expect
      .poll(async () => {
        const connections = await connectionsFor({
          scenario: 'notificationSseCompletion',
          stream: 'notification',
          event: 'open',
        })
        return connections.length
      })
      .toBeGreaterThan(0)

    await expect(page.getByText(notificationSseAnswer).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)
    await expect(page.getByText(/heartbeat/i)).toHaveCount(0)

    const requests = await requestsFor({ scenario: 'notificationSseCompletion' })
    const notificationRequests = requests.filter((entry) => entry.path.endsWith('/events'))
    const snapshotRequests = requests.filter((entry) => entry.path.endsWith('/snapshot'))
    const notificationFrames = await sseEventsFor({
      scenario: 'notificationSseCompletion',
      stream: 'notification',
    })

    expect(notificationRequests.length).toBeGreaterThan(0)
    expect(snapshotRequests.length).toBeGreaterThanOrEqual(2)
    assertMonotonicUniqueFrameIds(notificationFrames)
    expect(notificationFrames.map((entry) => entry.data?.type)).toEqual(
      expect.arrayContaining(['hello', 'heartbeat', 'snapshot_invalidated']),
    )
    assertSnapshotRefreshAfterInvalidation(notificationFrames, snapshotRequests)

    expect(() => assertSnapshotRefreshAfterInvalidation(
      notificationFrames.filter((entry) => entry.data?.type !== 'snapshot_invalidated'),
      snapshotRequests,
    )).toThrow()
  })
})
