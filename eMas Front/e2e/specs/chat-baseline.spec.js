import { expect, test } from '@playwright/test'

test.describe('Factory Agent chat baseline', () => {
  test('app opens dashboard and floating chat control is reachable by an accessible selector', async ({ page }) => {
    await page.goto('/')

    await expect(page.getByText('Dashboard Overview')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Open AI Assistant' })).toBeVisible()
  })

  test('chat modal opens and shows empty state plus enabled composer', async ({ page }) => {
    await page.goto('/')

    await page.getByRole('button', { name: 'Open AI Assistant' }).click()

    await expect(page.getByRole('dialog', { name: 'AI Assistant' })).toBeVisible()
    await expect(page.getByText('Start a session from the sidebar.')).toBeVisible()
    await expect(page.getByText('Ask for operations tasks requiring safe approvals.')).toBeVisible()
    await expect(page.getByRole('dialog', { name: 'AI Assistant' }).getByRole('combobox')).toHaveCount(0)
    await expect(page.getByPlaceholder('Ask factory agent...')).toBeEnabled()
    await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled()
  })
})
