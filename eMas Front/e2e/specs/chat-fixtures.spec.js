import { expect, test } from '@playwright/test'
import { chatSelectors } from '../fixtures/selectors.js'
import {
  backendUnavailablePrompt,
  emptyAssistantFallbackAnswer,
  emptyAssistantPrompt,
  machineStatusAnswer,
  machineStatusPrompt,
  responseDocumentRendererPrompt,
  typedKnowledgeSourcePrompt,
  typedPendingApprovalPrompt,
  typedRejectedPrompt,
} from '../fixtures/factoryAgentFixtures.js'

const mockBaseUrl = `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_FACTORY_AGENT_PORT || 8015)}`
const backendUnavailableVisiblePattern = /Factory Agent is disconnected|Backend unavailable/i
const attentionDiagnosticVisiblePattern = /Factory Agent chat could not start|Prompt route not matched|Factory Agent needs attention/i

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

    await expect(page.getByText(backendUnavailableVisiblePattern).first()).toBeVisible()
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
    await expect(page.getByText('Execution completed.')).toHaveCount(0)
    await expect(page.getByText(attentionDiagnosticVisiblePattern)).toHaveCount(0)

    await expect
      .poll(async () => {
        const requests = await requestsForPrompt(emptyAssistantPrompt)
        return requests.some(
          (entry) => entry.scenario_name === 'emptyCompletedAnswer' && entry.path.endsWith('/execute') && entry.status === 200,
        )
      })
      .toBe(true)
  })

  test('typed rejected presentation suppresses stale success details', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()

    await sendChatPrompt(page, typedRejectedPrompt)

    await expect(page.getByText('Operator rejected the requested priority update.').first()).toBeVisible()
    await expect(page.getByText('Run complete')).toHaveCount(0)
    await expect(page.getByText(/All requested changes completed/i)).toHaveCount(0)
    await expect(page.getByText(/Updated \*\*99\*\* jobs successfully/i)).toHaveCount(0)
  })

  test('typed pending approval remains pending despite stale completion text', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()

    await sendChatPrompt(page, typedPendingApprovalPrompt)

    await expect(page.getByText('Review the proposed priority update batch.').first()).toBeVisible()
    await expect(page.getByText('Approval required')).toBeVisible()
    await expect(page.getByText('Operator review required for one low-priority job.')).toBeVisible()
    await expect(page.getByText('Run complete')).toHaveCount(0)
    await expect(page.getByText(/All requested changes completed/i)).toHaveCount(0)
  })

  test('typed knowledge answer renders source metadata', async ({ page }) => {
    test.setTimeout(45_000)
    await page.goto('/')
    await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()

    await sendChatPrompt(page, typedKnowledgeSourcePrompt)

    await expect(page.getByText('Use the cited LOTO procedure before lockout.').last()).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText('Knowledge sources').last()).toBeVisible()
    await expect(page.getByText('Typed LOTO Procedure - Source 1').last()).toBeVisible()
  })

  test('response_document renderer keeps completed evidence while approval 2 is pending', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()

    await sendChatPrompt(page, responseDocumentRendererPrompt)

    await expect(page.getByText(/Updated 10 jobs from medium to high/).first()).toBeVisible()
    await expect(page.getByText('Update 11 jobs from high to low').first()).toBeVisible()
    await expect(page.getByText('JOB-SEED-002').first()).toBeVisible()
    await expect(page.getByText('+1 more').first()).toBeVisible()
    await expect(page.getByText(/All requested changes completed/i)).toHaveCount(0)
    await expect(page.getByText('Review and edit request')).toHaveCount(0)
  })
})
