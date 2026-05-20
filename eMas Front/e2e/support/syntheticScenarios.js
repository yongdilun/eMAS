import { expect } from '@playwright/test'

import { chatSelectors } from '../fixtures/selectors.js'
import { releaseJson, resetReleaseFaults, setReleaseFaults } from './releaseScenarios.js'
import { syntheticRuntimeEnv } from './syntheticEnv.js'

export const syntheticEnv = syntheticRuntimeEnv()
export const activeSessionStorageKey = 'factory_agent_active_session_id'

export async function syntheticJson(path, options = {}) {
  const response = await fetch(`${syntheticEnv.baseUrl}${path}`, {
    method: options.method || 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(syntheticEnv.authToken ? { Authorization: `Bearer ${syntheticEnv.authToken}` } : {}),
      ...(options.headers || {}),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  const text = await response.text()
  let body = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = text
  }
  if (!response.ok && !options.allowFailure) {
    throw new Error(`Synthetic ${options.method || 'GET'} ${path} failed: ${response.status} ${text}`)
  }
  return { response, body, text }
}

export async function resetSyntheticFaults() {
  if (syntheticEnv.live) return
  await resetReleaseFaults()
}

export async function setSyntheticFaults(faults) {
  if (syntheticEnv.live) throw new Error('Synthetic fault toggles are disabled in live production/staging mode.')
  return setReleaseFaults(faults)
}

export async function openChat(page) {
  await page.goto('/')
  await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
  await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()
}

export async function sendPrompt(page, prompt) {
  const composer = page.getByPlaceholder(chatSelectors.composerPlaceholder)
  await expect(composer).toBeEnabled()
  await composer.fill(prompt)
  await page.getByRole('button', { name: chatSelectors.sendButtonName }).click()
  await expect(page.getByText(prompt)).toBeVisible()
}

export async function activeSessionId(page) {
  return page.evaluate((key) => window.localStorage.getItem(key), activeSessionStorageKey)
}

export async function snapshotForPage(page) {
  let sessionId = await activeSessionId(page)
  if (!sessionId) {
    await page.waitForFunction((key) => window.localStorage.getItem(key), activeSessionStorageKey, { timeout: 5000 })
    sessionId = await activeSessionId(page)
  }
  if (!sessionId) throw new Error('No active Factory Agent session id in localStorage')
  const { body } = await syntheticJson(`/agent/sessions/${sessionId}/snapshot`)
  return body
}

export async function waitForCompletion(page, timeout) {
  await expect(page.getByText('Run complete')).toBeVisible({ timeout })
  const snapshot = await snapshotForPage(page)
  const timeline = Array.isArray(snapshot.timeline) ? snapshot.timeline : []
  const completed = timeline.find((item) => item?.role === 'assistant' || item?.type === 'assistant_message') || timeline.at(-1)
  const text = [
    completed?.content,
    completed?.summary,
    completed?.message,
    completed?.details?.summary,
    completed?.details?.answer,
  ]
    .filter(Boolean)
    .join('\n')
  const dialogText = await page.getByRole('dialog').textContent().catch(() => '')
  return { snapshot, finalText: text || dialogText || '', completed }
}

export async function releaseHarnessJson(path, options = {}) {
  if (syntheticEnv.live) throw new Error('Release harness endpoints are disabled in live production/staging mode.')
  return releaseJson(path, options)
}
