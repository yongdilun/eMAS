import { useCallback, useRef, useState } from 'react'

const CLIENT_ACTIVITY_PREFIX = 'client_activity_'
const CLIENT_ACTIVITY_PENDING_ID = 'client_activity_pending'
const CLIENT_FALLBACK_LABEL = 'Starting request...'

export function isClientActivityStep(step) {
  return String(step?.id || '').startsWith(CLIENT_ACTIVITY_PREFIX)
}

export function stripClientActivitySteps(steps) {
  return (Array.isArray(steps) ? steps : []).filter((step) => !isClientActivityStep(step))
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
      setActivitySteps((prev) => stripClientActivitySteps(prev))
    }
  }, [activityTimelineEnabled, clearClientProgressTimers, setActivitySteps])

  const startClientProgress = useCallback((sessionId, text) => {
    if (!sessionId) return
    clearClientProgressTimers()
    if (activityTimelineEnabled) {
      setClientProgress(null)
      setActivitySteps((prev) => {
        const serverSteps = stripClientActivitySteps(prev)
        if (serverSteps.length) return serverSteps
        return [
          {
            id: CLIENT_ACTIVITY_PENDING_ID,
            timestamp: Date.now() / 1000,
            group: 'planning',
            label: CLIENT_FALLBACK_LABEL,
            detail: null,
            state: 'running',
          },
        ]
      })
      return
    }

    const startedAt = new Date().toISOString()
    const requestKey = `${sessionId}:${Date.now()}`
    setClientProgress({
      requestKey,
      sessionId,
      text,
      content: CLIENT_FALLBACK_LABEL,
      stage: 'starting',
      startedAt,
    })
  }, [activityTimelineEnabled, clearClientProgressTimers, setActivitySteps])

  return {
    clientProgress,
    clearClientProgress,
    clearClientProgressTimers,
    startClientProgress,
  }
}
