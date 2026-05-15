export const machineStatusPrompt = 'Show status for machine M-CNC-01'

export const machineStatusAnswer =
  'Machine M-CNC-01 is running normally at 87% utilization. No active alarms are reported, and the next preventive maintenance window is scheduled for Friday at 14:00.'

export const backendUnavailablePrompt = 'Simulate backend unavailable during plan creation'

export const emptyAssistantPrompt = 'Return an empty completed answer'

export const emptyAssistantFallbackAnswer = 'Execution completed.'

export const notificationSsePrompt = 'Validate notification SSE refresh for M-CNC-01'

export const notificationSseAnswer =
  'Notification SSE refreshed the Factory Agent snapshot and confirmed M-CNC-01 is complete with no alarms.'

export const activitySsePrompt = 'Validate ordered activity SSE steps for M-CNC-01'

export const activitySseAnswer =
  'Activity SSE completed in order before the final M-CNC-01 response was shown.'

export const malformedSsePrompt = 'Validate malformed SSE recovery for M-CNC-01'

export const malformedSseAnswer =
  'Malformed SSE data was ignored, and the later valid notification refreshed the completed M-CNC-01 answer.'

export const retryExecutePrompt = 'Simulate execute retry for machine M-CNC-01'

export const retryExecuteAnswer =
  'Execution retried after a temporary conflict and completed the M-CNC-01 status check.'

export const nonTerminalPrompt = 'Keep the Factory Agent run active without a final answer'

export const nonTerminalFinalAnswer = 'This non-terminal fixture should never be rendered as a final answer.'

export const cancelRunPrompt = 'Start an active run that I will cancel'

export const cancelledRunMessage = 'Run cancelled by operator request.'

export const disconnectPrompt = 'Open a long running SSE stream for disconnect testing'

export const streamDropPrompt = 'Simulate notification SSE disconnect for M-CNC-01'

const baseTime = Date.parse('2026-05-16T04:00:00.000Z')

export function fixtureTime(offsetSeconds = 0) {
  return new Date(baseTime + offsetSeconds * 1000).toISOString()
}

export function createFactoryAgentSession({ sessionId, userId, name, scenarioName = 'readMachineHappyPath' }) {
  const createdAt = fixtureTime()
  return {
    session_id: sessionId,
    user_id: userId || 'frontend-operator',
    name: name || 'Playwright session',
    scenario_name: scenarioName,
    current_turn_id: null,
    status: 'IDLE',
    created_at: createdAt,
    updated_at: createdAt,
    operation_id: null,
    messages: [],
    timeline: [],
    plan: null,
    steps: [],
    activity_steps: [],
    pending_approval: null,
    execute_count: 0,
  }
}

export function createHappyPathSession(options) {
  return createFactoryAgentSession(options)
}

export function buildFactoryAgentPlan(
  session,
  {
    planId = 'pw-plan-machine-status',
    objective = 'Review machine status for M-CNC-01',
    stepId = 'pw-step-machine-status',
    toolName = 'get_machine_status',
    status = 'EXECUTING',
  } = {},
) {
  return {
    plan_id: planId,
    session_id: session.session_id,
    status,
    objective,
    created_at: fixtureTime(2),
    updated_at: fixtureTime(2),
    steps: [
      {
        id: stepId,
        plan_id: planId,
        tool_name: toolName,
        status: 'IN_PROGRESS',
        created_at: fixtureTime(3),
      },
    ],
  }
}

export function buildHappyPathPlan(session) {
  return buildFactoryAgentPlan(session)
}

export function userMessageEvent({ turnId, content, offsetSeconds = 1 }) {
  return {
    event_id: turnId,
    turn_id: turnId,
    event_type: 'user_message',
    role: 'user',
    content,
    status: 'DONE',
    created_at: fixtureTime(offsetSeconds),
  }
}

export function planCreatedEvent({
  turnId,
  eventId = 'pw-plan-created',
  planId = 'pw-plan-machine-status',
  content = 'Checking machine status for M-CNC-01.',
  status = 'COMPLETED',
  offsetSeconds = 2,
} = {}) {
  return {
    event_id: eventId,
    turn_id: turnId,
    event_type: 'plan_created',
    content,
    status,
    operation_id: planId,
    details: {
      status,
      plan_id: planId,
      plan_explanation: content,
    },
    created_at: fixtureTime(offsetSeconds),
  }
}

export function executionStartedEvent({
  turnId,
  eventId = 'pw-execution-started',
  planId = 'pw-plan-machine-status',
  offsetSeconds = 3,
} = {}) {
  return {
    event_id: eventId,
    turn_id: turnId,
    event_type: 'execution_started',
    content: 'Execution started.',
    status: 'IN_PROGRESS',
    operation_id: planId,
    created_at: fixtureTime(offsetSeconds),
  }
}

export function toolResultEvent({
  turnId,
  eventId = 'pw-tool-result-machine-status',
  stepId = 'pw-step-machine-status',
  planId = 'pw-plan-machine-status',
  toolName = 'get_machine_status',
  content = machineStatusAnswer,
  details,
  offsetSeconds = 4,
} = {}) {
  return {
    event_id: eventId,
    turn_id: turnId,
    event_type: 'tool_result',
    step_id: stepId,
    tool_name: toolName,
    content,
    status: 'DONE',
    operation_id: planId,
    details,
    created_at: fixtureTime(offsetSeconds),
  }
}

export function sessionCompletedEvent({
  turnId,
  eventId = 'pw-session-completed',
  planId = 'pw-plan-machine-status',
  content = machineStatusAnswer,
  reason = 'happy_path_fixture',
  offsetSeconds = 5,
} = {}) {
  return {
    event_id: eventId,
    turn_id: turnId,
    event_type: 'session_completed',
    content,
    status: 'COMPLETED',
    operation_id: planId,
    details: { reason },
    created_at: fixtureTime(offsetSeconds),
  }
}

export function sessionFailedEvent({
  turnId,
  eventId = 'pw-session-failed',
  content = 'Service temporarily unavailable. Please retry shortly.',
  reason = 'backend_unavailable_fixture',
  offsetSeconds = 3,
} = {}) {
  return {
    event_id: eventId,
    turn_id: turnId,
    event_type: 'session_failed',
    content,
    status: 'FAILED',
    details: { reason },
    created_at: fixtureTime(offsetSeconds),
  }
}

export function snapshotFromSession(session, activitySteps = []) {
  return {
    session: sessionSummary(session),
    messages: session.messages,
    timeline: [...session.timeline],
    plan: session.plan,
    steps: session.steps,
    activity_steps: activitySteps,
    pending_approval: session.pending_approval || null,
    resume_hint: null,
  }
}

export function activeHappyPathSnapshot(session) {
  return snapshotFromSession(session, [
    {
      id: 'pw-activity-understanding',
      timestamp: Date.parse(fixtureTime(1)) / 1000,
      group: 'planning',
      label: 'Understanding your request',
      detail: 'Reviewing machine M-CNC-01 and recent context',
      state: 'running',
    },
  ])
}

export function completedHappyPathSnapshot(session) {
  return snapshotFromSession(session, completedActivitySteps())
}

export function completedActivitySteps() {
  return [
    {
      id: 'pw-activity-understanding',
      timestamp: Date.parse(fixtureTime(1)) / 1000,
      group: 'planning',
      label: 'Understanding your request',
      detail: 'Reviewing machine M-CNC-01 and recent context',
      state: 'success',
    },
    {
      id: 'pw-activity-checking',
      timestamp: Date.parse(fixtureTime(4)) / 1000,
      group: 'research',
      label: 'Gathering information',
      detail: 'Checking machine records',
      state: 'success',
    },
    {
      id: 'pw-activity-complete',
      timestamp: Date.parse(fixtureTime(5)) / 1000,
      group: 'response',
      label: 'Run complete',
      detail: 'All steps finished. See the thread below.',
      state: 'complete',
    },
  ]
}

export function orderedSseActivitySteps({ terminal = false } = {}) {
  const steps = [
    {
      id: 'pw-sse-activity-understanding',
      timestamp: Date.parse(fixtureTime(1)) / 1000,
      group: 'planning',
      label: 'SSE understanding request',
      detail: 'Notification stream opened and the request was accepted',
      state: 'success',
    },
    {
      id: 'pw-sse-activity-checking-machine',
      timestamp: Date.parse(fixtureTime(2)) / 1000,
      group: 'research',
      label: 'SSE checking machine telemetry',
      detail: 'Reading M-CNC-01 status and alarm records',
      state: terminal ? 'success' : 'running',
    },
    {
      id: 'pw-sse-activity-validating',
      timestamp: Date.parse(fixtureTime(3)) / 1000,
      group: 'research',
      label: 'SSE validating result',
      detail: 'Ordering the streamed activity rows before final response',
      state: terminal ? 'success' : 'waiting',
    },
  ]

  if (terminal) {
    steps.push({
      id: 'pw-sse-activity-complete',
      timestamp: Date.parse(fixtureTime(4)) / 1000,
      group: 'response',
      label: 'Run complete',
      detail: 'All steps finished. See the thread below.',
      state: 'complete',
    })
  }

  return steps
}

export function sessionSummary(session) {
  return {
    session_id: session.session_id,
    user_id: session.user_id,
    name: session.name,
    status: session.status,
    created_at: session.created_at,
    updated_at: session.updated_at,
    operation_id: session.operation_id || session.plan?.plan_id || null,
  }
}
