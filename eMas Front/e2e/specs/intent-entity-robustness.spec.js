import { expect, test } from '@playwright/test'

import { chatSelectors } from '../fixtures/selectors.js'
import {
  manualPromptBankEntries,
  phase18MockRagAnswer,
  phase18MockRagSource,
} from '../support/intentEntityScenarios.js'

async function openChat(page) {
  await page.goto('/')
  await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
  await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()
}

async function sendPrompt(page, prompt) {
  const composer = page.getByPlaceholder(chatSelectors.composerPlaceholder)
  await expect(composer).toBeEnabled()
  await composer.fill(prompt)
  await page.getByRole('button', { name: chatSelectors.sendButtonName }).click()
  await expect(page.getByText(prompt)).toBeVisible()
}

test.describe('Phase 18 intent/entity prompt robustness @intent-entity', () => {
  test('scenario 106/114/115: manual LOTO prompt bank routes to RAG without repeated machine clarification', async ({ page }) => {
    const entry = manualPromptBankEntries.find((item) => item.id === 'phase18-loto-m-cnc-01')
    expect(entry).toBeTruthy()

    await openChat(page)
    await sendPrompt(page, entry.prompt)

    await expect(page.getByText(phase18MockRagAnswer).first()).toBeVisible()
    await expect(page.getByText('Knowledge sources')).toBeVisible()
    await expect(page.getByText(phase18MockRagSource.title).first()).toBeVisible()
    await expect(page.getByText(/Which machine ID/i)).toHaveCount(0)
    await expect(page.getByText(/provide the exact machine/i)).toHaveCount(0)
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)
  })
})
