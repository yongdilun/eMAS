import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { classifyFactoryAgentError, normalizeFactoryAgentError } from '../../../../services/factoryAgentErrors'
import { FACTORY_AGENT_STATUS, factoryAgentApi } from '../../../../services/factoryAgentApi'
import { assembleFactoryAgentTurns, computeFactoryAgentTurnSummary } from '../turns/turnAssembler'
import { buildActivityStepsFromSnapshot, finalizeHistoricalActivityStates } from './activityTimelineUtils'
import { resolveApprovalTablePresentation } from './approvalInterruptDisplay.js'
import { formatFactoryAgentTime } from './factoryAgentDisplayTime.js'
import { useActivityStream } from './useActivityStream.js'
import { useFactoryAgentClientProgress } from './useFactoryAgentClientProgress.js'
import { useSessionEvents } from './useSessionEvents.js'

const DEFAULT_USER_ID = import.meta.env?.VITE_FACTORY_AGENT_USER_ID || 'frontend-operator'
const ACTIVITY_TIMELINE_ENABLED = !['0', 'false', 'off'].includes(
  String(import.meta.env?.VITE_FACTORY_AGENT_ACTIVITY_TIMELINE ?? 'true').trim().toLowerCase(),
)
const ACTIVE_SESSION_KEY = 'factory_agent_active_session_id'
const SESSION_COUNTER_KEY = 'factory_agent_session_counter'
const MESSAGE_MODE_KEY = 'factory_agent_message_mode'

const hasStorage = () => typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'

function nowTime() {
  return formatFactoryAgentTime(Date.now())
}

function formatTs(ts) {
  if (!ts) return nowTime()
  try {
    return formatFactoryAgentTime(ts)
  } catch {
    return nowTime()
  }
}

function nextSessionName() {
  if (!hasStorage()) return 'New chat'
  try {
    const current = Number(localStorage.getItem(SESSION_COUNTER_KEY) || '0')
    const next = Number.isFinite(current) ? current + 1 : 1
    localStorage.setItem(SESSION_COUNTER_KEY, String(next))
    return `Chat ${next}`
  } catch {
    return 'New chat'
  }
}

function normalizeTextKey(value) {
  return String(value || '').trim().toLowerCase()
}

function turnHasRealAssistantProgress(turn) {
  if (!turn) return false
  return Boolean(
    turn.terminal ||
    (Array.isArray(turn.thinking) && turn.thinking.length) ||
    (Array.isArray(turn.tools) && turn.tools.length) ||
    (Array.isArray(turn.status) && turn.status.length) ||
    (Array.isArray(turn.approvals) && turn.approvals.length) ||
    (Array.isArray(turn.confirmations) && turn.confirmations.length),
  )
}

function toSessionSummary(session) {
  if (!session?.session_id) return null
  return {
    session_id: session.session_id,
    name: session.name || 'New chat',
    status: session.status || FACTORY_AGENT_STATUS.IDLE,
    updated_at: session.updated_at || null,
  }
}

function toTimelineMessage(event) {
  return {
    id: event.event_id,
    role: event.role === 'user' ? 'user' : 'assistant',
    eventType: event.event_type,
    content: event.content,
    mode: event.mode || null,
    timestamp: formatTs(event.created_at),
    createdAt: event.created_at || null,
    stepId: event.step_id || null,
    approvalId: event.approval_id || null,
    toolName: event.tool_name || null,
    status: event.status || null,
    details: event.details || null,
  }
}

const EVENT_PRIORITY = {
  user_message: 0,
  plan_created: 1,
  execution_started: 2,
  tool_started: 3,
  approval_required: 3,
  tool_result: 4,
  approval_decided: 5,
  replan_requested: 6,
  session_blocked: 7,
  session_failed: 8,
  session_completed: 9,
}

export function useFactoryAgentChat() {
  const [session, setSession] = useState(null)
  const [plan, setPlan] = useState(null)
  const [steps, setSteps] = useState([])
  const [timeline, setTimeline] = useState([])
  const [activitySteps, setActivitySteps] = useState([])
  const [sessionList, setSessionList] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [isCancelling, setIsCancelling] = useState(false)
  const [error, setError] = useState(null)
  const [pendingApproval, setPendingApproval] = useState(null)
  const [approvalReason, setApprovalReason] = useState('')
  const [isDecidingApproval, setIsDecidingApproval] = useState(false)
  const [isPollingSession, setIsPollingSession] = useState(false)
  const [isRetryingConnection, setIsRetryingConnection] = useState(false)
  const [resumeHint, setResumeHint] = useState(null)
  const [lastSyncedAt, setLastSyncedAt] = useState(null)
  const [streamDiagnosticsBySource, setStreamDiagnosticsBySource] = useState({})
  const [optimisticMessages, setOptimisticMessages] = useState([])
  const [messageMode, setMessageMode] = useState(() => {
    if (!hasStorage()) return 'normal'
    return localStorage.getItem(MESSAGE_MODE_KEY) || 'normal'
  })

  const sessionPollTimerRef = useRef(null)
  /** Persisted table presentation keyed by approval_id (kept for timeline rendering after decide). */
  const bundleTableByApprovalIdRef = useRef(new Map())
  const lastSnapshotSessionIdRef = useRef(null)
  const {
    clientProgress,
    clearClientProgress,
    clearClientProgressTimers,
    startClientProgress,
  } = useFactoryAgentClientProgress({
    activityTimelineEnabled: ACTIVITY_TIMELINE_ENABLED,
    setActivitySteps,
  })

  const mergeSessionSummary = useCallback((summary) => {
    if (!summary?.session_id) return
    setSessionList((prev) => {
      const nextItem = toSessionSummary(summary)
      const without = prev.filter((item) => item.session_id !== nextItem.session_id)
      return [nextItem, ...without].sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))
    })
  }, [])

  const removeOptimisticMessage = useCallback((messageId) => {
    setOptimisticMessages((prev) => prev.filter((item) => item.id !== messageId))
  }, [])

  const appendOptimisticUserMessage = useCallback((content) => {
    const id = `optimistic-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    setOptimisticMessages((prev) => [
      ...prev,
      {
        id,
        role: 'user',
        eventType: 'user_message',
        content,
        timestamp: nowTime(),
        createdAt: new Date().toISOString(),
      },
    ])
    return id
  }, [])

  const applySnapshot = useCallback((snapshot, meta = {}) => {
    const requestedSessionId = meta?.requestedSessionId ?? null
    const nextSession = snapshot?.session || null
    const sidFromBody = nextSession?.session_id || null
    const sid = sidFromBody || requestedSessionId || null
    const normSid = (v) => (v == null ? '' : String(v).trim().toLowerCase())
    const prevSnapSid = lastSnapshotSessionIdRef.current
    // Prefer the GET /snapshot/{id} argument over body.session_id so COMPLETED -> IDLE
    // polls on the same chat are not misclassified as a session switch.
    const switchedSession =
      requestedSessionId != null && String(requestedSessionId).length > 0
        ? Boolean(normSid(prevSnapSid) && normSid(prevSnapSid) !== normSid(requestedSessionId))
        : Boolean(sid && prevSnapSid && normSid(sid) !== normSid(prevSnapSid))
    if (switchedSession) {
      bundleTableByApprovalIdRef.current.clear()
    }
    lastSnapshotSessionIdRef.current = sid

    setSession(nextSession)
    setPlan(snapshot?.plan || null)
    setSteps(Array.isArray(snapshot?.steps) ? snapshot.steps : [])
    const nextTimeline = Array.isArray(snapshot?.timeline) ? snapshot.timeline : []
    setTimeline(nextTimeline)

    if (ACTIVITY_TIMELINE_ENABLED) {
      setActivitySteps((prev) => {
        const clientOnly = (Array.isArray(prev) ? prev : []).filter((s) =>
          String(s?.id || '').startsWith('client_activity_'),
        )
        const withoutClient = (Array.isArray(prev) ? prev : []).filter(
          (s) => !String(s?.id || '').startsWith('client_activity_'),
        )
        const serverSteps = Array.isArray(snapshot?.activity_steps)
          ? snapshot.activity_steps
          : Array.isArray(snapshot?.activitySteps)
            ? snapshot.activitySteps
            : []

        const isStreamActive = [
          'PLANNING',
          'EXECUTING',
          'WAITING_APPROVAL',
          'WAITING_CONFIRMATION',
        ].includes(nextSession?.status)

        let result
        if (serverSteps.length) {
          if (isStreamActive) {
            // Union by id: polls can arrive before SSE has caught up, or SSE can be
            // ahead on some ids - only updating `withoutClient` in place drops rows
            // that exist only on the server (looks like "first and last" only).
            const byId = new Map()
            for (const s of withoutClient) {
              if (s?.id) byId.set(s.id, { ...s })
            }
            for (const s of serverSteps) {
              if (!s?.id) continue
              const existing = byId.get(s.id)
              byId.set(s.id, existing ? { ...existing, ...s } : { ...s })
            }
            const merged = Array.from(byId.values()).sort(
              (a, b) => (a.timestamp || 0) - (b.timestamp || 0),
            )
            result = [...clientOnly, ...merged].sort(
              (a, b) => (a.timestamp || 0) - (b.timestamp || 0),
            )
          } else {
            // Session no longer in an active stream: drop client placeholder rows so a
            // stale `client_activity_pending` "Reviewing results..." cannot sit after
            // server "Run complete" and block the assistant body gate.
            result = finalizeHistoricalActivityStates(serverSteps.map((s) => ({ ...s })))
          }
        } else {
          const built = buildActivityStepsFromSnapshot({
            session: nextSession,
            plan: snapshot?.plan || null,
            steps: Array.isArray(snapshot?.steps) ? snapshot.steps : [],
            timeline: nextTimeline,
            pending_approval: snapshot?.pending_approval || null,
          })
          if (built.length) {
            result = finalizeHistoricalActivityStates(built)
          } else if (switchedSession) {
            // New session snapshot: do not carry over activity rows from the previous session.
            result = clientOnly
          } else if (isStreamActive) {
            // IDLE and similar snapshots often omit activity_steps; built can still be empty
            // while the UI already showed rows during the run - keep them.
            result = [...clientOnly, ...withoutClient].sort(
              (a, b) => (a.timestamp || 0) - (b.timestamp || 0),
            )
          } else {
            result = finalizeHistoricalActivityStates(withoutClient)
          }
        }

        return result
      })
    }

    // Server is now the source of truth for pending_approval.
    // The snapshot loader self-heals stale approvals, so we trust it directly.
    const serverPending = snapshot?.pending_approval || null
    setPendingApproval(serverPending)

    // Server-derived resume hint replaces the isResumingAfterApproval client flag.
    setResumeHint(snapshot?.resume_hint || null)

    setLastSyncedAt(new Date().toISOString())
    if (nextSession?.session_id && hasStorage()) {
      localStorage.setItem(ACTIVE_SESSION_KEY, nextSession.session_id)
    }
    mergeSessionSummary(nextSession)
    return nextSession
  }, [mergeSessionSummary])

  useEffect(() => {
    if (hasStorage()) localStorage.setItem(MESSAGE_MODE_KEY, messageMode)
  }, [messageMode])

  const clearSnapshotState = useCallback(() => {
    setSession(null)
    setPlan(null)
    setSteps([])
    setTimeline([])
    setActivitySteps([])
    setPendingApproval(null)
    setResumeHint(null)
    bundleTableByApprovalIdRef.current.clear()
    lastSnapshotSessionIdRef.current = null
  }, [])

  const getStashedBundlePresentation = useCallback((approvalId) => {
    if (!approvalId) return null
    return bundleTableByApprovalIdRef.current.get(approvalId) ?? null
  }, [])

  const refreshSessionList = useCallback(async () => {
    const rows = await factoryAgentApi.listSessions({ user_id: DEFAULT_USER_ID })
    setSessionList((Array.isArray(rows) ? rows : []).map((row) => toSessionSummary(row)).filter(Boolean))
    return rows
  }, [])

  const refreshSnapshot = useCallback(async (sessionId) => {
    if (!sessionId) return null
    const snapshot = await factoryAgentApi.getSnapshot(sessionId)
    applySnapshot(snapshot, { requestedSessionId: sessionId })
    return snapshot
  }, [applySnapshot])

  const safelyRefreshSnapshot = useCallback(async (sessionId) => {
    try {
      return await refreshSnapshot(sessionId)
    } catch (err) {
      const kind = classifyFactoryAgentError(err)
      if (kind === 'not_found') {
        if (hasStorage()) localStorage.removeItem(ACTIVE_SESSION_KEY)
        clearSnapshotState()
      }
      throw err
    }
  }, [clearSnapshotState, refreshSnapshot])

  const applyStreamActivityStep = useCallback((incoming) => {
    if (!ACTIVITY_TIMELINE_ENABLED || !incoming?.id) return
    setActivitySteps((prev) => {
      const base = Array.isArray(prev) ? prev : []
      const clientOnly = base.filter((s) => String(s?.id || '').startsWith('client_activity_'))
      const withoutClient = base.filter((s) => !String(s?.id || '').startsWith('client_activity_'))
      const idx = withoutClient.findIndex((s) => s.id === incoming.id)
      const next = [...withoutClient]
      if (idx >= 0) next[idx] = { ...next[idx], ...incoming }
      else next.push(incoming)
      next.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))
      return [...clientOnly, ...next].sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))
    })
  }, [])

  const updateStreamDiagnostic = useCallback((diagnostic) => {
    if (!diagnostic?.source) return
    setStreamDiagnosticsBySource((prev) => {
      const next = {
        source: diagnostic.source,
        status: diagnostic.status || 'info',
        message: diagnostic.message || '',
        updatedAt: new Date().toISOString(),
      }
      const current = prev[diagnostic.source]
      if (current?.status === next.status && current?.message === next.message) return prev
      return { ...prev, [diagnostic.source]: next }
    })
  }, [])

  const streamDiagnostics = useMemo(() => (
    Object.values(streamDiagnosticsBySource)
      .filter((item) => item?.status && !['connected', 'idle'].includes(item.status))
      .sort((a, b) => String(a.source).localeCompare(String(b.source)))
  ), [streamDiagnosticsBySource])

  const activityStreamEnabled =
    ACTIVITY_TIMELINE_ENABLED &&
    Boolean(session?.session_id) &&
    (isSending ||
      [
        FACTORY_AGENT_STATUS.PLANNING,
        FACTORY_AGENT_STATUS.EXECUTING,
        FACTORY_AGENT_STATUS.WAITING_APPROVAL,
        FACTORY_AGENT_STATUS.WAITING_CONFIRMATION,
        FACTORY_AGENT_STATUS.BLOCKED,
      ].includes(session?.status))

  useActivityStream(session?.session_id || null, applyStreamActivityStep, {
    enabled: activityStreamEnabled,
    onDiagnostic: updateStreamDiagnostic,
  })

  const sessionEventsEnabled = Boolean(
    session?.session_id &&
    (isSending ||
      [
        FACTORY_AGENT_STATUS.PLANNING,
        FACTORY_AGENT_STATUS.EXECUTING,
        FACTORY_AGENT_STATUS.WAITING_APPROVAL,
        FACTORY_AGENT_STATUS.WAITING_CONFIRMATION,
        FACTORY_AGENT_STATUS.BLOCKED,
      ].includes(session?.status)),
  )

  const appendUserMessageAndRefresh = useCallback(async (sessionId, text, mode) => {
    await factoryAgentApi.addMessage(sessionId, { role: 'user', content: text, mode })
    await safelyRefreshSnapshot(sessionId)
  }, [safelyRefreshSnapshot])

  const clearSessionPoll = useCallback(() => {
    if (sessionPollTimerRef.current) {
      clearInterval(sessionPollTimerRef.current)
      sessionPollTimerRef.current = null
    }
    setIsPollingSession(false)
  }, [])

  const pollSnapshot = useCallback(async () => {
    if (!session?.session_id) return
    try {
      await safelyRefreshSnapshot(session.session_id)
    } catch (err) {
      setError(normalizeFactoryAgentError(err, 'Failed to refresh session'))
    }
  }, [safelyRefreshSnapshot, session?.session_id])

  // SSE-driven invalidation calls pollSnapshot directly; the interval poll is a
  // safety net / fallback. When SSE is healthy, intervals are longer.
  const sessionPollIntervalMs = useMemo(() => {
    if (!session?.status) return null
    if (
      [FACTORY_AGENT_STATUS.PLANNING, FACTORY_AGENT_STATUS.EXECUTING,
      FACTORY_AGENT_STATUS.WAITING_APPROVAL, FACTORY_AGENT_STATUS.WAITING_CONFIRMATION].includes(session.status)
    ) {
      return 3000
    }
    if (session.status === FACTORY_AGENT_STATUS.BLOCKED) return 6000
    return null
  }, [session?.status])

  useEffect(() => {
    clearSessionPoll()
    if (!sessionPollIntervalMs || !session?.session_id) return
    setIsPollingSession(true)
    sessionPollTimerRef.current = setInterval(pollSnapshot, sessionPollIntervalMs)
    return clearSessionPoll
  }, [clearSessionPoll, pollSnapshot, session?.session_id, session?.status, sessionPollIntervalMs])

  // SSE notification stream - triggers snapshot re-fetch on invalidation.
  // This replaces the tight 1.5 s poll with event-driven latency (~500 ms backend poll).
  useSessionEvents(
    session?.session_id || null,
    useCallback(() => {
      if (session?.session_id) pollSnapshot()
    }, [pollSnapshot, session?.session_id]),
    { enabled: sessionEventsEnabled, fallbackMs: 4000, onDiagnostic: updateStreamDiagnostic },
  )

  useEffect(() => clearClientProgressTimers, [clearClientProgressTimers])

  useEffect(() => {
    const bootstrap = async () => {
      setLoading(true)
      setError(null)
      try {
        await refreshSessionList()
        if (!hasStorage()) return
        const savedId = localStorage.getItem(ACTIVE_SESSION_KEY)
        if (!savedId) return
        await safelyRefreshSnapshot(savedId)
      } catch (err) {
        setError(normalizeFactoryAgentError(err, 'Could not restore active session'))
      } finally {
        setLoading(false)
      }
    }

    bootstrap()
  }, [refreshSessionList, safelyRefreshSnapshot])

  const retryConnection = useCallback(async () => {
    setIsRetryingConnection(true)
    setError(null)
    try {
      await refreshSessionList()
      const savedId = session?.session_id || (hasStorage() ? localStorage.getItem(ACTIVE_SESSION_KEY) : null)
      if (savedId) await safelyRefreshSnapshot(savedId)
      return true
    } catch (err) {
      setError(normalizeFactoryAgentError(err, 'Could not reconnect to Factory Agent'))
      return false
    } finally {
      setIsRetryingConnection(false)
    }
  }, [refreshSessionList, safelyRefreshSnapshot, session?.session_id])

  const startNewSession = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const created = await factoryAgentApi.createSession({
        user_id: DEFAULT_USER_ID,
        name: nextSessionName(),
      })
      mergeSessionSummary(created)
      await refreshSessionList()
      await safelyRefreshSnapshot(created.session_id)
      return created
    } catch (err) {
      setError(normalizeFactoryAgentError(err, 'Failed to create session'))
      return null
    } finally {
      setLoading(false)
    }
  }, [mergeSessionSummary, refreshSessionList, safelyRefreshSnapshot])

  const switchSession = useCallback(async (sessionId) => {
    if (!sessionId) return
    setLoading(true)
    setError(null)
    try {
      await safelyRefreshSnapshot(sessionId)
    } catch (err) {
      setError(normalizeFactoryAgentError(err, 'Could not switch to selected session'))
    } finally {
      setLoading(false)
    }
  }, [safelyRefreshSnapshot])

  const renameSession = useCallback(async (sessionId, name) => {
    const trimmed = (name || '').trim()
    if (!sessionId || !trimmed) return
    try {
      const updated = await factoryAgentApi.updateSession(sessionId, { name: trimmed })
      mergeSessionSummary(updated)
      if (session?.session_id === sessionId) {
        setSession((prev) => (prev ? { ...prev, name: updated.name } : prev))
      }
    } catch (err) {
      setError(normalizeFactoryAgentError(err, 'Failed to rename session'))
    }
  }, [mergeSessionSummary, session?.session_id])

  const executeWithRetry = useCallback(async (sessionId, options = {}) => {
    const preferBackground = options.background ?? true
    try {
      // Prefer background execution so the UI can stream progress via polling
      // (tool_started/tool_result events) instead of waiting for one long HTTP request.
      return await factoryAgentApi.execute(sessionId, { background: preferBackground })
    } catch (err) {
      if (err?.status === 409) {
        await safelyRefreshSnapshot(sessionId)
        return factoryAgentApi.execute(sessionId, { background: preferBackground })
      }
      // Queue may be disabled or full; fall back to foreground execute.
      if (err?.status === 429 || String(err?.message || '').toLowerCase().includes('queue')) {
        return factoryAgentApi.execute(sessionId, { background: false })
      }
      throw err
    }
  }, [safelyRefreshSnapshot])

  const runIntent = useCallback(async (sessionId, text, mode = 'normal') => {
    await factoryAgentApi.addMessage(sessionId, { role: 'user', content: text, mode })
    await safelyRefreshSnapshot(sessionId)
    const planResp = await factoryAgentApi.createPlan(sessionId)
    if (!(planResp?.status === 'COMPLETED')) {
      await executeWithRetry(sessionId, { background: mode !== 'plan' })
    }
    return safelyRefreshSnapshot(sessionId)
  }, [executeWithRetry, safelyRefreshSnapshot])

  const handleSend = useCallback(async (overrideText) => {
    const text = (overrideText ?? input).trim()
    if (!text || isSending || session?.status === FACTORY_AGENT_STATUS.PLANNING) return

    const optimisticId = appendOptimisticUserMessage(text)
    setInput('')
    setError(null)
    setIsSending(true)

    try {
      let current = session
      // Keep one session as the chat "thread" until the user explicitly starts a new one.
      if (!current) current = await startNewSession()
      if (!current) return
      startClientProgress(current.session_id, text)

      if ([FACTORY_AGENT_STATUS.IDLE, FACTORY_AGENT_STATUS.BLOCKED, FACTORY_AGENT_STATUS.FAILED, FACTORY_AGENT_STATUS.COMPLETED].includes(current.status)) {
        await runIntent(current.session_id, text, messageMode)
      } else if (current.status === FACTORY_AGENT_STATUS.WAITING_CONFIRMATION) {
        await appendUserMessageAndRefresh(current.session_id, text, messageMode)
      } else if (current.status === FACTORY_AGENT_STATUS.WAITING_APPROVAL) {
        await appendUserMessageAndRefresh(current.session_id, text, messageMode)
        const planResp = await factoryAgentApi.createPlan(current.session_id)
        if (!(planResp?.status === 'COMPLETED')) {
          await executeWithRetry(current.session_id, { background: messageMode !== 'plan' })
        }
        await safelyRefreshSnapshot(current.session_id)
      } else if (current.status === FACTORY_AGENT_STATUS.EXECUTING) {
        await appendUserMessageAndRefresh(current.session_id, text, messageMode)
      } else {
        await safelyRefreshSnapshot(current.session_id)
      }
      await refreshSessionList()
    } catch (err) {
      setError(normalizeFactoryAgentError(err, 'Failed to send request'))
    } finally {
      removeOptimisticMessage(optimisticId)
      clearClientProgress()
      setIsSending(false)
    }
  }, [
    appendOptimisticUserMessage,
    appendUserMessageAndRefresh,
    clearClientProgress,
    executeWithRetry,
    input,
    isSending,
    refreshSessionList,
    removeOptimisticMessage,
    messageMode,
    runIntent,
    safelyRefreshSnapshot,
    session,
    startClientProgress,
    startNewSession,
  ])

  const deleteSession = useCallback(async (sessionId) => {
    if (!sessionId) return
    setError(null)
    try {
      await factoryAgentApi.deleteSession(sessionId)
      if (session?.session_id === sessionId) {
        if (hasStorage()) localStorage.removeItem(ACTIVE_SESSION_KEY)
        clearSnapshotState()
      }
      await refreshSessionList()
      return true
    } catch (err) {
      setError(normalizeFactoryAgentError(err, 'Failed to delete session'))
      return false
    }
  }, [clearSnapshotState, refreshSessionList, session?.session_id])

  const handleCancel = useCallback(async () => {
    if (!session?.session_id) return
    setIsCancelling(true)
    setError(null)
    try {
      await factoryAgentApi.cancelSession(session.session_id)
      await safelyRefreshSnapshot(session.session_id)
      await refreshSessionList()
    } catch (err) {
      setError(normalizeFactoryAgentError(err, 'Failed to cancel session'))
    } finally {
      setIsCancelling(false)
    }
  }, [refreshSessionList, safelyRefreshSnapshot, session?.session_id])

  const decideApproval = useCallback(async (decision, argsOverride) => {
    if (!pendingApproval?.approval_id || isDecidingApproval) return
    setIsDecidingApproval(true)
    setError(null)

    const stashBundle = (appr, argsForBundle) => {
      const args = argsForBundle && typeof argsForBundle === 'object' ? argsForBundle : {}
      const frozen = resolveApprovalTablePresentation({
        event_type: 'approval_required',
        content: appr.risk_summary ? `Waiting for your approval: ${appr.risk_summary}` : '',
        risk_summary: appr.risk_summary,
        details: { args },
        args,
      })
      const aid = appr.approval_id
      if (frozen && aid) bundleTableByApprovalIdRef.current.set(aid, frozen)
    }

    try {
      if (decision === 'approve') {
        const payload = { decided_by: DEFAULT_USER_ID }
        if (argsOverride && typeof argsOverride === 'object') payload.args = argsOverride
        const snapshotApproval = pendingApproval
        const resolvedId = snapshotApproval.approval_id
        // Optimistically clear the pending approval card immediately so the UI
        // does not re-show the stale card while the next snapshot arrives.
        setPendingApproval(null)
        const mergedArgs =
          argsOverride && typeof argsOverride === 'object'
            ? { ...(snapshotApproval.args && typeof snapshotApproval.args === 'object' ? snapshotApproval.args : {}), ...argsOverride }
            : snapshotApproval.args || {}
        stashBundle(snapshotApproval, mergedArgs)
        await factoryAgentApi.approve(resolvedId, payload)
        await safelyRefreshSnapshot(session?.session_id)
      } else {
        const rejectId = pendingApproval.approval_id
        setPendingApproval(null)
        stashBundle(pendingApproval, pendingApproval.args || {})
        await factoryAgentApi.reject(rejectId, {
          decided_by: DEFAULT_USER_ID,
          rejection_reason: approvalReason?.trim() || undefined,
        })
        await safelyRefreshSnapshot(session?.session_id)
      }
      setApprovalReason('')
      if (session?.session_id) await refreshSessionList()
    } catch (err) {
      setError(normalizeFactoryAgentError(err, 'Failed to submit approval decision'))
    } finally {
      setIsDecidingApproval(false)
    }
  }, [approvalReason, isDecidingApproval, pendingApproval, refreshSessionList, safelyRefreshSnapshot, session?.session_id])

  const retryFromCurrent = useCallback(async () => {
    if (!session?.session_id) return
    setError(null)
    try {
      await executeWithRetry(session.session_id)
      await safelyRefreshSnapshot(session.session_id)
      await refreshSessionList()
    } catch (err) {
      setError(normalizeFactoryAgentError(err, 'Failed to retry current session'))
    }
  }, [executeWithRetry, refreshSessionList, safelyRefreshSnapshot, session?.session_id])

  const decideConfirmation = useCallback(async (option) => {
    if (!session?.session_id || !option?.field) return
    setError(null)
    setIsSending(true)
    try {
      await factoryAgentApi.confirm(session.session_id, {
        field: option.field,
        value: option.value,
      })
      await safelyRefreshSnapshot(session.session_id)
      const planResp = await factoryAgentApi.createPlan(session.session_id)
      if (!(planResp?.status === 'COMPLETED')) {
        await executeWithRetry(session.session_id, { background: messageMode !== 'plan' })
      }
      await safelyRefreshSnapshot(session.session_id)
      await refreshSessionList()
    } catch (err) {
      setError(normalizeFactoryAgentError(err, 'Failed to confirm filter'))
    } finally {
      setIsSending(false)
    }
  }, [executeWithRetry, messageMode, refreshSessionList, safelyRefreshSnapshot, session?.session_id])

  const messages = useMemo(() => {
    const serverMessages = timeline.map(toTimelineMessage)
    const serverUserContents = new Set(
      serverMessages
        .filter((m) => m.role === 'user')
        .map((m) => String(m.content || '').trim().toLowerCase())
        .filter(Boolean),
    )
    const filteredOptimistic = optimisticMessages.filter((m) => {
      if (m.role !== 'user') return true
      const key = String(m.content || '').trim().toLowerCase()
      return key ? !serverUserContents.has(key) : true
    })
    const merged = [...serverMessages, ...filteredOptimistic]
    merged.sort((a, b) => {
      const ts = String(a.createdAt || '').localeCompare(String(b.createdAt || ''))
      if (ts !== 0) return ts
      const prio = (EVENT_PRIORITY[a.eventType] ?? 99) - (EVENT_PRIORITY[b.eventType] ?? 99)
      if (prio !== 0) return prio
      return String(a.id || '').localeCompare(String(b.id || ''))
    })
    return merged
  }, [optimisticMessages, timeline])

  const turns = useMemo(() => {
    const assembled = assembleFactoryAgentTurns(Array.isArray(timeline) ? timeline : [])
    const mapped = assembled.map((t) => ({
      ...t,
      summary: computeFactoryAgentTurnSummary(t),
    }))
    if (
      ACTIVITY_TIMELINE_ENABLED ||
      !isSending ||
      !clientProgress ||
      clientProgress.sessionId !== session?.session_id ||
      !mapped.length
    ) {
      return mapped
    }

    const latestIndex = mapped.length - 1
    const latest = mapped[latestIndex]
    const latestUserKey = normalizeTextKey(latest?.user?.content)
    const progressUserKey = normalizeTextKey(clientProgress.text)
    if (latest?.user?.content && latestUserKey === progressUserKey && !turnHasRealAssistantProgress(latest)) {
      mapped[latestIndex] = {
        ...latest,
        summary: clientProgress.content,
        clientProgress,
      }
    }
    return mapped
  }, [clientProgress, isSending, session?.session_id, timeline])

  const activeSessionName = useMemo(() => {
    if (session?.name) return session.name
    return sessionList.find((item) => item.session_id === session?.session_id)?.name || null
  }, [session?.name, session?.session_id, sessionList])

  return {
    session,
    plan,
    steps,
    timeline,
    activitySteps,
    messages,
    turns,
    sessionList,
    activeSessionName,
    input,
    setInput,
    loading,
    isSending,
    isCancelling,
    isRetryingConnection,
    error,
    streamDiagnostics,
    pendingApproval,
    approvalReason,
    messageMode,
    setApprovalReason,
    setMessageMode,
    isDecidingApproval,
    isPollingSession,
    resumeHint,
    isResumingAfterApproval: !!(resumeHint?.applying_after_approval),
    getStashedBundlePresentation,
    lastSyncedAt,
    clientProgress,
    handleSend,
    handleCancel,
    retryConnection,
    decideApproval,
    decideConfirmation,
    startNewSession,
    switchSession,
    renameSession,
    deleteSession,
    refreshSession: safelyRefreshSnapshot,
    retryFromCurrent,
  }
}
