const DOCUMENT_STATES = new Set([
  'running',
  'waiting_approval',
  'waiting_confirmation',
  'completed',
  'failed',
  'blocked',
  'rejected',
  'expired',
  'cancelled',
])

const STEP_KINDS = new Set(['analysis', 'read', 'approval', 'mutation', 'knowledge', 'diagnostic', 'cancelled', 'completed'])
const STEP_STATES = new Set(['pending', 'current', 'waiting', 'completed', 'failed', 'rejected', 'expired', 'cancelled'])
const BLOCK_TYPES = new Set([
  'run_activity',
  'short_message',
  'approval_required',
  'approval_card',
  'completed_step',
  'result_summary',
  'mutation_result',
  'result_table',
  'status_result',
  'record_preview',
  'knowledge_answer',
  'source_list',
  'warning',
  'diagnostic',
])

const ACTIVITY_GROUP_BY_KIND = {
  analysis: 'planning',
  read: 'research',
  approval: 'approval',
  mutation: 'research',
  knowledge: 'research',
  diagnostic: 'system',
  cancelled: 'system',
  completed: 'response',
}

const ACTIVITY_STATE_BY_STEP = {
  pending: 'running',
  current: 'running',
  waiting: 'waiting',
  completed: 'success',
  failed: 'error',
  rejected: 'error',
  expired: 'error',
  cancelled: 'complete',
}

function cleanString(value) {
  return value == null ? '' : String(value).trim()
}

function cleanObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function cleanRows(value) {
  return Array.isArray(value)
    ? value.filter((row) => row && typeof row === 'object' && !Array.isArray(row))
    : []
}

function cleanGroups(value) {
  return Array.isArray(value)
    ? value.filter((group) => group && typeof group === 'object' && !Array.isArray(group))
    : []
}

function cleanSources(value) {
  return Array.isArray(value)
    ? value.filter((source) => source && typeof source === 'object' && !Array.isArray(source))
    : []
}

function cleanStatusFields(value) {
  return Array.isArray(value)
    ? value
      .filter((field) => field && typeof field === 'object' && !Array.isArray(field))
      .map((field) => ({
        ...field,
        key: cleanString(field.key),
        label: cleanString(field.label),
        value: cleanString(field.value),
        primary: Boolean(field.primary),
      }))
      .filter((field) => field.label && field.value)
    : []
}

function fallbackId(prefix, index) {
  return `${prefix}:${index + 1}`
}

export function humanizeResponseDocumentKey(key) {
  return String(key || 'field')
    .replace(/\{.*?\}/g, '')
    .replace(/[_-]+/g, ' ')
    .replace(/\bid\b/gi, 'ID')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^\w/, (c) => c.toUpperCase())
}

function orderedRowKeys(rows) {
  const preferred = [
    'display_id',
    'record_id',
    'job_id',
    'machine_id',
    'id',
    'entity_type',
    'change',
    'status',
    'outcome',
    'previous_priority',
    'current_priority',
    'new_priority',
    'priority',
    'error',
    'reason',
  ]
  const seen = new Set()
  const keys = []
  for (const key of preferred) {
    if (rows.some((row) => Object.prototype.hasOwnProperty.call(row, key))) {
      seen.add(key)
      keys.push(key)
    }
  }
  for (const row of rows) {
    for (const key of Object.keys(row || {})) {
      if (!seen.has(key)) {
        seen.add(key)
        keys.push(key)
      }
    }
  }
  return keys.slice(0, 8)
}

export function tablePresentationFromResponseRows(rows, title = 'Affected records') {
  const safeRows = cleanRows(rows)
  if (!safeRows.length) return null
  const keys = orderedRowKeys(safeRows)
  if (!keys.length) return null
  return {
    render_hint: 'table',
    title,
    table: {
      columns: keys.map((key) => ({ key, label: humanizeResponseDocumentKey(key) })),
      rows: safeRows,
      displayed_rows: safeRows.length,
      total_rows: safeRows.length,
    },
  }
}

function normalizeRunStep(step, index, violations) {
  if (!step || typeof step !== 'object' || Array.isArray(step)) {
    violations.push(`run_steps[${index}] is not an object`)
    return null
  }
  const stepId = cleanString(step.step_id || step.stepId || step.id)
  const kind = cleanString(step.kind)
  const state = cleanString(step.state)
  const title = cleanString(step.title)
  if (!stepId) violations.push(`run_steps[${index}] is missing step_id`)
  if (!STEP_KINDS.has(kind)) violations.push(`run_steps[${index}] has invalid kind`)
  if (!STEP_STATES.has(state)) violations.push(`run_steps[${index}] has invalid state`)
  if (!title) violations.push(`run_steps[${index}] is missing title`)
  if (!stepId || !STEP_KINDS.has(kind) || !STEP_STATES.has(state) || !title) return null
  return {
    ...step,
    step_id: stepId,
    kind,
    state,
    title,
    summary: cleanString(step.summary) || null,
    approval_id: cleanString(step.approval_id || step.approvalId) || null,
    operation_id: cleanString(step.operation_id || step.operationId) || null,
    record_count: Number.isFinite(Number(step.record_count)) ? Number(step.record_count) : null,
    current: Boolean(step.current),
    diagnostics: cleanObject(step.diagnostics),
  }
}

function normalizeBlock(block, index, violations) {
  if (!block || typeof block !== 'object' || Array.isArray(block)) {
    violations.push(`blocks[${index}] is not an object`)
    return null
  }
  const type = cleanString(block.type)
  const id = cleanString(block.id) || fallbackId(type || 'block', index)
  if (!BLOCK_TYPES.has(type)) {
    violations.push(`blocks[${index}] has unsupported type`)
    return null
  }
  const normalizedType = type === 'approval_card' ? 'approval_required' : type
  const rows = cleanRows(block.rows)
  const groups = cleanGroups(block.groups)
  const sources = cleanSources(block.sources)
  return {
    ...block,
    id,
    type: normalizedType,
    title: cleanString(block.title) || defaultBlockTitle(normalizedType),
    message: cleanString(block.message),
    summary: cleanString(block.summary),
    user_message: cleanString(block.user_message || block.userMessage),
    answer: cleanString(block.answer),
    approval_id: cleanString(block.approval_id || block.approvalId) || null,
    operation_id: cleanString(block.operation_id || block.operationId) || null,
    contract: cleanString(block.contract) || null,
    rows,
    groups,
    sources,
    fields: cleanStatusFields(block.fields),
    secondary_fields: cleanStatusFields(block.secondary_fields || block.secondaryFields),
    steps: Array.isArray(block.steps) ? block.steps.filter((row) => row && typeof row === 'object') : [],
    impact: cleanObject(block.impact),
    technical_details: cleanObject(block.technical_details || block.technicalDetails),
    next_actions: Array.isArray(block.next_actions || block.nextActions)
      ? (block.next_actions || block.nextActions).filter((action) => action && typeof action === 'object')
      : [],
    retry_safety: cleanObject(block.retry_safety || block.retrySafety),
    details_collapsed: block.details_collapsed !== false,
  }
}

function defaultBlockTitle(type) {
  if (type === 'approval_required') return 'Approval required'
  if (type === 'completed_step') return 'Completed step'
  if (type === 'result_summary') return 'Result summary'
  if (type === 'mutation_result') return 'Mutation result'
  if (type === 'result_table') return 'Affected records'
  if (type === 'status_result') return 'Status'
  if (type === 'record_preview') return 'Records'
  if (type === 'source_list') return 'Knowledge sources'
  if (type === 'diagnostic') return 'Needs attention'
  if (type === 'warning') return 'Warning'
  return ''
}

export function invalidResponseDocumentDiagnostic(violations = []) {
  const details = violations.length ? violations : ['response_document did not match the expected frontend contract']
  return {
    version: 1,
    id: 'invalid-response-document',
    document_id: 'invalid-response-document',
    turn_id: null,
    operation_id: null,
    revision: 0,
    revision_source: 'frontend_validation',
    state: 'failed',
    status: 'failed',
    summary: 'I could not render a valid response document for this run.',
    message: 'I could not render a valid response document for this run.',
    current_step_id: 'diagnostic:response_document_invalid',
    run_steps: [
      {
        step_id: 'diagnostic:response_document_invalid',
        kind: 'diagnostic',
        state: 'failed',
        title: 'Response document invalid',
        summary: 'The response document payload did not match the expected contract.',
        current: true,
        diagnostics: { reason: 'response_document_invalid' },
      },
    ],
    blocks: [
      {
        id: 'message:response_document_invalid',
        type: 'short_message',
        message: 'I could not render a valid response document for this run.',
        status: 'failed',
      },
      {
        id: 'diagnostic:response_document_invalid',
        type: 'diagnostic',
        severity: 'error',
        reason: 'response_document_invalid',
        title: 'Response document invalid',
        user_message: 'The response document payload did not match the expected contract.',
        cause: 'The frontend received response_document, but required fields were missing or malformed.',
        impact: { stale_presentation_fallback_used: false },
        current_state: 'Showing a diagnostic instead of older presentation content.',
        next_action: 'Refresh the session or start a new request after the backend contract is healthy.',
        next_actions: [{ id: 'view_diagnostics', label: 'View diagnostics' }],
        retry_safety: { safe_to_retry: false, policy: 'retry_after_contract_fix' },
        technical_details: { reason: 'response_document_invalid', violations: details, sanitized: true },
        details_collapsed: true,
      },
    ],
    invariants: { invalid_response_document: true },
    diagnostics: { reason: 'response_document_invalid', violations: details, sanitized: true },
    invalid: true,
  }
}

export function normalizeResponseDocument(value) {
  if (value == null) return { status: 'absent', document: null, violations: [] }
  const violations = []
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { status: 'invalid', document: invalidResponseDocumentDiagnostic(['response_document is not an object']), violations: ['response_document is not an object'] }
  }

  const version = Number(value.version)
  const id = cleanString(value.id || value.document_id || value.documentId)
  const documentId = cleanString(value.document_id || value.documentId || value.id)
  const state = cleanString(value.state || value.status)
  const status = cleanString(value.status || value.state)
  const revision = Number(value.revision)
  if (version !== 1) violations.push('version must be 1')
  if (!documentId) violations.push('document_id is required')
  if (!id) violations.push('id is required')
  if (!DOCUMENT_STATES.has(state)) violations.push('state is invalid')
  if (!DOCUMENT_STATES.has(status)) violations.push('status is invalid')
  if (!Number.isFinite(revision) || revision < 0) violations.push('revision must be a non-negative number')
  if (!Array.isArray(value.run_steps || value.runSteps)) violations.push('run_steps must be an array')
  if (!Array.isArray(value.blocks)) violations.push('blocks must be an array')

  const runSteps = Array.isArray(value.run_steps || value.runSteps)
    ? (value.run_steps || value.runSteps).map((step, index) => normalizeRunStep(step, index, violations)).filter(Boolean)
    : []
  const blocks = Array.isArray(value.blocks)
    ? value.blocks.map((block, index) => normalizeBlock(block, index, violations)).filter(Boolean)
    : []

  if (violations.length) {
    return { status: 'invalid', document: invalidResponseDocumentDiagnostic(violations), violations }
  }

  const normalized = {
    ...value,
    version: 1,
    id,
    document_id: documentId,
    turn_id: cleanString(value.turn_id || value.turnId) || null,
    operation_id: cleanString(value.operation_id || value.operationId) || null,
    revision,
    revision_source: cleanString(value.revision_source || value.revisionSource) || 'unknown',
    state,
    status,
    summary: cleanString(value.summary) || null,
    message: cleanString(value.message) || null,
    current_step_id: cleanString(value.current_step_id || value.currentStepId) || null,
    run_steps: runSteps,
    blocks,
    invariants: cleanObject(value.invariants),
    diagnostics: cleanObject(value.diagnostics),
    invalid: false,
  }
  return { status: 'valid', document: normalized, violations: [] }
}

export function responseDocumentMessage(document) {
  if (!document) return null
  const shortBlock = (document.blocks || []).find((block) => block.type === 'short_message' && block.message)
  if (shortBlock?.message) return shortBlock.message
  return document.message || document.summary || null
}

export function sourcesFromResponseDocument(document) {
  if (!document) return []
  const sources = []
  for (const block of document.blocks || []) {
    if (block.type === 'source_list') sources.push(...cleanSources(block.sources))
  }
  return sources
}

export function activityStepsFromResponseDocument(document) {
  const steps = Array.isArray(document?.run_steps) ? document.run_steps : []
  return steps.map((step, index) => {
    const terminalComplete = step.kind === 'completed' || step.state === 'completed'
    return {
      id: step.step_id || fallbackId('response-document-step', index),
      timestamp: index + 1,
      group: ACTIVITY_GROUP_BY_KIND[step.kind] || 'system',
      label: step.title,
      detail: step.summary || null,
      state: terminalComplete && step.kind === 'completed'
        ? 'complete'
        : ACTIVITY_STATE_BY_STEP[step.state] || 'running',
    }
  })
}
