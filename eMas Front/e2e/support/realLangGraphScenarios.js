import { expect } from '@playwright/test'

import { chatSelectors } from '../fixtures/selectors.js'
import { realLangGraphRuntimeEnv } from './fullStackEnv.js'

export const realLangGraphEnv = realLangGraphRuntimeEnv()
export const activeSessionStorageKey = 'factory_agent_active_session_id'

export const canonicalJobPriorities = Object.freeze({
  'JOB-SEED-001': 'high',
  'JOB-SEED-002': 'medium',
  'JOB-SEED-003': 'high',
  'JOB-SEED-004': 'medium',
  'JOB-SEED-005': 'low',
  'JOB-SEED-006': 'high',
  'JOB-SEED-007': 'medium',
  'JOB-SEED-008': 'high',
  'JOB-SEED-009': 'low',
  'JOB-SEED-010': 'medium',
  'JOB-SEED-011': 'high',
  'JOB-SEED-012': 'low',
  'JOB-SEED-013': 'high',
  'JOB-SEED-014': 'medium',
  'JOB-SEED-015': 'high',
  'JOB-SEED-016': 'medium',
  'JOB-SEED-017': 'low',
  'JOB-SEED-018': 'medium',
  'JOB-SEED-019': 'high',
  'JOB-SEED-020': 'medium',
  'JOB-SEED-021': 'high',
  'JOB-SEED-022': 'medium',
  'JOB-SEED-023': 'high',
  'JOB-SEED-024': 'low',
  'JOB-SEED-025': 'medium',
  'JOB-SEED-026': 'high',
})

export const canonicalJobIds = Object.freeze(Object.keys(canonicalJobPriorities))
export const originalHighJobIds = Object.freeze(jobIdsByPriority('high'))
export const originalLowJobIds = Object.freeze(jobIdsByPriority('low'))
export const originalMediumJobIds = Object.freeze(jobIdsByPriority('medium'))

const seededJobFields = 'job_id,priority,product_id,status,deadline'

export function jobIdsByPriority(priority) {
  return Object.entries(canonicalJobPriorities)
    .filter(([, value]) => value === priority)
    .map(([jobId]) => jobId)
}

export function expectedPriorityMapForCascade(changes) {
  const expected = { ...canonicalJobPriorities }
  for (const change of changes) {
    for (const jobId of jobIdsByPriority(change.source)) expected[jobId] = change.target
  }
  return expected
}

export async function factoryAgentJson(path, options = {}) {
  const response = await fetch(`${realLangGraphEnv.factoryAgentBaseUrl}${path}`, {
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

export async function goApiJson(path, options = {}) {
  const response = await fetch(`${realLangGraphEnv.goApiBaseUrl}${path}`, {
    method: options.method || 'GET',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  const text = await response.text()
  let body = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch (err) {
      throw new Error(`Go API ${options.method || 'GET'} ${path} returned non-JSON: ${response.status} ${text.slice(0, 300)}`)
    }
  }
  if (!response.ok) {
    throw new Error(`Go API ${options.method || 'GET'} ${path} failed: ${response.status} ${text}`)
  }
  return body
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
  let sessionId = await activeSessionId(page)
  if (!sessionId) {
    await page.waitForFunction((key) => window.localStorage.getItem(key), activeSessionStorageKey, { timeout: 5000 })
    sessionId = await activeSessionId(page)
  }
  if (!sessionId) throw new Error('No active Factory Agent session id in localStorage')
  return factoryAgentJson(`/approvals/pending?session_id=${encodeURIComponent(sessionId)}`)
}

export async function resetSeededJobPriorities() {
  for (const [jobId, priority] of Object.entries(canonicalJobPriorities)) {
    await goApiJson(`/jobs/${jobId}`, { method: 'PUT', body: { priority } })
  }
}

export async function resetCanonicalGoApiSeed() {
  await goApiJson('/__e2e/reset', { method: 'POST' })
}

export async function resetFactoryAgentSessions() {
  await factoryAgentJson('/sessions?user_id=frontend-operator', { method: 'DELETE' })
}

export async function currentPriorityMap() {
  const body = await goApiJson('/jobs?fields=job_id,priority&sort_by=created_at&sort_dir=asc&limit=200')
  const rows = Array.isArray(body?.data) ? body.data : []
  return Object.fromEntries(
    rows
      .filter((row) => row?.job_id && Object.hasOwn(canonicalJobPriorities, row.job_id))
      .map((row) => [row.job_id, row.priority]),
  )
}

export async function currentSeededJobRowsById(jobIds = canonicalJobIds) {
  const wanted = new Set(jobIds)
  const body = await goApiJson(`/jobs?fields=${seededJobFields}&sort_by=created_at&sort_dir=asc&limit=200`)
  const rows = Array.isArray(body?.data) ? body.data : []
  return Object.fromEntries(
    rows
      .filter((row) => row?.job_id && wanted.has(row.job_id))
      .map((row) => [
        row.job_id,
        {
          job_id: row.job_id,
          priority: row.priority,
          product_id: row.product_id,
          status: row.status,
          deadline: row.deadline,
        },
      ]),
  )
}

export async function sessionMessages(sessionId) {
  return factoryAgentJson(`/sessions/${sessionId}/messages`)
}

export async function approvalById(approvalId) {
  return factoryAgentJson(`/approvals/${approvalId}`)
}

export function bundleRows(approval) {
  const rows = approval?.args?.bundle_ui?.rows
  return Array.isArray(rows) ? rows : []
}

export function bundleJobIds(approval) {
  return bundleRows(approval).map((row) => row.job_id).filter(Boolean).sort()
}

export async function expectGraphPriorityApproval(approvalOrId, expected) {
  const approvalId = typeof approvalOrId === 'string' ? approvalOrId : approvalOrId?.approval_id
  expect(approvalId, 'approval id should be present').toBeTruthy()
  const approval = await approvalById(approvalId)
  const bundle = approval.args?.bundle_ui || {}
  expect(approval.subject_type).toBe('graph')
  expect(approval.status).toBe(expected.status)
  expect(['job_priority_bundle', 'v2_planner_owned_approval_preview']).toContain(bundle.kind)
  const lockedConstraints = bundle.locked_constraints || {}
  const previousPriority = bundle.previous_priority || bundle.original_priority || lockedConstraints.priority || lockedConstraints.priority_from
  const newPriority = bundle.new_priority || lockedConstraints.new_priority || lockedConstraints.priority_to
  expect(previousPriority).toBe(expected.originalPriority)
  expect(newPriority).toBe(expected.requestedPriority)
  expect(bundleJobIds(approval)).toEqual([...expected.jobIds].sort())
  for (const row of bundleRows(approval)) {
    expect(row.previous_priority || row.original_priority || row.priority).toBe(expected.originalPriority)
    expect(row.new_priority).toBe(expected.requestedPriority)
  }
  expect(approval.args?.count).toBe(expected.jobIds.length)
  return approval
}

export async function expectSnapshotApprovalState(page, { status, pendingApprovalId }) {
  const snapshot = await snapshotForPage(page)
  expect(snapshot.session.status).toBe(status)
  expect(snapshot.phase).toBe(status)
  expect(snapshot.pending_approval?.approval_id || null).toBe(pendingApprovalId || null)
  const pending = await pendingApprovalsForPage(page)
  const pendingIds = pending.map((approval) => approval.approval_id).sort()
  expect(pendingIds).toEqual(pendingApprovalId ? [pendingApprovalId] : [])
  return snapshot
}

export function timelineText(snapshot) {
  return (snapshot?.timeline || []).map((event) => event.content || '').join('\n')
}

export function activityText(snapshot) {
  return (snapshot?.activity_steps || []).map((step) => step.label || step.description || '').join('\n')
}

export function approvalIdsFromTimeline(snapshot) {
  return new Set(
    (snapshot?.timeline || [])
      .map((event) => event?.details?.approval_id || event?.approval_id)
      .filter(Boolean),
  )
}

export function expectTimelineEvidenceInOrder(snapshot, checks) {
  const events = Array.isArray(snapshot?.timeline) ? snapshot.timeline : []
  let cursor = -1
  for (const check of checks) {
    const found = events.findIndex((event, index) => index > cursor && check.predicate(event))
    expect(
      found,
      `Expected timeline evidence after index ${cursor}: ${check.label}\n${events
        .map((event, index) => `${index}: ${event.event_type} ${event.approval_id || ''} ${event.content || ''}`)
        .join('\n')}`,
    ).toBeGreaterThan(cursor)
    cursor = found
  }
}

export async function finalAssistantText(sessionId) {
  const messages = await sessionMessages(sessionId)
  return [...messages].reverse().find((message) => message.role === 'assistant')?.content || ''
}
