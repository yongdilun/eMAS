import { useCallback, useRef, useState } from 'react'

const CLIENT_PROGRESS_STAGES = [
  { delayMs: 0, stage: 'intent' },
  { delayMs: 900, stage: 'planning' },
  { delayMs: 2200, stage: 'tool' },
  { delayMs: 6500, stage: 'answer' },
  { delayMs: 12000, stage: 'long' },
]

function stageToActivityRow(stage) {
  if (stage === 'intent') {
    return { group: 'planning', label: 'Understanding...' }
  }
  if (stage === 'planning') {
    return { group: 'planning', label: 'Understanding your request...' }
  }
  if (stage === 'tool') {
    return { group: 'research', label: 'Checking information...' }
  }
  if (stage === 'answer') {
    return { group: 'planning', label: 'Wrapping up\u2026' }
  }
  return { group: 'system', label: 'Reviewing results...' }
}

function stageToMessage(stage) {
  if (stage === 'intent') return 'Understanding...'
  if (stage === 'planning') return 'Understanding your request...'
  if (stage === 'tool') return 'Checking information...'
  if (stage === 'answer') return 'Wrapping up\u2026'
  return 'Reviewing results...'
}

export function useFactoryAgentClientProgress({ activityTimelineEnabled, setActivitySteps }) {
  const [clientProgress, setClientProgress] = useState(null)
  const clientProgressTimersRef = useRef([])

  const clearClientProgressTimers = useCallback(() => {
    for (const timer of clientProgressTimersRef.current) {
      clearTimeout(timer)
    }
    clientProgressTimersRef.current = []
  }, [])

  const clearClientProgress = useCallback(() => {
    clearClientProgressTimers()
    setClientProgress(null)
    if (activityTimelineEnabled) {
      setActivitySteps((prev) =>
        (Array.isArray(prev) ? prev : []).filter((s) => !String(s?.id || '').startsWith('client_activity_')),
      )
    }
  }, [activityTimelineEnabled, clearClientProgressTimers, setActivitySteps])

  const startClientProgress = useCallback((sessionId, text) => {
    if (!sessionId) return
    clearClientProgressTimers()
    if (activityTimelineEnabled) {
      setClientProgress(null)
      const baseTs = Date.now() / 1000
      const detail = 'This updates as the session progresses'
      setActivitySteps([
        {
          id: 'client_activity_pending',
          timestamp: baseTs,
          group: 'planning',
          label: 'Understanding...',
          detail,
          state: 'running',
        },
      ])
      let archiveSeq = 0
      const applyStage = (stage) => {
        const row = stageToActivityRow(stage)
        const ts = Date.now() / 1000
        setActivitySteps((prev) => {
          const list = Array.isArray(prev) ? prev : []
          const pendingIdx = list.findIndex((s) => String(s?.id || '') === 'client_activity_pending')
          const pending = pendingIdx >= 0 ? list[pendingIdx] : null
          const rest = list.filter((s) => String(s?.id || '') !== 'client_activity_pending')

          const nextPending = {
            id: 'client_activity_pending',
            timestamp: ts,
            group: row.group,
            label: row.label,
            detail,
            state: 'running',
          }

          if (
            pending &&
            pending.group === nextPending.group &&
            pending.label === nextPending.label &&
            pending.state === 'running'
          ) {
            return list
          }

          if (!pending) {
            return [...rest, nextPending].sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))
          }

          archiveSeq += 1
          const archived = {
            ...pending,
            id: `client_activity_hist_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
            state: 'success',
            timestamp: ts - archiveSeq * 0.0001,
          }
          return [...rest, archived, nextPending].sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))
        })
      }
      for (const item of CLIENT_PROGRESS_STAGES) {
        const timer = setTimeout(() => applyStage(item.stage), item.delayMs)
        clientProgressTimersRef.current.push(timer)
      }
      return
    }

    const startedAt = new Date().toISOString()
    const requestKey = `${sessionId}:${Date.now()}`
    const setStage = (stage) => {
      setClientProgress({
        requestKey,
        sessionId,
        text,
        content: stageToMessage(stage),
        stage,
        startedAt,
      })
    }

    for (const item of CLIENT_PROGRESS_STAGES) {
      const timer = setTimeout(() => setStage(item.stage), item.delayMs)
      clientProgressTimersRef.current.push(timer)
    }
  }, [activityTimelineEnabled, clearClientProgressTimers, setActivitySteps])

  return {
    clientProgress,
    clearClientProgress,
    clearClientProgressTimers,
    startClientProgress,
  }
}
