import { expect, test } from '@playwright/test'

import { chatSelectors } from '../fixtures/selectors.js'
import {
  phase19LotoRegressionEntries,
  phase19UnknownDiagnostic,
  phase19UnknownPrompt,
} from '../support/promptRegressionScenarios.js'
import {
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

test.describe('Phase 19 prompt regression diagnostics @prompt-regression', () => {
  test('scenario 116/124: LOTO wording matrix routes successfully without generic attention diagnostics', async ({ page }) => {
    expect(phase19LotoRegressionEntries.length).toBeGreaterThanOrEqual(5)

    for (const [index, entry] of phase19LotoRegressionEntries.entries()) {
      if (index > 0) {
        await page.getByRole('button', { name: 'New Session' }).click()
      } else {
        await openChat(page)
      }
      await sendPrompt(page, entry.source_prompt)

      await expect(page.getByText(phase18MockRagAnswer).first()).toBeVisible()
      await expect(page.getByText('Knowledge sources')).toBeVisible()
      await expect(page.getByText(phase18MockRagSource.title).first()).toBeVisible()
      await expect(page.getByText(/Which machine ID/i)).toHaveCount(0)
      await expect(page.getByText('Factory Agent needs attention')).toHaveCount(0)
      await expect(page.getByText('Run complete')).toBeVisible()
    }
  })

  test('scenario 124: true unknown prompt shows the generic Factory Agent attention diagnostic', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, phase19UnknownPrompt)

    await expect(page.getByText('Factory Agent needs attention')).toBeVisible()
    await expect(page.getByText(phase19UnknownDiagnostic).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toHaveCount(0)
  })
})
