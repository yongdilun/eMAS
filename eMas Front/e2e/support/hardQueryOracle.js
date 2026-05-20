import fs from 'node:fs'
import path from 'node:path'

import { expect } from '@playwright/test'

import {
  buildSemanticProbe,
  collectVisibleResponseDocumentUi,
  compactText,
  serializeSemanticProbe,
} from './responseDocumentProbe.js'
import { HARD_QUERY_FORBIDDEN_RUNTIME_PATTERNS } from './hardQueryScenarios.js'

const PASS = '__hard_query_oracle_pass__'
const WRITE_TOOL_RE = /^(post|put|patch|delete)__/i

function asArray(value) {
  if (value === undefined || value === null) return []
  return Array.isArray(value) ? value : [value]
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

function canonicalField(value) {
  return String(value || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
}

function fieldsFromArg(value) {
  if (Array.isArray(value)) return value.map(canonicalField).filter(Boolean)
  return String(value || '').split(',').map(canonicalField).filter(Boolean)
}

function normalizeExpectedArg(value) {
  if (Array.isArray(value)) return value.map(canonicalField).filter(Boolean)
  return value
}

function valuesEqual(actual, expected) {
  if (Array.isArray(expected)) {
    return JSON.stringify(fieldsFromArg(actual)) === JSON.stringify(normalizeExpectedArg(expected))
  }
  if (typeof expected === 'number') return Number(actual) === expected
  return String(actual ?? '').toLowerCase() === String(expected ?? '').toLowerCase()
}

function arrayContainsAll(actual, expected) {
  const actualSet = new Set(asArray(actual).map(canonicalField))
  return asArray(expected).every((value) => actualSet.has(canonicalField(value)))
}

function arrayEquals(actual, expected) {
  return JSON.stringify(asArray(actual).map(canonicalField)) === JSON.stringify(asArray(expected).map(canonicalField))
}

function compactStep(step) {
  return {
    tool_name: step?.tool_name || step?.toolName || null,
    status: step?.status || null,
    args: step?.args || {},
    result_summary: compactText(step?.result_summary || '', 160),
  }
}

function backendSteps(snapshot) {
  return Array.isArray(snapshot?.steps) ? snapshot.steps.map(compactStep) : []
}

function backendBlocks(snapshot) {
  return Array.isArray(snapshot?.response_document?.blocks) ? snapshot.response_document.blocks : []
}

function backendRunSteps(snapshot) {
  return Array.isArray(snapshot?.response_document?.run_steps) ? snapshot.response_document.run_steps : []
}

function toolName(step) {
  return step?.tool_name || step?.toolName || ''
}

function stepMatches(step, expected) {
  if (expected.toolName && toolName(step) !== expected.toolName) return false
  const args = step?.args || {}
  for (const [key, expectedValue] of Object.entries(expected.args || {})) {
    if (!valuesEqual(args[key], expectedValue)) return false
  }
  return true
}

function addStepViolations(violations, snapshot, expected) {
  const steps = backendSteps(snapshot)
  if (Object.hasOwn(expected, 'minStepCount') && steps.length < expected.minStepCount) {
    violations.push(`expected at least ${expected.minStepCount} backend steps but saw ${steps.length}`)
  }
  if (Object.hasOwn(expected, 'maxStepCount') && steps.length > expected.maxStepCount) {
    violations.push(`expected at most ${expected.maxStepCount} backend steps but saw ${steps.length}`)
  }
  for (const expectedToolName of asArray(expected.toolNames)) {
    if (!steps.some((step) => toolName(step) === expectedToolName)) {
      violations.push(`backend steps missing tool ${expectedToolName}`)
    }
  }
  let cursor = 0
  for (const expectedStep of asArray(expected.stepSequence)) {
    const found = steps.findIndex((step, index) => index >= cursor && stepMatches(step, expectedStep))
    if (found < 0) {
      violations.push(`backend step sequence missing ${expectedStep.toolName} with args ${JSON.stringify(expectedStep.args || {})}`)
      continue
    }
    cursor = found + 1
  }
  if (expected.noMutation) {
    const writeSteps = steps.filter((step) => WRITE_TOOL_RE.test(toolName(step)))
    if (writeSteps.length) {
      violations.push(`read-only scenario executed write tools: ${writeSteps.map(toolName).join(', ')}`)
    }
  }
}

function blockMatches(block, expectedBlock) {
  if (expectedBlock.type && block?.type !== expectedBlock.type) return false
  if (expectedBlock.contract && block?.contract !== expectedBlock.contract) return false
  if (expectedBlock.readScope && block?.read_scope !== expectedBlock.readScope) return false
  if (expectedBlock.displayMode && block?.display_mode !== expectedBlock.displayMode) return false
  if (expectedBlock.entityType && block?.entity_type !== expectedBlock.entityType) return false
  if (Object.hasOwn(expectedBlock, 'entityCount') && Number(block?.entity_count) !== Number(expectedBlock.entityCount)) return false
  if (expectedBlock.requestedFields && !arrayEquals(block?.requested_fields || [], expectedBlock.requestedFields)) return false
  if (Object.hasOwn(expectedBlock, 'maxRows') && Array.isArray(block?.rows) && block.rows.length > expectedBlock.maxRows) return false
  return true
}

function addResponseDocumentViolations(violations, snapshot, expected) {
  const document = snapshot?.response_document || {}
  const blocks = backendBlocks(snapshot)
  const blockTypes = blocks.map((block) => block?.type).filter(Boolean)
  const contracts = [
    ...blocks.map((block) => block?.contract),
    ...blocks.flatMap((block) => Array.isArray(block?.citations) ? block.citations.map((citation) => citation?.contract) : []),
    ...blocks.flatMap((block) => Array.isArray(block?.sources) ? block.sources.map((source) => source?.contract) : []),
    document.invariants?.read_status_contract,
    document.invariants?.mutation_business_contract,
    document.invariants?.no_op_mutation_contract,
    document.invariants?.source_list_contract,
    document.invariants?.source_locator_contract,
  ].filter(Boolean)
  const responseExpected = expected.responseDocument || {}
  for (const type of asArray(responseExpected.blockTypes)) {
    if (!blockTypes.includes(type)) violations.push(`response_document missing block type ${type}`)
  }
  for (const type of asArray(responseExpected.hiddenBlockTypes)) {
    if (blockTypes.includes(type)) violations.push(`response_document unexpectedly exposed block type ${type}`)
  }
  for (const contract of asArray(responseExpected.contracts)) {
    if (!contracts.includes(contract)) violations.push(`response_document missing contract ${contract}`)
  }
  for (const expectedBlock of asArray(responseExpected.blocks)) {
    if (!blocks.some((block) => blockMatches(block, expectedBlock))) {
      violations.push(`response_document missing semantic block ${JSON.stringify(expectedBlock)}`)
    }
  }
  if (Object.hasOwn(responseExpected, 'minReadRunSteps')) {
    const readRunSteps = backendRunSteps(snapshot).filter((step) => step?.kind === 'read')
    if (readRunSteps.length < responseExpected.minReadRunSteps) {
      violations.push(`response_document expected at least ${responseExpected.minReadRunSteps} read run_steps but saw ${readRunSteps.length}`)
    }
  }
  if (expected.noMutation && blockTypes.some((type) => ['approval_required', 'mutation_result'].includes(type))) {
    violations.push(`read-only scenario response_document contained mutation/approval block: ${blockTypes.join(', ')}`)
  }
}

function visibleBlockMatches(block, expectedBlock) {
  if (expectedBlock.type && block?.type !== expectedBlock.type) return false
  if (expectedBlock.contract && block?.contract !== expectedBlock.contract) return false
  if (expectedBlock.readScope && block?.readScope !== expectedBlock.readScope) return false
  if (expectedBlock.displayMode && block?.displayMode !== expectedBlock.displayMode) return false
  if (expectedBlock.entityType && block?.entityType !== expectedBlock.entityType) return false
  if (expectedBlock.requestedFields && !arrayEquals(block?.requestedFields || [], expectedBlock.requestedFields)) return false
  if (expectedBlock.statusFieldKeys && !arrayEquals(block?.statusFieldKeys || [], expectedBlock.statusFieldKeys)) return false
  if (expectedBlock.tableColumnKeys && !arrayEquals(block?.tableColumnKeys || [], expectedBlock.tableColumnKeys)) return false
  if (Object.hasOwn(expectedBlock, 'maxRows')) {
    const rowCount = Number(block?.tableRenderedRowCount ?? block?.tableRowCount ?? block?.entityCount ?? 0)
    if (Number.isFinite(rowCount) && rowCount > Number(expectedBlock.maxRows)) return false
  }
  return true
}

function addVisibleBlockViolations(violations, ui, expected) {
  const blocks = Array.isArray(ui?.visibleBlocks) ? ui.visibleBlocks : []
  for (const expectedBlock of asArray(expected.visibleSemanticBlocks)) {
    const block = blocks.find((candidate) => visibleBlockMatches(candidate, expectedBlock))
    if (!block) {
      violations.push(`visible DOM missing semantic block ${JSON.stringify(expectedBlock)}`)
      continue
    }
    for (const key of asArray(expectedBlock.forbiddenStatusFieldKeys)) {
      if (arrayContainsAll(block.statusFieldKeys || [], [key]) || arrayContainsAll(block.statusSecondaryFieldKeys || [], [key])) {
        violations.push(`visible status block leaked field ${key}`)
      }
    }
    for (const key of asArray(expectedBlock.forbiddenTableColumnKeys)) {
      if (arrayContainsAll(block.tableColumnKeys || [], [key])) {
        violations.push(`visible result table leaked column ${key}`)
      }
    }
  }
  const expectedRunSteps = asArray(expected.visibleRunSteps)
  if (expectedRunSteps.length) {
    const titles = asArray(ui?.visibleRunSteps).map((step) => step?.title || '')
    let cursor = 0
    for (const expectedStep of expectedRunSteps) {
      const found = titles.findIndex((title, index) => index >= cursor && matches(title, expectedStep.title))
      if (found < 0) violations.push(`visible run steps missing ordered title ${labelForPattern(expectedStep.title)}`)
      else cursor = found + 1
    }
  }
}

function addApprovalViolations(violations, snapshot, pendingApprovals, expected) {
  if (!Object.hasOwn(expected, 'approvalCount')) return
  const pending = Array.isArray(pendingApprovals) ? pendingApprovals : []
  if (pending.length !== expected.approvalCount) {
    violations.push(`pending approval count expected ${expected.approvalCount} but saw ${pending.length}`)
  }
  if (expected.approvalCount === 0 && snapshot?.pending_approval) {
    violations.push(`snapshot still has pending approval ${snapshot.pending_approval.approval_id || '<unknown>'}`)
  }
}

function addForbiddenTextViolations(violations, snapshot, ui, expected) {
  const visibleText = String(ui?.latestAssistantText || ui?.latestAssistantMessage || '')
  const backendContractText = JSON.stringify({
    response_document: snapshot?.response_document || {},
    steps: backendSteps(snapshot).map((step) => ({
      tool_name: step.tool_name,
      status: step.status,
      args: step.args,
      result_summary: step.result_summary,
    })),
  })
  for (const item of [...HARD_QUERY_FORBIDDEN_RUNTIME_PATTERNS, ...asArray(expected.forbiddenVisibleText)]) {
    const pattern = item?.pattern || item
    if (matches(visibleText, pattern)) {
      violations.push(`forbidden visible text matched ${item?.label || labelForPattern(pattern)}`)
    }
  }
  for (const item of [...HARD_QUERY_FORBIDDEN_RUNTIME_PATTERNS, ...asArray(expected.forbiddenBackendText)]) {
    const pattern = item?.pattern || item
    if (matches(backendContractText, pattern)) {
      violations.push(`forbidden backend contract text matched ${item?.label || labelForPattern(pattern)}`)
    }
  }
}

function evaluateHardQueryProbe({ snapshot, ui, pendingApprovals, scenario }) {
  const expected = scenario.expected || {}
  const violations = []
  const sessionStatus = snapshot?.session?.status || null
  const responseState = snapshot?.response_document?.state || null

  if (expected.sessionStatus && sessionStatus !== expected.sessionStatus) {
    violations.push(`backend session.status expected ${expected.sessionStatus} but saw ${sessionStatus || '<missing>'}`)
  }
  if (expected.responseState && responseState !== expected.responseState) {
    violations.push(`response_document.state expected ${expected.responseState} but saw ${responseState || '<missing>'}`)
  }

  addStepViolations(violations, snapshot, expected)
  addResponseDocumentViolations(violations, snapshot, expected)
  addVisibleBlockViolations(violations, ui, expected)
  addApprovalViolations(violations, snapshot, pendingApprovals, expected)
  addForbiddenTextViolations(violations, snapshot, ui, expected)

  return {
    ok: violations.length === 0,
    violations,
    semanticProbe: buildSemanticProbe({
      checkpoint: `${scenario.id} hard query oracle`,
      snapshot,
      ui,
      expected,
      violations,
    }),
    hardQuery: {
      scenarioId: scenario.id,
      prompt: scenario.prompt,
      backendSteps: backendSteps(snapshot),
      backendRunSteps: backendRunSteps(snapshot).map((step) => ({
        kind: step.kind,
        title: step.title,
        state: step.state,
        record_count: step.record_count,
      })),
      responseBlocks: backendBlocks(snapshot).map((block) => ({
        type: block.type,
        contract: block.contract,
        read_scope: block.read_scope,
        requested_fields: block.requested_fields,
        display_mode: block.display_mode,
        entity_type: block.entity_type,
        entity_count: block.entity_count,
        row_count: Array.isArray(block.rows) ? block.rows.length : null,
      })),
      visibleBlocks: asArray(ui?.visibleBlocks).map((block) => ({
        type: block.type,
        contract: block.contract,
        readScope: block.readScope,
        requestedFields: block.requestedFields,
        displayMode: block.displayMode,
        entityType: block.entityType,
        statusFieldKeys: block.statusFieldKeys,
        tableColumnKeys: block.tableColumnKeys,
        tableRenderedRowCount: block.tableRenderedRowCount,
      })),
      visibleRunSteps: ui?.visibleRunSteps || [],
      pendingApprovals,
      violations,
    },
  }
}

function safeArtifactName(value) {
  return String(value || 'hard-query')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
    .slice(0, 80) || 'hard-query'
}

async function attachHardQueryArtifact(testInfo, scenario, payload) {
  if (!testInfo) return
  const name = `${safeArtifactName(scenario.id)}-hard-query-oracle.json`
  const artifactPath = testInfo.outputPath(name)
  fs.mkdirSync(path.dirname(artifactPath), { recursive: true })
  fs.writeFileSync(artifactPath, serializeSemanticProbe(payload))
  await testInfo.attach(name, {
    path: artifactPath,
    contentType: 'application/json',
  })
}

export async function collectHardQueryProbe(page, scenario, { snapshotForPage, pendingApprovalsForPage }) {
  const [snapshot, ui, pendingApprovals] = await Promise.all([
    snapshotForPage(page),
    collectVisibleResponseDocumentUi(page),
    pendingApprovalsForPage(page),
  ])
  return { snapshot, ui, pendingApprovals, scenario }
}

export async function expectHardQueryScenario(page, scenario, {
  snapshotForPage,
  pendingApprovalsForPage,
  testInfo = null,
  timeout = 30_000,
}) {
  let lastEvaluation = null
  try {
    await expect
      .poll(async () => {
        const probe = await collectHardQueryProbe(page, scenario, { snapshotForPage, pendingApprovalsForPage })
        lastEvaluation = evaluateHardQueryProbe(probe)
        return lastEvaluation.ok ? PASS : JSON.stringify(lastEvaluation.hardQuery, null, 2)
      }, {
        timeout,
        message: `Hard query scenario ${scenario.id} did not converge`,
      })
      .toBe(PASS)
  } catch (error) {
    const payload = {
      ...(lastEvaluation?.semanticProbe || {}),
      hardQuery: lastEvaluation?.hardQuery || { scenarioId: scenario.id, violations: [String(error?.message || error)] },
    }
    await attachHardQueryArtifact(testInfo, scenario, payload)
    throw new Error(
      `Hard query oracle failed for ${scenario.id}: ${scenario.prompt}\n` +
      `${(lastEvaluation?.hardQuery?.violations || [String(error?.message || error)]).join('\n')}\n` +
      `Semantic probe JSON:\n${serializeSemanticProbe(payload)}`,
    )
  }
  return lastEvaluation
}

export const hardQueryOracleInternalsForTest = Object.freeze({
  evaluateHardQueryProbe,
  fieldsFromArg,
  visibleBlockMatches,
  stepMatches,
})
