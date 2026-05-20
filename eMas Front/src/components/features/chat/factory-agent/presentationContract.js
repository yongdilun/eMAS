const TERMINAL_STATES = new Set(['completed', 'failed', 'rejected', 'expired', 'cancelled'])

export function normalizeTypedPresentation(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const kind = String(value.kind || '').trim()
  const state = String(value.state || '').trim()
  if (!kind || !state) return null
  return {
    ...value,
    kind,
    state,
    rows: Array.isArray(value.rows)
      ? value.rows.filter((row) => row && typeof row === 'object' && !Array.isArray(row))
      : [],
    sources: Array.isArray(value.sources)
      ? value.sources.filter((source) => source && typeof source === 'object' && !Array.isArray(source))
      : [],
    diagnostics: value.diagnostics && typeof value.diagnostics === 'object' && !Array.isArray(value.diagnostics)
      ? value.diagnostics
      : {},
    invariants: value.invariants && typeof value.invariants === 'object' && !Array.isArray(value.invariants)
      ? value.invariants
      : {},
  }
}

export function hasTypedPresentation(value) {
  return Boolean(normalizeTypedPresentation(value))
}

function humanizeKey(key) {
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
    'job_id',
    'machine_id',
    'id',
    'status',
    'outcome',
    'priority',
    'previous_priority',
    'new_priority',
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

export function tablePresentationFromTypedPresentation(value) {
  const presentation = normalizeTypedPresentation(value)
  if (!presentation || !presentation.rows.length) return null
  const keys = orderedRowKeys(presentation.rows)
  if (!keys.length) return null
  return {
    render_hint: 'table',
    table: {
      columns: keys.map((key) => ({ key, label: humanizeKey(key) })),
      rows: presentation.rows,
      displayed_rows: presentation.rows.length,
      total_rows: presentation.rows.length,
    },
    analysis: {
      facts: diagnosticFactsForPresentation(presentation),
    },
    typed: {
      kind: presentation.kind,
      state: presentation.state,
      operation_id: presentation.operation_id || null,
      approval_id: presentation.approval_id || null,
    },
  }
}

export function diagnosticFactsForPresentation(value) {
  const presentation = normalizeTypedPresentation(value)
  if (!presentation) return []
  const diagnostics = presentation.diagnostics || {}
  const facts = []
  for (const key of ['reason', 'error', 'message', 'rejection_reason']) {
    const raw = diagnostics[key]
    if (raw == null || raw === '') continue
    facts.push(`${humanizeKey(key)}: ${raw}`)
  }
  return facts
}

export function summaryFromTypedPresentation(value) {
  const presentation = normalizeTypedPresentation(value)
  if (!presentation) return null
  const summary = String(presentation.summary || '').trim()
  if (summary) return summary

  const diagnostics = presentation.diagnostics || {}
  for (const key of ['message', 'error', 'detail', 'reason', 'rejection_reason']) {
    const raw = diagnostics[key]
    if (typeof raw === 'string' && raw.trim()) return raw.trim()
  }

  if (presentation.kind === 'approval_required' && presentation.state === 'pending') return 'Waiting for approval.'
  if (presentation.kind === 'mutation_result' && presentation.state === 'completed') return 'Requested changes completed.'
  if (presentation.kind === 'partial_failure' || presentation.state === 'failed') return 'Some requested work could not be completed.'
  if (presentation.kind === 'diagnostic') return 'The request could not be completed.'
  if (presentation.kind === 'cancelled' || presentation.state === 'cancelled') return 'Run cancelled by operator request.'
  if (presentation.kind === 'rejected' || presentation.state === 'rejected') return 'Approval rejected.'
  if (presentation.kind === 'expired' || presentation.state === 'expired') return 'Approval expired.'
  if (presentation.kind === 'knowledge_answer' || presentation.kind === 'answer') return 'Answer ready.'
  return null
}

export function typedPresentationIsAuthoritative(value) {
  const presentation = normalizeTypedPresentation(value)
  if (!presentation) return false
  if (presentation.kind === 'approval_required' && presentation.state === 'pending') return true
  return TERMINAL_STATES.has(presentation.state)
}

export function activityStepFromTypedPresentation(value, options = {}) {
  const presentation = normalizeTypedPresentation(value)
  if (!presentation) return null
  const timestamp = Number.isFinite(Number(options.timestamp)) ? Number(options.timestamp) : Date.now() / 1000
  const id = options.id || `typed_presentation_${presentation.kind}_${presentation.state}`
  const summary = summaryFromTypedPresentation(presentation)

  if (presentation.kind === 'approval_required' && presentation.state === 'pending') {
    return { id, timestamp, group: 'approval', label: 'Waiting for approval', detail: null, state: 'waiting' }
  }
  if (presentation.state === 'rejected' || presentation.kind === 'rejected') {
    return { id, timestamp, group: 'approval', label: 'Approval declined', detail: summary, state: 'error' }
  }
  if (presentation.state === 'expired' || presentation.kind === 'expired') {
    return { id, timestamp, group: 'approval', label: 'Approval expired', detail: summary, state: 'error' }
  }
  if (presentation.state === 'cancelled' || presentation.kind === 'cancelled') {
    return { id, timestamp, group: 'system', label: 'Run cancelled', detail: summary, state: 'complete' }
  }
  if (presentation.state === 'failed' || presentation.kind === 'partial_failure' || presentation.kind === 'diagnostic') {
    return { id, timestamp, group: 'system', label: 'Something needs attention', detail: summary, state: 'error' }
  }
  if (presentation.state === 'completed') {
    return { id, timestamp, group: 'response', label: 'Run complete', detail: 'All steps finished. See the thread below.', state: 'complete' }
  }
  return null
}
