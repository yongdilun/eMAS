import { expect, test } from '@playwright/test'
import { chatSelectors } from '../fixtures/selectors.js'
import {
  backendUnavailablePrompt,
  emptyAssistantFallbackAnswer,
  emptyAssistantPrompt,
  machineStatusAnswer,
  machineStatusPrompt,
} from '../fixtures/factoryAgentFixtures.js'

const mockBaseUrl = `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_FACTORY_AGENT_PORT || 8015)}`

async function requestsForPrompt(prompt) {
  const response = await fetch(`${mockBaseUrl}/__test/requests?contains=${encodeURIComponent(prompt)}`)
  if (!response.ok) throw new Error(`Could not read mock requests: ${response.status}`)
  const body = await response.json()
  return body.requests || []
}

async function sendChatPrompt(page, prompt) {
  const composer = page.getByPlaceholder(chatSelectors.composerPlaceholder)
  await expect(composer).toBeEnabled()
  await composer.fill(prompt)
  await page.getByRole('button', { name: chatSelectors.sendButtonName }).click()
  await expect(page.getByText(prompt)).toBeVisible()
}

test.describe('Factory Agent chat scenario fixtures', () => {
  test('plan creation 503 shows backend unavailable without fake success', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()

    await sendChatPrompt(page, backendUnavailablePrompt)

    await expect(page.getByText('Factory Agent backend unavailable')).toBeVisible()
    await expect(page.getByText('Service temporarily unavailable. Please retry shortly.')).toBeVisible()
    await expect(page.getByText('Run complete')).toHaveCount(0)
    await expect(page.getByText(machineStatusAnswer)).toHaveCount(0)

    await expect
      .poll(async () => {
        const requests = await requestsForPrompt(backendUnavailablePrompt)
        return requests.some((entry) => entry.path.endsWith('/plans') && entry.status === 503)
      })
      .toBe(true)

    const requests = await requestsForPrompt(backendUnavailablePrompt)
    expect(requests.some((entry) => entry.path.endsWith('/execute'))).toBe(false)
  })

  test('completed empty assistant content does not reuse the previous answer', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()

    await sendChatPrompt(page, machineStatusPrompt)
    await expect(page.getByText(machineStatusAnswer).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    const existingMachineAnswerCount = await page.getByText(machineStatusAnswer).count()

    await sendChatPrompt(page, emptyAssistantPrompt)

    await expect(page.getByText(emptyAssistantFallbackAnswer).last()).toBeVisible()
    await expect(page.getByText(machineStatusAnswer)).toHaveCount(existingMachineAnswerCount)

    await expect
      .poll(async () => {
        const requests = await requestsForPrompt(emptyAssistantPrompt)
        return requests.some(
          (entry) => entry.scenario_name === 'emptyCompletedAnswer' && entry.path.endsWith('/execute') && entry.status === 200,
        )
      })
      .toBe(true)
  })
})
