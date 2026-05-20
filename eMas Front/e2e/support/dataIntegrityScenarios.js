import fs from 'node:fs'
import path from 'node:path'

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
export const canonicalJobIds = Object.freeze(Object.keys(canonicalJobPriorities))

const seededJobFields = 'job_id,priority,product_id,status,deadline'

export function jobIdsByPriority(priority) {
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

export function expectedPriorityMapForCascade(changes) {
  const expected = { ...canonicalJobPriorities }
  for (const change of changes) {
    const source = change?.source
    const target = change?.target
    if (!source || !target) continue
    for (const jobId of jobIdsByPriority(source)) expected[jobId] = target
  }
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

export function createSeededOracleArtifact(name) {
  return {
    name,
    created_at: new Date().toISOString(),
    urls: {
      go_api: seededEnv.goApiBaseUrl,
      factory_agent: seededEnv.factoryAgentBaseUrl,
    },
    checkpoints: [],
  }
}

export function recordOracleCheckpoint(artifact, label, data = {}) {
  if (!artifact) return data
  artifact.checkpoints.push({
    label,
    captured_at: new Date().toISOString(),
    ...data,
  })
  return data
}

export async function attachSeededOracleArtifact(testInfo, artifact, error = null) {
  if (!testInfo || !artifact) return
  const safeName = String(artifact.name || 'seeded-oracle')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
    .slice(0, 80) || 'seeded-oracle'
  const body = {
    ...artifact,
    failure: error
      ? {
          message: error?.message || String(error),
          stack: error?.stack || null,
        }
      : null,
  }
  const artifactPath = testInfo.outputPath(`${safeName}-oracle.json`)
  fs.mkdirSync(path.dirname(artifactPath), { recursive: true })
  fs.writeFileSync(artifactPath, JSON.stringify(body, null, 2))
  await testInfo.attach(`${safeName}-oracle.json`, {
    path: artifactPath,
    contentType: 'application/json',
  })
}

export async function withSeededOracleArtifact(testInfo, name, run) {
  const artifact = createSeededOracleArtifact(name)
  try {
    return await run(artifact)
  } catch (error) {
    await attachSeededOracleArtifact(testInfo, artifact, error)
    throw error
  }
}

export async function captureInitialSeededState(artifact) {
  const priorities = await currentPriorityMap()
  const rowsById = await currentSeededJobRowsById()
  recordOracleCheckpoint(artifact, 'initial seeded DB state before prompt', {
    priorities,
    rowsById,
  })
  expect(priorities).toEqual(canonicalJobPriorities)
  expect(Object.keys(rowsById).sort()).toEqual([...canonicalJobIds].sort())
  return { priorities, rowsById }
}

export async function captureFinalSeededState(artifact, { page = null, sessionId = null } = {}) {
  const priorities = await currentPriorityMap()
  const rowsById = await currentSeededJobRowsById()
  const snapshot = page ? await snapshotForArtifact(page) : null
  const browserText = page ? await page.locator('body').evaluate((body) => body.innerText) : null
  const audit = sessionId ? await dataIntegrityAudit(sessionId) : null
  return recordOracleCheckpoint(artifact, 'final seeded oracle evidence', {
    priorities,
    rowsById,
    snapshot,
    timeline: snapshot?.timeline || null,
    audit,
    browserText,
  })
}

async function snapshotForArtifact(page) {
  try {
    const { snapshotForPage } = await import('./fullStackScenarios.js')
    return snapshotForPage(page)
  } catch {
    return null
  }
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

export async function expectApprovalRowMatches(approvalOrId, expected) {
  const approvalId = typeof approvalOrId === 'string' ? approvalOrId : approvalOrId?.approval_id
  expect(approvalId, 'approval id should be present').toBeTruthy()
  const approval = await approvalById(approvalId)
  const bundle = approval.args?.bundle_ui || {}
  expect(approval.status).toBe(expected.status)
  expect(bundle.write_set).toBe(expected.writeSet)
  expect(bundle.kind).toBe(expected.kind || bundle.kind)
  expect(bundleJobIds(approval)).toEqual([...expected.jobIds].sort())
  if (expected.requestedPriority) {
    for (const row of bundleRows(approval)) {
      expect(row.new_priority).toBe(expected.requestedPriority)
    }
  }
  if (expected.originalPriority) {
    for (const row of bundleRows(approval)) {
      expect(row.original_priority || row.previous_priority).toBe(expected.originalPriority)
    }
  }
  if (Object.hasOwn(expected, 'previousApprovalId')) {
    expect(bundle.previous_approval_id || null).toBe(expected.previousApprovalId)
  }
  if (expected.count !== undefined) {
    expect(approval.args?.count).toBe(expected.count)
  }
  const previewArgs = Array.isArray(approval.args?.preview)
    ? approval.args.preview.map((item) => item?.args || {})
    : []
  if (previewArgs.length) {
    expect(previewArgs.map((args) => args.id).filter(Boolean).sort()).toEqual([...expected.jobIds].sort())
    if (expected.requestedPriority) {
      expect(new Set(previewArgs.map((args) => args.priority))).toEqual(new Set([expected.requestedPriority]))
    }
  }
  return approval
}

export async function expectSnapshotApprovalState(page, { status, pendingApprovalId }) {
  const { pendingApprovalsForPage, snapshotForPage } = await import('./fullStackScenarios.js')
  const snapshot = await snapshotForPage(page)
  expect(snapshot.session.status).toBe(status)
  expect(snapshot.phase).toBe(status)
  expect(snapshot.pending_approval?.approval_id || null).toBe(pendingApprovalId || null)
  const pending = await pendingApprovalsForPage(page)
  const pendingIds = pending.map((approval) => approval.approval_id).sort()
  expect(pendingIds).toEqual(pendingApprovalId ? [pendingApprovalId] : [])
  return snapshot
}

export async function expectRowsUnchangedFromInitial(initialRowsById, jobIds) {
  const current = await currentSeededJobRowsById(jobIds)
  expectUnchangedRowsMatch(initialRowsById, current, jobIds)
}

export function expectUnchangedRowsMatch(initialRowsById, currentRowsById, jobIds) {
  const expected = Object.fromEntries(jobIds.map((jobId) => [jobId, initialRowsById[jobId]]))
  const current = Object.fromEntries(jobIds.map((jobId) => [jobId, currentRowsById[jobId]]))
  expect(current).toEqual(expected)
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
  for (const entry of matching) {
    expect(entry.after_priority).toBe(status === 'succeeded' ? requestedPriority : entry.after_priority)
    expect(entry.approval_id).toBe(approvalId)
  }
  return matching
}

export function expectAuditCommit(entries, { scenario, writeSet, approvalId, succeededJobIds = [], failedJobIds = [], requestedPriority }) {
  const scoped = entries.filter(
    (entry) =>
      entry.scenario === scenario &&
      entry.write_set === writeSet &&
      entry.approval_id === approvalId &&
      entry.requested_priority === requestedPriority,
  )
  expect(scoped.map((entry) => entry.job_id).sort()).toEqual([...succeededJobIds, ...failedJobIds].sort())
  expect(scoped.filter((entry) => entry.status === 'succeeded').map((entry) => entry.job_id).sort()).toEqual([...succeededJobIds].sort())
  expect(scoped.filter((entry) => entry.status === 'failed').map((entry) => entry.job_id).sort()).toEqual([...failedJobIds].sort())
  for (const entry of scoped.filter((row) => row.status === 'succeeded')) {
    expect(entry.after_priority).toBe(requestedPriority)
    expect(entry.reason).toBeNull()
  }
  for (const entry of scoped.filter((row) => row.status === 'failed')) {
    expect(entry.reason).toBeTruthy()
  }
  return scoped
}

export function expectNoSuccessfulAudit(entries) {
  expect(entries.filter((entry) => entry.status === 'succeeded')).toHaveLength(0)
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

export function expectCascadeTimelineEvidence(snapshot, { firstApprovalId, secondApprovalId, firstSummary, secondSummary }) {
  expectTimelineEvidenceInOrder(snapshot, [
    {
      label: `approval requested ${firstApprovalId}`,
      predicate: (event) => event.event_type === 'approval_required' && event.approval_id === firstApprovalId,
    },
    {
      label: `approval decided ${firstApprovalId}`,
      predicate: (event) => event.event_type === 'approval_decided' && event.approval_id === firstApprovalId && event.status === 'APPROVED',
    },
    {
      label: `commit evidence ${firstApprovalId}`,
      predicate: (event) =>
        event.event_type === 'tool_result' &&
        (event.approval_id === firstApprovalId || event.details?.result?.approval_id === firstApprovalId) &&
        String(event.content || '').includes(firstSummary),
    },
    {
      label: `approval requested ${secondApprovalId}`,
      predicate: (event) => event.event_type === 'approval_required' && event.approval_id === secondApprovalId,
    },
    {
      label: `approval decided ${secondApprovalId}`,
      predicate: (event) => event.event_type === 'approval_decided' && event.approval_id === secondApprovalId && event.status === 'APPROVED',
    },
    {
      label: `commit evidence ${secondApprovalId}`,
      predicate: (event) =>
        event.event_type === 'tool_result' &&
        (event.approval_id === secondApprovalId || event.details?.result?.approval_id === secondApprovalId) &&
        String(event.content || '').includes(secondSummary),
    },
    {
      label: 'terminal session completion',
      predicate: (event) => event.event_type === 'session_completed' && event.status === 'COMPLETED',
    },
  ])
}

export function expectFinalSummaryClaimsOnly(text, { mustInclude = [], mustExclude = [] }) {
  const value = String(text || '')
  for (const phrase of mustInclude) {
    if (phrase instanceof RegExp) {
      expect(value).toMatch(phrase)
    } else {
      expect(value).toContain(phrase)
    }
  }
  for (const phrase of mustExclude) expect(value).not.toMatch(phrase instanceof RegExp ? phrase : new RegExp(escapeRegExp(phrase), 'i'))
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
