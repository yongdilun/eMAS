export const ACTIVITY_STATES = ['running', 'success', 'retry', 'waiting', 'error', 'complete']

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
  const steps = Array.isArray(activitySteps) ? activitySteps : []
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
  if (hasActivity) return activityEnded
  return Boolean(turnEnded)
}

export function normalizeActivityStep(step) {
  if (!step || typeof step !== 'object') return null
  const id = String(step.id || '').trim()
  const label = String(step.label || '').trim()
  const state = ACTIVITY_STATES.includes(step.state) ? step.state : 'running'
  if (!id || !label) return null
  return {
    id,
    timestamp: Number.isFinite(Number(step.timestamp)) ? Number(step.timestamp) : Date.now() / 1000,
    group: String(step.group || 'system'),
    label,
    detail: step.detail == null ? null : String(step.detail),
    state,
  }
}

export function mergeActivityStep(steps, step) {
  const normalized = normalizeActivityStep(step)
  if (!normalized) return Array.isArray(steps) ? steps : []
  const existing = Array.isArray(steps) ? steps : []
  const without = existing.filter((item) => item.id !== normalized.id)
  return [...without, normalized].sort((a, b) => {
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
  return rows.filter((step) => {
    const label = String(step?.label || '').toLowerCase()
    const group = String(step?.group || '').toLowerCase()
    return !(step?.state === 'complete' && group === 'response') && label !== 'run complete'
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

function activityBaseForEvent(event) {
  const type = event?.event_type || event?.eventType
  const status = String(event?.status || '').toUpperCase()
  if (type === 'plan_created') return ['planning', 'Understanding your request', 'success']
  if (type === 'execution_started') return ['planning', 'Preparing the next step', 'running']
  if (type === 'tool_started') return ['research', 'Gathering information', 'running']
  if (type === 'tool_result') {
    return status === 'FAILED' || status === 'AMBIGUOUS'
      ? ['research', 'Could not complete that check', 'error']
      : ['research', 'Information checked', 'success']
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
  const type = event?.event_type || event?.eventType
  const domain = safeDomainLabel(event)
  if (type === 'plan_created') return 'Reviewing your request and recent context'
  if (type === 'execution_started') return 'Preparing the next safe action'
  if (type === 'tool_started') return `Checking ${domain}`
  if (type === 'tool_result') return label === 'Could not complete that check' ? 'A check could not be completed' : `Checked ${domain}`
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

/**
 * One logical operation (plan scope): pre-approval tools show as review/staging rows;
 * post-approval execution uses Applying / Updating / Verifying labels.
 */
function buildStepsFromEventsOperational(events) {
  const sorted = sortTimelineEvents(events)
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
  const push = (group, label, state, detail, tsSrc) => {
    const timestamp = Number.isFinite(tsSrc) ? tsSrc : Date.now() / 1000
    uid += 1
    const step = normalizeActivityStep({
      id: `op_activity_${uid}`,
      timestamp,
      group,
      label,
      detail: detail == null ? null : String(detail),
      state,
    })
    if (step) steps.push(step)
  }

  let seenUnderstanding = false
  let seenPreparingChanges = false
  let seenApplying = false

  for (let i = 0; i < sorted.length; i += 1) {
    const event = sorted[i]
    const t = getType(event)
    const ts = toEventTime(event) / 1000

    if (t === 'user_message') continue
    if (t === 'tool_started') continue

    if (t === 'plan_created') {
      if (!seenUnderstanding) {
        push('planning', 'Understanding your request', 'success', 'Reviewing your request and recent context', ts)
        seenUnderstanding = true
      }
      continue
    }

    if (t === 'replan_requested') {
      push('planning', 'Preparing changes', 'retry', 'Refining the response with updated information', ts)
      continue
    }

    if (t === 'execution_started') {
      const afterApproved = approvalApprovedIdx >= 0 && i > approvalApprovedIdx
      if (afterApproved) {
        if (!seenApplying) {
          push('research', 'Applying approved changes', 'running', 'Running approved tools', ts)
          seenApplying = true
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

      if (st === 'FAILED' || st === 'AMBIGUOUS') {
        const domain = safeDomainLabel(event)
        push('research', 'Could not complete that check', 'error', `A check could not be completed (${domain})`, ts)
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
      push('system', 'Something needs attention', 'error', String(event?.content || 'The request could not be completed'), ts)
      continue
    }

    if (t === 'session_completed') {
      push('response', 'Run complete', 'complete', 'All steps finished. See the thread below.', ts)
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
  const { mode = 'legacy', scopedEvents = null, sessionStatus = '' } = options
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
    const built = buildStepsFromEventsOperational(sourceEvents)
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
      || label === 'Could not complete that check'
      || label === 'Updating job records'
      || label === 'Verifying result'
      || label === 'Applying approved changes'
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

  // Suppress session_completed timeline events while the session is still active.
  // showing "Run complete" before the session is terminal is misleading.
  const suppressCompletion = hasPendingApproval || ACTIVE_SESSION_STATUSES.has(status)
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
    })
  } else {
    steps = buildActivityStepsFromTimeline(timeline, { mode: 'legacy', sessionStatus: status })
  }

  const now = Date.now() / 1000

  if (status === 'PLANNING') {
    steps = appendStep(steps, {
      id: `snapshot_activity_${steps.length + 1}`,
      timestamp: now,
      group: 'planning',
      label: 'Understanding your request',
      detail: 'Reviewing your request and recent context',
      state: 'running',
    })
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

  if (status === 'FAILED' || status === 'BLOCKED') {
    steps = appendStep(steps, {
      id: `snapshot_activity_${steps.length + 1}`,
      timestamp: now,
      group: 'system',
      label: 'Something needs attention',
      detail: 'The request could not be completed',
      state: 'error',
    })
  }

  if (status === 'COMPLETED') {
    steps = appendStep(steps, {
      id: `snapshot_activity_${steps.length + 1}`,
      timestamp: now,
      group: 'response',
      label: 'Run complete',
      detail: 'All steps finished. See the thread below.',
      state: 'complete',
    })
  }

  if (['COMPLETED', 'FAILED', 'BLOCKED'].includes(status)) {
    steps = injectExecutionSummaryFromPlanSteps(steps, planSteps, plan)
  }

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
