import { expect } from '@playwright/test'

import { factoryAgentJson, seededEnv } from './fullStackScenarios.js'

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

export const originalHighJobIds = Object.freeze(jobIdsByPriority('high'))
export const originalLowJobIds = Object.freeze(jobIdsByPriority('low'))
export const originalMediumJobIds = Object.freeze(jobIdsByPriority('medium'))

function jobIdsByPriority(priority) {
  return Object.entries(canonicalJobPriorities)
    .filter(([, value]) => value === priority)
    .map(([jobId]) => jobId)
}

export function expectedCascadePriorities() {
  const expected = { ...canonicalJobPriorities }
  for (const jobId of originalHighJobIds) expected[jobId] = 'low'
  for (const jobId of originalLowJobIds) expected[jobId] = 'medium'
  return expected
}

export async function goApiJson(path, options = {}) {
  const response = await fetch(`${seededEnv.goApiBaseUrl}${path}`, {
    method: options.method || 'GET',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  const text = await response.text()
  const body = text ? JSON.parse(text) : null
  if (!response.ok) {
    throw new Error(`Go API ${options.method || 'GET'} ${path} failed: ${response.status} ${text}`)
  }
  return body
}

export async function factoryAgentRaw(path, options = {}) {
  const response = await fetch(`${seededEnv.factoryAgentBaseUrl}${path}`, {
    method: options.method || 'GET',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  const text = await response.text()
  let body = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = text
    }
  }
  return { ok: response.ok, status: response.status, body }
}

export async function resetSeededJobPriorities() {
  for (const [jobId, priority] of Object.entries(canonicalJobPriorities)) {
    await goApiJson(`/jobs/${jobId}`, { method: 'PUT', body: { priority } })
  }
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

export async function priorityForJob(jobId) {
  const body = await goApiJson(`/jobs/${jobId}`)
  return body?.data?.priority
}

export async function dataIntegrityAudit(sessionId) {
  const body = await factoryAgentJson(`/_playwright/data-integrity/audit?session_id=${encodeURIComponent(sessionId)}`)
  return Array.isArray(body?.entries) ? body.entries : []
}

export async function sessionMessages(sessionId) {
  return factoryAgentJson(`/sessions/${sessionId}/messages`)
}

export async function sseConnections(sessionId) {
  const body = await factoryAgentJson('/_playwright/sse-connections')
  const rows = Array.isArray(body?.connections) ? body.connections : []
  return rows.filter((row) => row.session_id === sessionId)
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

export function expectAuditForJobs(entries, { scenario, writeSet, approvalId, jobIds, requestedPriority, status = 'succeeded' }) {
  const matching = entries.filter(
    (entry) =>
      entry.scenario === scenario &&
      entry.write_set === writeSet &&
      entry.approval_id === approvalId &&
      entry.requested_priority === requestedPriority &&
      entry.status === status,
  )
  expect(matching.map((entry) => entry.job_id).sort()).toEqual([...jobIds].sort())
}

export function expectNoSuccessfulAudit(entries) {
  expect(entries.filter((entry) => entry.status === 'succeeded')).toHaveLength(0)
}
