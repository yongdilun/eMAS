import { expect, test } from '@playwright/test'
import { chatSelectors } from '../fixtures/selectors.js'
import { responseDocumentTrafficPrompt } from '../fixtures/factoryAgentFixtures.js'

async function sendChatPrompt(page, prompt) {
  const composer = page.getByPlaceholder(chatSelectors.composerPlaceholder)
  await expect(composer).toBeEnabled()
  await composer.fill(prompt)
  await page.getByRole('button', { name: chatSelectors.sendButtonName }).click()
  await expect(page.getByText(prompt)).toBeVisible()
}

async function installStaleFlickerProbe(page) {
  await page.evaluate(() => {
    window.__responseDocumentTrafficProbe = {
      finalSeen: false,
      staleAfterFinal: false,
      samples: [],
    }
    const check = () => {
      const text = document.body?.innerText || ''
      const probe = window.__responseDocumentTrafficProbe
      if (!probe) return
      if (text.includes('Done. I updated 21 jobs across 2 approved business changes.')) {
        probe.finalSeen = true
      }
      if (
        probe.finalSeen &&
        (
          text.includes('Waiting for approval 2') ||
          text.includes('Stale failure: database unavailable.') ||
          text.includes('Response document invalid')
        )
      ) {
        probe.staleAfterFinal = true
        probe.samples.push(text.slice(0, 2000))
      }
    }
    const observer = new MutationObserver(check)
    observer.observe(document.body, { childList: true, subtree: true, characterData: true })
    window.__responseDocumentTrafficProbeObserver = observer
    check()
  })
}

test.describe('Factory Agent response_document revision busy traffic', () => {
  test('response_document revision event storm busy traffic ignores stale revision updates', async ({ page }) => {
    await page.goto('/')
    await installStaleFlickerProbe(page)
    await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()

    await sendChatPrompt(page, responseDocumentTrafficPrompt)

    await expect(page.getByText('Done. I updated 21 jobs across 2 approved business changes.').first()).toBeVisible()
    await expect(page.getByText('Medium -> High: 10 jobs')).toHaveCount(1)
    await expect(page.getByText('Original High -> Low: 11 jobs')).toHaveCount(1)

    await expect(page.getByText('Stale failure: database unavailable.')).toHaveCount(0)
    await expect(page.getByText('Response document invalid')).toHaveCount(0)
    await expect(page.getByText('Approval required')).toHaveCount(0)
    await expect(page.getByText('Waiting for approval 2')).toHaveCount(0)

    await page.waitForTimeout(900)
    await expect(page.getByText('Done. I updated 21 jobs across 2 approved business changes.').first()).toBeVisible()
    await expect(page.getByText('Stale failure: database unavailable.')).toHaveCount(0)
    await expect(page.getByText('Response document invalid')).toHaveCount(0)
    await expect(page.getByText('Approval required')).toHaveCount(0)
    await expect(page.getByText('Waiting for approval 2')).toHaveCount(0)

    const probe = await page.evaluate(() => window.__responseDocumentTrafficProbe)
    expect(probe.finalSeen).toBe(true)
    expect(probe.staleAfterFinal, probe.samples?.[0] || 'stale response document text appeared after final success').toBe(false)
  })
})
