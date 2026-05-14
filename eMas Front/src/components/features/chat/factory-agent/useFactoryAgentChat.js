import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { classifyFactoryAgentError, normalizeFactoryAgentError } from '../../../../services/factoryAgentErrors'
import { FACTORY_AGENT_STATUS, factoryAgentApi } from '../../../../services/factoryAgentApi'
import { assembleFactoryAgentTurns, computeFactoryAgentTurnSummary } from '../turns/turnAssembler'
import { buildActivityStepsFromSnapshot, finalizeHistoricalActivityStates } from './activityTimelineUtils'
import { resolveApprovalTablePresentation } from './approvalInterruptDisplay.js'

const DEFAULT_USER_ID = import.meta.env?.VITE_FACTORY_AGENT_USER_ID || 'frontend-operator'
const ACTIVITY_TIMELINE_ENABLED = !['0', 'false', 'off'].includes(
  String(import.meta.env?.VITE_FACTORY_AGENT_ACTIVITY_TIMELINE ?? 'true').trim().toLowerCase(),
)
const ACTIVE_SESSION_KEY = 'factory_agent_active_session_id'
const SESSION_COUNTER_KEY = 'factory_agent_session_counter'
const MESSAGE_MODE_KEY = 'factory_agent_message_mode'
const CLIENT_PROGRESS_STAGES = [
  { delayMs: 0, stage: 'intent' },
  { delayMs: 900, stage: 'planning' },
  { delayMs: 2200, stage: 'tool' },
  { delayMs: 6500, stage: 'answer' },
  { delayMs: 12000, stage: 'long' },
]

const hasStorage = () => typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'

function nowTime() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function formatTs(ts) {
  if (!ts) return nowTime()
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
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
  const [isResumingAfterApproval, setIsResumingAfterApproval] = useState(false)
  const [lastSyncedAt, setLastSyncedAt] = useState(null)
  const [optimisticMessages, setOptimisticMessages] = useState([])
  const [clientProgress, setClientProgress] = useState(null)
  const [messageMode, setMessageMode] = useState(() => {
    if (!hasStorage()) return 'normal'
    return localStorage.getItem(MESSAGE_MODE_KEY) || 'normal'
  })

  const sessionPollTimerRef = useRef(null)
  const clientProgressTimersRef = useRef([])
  /** Persisted table presentation keyed by approval_id after approve (timeline may omit args). */
  const bundleTableByApprovalIdRef = useRef(new Map())
  /** Suppress server stale `pending_approval` until snapshot clears it (same approval_id). */
  const dismissedPendingApprovalIdsRef = useRef(new Set())
  const lastSnapshotSessionIdRef = useRef(null)

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

  const clearClientProgressTimers = useCallback(() => {
    for (const timer of clientProgressTimersRef.current) {
      clearTimeout(timer)
    }
    clientProgressTimersRef.current = []
  }, [])

  const clearClientProgress = useCallback(() => {
    clearClientProgressTimers()
    setClientProgress(null)
  }, [clearClientProgressTimers])

  const startClientProgress = useCallback((sessionId, text) => {
    if (!sessionId) return
    clearClientProgressTimers()
    if (ACTIVITY_TIMELINE_ENABLED) {
      setClientProgress(null)
      setActivitySteps([{
        id: 'client_activity_pending',
        timestamp: Date.now() / 1000,
        group: 'planning',
        label: 'Working on your request',
        detail: 'This updates as the session progresses',
        state: 'running',
      }])
      return
    }
    const startedAt = new Date().toISOString()
    const requestKey = `${sessionId}:${Date.now()}`

    const setStage = (stage) => {
      setClientProgress({
        requestKey,
        sessionId,
        text,
        content: stage === 'intent'
          ? 'Understanding...'
          : stage === 'planning'
          ? 'Understanding your request...'
          : stage === 'tool'
          ? 'Checking information...'
          : stage === 'answer'
          ? 'Finalizing answer...'
          : 'Reviewing results...',
        stage,
        startedAt,
      })
    }

    for (const item of CLIENT_PROGRESS_STAGES) {
      const timer = setTimeout(() => setStage(item.stage), item.delayMs)
      clientProgressTimersRef.current.push(timer)
    }
  }, [clearClientProgressTimers])

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

  const applySnapshot = useCallback((snapshot) => {
    const nextSession = snapshot?.session || null
    const sid = nextSession?.session_id || null
    if (sid && lastSnapshotSessionIdRef.current && sid !== lastSnapshotSessionIdRef.current) {
      dismissedPendingApprovalIdsRef.current.clear()
      setIsResumingAfterApproval(false)
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
        const built = buildActivityStepsFromSnapshot({
          session: nextSession,
          plan: snapshot?.plan || null,
          steps: Array.isArray(snapshot?.steps) ? snapshot.steps : [],
          timeline: nextTimeline,
          pending_approval: snapshot?.pending_approval || null,
        })
        if (built.length) return finalizeHistoricalActivityStates(built)
        return clientOnly
      })
    }
    if (nextSession?.status !== FACTORY_AGENT_STATUS.WAITING_APPROVAL) {
      setIsResumingAfterApproval(false)
    }
    const serverPending = snapshot?.pending_approval || null
    const spId = serverPending?.approval_id || null
    const waitingApproval = nextSession?.status === FACTORY_AGENT_STATUS.WAITING_APPROVAL
    if (!spId) {
      dismissedPendingApprovalIdsRef.current.clear()
      setPendingApproval(null)
    } else if (!waitingApproval || dismissedPendingApprovalIdsRef.current.has(spId)) {
      setPendingApproval(null)
    } else {
      setPendingApproval(serverPending)
    }
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
    bundleTableByApprovalIdRef.current.clear()
    dismissedPendingApprovalIdsRef.current.clear()
    lastSnapshotSessionIdRef.current = null
    setIsResumingAfterApproval(false)
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
    applySnapshot(snapshot)
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

  const sessionPollIntervalMs = useMemo(() => {
    if (!session?.status) return null
    if ([FACTORY_AGENT_STATUS.PLANNING, FACTORY_AGENT_STATUS.EXECUTING, FACTORY_AGENT_STATUS.WAITING_APPROVAL, FACTORY_AGENT_STATUS.WAITING_CONFIRMATION].includes(session.status)) {
      return 1500
    }
    if (session.status === FACTORY_AGENT_STATUS.BLOCKED) return 4000
    return null
  }, [session?.status])

  useEffect(() => {
    clearSessionPoll()
    if (!sessionPollIntervalMs || !session?.session_id) return
    setIsPollingSession(true)
    sessionPollTimerRef.current = setInterval(pollSnapshot, sessionPollIntervalMs)
    return clearSessionPoll
  }, [clearSessionPoll, pollSnapshot, session?.session_id, session?.status, sessionPollIntervalMs])

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
        await factoryAgentApi.approve(resolvedId, payload)
        setIsResumingAfterApproval(true)
        dismissedPendingApprovalIdsRef.current.add(resolvedId)
        const mergedArgs =
          argsOverride && typeof argsOverride === 'object'
            ? { ...(snapshotApproval.args && typeof snapshotApproval.args === 'object' ? snapshotApproval.args : {}), ...argsOverride }
            : snapshotApproval.args || {}
        stashBundle(snapshotApproval, mergedArgs)
        setPendingApproval(null)
      } else {
        const rejectId = pendingApproval.approval_id
        await factoryAgentApi.reject(rejectId, {
          decided_by: DEFAULT_USER_ID,
          rejection_reason: approvalReason?.trim() || undefined,
        })
        dismissedPendingApprovalIdsRef.current.add(rejectId)
        setIsResumingAfterApproval(false)
        stashBundle(pendingApproval, pendingApproval.args || {})
        setPendingApproval(null)
      }
      setApprovalReason('')
      if (session?.session_id) {
        if (decision !== 'approve') await safelyRefreshSnapshot(session.session_id)
        await refreshSessionList()
      }
    } catch (err) {
      setError(normalizeFactoryAgentError(err, 'Failed to submit approval decision'))
      setIsResumingAfterApproval(false)
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
    error,
    pendingApproval,
    approvalReason,
    messageMode,
    setApprovalReason,
    setMessageMode,
    isDecidingApproval,
    isPollingSession,
    isResumingAfterApproval,
    getStashedBundlePresentation,
    lastSyncedAt,
    clientProgress,
    handleSend,
    handleCancel,
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
