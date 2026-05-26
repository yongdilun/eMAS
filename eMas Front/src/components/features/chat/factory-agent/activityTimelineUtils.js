export const ACTIVITY_STATES = ['running', 'success', 'retry', 'waiting', 'error', 'complete']

import {
  activityStepFromTypedPresentation,
  normalizeTypedPresentation,
  typedPresentationIsAuthoritative,
} from './presentationContract.js'

/**
 * When the activity timeline is enabled for the latest turn, defer assistant
 * prose, tables, and stream-gated extras until the strip shows a terminal step,
 * or until the turn has a terminal event when no steps exist yet.
 */
export function assistantAnswerAllowed({
  activityTimelineEnabled,
  isLatestTurn,
  sessionStatus,
  activitySteps,
  turn,
}) {
  if (!activityTimelineEnabled || !isLatestTurn) return true

  const stu = String(sessionStatus || '').toUpperCase()
  const steps = truncateActivityAfterTerminal(Array.isArray(activitySteps) ? activitySteps : [])
  const hasActivity = steps.length > 0
  const last = hasActivity ? steps[steps.length - 1] : null
  const activityEnded = Boolean(last && (last.state === 'complete' || last.state === 'error'))
  const term = turn?.terminal?.event_type
  const turnEnded =
    term === 'session_completed' || term === 'session_failed' || term === 'session_blocked'

  const skipActivityRowTerminal =
    stu === 'WAITING_APPROVAL' ||
    stu === 'WAITING_CONFIRMATION' ||
    stu === 'FAILED' ||
    stu === 'BLOCKED'

  if (skipActivityRowTerminal) return true
  if (ACTIVE_SESSION_STATUSES.has(stu) && !turnEnded) return false
  if (hasActivity) return activityEnded
  return Boolean(turnEnded)
}

export function normalizeActivityStep(step) {
  if (!step || typeof step !== 'object') return null
  const id = String(step.id || '').trim()
  const label = String(step.label || '').trim()
  const state = ACTIVITY_STATES.includes(step.state) ? step.state : 'running'
  if (!id || !label) return null
  const replanAttempt = intValue(step._replanAttempt ?? step._replan_attempt ?? step.replanAttempt ?? step.replan_attempt)
  const normalized = {
    id,
    timestamp: Number.isFinite(Number(step.timestamp)) ? Number(step.timestamp) : Date.now() / 1000,
    group: String(step.group || 'system'),
    label,
    detail: step.detail == null ? null : String(step.detail),
    state,
  }
  if (replanAttempt != null) normalized._replanAttempt = replanAttempt
  return normalized
}

export function mergeActivityStep(steps, step) {
  const normalized = normalizeActivityStep(step)
  if (!normalized) return Array.isArray(steps) ? steps : []
  const existing = Array.isArray(steps) ? steps : []
  const without = existing.filter((item) => item.id !== normalized.id)
  return coalesceActivitySteps([...without, normalized].sort((a, b) => {
    const ts = Number(a.timestamp || 0) - Number(b.timestamp || 0)
    if (ts !== 0) return ts
    return String(a.id || '').localeCompare(String(b.id || ''))
  }))
}

export function truncateActivityAfterTerminal(steps = []) {
  const rows = Array.isArray(steps) ? steps.filter(Boolean) : []
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const state = rows[i]?.state
    if (state === 'complete' || state === 'error') return rows.slice(0, i + 1)
  }
  return rows
}

const ACTIVITY_STATE_MERGE_RANK = {
  running: 0,
  retry: 0,
  waiting: 0,
  success: 1,
  complete: 2,
  error: 2,
}

function activityMeaningKey(step) {
  if (!step) return ''
  return [
    String(step.group || '').trim().toLowerCase(),
    String(step.label || '').trim().toLowerCase(),
    String(step.detail || '').trim().toLowerCase(),
  ].join('::')
}

function preferActivityId(a, b) {
  const aid = String(a?.id || '')
  const bid = String(b?.id || '')
  const aGraph = aid.startsWith('graph:')
  const bGraph = bid.startsWith('graph:')
  if (aGraph && !bGraph) return aid
  if (bGraph && !aGraph) return bid
  const aClient = aid.startsWith('client_activity_')
  const bClient = bid.startsWith('client_activity_')
  if (aClient && !bClient) return bid
  if (bClient && !aClient) return aid
  return aid || bid
}

function mergeDuplicateActivityStep(existing, incoming) {
  const existingRank = ACTIVITY_STATE_MERGE_RANK[existing?.state] ?? 0
  const incomingRank = ACTIVITY_STATE_MERGE_RANK[incoming?.state] ?? 0
  const preferredState = incomingRank > existingRank ? incoming.state : existing.state
  return {
    ...existing,
    ...incoming,
    id: preferActivityId(existing, incoming),
    timestamp: Math.min(Number(existing?.timestamp || 0), Number(incoming?.timestamp || 0)) || incoming.timestamp || existing.timestamp,
    state: preferredState,
  }
}

export function coalesceActivitySteps(steps = []) {
  const rows = Array.isArray(steps) ? steps : []
  const out = []
  const indexByMeaning = new Map()
  for (const raw of rows) {
    const step = normalizeActivityStep(raw)
    if (!step) continue
    const key = activityMeaningKey(step)
    if (key && indexByMeaning.has(key)) {
      const index = indexByMeaning.get(key)
      out[index] = mergeDuplicateActivityStep(out[index], step)
      continue
    }
    indexByMeaning.set(key, out.length)
    out.push(step)
  }
  return out.sort((a, b) => {
    const ts = Number(a.timestamp || 0) - Number(b.timestamp || 0)
    if (ts !== 0) return ts
    return String(a.id || '').localeCompare(String(b.id || ''))
  })
}

/** Collapse only when the latest step is terminal — not if an older step was `complete` while the user is still waiting (e.g. approval). */
export function shouldAutoCollapseActivity(steps) {
  if (!Array.isArray(steps) || !steps.length) return false
  const last = steps[steps.length - 1]
  return last?.state === 'complete' || last?.state === 'error'
}

export function shouldShowActivityTimeline(steps) {
  return Array.isArray(steps) && steps.length > 0
}

export function stripPrematureTerminalActivitySteps(steps = [], sessionStatus = '') {
  const status = String(sessionStatus || '').toUpperCase()
  const rows = Array.isArray(steps) ? steps : []
  if (!ACTIVE_SESSION_STATUSES.has(status)) return rows
  const firstTerminal = rows.findIndex((step) => {
    const label = String(step?.label || '').toLowerCase()
    const group = String(step?.group || '').toLowerCase()
    return (step?.state === 'complete' && group === 'response') || label === 'run complete'
  })
  const candidateRows = firstTerminal >= 0 ? rows.slice(0, firstTerminal) : rows
  const withoutTerminal = candidateRows.filter((step) => {
    const label = String(step?.label || '').toLowerCase()
    const group = String(step?.group || '').toLowerCase()
    return !(step?.state === 'complete' && group === 'response') && label !== 'run complete'
  })
  if (status !== 'WAITING_APPROVAL') return withoutTerminal

  let latestWaitingApproval = -1
  for (let i = withoutTerminal.length - 1; i >= 0; i -= 1) {
    const step = withoutTerminal[i]
    const label = String(step?.label || '').toLowerCase()
    if (
      step?.group === 'approval'
      && (label === 'waiting for approval' || label === 'waiting for your approval')
      && step?.state === 'waiting'
    ) {
      latestWaitingApproval = i
      break
    }
  }
  if (latestWaitingApproval < 0) return withoutTerminal

  return withoutTerminal.slice(0, latestWaitingApproval + 1).map((step, index) => {
    if (index >= latestWaitingApproval || !FINALIZED_STATES.has(step?.state)) return step
    return { ...step, state: 'success' }
  })
}

const FINALIZED_STATES = new Set(['running', 'retry', 'waiting'])
const MERGEABLE_STATES = new Set(['running', 'success'])
const ACTIVE_SESSION_STATUSES = new Set(['PLANNING', 'EXECUTING', 'WAITING_APPROVAL', 'WAITING_CONFIRMATION'])

const SAFE_DOMAIN_LABELS = [
  ['approval', 'approval requests'],
  ['inventory', 'inventory records'],
  ['material', 'inventory records'],
  ['job', 'job records'],
  ['machine', 'machine records'],
  ['maintenance', 'maintenance records'],
  ['process', 'process records'],
  ['product', 'product records'],
  ['production', 'production records'],
  ['proposal', 'proposal records'],
  ['quality', 'quality records'],
  ['report', 'report records'],
  ['scheduling', 'scheduling records'],
  ['storage', 'storage records'],
]

function safeDomainLabel(event) {
  const text = [
    event?.tool_name,
    event?.toolName,
    event?.content,
    event?.details?.subject_type,
    event?.step_context?.tool_name,
  ].filter(Boolean).join(' ').toLowerCase().replace(/\{.*?\}/g, ' ').replace(/[_-]+/g, ' ')
  const match = SAFE_DOMAIN_LABELS.find(([token]) => text.includes(token))
  return match ? match[1] : 'relevant records'
}

function isRagActivityEvent(event) {
  const text = [
    event?.tool_name,
    event?.toolName,
    event?.details?.tool_name,
    event?.step_context?.tool_name,
    event?.stepContext?.toolName,
  ].filter(Boolean).join(' ').toLowerCase()
  const sources = event?.details?.sources
  return text.includes('rag') || text.includes('search_documents') || text.includes('knowledge') || (Array.isArray(sources) && sources.length > 0)
}

function activityBaseForEvent(event) {
  const typedStep = typedActivityStepForEvent(event)
  if (typedStep) return [typedStep.group, typedStep.label, typedStep.state]
  const type = event?.event_type || event?.eventType
  const status = String(event?.status || '').toUpperCase()
  if (type === 'plan_created') return ['planning', 'Understood request', 'success']
  if (type === 'execution_started') return ['planning', 'Preparing next action', 'running']
  if (type === 'tool_started') {
    if (isRagActivityEvent(event)) return ['research', 'Searching knowledge sources', 'running']
    return ['research', `Reading ${safeDomainLabel(event)}`, 'running']
  }
  if (type === 'tool_result') {
    if (status === 'FAILED' || status === 'AMBIGUOUS') return ['research', 'Could not complete that check', 'error']
    if (isRagActivityEvent(event)) return ['research', 'Building cited answer', 'success']
    return ['research', `Checked ${safeDomainLabel(event)}`, 'success']
  }
  if (type === 'approval_required') {
    if (status && status !== 'PENDING') return null
    return ['approval', 'Waiting for approval', 'waiting']
  }
  if (type === 'approval_decided') {
    if (status === 'APPROVED') return ['approval', 'Approval received', 'success']
    return ['approval', 'Approval updated', status === 'REJECTED' ? 'error' : 'success']
  }
  if (type === 'confirmation_required') return ['approval', 'Waiting for your confirmation', 'waiting']
  if (type === 'confirmation_decided') return ['approval', 'Confirmation received', 'success']
  if (type === 'replan_requested') return ['planning', 'Improving the response', 'retry']
  if (type === 'session_failed' || type === 'session_blocked') return ['system', 'Something needs attention', 'error']
  if (type === 'session_completed') return ['response', 'Run complete', 'complete']
  return null
}

function detailForEvent(event, label) {
  const typedStep = typedActivityStepForEvent(event)
  if (typedStep) return typedStep.detail
  const type = event?.event_type || event?.eventType
  const domain = safeDomainLabel(event)
  if (type === 'plan_created') return 'Reviewing your request and recent context'
  if (type === 'execution_started') return 'Preparing the next safe action'
  if (type === 'tool_started') return isRagActivityEvent(event) ? 'Searching retrieved documents' : `Checking ${domain}`
  if (type === 'tool_result') {
    if (label === 'Could not complete that check') return 'A check could not be completed'
    if (isRagActivityEvent(event)) return 'Checking citation support'
    return `Checked ${domain}`
  }
  if (type === 'approval_required') return null
  if (type === 'approval_decided') {
    if (String(event?.status || '').toUpperCase() === 'APPROVED') return 'Continuing with your approved changes'
    return 'Approval decision recorded'
  }
  if (type === 'confirmation_required') return 'Waiting for confirmation'
  if (type === 'confirmation_decided') return 'Confirmation received'
  if (type === 'replan_requested') return 'Refining the response with updated information'
  if (type === 'session_completed') return 'All steps finished. See the thread below.'
  if (type === 'session_failed' || type === 'session_blocked') return 'The request could not be completed'
  return null
}

function toEventTime(event) {
  const ts = Date.parse(event?.created_at || event?.createdAt || '')
  return Number.isFinite(ts) ? ts : 0
}

function getEventType(event) {
  return event?.event_type || event?.eventType || ''
}

function typedActivityStepForEvent(event) {
  const presentation = normalizeTypedPresentation(event?.presentation)
  if (!typedPresentationIsAuthoritative(presentation)) return null
  const type = getEventType(event)
  if (!['session_completed', 'session_failed', 'session_blocked', 'approval_required', 'approval_decided'].includes(type)) {
    return null
  }
  return activityStepFromTypedPresentation(presentation, {
    id: `typed:${event?.event_id || event?.id || type}`,
    timestamp: toEventTime(event) / 1000,
  })
}

export function resolveOperationIdFromSnapshot(snapshot = {}) {
  const session = snapshot.session || {}
  const plan = snapshot.plan || null
  const pending = snapshot.pending_approval || snapshot.pendingApproval || null
  const c = (v) => String(v || '').trim()
  return (
    c(session.operation_id || session.operationId)
    || c(plan?.plan_id || plan?.planId)
    || c(pending?.plan_id || pending?.planId)
  )
}

function eventPlanId(event) {
  const sc = event?.step_context || event?.stepContext || {}
  const d = event?.details || {}
  return String(event?.operation_id || event?.operationId || sc.plan_id || d.plan_id || '').trim()
}

function eventsMatchingOperation(timeline, operationId) {
  if (!operationId || !Array.isArray(timeline)) return []
  const oid = String(operationId).trim()
  const byOp = timeline.filter((e) => String(e?.operation_id || e?.operationId || '').trim() === oid)
  if (byOp.length) return byOp
  return timeline.filter((e) => eventPlanId(e) === oid)
}

function timelineHasApprovalActivity(timeline) {
  return (Array.isArray(timeline) ? timeline : []).some((e) => {
    const t = getEventType(e)
    return t === 'approval_required' || t === 'approval_decided'
  })
}

function scopedHasApprovalActivity(events) {
  return (Array.isArray(events) ? events : []).some((e) => {
    const t = getEventType(e)
    if (t === 'approval_required') {
      const st = String(e?.status || '').toUpperCase()
      return !st || st === 'PENDING'
    }
    return t === 'approval_decided'
  })
}

function toolNameForEvent(event) {
  return String(event?.tool_name || event?.toolName || event?.details?.tool_name || event?.step_context?.tool_name || '').trim()
}

function eventUsesWriteTool(event) {
  return /^(post|put|patch|delete)__/.test(toolNameForEvent(event).toLowerCase())
}

function eventDetails(event) {
  return event?.details && typeof event.details === 'object' ? event.details : {}
}

function eventArgs(event) {
  const details = eventDetails(event)
  if (details.args && typeof details.args === 'object') return details.args
  const result = details.result && typeof details.result === 'object' ? details.result : {}
  if (result.request_args && typeof result.request_args === 'object') return result.request_args
  return {}
}

function domainSubjectForEvent(event) {
  const label = safeDomainLabel(event)
  if (label.endsWith(' records')) return label.slice(0, -' records'.length)
  if (label.endsWith(' requests')) return label.slice(0, -' requests'.length)
  return ''
}

function readTargetLabel(event) {
  if (!event) return 'selected read'
  const subject = domainSubjectForEvent(event)
  const args = eventArgs(event)
  const rawFields = args.fields || args.requested_fields || args.requestedFields
  const fields = Array.isArray(rawFields)
    ? rawFields.map((item) => String(item).trim().toLowerCase()).filter(Boolean)
    : String(rawFields || '').split(',').map((item) => item.trim().toLowerCase()).filter(Boolean)
  if (subject && fields.includes('status')) return `${subject} status read`
  if (subject) return `${subject} read`
  return 'selected read'
}

function intValue(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.trunc(parsed) : null
}

function replanContextCandidates(context) {
  if (!context || typeof context !== 'object') return []
  const candidates = [context]
  for (const key of ['intent_contract', 'intentContract', 'planner_owned_agent_graph', 'plannerOwnedAgentGraph']) {
    if (context[key] && typeof context[key] === 'object') candidates.push(context[key])
  }
  return candidates
}

function replanSpineFromSnapshot(snapshot = {}) {
  const session = snapshot?.session || {}
  const context = session.replan_context || session.replanContext || {}
  for (const candidate of replanContextCandidates(context)) {
    const direct = candidate.replan_spine || candidate.replanSpine
    if (direct && typeof direct === 'object') return direct
    const responseContext = candidate.response_document_context || candidate.responseDocumentContext
    const diagnostics = responseContext && typeof responseContext === 'object' ? responseContext.diagnostics : null
    const nested = diagnostics && typeof diagnostics === 'object' ? diagnostics.replan_spine || diagnostics.replanSpine : null
    if (nested && typeof nested === 'object') return nested
  }
  return {}
}

function hasReplanStory(replanSpine) {
  return Boolean(
    replanSpine
    && typeof replanSpine === 'object'
    && (
      replanSpine.attempt_count
      || replanSpine.attemptCount
      || replanSpine.attempts
      || replanSpine.replan_limit_reached
      || replanSpine.replanLimitReached
    ),
  )
}

function totalAttemptCount(replanSpine) {
  const maxReplans = intValue(replanSpine?.max_attempts ?? replanSpine?.maxAttempts) || 0
  const attemptCount = intValue(replanSpine?.attempt_count ?? replanSpine?.attemptCount) || 0
  if (maxReplans > 0) return maxReplans + 1
  if (attemptCount > 0) return attemptCount + 1
  return 0
}

function attemptDetail(attempt, total, message) {
  if (attempt > 0 && total > 0) return `Attempt ${attempt} of ${total} - ${message}`
  return message
}

function resultErrorKind(event) {
  if (!event) return null
  const details = eventDetails(event)
  const result = details.result && typeof details.result === 'object' ? details.result : {}
  const error = result.error && typeof result.error === 'object' ? result.error : {}
  const errorType = String(error.error_type || error.errorType || result.error_type || result.errorType || details.error_type || details.errorType || '').trim().toLowerCase()
  const statusCode = intValue(result.status_code ?? result.statusCode ?? result.http_status ?? result.httpStatus ?? details.http_status ?? details.httpStatus)
  if (errorType === 'timeout' || statusCode === 408 || statusCode === 504) return 'timeout'
  if (['empty_data', 'insufficient_context', 'no_match', 'missing_evidence'].includes(errorType)) return 'incomplete'
  if (['http_error', 'http_500', 'network', 'tool_execution_exception'].includes(errorType)) return 'tool_error'
  if (statusCode != null && statusCode >= 400) return 'tool_error'
  return null
}

function attemptReasonKind({ replanSpine, replanAttempt, failedEvent }) {
  const eventKind = resultErrorKind(failedEvent)
  if (eventKind) return eventKind
  const attempts = Array.isArray(replanSpine?.attempts) ? replanSpine.attempts : []
  const attempt = attempts.find((item) => item && typeof item === 'object' && intValue(item.attempt) === replanAttempt)
  const reasons = Array.isArray(attempt?.missing_evidence_reasons)
    ? attempt.missing_evidence_reasons
    : Array.isArray(attempt?.missingEvidenceReasons)
      ? attempt.missingEvidenceReasons
      : Array.isArray(replanSpine?.missing_evidence_reasons)
        ? replanSpine.missing_evidence_reasons
        : Array.isArray(replanSpine?.missingEvidenceReasons)
          ? replanSpine.missingEvidenceReasons
          : []
  for (const reason of reasons) {
    const code = String(reason?.reason || '').trim().toLowerCase()
    if (['insufficient_context', 'missing_evidence', 'no_match'].includes(code)) return 'incomplete'
    if (code === 'tool_error') return 'tool_error'
  }
  return 'tool_error'
}

function retryReasonText(kind) {
  if (kind === 'timeout') return 'Previous read timed out'
  if (kind === 'incomplete') return 'Evidence was incomplete'
  if (kind === 'different_tool') return 'Trying a different tool'
  return 'Previous read failed'
}

function replanLabel(kind) {
  if (kind === 'timeout') return 'Replanning after timeout'
  if (kind === 'incomplete') return 'Replanning for more evidence'
  if (kind === 'different_tool') return 'Replanning with a different tool'
  return 'Replanning after failed read'
}

function hasPriorReplan(sorted, index) {
  for (let i = index - 1; i >= 0; i -= 1) {
    if (getEventType(sorted[i]) === 'replan_requested') return true
  }
  return false
}

function hasLaterReplan(sorted, index) {
  for (let i = index + 1; i < sorted.length; i += 1) {
    if (getEventType(sorted[i]) === 'replan_requested') return true
  }
  return false
}

/** Slice from the latest user_message so approval + pre/post plan ids stay in one strip. */
function timelineFromLatestUserMessage(timeline) {
  const sorted = sortTimelineEvents(timeline)
  let start = 0
  for (let i = sorted.length - 1; i >= 0; i -= 1) {
    if (getEventType(sorted[i]) === 'user_message') {
      start = i
      break
    }
  }
  return sorted.slice(start)
}

/** Widen scope when resume used a new plan id so strict plan match dropped approval rows. */
function operationScopedEventsForActivity(timeline, operationId) {
  const direct = eventsMatchingOperation(timeline, operationId)
  if (
    direct.length
    && timelineHasApprovalActivity(timeline)
    && !scopedHasApprovalActivity(direct)
  ) {
    return timelineFromLatestUserMessage(timeline)
  }
  return direct
}

function sortTimelineEvents(events) {
  return [...(events || [])].filter(Boolean).sort((a, b) => {
    const d = toEventTime(a) - toEventTime(b)
    if (d !== 0) return d
    return String(a.event_id || a.id || '').localeCompare(String(b.event_id || b.id || ''))
  })
}

function mergeRepeatedActivitySteps(steps = []) {
  const merged = []
  const indexBySignature = new Map()
  const countsBySignature = new Map()

  for (const step of steps) {
    const normalized = normalizeActivityStep(step)
    if (!normalized) continue
    const signature = `${normalized.group}::${normalized.label}::${normalized.detail || ''}::${normalized.state}`
    if (MERGEABLE_STATES.has(normalized.state) && indexBySignature.has(signature)) {
      const index = indexBySignature.get(signature)
      const count = (countsBySignature.get(signature) || 1) + 1
      countsBySignature.set(signature, count)
      merged[index] = {
        ...merged[index],
        timestamp: normalized.timestamp,
        detail: `${normalized.detail || normalized.label} (${count} updates)`,
      }
      continue
    }
    indexBySignature.set(signature, merged.length)
    countsBySignature.set(signature, 1)
    merged.push(normalized)
  }

  return merged
}

function looksLikeInterruptBundleDetail(text) {
  const s = String(text || '')
  return s.includes('Jobs affected:') || s.includes('Current vs requested priority') || s.includes('Current priority vs requested priority')
}

/** After the last terminal (complete/error), drop noisy replan detail leaked from server copy. */
function trimTailStepDetail(step) {
  if (!step || step.state !== 'success') return step
  const label = String(step.label || '')
  if (label !== 'Improving the response') return step
  const d = String(step.detail || '')
  if (!looksLikeInterruptBundleDetail(d) && d.length < 400) return step
  return {
    ...step,
    detail: 'Refining the response with updated information',
  }
}

/**
 * Use the **last** session terminal (complete/error), not the first.
 * Otherwise timeline events appended after `session_completed` (e.g. `replan_requested`)
 * stay `retry` and show as "Current" even though the run finished.
 */
export function finalizeHistoricalActivityStates(steps = []) {
  if (!Array.isArray(steps) || !steps.length) return steps

  let lastTerminal = -1
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const st = steps[i]?.state
    if (st === 'complete' || st === 'error') {
      lastTerminal = i
      break
    }
  }

  if (lastTerminal < 0) {
    const upperBound = steps.length - 1
    return steps.map((step, index) => {
      if (index >= upperBound || !FINALIZED_STATES.has(step?.state)) return step
      return { ...step, state: 'success' }
    })
  }

  const finalized = steps.map((step, index) => {
    const st = step?.state
    if (st === 'complete' || st === 'error') {
      if (index === lastTerminal) return step
      return step
    }
    if (!FINALIZED_STATES.has(st)) return step
    if (index < lastTerminal) return { ...step, state: 'success' }
    if (index > lastTerminal) return trimTailStepDetail({ ...step, state: 'success' })
    return { ...step, state: 'success' }
  })

  // Timeline can emit replan/tool noise after `session_completed`; those rows were
  // finalized as success above but must not remain as the *last* row or the
  // collapsed strip shows "Improving the response" instead of the terminal step.
  let terminalIdx = -1
  for (let i = finalized.length - 1; i >= 0; i -= 1) {
    const st = finalized[i]?.state
    if (st === 'complete' || st === 'error') {
      terminalIdx = i
      break
    }
  }
  if (terminalIdx >= 0 && terminalIdx < finalized.length - 1) {
    return finalized.slice(0, terminalIdx + 1)
  }
  return finalized
}

function capActivitySteps(steps = [], idPrefix = 'snapshot_activity') {
  const summarized = summarizeNoisyRetryAttempts(steps)
  if (summarized !== steps) return summarized.map((step, index) => ({ ...step, id: `${idPrefix}_${index + 1}` }))
  if (steps.length <= 12) return steps.map((step, index) => ({ ...step, id: `${idPrefix}_${index + 1}` }))
  const olderCount = steps.length - 11
  return [
    normalizeActivityStep({
      id: `${idPrefix}_grouped`,
      timestamp: steps[olderCount - 1]?.timestamp || Date.now() / 1000,
      group: 'system',
      label: 'Earlier activity',
      detail: `${olderCount} earlier updates grouped`,
      state: 'success',
    }),
    ...steps.slice(-11).map((step, index) => ({ ...step, id: `${idPrefix}_${index + 2}` })),
  ].filter(Boolean)
}

function attemptNumberFromStep(step) {
  return intValue(step?._replanAttempt ?? step?._replan_attempt ?? step?.replanAttempt ?? step?.replan_attempt)
}

function summarizeNoisyRetryAttempts(steps = []) {
  const rows = Array.isArray(steps) ? steps : []
  const attemptNumbers = Array.from(new Set(rows.map((step) => attemptNumberFromStep(step)).filter(Boolean))).sort((a, b) => a - b)
  if (attemptNumbers.length <= 3) return steps
  const firstAttempt = attemptNumbers[0]
  const latestAttempt = attemptNumbers[attemptNumbers.length - 1]
  const collapsedCount = attemptNumbers.filter((attempt) => attempt !== firstAttempt && attempt !== latestAttempt).length
  if (collapsedCount <= 0) return steps

  const out = []
  let insertedSummary = false
  let firstLatestIndex = rows.findIndex((step) => attemptNumberFromStep(step) === latestAttempt)
  if (firstLatestIndex < 0) firstLatestIndex = rows.length
  for (let index = 0; index < rows.length; index += 1) {
    const step = rows[index]
    const attempt = attemptNumberFromStep(step)
    if (attempt && attempt !== firstAttempt && attempt !== latestAttempt) {
      if (!insertedSummary && index < firstLatestIndex) {
        out.push(normalizeActivityStep({
          id: 'retry_attempts_collapsed',
          timestamp: Number(step.timestamp || 0),
          group: 'system',
          label: 'Earlier retry attempts',
          detail: `${collapsedCount} earlier attempts collapsed`,
          state: 'success',
        }))
        insertedSummary = true
      }
      continue
    }
    out.push(step)
  }
  return out.filter(Boolean)
}

/**
 * One logical operation (plan scope): pre-approval tools show as review/staging rows;
 * post-approval execution uses Applying / Updating / Verifying labels.
 */
function buildStepsFromEventsOperational(events, options = {}) {
  const sorted = sortTimelineEvents(events)
  const replanSpine = options.replanSpine && typeof options.replanSpine === 'object' ? options.replanSpine : {}
  const storyEnabled = hasReplanStory(replanSpine)
  const totalAttempts = totalAttemptCount(replanSpine)
  const getType = (e) => getEventType(e)
  const firstAprIdx = sorted.findIndex((e) => getType(e) === 'approval_required')
  const hasApproval = firstAprIdx >= 0

  let approvalApprovedIdx = -1
  for (let i = 0; i < sorted.length; i += 1) {
    if (getType(sorted[i]) !== 'approval_decided') continue
    const st = String(sorted[i]?.status || '').toUpperCase()
    if (st === 'APPROVED') {
      approvalApprovedIdx = i
      break
    }
  }

  const postApprovalDoneToolResults = []
  if (approvalApprovedIdx >= 0) {
    for (let j = approvalApprovedIdx + 1; j < sorted.length; j += 1) {
      if (getType(sorted[j]) !== 'tool_result') continue
      const st = String(sorted[j]?.status || '').toUpperCase()
      if (st === 'DONE') postApprovalDoneToolResults.push(sorted[j])
    }
  }

  const preApprovalDoneToolResults =
    hasApproval && firstAprIdx >= 0
      ? sorted.filter(
        (ev, j) =>
          j < firstAprIdx
          && getType(ev) === 'tool_result'
          && String(ev?.status || '').toUpperCase() === 'DONE',
      )
      : []

  const allDoneTools = sorted.filter(
    (e) => getType(e) === 'tool_result' && String(e?.status || '').toUpperCase() === 'DONE',
  )

  const steps = []
  let uid = 0
  const push = (group, label, state, detail, tsSrc, meta = {}) => {
    const timestamp = Number.isFinite(tsSrc) ? tsSrc : Date.now() / 1000
    uid += 1
    const step = normalizeActivityStep({
      id: `op_activity_${uid}`,
      timestamp,
      group,
      label,
      detail: detail == null ? null : String(detail),
      state,
      _replanAttempt: meta.replanAttempt,
    })
    if (step) steps.push(step)
  }

  let seenUnderstanding = false
  let seenPreparingChanges = false
  let seenApplying = false
  let seenInitialReadExecution = false
  let priorReplans = 0
  let lastFailedReadEvent = null

  for (let i = 0; i < sorted.length; i += 1) {
    const event = sorted[i]
    const t = getType(event)
    const ts = toEventTime(event) / 1000

    if (t === 'user_message') continue
    if (t === 'tool_started') continue

    const typedStep = typedActivityStepForEvent(event)
    if (typedStep) {
      push(typedStep.group, typedStep.label, typedStep.state, typedStep.detail, ts)
      continue
    }

    if (t === 'plan_created') {
      if (!seenUnderstanding) {
        push('planning', 'Understood request', 'success', 'Reviewing your request and recent context', ts)
        seenUnderstanding = true
      }
      continue
    }

    if (t === 'replan_requested') {
      if (storyEnabled && totalAttempts > 0) {
        const nextAttempt = priorReplans + 2
        const kind = attemptReasonKind({
          replanSpine,
          replanAttempt: Math.max(1, nextAttempt - 1),
          failedEvent: lastFailedReadEvent,
        })
        push('planning', replanLabel(kind), 'retry', attemptDetail(nextAttempt, totalAttempts, retryReasonText(kind)), ts, { replanAttempt: nextAttempt })
        priorReplans += 1
      } else {
        push('planning', 'Replanning', 'retry', 'Preparing another safe attempt', ts)
      }
      continue
    }

    if (t === 'execution_started') {
      const afterApproved = approvalApprovedIdx >= 0 && i > approvalApprovedIdx
      if (afterApproved) {
        if (!seenApplying) {
          push('research', 'Applying approved changes', 'running', 'Running approved tools', ts)
          seenApplying = true
        }
      } else if (!hasApproval) {
        if (hasPriorReplan(sorted, i)) {
          push(
            'research',
            storyEnabled ? `Retrying ${readTargetLabel(lastFailedReadEvent)}` : 'Retrying tool',
            'running',
            storyEnabled
              ? attemptDetail(priorReplans + 1, totalAttempts, 'Running the next selected read')
              : 'Running the next selected read',
            ts,
            { replanAttempt: storyEnabled ? priorReplans + 1 : null },
          )
        } else if (!seenInitialReadExecution) {
          push(
            'research',
            'Running selected tool',
            'running',
            storyEnabled ? attemptDetail(1, totalAttempts, 'Running the selected read') : 'Running the selected read',
            ts,
            { replanAttempt: storyEnabled ? 1 : null },
          )
          seenInitialReadExecution = true
        }
      } else if (!seenPreparingChanges) {
        push('planning', 'Preparing changes', 'running', 'Preparing the next safe action', ts)
        seenPreparingChanges = true
      }
      continue
    }

    if (t === 'approval_required') {
      const ars = String(event?.status || '').toUpperCase()
      if (ars && ars !== 'PENDING') continue
      push('approval', 'Waiting for approval', 'waiting', null, ts)
      continue
    }

    if (t === 'approval_decided') {
      const st = String(event?.status || '').toUpperCase()
      if (st === 'APPROVED') {
        push('approval', 'Approval received', 'success', 'Continuing with your approved changes', ts)
      } else if (st === 'REJECTED' || st === 'EXPIRED') {
        push('approval', 'Approval declined', 'error', String(event?.content || 'Request was not approved'), ts)
      } else {
        push('approval', 'Approval updated', 'success', 'Approval decision recorded', ts)
      }
      continue
    }

    if (t === 'confirmation_required') {
      push('approval', 'Waiting for your confirmation', 'waiting', 'Waiting for confirmation', ts)
      continue
    }
    if (t === 'confirmation_decided') {
      push('approval', 'Confirmation received', 'success', null, ts)
      continue
    }

    if (t === 'tool_result') {
      const st = String(event?.status || '').toUpperCase()
      const afterApproved = approvalApprovedIdx >= 0 && i > approvalApprovedIdx

      if (!hasApproval && !eventUsesWriteTool(event)) {
        const domain = safeDomainLabel(event)
        if (st === 'FAILED' || st === 'AMBIGUOUS') {
          const retryFollows = hasLaterReplan(sorted, i)
          const attempt = priorReplans + 1
          const kind = storyEnabled
            ? attemptReasonKind({ replanSpine, replanAttempt: Math.max(1, attempt), failedEvent: event })
            : null
          push(
            'response',
            'Checking evidence',
            retryFollows ? 'success' : 'error',
            storyEnabled
              ? attemptDetail(
                attempt,
                totalAttempts,
                retryFollows ? retryReasonText(kind) : 'Evidence could not be verified',
              )
              : retryFollows
                ? `Evidence from ${domain} needs another attempt`
                : `Evidence from ${domain} could not be verified`,
            ts,
            { replanAttempt: storyEnabled ? attempt : null },
          )
          lastFailedReadEvent = event
          continue
        }
        if (st === 'DONE') {
          const attempt = priorReplans + 1
          push(
            'response',
            storyEnabled && priorReplans > 0 ? 'Checking new evidence' : 'Checking evidence',
            'success',
            storyEnabled ? attemptDetail(attempt, totalAttempts, `Verified ${domain}`) : `Verified ${domain}`,
            ts,
            { replanAttempt: storyEnabled ? attempt : null },
          )
          continue
        }
      }

      if (st === 'FAILED' || st === 'AMBIGUOUS') {
        const domain = safeDomainLabel(event)
        push('research', 'Could not complete that check', 'error', `A check could not be completed (${domain})`, ts)
        if (!eventUsesWriteTool(event)) lastFailedReadEvent = event
        continue
      }
      if (st !== 'DONE') continue

      if (hasApproval && firstAprIdx >= 0 && i < firstAprIdx) {
        const idxPre = preApprovalDoneToolResults.indexOf(event)
        if (idxPre >= 0) {
          if (preApprovalDoneToolResults.length >= 2) {
            const isLastPre = idxPre === preApprovalDoneToolResults.length - 1
            if (isLastPre) {
              push('research', 'Verifying result', 'success', 'Validated staged changes before approval', ts)
            } else {
              push('research', 'Updating job records', 'success', `Reviewed ${safeDomainLabel(event)}`, ts)
            }
          } else {
            push('research', 'Updating job records', 'success', `Checked ${safeDomainLabel(event)}`, ts)
          }
        }
        continue
      }

      if (hasApproval && afterApproved) {
        const idxInPost = postApprovalDoneToolResults.indexOf(event)
        if (idxInPost >= 0) {
          if (postApprovalDoneToolResults.length >= 2) {
            const isLast = idxInPost === postApprovalDoneToolResults.length - 1
            if (isLast) {
              push('research', 'Verifying result', 'success', 'Validated the outcome', ts)
            } else {
              push('research', 'Updating job records', 'success', `Applied changes (${safeDomainLabel(event)})`, ts)
            }
          } else {
            push('research', 'Updating job records', 'success', `Checked ${safeDomainLabel(event)}`, ts)
          }
        }
        continue
      }

      if (!hasApproval) {
        const idxAll = allDoneTools.indexOf(event)
        if (idxAll >= 0) {
          if (allDoneTools.length >= 2) {
            const isLast = idxAll === allDoneTools.length - 1
            if (isLast) {
              push('research', 'Verifying result', 'success', 'Validated the outcome', ts)
            } else {
              push('research', 'Updating job records', 'success', `Checked ${safeDomainLabel(event)}`, ts)
            }
          } else {
            push('research', 'Updating job records', 'success', `Checked ${safeDomainLabel(event)}`, ts)
          }
        }
        continue
      }

      continue
    }

    if (t === 'session_failed' || t === 'session_blocked') {
      const attemptCount = intValue(replanSpine.attempt_count ?? replanSpine.attemptCount) || 0
      const attempt = Math.min(totalAttempts || priorReplans + 1, Math.max(priorReplans + 1, attemptCount + 1))
      push(
        'system',
        'Something needs attention',
        'error',
        storyEnabled && (replanSpine.replan_limit_reached || replanSpine.replanLimitReached)
          ? attemptDetail(attempt, totalAttempts, 'Evidence could not be verified after retries')
          : String(event?.content || 'The request could not be completed'),
        ts,
        { replanAttempt: storyEnabled ? attempt : null },
      )
      continue
    }

    if (t === 'session_completed') {
      const attemptCount = intValue(replanSpine.attempt_count ?? replanSpine.attemptCount) || 0
      const attempt = Math.min(totalAttempts || priorReplans + 1, Math.max(priorReplans + 1, attemptCount + 1))
      push(
        'response',
        'Run complete',
        'complete',
        storyEnabled && priorReplans > 0
          ? attemptDetail(attempt, totalAttempts, 'Completed with verified evidence')
          : 'All steps finished. See the thread below.',
        ts,
        { replanAttempt: storyEnabled && priorReplans > 0 ? attempt : null },
      )
      continue
    }
  }

  return steps
}

function latestTurnTimeline(timeline = []) {
  const events = Array.isArray(timeline) ? timeline.filter(Boolean) : []
  const userEvents = events.filter((event) => (event.event_type || event.eventType) === 'user_message')
  if (!userEvents.length) return events
  const latestUser = userEvents.reduce((latest, event) => (toEventTime(event) >= toEventTime(latest) ? event : latest), userEvents[0])
  const latestTurnId = latestUser.turn_id || latestUser.turnId || latestUser.event_id || latestUser.id || null
  const latestUserTime = toEventTime(latestUser)
  return events.filter((event) => {
    const type = event.event_type || event.eventType
    if (type === 'user_message') return event === latestUser
    const turnId = event.turn_id || event.turnId || null
    if (latestTurnId && turnId) return turnId === latestTurnId
    return toEventTime(event) >= latestUserTime
  })
}

function activityTimelineIsTerminalSession(sessionStatus) {
  const s = String(sessionStatus || '').toUpperCase()
  return s === 'COMPLETED' || s === 'FAILED' || s === 'BLOCKED'
}

export function buildActivityStepsFromTimeline(timeline = [], options = {}) {
  const { mode = 'legacy', scopedEvents = null, sessionStatus = '', replanSpine = {} } = options
  let sourceEvents
  if (scopedEvents != null && scopedEvents.length) {
    sourceEvents = sortTimelineEvents(scopedEvents)
  } else if (activityTimelineIsTerminalSession(sessionStatus)) {
    // Read-only review: show the whole session, not only events tied to the latest user turn.
    sourceEvents = sortTimelineEvents(timeline)
  } else {
    sourceEvents = latestTurnTimeline(timeline)
  }
  if (mode === 'operational' && sourceEvents.length) {
    const built = buildStepsFromEventsOperational(sourceEvents, { replanSpine })
    const steps = finalizeHistoricalActivityStates(mergeRepeatedActivitySteps(built))
    return capActivitySteps(steps)
  }
  let steps = []
  for (const event of sourceEvents) {
    const base = activityBaseForEvent(event)
    if (!base) continue
    const [group, label, state] = base
    const detail = detailForEvent(event, label)
    const timestamp = Date.parse(event?.created_at || event?.createdAt || '')
    const step = normalizeActivityStep({
      id: `snapshot_activity_${steps.length + 1}`,
      timestamp: Number.isFinite(timestamp) ? timestamp / 1000 : Date.now() / 1000,
      group,
      label,
      detail,
      state,
    })
    if (step) steps.push(step)
  }
  steps = finalizeHistoricalActivityStates(mergeRepeatedActivitySteps(steps))
  return capActivitySteps(steps)
}

function appendStep(steps, step) {
  const normalized = normalizeActivityStep(step)
  if (!normalized) return steps
  const duplicate = steps.some((item) => item.label === normalized.label && item.state === normalized.state)
  return duplicate ? steps : [...steps, normalized]
}

function currentDomainFromSteps(steps = []) {
  const row = Array.isArray(steps)
    ? steps.find((step) => String(step?.status || '').toUpperCase() === 'IN_PROGRESS') || steps[0]
    : null
  return safeDomainLabel(row || {})
}

function filterPlanStepsForActivePlan(planSteps, plan) {
  const rows = Array.isArray(planSteps) ? planSteps : []
  let pid = plan?.plan_id || plan?.planId
  if (!pid && rows.length) {
    const firstPid = rows[0]?.plan_id || rows[0]?.planId
    if (firstPid && rows.every((r) => (r.plan_id || r.planId) === firstPid)) pid = firstPid
  }
  if (!pid) return []
  return rows.filter((r) => (r.plan_id || r.planId) === pid)
}

function timelineHasExecutionActivity(steps) {
  return (Array.isArray(steps) ? steps : []).some((s) => {
    if (s?.group !== 'research') return false
    const label = String(s?.label || '')
    return (
      label === 'Information checked'
      || label === 'Gathering information'
      || label === 'Running selected tool'
      || label === 'Retrying tool'
      || label === 'Checking evidence'
      || label === 'Could not complete that check'
      || label === 'Updating job records'
      || label === 'Verifying result'
      || label === 'Applying approved changes'
      || label === 'Searching knowledge sources'
      || label === 'Building cited answer'
      || label.startsWith('Reading ')
      || label.startsWith('Checked ')
    )
  })
}

function findLastTerminalStepIndex(steps) {
  if (!Array.isArray(steps) || !steps.length) return -1
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const st = steps[i]?.state
    if (st === 'complete' || st === 'error') return i
  }
  return -1
}

/**
 * When the server timeline omits tool rows (LangGraph / projection gaps) but plan steps
 * show finished work, add one consolidated execution row so the strip is not
 * only "Understanding" → "Run complete".
 */
function injectExecutionSummaryFromPlanSteps(steps, planSteps, plan) {
  const scoped = filterPlanStepsForActivePlan(planSteps, plan)
  if (!scoped.length) return steps
  if (timelineHasExecutionActivity(steps)) return steps

  const terminalIdx = findLastTerminalStepIndex(steps)
  if (terminalIdx < 0) return steps

  const finished = scoped.filter((s) => {
    const st = String(s?.status || '').toUpperCase()
    return st === 'DONE' || st === 'FAILED' || st === 'AMBIGUOUS'
  })
  if (!finished.length) return steps

  const domain = currentDomainFromSteps(scoped)
  const anyFail = finished.some((s) => ['FAILED', 'AMBIGUOUS'].includes(String(s?.status || '').toUpperCase()))
  const baseTs = Number(steps[terminalIdx]?.timestamp) || Date.now() / 1000
  const inserted = normalizeActivityStep({
    id: 'snapshot_activity_plan_execution_summary',
    timestamp: baseTs - 0.001,
    group: 'research',
    label: anyFail ? 'Could not complete that check' : 'Updating job records',
    detail: anyFail
      ? `Checked ${domain}; some steps did not complete`
      : `Checked ${domain} (${finished.length} update${finished.length === 1 ? '' : 's'})`,
    state: anyFail ? 'error' : 'success',
  })
  if (!inserted) return steps
  const merged = [...steps.slice(0, terminalIdx), inserted, ...steps.slice(terminalIdx)]
  return finalizeHistoricalActivityStates(mergeRepeatedActivitySteps(merged))
}

export function buildActivityStepsFromSnapshot(snapshot = {}) {
  const session = snapshot?.session || {}
  const plan = snapshot?.plan || null
  const rawTimeline = Array.isArray(snapshot?.timeline) ? snapshot.timeline : []
  const planSteps = Array.isArray(snapshot?.steps) ? snapshot.steps : []
  const status = String(session?.status || '').toUpperCase()
  const hasPendingApproval = Boolean(snapshot?.pending_approval)
  const snapshotPresentation = normalizeTypedPresentation(snapshot?.presentation)
  const typedAuthoritative = typedPresentationIsAuthoritative(snapshotPresentation)
  const typedIsNonCompletedTerminal = Boolean(typedAuthoritative && snapshotPresentation?.state !== 'completed')
  const replanSpine = replanSpineFromSnapshot(snapshot)

  // Suppress session_completed timeline events while the session is still active.
  // showing "Run complete" before the session is terminal is misleading.
  const suppressCompletion = hasPendingApproval || ACTIVE_SESSION_STATUSES.has(status) || typedIsNonCompletedTerminal
  const timeline = suppressCompletion
    ? rawTimeline.filter((e) => (e?.event_type || e?.eventType) !== 'session_completed')
    : rawTimeline

  const operationId = resolveOperationIdFromSnapshot(snapshot)
  const scoped = operationId ? operationScopedEventsForActivity(timeline, operationId) : []
  let steps = []
  if (operationId && scoped.length) {
    steps = buildActivityStepsFromTimeline(timeline, {
      mode: 'operational',
      scopedEvents: scoped,
      sessionStatus: status,
      replanSpine,
    })
  } else {
    steps = buildActivityStepsFromTimeline(timeline, { mode: 'legacy', sessionStatus: status })
  }

  const now = Date.now() / 1000

  if (status === 'PLANNING') {
    if (!steps.length) {
      steps = appendStep(steps, {
        id: `snapshot_activity_${steps.length + 1}`,
        timestamp: now,
        group: 'planning',
        label: 'Understanding your request',
        detail: 'Reviewing your request and recent context',
        state: 'running',
      })
    }
  }

  if (status === 'EXECUTING') {
    const domain = currentDomainFromSteps(planSteps)
    const hasApprovedResume = timeline.some(
      (e) => getEventType(e) === 'approval_decided' && String(e?.status || '').toUpperCase() === 'APPROVED',
    )
    steps = appendStep(steps, {
      id: `snapshot_activity_${steps.length + 1}`,
      timestamp: now,
      group: 'research',
      label: hasApprovedResume ? 'Applying approved changes' : 'Gathering information',
      detail: hasApprovedResume ? 'Running approved tools' : `Checking ${domain}`,
      state: 'running',
    })
  }

  if (status === 'WAITING_APPROVAL') {
    const hasApprovalWaiting = steps.some(
      (s) => s?.group === 'approval' && s?.label === 'Waiting for approval' && s?.state === 'waiting',
    )
    if (!hasApprovalWaiting) {
      steps = appendStep(steps, {
        id: `snapshot_activity_${steps.length + 1}`,
        timestamp: now,
        group: 'approval',
        label: 'Waiting for approval',
        detail: null,
        state: 'waiting',
      })
    }
  }

  if (status === 'WAITING_CONFIRMATION') {
    steps = appendStep(steps, {
      id: `snapshot_activity_${steps.length + 1}`,
      timestamp: now,
      group: 'approval',
      label: 'Waiting for your confirmation',
      detail: 'Waiting for confirmation',
      state: 'waiting',
    })
  }

  if ((status === 'FAILED' || status === 'BLOCKED') && !typedIsNonCompletedTerminal) {
    steps = appendStep(steps, {
      id: `snapshot_activity_${steps.length + 1}`,
      timestamp: now,
      group: 'system',
      label: 'Something needs attention',
      detail: 'The request could not be completed',
      state: 'error',
    })
  }

  if (status === 'COMPLETED' && !typedIsNonCompletedTerminal) {
    steps = appendStep(steps, {
      id: `snapshot_activity_${steps.length + 1}`,
      timestamp: now,
      group: 'response',
      label: 'Run complete',
      detail: 'All steps finished. See the thread below.',
      state: 'complete',
    })
  }

  if (typedIsNonCompletedTerminal) {
    const typedStep = activityStepFromTypedPresentation(snapshotPresentation, {
      id: `snapshot_activity_typed_${snapshotPresentation.kind}_${snapshotPresentation.state}`,
      timestamp: now,
    })
    if (typedStep) {
      steps = steps.filter((step) => {
        const label = String(step?.label || '')
        return label !== 'Run complete' && label !== 'Improving the response'
      })
      steps = appendStep(steps, typedStep)
    }
  }

  if (['COMPLETED', 'FAILED', 'BLOCKED'].includes(status) && !typedIsNonCompletedTerminal) {
    steps = injectExecutionSummaryFromPlanSteps(steps, planSteps, plan)
  }

  steps = stripPrematureTerminalActivitySteps(steps, status)
  return capActivitySteps(finalizeHistoricalActivityStates(mergeRepeatedActivitySteps(steps)))
}

export function friendlySessionStatus(status, isSending = false) {
  if (isSending) return 'Working'
  if (status === 'PLANNING') return 'Understanding'
  if (status === 'EXECUTING') return 'Checking'
  if (status === 'WAITING_APPROVAL') return 'Waiting for approval'
  if (status === 'WAITING_CONFIRMATION') return 'Waiting for confirmation'
  if (status === 'BLOCKED') return 'Needs attention'
  if (status === 'FAILED') return 'Needs attention'
  if (status === 'COMPLETED') return 'Complete'
  return 'Ready'
}
