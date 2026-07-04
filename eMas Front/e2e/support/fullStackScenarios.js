import { expect } from '@playwright/test'
import { chatSelectors } from '../fixtures/selectors.js'
import { seededRuntimeEnv } from './fullStackEnv.js'

export const seededEnv = seededRuntimeEnv()
export const activeSessionStorageKey = 'factory_agent_active_session_id'

export async function factoryAgentJson(path, options = {}) {
  const response = await fetch(`${seededEnv.factoryAgentBaseUrl}${path}`, {
    method: options.method || 'GET',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  const text = await response.text()
  const body = text ? JSON.parse(text) : null
  if (!response.ok) {
    throw new Error(`Factory Agent ${options.method || 'GET'} ${path} failed: ${response.status} ${text}`)
  }
  return body
}

export async function openChat(page) {
  await page.goto('/')
  await page.waitForLoadState('domcontentloaded')
  const dialog = page.getByRole('dialog', { name: chatSelectors.dialogName })
  const openButton = page.locator('[data-testid="floating-chat-button"]').last()
  const clickStrategies = [
    () => openButton.click(),
    () => openButton.click({ force: true }),
    () => openButton.dispatchEvent('click'),
    () => openButton.evaluate((button) => button.click()),
    async () => {
      const box = await openButton.boundingBox()
      if (!box) throw new Error('AI Assistant launcher did not have a clickable bounding box')
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2)
    },
  ]
  for (let attempt = 0; attempt < clickStrategies.length; attempt += 1) {
    if (await dialog.isVisible().catch(() => false)) return
    await expect(openButton).toBeVisible({ timeout: 10_000 })
    await clickStrategies[attempt]()
    try {
      await expect(dialog).toBeVisible({ timeout: 5_000 })
      return
    } catch (error) {
      if (attempt === clickStrategies.length - 1) throw error
      await page.waitForTimeout(500)
    }
  }
}

export async function sendPrompt(page, prompt) {
  const composer = page.getByPlaceholder(/Ask factory agent|Send a revision|Send a follow-up message/i)
  await expect(composer).toBeEnabled()
  await composer.fill(prompt)
  await page.getByRole('button', { name: chatSelectors.sendButtonName }).click()
  await expect(page.getByText(prompt).first()).toBeVisible()
}

export async function startNewChatSession(page) {
  const previous = await activeSessionId(page, { timeout: 0 })
  await page.getByRole('button', { name: 'New Session' }).click()
  await expect
    .poll(async () => {
      const current = await activeSessionId(page, { timeout: 0 })
      return Boolean(current && current !== previous)
    }, { timeout: 10_000 })
    .toBe(true)
  await expect(page.getByPlaceholder(/Ask factory agent|Send a revision|Send a follow-up message/i)).toBeEnabled()
}

export async function activeSessionId(page, { timeout = 5000 } = {}) {
  const current = await page.evaluate((key) => window.localStorage.getItem(key), activeSessionStorageKey)
  if (current || timeout <= 0) return current
  try {
    await page.waitForFunction((key) => window.localStorage.getItem(key), activeSessionStorageKey, { timeout })
  } catch {
    return null
  }
  return page.evaluate((key) => window.localStorage.getItem(key), activeSessionStorageKey)
}

export async function snapshotForPage(page) {
  let sessionId = await activeSessionId(page)
  if (!sessionId) {
    await page.waitForFunction((key) => window.localStorage.getItem(key), activeSessionStorageKey, { timeout: 5000 })
    sessionId = await activeSessionId(page)
  }
  if (!sessionId) throw new Error('No active Factory Agent session id in localStorage')
  return factoryAgentJson(`/sessions/${sessionId}/snapshot`)
}

export async function pendingApprovalsForPage(page) {
  let sessionId = await activeSessionId(page)
  if (!sessionId) {
    await page.waitForFunction((key) => window.localStorage.getItem(key), activeSessionStorageKey, { timeout: 5000 })
    sessionId = await activeSessionId(page)
  }
  if (!sessionId) throw new Error('No active Factory Agent session id in localStorage')
  return factoryAgentJson(`/approvals/pending?session_id=${encodeURIComponent(sessionId)}`)
}

export async function waitForSessionStatus(page, expectedStatus, { timeout = 30_000 } = {}) {
  await expect
    .poll(async () => {
      const snapshot = await snapshotForPage(page)
      return snapshot.session.status
    }, { timeout })
    .toBe(expectedStatus)
}

export function textIndex(haystack, needle) {
  const idx = String(haystack || '').indexOf(needle)
  expect(idx, `Expected to find "${needle}" in text`).toBeGreaterThanOrEqual(0)
  return idx
}
