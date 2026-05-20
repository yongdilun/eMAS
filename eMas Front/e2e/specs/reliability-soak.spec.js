import { expect, test } from '@playwright/test'

import { chatSelectors } from '../fixtures/selectors.js'
import {
  reliabilityConcurrentTurns,
  reliabilityLargeResultAnswer,
  reliabilityLargeResultPrompt,
  reliabilityLongStreamAnswer,
  reliabilityLongStreamPrompt,
  reliabilityLongStreamStepCount,
  reliabilitySlowTimeoutPrompt,
} from '../support/reliabilityScenarios.js'
import {
  assertStableBrowserResources,
  browserResourceSnapshot,
} from '../support/resourceMetrics.js'
import { runReliabilitySoak } from '../support/soakRunner.js'

const mockBaseUrl = `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_FACTORY_AGENT_PORT || 8015)}`
const activeSessionStorageKey = 'factory_agent_active_session_id'

test.setTimeout(360_000)

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

async function connectionsFor(query) {
  const params = new URLSearchParams(query)
  const body = await mockJson(`/__test/sse-connections?${params}`)
  return body.connections || []
}

async function activeSessionId(page) {
  return page.evaluate((key) => window.localStorage.getItem(key), activeSessionStorageKey)
}

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

async function expectComposerReady(page) {
  await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)
  await expect(page.getByRole('dialog', { name: chatSelectors.dialogName }).getByRole('combobox')).toHaveCount(0)
  await expect(page.getByPlaceholder(chatSelectors.composerPlaceholder)).toBeEnabled()
}

async function dialogDoesNotOverflow(page) {
  return page.getByRole('dialog').evaluate((dialog) => dialog.scrollWidth <= dialog.clientWidth + 1)
}

test.describe('Phase 15 reliability, scale, and soak hardening @reliability', () => {
  test.describe.configure({ timeout: 360_000 })

  test('scenario 91: ten concurrent read-only browser sessions complete without cross-session leakage', async ({ browser }) => {
    const contexts = []
    const results = []

    try {
      await Promise.all(
        reliabilityConcurrentTurns.map(async (turn) => {
          const context = await browser.newContext()
          contexts.push(context)
          const page = await context.newPage()
          const startedAt = Date.now()

          await openChat(page)
          await sendPrompt(page, turn.prompt)
          await expect(page.getByText(turn.answer).first()).toBeVisible({ timeout: 20_000 })
          await expectComposerReady(page)

          for (const other of reliabilityConcurrentTurns) {
            if (other.key === turn.key) continue
            await expect(page.getByText(other.answer)).toHaveCount(0)
          }

          results.push({
            key: turn.key,
            session_id: await activeSessionId(page),
            duration_ms: Date.now() - startedAt,
          })
        }),
      )
    } finally {
      await Promise.all(contexts.map((context) => context.close()))
    }

    expect(results).toHaveLength(reliabilityConcurrentTurns.length)
    expect(new Set(results.map((result) => result.session_id)).size).toBe(reliabilityConcurrentTurns.length)
    expect(Math.max(...results.map((result) => result.duration_ms))).toBeLessThan(25_000)
  })

  test('scenario 92: long stream reaches terminal state without duplicate rows, high memory, or stuck busy UI', async ({ page }) => {
    await openChat(page)
    const before = await browserResourceSnapshot(page)

    await sendPrompt(page, reliabilityLongStreamPrompt)
    await expect(page.getByText('Reliability stream step 01').first()).toBeVisible()
    await expect(page.getByText(`Reliability stream step ${String(reliabilityLongStreamStepCount).padStart(2, '0')}`).first()).toBeVisible({
      timeout: 20_000,
    })
    await expect(page.getByText(reliabilityLongStreamAnswer).first()).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)

    const activityToggle = page.getByRole('button', { name: /Run complete.*updates/i }).first()
    await activityToggle.click()
    const activityList = page.locator('ol').filter({ hasText: 'Reliability stream step 01' }).first()
    await expect(activityList.locator('li')).toHaveCount(reliabilityLongStreamStepCount + 1)
    const activityText = await activityList.innerText()
    for (let index = 1; index <= reliabilityLongStreamStepCount; index += 1) {
      const label = `Reliability stream step ${String(index).padStart(2, '0')}`
      expect((activityText.match(new RegExp(label, 'g')) || [])).toHaveLength(1)
    }

    const after = await browserResourceSnapshot(page)
    assertStableBrowserResources(expect, before, after)
    await expectComposerReady(page)

    const sessionId = await activeSessionId(page)
    await expect
      .poll(async () => {
        const closed = await connectionsFor({ session_id: sessionId, stream: 'activity', event: 'close' })
        return closed.length
      })
      .toBeGreaterThan(0)
  })

  test('scenario 93: large structured result and many sources keep stable layout and usable controls', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 820 })
    await openChat(page)
    await sendPrompt(page, reliabilityLargeResultPrompt)

    await expect(page.getByText(/Phase 15 reliability large result rendered 120 rows/i).first()).toBeVisible({
      timeout: 20_000,
    })
    await expect(page.getByRole('table').first()).toBeVisible()
    await expect(page.getByText('Showing 20 of 120 rows.')).toBeVisible()
    await expect(page.getByText('Knowledge sources').last()).toBeVisible()
    await expect(page.getByText('Reliability Source 01 - Source 1').first()).toBeVisible()
    await expect(page.getByText('Reliability Source 24 - Source 24').first()).toBeVisible()

    expect(await dialogDoesNotOverflow(page)).toBe(true)
    await page.getByText('Show details').first().click()
    await expect(page.getByText(/reliability_large_result_fixture/i).first()).toBeVisible()
    await expectComposerReady(page)

    await page.getByRole('button', { name: 'Close' }).first().click()
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toHaveCount(0)
    await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
    await expect(page.getByText(/Phase 15 reliability large result rendered 120 rows/i).first()).toBeVisible()
    expect(await dialogDoesNotOverflow(page)).toBe(true)
  })

  test('scenario 94: slow response shows progress, times out, and keeps retry/cancel controls usable', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, reliabilitySlowTimeoutPrompt)

    await expect(page.getByText(/Understanding your request|slow-response fixture accepted/i).first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Cancel current run' })).toBeVisible()
    await expect(page.getByText(/Factory Agent request timed out/i).first()).toBeVisible({ timeout: 10_000 })
    await expect(page.getByRole('button', { name: 'Retry connection' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Cancel current run' })).toBeVisible()

    await page.getByRole('button', { name: 'Retry connection' }).click()
    await expect(page.getByRole('button', { name: 'Cancel current run' })).toBeVisible()
    await page.getByRole('button', { name: 'Cancel current run' }).click()
    await expect(page.getByText('Run cancelled by operator request.').first()).toBeVisible()
    await expectComposerReady(page)
  })

  test('scenario 95: repeated soak runner completes mocked, seeded, and release smoke suites without leaked ports', async ({}, testInfo) => {
    test.setTimeout(360_000)
    const repeat = Number(process.env.PLAYWRIGHT_RELIABILITY_SOAK_REPEAT || 1)
    const summary = await runReliabilitySoak({
      repeat,
      includeRelease: process.env.PLAYWRIGHT_RELIABILITY_SKIP_RELEASE !== '1',
    })

    await testInfo.attach('phase15-soak-results.json', {
      path: summary.result_path,
      contentType: 'application/json',
    })

    expect(summary.results).toHaveLength(repeat * (summary.include_release ? 3 : 2))
    expect(summary.failures).toEqual([])
    for (const result of summary.results) {
      expect(result.exit_code, `${result.label} iteration ${result.iteration}`).toBe(0)
      expect(result.timed_out, `${result.label} iteration ${result.iteration}`).toBe(false)
      expect(result.ports_closed, `${result.label} iteration ${result.iteration}`).toBe(true)
      expect(result.open_ports, `${result.label} iteration ${result.iteration}`).toEqual([])
    }
  })
})
