import fs from 'node:fs'
import path from 'node:path'

import { expect } from '@playwright/test'

import { chatSelectors } from '../fixtures/selectors.js'
import { releaseRuntimeEnv } from './releaseEnv.js'

export const releaseEnv = releaseRuntimeEnv()
export const activeSessionStorageKey = 'factory_agent_active_session_id'

export async function releaseJson(path, options = {}) {
  const response = await fetch(`${releaseEnv.releaseBaseUrl}${path}`, {
    method: options.method || 'GET',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
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
    throw new Error(`Release ${options.method || 'GET'} ${path} failed: ${response.status} ${text}`)
  }
  return { response, body, text }
}

export async function factoryAgentJson(path, options = {}) {
  const response = await fetch(`${releaseEnv.directFactoryAgentBaseUrl}${path}`, {
    method: options.method || 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(options.auth === false ? {} : { Authorization: `Bearer ${releaseEnv.bearerToken}` }),
      ...(options.headers || {}),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  const text = await response.text()
  const body = text ? JSON.parse(text) : null
  if (!response.ok) {
    throw new Error(`Factory Agent ${options.method || 'GET'} ${path} failed: ${response.status} ${text}`)
  }
  return body
}

export async function setReleaseFaults(faults) {
  const { body } = await releaseJson('/__release/faults', { method: 'POST', body: faults })
  return body
}

export async function resetReleaseFaults() {
  return setReleaseFaults({
    goApiUnavailable: false,
    factoryAgentUnavailable: false,
    authFailure: false,
    providerUnavailable: false,
    schemaMismatch: false,
  })
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
  return factoryAgentJson(`/sessions/${sessionId}/snapshot`)
}

export async function pendingApprovalsForPage(page) {
  const sessionId = await activeSessionId(page)
  if (!sessionId) throw new Error('No active Factory Agent session id in localStorage')
  return factoryAgentJson(`/approvals/pending?session_id=${encodeURIComponent(sessionId)}`)
}

export async function proxyLogText() {
  const { text } = await releaseJson('/__release/logs')
  return text
}

export function releaseLogSizeBytes(fileName) {
  const filePath = path.join(releaseEnv.artifactDir, fileName)
  return fs.existsSync(filePath) ? fs.statSync(filePath).size : 0
}
