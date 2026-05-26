import { fixtureTime, orderedSseActivitySteps } from './factoryAgentFixtures.js'
import { reliabilityLongActivitySteps } from '../support/reliabilityScenarios.js'

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

export function orderedActivityStream({ firstActivityDelayMs = 90, prematureTerminal = false } = {}) {
  const [understanding, checking, validating] = orderedSseActivitySteps({ terminal: false })
  const [, , , complete] = orderedSseActivitySteps({ terminal: true })

  const frames = [
    {
      id: 1,
      event: 'control',
      data: { type: 'STREAM_READY' },
    },
    {
      id: 2,
      event: 'activity',
      delayMs: firstActivityDelayMs,
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

  if (prematureTerminal) {
    frames.push({
      id: 6,
      event: 'activity',
      delayMs: 120,
      data: complete,
    })
  }

  return frames
}

export function activeSnapshotRaceNotificationStream() {
  return [
    {
      id: 1,
      event: 'notification',
      data: { type: 'hello', cursor: 1 },
    },
    {
      id: 2,
      event: 'notification',
      delayMs: 650,
      data: {
        type: 'snapshot_invalidated',
        cursor: 2,
        reason: 'active_snapshot_race',
        session_status: 'EXECUTING',
      },
    },
    {
      id: 3,
      event: 'notification',
      delayMs: 650,
      data: {
        type: 'snapshot_invalidated',
        cursor: 3,
        reason: 'active_snapshot_race',
        session_status: 'EXECUTING',
      },
    },
    {
      id: 4,
      event: 'notification',
      delayMs: 650,
      data: {
        type: 'snapshot_invalidated',
        cursor: 4,
        reason: 'active_snapshot_race',
        session_status: 'EXECUTING',
      },
    },
    {
      id: 5,
      event: 'notification',
      delayMs: 1200,
      data: {
        type: 'snapshot_invalidated',
        cursor: 5,
        reason: 'execution_completed',
        session_status: 'COMPLETED',
      },
    },
    {
      id: 6,
      event: 'notification',
      delayMs: 40,
      data: {
        type: 'phase_changed',
        cursor: 6,
        phase: 'COMPLETED',
        status: 'COMPLETED',
      },
    },
  ]
}

export function reliabilityLongActivityStream() {
  return [
    {
      id: 1,
      event: 'control',
      data: { type: 'STREAM_READY' },
    },
    ...reliabilityLongActivitySteps({ terminal: false }).map((step, index) => ({
      id: index + 2,
      event: 'activity',
      delayMs: index === 0 ? 50 : 10,
      data: step,
    })),
  ]
}
