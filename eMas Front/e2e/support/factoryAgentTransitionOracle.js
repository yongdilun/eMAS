import fs from 'node:fs'
import path from 'node:path'

import { expect } from '@playwright/test'

import {
  baseForbiddenProbeText,
  buildSemanticProbe,
  collectVisibleResponseDocumentUi,
  finalResponseQualityViolations,
  semanticProbeHumanSummary,
  serializeSemanticProbe,
} from './responseDocumentProbe.js'

const PASS = '__factory_agent_transition_pass__'

export const uiStatusByBackendStatus = Object.freeze({
  PLANNING: 'Understanding',
  EXECUTING: 'Checking',
  WAITING_APPROVAL: 'Waiting for approval',
  WAITING_CONFIRMATION: 'Waiting for confirmation',
  BLOCKED: 'Needs attention',
  FAILED: 'Needs attention',
  COMPLETED: 'Complete',
  IDLE: 'Ready',
})

export const baseForbiddenTransitionText = baseForbiddenProbeText

function asArray(value) {
  if (value === undefined || value === null) return []
  return Array.isArray(value) ? value : [value]
}

function uniq(values) {
  return [...new Set(values.filter((value) => value !== undefined && value !== null))]
}

function matches(value, pattern) {
  const text = String(value || '')
  if (pattern instanceof RegExp) return pattern.test(text)
  return text.includes(String(pattern))
}

function labelForPattern(pattern) {
  if (pattern?.label) return pattern.label
  if (pattern instanceof RegExp) return String(pattern)
  return JSON.stringify(pattern)
}

function backendSummary(snapshot) {
  const document = snapshot?.response_document || {}
  const blocks = Array.isArray(document.blocks) ? document.blocks : []
  const backendSteps = Array.isArray(snapshot?.steps) ? snapshot.steps : []
  const runSteps = Array.isArray(document.run_steps) ? document.run_steps : []
  const timeline = Array.isArray(snapshot?.timeline) ? snapshot.timeline : []
  const activitySteps = Array.isArray(snapshot?.activity_steps) ? snapshot.activity_steps : []
  const contracts = uniq([
    ...blocks.map((block) => block?.contract),
    ...blocks.flatMap((block) => Array.isArray(block?.groups) ? block.groups.map((group) => group?.contract) : []),
    ...blocks.flatMap((block) => Array.isArray(block?.sources) ? block.sources.map((source) => source?.contract) : []),
    ...blocks.flatMap((block) => Array.isArray(block?.citations) ? block.citations.map((citation) => citation?.contract) : []),
    document.invariants?.read_status_contract,
    document.invariants?.mutation_business_contract,
    document.invariants?.no_op_mutation_contract,
  ])
  return {
    sessionStatus: snapshot?.session?.status || null,
    phase: snapshot?.phase || null,
    pendingApprovalId: snapshot?.pending_approval?.approval_id || null,
    responseDocumentState: document.state || null,
    responseDocumentRevision: document.revision ?? null,
    responseDocumentCurrentStepId: document.current_step_id || null,
    responseBlockTypes: blocks.map((block) => block?.type).filter(Boolean),
    responseApprovalIds: blocks.map((block) => block?.approval_id).filter(Boolean),
    responseContracts: contracts,
    backendSteps,
    backendStepTools: backendSteps.map((step) => step?.tool_name || step?.toolName).filter(Boolean),
    responseRunSteps: runSteps,
    responseRunStepTitles: runSteps.map((step) => step?.title || step?.label || '').filter(Boolean),
    responseRunStepKinds: runSteps.map((step) => step?.kind).filter(Boolean),
    timeline,
    timelineEventTypes: timeline.map((event) => event?.event_type || event?.type).filter(Boolean),
    activityLabels: activitySteps.map((step) => step?.label || step?.description || '').filter(Boolean),
  }
}

function valuesEqual(actual, expected) {
  return JSON.stringify(actual) === JSON.stringify(expected)
}

function stepToolName(step) {
  return step?.tool_name || step?.toolName || ''
}

function stepMatches(step, expectedStep) {
  if (expectedStep.toolName && stepToolName(step) !== expectedStep.toolName) return false
  if (expectedStep.status && step?.status !== expectedStep.status) return false
  const args = step?.args || {}
  for (const [key, expectedValue] of Object.entries(expectedStep.args || {})) {
    if (!valuesEqual(args[key], expectedValue)) return false
  }
  return true
}

function timelineEventMatches(event, expectedEvent) {
  const eventType = event?.event_type || event?.type || ''
  if (typeof expectedEvent === 'string') return eventType === expectedEvent
  if (expectedEvent.eventType && eventType !== expectedEvent.eventType) return false
  if (expectedEvent.approvalId && (event?.approval_id || event?.details?.approval_id) !== expectedEvent.approvalId) return false
  if (expectedEvent.status && event?.status !== expectedEvent.status) return false
  if (expectedEvent.toolName && (event?.tool_name || event?.details?.tool_name) !== expectedEvent.toolName) return false
  if (expectedEvent.text && !matches(`${event?.content || ''} ${event?.message || ''} ${event?.summary || ''}`, expectedEvent.text)) return false
  return true
}

function addOrderedPatternViolations(violations, actualValues, expectedValues, label) {
  let cursor = 0
  for (const expectedValue of asArray(expectedValues)) {
    const found = actualValues.findIndex((actualValue, index) => index >= cursor && matches(actualValue, expectedValue))
    if (found < 0) {
      violations.push(`${label} missing ordered ${labelForPattern(expectedValue)}`)
      continue
    }
    cursor = found + 1
  }
}

function addMiddleStepViolations(violations, backend, expected) {
  addListExpectationViolations(violations, backend.backendStepTools, expected.backendStepTools, 'backend step tools')
  let stepCursor = 0
  for (const expectedStep of asArray(expected.backendStepSequence)) {
    const found = backend.backendSteps.findIndex((step, index) => index >= stepCursor && stepMatches(step, expectedStep))
    if (found < 0) {
      violations.push(`backend step sequence missing ${expectedStep.toolName || '<any tool>'} ${JSON.stringify(expectedStep.args || {})}`)
      continue
    }
    stepCursor = found + 1
  }

  addListExpectationViolations(violations, backend.responseRunStepKinds, expected.responseRunStepKinds, 'response_document run_step kinds')
  addOrderedPatternViolations(violations, backend.responseRunStepTitles, expected.responseRunStepTitles, 'response_document run_step titles')

  let timelineCursor = 0
  for (const expectedEvent of asArray(expected.timelineEventsInOrder || expected.timelineEventTypesInOrder)) {
    const found = backend.timeline.findIndex((event, index) => index >= timelineCursor && timelineEventMatches(event, expectedEvent))
    if (found < 0) {
      const label = typeof expectedEvent === 'string' ? expectedEvent : expectedEvent.label || expectedEvent.eventType || '<event>'
      violations.push(`timeline missing ordered ${label}`)
      continue
    }
    timelineCursor = found + 1
  }

  addOrderedPatternViolations(violations, backend.activityLabels, expected.activityLabelsInOrder, 'activity labels')
  for (const pattern of asArray(expected.activityLabelsInclude)) {
    if (!backend.activityLabels.some((label) => matches(label, pattern))) {
      violations.push(`activity labels missing ${labelForPattern(pattern)}`)
    }
  }
}

export function summarizeTransitionProbe(probe, { expected = {}, violations = [] } = {}) {
  return buildSemanticProbe({
    checkpoint: probe.checkpoint || null,
    snapshot: probe.snapshot,
    ui: probe.ui || {},
    expected,
    violations,
  })
}

function expectedStatuses(expected) {
  const statuses = asArray(expected.sessionStatuses || expected.sessionStatus)
  return statuses.length ? statuses : null
}

function expectedResponseStates(expected) {
  const states = asArray(expected.responseStates || expected.responseState)
  return states.length ? states : null
}

function expectedUiStatuses(statuses) {
  if (!statuses) return null
  return uniq(statuses.map((status) => uiStatusByBackendStatus[status] || null))
}

function addForbiddenTextViolations(violations, text, expected) {
  const forbidden = [...baseForbiddenTransitionText, ...asArray(expected.forbiddenText)]
  if (expected.forbidWaitingApproval1) {
    forbidden.push({ label: 'stale Waiting for approval 1 after approval 1 was decided', pattern: /Waiting for approval 1/i })
  }
  if (expected.forbidApprovalRequired) {
    forbidden.push({ label: 'stale Approval required after completion', pattern: /Approval required/i })
  }
  for (const item of forbidden) {
    const pattern = item?.pattern || item
    if (matches(text, pattern)) {
      violations.push(`forbidden visible text matched ${item?.label || labelForPattern(pattern)}`)
    }
  }
}

function addTextExpectationViolations(violations, text, expected) {
  for (const pattern of asArray(expected.textIncludes)) {
    if (!matches(text, pattern)) violations.push(`visible text did not include ${labelForPattern(pattern)}`)
  }
  for (const pattern of asArray(expected.textExcludes)) {
    if (matches(text, pattern)) violations.push(`visible text unexpectedly included ${labelForPattern(pattern)}`)
  }
}

function addListExpectationViolations(violations, actualValues, requiredValues, label) {
  const actual = new Set(actualValues || [])
  for (const value of asArray(requiredValues)) {
    if (!actual.has(value)) violations.push(`${label} missing ${value}`)
  }
}

function addAbsentListExpectationViolations(violations, actualValues, forbiddenValues, label) {
  const actual = new Set(actualValues || [])
  for (const value of asArray(forbiddenValues)) {
    if (actual.has(value)) violations.push(`${label} still contained ${value}`)
  }
}

export function evaluateTransitionProbe(probe, expected = {}) {
  const violations = []
  const snapshot = probe.snapshot || {}
  const document = snapshot.response_document || {}
  const ui = probe.ui || {}
  const backend = backendSummary(snapshot)
  const sessionStatuses = expectedStatuses(expected)
  const responseStates = expectedResponseStates(expected)

  if (sessionStatuses && !sessionStatuses.includes(backend.sessionStatus)) {
    violations.push(`backend session.status expected ${sessionStatuses.join(' or ')} but saw ${backend.sessionStatus || '<missing>'}`)
  }
  if (responseStates && !responseStates.includes(backend.responseDocumentState)) {
    violations.push(`response_document.state expected ${responseStates.join(' or ')} but saw ${backend.responseDocumentState || '<missing>'}`)
  }
  if (Object.hasOwn(expected, 'pendingApprovalId') && backend.pendingApprovalId !== (expected.pendingApprovalId || null)) {
    violations.push(`pending_approval.approval_id expected ${expected.pendingApprovalId || '<none>'} but saw ${backend.pendingApprovalId || '<none>'}`)
  }
  if (expected.pendingApprovalMustDifferFrom && backend.pendingApprovalId === expected.pendingApprovalMustDifferFrom) {
    violations.push(`pending_approval.approval_id was still stale ${backend.pendingApprovalId}`)
  }
  if (Object.hasOwn(expected, 'revisionGreaterThan')) {
    const revision = Number(document.revision)
    if (!Number.isFinite(revision) || revision <= Number(expected.revisionGreaterThan)) {
      violations.push(`response_document.revision expected > ${expected.revisionGreaterThan} but saw ${document.revision ?? '<missing>'}`)
    }
  }
  if (Object.hasOwn(expected, 'minRevision')) {
    const revision = Number(document.revision)
    if (!Number.isFinite(revision) || revision < Number(expected.minRevision)) {
      violations.push(`response_document.revision expected >= ${expected.minRevision} but saw ${document.revision ?? '<missing>'}`)
    }
  }

  const derivedUiStatuses = expectedUiStatuses(sessionStatuses)
  const headerStatuses = asArray(expected.headerStatuses || expected.headerStatus)
  const sidebarStatuses = asArray(expected.sidebarStatuses || expected.sidebarStatus)
  const allowedHeaderStatuses = headerStatuses.length ? headerStatuses : derivedUiStatuses
  const allowedSidebarStatuses = sidebarStatuses.length ? sidebarStatuses : derivedUiStatuses

  if (allowedHeaderStatuses?.length && ui.headerStatus && !allowedHeaderStatuses.includes(ui.headerStatus)) {
    violations.push(`visible header status expected ${allowedHeaderStatuses.join(' or ')} but saw ${ui.headerStatus || '<missing>'}`)
  }
  if (allowedSidebarStatuses?.length && ui.activeSidebarStatus && !allowedSidebarStatuses.includes(ui.activeSidebarStatus)) {
    violations.push(`active sidebar status expected ${allowedSidebarStatuses.join(' or ')} but saw ${ui.activeSidebarStatus || '<missing>'}`)
  }

  addListExpectationViolations(violations, ui.visibleBlockTypes, expected.visibleBlockTypes, 'visible block types')
  addAbsentListExpectationViolations(violations, ui.visibleBlockTypes, expected.hiddenBlockTypes, 'visible block types')
  addListExpectationViolations(violations, ui.visibleBlockIds, expected.visibleBlockIds, 'visible block ids')
  addAbsentListExpectationViolations(violations, ui.visibleBlockIds, expected.hiddenBlockIds, 'visible block ids')
  addListExpectationViolations(violations, backend.responseBlockTypes, expected.backendBlockTypes, 'response_document block types')
  addAbsentListExpectationViolations(violations, backend.responseBlockTypes, expected.hiddenBackendBlockTypes, 'response_document block types')
  addListExpectationViolations(violations, backend.responseContracts, expected.responseContracts, 'response_document contracts')
  addListExpectationViolations(violations, ui.visibleContracts, expected.responseContracts, 'visible response contracts')
  addMiddleStepViolations(violations, backend, expected)

  if (Object.hasOwn(expected, 'approvalActionCount')) {
    const count = ui.approvalActionLabels.length
    if (count !== expected.approvalActionCount) {
      violations.push(`visible approval action count expected ${expected.approvalActionCount} but saw ${count}`)
    }
  }

  const text = ui.latestAssistantText || ui.latestAssistantMessage || ui.visibleText || ''
  addForbiddenTextViolations(violations, text, {
    ...expected,
    forbidApprovalRequired:
      expected.forbidApprovalRequired ||
      expected.sessionStatus === 'COMPLETED' ||
      expected.responseState === 'completed',
  })
  addTextExpectationViolations(violations, text, expected)
  violations.push(...finalResponseQualityViolations(ui.finalResponseQuality || {}, expected))

  return {
    ok: violations.length === 0,
    violations,
    summary: summarizeTransitionProbe(probe, { expected, violations }),
  }
}

export function formatTransitionFailure({ checkpoint, expected, result }) {
  return serializeSemanticProbe(result?.summary || buildSemanticProbe({
    checkpoint,
    expected,
    violations: result?.violations || [],
  }))
}

function safeArtifactName(value) {
  return String(value || 'transition-checkpoint')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
    .slice(0, 90) || 'transition-checkpoint'
}

async function attachTransitionArtifact(testInfo, checkpoint, payload) {
  if (!testInfo) return
  const name = `${safeArtifactName(checkpoint)}-semantic-probe.json`
  const body = serializeSemanticProbe(payload)
  const artifactPath = testInfo.outputPath(name)
  fs.mkdirSync(path.dirname(artifactPath), { recursive: true })
  fs.writeFileSync(artifactPath, body)
  await testInfo.attach(name, {
    path: artifactPath,
    contentType: 'application/json',
  })
}

export async function collectVisibleTransitionUi(page) {
  return collectVisibleResponseDocumentUi(page)
}

export async function collectTransitionProbe(page, { checkpoint, snapshotForPage }) {
  if (typeof snapshotForPage !== 'function') {
    throw new Error('collectTransitionProbe requires snapshotForPage(page)')
  }
  const [snapshot, ui] = await Promise.all([
    snapshotForPage(page),
    collectVisibleTransitionUi(page),
  ])
  return { checkpoint, snapshot, ui }
}

export async function expectTransitionCheckpoint(page, {
  checkpoint,
  snapshotForPage,
  expected,
  testInfo = null,
  timeout = 10_000,
}) {
  let lastResult = null
  let lastProbe = null
  try {
    await expect
      .poll(async () => {
        lastProbe = await collectTransitionProbe(page, { checkpoint, snapshotForPage })
        lastResult = evaluateTransitionProbe(lastProbe, expected)
        return lastResult.ok ? PASS : formatTransitionFailure({ checkpoint, expected, result: lastResult })
      }, {
        timeout,
        message: `Factory Agent transition checkpoint did not converge: ${checkpoint}`,
      })
      .toBe(PASS)
  } catch (error) {
    const semanticProbe = lastResult?.summary || buildSemanticProbe({
      checkpoint,
      snapshot: lastProbe?.snapshot,
      ui: lastProbe?.ui || {},
      expected,
      violations: [error?.message || String(error)],
    })
    const payload = serializeSemanticProbe(semanticProbe)
    await attachTransitionArtifact(testInfo, checkpoint, semanticProbe)
    throw new Error(
      `Factory Agent transition checkpoint failed: ${checkpoint}\n` +
      `${semanticProbeHumanSummary(semanticProbe)}\n` +
      `Semantic probe JSON:\n${payload}`,
    )
  }
  return lastResult.summary
}
