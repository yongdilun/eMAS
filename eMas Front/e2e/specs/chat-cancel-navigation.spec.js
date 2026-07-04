import { expect, test } from '@playwright/test'
import { chatSelectors } from '../fixtures/selectors.js'
import {
  cancelRunPrompt,
  cancelledRunMessage,
  disconnectPrompt,
  machineStatusAnswer,
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

async function connectionsFor(query) {
  const params = new URLSearchParams(query)
  const body = await getMockJson(`/__test/sse-connections?${params}`)
  return body.connections || []
}

async function activeSessionId(page) {
  return page.evaluate(() => window.localStorage.getItem('factory_agent_active_session_id'))
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

test.describe('Factory Agent chat cancel and disconnect scenarios', () => {
  test('cancel active run calls /cancel and returns to a non-busy cancelled state', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, cancelRunPrompt)

    const cancelButton = page.getByRole('button', { name: 'Cancel current run' })
    await expect(cancelButton).toBeVisible()
    await cancelButton.click()

    await expect(page.getByText(cancelledRunMessage).first()).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Cancel current run' })).toHaveCount(0)
    await expect(page.getByText('Run complete')).toHaveCount(0)
    await expect(page.getByText(machineStatusAnswer)).toHaveCount(0)

    await expect
      .poll(async () => {
        const requests = await requestsFor({ scenario: 'cancellableActiveRun' })
        return requests.some((entry) => entry.path.endsWith('/cancel') && entry.status === 200)
      })
      .toBe(true)
  })

  test('SO-016 closing the modal during an active stream records EventSource disconnect @sse', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, disconnectPrompt)
    const sessionId = await activeSessionId(page)
    await expect(page.getByText('Understanding your request').first()).toBeVisible()

    let observedStreams = []
    await expect
      .poll(async () => {
        const streams = []
        for (const stream of ['notification', 'activity']) {
          const connections = await connectionsFor({
            session_id: sessionId,
            stream,
            event: 'open',
          })
          for (const connection of connections) {
            if (connection.connection_id) streams.push({ stream, connectionId: connection.connection_id })
          }
        }
        observedStreams = streams
        return streams.length
      })
      .toBeGreaterThan(0)

    await page.getByRole('button', { name: 'Close' }).first().click()
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toHaveCount(0)

    for (const { stream, connectionId } of observedStreams) {
      await expect
        .poll(async () => {
          const connections = await connectionsFor({
            session_id: sessionId,
            stream,
            event: 'close',
          })
          return connections.some((connection) => connection.connection_id === connectionId)
        })
        .toBe(true)
    }
  })
})
