import { expect, test } from '@playwright/test'
import { chatSelectors } from '../fixtures/selectors.js'
import {
  activitySseAnswer,
  activitySsePrompt,
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

test.describe('Factory Agent chat SSE activity stream', () => {
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

    await expect(page.getByText(activitySseAnswer)).toHaveCount(0, { timeout: 150 })
    await expect(page.getByText(/heartbeat/i)).toHaveCount(0)

    await expect(page.getByText(activitySseAnswer).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)

    const notificationConnections = await connectionsFor({
      scenario: 'activitySseOrdered',
      stream: 'notification',
      event: 'open',
    })
    expect(notificationConnections.length).toBeGreaterThan(0)

    const requests = await requestsFor({ scenario: 'activitySseOrdered' })
    expect(requests.some((entry) => entry.path.endsWith('/events/activity'))).toBe(true)
    expect(requests.some((entry) => entry.path.endsWith('/snapshot'))).toBe(true)
  })
})
