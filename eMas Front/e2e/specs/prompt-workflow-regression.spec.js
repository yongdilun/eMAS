import { expect, test } from '@playwright/test'

import { chatSelectors } from '../fixtures/selectors.js'
import {
  phase19LotoRegressionEntries,
  phase19UnknownDiagnostic,
  phase19UnknownPrompt,
} from '../support/promptRegressionScenarios.js'
import {
  phase18MockRagAnswer,
} from '../support/intentEntityScenarios.js'

const attentionDiagnosticVisiblePattern = /Factory Agent chat could not start|Prompt route not matched|Factory Agent needs attention/i

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

async function visibleDialogText(page) {
  return page.getByRole('dialog', { name: chatSelectors.dialogName }).evaluate((node) => node.innerText || '')
}

test.describe('Phase 19 prompt regression diagnostics @prompt-regression', () => {
  test('scenario 116/124: LOTO wording matrix routes successfully without generic attention diagnostics', async ({ page }) => {
    test.setTimeout(120_000)
    expect(phase19LotoRegressionEntries.length).toBeGreaterThanOrEqual(5)

    for (const [index, entry] of phase19LotoRegressionEntries.entries()) {
      if (index > 0) {
        await page.getByRole('button', { name: 'New Session' }).click()
      } else {
        await openChat(page)
      }
      await sendPrompt(page, entry.source_prompt)

      await expect.poll(async () => (await visibleDialogText(page)).includes(phase18MockRagAnswer), { timeout: 30_000 }).toBe(true)
      await expect(page.getByText(/Which machine ID/i)).toHaveCount(0)
      await expect(page.getByText(attentionDiagnosticVisiblePattern)).toHaveCount(0)
      await expect(page.getByText('Run complete').last()).toBeVisible()
    }
  })

  test('scenario 124: true unknown prompt shows the generic Factory Agent attention diagnostic', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, phase19UnknownPrompt)

    await expect(page.getByText(attentionDiagnosticVisiblePattern).first()).toBeVisible()
    await expect(page.getByText(phase19UnknownDiagnostic).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toHaveCount(0)
  })
})
