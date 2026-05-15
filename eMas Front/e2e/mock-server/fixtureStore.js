import {
  activeHappyPathSnapshot,
  activitySseAnswer,
  activitySsePrompt,
  backendUnavailablePrompt,
  buildFactoryAgentPlan,
  buildHappyPathPlan,
  completedActivitySteps,
  completedHappyPathSnapshot,
  createFactoryAgentSession,
  emptyAssistantPrompt,
  executionStartedEvent,
  fixtureTime,
  machineStatusAnswer,
  machineStatusPrompt,
  notificationSseAnswer,
  notificationSsePrompt,
  orderedSseActivitySteps,
  planCreatedEvent,
  sessionCompletedEvent,
  sessionFailedEvent,
  sessionSummary,
  snapshotFromSession,
  toolResultEvent,
  userMessageEvent,
} from '../fixtures/factoryAgentFixtures.js'
import {
  defaultActivityStream,
  defaultNotificationStream,
  notificationCompletionStream,
  orderedActivityStream,
} from '../fixtures/sseScripts.js'

export const DEFAULT_SCENARIO = 'readMachineHappyPath'

function touch(session) {
  session.updated_at = new Date().toISOString()
}

function appendTimeline(session, event) {
  session.timeline.push({
    created_at: new Date().toISOString(),
    ...event,
  })
  touch(session)
}

function turnIdFor(session, prefix) {
  return `${prefix}-${session.messages.length + 1}`
}

function addUserTurn(session, content, prefix) {
  const turnId = turnIdFor(session, prefix)
  session.current_turn_id = turnId
  session.status = 'PLANNING'
  session.completion_scheduled = false
  session.completion_promise = null
  appendTimeline(session, userMessageEvent({ turnId, content }))
  return turnId
}

function completeSteps(session) {
  session.steps = session.steps.map((step) => ({
    ...step,
    status: 'DONE',
    updated_at: fixtureTime(4),
  }))
}

function scheduleCompletion(session, sleep, {
  delayMs = 450,
  turnId,
  planId,
  stepId,
  toolName,
  answer,
  eventPrefix,
} = {}) {
  if (session.completion_scheduled) return
  session.completion_scheduled = true
  session.completion_promise = (async () => {
    await sleep(delayMs)
    session.status = 'COMPLETED'
    completeSteps(session)
    appendTimeline(
      session,
      toolResultEvent({
        turnId,
        eventId: `${eventPrefix}-tool-result`,
        stepId,
        planId,
        toolName,
        content: answer,
        details: {
          args: { machine_id: 'M-CNC-01' },
          result: {
            machine_id: 'M-CNC-01',
            status: 'RUNNING',
            alarms: [],
            _summary: answer,
          },
        },
      }),
    )
    appendTimeline(
      session,
      sessionCompletedEvent({
        turnId,
        eventId: `${eventPrefix}-completed`,
        planId,
        content: answer,
        reason: 'sse_fixture',
      }),
    )
  })()
}

function defaultIdleSnapshot(session) {
  return snapshotFromSession(session)
}

export const scenarioCatalog = {
  readMachineHappyPath: {
    name: 'readMachineHappyPath',
    description: 'Phase 2 machine status happy path.',
    prompts: [machineStatusPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || machineStatusPrompt, 'pw-turn-machine-status')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-machine-status'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-machine-status'
      session.plan = buildHappyPathPlan(session)
      session.steps = [...session.plan.steps]
      appendTimeline(session, planCreatedEvent({ turnId }))
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-machine-status' } }
    },
    async onExecute(session, sleep) {
      const turnId = session.current_turn_id || 'pw-turn-machine-status'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(session, executionStartedEvent({ turnId }))
      await sleep(350)
      session.status = 'COMPLETED'
      completeSteps(session)
      appendTimeline(
        session,
        toolResultEvent({
          turnId,
          details: {
            args: { machine_id: 'M-CNC-01' },
            result: {
              machine_id: 'M-CNC-01',
              status: 'RUNNING',
              utilization: 87,
              alarms: [],
              next_maintenance: 'Friday 14:00',
              _summary: machineStatusAnswer,
            },
          },
        }),
      )
      appendTimeline(session, sessionCompletedEvent({ turnId }))
      return { status: 200, body: { status: 'COMPLETED', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'COMPLETED') return completedHappyPathSnapshot(session)
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return activeHappyPathSnapshot(session)
      return defaultIdleSnapshot(session)
    },
  },

  backendUnavailable: {
    name: 'backendUnavailable',
    description: 'Plan creation returns 503 without executing or faking success.',
    prompts: [backendUnavailablePrompt],
    onMessage(session, content) {
      addUserTurn(session, content || backendUnavailablePrompt, 'pw-turn-backend-unavailable')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-backend-unavailable'
      session.status = 'FAILED'
      appendTimeline(
        session,
        sessionFailedEvent({
          turnId,
          content: 'Service temporarily unavailable. Please retry shortly.',
        }),
      )
      return {
        status: 503,
        body: { detail: 'Service temporarily unavailable. Please retry shortly.' },
      }
    },
    async onExecute() {
      return { status: 409, body: { detail: 'Execution should not start for this scenario.' } }
    },
    snapshot(session) {
      return snapshotFromSession(session, [
        {
          id: 'pw-activity-backend-unavailable',
          timestamp: Date.parse(fixtureTime(3)) / 1000,
          group: 'error',
          label: 'Backend unavailable',
          detail: 'Factory Agent returned 503 while creating the plan',
          state: 'error',
        },
      ])
    },
  },

  emptyCompletedAnswer: {
    name: 'emptyCompletedAnswer',
    description: 'Completed snapshot has empty assistant content and must not reuse a previous answer.',
    prompts: [emptyAssistantPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || emptyAssistantPrompt, 'pw-turn-empty-answer')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-empty-answer'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-empty-answer'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-empty-answer',
        objective: 'Complete with an empty assistant body',
        stepId: 'pw-step-empty-answer',
        toolName: 'noop_empty_answer',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-plan-empty-answer-created',
          planId: 'pw-plan-empty-answer',
          content: '',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-empty-answer' } }
    },
    async onExecute(session, sleep) {
      const turnId = session.current_turn_id || 'pw-turn-empty-answer'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-empty-answer-execution-started',
          planId: 'pw-plan-empty-answer',
        }),
      )
      await sleep(120)
      session.status = 'COMPLETED'
      completeSteps(session)
      appendTimeline(
        session,
        sessionCompletedEvent({
          turnId,
          eventId: 'pw-empty-answer-completed',
          planId: 'pw-plan-empty-answer',
          content: '',
          reason: 'empty_assistant_content_fixture',
        }),
      )
      return { status: 200, body: { status: 'COMPLETED', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'COMPLETED') return snapshotFromSession(session, completedActivitySteps())
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return activeHappyPathSnapshot(session)
      return defaultIdleSnapshot(session)
    },
  },

  notificationSseCompletion: {
    name: 'notificationSseCompletion',
    description: 'Notification SSE hello and snapshot invalidation refresh a completed snapshot.',
    prompts: [notificationSsePrompt],
    onMessage(session, content) {
      addUserTurn(session, content || notificationSsePrompt, 'pw-turn-notification-sse')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-notification-sse'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-notification-sse'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-notification-sse',
        objective: 'Validate browser notification SSE refresh behavior',
        stepId: 'pw-step-notification-sse',
        toolName: 'get_machine_status',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-notification-sse-plan-created',
          planId: 'pw-plan-notification-sse',
          content: 'Waiting for the notification stream to invalidate the snapshot.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-notification-sse' } }
    },
    async onExecute(session, sleep) {
      const turnId = session.current_turn_id || 'pw-turn-notification-sse'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-notification-sse-execution-started',
          planId: 'pw-plan-notification-sse',
        }),
      )
      scheduleCompletion(session, sleep, {
        delayMs: 420,
        turnId,
        planId: 'pw-plan-notification-sse',
        stepId: 'pw-step-notification-sse',
        toolName: 'get_machine_status',
        answer: notificationSseAnswer,
        eventPrefix: 'pw-notification-sse',
      })
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'COMPLETED') return snapshotFromSession(session, completedActivitySteps())
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return activeHappyPathSnapshot(session)
      return defaultIdleSnapshot(session)
    },
    notificationStream() {
      return notificationCompletionStream()
    },
  },

  activitySseOrdered: {
    name: 'activitySseOrdered',
    description: 'Activity SSE emits ordered steps before final completion appears from the snapshot.',
    prompts: [activitySsePrompt],
    onMessage(session, content) {
      addUserTurn(session, content || activitySsePrompt, 'pw-turn-activity-sse')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-sse'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-activity-sse'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-activity-sse',
        objective: 'Validate ordered browser activity stream behavior',
        stepId: 'pw-step-activity-sse',
        toolName: 'get_machine_status',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-activity-sse-plan-created',
          planId: 'pw-plan-activity-sse',
          content: 'Keeping the assistant answer gated until activity and snapshot completion.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-activity-sse' } }
    },
    async onExecute(session, sleep) {
      const turnId = session.current_turn_id || 'pw-turn-activity-sse'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-activity-sse-execution-started',
          planId: 'pw-plan-activity-sse',
        }),
      )
      scheduleCompletion(session, sleep, {
        delayMs: 3200,
        turnId,
        planId: 'pw-plan-activity-sse',
        stepId: 'pw-step-activity-sse',
        toolName: 'get_machine_status',
        answer: activitySseAnswer,
        eventPrefix: 'pw-activity-sse',
      })
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'COMPLETED') return snapshotFromSession(session, orderedSseActivitySteps({ terminal: true }))
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return snapshotFromSession(session)
      return defaultIdleSnapshot(session)
    },
    notificationStream() {
      return notificationCompletionStream({ invalidationDelayMs: 3400 })
    },
    activityStream() {
      return orderedActivityStream()
    },
  },
}

export function scenarioNames() {
  return Object.keys(scenarioCatalog)
}

export function resolveScenarioForPrompt(prompt) {
  const normalized = String(prompt || '').trim().toLowerCase()
  return (
    Object.values(scenarioCatalog).find((scenario) =>
      scenario.prompts.some((candidate) => candidate.toLowerCase() === normalized),
    ) || scenarioCatalog[DEFAULT_SCENARIO]
  )
}

export function getScenario(name) {
  return scenarioCatalog[name] || scenarioCatalog[DEFAULT_SCENARIO]
}

export function createScenarioSession({ sessionId, userId, name, scenarioName = DEFAULT_SCENARIO }) {
  return createFactoryAgentSession({ sessionId, userId, name, scenarioName })
}

export function summarizeScenarioSession(session) {
  return sessionSummary(session)
}

export function notificationStreamForScenario(session) {
  const scenario = getScenario(session?.scenario_name)
  return scenario.notificationStream?.(session) || defaultNotificationStream()
}

export function activityStreamForScenario(session) {
  const scenario = getScenario(session?.scenario_name)
  return scenario.activityStream?.(session) || defaultActivityStream()
}
