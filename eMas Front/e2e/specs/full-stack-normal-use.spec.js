import { expect, test } from '../support/seededArtifacts.js'
import {
  activeSessionId,
  factoryAgentJson,
  openChat,
  sendPrompt,
} from '../support/fullStackScenarios.js'
import { chatSelectors } from '../fixtures/selectors.js'

test.describe('Phase 13 seeded normal-use checks @normal-use', () => {
  test('scenario 83 @normal-use: seeded reload restores completed RAG answer, sources, and idle composer', async ({ page }) => {
    const prompt = 'Use seeded LOTO guidance to explain hazardous energy lockout for Phase 13 normal-use reload'

    await openChat(page)
    await sendPrompt(page, prompt)
    await expect(page.getByText(/Controlled seeded RAG answer/i).first()).toBeVisible()
    await expect(page.getByText('Knowledge sources').first()).toBeVisible()
    await expect(page.getByText('Seeded General LOTO Guidance').first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)
    const sessionId = await activeSessionId(page)

    await page.reload()
    await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()

    await expect(page.getByText(prompt)).toBeVisible()
    await expect(page.getByText(/Controlled seeded RAG answer/i).first()).toBeVisible()
    await expect(page.getByText('Knowledge sources').first()).toBeVisible()
    await expect(page.getByText('Seeded General LOTO Guidance').first()).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName }).getByRole('combobox')).toHaveCount(0)
    await expect(page.getByPlaceholder(chatSelectors.composerPlaceholder)).toBeEnabled()

    const snapshot = await factoryAgentJson(`/sessions/${sessionId}/snapshot`)
    expect(snapshot.session.status).toBe('COMPLETED')
  })
})
