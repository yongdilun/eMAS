import { expect, test } from '@playwright/test'
import { chatSelectors } from '../fixtures/selectors.js'
import {
  malformedSseAnswer,
  malformedSsePrompt,
  nonTerminalFinalAnswer,
  nonTerminalPrompt,
  retryExecuteAnswer,
  retryExecutePrompt,
  streamDropPrompt,
} from '../fixtures/factoryAgentFixtures.js'

const mockBaseUrl = `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_FACTORY_AGENT_PORT || 8015)}`

async function getMockJson(path) {
  const response = await fetch(`${mockBaseUrl}${path}`)
  if (!response.ok) throw new Error(`Could not read mock ${path}: ${response.status}`)
  return response.json()
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

async function connectionsFor(query) {
  const params = new URLSearchParams(query)
  const body = await getMockJson(`/__test/sse-connections?${params}`)
  return body.connections || []
}

function assertMalformedFrameRecovery(frames) {
  const malformedIndex = frames.findIndex((entry) => entry.raw)
  const validIndex = frames.findIndex((entry) => entry.data?.type === 'snapshot_invalidated')
  expect(malformedIndex).toBeGreaterThanOrEqual(0)
  expect(validIndex).toBeGreaterThan(malformedIndex)
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

test.describe('Factory Agent chat failure and stream robustness scenarios', () => {
  test('SO-015 malformed SSE payload is ignored and the next valid notification still updates the UI @sse', async ({ page }) => {
    const pageErrors = []
    page.on('pageerror', (err) => pageErrors.push(err.message))

    await openChat(page)
    await sendChatPrompt(page, malformedSsePrompt)

    await expect
      .poll(async () => {
        const connections = await connectionsFor({
          scenario: 'malformedSseRecovery',
          stream: 'notification',
          event: 'open',
        })
        return connections.length
      })
      .toBeGreaterThan(0)

    await expect(page.getByText(malformedSseAnswer).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)
    expect(pageErrors).toEqual([])

    const frames = await sseEventsFor({
      scenario: 'malformedSseRecovery',
      stream: 'notification',
    })
    assertMalformedFrameRecovery(frames)
    expect(() => assertMalformedFrameRecovery(frames.filter((entry) => !entry.raw))).toThrow()

    const requests = await requestsFor({ scenario: 'malformedSseRecovery' })
    const validInvalidation = frames.find((entry) => entry.data?.type === 'snapshot_invalidated')
    expect(
      requests.some((entry) => entry.path.endsWith('/snapshot') && String(entry.at) >= String(validInvalidation.at)),
    ).toBe(true)
  })

  test('execute 409 is retried and the final response completes once', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, retryExecutePrompt)

    await expect(page.getByText(retryExecuteAnswer).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()

    await expect
      .poll(async () => {
        const requests = await requestsFor({ scenario: 'executeConflictRetry' })
        return requests
          .filter((entry) => entry.path.includes('/execute'))
          .map((entry) => entry.status)
      })
      .toEqual([409, 200])
  })

  test('non-terminal active session stays busy and does not fabricate a final answer', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, nonTerminalPrompt)

    await expect(page.locator('[role="status"][aria-busy="true"]')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Cancel current run' })).toBeVisible()
    await expect(page.getByText('Understanding your request').first()).toBeVisible()
    await expect(page.getByText('Run complete')).toHaveCount(0, { timeout: 750 })
    await expect(page.getByText(nonTerminalFinalAnswer)).toHaveCount(0)
  })

  test('SO-030 notification stream drop shows snapshot polling fallback diagnostic without final success @sse', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, streamDropPrompt)

    await expect(page.getByText(/Snapshot stream disconnected\. Polling every 4 seconds while reconnecting\./)).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toBeVisible()
    await expect(page.getByText('Run complete')).toHaveCount(0, { timeout: 750 })

    await expect
      .poll(async () => {
        const connections = await connectionsFor({
          scenario: 'notificationStreamDrop',
          stream: 'notification',
          event: 'close',
        })
        return connections.length
      })
      .toBeGreaterThan(0)

    const closed = await connectionsFor({
      scenario: 'notificationStreamDrop',
      stream: 'notification',
      event: 'close',
    })
    const closedAt = closed[0]?.at
    expect(closedAt).toBeTruthy()

    await expect
      .poll(async () => {
        const requests = await requestsFor({ scenario: 'notificationStreamDrop' })
        return requests.filter((entry) => entry.path.endsWith('/snapshot') && String(entry.at) >= String(closedAt)).length
      }, { timeout: 7000 })
      .toBeGreaterThan(0)
  })
})
