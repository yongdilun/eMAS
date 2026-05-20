import { expect, test } from '@playwright/test'
import { chatSelectors } from '../fixtures/selectors.js'
import {
  backendUnavailablePrompt,
  cancelRunPrompt,
  cancelledRunMessage,
} from '../fixtures/factoryAgentFixtures.js'
import {
  normalUseLifecycleCompletedPrompt,
  normalUsePlanModeAnswer,
  normalUsePlanModeDraftPrompt,
  normalUsePlanModeFinalPrompt,
  normalUseTurns,
} from '../support/normalUseScenarios.js'

const mockBaseUrl = `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_FACTORY_AGENT_PORT || 8015)}`
const activeSessionStorageKey = 'factory_agent_active_session_id'
const backendUnavailableVisiblePattern = /Factory Agent is disconnected|Backend unavailable/i

async function mockJson(path, options = {}) {
  const response = await fetch(`${mockBaseUrl}${path}`, {
    method: options.method || 'GET',
    headers: { 'Content-Type': 'application/json' },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  const text = await response.text()
  const body = text ? JSON.parse(text) : null
  if (!response.ok) throw new Error(`Mock ${options.method || 'GET'} ${path} failed: ${response.status} ${text}`)
  return body
}

async function requestsFor(query) {
  const params = new URLSearchParams(query)
  const body = await mockJson(`/__test/requests?${params}`)
  return body.requests || []
}

async function connectionsFor(query) {
  const params = new URLSearchParams(query)
  const body = await mockJson(`/__test/sse-connections?${params}`)
  return body.connections || []
}

async function activeSessionId(page) {
  return page.evaluate((key) => window.localStorage.getItem(key), activeSessionStorageKey)
}

async function setActiveSessionId(page, sessionId) {
  await page.evaluate(
    ({ key, value }) => window.localStorage.setItem(key, value),
    { key: activeSessionStorageKey, value: sessionId },
  )
}

async function openAssistant(page) {
  await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
  await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()
}

async function openChat(page) {
  await page.goto('/')
  await openAssistant(page)
}

async function closeChat(page) {
  await page.getByRole('button', { name: 'Close' }).first().click()
  await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toHaveCount(0)
}

async function expectComposerReady(page) {
  await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)
  await expect(page.getByRole('dialog', { name: chatSelectors.dialogName }).getByRole('combobox')).toHaveCount(0)
  await expect(page.getByPlaceholder(chatSelectors.composerPlaceholder)).toBeEnabled()
}

async function sendPrompt(page, prompt) {
  const composer = page.getByPlaceholder(chatSelectors.composerPlaceholder)
  await expect(composer).toBeEnabled()
  await composer.fill(prompt)
  await page.getByRole('button', { name: chatSelectors.sendButtonName }).click()
  await expect(page.getByText(prompt)).toBeVisible()
}

function visibleAnswerText(answer) {
  return String(answer || '').replace(/\s*\[\^\d+\]/g, '').trim()
}

async function expectAnyVisibleText(page, textOrRegex) {
  const locator = page.getByText(textOrRegex)
  await expect
    .poll(async () => {
      const count = await locator.count()
      for (let index = 0; index < count; index += 1) {
        if (await locator.nth(index).isVisible()) return true
      }
      return false
    })
    .toBe(true)
}

test.describe('Phase 13 normal-use hardening @normal-use', () => {
  test('scenario 81: ten-turn operator chat keeps transcript, sources, details, and idle composer state', async ({ page }) => {
    test.slow()
    await openChat(page)

    let firstSessionId = null
    const seenAnswers = []
    for (const turn of normalUseTurns) {
      await sendPrompt(page, turn.prompt)
      await expectAnyVisibleText(page, visibleAnswerText(turn.answer))
      await expectComposerReady(page)

      const currentSessionId = await activeSessionId(page)
      if (!firstSessionId) firstSessionId = currentSessionId
      expect(currentSessionId).toBe(firstSessionId)

      seenAnswers.push(turn.answer)
      for (const answer of seenAnswers) {
        await expectAnyVisibleText(page, visibleAnswerText(answer))
      }
    }

    await expect(page.getByRole('table').first()).toBeVisible()
    await expect(page.getByText('Knowledge sources').first()).toBeVisible()
    await expect(page.getByText('Normal Use LOTO Procedure').first()).toBeVisible()

    await page.getByText('Show details').last().click()
    await expectAnyVisibleText(page, /Reason: normal_use_fixture/)
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName }).getByRole('combobox')).toHaveCount(0)
    await expect(page.getByText(/Factory Agent is disconnected|Backend unavailable|Run cancelled by operator request/i)).toHaveCount(0)
  })

  test('SO-019 scenario 82: many historical sessions load, select, and restore the correct transcript', async ({ page }, testInfo) => {
    const runId = `w${testInfo.workerIndex}-${Date.now()}`
    const seeded = await mockJson('/__test/normal-use-history', {
      method: 'POST',
      body: { run_id: runId },
    })

    await openChat(page)
    const targetButton = page.getByRole('button', { name: `Open session ${seeded.target.name}` })
    await expect(targetButton).toBeVisible()
    await targetButton.click()

    await expect(page.getByRole('heading', { name: seeded.target.name })).toBeVisible()
    await expect(targetButton).toHaveAttribute('aria-current', 'page')
    await expect(page.getByText(seeded.target_prompt)).toBeVisible()
    await expectAnyVisibleText(page, seeded.target_answer)
    await expect(page.getByText(seeded.decoy_answer)).toHaveCount(0)
    await expect(page.getByText('Knowledge sources').first()).toBeVisible()
    await expectComposerReady(page)
  })

  test('SO-019 scenario 83: browser reload restores completed answer, sources, details, and non-busy composer', async ({ page }) => {
    const lotoTurn = normalUseTurns.find((turn) => turn.key === 'loto-guidance')
    await openChat(page)
    await sendPrompt(page, lotoTurn.prompt)

    await expectAnyVisibleText(page, visibleAnswerText(lotoTurn.answer))
    await expect(page.getByText('Knowledge sources').first()).toBeVisible()
    await expect(page.getByText('Normal Use LOTO Procedure').first()).toBeVisible()
    await expectComposerReady(page)
    const sessionIdBeforeReload = await activeSessionId(page)

    await page.getByText('Show details').first().click()
    await expectAnyVisibleText(page, /normal_use_fixture/)

    await page.reload()
    await openAssistant(page)

    await expect(page.getByText(lotoTurn.prompt)).toBeVisible()
    await expectAnyVisibleText(page, visibleAnswerText(lotoTurn.answer))
    await expect(page.getByText('Knowledge sources').first()).toBeVisible()
    await expect(page.getByText('Normal Use LOTO Procedure').first()).toBeVisible()
    await expectComposerReady(page)
    expect(await activeSessionId(page)).toBe(sessionIdBeforeReload)
  })

  test('scenario 84: edited draft submits once with final text in normal mode', async ({ page }) => {
    await page.goto('/')
    await page.evaluate(() => window.localStorage.setItem('factory_agent_message_mode', 'plan'))
    await openAssistant(page)

    const composer = page.getByPlaceholder(chatSelectors.composerPlaceholder)
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName }).getByRole('combobox')).toHaveCount(0)
    await composer.fill(normalUsePlanModeDraftPrompt)
    await composer.fill(normalUsePlanModeFinalPrompt)
    await page.getByRole('button', { name: chatSelectors.sendButtonName }).click()

    await expect(page.getByText(normalUsePlanModeFinalPrompt)).toBeVisible()
    await expect(page.getByText(normalUsePlanModeAnswer).first()).toBeVisible()
    await expectComposerReady(page)
    await expect(composer).toHaveValue('')

    const finalRequests = await requestsFor({ contains: normalUsePlanModeFinalPrompt })
    const finalMessageRequests = finalRequests.filter((entry) => entry.path.endsWith('/messages'))
    expect(finalMessageRequests).toHaveLength(1)
    expect(finalMessageRequests[0].body.content).toBe(normalUsePlanModeFinalPrompt)
    expect(finalMessageRequests[0].body.mode).toBe('normal')

    const draftRequests = await requestsFor({ contains: normalUsePlanModeDraftPrompt })
    expect(draftRequests.filter((entry) => entry.path.endsWith('/messages'))).toHaveLength(0)
  })

  test('scenario 85: repeated modal open and close across completed, failed, and cancelled sessions stays clean', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, normalUseLifecycleCompletedPrompt)
    await expectAnyVisibleText(page, /Phase 13 lifecycle completed session/i)
    await expectComposerReady(page)
    const completedId = await activeSessionId(page)
    await closeChat(page)

    await openAssistant(page)
    await expectAnyVisibleText(page, /Phase 13 lifecycle completed session/i)
    await expect(page.getByText(backendUnavailableVisiblePattern)).toHaveCount(0)
    await expectComposerReady(page)
    await page.getByRole('button', { name: 'New Session' }).click()
    await sendPrompt(page, backendUnavailablePrompt)
    await expect(page.getByText(backendUnavailableVisiblePattern).first()).toBeVisible()
    await expect(page.getByText('Service temporarily unavailable. Please retry shortly.')).toBeVisible()
    await expectComposerReady(page)
    const failedId = await activeSessionId(page)
    await closeChat(page)

    await openAssistant(page)
    await page.getByRole('button', { name: 'New Session' }).click()
    await sendPrompt(page, cancelRunPrompt)
    const cancelledId = await activeSessionId(page)
    await expect
      .poll(async () => {
        const opened = await connectionsFor({ session_id: cancelledId, stream: 'notification', event: 'open' })
        return opened.length
      })
      .toBeGreaterThan(0)
    await page.getByRole('button', { name: 'Cancel current run' }).click()
    await expect(page.getByText(cancelledRunMessage).first()).toBeVisible()
    await expectComposerReady(page)
    await closeChat(page)

    await expect
      .poll(async () => {
        const closed = await connectionsFor({ session_id: cancelledId, stream: 'notification', event: 'close' })
        return closed.length
      })
      .toBeGreaterThan(0)

    await setActiveSessionId(page, completedId)
    await openAssistant(page)
    await expectAnyVisibleText(page, /Phase 13 lifecycle completed session/i)
    await expect(page.getByText(backendUnavailableVisiblePattern)).toHaveCount(0)
    await expect(page.getByText(cancelledRunMessage)).toHaveCount(0)
    await expectComposerReady(page)
    await closeChat(page)

    await setActiveSessionId(page, failedId)
    await openAssistant(page)
    await expect(page.getByText('Service temporarily unavailable. Please retry shortly.').first()).toBeVisible()
    await expect(page.getByText(/Phase 13 lifecycle completed session/i)).toHaveCount(0)
    await expectComposerReady(page)
    await closeChat(page)

    await setActiveSessionId(page, cancelledId)
    await openAssistant(page)
    await expect(page.getByText(cancelledRunMessage).first()).toBeVisible()
    await expect(page.getByText(backendUnavailableVisiblePattern)).toHaveCount(0)
    await expectComposerReady(page)
  })
})
