import { expect, test } from '@playwright/test'
import { chatSelectors } from '../fixtures/selectors.js'
import { machineStatusAnswer, machineStatusPrompt } from '../fixtures/factoryAgentFixtures.js'

test.describe('Factory Agent chat happy path', () => {
  test('user sends a machine status request and sees the completed assistant answer', async ({ page }) => {
    await page.goto('/')

    await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()

    const composer = page.getByPlaceholder(chatSelectors.composerPlaceholder)
    await expect(composer).toBeEnabled()

    await composer.fill(machineStatusPrompt)
    await page.getByRole('button', { name: chatSelectors.sendButtonName }).click()

    await expect(page.getByText(machineStatusPrompt)).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toBeVisible()

    await expect(page.getByText(machineStatusAnswer).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName }).getByRole('combobox')).toHaveCount(0)
    await expect(page.getByPlaceholder(chatSelectors.composerPlaceholder)).toBeEnabled()
  })
})
