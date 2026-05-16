import {
  activeHappyPathSnapshot,
  activitySseAnswer,
  activitySsePrompt,
  backendUnavailablePrompt,
  buildFactoryAgentPlan,
  buildHappyPathPlan,
  cancelRunPrompt,
  completedActivitySteps,
  completedHappyPathSnapshot,
  createFactoryAgentSession,
  disconnectPrompt,
  emptyAssistantPrompt,
  executionStartedEvent,
  fixtureTime,
  machineStatusAnswer,
  machineStatusPrompt,
  malformedSseAnswer,
  malformedSsePrompt,
  nonTerminalPrompt,
  notificationSseAnswer,
  notificationSsePrompt,
  orderedSseActivitySteps,
  planCreatedEvent,
  retryExecuteAnswer,
  retryExecutePrompt,
  sessionCompletedEvent,
  sessionFailedEvent,
  sessionSummary,
  snapshotFromSession,
  streamDropPrompt,
  toolResultEvent,
  userMessageEvent,
} from '../fixtures/factoryAgentFixtures.js'
import {
  defaultActivityStream,
  defaultNotificationStream,
  disconnectingNotificationStream,
  longRunningNotificationStream,
  malformedThenValidNotificationStream,
  notificationCompletionStream,
  orderedActivityStream,
  reliabilityLongActivityStream,
} from '../fixtures/sseScripts.js'
import {
  normalUseLifecycleCompletedPrompt,
  normalUsePlanModeFinalPrompt,
  normalUsePromptSet,
  normalUseTurnForPrompt,
} from '../support/normalUseScenarios.js'
import {
  manualPromptBankPrompts,
  phase18MockRagAnswer,
  phase18MockRagSource,
} from '../support/intentEntityScenarios.js'
import {
  phase19UnknownDiagnostic,
  phase19UnknownPrompt,
} from '../support/promptRegressionScenarios.js'
import {
  reliabilityConcurrentTurns,
  reliabilityLargeResultAnswer,
  reliabilityLargeResultPresentation,
  reliabilityLargeResultPrompt,
  reliabilityLargeResultRows,
  reliabilityLargeResultSources,
  reliabilityLongActivitySteps,
  reliabilityLongStreamAnswer,
  reliabilityLongStreamPrompt,
  reliabilitySlowActivitySteps,
  reliabilitySlowTimeoutPrompt,
  reliabilityTurnForPrompt,
} from '../support/reliabilityScenarios.js'
import {
  securityActivitySteps,
  securityLargeUnsafePrompt,
  securityMockTools,
  securitySafeOwnAnswer,
  securitySafeOwnPrompt,
  securityUnsafeActionBlocked,
  securityUnsafeActionPrompt,
  securityUnsafeActionRisk,
  securityUnsafeMarkdownAnswer,
} from '../support/securityScenarios.js'

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

function normalUseIds(session, turn) {
  const safeKey = String(turn?.key || 'turn').replace(/[^a-z0-9-]/gi, '-').toLowerCase()
  const sequence = session.messages.length || 1
  return {
    turnId: session.current_turn_id || `pw-turn-normal-use-${safeKey}-${sequence}`,
    planId: `pw-plan-normal-use-${safeKey}-${sequence}`,
    stepId: `pw-step-normal-use-${safeKey}-${sequence}`,
  }
}

function normalUseDetails(turn) {
  return {
    args: turn.args || {},
    result: {
      ...(turn.result || {}),
      _summary: turn.answer,
    },
    ...(turn.presentation ? { presentation: turn.presentation } : {}),
  }
}

function normalUseActivitySteps(turn) {
  return [
    {
      id: `pw-normal-use-understanding-${turn.key}`,
      timestamp: Date.parse(fixtureTime(1)) / 1000,
      group: 'planning',
      label: 'Understanding your request',
      detail: turn.plan,
      state: 'success',
    },
    {
      id: `pw-normal-use-checking-${turn.key}`,
      timestamp: Date.parse(fixtureTime(2)) / 1000,
      group: 'research',
      label: 'Gathering information',
      detail: `Using ${turn.toolName} for the normal-use fixture`,
      state: 'success',
    },
    {
      id: `pw-normal-use-complete-${turn.key}`,
      timestamp: Date.parse(fixtureTime(3)) / 1000,
      group: 'response',
      label: 'Run complete',
      detail: 'Normal-use turn completed.',
      state: 'complete',
    },
  ]
}

function currentNormalUseTurn(session) {
  return session.normal_use_current_turn || normalUseTurnForPrompt(session.last_prompt)
}

function reliabilityIds(session, key = 'run') {
  const safeKey = String(key || 'run').replace(/[^a-z0-9-]/gi, '-').toLowerCase()
  const sequence = session.messages.length || 1
  return {
    turnId: session.current_turn_id || `pw-turn-reliability-${safeKey}-${sequence}`,
    planId: `pw-plan-reliability-${safeKey}-${sequence}`,
    stepId: `pw-step-reliability-${safeKey}-${sequence}`,
  }
}

export const scenarioCatalog = {
  reliabilityConcurrentReadOnly: {
    name: 'reliabilityConcurrentReadOnly',
    description: 'Phase 15 ten concurrent read-only sessions with per-session answers.',
    prompts: reliabilityConcurrentTurns.map((turn) => turn.prompt),
    onMessage(session, content) {
      const turn = reliabilityTurnForPrompt(content)
      session.reliability_turn = turn
      addUserTurn(session, content || turn.prompt, `pw-turn-reliability-${turn.key}`)
    },
    onPlan(session) {
      const turn = session.reliability_turn || reliabilityTurnForPrompt(session.last_prompt)
      const ids = reliabilityIds(session, turn.key)
      session.status = 'EXECUTING'
      session.operation_id = ids.planId
      session.plan = buildFactoryAgentPlan(session, {
        planId: ids.planId,
        objective: `Read-only reliability status check for ${turn.label}.`,
        stepId: ids.stepId,
        toolName: 'get_machine_status',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-created`,
          planId: ids.planId,
          content: `Checking ${turn.machineId} for ${turn.label}.`,
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: ids.planId } }
    },
    async onExecute(session, sleep) {
      const turn = session.reliability_turn || reliabilityTurnForPrompt(session.last_prompt)
      const ids = reliabilityIds(session, turn.key)
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-execution-started`,
          planId: ids.planId,
        }),
      )
      await sleep(120 + reliabilityConcurrentTurns.indexOf(turn) * 12)
      session.status = 'COMPLETED'
      completeSteps(session)
      appendTimeline(
        session,
        toolResultEvent({
          turnId: ids.turnId,
          eventId: `${ids.stepId}-tool-result`,
          stepId: ids.stepId,
          planId: ids.planId,
          toolName: 'get_machine_status',
          content: turn.answer,
          details: {
            args: { machine_id: turn.machineId },
            result: {
              machine_id: turn.machineId,
              reliability_session: turn.label,
              _summary: turn.answer,
            },
          },
        }),
      )
      appendTimeline(
        session,
        sessionCompletedEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-completed`,
          planId: ids.planId,
          content: turn.answer,
          reason: 'reliability_concurrent_fixture',
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

  reliabilityLongActivityStream: {
    name: 'reliabilityLongActivityStream',
    description: 'Phase 15 long activity stream with many ordered rows.',
    prompts: [reliabilityLongStreamPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || reliabilityLongStreamPrompt, 'pw-turn-reliability-long-stream')
    },
    onPlan(session) {
      const ids = reliabilityIds(session, 'long-stream')
      session.status = 'EXECUTING'
      session.operation_id = ids.planId
      session.plan = buildFactoryAgentPlan(session, {
        planId: ids.planId,
        objective: 'Exercise a long activity stream without duplicate rows.',
        stepId: ids.stepId,
        toolName: 'stream_many_activity_events',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-created`,
          planId: ids.planId,
          content: 'Starting the Phase 15 long activity stream.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: ids.planId } }
    },
    async onExecute(session, sleep) {
      const ids = reliabilityIds(session, 'long-stream')
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-execution-started`,
          planId: ids.planId,
        }),
      )
      scheduleCompletion(session, sleep, {
        delayMs: 900,
        turnId: ids.turnId,
        planId: ids.planId,
        stepId: ids.stepId,
        toolName: 'stream_many_activity_events',
        answer: reliabilityLongStreamAnswer,
        eventPrefix: 'pw-reliability-long-stream',
      })
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'COMPLETED') return snapshotFromSession(session, reliabilityLongActivitySteps({ terminal: true }))
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return snapshotFromSession(session, reliabilityLongActivitySteps({ terminal: false }).slice(0, 1))
      return defaultIdleSnapshot(session)
    },
    notificationStream() {
      return notificationCompletionStream({ invalidationDelayMs: 1350 })
    },
    activityStream() {
      return reliabilityLongActivityStream()
    },
  },

  reliabilityLargeStructuredResult: {
    name: 'reliabilityLargeStructuredResult',
    description: 'Phase 15 large table result plus many knowledge sources.',
    prompts: [reliabilityLargeResultPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || reliabilityLargeResultPrompt, 'pw-turn-reliability-large-result')
    },
    onPlan(session) {
      const ids = reliabilityIds(session, 'large-result')
      session.status = 'EXECUTING'
      session.operation_id = ids.planId
      session.plan = buildFactoryAgentPlan(session, {
        planId: ids.planId,
        objective: 'Render a large structured read-only result with many sources.',
        stepId: ids.stepId,
        toolName: 'list_reliability_jobs',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-created`,
          planId: ids.planId,
          content: 'Gathering a large read-only reliability result set.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: ids.planId } }
    },
    async onExecute(session, sleep) {
      const ids = reliabilityIds(session, 'large-result')
      const sources = reliabilityLargeResultSources()
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-execution-started`,
          planId: ids.planId,
        }),
      )
      await sleep(180)
      session.status = 'COMPLETED'
      completeSteps(session)
      appendTimeline(
        session,
        toolResultEvent({
          turnId: ids.turnId,
          eventId: `${ids.stepId}-tool-result`,
          stepId: ids.stepId,
          planId: ids.planId,
          toolName: 'list_reliability_jobs',
          content: reliabilityLargeResultAnswer,
          details: {
            args: { limit: 120, include_sources: true },
            result: {
              data: reliabilityLargeResultRows(),
              _summary: reliabilityLargeResultAnswer,
            },
            presentation: reliabilityLargeResultPresentation(),
          },
        }),
      )
      appendTimeline(
        session,
        sessionCompletedEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-completed`,
          planId: ids.planId,
          content: reliabilityLargeResultAnswer,
          reason: 'reliability_large_result_fixture',
          details: { sources },
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

  reliabilitySlowResponseTimeout: {
    name: 'reliabilitySlowResponseTimeout',
    description: 'Phase 15 slow plan response lets the browser timeout while preserving retry/cancel controls.',
    prompts: [reliabilitySlowTimeoutPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || reliabilitySlowTimeoutPrompt, 'pw-turn-reliability-slow-timeout')
    },
    async onPlan(session, sleep) {
      const ids = reliabilityIds(session, 'slow-timeout')
      await sleep(2600)
      if (session.status === 'FAILED') {
        return { status: 409, body: { detail: 'Run was cancelled before slow planning completed.' } }
      }
      session.status = 'EXECUTING'
      session.operation_id = ids.planId
      session.plan = buildFactoryAgentPlan(session, {
        planId: ids.planId,
        objective: 'This plan is intentionally slower than the reliability request timeout.',
        stepId: ids.stepId,
        toolName: 'slow_reliability_tool',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-created`,
          planId: ids.planId,
          content: 'The slow fixture eventually created a plan.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: ids.planId } }
    },
    async onExecute(session, sleep) {
      const ids = reliabilityIds(session, 'slow-timeout')
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-execution-started`,
          planId: ids.planId,
        }),
      )
      await sleep(2600)
      if (session.status === 'FAILED') {
        return { status: 409, body: { detail: 'Run was cancelled before slow execution completed.' } }
      }
      session.status = 'COMPLETED'
      completeSteps(session)
      appendTimeline(
        session,
        sessionCompletedEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-completed`,
          planId: ids.planId,
          content: 'Slow response completed after the timeout window.',
          reason: 'reliability_slow_timeout_fixture',
        }),
      )
      return { status: 200, body: { status: 'COMPLETED', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'FAILED') return snapshotFromSession(session)
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return snapshotFromSession(session, reliabilitySlowActivitySteps())
      return defaultIdleSnapshot(session)
    },
    notificationStream() {
      return longRunningNotificationStream()
    },
  },

  securityOwnerIsolatedRead: {
    name: 'securityOwnerIsolatedRead',
    description: 'Phase 16 current-operator read-only session used for local-storage tamper checks.',
    prompts: [securitySafeOwnPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || securitySafeOwnPrompt, 'pw-turn-security-owner')
    },
    onPlan(session) {
      const ids = {
        turnId: session.current_turn_id || 'pw-turn-security-owner',
        planId: 'pw-plan-security-owner',
        stepId: 'pw-step-security-owner',
      }
      session.status = 'EXECUTING'
      session.operation_id = ids.planId
      session.plan = buildFactoryAgentPlan(session, {
        planId: ids.planId,
        objective: 'Confirm the current operator sees only their own session.',
        stepId: ids.stepId,
        toolName: 'get_machine_status',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-created`,
          planId: ids.planId,
          content: 'Checking current-operator session isolation.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: ids.planId } }
    },
    async onExecute(session, sleep) {
      const turnId = session.current_turn_id || 'pw-turn-security-owner'
      await sleep(120)
      session.status = 'COMPLETED'
      completeSteps(session)
      appendTimeline(
        session,
        toolResultEvent({
          turnId,
          eventId: 'pw-security-owner-tool-result',
          stepId: 'pw-step-security-owner',
          planId: 'pw-plan-security-owner',
          toolName: 'get_machine_status',
          content: securitySafeOwnAnswer,
          details: {
            args: { machine_id: 'M-CNC-01' },
            result: {
              machine_id: 'M-CNC-01',
              _summary: securitySafeOwnAnswer,
            },
          },
        }),
      )
      appendTimeline(
        session,
        sessionCompletedEvent({
          turnId,
          eventId: 'pw-security-owner-completed',
          planId: 'pw-plan-security-owner',
          content: securitySafeOwnAnswer,
          reason: 'security_owner_isolation_fixture',
        }),
      )
      return { status: 200, body: { status: 'COMPLETED', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'COMPLETED') return snapshotFromSession(session, securityActivitySteps({ terminal: true }))
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return snapshotFromSession(session, securityActivitySteps())
      return defaultIdleSnapshot(session)
    },
  },

  securityLargeUnsafeMarkdown: {
    name: 'securityLargeUnsafeMarkdown',
    description: 'Phase 16 large pasted input and unsafe rendered content stay inert and stable.',
    prompts: [securityLargeUnsafePrompt],
    onMessage(session, content) {
      addUserTurn(session, content || securityLargeUnsafePrompt, 'pw-turn-security-large-unsafe')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-security-large-unsafe'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-security-large-unsafe'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-security-large-unsafe',
        objective: 'Render unsafe markdown and large text safely.',
        stepId: 'pw-step-security-large-unsafe',
        toolName: 'render_security_fixture',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-security-large-plan-created',
          planId: 'pw-plan-security-large-unsafe',
          content: 'Validating large input and unsafe markdown rendering.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-security-large-unsafe' } }
    },
    async onExecute(session, sleep) {
      const turnId = session.current_turn_id || 'pw-turn-security-large-unsafe'
      await sleep(140)
      session.status = 'COMPLETED'
      completeSteps(session)
      appendTimeline(
        session,
        toolResultEvent({
          turnId,
          eventId: 'pw-security-large-tool-result',
          stepId: 'pw-step-security-large-unsafe',
          planId: 'pw-plan-security-large-unsafe',
          toolName: 'render_security_fixture',
          content: securityUnsafeMarkdownAnswer,
          details: {
            args: { render_mode: 'inert_text' },
            result: {
              _summary: securityUnsafeMarkdownAnswer,
            },
          },
        }),
      )
      appendTimeline(
        session,
        sessionCompletedEvent({
          turnId,
          eventId: 'pw-security-large-completed',
          planId: 'pw-plan-security-large-unsafe',
          content: securityUnsafeMarkdownAnswer,
          reason: 'security_large_unsafe_markdown_fixture',
        }),
      )
      return { status: 200, body: { status: 'COMPLETED', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'COMPLETED') return snapshotFromSession(session, securityActivitySteps({ terminal: true }))
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return snapshotFromSession(session, securityActivitySteps())
      return defaultIdleSnapshot(session)
    },
  },

  securityUnsafeToolBlocked: {
    name: 'securityUnsafeToolBlocked',
    description: 'Phase 16 unsafe unsupported tool request stays approval-gated and allowlist-blocked.',
    prompts: [securityUnsafeActionPrompt],
    onMessage(session, content) {
      const turnId = addUserTurn(session, content || securityUnsafeActionPrompt, 'pw-turn-security-unsafe-tool')
      session.security_pending_turn_id = turnId
    },
    onPlan(session) {
      const turnId = session.security_pending_turn_id || session.current_turn_id || 'pw-turn-security-unsafe-tool'
      session.status = 'WAITING_APPROVAL'
      session.operation_id = 'pw-plan-security-unsafe-tool'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-security-unsafe-tool',
        objective: 'Block unsupported destructive action unless an approved allowlisted tool exists.',
        stepId: 'pw-step-security-unsafe-tool',
        toolName: 'phase16_unsafe_delete_production_jobs',
        status: 'PENDING_APPROVAL',
      })
      session.steps = session.plan.steps.map((step) => ({ ...step, status: 'WAITING_APPROVAL' }))
      session.pending_approval = {
        approval_id: 'pw-approval-security-unsafe-tool',
        session_id: session.session_id,
        subject_type: 'tool',
        tool_name: 'phase16_unsafe_delete_production_jobs',
        side_effect_level: 'CRITICAL',
        risk_summary: securityUnsafeActionRisk,
        args: { reason: 'operator attempted unsupported destructive action' },
        status: 'PENDING',
        created_at: fixtureTime(3),
        expires_at: fixtureTime(300),
      }
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-security-unsafe-plan-created',
          planId: 'pw-plan-security-unsafe-tool',
          content: 'Unsafe destructive tool request requires approval and allowlist review.',
          status: 'PENDING_APPROVAL',
        }),
      )
      appendTimeline(session, {
        event_id: 'pw-security-unsafe-approval-required',
        turn_id: turnId,
        event_type: 'approval_required',
        approval_id: session.pending_approval.approval_id,
        tool_name: session.pending_approval.tool_name,
        content: securityUnsafeActionRisk,
        status: 'PENDING',
        details: {
          args: session.pending_approval.args,
          side_effect_level: session.pending_approval.side_effect_level,
        },
        created_at: fixtureTime(3),
      })
      return { status: 200, body: { status: 'WAITING_APPROVAL', plan_id: 'pw-plan-security-unsafe-tool' } }
    },
    async onExecute() {
      return { status: 200, body: { status: 'WAITING_APPROVAL', session_id: null } }
    },
    snapshot(session) {
      return snapshotFromSession(session, [
        {
          id: 'pw-security-unsafe-gated',
          timestamp: Date.parse(fixtureTime(3)) / 1000,
          group: 'approval',
          label: 'Approval gate active',
          detail: 'No unsupported or unsafe action has executed.',
          state: 'waiting',
        },
      ])
    },
  },

  normalUseConversation: {
    name: 'normalUseConversation',
    description: 'Phase 13 realistic normal-use operator turns with deterministic final answers.',
    prompts: [...normalUsePromptSet, normalUsePlanModeFinalPrompt, normalUseLifecycleCompletedPrompt],
    onMessage(session, content) {
      const turn = normalUseTurnForPrompt(content)
      session.normal_use_current_turn = turn
      const turnId = addUserTurn(session, content || turn.prompt, `pw-turn-normal-use-${turn.key}`)
      session.normal_use_current_turn_id = turnId
    },
    onPlan(session) {
      const turn = currentNormalUseTurn(session)
      const ids = normalUseIds(session, turn)
      session.status = 'EXECUTING'
      session.operation_id = ids.planId
      session.plan = buildFactoryAgentPlan(session, {
        planId: ids.planId,
        objective: turn.plan,
        stepId: ids.stepId,
        toolName: turn.toolName,
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-created`,
          planId: ids.planId,
          content: turn.plan,
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: ids.planId } }
    },
    async onExecute(session, sleep) {
      const turn = currentNormalUseTurn(session)
      const ids = normalUseIds(session, turn)
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-execution-started`,
          planId: ids.planId,
        }),
      )
      await sleep(120)
      session.status = 'COMPLETED'
      completeSteps(session)
      appendTimeline(
        session,
        toolResultEvent({
          turnId: ids.turnId,
          eventId: `${ids.stepId}-tool-result`,
          stepId: ids.stepId,
          planId: ids.planId,
          toolName: turn.toolName,
          content: turn.answer,
          details: normalUseDetails(turn),
        }),
      )
      appendTimeline(
        session,
        sessionCompletedEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-completed`,
          planId: ids.planId,
          content: turn.answer,
          reason: 'normal_use_fixture',
          details: {
            ...(turn.sources ? { sources: turn.sources } : {}),
            ...(turn.safetyContent ? { safety_content: turn.safetyContent } : {}),
          },
        }),
      )
      return { status: 200, body: { status: 'COMPLETED', session_id: session.session_id } }
    },
    snapshot(session) {
      const turn = currentNormalUseTurn(session)
      if (session.status === 'COMPLETED') return snapshotFromSession(session, normalUseActivitySteps(turn))
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return activeHappyPathSnapshot(session)
      return defaultIdleSnapshot(session)
    },
  },

  intentEntityPromptBank: {
    name: 'intentEntityPromptBank',
    description: 'Phase 18 manual prompt bank routes LOTO machine prompt to deterministic RAG without clarification.',
    prompts: manualPromptBankPrompts,
    onMessage(session, content) {
      addUserTurn(session, content || manualPromptBankPrompts[0], 'pw-turn-intent-entity')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-intent-entity'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-intent-entity-rag'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-intent-entity-rag',
        objective: 'Route the M-CNC-01 LOTO procedure prompt to controlled RAG.',
        stepId: 'pw-step-intent-entity-rag',
        toolName: 'rag_loto_lookup',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-intent-entity-plan-created',
          planId: 'pw-plan-intent-entity-rag',
          content: 'Routing to LOTO/RAG with machine_id=M-CNC-01.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-intent-entity-rag' } }
    },
    async onExecute(session, sleep) {
      const turnId = session.current_turn_id || 'pw-turn-intent-entity'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-intent-entity-execution-started',
          planId: 'pw-plan-intent-entity-rag',
        }),
      )
      await sleep(140)
      session.status = 'COMPLETED'
      completeSteps(session)
      appendTimeline(
        session,
        toolResultEvent({
          turnId,
          eventId: 'pw-intent-entity-tool-result',
          stepId: 'pw-step-intent-entity-rag',
          planId: 'pw-plan-intent-entity-rag',
          toolName: 'rag_loto_lookup',
          content: phase18MockRagAnswer,
          details: {
            args: { route: 'rag_loto', machine_id: 'M-CNC-01' },
            result: {
              route: 'rag_loto',
              machine_id: 'M-CNC-01',
              _summary: phase18MockRagAnswer,
            },
            sources: [phase18MockRagSource],
            safety_content: {
              title: 'Safety Advisory',
              content: 'Controlled Phase 18 fixture. Verify the M-CNC-01 site procedure before acting.',
            },
          },
        }),
      )
      appendTimeline(
        session,
        sessionCompletedEvent({
          turnId,
          eventId: 'pw-intent-entity-completed',
          planId: 'pw-plan-intent-entity-rag',
          content: phase18MockRagAnswer,
          reason: 'intent_entity_prompt_bank_fixture',
          details: {
            sources: [phase18MockRagSource],
            safety_content: {
              title: 'Safety Advisory',
              content: 'Controlled Phase 18 fixture. Verify the M-CNC-01 site procedure before acting.',
            },
          },
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

  promptRegressionUnknown: {
    name: 'promptRegressionUnknown',
    description: 'Phase 19 true unknown prompt shows the generic Factory Agent attention diagnostic.',
    prompts: [phase19UnknownPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || phase19UnknownPrompt, 'pw-turn-prompt-regression-unknown')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-prompt-regression-unknown'
      session.status = 'FAILED'
      appendTimeline(
        session,
        sessionFailedEvent({
          turnId,
          content: phase19UnknownDiagnostic,
        }),
      )
      return {
        status: 422,
        body: { detail: phase19UnknownDiagnostic },
      }
    },
    async onExecute() {
      return { status: 409, body: { detail: 'Execution should not start for the unknown prompt fixture.' } }
    },
    snapshot(session) {
      return snapshotFromSession(session, [
        {
          id: 'pw-activity-prompt-regression-unknown',
          timestamp: Date.parse(fixtureTime(3)) / 1000,
          group: 'error',
          label: 'Prompt route not matched',
          detail: phase19UnknownDiagnostic,
          state: 'error',
        },
      ])
    },
  },

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

  malformedSseRecovery: {
    name: 'malformedSseRecovery',
    description: 'Malformed notification SSE payload is ignored before a later valid frame completes the run.',
    prompts: [malformedSsePrompt],
    onMessage(session, content) {
      addUserTurn(session, content || malformedSsePrompt, 'pw-turn-malformed-sse')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-malformed-sse'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-malformed-sse'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-malformed-sse',
        objective: 'Validate malformed SSE recovery behavior',
        stepId: 'pw-step-malformed-sse',
        toolName: 'get_machine_status',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-malformed-sse-plan-created',
          planId: 'pw-plan-malformed-sse',
          content: 'Waiting for a valid notification after a malformed SSE frame.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-malformed-sse' } }
    },
    async onExecute(session, sleep) {
      const turnId = session.current_turn_id || 'pw-turn-malformed-sse'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-malformed-sse-execution-started',
          planId: 'pw-plan-malformed-sse',
        }),
      )
      scheduleCompletion(session, sleep, {
        delayMs: 260,
        turnId,
        planId: 'pw-plan-malformed-sse',
        stepId: 'pw-step-malformed-sse',
        toolName: 'get_machine_status',
        answer: malformedSseAnswer,
        eventPrefix: 'pw-malformed-sse',
      })
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'COMPLETED') return snapshotFromSession(session, completedActivitySteps())
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return activeHappyPathSnapshot(session)
      return defaultIdleSnapshot(session)
    },
    notificationStream() {
      return malformedThenValidNotificationStream({ invalidationDelayMs: 620 })
    },
  },

  executeConflictRetry: {
    name: 'executeConflictRetry',
    description: 'First execute call returns 409, then the built-in retry completes normally.',
    prompts: [retryExecutePrompt],
    onMessage(session, content) {
      addUserTurn(session, content || retryExecutePrompt, 'pw-turn-execute-retry')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-execute-retry'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-execute-retry'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-execute-retry',
        objective: 'Retry execute after a temporary conflict',
        stepId: 'pw-step-execute-retry',
        toolName: 'get_machine_status',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-execute-retry-plan-created',
          planId: 'pw-plan-execute-retry',
          content: 'Preparing to retry if execution is already in progress.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-execute-retry' } }
    },
    async onExecute(session, sleep) {
      const turnId = session.current_turn_id || 'pw-turn-execute-retry'
      session.execute_count += 1
      session.status = 'EXECUTING'
      if (session.execute_count === 1) {
        appendTimeline(
          session,
          executionStartedEvent({
            turnId,
            eventId: 'pw-execute-retry-conflict-started',
            planId: 'pw-plan-execute-retry',
          }),
        )
        return { status: 409, body: { detail: 'Execution already in progress. Retry with the latest snapshot.' } }
      }

      await sleep(180)
      session.status = 'COMPLETED'
      completeSteps(session)
      appendTimeline(
        session,
        toolResultEvent({
          turnId,
          eventId: 'pw-execute-retry-tool-result',
          stepId: 'pw-step-execute-retry',
          planId: 'pw-plan-execute-retry',
          toolName: 'get_machine_status',
          content: retryExecuteAnswer,
          details: {
            args: { machine_id: 'M-CNC-01' },
            result: {
              machine_id: 'M-CNC-01',
              status: 'RUNNING',
              _summary: retryExecuteAnswer,
            },
          },
        }),
      )
      appendTimeline(
        session,
        sessionCompletedEvent({
          turnId,
          eventId: 'pw-execute-retry-completed',
          planId: 'pw-plan-execute-retry',
          content: retryExecuteAnswer,
          reason: 'execute_conflict_retry_fixture',
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

  nonTerminalActiveRun: {
    name: 'nonTerminalActiveRun',
    description: 'Session remains active and never emits a terminal answer within the test window.',
    prompts: [nonTerminalPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || nonTerminalPrompt, 'pw-turn-non-terminal')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-non-terminal'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-non-terminal'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-non-terminal',
        objective: 'Keep this session active without terminal completion',
        stepId: 'pw-step-non-terminal',
        toolName: 'long_running_check',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-non-terminal-plan-created',
          planId: 'pw-plan-non-terminal',
          content: 'The run is intentionally still active.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-non-terminal' } }
    },
    async onExecute(session) {
      const turnId = session.current_turn_id || 'pw-turn-non-terminal'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-non-terminal-execution-started',
          planId: 'pw-plan-non-terminal',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'FAILED') return snapshotFromSession(session)
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return activeHappyPathSnapshot(session)
      return defaultIdleSnapshot(session)
    },
    notificationStream() {
      return longRunningNotificationStream()
    },
  },

  cancellableActiveRun: {
    name: 'cancellableActiveRun',
    description: 'Active run stays cancellable until POST /cancel moves it to a non-busy state.',
    prompts: [cancelRunPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || cancelRunPrompt, 'pw-turn-cancellable-run')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-cancellable-run'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-cancellable-run'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-cancellable-run',
        objective: 'Keep this session active until cancellation',
        stepId: 'pw-step-cancellable-run',
        toolName: 'long_running_check',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-cancellable-run-plan-created',
          planId: 'pw-plan-cancellable-run',
          content: 'The run is active and can be cancelled.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-cancellable-run' } }
    },
    async onExecute(session) {
      const turnId = session.current_turn_id || 'pw-turn-cancellable-run'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-cancellable-run-execution-started',
          planId: 'pw-plan-cancellable-run',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'FAILED') return snapshotFromSession(session)
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return activeHappyPathSnapshot(session)
      return defaultIdleSnapshot(session)
    },
    notificationStream() {
      return longRunningNotificationStream()
    },
  },

  modalDisconnectActiveRun: {
    name: 'modalDisconnectActiveRun',
    description: 'Long-running stream stays open so closing the modal records EventSource disconnect.',
    prompts: [disconnectPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || disconnectPrompt, 'pw-turn-modal-disconnect')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-modal-disconnect'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-modal-disconnect'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-modal-disconnect',
        objective: 'Hold open the stream until the modal closes',
        stepId: 'pw-step-modal-disconnect',
        toolName: 'long_running_check',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-modal-disconnect-plan-created',
          planId: 'pw-plan-modal-disconnect',
          content: 'The stream should close when the chat modal unmounts.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-modal-disconnect' } }
    },
    async onExecute(session) {
      const turnId = session.current_turn_id || 'pw-turn-modal-disconnect'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-modal-disconnect-execution-started',
          planId: 'pw-plan-modal-disconnect',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return activeHappyPathSnapshot(session)
      return defaultIdleSnapshot(session)
    },
    notificationStream() {
      return longRunningNotificationStream()
    },
  },

  notificationStreamDrop: {
    name: 'notificationStreamDrop',
    description: 'Notification SSE closes unexpectedly and the UI shows polling fallback diagnostics.',
    prompts: [streamDropPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || streamDropPrompt, 'pw-turn-stream-drop')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-stream-drop'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-stream-drop'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-stream-drop',
        objective: 'Drop the notification stream while the run remains active',
        stepId: 'pw-step-stream-drop',
        toolName: 'long_running_check',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-stream-drop-plan-created',
          planId: 'pw-plan-stream-drop',
          content: 'The notification stream will close before completion.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-stream-drop' } }
    },
    async onExecute(session) {
      const turnId = session.current_turn_id || 'pw-turn-stream-drop'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-stream-drop-execution-started',
          planId: 'pw-plan-stream-drop',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return activeHappyPathSnapshot(session)
      return defaultIdleSnapshot(session)
    },
    notificationStream() {
      return disconnectingNotificationStream()
    },
  },
}

export function scenarioNames() {
  return Object.keys(scenarioCatalog)
}

export function mockTools() {
  return securityMockTools
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

export function createNormalUseHistorySession({
  sessionId,
  userId = 'frontend-operator',
  name,
  prompt,
  answer,
  updatedOffsetSeconds = 0,
  sources = [],
}) {
  const session = createFactoryAgentSession({
    sessionId,
    userId,
    name,
    scenarioName: 'normalUseConversation',
  })
  const timeOffset = 200 + Number(updatedOffsetSeconds || 0)
  const createdAt = fixtureTime(timeOffset)
  const updatedAt = fixtureTime(timeOffset + 5)
  const turn = {
    key: `history-${String(updatedOffsetSeconds).replace(/[^a-z0-9-]/gi, '-')}`,
    prompt,
    answer,
    plan: `Restoring historical transcript for ${name}.`,
    toolName: 'get_machine_status',
    args: { machine_id: 'M-CNC-01' },
    result: { machine_id: 'M-CNC-01', status: 'RUNNING', restored: true },
    sources,
  }
  const turnId = `${sessionId}-turn-1`
  const planId = `${sessionId}-plan-1`
  const stepId = `${sessionId}-step-1`

  session.status = 'COMPLETED'
  session.created_at = createdAt
  session.updated_at = updatedAt
  session.current_turn_id = turnId
  session.messages.push({
    id: `${sessionId}-message-1`,
    role: 'user',
    content: prompt,
    mode: 'normal',
    created_at: fixtureTime(timeOffset + 1),
  })
  session.plan = buildFactoryAgentPlan(session, {
    planId,
    objective: turn.plan,
    stepId,
    toolName: turn.toolName,
    status: 'COMPLETED',
  })
  session.steps = session.plan.steps.map((step) => ({
    ...step,
    status: 'DONE',
    updated_at: fixtureTime(timeOffset + 4),
  }))
  session.activity_steps = normalUseActivitySteps(turn)
  session.timeline.push(
    userMessageEvent({ turnId, content: prompt, offsetSeconds: timeOffset + 1 }),
    planCreatedEvent({
      turnId,
      eventId: `${sessionId}-plan-created`,
      planId,
      content: turn.plan,
      offsetSeconds: timeOffset + 2,
    }),
    executionStartedEvent({
      turnId,
      eventId: `${sessionId}-execution-started`,
      planId,
      offsetSeconds: timeOffset + 3,
    }),
    toolResultEvent({
      turnId,
      eventId: `${sessionId}-tool-result`,
      stepId,
      planId,
      toolName: turn.toolName,
      content: answer,
      details: normalUseDetails(turn),
      offsetSeconds: timeOffset + 4,
    }),
    sessionCompletedEvent({
      turnId,
      eventId: `${sessionId}-completed`,
      planId,
      content: answer,
      reason: 'normal_use_history_fixture',
      details: sources.length ? { sources } : {},
      offsetSeconds: timeOffset + 5,
    }),
  )
  return session
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
