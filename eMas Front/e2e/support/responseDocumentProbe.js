import { redactSensitiveArtifactText } from './artifactRedaction.js'

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

export const statusLabels = Object.freeze([
  'Ready',
  'Understanding',
  'Checking',
  'Waiting for approval',
  'Waiting for confirmation',
  'Needs attention',
  'Complete',
  'Working',
])

export const baseForbiddenProbeText = Object.freeze([
  { label: 'internal non_terminal_snapshot reason', pattern: /non_terminal_snapshot/i },
  { label: 'orphan idle diagnostic', pattern: /Session status:\s*IDLE/i },
  {
    label: 'generic needs-attention diagnostic',
    pattern: /Needs attention\s+The request needs attention before it can continue/i,
  },
  { label: 'raw JSON object', pattern: /(?:^|\n)\s*[\[{]\s*"[^"\n]+"\s*:/ },
  { label: 'traceback or stack trace', pattern: /Traceback|stack trace|^\s*at\s+\S+.*:\d+:\d+/im },
  {
    label: 'secret or token diagnostic',
    pattern: /\b(?:api[_-]?key|authorization|bearer|password|secret|token)\b\s*[:=]\s*(?!\[redacted\])[\w.+/=-]{6,}/i,
  },
  { label: 'known secret sample', pattern: /\b(?:sk-[a-z0-9_-]{12,}|raw-secret-token|super-secret)\b/i },
])

export const finalResponseForbiddenProbeText = Object.freeze([
  { label: 'raw assistant done_all marker', pattern: /(?:^|\s)done_all(?:\s|$)/i },
  { label: 'raw assistant success markdown', pattern: /\*\*Success\*\*/i },
  { label: 'backend operation aggregate leak', pattern: /Updated 63 jobs across 22 approved steps/i },
  { label: 'internal Operation ID', pattern: /Operation ID/i },
  { label: 'internal Step ID', pattern: /Step ID/i },
  { label: 'internal Row ID', pattern: /Row ID/i },
  { label: 'legacy approved-step aggregate', pattern: /Updated 21 jobs across 2 approved steps/i },
])

export const pendingApprovalGuidanceProbeText = Object.freeze([
  {
    label: 'always-visible pending follow-up guidance',
    pattern: /Follow-up messages can revise the plan, but the current approval remains pending until you approve, reject, or cancel it\./i,
  },
])

export const readOnlyStatusForbiddenProbeText = Object.freeze([
  { label: 'raw assistant done_all marker', pattern: /(?:^|\s)done_all(?:\s|$)/i },
  { label: 'raw assistant success markdown', pattern: /\*\*Success\*\*/i },
  { label: 'dump-style Machineid label', pattern: /\bMachineid\b/i },
  { label: 'dump-style Machinename label', pattern: /\bMachinename\b/i },
  { label: 'dump-style Capacityperhour label', pattern: /\bCapacityperhour\b/i },
  { label: 'dump-style Defaultsetuptime label', pattern: /\bDefaultsetuptime\b/i },
  { label: 'dump-style Defaultcleaningtime label', pattern: /\bDefaultcleaningtime\b/i },
  { label: 'dump-style Defaultchangeovertime label', pattern: /\bDefaultchangeovertime\b/i },
  { label: 'dump-style Utilizationrate label', pattern: /\bUtilizationrate\b/i },
])

export const documentContentRagForbiddenProbeText = Object.freeze([
  { label: 'raw safety admonition directive', pattern: /:::safety/i },
  { label: 'raw safety warning markdown', pattern: /SAFETY WARNING/i },
  { label: 'raw markdown footnote definition', pattern: /^\s*\[\^[^\]]+\]:/im },
  { label: 'unconverted markdown citation marker', pattern: /\[\^[^\]]+\]/i },
  { label: 'legacy safety advisory chrome', pattern: /Safety Advisory/i },
  { label: 'machine ID clarification', pattern: /Which machine ID/i },
  { label: 'exact machine ID clarification', pattern: /exact machine ID/i },
  { label: 'no-results diagnostic', pattern: /\bNo results\b/i },
  { label: 'completed_answer technical detail', pattern: /completed_answer/i },
  { label: 'approval UI on RAG answer', pattern: /Approval required/i },
  { label: 'synthetic LOTO notification source id', pattern: /loto_notification_requirement/i },
  { label: 'hardcoded LOTO notification source title', pattern: /LOTO Notification Requirements/i },
])

const DISPLAYABLE_BLOCK_TYPES = new Set([
  'approval_required',
  'approval_card',
  'completed_step',
  'result_summary',
  'mutation_result',
  'result_table',
  'status_result',
  'record_preview',
  'knowledge_answer',
  'safety_notice',
  'source_list',
  'warning',
  'diagnostic',
])

const SECRET_TEXT_RE = /\b(api[_-]?key|authorization|bearer|password|secret|token)\b\s*[:=]?\s*[^\s,;'"`]+/gi
const OPENAI_KEY_RE = /\bsk-[a-z0-9_-]{8,}/gi
const STACK_TRACE_RE = /(?:Traceback \(most recent call last\):[\s\S]*|stack trace[\s\S]*|^\s*at\s+\S+.*:\d+:\d+.*(?:\n\s*at\s+\S+.*:\d+:\d+)*)/gim

export function asArray(value) {
  if (value === undefined || value === null) return []
  return Array.isArray(value) ? value : [value]
}

export function matches(value, pattern) {
  const text = String(value || '')
  if (pattern instanceof RegExp) return pattern.test(text)
  return text.includes(String(pattern))
}

export function labelForPattern(pattern) {
  if (pattern?.label) return pattern.label
  if (pattern instanceof RegExp) return String(pattern)
  return JSON.stringify(pattern)
}

function uniq(values) {
  return [...new Set(values.filter((value) => value !== undefined && value !== null && value !== ''))]
}

function compactArray(values, limit = 12) {
  return uniq(values).slice(0, limit)
}

function compactObject(value) {
  return Object.fromEntries(Object.entries(value).filter(([, item]) => (
    item !== undefined &&
    item !== null &&
    item !== '' &&
    item !== false &&
    !(Array.isArray(item) && item.length === 0)
  )))
}

export function redactProbeText(value) {
  return String(value == null ? '' : value)
    .replace(STACK_TRACE_RE, '[stack trace redacted]')
    .replace(SECRET_TEXT_RE, '$1=[redacted]')
    .replace(OPENAI_KEY_RE, '[redacted-openai-key]')
}

export function compactText(value, limit = 260) {
  const text = redactProbeText(value).replace(/\s+/g, ' ').trim()
  if (text.length <= limit) return text
  return `${text.slice(0, limit)}...`
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
  if (!statuses?.length) return null
  return compactArray(statuses.map((status) => uiStatusByBackendStatus[status] || null))
}

function blockApprovalIdFromId(id) {
  const match = String(id || '').match(/^approval:(.+)$/)
  return match ? match[1] : null
}

function summarizeBlocks(blocks = []) {
  return blocks.slice(-8).map((block) => compactObject({
    type: block?.type || null,
    id: block?.id || null,
    contract: block?.contract || null,
    entityType: block?.entity_type || null,
    approvalId: block?.approval_id || blockApprovalIdFromId(block?.id) || null,
    title: compactText(block?.title || '', 80) || null,
    summary: compactText(block?.summary || block?.message || block?.user_message || block?.answer || '', 140) || null,
  }))
}

function summarizeRunSteps(steps = []) {
  return steps.slice(-8).map((step) => compactObject({
    id: step?.step_id || step?.id || null,
    title: compactText(step?.title || step?.label || '', 120) || null,
    state: step?.state || null,
    approvalId: step?.approval_id || null,
    current: Boolean(step?.current),
  }))
}

function summarizeSourceCitationsFromBlocks(blocks = []) {
  const citations = []
  for (const block of blocks) {
    if (block?.type !== 'knowledge_answer' || !Array.isArray(block.citations)) continue
    for (const citation of block.citations) {
      citations.push(compactObject({
        contract: citation?.contract || null,
        citationId: citation?.citation_id || citation?.citationId || null,
        sourceId: citation?.source_id || citation?.sourceId || null,
        sourceNumber: citation?.source_number || citation?.sourceNumber || null,
        docId: citation?.doc_id || citation?.docId || null,
        chunkId: citation?.chunk_id || citation?.chunkId || null,
        title: compactText(citation?.title || '', 100) || null,
      }))
    }
  }
  return citations.slice(0, 12)
}

export function summarizeBackendSnapshot(snapshot) {
  const document = snapshot?.response_document || {}
  const blocks = Array.isArray(document.blocks) ? document.blocks : []
  const runSteps = Array.isArray(document.run_steps) ? document.run_steps : []
  const session = snapshot?.session || {}
  const sessionId = session.session_id || snapshot?.session_id || null
  const sessionName = session.name || session.title || session.current_intent || snapshot?.name || null
  const blockSummaries = summarizeBlocks(blocks)
  const blockTypes = blocks.map((block) => block?.type).filter(Boolean)
  const contracts = compactArray([
    ...blocks.map((block) => block?.contract),
    ...blocks.flatMap((block) => Array.isArray(block?.groups) ? block.groups.map((group) => group?.contract) : []),
    ...blocks.flatMap((block) => Array.isArray(block?.citations) ? block.citations.map((citation) => citation?.contract) : []),
    ...blocks.flatMap((block) => Array.isArray(block?.sources) ? block.sources.map((source) => source?.contract) : []),
    document.invariants?.read_status_contract,
    document.invariants?.mutation_business_contract,
    document.invariants?.no_op_mutation_contract,
  ])
  const approvalIds = compactArray([
    ...blocks.map((block) => block?.approval_id),
    ...blockSummaries.map((block) => block.approvalId),
  ])

  return {
    sessionId,
    sessionName: compactText(sessionName, 120) || null,
    sessionStatus: session.status || null,
    phase: snapshot?.phase || null,
    pendingApprovalId: snapshot?.pending_approval?.approval_id || null,
    responseDocumentState: document.state || null,
    responseDocumentRevision: document.revision ?? null,
    responseDocumentCurrentStepId: document.current_step_id || null,
    responseBlockTypes: blockTypes,
    responseApprovalIds: approvalIds,
    responseContracts: contracts,
    responseDocument: {
      state: document.state || null,
      revision: document.revision ?? null,
      currentStepId: document.current_step_id || null,
      blockTypes,
      blockIds: compactArray(blocks.map((block) => block?.id)),
      contracts,
      approvalIds,
      sourceCitations: summarizeSourceCitationsFromBlocks(blocks),
      runSteps: summarizeRunSteps(runSteps),
      blocks: blockSummaries,
    },
  }
}

function summarizeVisibleBlocks(blocks = []) {
  return blocks.slice(-8).map((block) => compactObject({
    type: block?.type || null,
    id: block?.id || null,
    contract: block?.contract || null,
    entityType: block?.entityType || null,
    approvalId: block?.approvalId || blockApprovalIdFromId(block?.id) || null,
    title: compactText(block?.title || '', 80) || null,
    text: compactText(block?.text || '', 180) || null,
    buttons: compactArray(block?.buttons || []),
  }))
}

function summarizeBusinessGroups(groups = []) {
  return asArray(groups).slice(0, 8).map((group) => compactObject({
    label: compactText(group?.label || group?.businessChange || group?.business_change || '', 80) || null,
    count: Number.isFinite(Number(group?.count ?? group?.record_count)) ? Number(group?.count ?? group?.record_count) : null,
    contract: group?.contract || null,
    entityType: group?.entityType || group?.entity_type || null,
    changeType: group?.changeType || group?.change_type || null,
    sourceStateBasis: group?.sourceStateBasis || group?.source_state_basis || null,
    fieldChangeCount: Number.isFinite(Number(group?.fieldChangeCount ?? group?.field_change_count))
      ? Number(group?.fieldChangeCount ?? group?.field_change_count)
      : null,
    text: compactText(group?.text || group?.summary || '', 120) || null,
  }))
}

function summarizeDuplicateEvidence(duplicates = []) {
  return asArray(duplicates).slice(0, 8).map((item) => compactObject({
    section: compactText(item?.section || '', 100) || null,
    records: compactArray(item?.records || [], 8),
  }))
}

export function summarizeFinalResponseQuality(quality = {}) {
  return compactObject({
    finalResultCardCount: Number.isFinite(Number(quality.finalResultCardCount))
      ? Number(quality.finalResultCardCount)
      : 0,
    finalSummaryText: compactText(quality.finalSummaryText || '', 180) || null,
    businessGroups: summarizeBusinessGroups(quality.businessGroups || []),
    affectedRecordPreviewCount: Number.isFinite(Number(quality.affectedRecordPreviewCount))
      ? Number(quality.affectedRecordPreviewCount)
      : 0,
    expandableAuditPresent: Boolean(quality.expandableAuditPresent),
    auditExpanded: Boolean(quality.auditExpanded),
    expandedAuditGroups: summarizeBusinessGroups(quality.expandedAuditGroups || []),
    forbiddenTextHits: compactArray(quality.forbiddenTextHits || [], 20),
    duplicateAffectedRecordEvidence: summarizeDuplicateEvidence(quality.duplicateAffectedRecordEvidence || []),
  })
}

export function forbiddenTextHits(text, expected = {}) {
  const forbidden = [...baseForbiddenProbeText, ...asArray(expected.forbiddenText)]
  if (expected.forbidWaitingApproval1) {
    forbidden.push({ label: 'stale Waiting for approval 1 after approval 1 was decided', pattern: /Waiting for approval 1/i })
  }
  if (expected.forbidApprovalRequired) {
    forbidden.push({ label: 'stale Approval required after completion', pattern: /Approval required/i })
  }
  return forbidden
    .filter((item) => matches(text, item?.pattern || item))
    .map((item) => item?.label || labelForPattern(item?.pattern || item))
}

export function summarizeVisibleUi(ui = {}, expected = {}) {
  const blocks = Array.isArray(ui.visibleBlocks) ? ui.visibleBlocks : []
  const blockSummaries = summarizeVisibleBlocks(blocks)
  const approvalIds = compactArray([
    ...asArray(ui.visibleApprovalIds),
    ...blockSummaries.map((block) => block.approvalId),
  ])
  const visibleContracts = compactArray([
    ...asArray(ui.visibleContracts),
    ...blockSummaries.map((block) => block.contract),
    ...asArray(ui.finalResponseQuality?.businessGroups).map((group) => group?.contract),
    ...asArray(ui.finalResponseQuality?.expandedAuditGroups).map((group) => group?.contract),
  ])
  const assistantTitle = ui.latestAssistantTitle || blockSummaries.find((block) => block.title)?.title || null
  const assistantMessage = ui.latestAssistantMessage || ui.latestAssistantText || ''

  return {
    activeSessionId: ui.activeSessionId || null,
    activeSessionName: compactText(ui.activeSessionName, 120) || null,
    headerStatus: ui.headerStatus || null,
    activeSidebarStatus: ui.activeSidebarStatus || null,
    latestUserPrompt: compactText(ui.latestUserPrompt, 220) || null,
    latestAssistant: {
      title: compactText(assistantTitle, 120) || null,
      message: compactText(assistantMessage, 360) || null,
    },
    visibleBlockTypes: compactArray(ui.visibleBlockTypes || blocks.map((block) => block.type)),
    visibleBlockIds: compactArray(ui.visibleBlockIds || blocks.map((block) => block.id)),
    visibleContracts,
    visibleBlocks: blockSummaries,
    visibleRunSteps: summarizeRunSteps(ui.visibleRunSteps || []),
    visibleApprovalIds: approvalIds,
    approvalButtons: compactArray(ui.approvalActionLabels || ui.approvalButtons || []),
    sourceChips: asArray(ui.sourceChips).slice(0, 12).map((chip) => compactObject({
      sourceId: chip?.sourceId || null,
      docId: chip?.docId || null,
      chunkId: chip?.chunkId || null,
      sourceNumber: chip?.sourceNumber || null,
      title: compactText(chip?.title || '', 80) || null,
      text: compactText(chip?.text || '', 40) || null,
    })),
    sourceDrawer: ui.sourceDrawer ? compactObject({
      open: Boolean(ui.sourceDrawer.open),
      view: ui.sourceDrawer.view || null,
      sourceId: ui.sourceDrawer.sourceId || null,
      docId: ui.sourceDrawer.docId || null,
      chunkId: ui.sourceDrawer.chunkId || null,
      sourceNumber: ui.sourceDrawer.sourceNumber || null,
      title: compactText(ui.sourceDrawer.title || '', 100) || null,
      entries: asArray(ui.sourceDrawer.entries).slice(0, 8).map((entry) => compactObject({
        role: entry?.role || null,
        sourceId: entry?.sourceId || null,
        docId: entry?.docId || null,
        chunkId: entry?.chunkId || null,
        sourceNumber: entry?.sourceNumber || null,
        title: compactText(entry?.title || '', 100) || null,
        openMode: entry?.openMode || null,
        highlightKind: entry?.highlightKind || null,
      })),
      pdf: ui.sourceDrawer.pdf ? compactObject({
        sourceId: ui.sourceDrawer.pdf.sourceId || null,
        docId: ui.sourceDrawer.pdf.docId || null,
        chunkId: ui.sourceDrawer.pdf.chunkId || null,
        sourceNumber: ui.sourceDrawer.pdf.sourceNumber || null,
        title: compactText(ui.sourceDrawer.pdf.title || '', 100) || null,
        src: compactText(ui.sourceDrawer.pdf.src || '', 180) || null,
        openMode: ui.sourceDrawer.pdf.openMode || null,
        highlightKind: ui.sourceDrawer.pdf.highlightKind || null,
      }) : null,
      text: compactText(ui.sourceDrawer.text || '', 180) || null,
    }) : null,
    forbiddenTextHits: compactArray(forbiddenTextHits(ui.visibleText || '', expected), 20),
    finalResponseQuality: summarizeFinalResponseQuality(ui.finalResponseQuality || {}),
  }
}

function compactExpected(expected = {}) {
  const output = {
    sessionStatus: expected.sessionStatus || expected.sessionStatuses || null,
    responseState: expected.responseState || expected.responseStates || null,
    pendingApprovalId: Object.hasOwn(expected, 'pendingApprovalId') ? expected.pendingApprovalId || null : undefined,
    visibleBlockTypes: expected.visibleBlockTypes || undefined,
    hiddenBlockTypes: expected.hiddenBlockTypes || undefined,
    backendBlockTypes: expected.backendBlockTypes || undefined,
    hiddenBackendBlockTypes: expected.hiddenBackendBlockTypes || undefined,
    responseContracts: expected.responseContracts || undefined,
    finalResponseQuality: expected.finalResponseQuality || undefined,
    textIncludes: asArray(expected.textIncludes).map(labelForPattern),
    textExcludes: asArray(expected.textExcludes).map(labelForPattern),
  }
  return Object.fromEntries(Object.entries(output).filter(([, value]) => value !== undefined && value !== null && !(Array.isArray(value) && value.length === 0)))
}

function hasDisplayableBackendBlock(backend, type) {
  return backend.responseDocument.blockTypes.includes(type) && DISPLAYABLE_BLOCK_TYPES.has(type)
}

function backendDocumentDisagrees(backend) {
  const document = backend.responseDocument
  const blockTypes = document.blockTypes
  if (backend.sessionStatus === 'WAITING_APPROVAL') {
    if (document.state && document.state !== 'waiting_approval') return 'session is WAITING_APPROVAL but response_document.state is not waiting_approval'
    if (backend.pendingApprovalId && !blockTypes.includes('approval_required')) return 'pending approval exists but response_document has no approval_required block'
    if (backend.pendingApprovalId && document.approvalIds.length && !document.approvalIds.includes(backend.pendingApprovalId)) {
      return 'pending approval id does not match response_document approval ids'
    }
  }
  if (backend.sessionStatus === 'COMPLETED') {
    if (document.state && document.state !== 'completed') return 'session is COMPLETED but response_document.state is not completed'
    if (blockTypes.includes('approval_required')) return 'completed response_document still contains approval_required'
    if (backend.pendingApprovalId) return 'completed session still has pending_approval'
  }
  if (document.state === 'waiting_approval' && !blockTypes.includes('approval_required')) {
    return 'waiting_approval response_document has no approval_required block'
  }
  if (document.state === 'completed' && blockTypes.includes('approval_required')) {
    return 'completed response_document still contains approval_required'
  }
  return null
}

function sessionListDisagrees(backend, visible, expected = {}) {
  const statuses = expectedStatuses(expected) || (backend.sessionStatus ? [backend.sessionStatus] : [])
  const allowed = asArray(expected.headerStatuses || expected.headerStatus)
  const allowedHeader = allowed.length ? allowed : expectedUiStatuses(statuses)
  const sidebar = asArray(expected.sidebarStatuses || expected.sidebarStatus)
  const allowedSidebar = sidebar.length ? sidebar : expectedUiStatuses(statuses)
  const expectedLabel = uiStatusByBackendStatus[backend.sessionStatus]

  if (allowedHeader?.length && visible.headerStatus && !allowedHeader.includes(visible.headerStatus)) {
    return `header shows ${visible.headerStatus} while backend maps to ${allowedHeader.join(' or ')}`
  }
  if (allowedSidebar?.length && visible.activeSidebarStatus && !allowedSidebar.includes(visible.activeSidebarStatus)) {
    return `sidebar shows ${visible.activeSidebarStatus} while backend maps to ${allowedSidebar.join(' or ')}`
  }
  if (expectedLabel && visible.headerStatus && visible.activeSidebarStatus && visible.headerStatus !== visible.activeSidebarStatus) {
    return `header (${visible.headerStatus}) and active sidebar (${visible.activeSidebarStatus}) disagree`
  }
  if (expectedLabel && visible.headerStatus && visible.headerStatus !== expectedLabel) {
    return `header shows ${visible.headerStatus} while backend session.status maps to ${expectedLabel}`
  }
  if (expectedLabel && visible.activeSidebarStatus && visible.activeSidebarStatus !== expectedLabel) {
    return `active sidebar shows ${visible.activeSidebarStatus} while backend session.status maps to ${expectedLabel}`
  }
  return null
}

function reducerOrderingDisagrees(backend, visible) {
  const visibleApproval = visible.visibleBlockTypes.includes('approval_required') || visible.approvalButtons.length > 0
  if (backend.sessionStatus === 'COMPLETED' || backend.responseDocument.state === 'completed') {
    if (visibleApproval) return 'backend is completed but visible UI still shows approval UI/actions'
  }
  if (!backend.pendingApprovalId && visibleApproval) {
    return 'backend has no pending approval but visible UI still shows approval UI/actions'
  }
  if (backend.pendingApprovalId && visible.visibleApprovalIds.length && !visible.visibleApprovalIds.includes(backend.pendingApprovalId)) {
    return 'visible approval id does not match backend pending_approval.approval_id'
  }
  return null
}

function rendererDomDisagrees(backend, visible, expected = {}) {
  for (const type of asArray(expected.visibleBlockTypes)) {
    if (hasDisplayableBackendBlock(backend, type) && !visible.visibleBlockTypes.includes(type)) {
      return `response_document contains ${type} but it is not visible in the DOM`
    }
  }
  for (const type of backend.responseDocument.blockTypes) {
    if (DISPLAYABLE_BLOCK_TYPES.has(type) && !visible.visibleBlockTypes.includes(type)) {
      return `response_document block ${type} is missing from visible DOM`
    }
  }
  return null
}

function expectedGroupMatches(actualGroup, expectedGroup) {
  const label = actualGroup?.label || ''
  const expectedLabel = expectedGroup?.label || expectedGroup?.businessChange || ''
  if (expectedLabel && label !== expectedLabel) return false
  if (expectedGroup?.labelPattern && !matches(label, expectedGroup.labelPattern)) return false
  if (expectedGroup?.labels && !asArray(expectedGroup.labels).includes(label)) return false
  if (Object.hasOwn(expectedGroup || {}, 'count') && Number(actualGroup?.count) !== Number(expectedGroup.count)) return false
  if (expectedGroup?.contract && actualGroup?.contract !== expectedGroup.contract) return false
  if (expectedGroup?.entityType && actualGroup?.entityType !== expectedGroup.entityType) return false
  if (expectedGroup?.changeType && actualGroup?.changeType !== expectedGroup.changeType) return false
  if (expectedGroup?.sourceStateBasis && actualGroup?.sourceStateBasis !== expectedGroup.sourceStateBasis) return false
  if (
    Object.hasOwn(expectedGroup || {}, 'fieldChangeCountMin') &&
    Number(actualGroup?.fieldChangeCount || 0) < Number(expectedGroup.fieldChangeCountMin)
  ) return false
  return true
}

function typedBusinessGroupEvidenceViolations(rules = {}) {
  if (rules.requireTypedContractEvidence === false) return []
  const violations = []
  for (const expectedGroup of asArray(rules.businessGroups)) {
    const label = expectedGroup?.label || expectedGroup?.businessChange || expectedGroup?.labelPattern || '<business group>'
    const contract = expectedGroup?.contract || null
    const entityType = expectedGroup?.entityType || expectedGroup?.entity_type || null
    const hasFieldChangeEvidence = (
      Object.hasOwn(expectedGroup || {}, 'fieldChangeCountMin') ||
      Object.hasOwn(expectedGroup || {}, 'fieldChangeCount') ||
      Object.hasOwn(expectedGroup || {}, 'field_change_count')
    )
    if (!contract) {
      violations.push(`text-only business group expectation ${label} must include typed contract evidence`)
      continue
    }
    if (!entityType) {
      violations.push(`business group expectation ${label} must include entity type contract evidence`)
    }
    if (contract === 'business_change_v1' && !hasFieldChangeEvidence) {
      violations.push(`business_change_v1 expectation ${label} must include typed field-change evidence`)
    }
  }
  return violations
}

export function finalResponseQualityViolations(quality = {}, expected = {}) {
  const violations = []
  const rules = expected.finalResponseQuality || (
    Object.hasOwn(expected, 'finalResultCardCount') ? expected : null
  )
  if (!rules || Object.keys(rules).length === 0) return violations
  violations.push(...typedBusinessGroupEvidenceViolations(rules))

  if (Object.hasOwn(rules, 'finalResultCardCount') && quality.finalResultCardCount !== rules.finalResultCardCount) {
    violations.push(`final result card count expected ${rules.finalResultCardCount} but saw ${quality.finalResultCardCount}`)
  }
  if (rules.finalSummaryText && !matches(quality.finalSummaryText || '', rules.finalSummaryText)) {
    violations.push(`final summary text did not match ${labelForPattern(rules.finalSummaryText)}`)
  }
  for (const expectedGroup of asArray(rules.businessGroups)) {
    if (!asArray(quality.businessGroups).some((group) => expectedGroupMatches(group, expectedGroup))) {
      violations.push(`business change group missing ${expectedGroup.label || expectedGroup.businessChange || expectedGroup.labelPattern || JSON.stringify(expectedGroup)}`)
    }
  }
  if (Object.hasOwn(rules, 'affectedRecordPreviewMax') && quality.affectedRecordPreviewCount > rules.affectedRecordPreviewMax) {
    violations.push(`affected-record preview expected at most ${rules.affectedRecordPreviewMax} rows but saw ${quality.affectedRecordPreviewCount}`)
  }
  if (Object.hasOwn(rules, 'affectedRecordPreviewMin') && quality.affectedRecordPreviewCount < rules.affectedRecordPreviewMin) {
    violations.push(`affected-record preview expected at least ${rules.affectedRecordPreviewMin} rows but saw ${quality.affectedRecordPreviewCount}`)
  }
  if (rules.expandableAuditPresent && !quality.expandableAuditPresent) {
    violations.push('expandable clean audit was not present')
  }
  if (rules.auditExpanded && !quality.auditExpanded) {
    violations.push('clean audit was expected to be expanded but was collapsed')
  }
  for (const expectedGroup of asArray(rules.expandedAuditGroups)) {
    if (!asArray(quality.expandedAuditGroups).some((group) => expectedGroupMatches(group, expectedGroup))) {
      violations.push(`expanded audit group missing ${expectedGroup.label || expectedGroup.businessChange || expectedGroup.labelPattern || JSON.stringify(expectedGroup)}`)
    }
  }
  if (rules.forbidFinalResponseText !== false && asArray(quality.forbiddenTextHits).length) {
    violations.push(`forbidden final response text: ${quality.forbiddenTextHits.join(', ')}`)
  }
  if (rules.forbidDuplicateAffectedRecords !== false && asArray(quality.duplicateAffectedRecordEvidence).length) {
    const sections = quality.duplicateAffectedRecordEvidence
      .map((item) => `${item.section || '<section>'}: ${(item.records || []).join(', ')}`)
      .join('; ')
    violations.push(`duplicate affected records in rendered section: ${sections}`)
  }
  return violations
}

export function classifySemanticProbe(probe, expected = {}) {
  const backend = probe.backend || summarizeBackendSnapshot(probe.snapshot)
  const visible = probe.visible || probe.ui || summarizeVisibleUi(probe.ui || {}, expected)
  const statuses = expectedStatuses(expected)
  const states = expectedResponseStates(expected)

  if (statuses?.length && !statuses.includes(backend.sessionStatus)) {
    return {
      classification: 'backend_state_gap',
      reasons: [`backend session.status expected ${statuses.join(' or ')} but saw ${backend.sessionStatus || '<missing>'}`],
    }
  }
  if (states?.length && !states.includes(backend.responseDocumentState)) {
    return {
      classification: 'response_document_gap',
      reasons: [`response_document.state expected ${states.join(' or ')} but saw ${backend.responseDocumentState || '<missing>'}`],
    }
  }

  const documentReason = backendDocumentDisagrees(backend)
  if (documentReason) return { classification: 'response_document_gap', reasons: [documentReason] }

  const reducerReason = reducerOrderingDisagrees(backend, visible)
  if (reducerReason) return { classification: 'reducer_ordering_gap', reasons: [reducerReason] }

  const sessionReason = sessionListDisagrees(backend, visible, expected)
  if (sessionReason) return { classification: 'session_list_sync_gap', reasons: [sessionReason] }

  const rendererReason = rendererDomDisagrees(backend, visible, expected)
  if (rendererReason) return { classification: 'renderer_dom_gap', reasons: [rendererReason] }

  const qualityViolations = finalResponseQualityViolations(visible.finalResponseQuality || {}, expected)
  if (qualityViolations.length) {
    return { classification: 'final_response_visual_quality_gap', reasons: qualityViolations.slice(0, 3) }
  }

  return { classification: 'unknown', reasons: [] }
}

export function buildSemanticProbe({
  checkpoint = null,
  snapshot = null,
  ui = {},
  expected = {},
  violations = [],
} = {}) {
  const backend = summarizeBackendSnapshot(snapshot)
  const visible = summarizeVisibleUi(ui, expected)
  const activeSessionId = visible.activeSessionId || backend.sessionId || null
  const activeSessionName = visible.activeSessionName || backend.sessionName || null
  const probe = {
    kind: 'factory_agent_response_document_semantic_probe',
    version: 1,
    checkpoint,
    activeSession: {
      id: activeSessionId,
      name: activeSessionName,
    },
    diagnosis: { classification: 'unknown', reasons: [] },
    expectations: compactExpected(expected),
    violations: asArray(violations).slice(0, 16).map((item) => compactText(item, 220)),
    visible,
    backend,
    artifactUse: 'Read this semantic probe first; screenshots and traces are supporting evidence.',
  }
  probe.diagnosis = classifySemanticProbe(probe, expected)
  if (visible.forbiddenTextHits.length && probe.diagnosis.classification === 'unknown') {
    probe.diagnosis = {
      classification: 'renderer_dom_gap',
      reasons: [`forbidden visible text: ${visible.forbiddenTextHits.join(', ')}`],
    }
  }
  return probe
}

export function semanticProbeHumanSummary(probe) {
  const diagnosis = probe?.diagnosis || { classification: 'unknown', reasons: [] }
  const backend = probe?.backend || {}
  const visible = probe?.visible || {}
  const reason = diagnosis.reasons?.length ? ` ${diagnosis.reasons[0]}` : ''
  return [
    `Semantic probe diagnosis: ${diagnosis.classification}.${reason}`,
    `Backend: session.status=${backend.sessionStatus || '<missing>'}, response_document.state=${backend.responseDocumentState || '<missing>'}, revision=${backend.responseDocumentRevision ?? '<missing>'}, pendingApprovalId=${backend.pendingApprovalId || '<none>'}.`,
    `Visible: header=${visible.headerStatus || '<missing>'}, sidebar=${visible.activeSidebarStatus || '<missing>'}, blocks=${(visible.visibleBlockTypes || []).join(', ') || '<none>'}, approvals=${(visible.visibleApprovalIds || []).join(', ') || '<none>'}.`,
    visible.finalResponseQuality
      ? `Final response: cards=${visible.finalResponseQuality.finalResultCardCount ?? 0}, groups=${(visible.finalResponseQuality.businessGroups || []).map((group) => `${group.label}:${group.count}`).join(', ') || '<none>'}, previewRows=${visible.finalResponseQuality.affectedRecordPreviewCount ?? 0}, audit=${visible.finalResponseQuality.expandableAuditPresent ? visible.finalResponseQuality.auditExpanded ? 'expanded' : 'collapsed' : '<missing>'}.`
      : null,
  ].filter(Boolean).join('\n')
}

export function serializeSemanticProbe(probe) {
  return redactSensitiveArtifactText(JSON.stringify(probe, null, 2))
}

function textLines(node) {
  return String(node?.innerText || node?.textContent || '')
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
}

function messageTextFromContainer(container, roleLabel) {
  const lines = textLines(container)
  return lines
    .filter((line) => line !== roleLabel && !/^\d{1,2}:\d{2}/.test(line) && line !== 'eMAS Response')
    .join(' ')
}

function activityStateFromIcon(iconText) {
  const icon = String(iconText || '').trim()
  if (icon === 'hourglass_empty') return 'waiting'
  if (icon === 'check') return 'success'
  if (icon === 'done_all') return 'complete'
  if (icon === 'priority_high') return 'error'
  if (icon === 'sync') return 'retry'
  if (icon === 'progress_activity') return 'running'
  return null
}

export async function collectVisibleResponseDocumentUi(page) {
  return page.evaluate((labels) => {
    const statusSet = new Set(labels)
    const compact = (value, limit = 260) => {
      const text = String(value || '').replace(/\s+/g, ' ').trim()
      return text.length <= limit ? text : `${text.slice(0, limit)}...`
    }
    const blockApprovalId = (id) => {
      const match = String(id || '').match(/^approval:(.+)$/)
      return match ? match[1] : null
    }
    const stateFromIcon = (iconText) => {
      const icon = String(iconText || '').trim()
      if (icon === 'hourglass_empty') return 'waiting'
      if (icon === 'check') return 'success'
      if (icon === 'done_all') return 'complete'
      if (icon === 'priority_high') return 'error'
      if (icon === 'sync') return 'retry'
      if (icon === 'progress_activity') return 'running'
      return null
    }
    const lines = (node) => String(node?.innerText || node?.textContent || '')
      .split(/\n+/)
      .map((line) => line.trim())
      .filter(Boolean)
    const visibleTextWithoutIcons = (node) => {
      if (!node) return ''
      const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, {
        acceptNode(textNode) {
          const parent = textNode.parentElement
          if (parent?.closest?.('.material-symbols-outlined')) return NodeFilter.FILTER_REJECT
          return NodeFilter.FILTER_ACCEPT
        },
      })
      const values = []
      while (walker.nextNode()) values.push(walker.currentNode.nodeValue || '')
      return values.join(' ').replace(/\s+/g, ' ').trim()
    }
    const messageText = (container, roleLabel) => lines(container)
      .filter((line) => line !== roleLabel && !/^\d{1,2}:\d{2}/.test(line) && line !== 'eMAS Response')
      .join(' ')
    const groupFromNode = (node) => ({
      label: node.getAttribute('data-business-change-label') || '',
      count: Number(node.getAttribute('data-business-change-count') || 0),
      contract: node.getAttribute('data-response-contract') || null,
      entityType: node.getAttribute('data-entity-type') || null,
      changeType: node.getAttribute('data-change-type') || null,
      sourceStateBasis: node.getAttribute('data-source-state-basis') || null,
      fieldChangeCount: Number(node.getAttribute('data-field-change-count') || 0),
      text: compact(node.innerText || node.textContent || '', 140),
    })
    const duplicateRowsInSection = (section, sectionName) => {
      const counts = new Map()
      for (const row of Array.from(section.querySelectorAll('[data-affected-record-row]'))) {
        const record = (row.getAttribute('data-record-id') || row.textContent || '').trim()
        if (!record || /^\+\d+ more$/.test(record)) continue
        counts.set(record, (counts.get(record) || 0) + 1)
      }
      const records = Array.from(counts.entries())
        .filter(([, count]) => count > 1)
        .map(([record]) => record)
      return records.length ? { section: sectionName, records } : null
    }

    const activeSessionId = window.localStorage.getItem('factory_agent_active_session_id') || null
    const dialog = document.querySelector('[role="dialog"]') || document.body
    const heading = dialog.querySelector('h2')
    const headerRegion = heading?.parentElement || dialog
    const headerStatus = Array.from(headerRegion.querySelectorAll('span'))
      .map((node) => (node.textContent || '').trim())
      .find((value) => statusSet.has(value)) || null
    const activeSessionButton = dialog.querySelector('aside [aria-current="page"]')
    const activeSidebarStatus = activeSessionButton
      ? Array.from(activeSessionButton.querySelectorAll('span'))
        .map((node) => (node.textContent || '').trim())
        .find((value) => statusSet.has(value)) || null
      : null
    const activeSessionName = activeSessionButton
      ? Array.from(activeSessionButton.querySelectorAll('span'))
        .map((node) => (node.textContent || '').trim())
        .find((value) => value && !statusSet.has(value))
      : heading?.textContent?.trim() || null

    const roleLabels = Array.from(dialog.querySelectorAll('span'))
      .filter((node) => ['You', 'eMAS AI Assistant'].includes((node.textContent || '').trim()))
    const latestUserLabel = [...roleLabels].reverse().find((node) => (node.textContent || '').trim() === 'You')
    const latestAssistantLabel = [...roleLabels].reverse().find((node) => (node.textContent || '').trim() === 'eMAS AI Assistant')
    const latestUserContainer = latestUserLabel?.closest('.mb-6') || null
    const latestAssistantContainer = latestAssistantLabel?.closest('.mb-6') || null

    const roots = Array.from(dialog.querySelectorAll('[data-response-document-root]'))
    const latestRoot = roots[roots.length - 1] || latestAssistantContainer || dialog
    const visibleBlocks = Array.from(latestRoot.querySelectorAll('[data-response-block-type]')).map((node) => {
      const buttons = Array.from(node.querySelectorAll('button'))
        .map((button) => (button.textContent || '').trim())
        .filter(Boolean)
      const type = node.getAttribute('data-response-block-type') || null
      const id = node.getAttribute('data-response-block-id') || null
      const contract = node.getAttribute('data-response-contract') || null
      const entityType = node.getAttribute('data-entity-type') || null
      const blockLines = lines(node)
      return {
        type,
        id,
        contract,
        entityType,
        approvalId: blockApprovalId(id),
        title: blockLines[0] || null,
        text: node.innerText || node.textContent || '',
        buttons,
        hasApprove: buttons.includes('Approve'),
        hasReject: buttons.includes('Reject'),
      }
    })
    const approvalActionLabels = Array.from(latestRoot.querySelectorAll('button'))
      .map((button) => (button.textContent || '').trim())
      .filter((label) => label === 'Approve' || label === 'Reject')
    const visibleRunSteps = Array.from(latestRoot.querySelectorAll('button[aria-expanded], ol li')).map((node) => {
      const icon = node.querySelector('.material-symbols-outlined')?.textContent || ''
      const rowLines = lines(node).filter((line) => !/^\d+ updates?$/.test(line) && line !== 'expand_more' && line !== 'expand_less')
      return {
        title: compact(rowLines[0] || node.textContent || '', 140),
        state: stateFromIcon(icon),
      }
    }).filter((row) => row.title)
    const finalCards = Array.from(latestRoot.querySelectorAll('[data-final-result-card]'))
    const latestFinalCard = finalCards[finalCards.length - 1] || null
    const audit = latestFinalCard?.querySelector('details[data-clean-audit]') || latestRoot.querySelector('details[data-clean-audit]')
    const finalVisibleText = visibleTextWithoutIcons(latestRoot)
    const finalForbidden = [
      ['raw assistant done_all marker', /(?:^|\s)done_all(?:\s|$)/i],
      ['raw assistant success markdown', /\*\*Success\*\*/i],
      ['backend operation aggregate leak', /Updated 63 jobs across 22 approved steps/i],
      ['internal Operation ID', /Operation ID/i],
      ['internal Step ID', /Step ID/i],
      ['internal Row ID', /Row ID/i],
      ['legacy approved-step aggregate', /Updated 21 jobs across 2 approved steps/i],
    ]
    const duplicateEvidence = []
    for (const [index, section] of Array.from(latestRoot.querySelectorAll('[data-affected-record-preview]')).entries()) {
      const duplicate = duplicateRowsInSection(section, `affected-record-preview-${index + 1}`)
      if (duplicate) duplicateEvidence.push(duplicate)
    }
    if (audit?.open) {
      for (const group of Array.from(audit.querySelectorAll('[data-clean-audit-group]'))) {
        const label = group.getAttribute('data-business-change-label') || 'clean-audit-group'
        const duplicate = duplicateRowsInSection(group, `clean-audit:${label}`)
        if (duplicate) duplicateEvidence.push(duplicate)
      }
    }
    const finalResponseQuality = {
      finalResultCardCount: finalCards.length,
      finalSummaryText: compact(latestFinalCard?.querySelector('[data-final-summary]')?.innerText || '', 220),
      businessGroups: Array.from(latestFinalCard?.querySelectorAll('[data-business-change-group]') || []).map(groupFromNode),
      affectedRecordPreviewCount: latestFinalCard
        ? Array.from(latestFinalCard.querySelectorAll('[data-affected-record-preview] [data-affected-record-row]')).length
        : 0,
      expandableAuditPresent: Boolean(audit),
      auditExpanded: Boolean(audit?.open),
      expandedAuditGroups: audit?.open
        ? Array.from(audit.querySelectorAll('[data-clean-audit-group]')).map(groupFromNode)
        : [],
      forbiddenTextHits: finalForbidden
        .filter(([, pattern]) => pattern.test(finalVisibleText))
        .map(([label]) => label),
      duplicateAffectedRecordEvidence: duplicateEvidence,
    }
    const visibleContracts = Array.from(latestRoot.querySelectorAll('[data-response-contract]'))
      .map((node) => node.getAttribute('data-response-contract'))
      .filter(Boolean)
    const sourceChips = Array.from(latestRoot.querySelectorAll('[data-source-chip]')).map((node) => ({
        sourceId: node.getAttribute('data-source-id') || null,
        docId: node.getAttribute('data-doc-id') || null,
        chunkId: node.getAttribute('data-chunk-id') || null,
        sourceNumber: node.getAttribute('data-source-number') || null,
        title: node.getAttribute('data-source-title') || null,
        openMode: node.getAttribute('data-source-open-mode') || null,
        highlightKind: node.getAttribute('data-source-highlight-kind') || null,
        text: compact(node.innerText || node.textContent || '', 40),
      }))
    const drawer = latestRoot.querySelector('[data-source-drawer]')
    const drawerEntries = drawer
      ? Array.from(drawer.querySelectorAll('[data-source-drawer-entry]')).map((node) => ({
        role: node.getAttribute('data-source-role') || null,
        sourceId: node.getAttribute('data-source-id') || null,
        docId: node.getAttribute('data-doc-id') || null,
        chunkId: node.getAttribute('data-chunk-id') || null,
        sourceNumber: node.getAttribute('data-source-number') || null,
        title: node.getAttribute('data-source-title') || null,
        openMode: node.getAttribute('data-source-open-mode') || null,
        highlightKind: node.getAttribute('data-source-highlight-kind') || null,
      }))
      : []
    const pdfFrame = drawer?.querySelector('[data-source-pdf-frame]') || null
    const sourceDrawer = drawer
      ? {
        open: true,
        view: drawer.getAttribute('data-source-drawer-view') || null,
        sourceId: drawer.getAttribute('data-source-id') || null,
        docId: drawer.getAttribute('data-doc-id') || null,
        chunkId: drawer.getAttribute('data-chunk-id') || null,
        sourceNumber: drawer.getAttribute('data-source-number') || null,
        title: drawer.getAttribute('data-source-title') || null,
        openMode: drawer.getAttribute('data-source-open-mode') || null,
        highlightKind: drawer.getAttribute('data-source-highlight-kind') || null,
        entries: drawerEntries,
        pdf: pdfFrame
          ? {
            sourceId: pdfFrame.getAttribute('data-source-id') || null,
            docId: pdfFrame.getAttribute('data-doc-id') || null,
            chunkId: pdfFrame.getAttribute('data-chunk-id') || null,
            sourceNumber: pdfFrame.getAttribute('data-source-number') || null,
            title: pdfFrame.getAttribute('data-source-title') || null,
            src: pdfFrame.getAttribute('src') || null,
            openMode: pdfFrame.getAttribute('data-source-open-mode') || null,
            highlightKind: pdfFrame.getAttribute('data-source-highlight-kind') || null,
          }
          : null,
        text: compact(drawer.innerText || drawer.textContent || '', 220),
      }
      : null

    return {
      activeSessionId,
      activeSessionName,
      headerStatus,
      activeSidebarStatus,
      latestUserPrompt: latestUserContainer ? messageText(latestUserContainer, 'You') : null,
      latestAssistantTitle: latestAssistantContainer ? lines(latestAssistantContainer).find((line) => line === 'eMAS Response') || null : null,
      latestAssistantMessage: latestAssistantContainer ? messageText(latestAssistantContainer, 'eMAS AI Assistant') : null,
      visibleBlockTypes: visibleBlocks.map((block) => block.type).filter(Boolean),
      visibleBlockIds: visibleBlocks.map((block) => block.id).filter(Boolean),
      visibleContracts,
      visibleBlocks,
      visibleRunSteps,
      visibleApprovalIds: visibleBlocks.map((block) => block.approvalId).filter(Boolean),
      approvalActionLabels,
      sourceChips,
      sourceDrawer,
      latestAssistantText: latestRoot.innerText || latestRoot.textContent || '',
      visibleText: dialog.innerText || document.body.innerText || '',
      finalResponseQuality,
    }
  }, statusLabels)
}

export const probeInternalsForTest = Object.freeze({
  activityStateFromIcon,
  messageTextFromContainer,
  textLines,
})
