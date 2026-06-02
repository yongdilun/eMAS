import { useCallback, useEffect, useRef } from 'react'
import { factoryAgentStreamAuth } from '../../../../services/factoryAgentApi.js'

const FACTORY_AGENT_BASE_URL = (
  import.meta.env?.VITE_FACTORY_AGENT_BASE_URL || 'http://127.0.0.1:8000'
).replace(/\/+$/, '')

export function useActivityStream(sessionId, onActivityStep, options = {}) {
  const { enabled = true, onDiagnostic } = options
  const onActivityStepRef = useRef(onActivityStep)
  onActivityStepRef.current = onActivityStep
  const onDiagnosticRef = useRef(onDiagnostic)
  onDiagnosticRef.current = onDiagnostic

  const esRef = useRef(null)
  const retryTimerRef = useRef(null)
  const retryDelayRef = useRef(500)
  const mountedRef = useRef(true)

  const queueRef = useRef([])
  const isProcessingQueueRef = useRef(false)

  const processQueue = useCallback(() => {
    if (!mountedRef.current) {
      isProcessingQueueRef.current = false
      return
    }
    // Drain everything already buffered (one SSE flush often sends several
    // `activity` lines back-to-back). Pace only between poll cycles (~1s),
    // not between steps from the same burst — otherwise the UI looks like
    // "first and last" with the middle row appearing a second late.
    while (queueRef.current.length > 0) {
      const step = queueRef.current.shift()
      onActivityStepRef.current?.(step)
    }
    if (!mountedRef.current) {
      isProcessingQueueRef.current = false
      return
    }
    setTimeout(() => {
      if (!mountedRef.current) {
        isProcessingQueueRef.current = false
        return
      }
      if (queueRef.current.length > 0) {
        processQueue()
      } else {
        isProcessingQueueRef.current = false
      }
    }, 1000)
  }, [])

  const closeEs = useCallback(() => {
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
  }, [])

  const emitDiagnostic = useCallback((status, message) => {
    onDiagnosticRef.current?.({
      source: 'activity-stream',
      status,
      message,
    })
  }, [])

  const connect = useCallback(() => {
    if (!mountedRef.current) return
    if (!sessionId || !enabled) return
    if (!factoryAgentStreamAuth.eventSourceEnabled) {
      emitDiagnostic('disabled', factoryAgentStreamAuth.disabledReason || 'Activity stream disabled.')
      return
    }
    if (typeof EventSource === 'undefined') {
      emitDiagnostic('disabled', 'Activity stream is unavailable in this browser.')
      return
    }

    closeEs()
    const url = `${FACTORY_AGENT_BASE_URL}/sessions/${sessionId}/events/activity`
    const es = new EventSource(url, { withCredentials: false })
    esRef.current = es

    es.addEventListener('activity_snapshot', (evt) => {
      if (!mountedRef.current) return
      try {
        const frame = JSON.parse(evt.data)
        const steps = Array.isArray(frame?.activity_steps)
          ? frame.activity_steps
          : Array.isArray(frame?.activitySteps)
            ? frame.activitySteps
            : []
        const revision = Number(frame?.activity_revision ?? frame?.activityRevision ?? evt.lastEventId ?? 0)
        if (frame && typeof frame === 'object') {
          queueRef.current.push({
            type: 'activity_snapshot',
            id: String(evt.lastEventId || revision || ''),
            activityRevision: Number.isFinite(revision) ? revision : 0,
            activitySteps: steps,
          })
          if (!isProcessingQueueRef.current) {
            isProcessingQueueRef.current = true
            processQueue()
          }
        }
      } catch {
        // ignore malformed frames
      }
    })

    es.addEventListener('activity', (evt) => {
      if (!mountedRef.current) return
      try {
        const step = JSON.parse(evt.data)
        if (step && typeof step === 'object' && step.id) {
          queueRef.current.push({ type: 'activity_legacy_step', step })
          if (!isProcessingQueueRef.current) {
            isProcessingQueueRef.current = true
            processQueue()
          }
        }
      } catch {
        // ignore malformed frames
      }
    })

    es.addEventListener('control', (evt) => {
      if (!mountedRef.current) return
      try {
        const frame = JSON.parse(evt.data)
        if (frame?.type === 'STREAM_READY') {
          retryDelayRef.current = 500
          emitDiagnostic('connected', 'Activity stream connected.')
        }
        if (frame?.type === 'SESSION_NOT_FOUND') {
          emitDiagnostic('stopped', 'Activity stream stopped because the session was not found.')
          closeEs()
        }
      } catch {
        // ignore
      }
    })

    es.onerror = () => {
      if (!mountedRef.current) return
      const delay = retryDelayRef.current
      retryDelayRef.current = Math.min(delay * 2, 30000)
      emitDiagnostic('reconnecting', `Activity stream disconnected. Reconnecting in ${Math.round(delay / 1000)} seconds.`)
      // Keep the EventSource open so native reconnect can send Last-Event-ID.
    }
  }, [sessionId, enabled, closeEs, emitDiagnostic, processQueue])

  useEffect(() => {
    mountedRef.current = true
    if (!sessionId || !enabled) {
      emitDiagnostic('idle', 'Activity stream idle.')
      closeEs()
      return () => {
        mountedRef.current = false
        closeEs()
      }
    }
    retryDelayRef.current = 500
    connect()
    return () => {
      mountedRef.current = false
      closeEs()
    }
  }, [sessionId, enabled, connect, closeEs, emitDiagnostic])
}
