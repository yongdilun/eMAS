import {
  activeHappyPathSnapshot,
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
  planCreatedEvent,
  sessionCompletedEvent,
  sessionFailedEvent,
  sessionSummary,
  snapshotFromSession,
  toolResultEvent,
  userMessageEvent,
} from '../fixtures/factoryAgentFixtures.js'

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
