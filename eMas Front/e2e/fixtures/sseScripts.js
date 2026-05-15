import { fixtureTime, orderedSseActivitySteps } from './factoryAgentFixtures.js'

export function defaultNotificationStream() {
  return [
    {
      id: 1,
      event: 'notification',
      data: { type: 'hello', cursor: 1 },
    },
  ]
}

export function defaultActivityStream() {
  return [
    {
      id: 1,
      event: 'control',
      data: { type: 'STREAM_READY' },
    },
  ]
}

export function notificationCompletionStream({ invalidationDelayMs = 650 } = {}) {
  return [
    {
      id: 1,
      event: 'notification',
      data: { type: 'hello', cursor: 1 },
    },
    {
      id: 2,
      event: 'notification',
      delayMs: 80,
      data: { type: 'heartbeat', cursor: 1 },
    },
    {
      id: 3,
      event: 'notification',
      delayMs: invalidationDelayMs,
      data: {
        type: 'snapshot_invalidated',
        cursor: 2,
        reason: 'execution_completed',
        session_status: 'COMPLETED',
      },
    },
    {
      id: 4,
      event: 'notification',
      delayMs: 40,
      data: {
        type: 'phase_changed',
        cursor: 3,
        phase: 'COMPLETED',
        status: 'COMPLETED',
      },
    },
  ]
}

export function malformedThenValidNotificationStream({ invalidationDelayMs = 650 } = {}) {
  return [
    {
      id: 1,
      event: 'notification',
      data: { type: 'hello', cursor: 1 },
    },
    {
      raw: 'id: 2\nevent: notification\ndata: { this is not valid json',
      delayMs: 80,
    },
    {
      id: 3,
      event: 'notification',
      delayMs: invalidationDelayMs,
      data: {
        type: 'snapshot_invalidated',
        cursor: 2,
        reason: 'malformed_frame_recovery',
        session_status: 'COMPLETED',
      },
    },
    {
      id: 4,
      event: 'notification',
      delayMs: 40,
      data: {
        type: 'phase_changed',
        cursor: 3,
        phase: 'COMPLETED',
        status: 'COMPLETED',
      },
    },
  ]
}

export function disconnectingNotificationStream() {
  return [
    {
      id: 1,
      event: 'notification',
      data: { type: 'hello', cursor: 1 },
    },
    {
      delayMs: 80,
      close: true,
    },
  ]
}

export function longRunningNotificationStream() {
  return [
    {
      id: 1,
      event: 'notification',
      data: { type: 'hello', cursor: 1 },
    },
  ]
}

export function orderedActivityStream() {
  const [understanding, checking, validating] = orderedSseActivitySteps({ terminal: false })

  return [
    {
      id: 1,
      event: 'control',
      data: { type: 'STREAM_READY' },
    },
    {
      id: 2,
      event: 'activity',
      delayMs: 90,
      data: { ...understanding, state: 'success', timestamp: Date.parse(fixtureTime(1)) / 1000 },
    },
    {
      id: 3,
      event: 'control',
      delayMs: 40,
      data: { type: 'HEARTBEAT' },
    },
    {
      id: 4,
      event: 'activity',
      delayMs: 1100,
      data: { ...checking, state: 'running' },
    },
    {
      id: 5,
      event: 'activity',
      delayMs: 1100,
      data: { ...validating, state: 'running' },
    },
  ]
}
