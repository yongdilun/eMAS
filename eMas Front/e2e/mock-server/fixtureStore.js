import {
  activeHappyPathSnapshot,
  activeRetryFullNoisyStoryActivitySteps,
  activeRetryStoryActivitySteps,
  activityActiveRetryStoryPrompt,
  activityRetryCollapseHandoffPrompt,
  activitySseAnswer,
  activitySseApprovalNoPendingPrompt,
  activitySseApprovalResumePrompt,
  activitySseDelayedFallbackPrompt,
  activitySseGraphDuplicatePrompt,
  activitySsePrompt,
  activitySseResponseDocumentPrompt,
  activitySharedTimestampOrderPrompt,
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
  responseDocumentRendererPrompt,
  responseDocumentTrafficPrompt,
  planCreatedEvent,
  retryExecuteAnswer,
  retryExecutePrompt,
  sessionCompletedEvent,
  sessionFailedEvent,
  sharedTimestampActivitySteps,
  sessionSummary,
  snapshotFromSession,
  streamDropPrompt,
  typedKnowledgeSourcePrompt,
  typedPendingApprovalPrompt,
  typedRejectedPrompt,
  toolResultEvent,
  userMessageEvent,
} from '../fixtures/factoryAgentFixtures.js'
import {
  activeSnapshotRaceNotificationStream,
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
  approvalPayload,
  allNoOpDocument,
  cancelledDocument,
  cascadeDefinition,
  cascadeFinalDocument,
  cascadeWaitingDocument,
  closedApprovalDocument,
  collapsedResultsDocument,
  expandedParentPageOnlyDocument,
  jobStatusDocument,
  lotoDocument,
  lotoNotificationDocument,
  machineDetailsDocument,
  mixedOperationRagDocument,
  multiStatusDocument,
  oshaReenergizingDocument,
  sourcePdfLocatorDocument,
  textSearchPdfLocatorDocument,
  noResultsDocument,
  partialFailureDocument,
  partialNoOpApprovalPayload,
  partialNoOpDefinition,
  partialNoOpFinalDocument,
  partialNoOpWaitingDocument,
  readStatusDocument,
  rejectedDocument,
  responseDocumentAllNoOpPrompt,
  responseDocumentCancelledRunPrompt,
  responseDocumentCollapsedResultsPrompt,
  responseDocumentCascadePrompt,
  responseDocumentCompatibilityPrompt,
  responseDocumentExpiredApprovalPrompt,
  responseDocumentExpandedParentPageOnlyPrompt,
  responseDocumentJobStatusPrompt,
  responseDocumentLotoPrompt,
  responseDocumentLotoNotificationPrompt,
  responseDocumentMachineDetailsPrompt,
  responseDocumentMixedOperationRagPrompt,
  responseDocumentMultiStatusPrompt,
  responseDocumentOshaReenergizingPrompt,
  responseDocumentSourcePdfPrompt,
  responseDocumentTextSearchPdfPrompt,
  responseDocumentNoResultsPrompt,
  responseDocumentPartialNoOpPrompt,
  responseDocumentPartialFailurePrompt,
  responseDocumentReadStatusPrompt,
  responseDocumentRejectedApprovalPrompt,
  responseDocumentReverseCascadePrompt,
  responseDocumentStaleApprovalPrompt,
  responseDocumentTimeoutPrompt,
  responseDocumentZeroMatchApprovalPrompt,
  runningCancellableDocument,
  timeoutDocument,
  zeroMatchApprovalDefinition,
  zeroMatchApprovalPayload,
  zeroMatchApprovalWaitingDocument,
} from '../support/responseDocumentScenarios.js'
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
  reliabilityStartedTimeoutActivitySteps,
  reliabilityStartedTimeoutAnswer,
  reliabilityStartedTimeoutPrompt,
  reliabilitySlowActivitySteps,
  reliabilitySlowTimeoutPrompt,
  reliabilityTurnForPrompt,
} from '../support/reliabilityScenarios.js'
import {
  securityActivitySteps,
  securityLargeUnsafePrompt,
  securityMockTools,
  securitySafeOwnAnswer,
  securityUnsupportedDangerousPrompts,
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
  session.pending_stream_completion = null
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

function completeSession(session, {
  turnId,
  planId,
  stepId,
  toolName,
  answer,
  eventPrefix,
} = {}) {
  if (session.status === 'COMPLETED') return
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
}

function scheduleCompletion(session, sleep, { delayMs = 450, ...completion } = {}) {
  if (session.completion_scheduled) return
  session.completion_scheduled = true
  session.completion_promise = (async () => {
    await sleep(delayMs)
    completeSession(session, completion)
  })()
}

function completeAfterStream(session, completion) {
  if (session.completion_scheduled) return
  session.completion_scheduled = true
  session.pending_stream_completion = completion
}

function completePendingStream(session) {
  if (!session.pending_stream_completion) return
  const completion = session.pending_stream_completion
  session.pending_stream_completion = null
  completeSession(session, completion)
}

function responseDocumentTrafficRows(kind) {
  if (kind === 'high-to-low') {
    return [
      { job_id: 'JOB-SEED-001', previous_priority: 'high', new_priority: 'low' },
      { job_id: 'JOB-SEED-003', previous_priority: 'high', new_priority: 'low' },
      { job_id: 'JOB-SEED-006', previous_priority: 'high', new_priority: 'low' },
      { job_id: 'JOB-SEED-008', previous_priority: 'high', new_priority: 'low' },
    ]
  }
  return [
    { job_id: 'JOB-SEED-002', previous_priority: 'medium', new_priority: 'high' },
    { job_id: 'JOB-SEED-004', previous_priority: 'medium', new_priority: 'high' },
    { job_id: 'JOB-SEED-007', previous_priority: 'medium', new_priority: 'high' },
  ]
}

function responseDocumentTrafficPendingApproval(session) {
  const rows = responseDocumentTrafficRows('high-to-low')
  return {
    approval_id: 'pw-approval-response-document-traffic-2',
    session_id: session.session_id,
    subject_type: 'tool',
    tool_name: 'typed_priority_update',
    side_effect_level: 'HIGH',
    risk_summary: 'Update 11 jobs from high to low.',
    args: { bundle_ui: { rows } },
    status: 'PENDING',
    created_at: fixtureTime(4),
    expires_at: fixtureTime(300),
  }
}

function responseDocumentTrafficDocument(session, {
  revision,
  state = 'completed',
  message = 'Done. I updated 21 jobs across 2 approved business changes.',
  kind = 'completed',
} = {}) {
  const turnId = session.response_document_turn_id || session.current_turn_id || 'pw-turn-response-document-traffic'
  const documentId = `rd:${session.session_id}:${turnId}`
  const firstRows = responseDocumentTrafficRows('medium-to-high').map((row) => ({
    ...row,
    business_change: 'Medium -> High',
    change: 'medium -> high',
    status: 'updated',
  }))
  const secondRows = responseDocumentTrafficRows('high-to-low').map((row) => ({
    ...row,
    business_change: 'Original High -> Low',
    change: 'high -> low',
    status: 'updated',
  }))
  const waiting = state === 'waiting_approval'
  const failed = state === 'failed'
  const runSteps = waiting
    ? [
        { step_id: 'analysis-1', kind: 'analysis', state: 'completed', title: 'Understood request', summary: 'Parsed the two-step priority update.' },
        { step_id: 'mutation-1', kind: 'mutation', state: 'completed', title: 'Updated 10 jobs: medium to high', summary: 'First step remains complete.' },
        { step_id: 'approval-2', kind: 'approval', state: 'waiting', title: 'Waiting for approval 2', summary: '11 original high-priority jobs are ready for review.', current: true },
      ]
    : failed
      ? [
          { step_id: 'diagnostic-stale-failure', kind: 'diagnostic', state: 'failed', title: 'Stale failure', summary: message, current: true },
        ]
      : [
          { step_id: 'analysis-1', kind: 'analysis', state: 'completed', title: 'Understood request', summary: 'Parsed the two-step priority update.' },
          { step_id: 'approval-1', kind: 'approval', state: 'completed', title: 'Approval 1 received', summary: 'First approval was accepted.' },
          { step_id: 'mutation-1', kind: 'mutation', state: 'completed', title: 'Updated 10 jobs: medium to high', summary: 'Step 1: Updated 10 jobs from medium to high.' },
          { step_id: 'approval-2', kind: 'approval', state: 'completed', title: 'Approval 2 received', summary: 'Second approval was accepted.' },
          { step_id: 'mutation-2', kind: 'mutation', state: 'completed', title: 'Updated 11 jobs: high to low', summary: 'Step 2: Updated 11 jobs from high to low.' },
          { step_id: 'completed-1', kind: 'completed', state: 'completed', title: 'Run complete', summary: message },
        ]
  const blocks = waiting
    ? [
        { id: `activity:${documentId}`, type: 'run_activity', step_ids: runSteps.map((step) => step.step_id) },
        { id: 'message:traffic:waiting', type: 'short_message', message: 'Waiting for approval 2 before changing original high-priority jobs.', status: 'waiting_approval' },
        { id: 'completed-step:traffic:approval-1', type: 'completed_step', title: 'Completed step', summary: 'Updated 10 jobs from medium to high.', rows: firstRows },
        { id: 'approval:traffic:approval-2', type: 'approval_required', approval_id: 'pw-approval-response-document-traffic-2', title: 'Approval required', summary: 'Update 11 jobs from high to low', rows: secondRows },
      ]
    : failed
      ? [
          { id: `activity:${documentId}`, type: 'run_activity', step_ids: runSteps.map((step) => step.step_id) },
          { id: 'message:traffic:stale-failure', type: 'short_message', message, status: 'failed' },
          {
            id: 'diagnostic:traffic:stale-failure',
            type: 'diagnostic',
            severity: 'error',
            reason: 'stale_failure_fixture',
            title: 'Stale failure',
            user_message: message,
            technical_details: { fixture: 'stale_failure' },
          },
        ]
      : [
          { id: `activity:${documentId}`, type: 'run_activity', step_ids: runSteps.map((step) => step.step_id) },
          { id: 'message:traffic:completed', type: 'short_message', message, status: 'completed' },
          {
            id: 'result-summary:traffic',
            type: 'result_summary',
            summary: message,
            steps: [
              { step_number: 1, business_change: 'Medium -> High', summary: 'Medium -> High: 10 jobs', record_count: 10, status: 'completed' },
              { step_number: 2, business_change: 'Original High -> Low', summary: 'Original High -> Low: 11 jobs', record_count: 11, status: 'completed' },
            ],
            total_count: 21,
            status: 'completed',
          },
          {
            id: 'mutation:traffic',
            type: 'mutation_result',
            summary: message,
            rows: [...firstRows, ...secondRows],
            groups: [
              { business_change: 'Medium -> High', summary: 'Medium -> High: 10 jobs', record_count: 10, rows: firstRows },
              { business_change: 'Original High -> Low', summary: 'Original High -> Low: 11 jobs', record_count: 11, rows: secondRows },
            ],
            preview_limit: 5,
            details_collapsed: true,
            status: 'completed',
          },
        ]

  return {
    version: 1,
    id: documentId,
    document_id: documentId,
    turn_id: turnId,
    operation_id: 'pw-plan-response-document-traffic',
    revision,
    revision_source: kind === 'duplicate' ? 'mock_duplicate' : 'mock_event_storm',
    state,
    status: state,
    summary: message,
    message,
    current_step_id: waiting ? 'approval-2' : failed ? 'diagnostic-stale-failure' : 'completed-1',
    run_steps: runSteps,
    blocks,
    invariants: { fixture: 'response_document_revision_event_storm' },
    diagnostics: {},
  }
}

function responseDocumentTrafficInvalidDocument(session) {
  const turnId = session.response_document_turn_id || session.current_turn_id || 'pw-turn-response-document-traffic'
  return {
    version: 1,
    id: `rd:${session.session_id}:${turnId}`,
    document_id: `rd:${session.session_id}:${turnId}`,
    turn_id: turnId,
    operation_id: 'pw-plan-response-document-traffic',
    revision: 4,
    revision_source: 'mock_invalid_after_valid',
    state: 'completed',
    status: 'completed',
    run_steps: [],
  }
}

function responseDocumentTrafficSnapshot(session) {
  const count = Number(session.response_document_snapshot_count || 0) + 1
  session.response_document_snapshot_count = count
  const pendingApproval = responseDocumentTrafficPendingApproval(session)
  const completedRevisionFive = responseDocumentTrafficDocument(session, { revision: 5 })
  const variants = {
    1: {
      status: 'WAITING_APPROVAL',
      pending_approval: pendingApproval,
      response_document: responseDocumentTrafficDocument(session, {
        revision: 1,
        state: 'waiting_approval',
        message: 'Waiting for approval 2 before changing original high-priority jobs.',
      }),
    },
    2: {
      status: 'EXECUTING',
      pending_approval: null,
      response_document: completedRevisionFive,
    },
    3: {
      status: 'FAILED',
      pending_approval: null,
      response_document: responseDocumentTrafficDocument(session, {
        revision: 4,
        state: 'failed',
        message: 'Stale failure: database unavailable.',
      }),
    },
    4: {
      status: 'WAITING_APPROVAL',
      pending_approval: pendingApproval,
      response_document: responseDocumentTrafficDocument(session, {
        revision: 3,
        state: 'waiting_approval',
        message: 'Waiting for approval 2 before changing original high-priority jobs.',
      }),
    },
    5: {
      status: 'EXECUTING',
      pending_approval: null,
      response_document: responseDocumentTrafficInvalidDocument(session),
    },
    6: {
      status: 'EXECUTING',
      pending_approval: null,
      response_document: responseDocumentTrafficDocument(session, { revision: 5, kind: 'duplicate' }),
    },
  }
  const selected = variants[count] || {
    status: 'COMPLETED',
    pending_approval: null,
    response_document: responseDocumentTrafficDocument(session, { revision: 6 }),
  }
  if (selected.status === 'COMPLETED') {
    session.status = 'COMPLETED'
    session.pending_approval = null
  }
  const snapSession = {
    ...session,
    status: selected.status,
    updated_at: fixtureTime(20 + count),
    pending_approval: selected.pending_approval,
    response_document: selected.response_document,
  }
  return {
    ...snapshotFromSession(snapSession),
    snapshot_revision: selected.response_document?.revision ?? count,
    pending_approval: selected.pending_approval,
    response_document: selected.response_document,
  }
}

function responseDocumentTrafficNotificationStream() {
  return [
    { id: 1, event: 'notification', data: { type: 'hello', cursor: 1 } },
    ...[2, 3, 4, 5, 6, 7].map((id) => ({
      id,
      event: 'notification',
      delayMs: 120,
      data: {
        type: 'snapshot_invalidated',
        cursor: id,
        reason: 'response_document_revision_event_storm',
        session_status: id >= 7 ? 'COMPLETED' : 'EXECUTING',
      },
    })),
  ]
}

function defaultIdleSnapshot(session) {
  return snapshotFromSession(session)
}

function responseDocumentTurnPrefix(name) {
  return `pw-turn-${String(name || 'response-document').replace(/[^a-z0-9]+/gi, '-').toLowerCase()}`
}

function beginResponseDocumentTurn(session, content, name) {
  const turnId = addUserTurn(session, content, responseDocumentTurnPrefix(name))
  session.response_document_turn_id = turnId
  session.response_document_snapshot_count = 0
  session.response_document_revision_base = Number(session.messages?.length || 1) * 100
  return turnId
}

function installResponseDocumentPlan(session, { turnId, operationId, objective, toolName = 'response_document_fixture', status = 'EXECUTING' }) {
  session.status = status
  session.operation_id = operationId
  session.plan = buildFactoryAgentPlan(session, {
    planId: operationId,
    objective,
    stepId: `${operationId}-step`,
    toolName,
    status,
  })
  session.steps = [...session.plan.steps]
  appendTimeline(
    session,
    planCreatedEvent({
      turnId,
      eventId: `${operationId}-plan-created`,
      planId: operationId,
      content: objective,
      status,
    }),
  )
}

function appendResponseDocumentCompletion(session, { turnId, operationId, content, reason = 'response_document_quality_fixture' }) {
  appendTimeline(
    session,
    sessionCompletedEvent({
      turnId,
      eventId: `${operationId}-completed`,
      planId: operationId,
      content,
      reason,
      offsetSeconds: 6,
    }),
  )
}

function responseDocumentCompletionScenario({ name, prompt, operationId, objective, buildDocument, status = 'COMPLETED' }) {
  return {
    name,
    description: `Response document quality fixture for ${name}.`,
    prompts: [prompt],
    onMessage(session, content) {
      beginResponseDocumentTurn(session, content || prompt, name)
    },
    onPlan(session) {
      const turnId = session.response_document_turn_id || session.current_turn_id || responseDocumentTurnPrefix(name)
      installResponseDocumentPlan(session, { turnId, operationId, objective })
      return { status: 200, body: { status: 'EXECUTING', plan_id: operationId } }
    },
    async onExecute(session, sleep) {
      const turnId = session.response_document_turn_id || session.current_turn_id || responseDocumentTurnPrefix(name)
      session.execute_count += 1
      session.status = status
      completeSteps(session)
      await sleep(80)
      session.response_document = buildDocument(session)
      session.presentation = {
        kind: 'mutation_result',
        state: 'completed',
        summary: 'All requested changes completed.',
        rows: [{ job_id: 'JOB-STALE-PRESENTATION', priority: 'stale' }],
      }
      appendResponseDocumentCompletion(session, {
        turnId,
        operationId,
        content: session.response_document.message,
      })
      return { status: 200, body: { status, session_id: session.session_id } }
    },
    snapshot(session) {
      return snapshotFromSession(session)
    },
  }
}

function responseDocumentCascadeScenario(kind = 'forward') {
  const definition = cascadeDefinition(kind)
  const name = kind === 'reverse' ? 'responseDocumentReverseCascade' : 'responseDocumentCascade'
  return {
    name,
    description: 'Response document two-approval cascade fixture.',
    prompts: [definition.prompt],
    onMessage(session, content) {
      beginResponseDocumentTurn(session, content || definition.prompt, name)
      session.response_document_cascade_kind = kind
      session.response_document_cascade_phase = 'approval1'
    },
    onPlan(session) {
      const turnId = session.response_document_turn_id || session.current_turn_id || responseDocumentTurnPrefix(name)
      installResponseDocumentPlan(session, {
        turnId,
        operationId: definition.operationId,
        objective: 'Exercise response_document two-approval cascade quality.',
        status: 'PENDING_APPROVAL',
      })
      session.status = 'WAITING_APPROVAL'
      session.pending_approval = {
        ...approvalPayload(session, definition.first),
        created_at: fixtureTime(3),
        expires_at: fixtureTime(300),
      }
      session.response_document = cascadeWaitingDocument(session, definition, 1)
      appendTimeline(session, {
        event_id: `${definition.first.approvalId}-required`,
        turn_id: turnId,
        event_type: 'approval_required',
        approval_id: definition.first.approvalId,
        tool_name: 'typed_priority_update',
        content: `Update ${definition.first.rows.length} jobs from ${definition.first.source} to ${definition.first.target}`,
        status: 'PENDING',
        operation_id: definition.operationId,
        details: { args: session.pending_approval.args, side_effect_level: 'HIGH' },
        created_at: fixtureTime(3),
      })
      return { status: 200, body: { status: 'WAITING_APPROVAL', plan_id: definition.operationId } }
    },
    async onExecute() {
      return { status: 200, body: { status: 'WAITING_APPROVAL', session_id: null } }
    },
    onApprove(session, approvalId) {
      const turnId = session.response_document_turn_id || session.current_turn_id || responseDocumentTurnPrefix(name)
      if (approvalId === definition.first.approvalId) {
        appendTimeline(session, {
          event_id: `${definition.first.approvalId}-approved`,
          turn_id: turnId,
          event_type: 'approval_decided',
          approval_id: definition.first.approvalId,
          tool_name: 'typed_priority_update',
          content: 'Approval 1 received.',
          status: 'APPROVED',
          operation_id: definition.operationId,
          created_at: fixtureTime(4),
        })
        session.response_document_cascade_phase = 'approval2'
        session.status = 'WAITING_APPROVAL'
        session.pending_approval = {
          ...approvalPayload(session, definition.second),
          created_at: fixtureTime(5),
          expires_at: fixtureTime(300),
        }
        session.response_document = cascadeWaitingDocument(session, definition, 2)
        appendTimeline(session, {
          event_id: `${definition.second.approvalId}-required`,
          turn_id: turnId,
          event_type: 'approval_required',
          approval_id: definition.second.approvalId,
          tool_name: 'typed_priority_update',
          content: `Update ${definition.second.rows.length} jobs from ${definition.second.source} to ${definition.second.target}`,
          status: 'PENDING',
          operation_id: definition.operationId,
          details: { args: session.pending_approval.args, side_effect_level: 'HIGH' },
          created_at: fixtureTime(5),
        })
        return { status: 200, body: { status: 'WAITING_APPROVAL', approval_id: approvalId } }
      }
      if (approvalId === definition.second.approvalId) {
        appendTimeline(session, {
          event_id: `${definition.second.approvalId}-approved`,
          turn_id: turnId,
          event_type: 'approval_decided',
          approval_id: definition.second.approvalId,
          tool_name: 'typed_priority_update',
          content: 'Approval 2 received.',
          status: 'APPROVED',
          operation_id: definition.operationId,
          created_at: fixtureTime(6),
        })
        session.response_document_cascade_phase = 'completed'
        session.status = 'COMPLETED'
        session.pending_approval = null
        completeSteps(session)
        session.response_document = cascadeFinalDocument(session, definition)
        appendResponseDocumentCompletion(session, {
          turnId,
          operationId: definition.operationId,
          content: definition.finalMessage,
        })
        return { status: 200, body: { status: 'COMPLETED', approval_id: approvalId } }
      }
      return { status: 404, body: { detail: 'Approval not found for response_document cascade.' } }
    },
    snapshot(session) {
      if (session.response_document_cascade_phase === 'approval1') {
        session.response_document_snapshot_count = Math.min(Number(session.response_document_snapshot_count || 0) + 1, 2)
        session.response_document = cascadeWaitingDocument(session, definition, 1)
      }
      return snapshotFromSession(session)
    },
  }
}

function responseDocumentPartialNoOpScenario() {
  const definition = partialNoOpDefinition()
  return {
    name: 'responseDocumentPartialNoOp',
    description: 'Response document partial no-op plus valid mutation fixture.',
    prompts: [responseDocumentPartialNoOpPrompt],
    onMessage(session, content) {
      beginResponseDocumentTurn(session, content || responseDocumentPartialNoOpPrompt, 'responseDocumentPartialNoOp')
      session.response_document_partial_noop_phase = 'approval'
    },
    onPlan(session) {
      const turnId = session.response_document_turn_id || session.current_turn_id || responseDocumentTurnPrefix('responseDocumentPartialNoOp')
      installResponseDocumentPlan(session, {
        turnId,
        operationId: definition.operationId,
        objective: 'Exercise response_document no-op mutation quality.',
        status: 'PENDING_APPROVAL',
      })
      session.status = 'WAITING_APPROVAL'
      session.pending_approval = {
        ...partialNoOpApprovalPayload(session, definition),
        created_at: fixtureTime(3),
        expires_at: fixtureTime(300),
      }
      session.response_document = partialNoOpWaitingDocument(session, definition)
      appendTimeline(session, {
        event_id: `${definition.approvalId}-required`,
        turn_id: turnId,
        event_type: 'approval_required',
        approval_id: definition.approvalId,
        tool_name: 'typed_priority_update',
        content: 'Update 3 jobs from high to low',
        status: 'PENDING',
        operation_id: definition.operationId,
        details: { args: session.pending_approval.args, side_effect_level: 'HIGH' },
        created_at: fixtureTime(3),
      })
      return { status: 200, body: { status: 'WAITING_APPROVAL', plan_id: definition.operationId } }
    },
    async onExecute() {
      return { status: 200, body: { status: 'WAITING_APPROVAL', session_id: null } }
    },
    onApprove(session, approvalId) {
      if (approvalId !== definition.approvalId) {
        return { status: 404, body: { detail: 'Approval not found for response_document partial no-op.' } }
      }
      const turnId = session.response_document_turn_id || session.current_turn_id || responseDocumentTurnPrefix('responseDocumentPartialNoOp')
      appendTimeline(session, {
        event_id: `${definition.approvalId}-approved`,
        turn_id: turnId,
        event_type: 'approval_decided',
        approval_id: definition.approvalId,
        tool_name: 'typed_priority_update',
        content: 'Approval 1 received.',
        status: 'APPROVED',
        operation_id: definition.operationId,
        created_at: fixtureTime(4),
      })
      session.response_document_partial_noop_phase = 'completed'
      session.status = 'COMPLETED'
      session.pending_approval = null
      completeSteps(session)
      session.response_document = partialNoOpFinalDocument(session, definition)
      appendResponseDocumentCompletion(session, {
        turnId,
        operationId: definition.operationId,
        content: definition.finalMessage,
      })
      return { status: 200, body: { status: 'COMPLETED', approval_id: approvalId } }
    },
    snapshot(session) {
      if (session.response_document_partial_noop_phase === 'approval') {
        session.response_document = partialNoOpWaitingDocument(session, definition)
      }
      return snapshotFromSession(session)
    },
  }
}

function responseDocumentZeroMatchApprovalScenario() {
  const definition = zeroMatchApprovalDefinition()
  return {
    name: 'responseDocumentZeroMatchApproval',
    description: 'Response document zero-match first business change with active medium-to-high approval fixture.',
    prompts: [responseDocumentZeroMatchApprovalPrompt],
    onMessage(session, content) {
      beginResponseDocumentTurn(session, content || responseDocumentZeroMatchApprovalPrompt, 'responseDocumentZeroMatchApproval')
      session.response_document_zero_match_phase = 'approval'
    },
    onPlan(session) {
      const turnId = session.response_document_turn_id || session.current_turn_id || responseDocumentTurnPrefix('responseDocumentZeroMatchApproval')
      installResponseDocumentPlan(session, {
        turnId,
        operationId: definition.operationId,
        objective: 'Exercise response_document zero-match active approval quality.',
        status: 'PENDING_APPROVAL',
      })
      session.status = 'WAITING_APPROVAL'
      session.pending_approval = {
        ...zeroMatchApprovalPayload(session, definition),
        created_at: fixtureTime(3),
        expires_at: fixtureTime(300),
      }
      session.response_document = zeroMatchApprovalWaitingDocument(session, definition)
      appendTimeline(session, {
        event_id: `${definition.approvalId}-required`,
        turn_id: turnId,
        event_type: 'approval_required',
        approval_id: definition.approvalId,
        tool_name: 'typed_priority_update',
        content: '2 jobs will be updated from medium to high priority.',
        status: 'PENDING',
        operation_id: definition.operationId,
        details: { args: session.pending_approval.args, side_effect_level: 'HIGH' },
        created_at: fixtureTime(3),
      })
      return { status: 200, body: { status: 'WAITING_APPROVAL', plan_id: definition.operationId } }
    },
    async onExecute() {
      return { status: 200, body: { status: 'WAITING_APPROVAL', session_id: null } }
    },
    snapshot(session) {
      if (session.response_document_zero_match_phase === 'approval') {
        session.response_document = zeroMatchApprovalWaitingDocument(session, definition)
      }
      return snapshotFromSession(session)
    },
  }
}

function responseDocumentRejectedScenario() {
  const baseDefinition = cascadeDefinition('forward')
  const definition = {
    ...baseDefinition,
    operationId: 'pw-plan-rd-rejected',
    second: {
      ...baseDefinition.second,
      approvalId: 'pw-rd-rejected-approval-2',
    },
  }
  return {
    name: 'responseDocumentRejectedApproval',
    description: 'Response document rejected approval fixture.',
    prompts: [responseDocumentRejectedApprovalPrompt],
    onMessage(session, content) {
      beginResponseDocumentTurn(session, content || responseDocumentRejectedApprovalPrompt, 'responseDocumentRejectedApproval')
    },
    onPlan(session) {
      const turnId = session.response_document_turn_id || session.current_turn_id || 'pw-turn-response-document-rejected'
      installResponseDocumentPlan(session, {
        turnId,
        operationId: 'pw-plan-rd-rejected',
        objective: 'Render response_document rejected approval quality fixture.',
        status: 'PENDING_APPROVAL',
      })
      session.status = 'WAITING_APPROVAL'
      session.pending_approval = {
        ...approvalPayload(session, definition.second),
        created_at: fixtureTime(5),
        expires_at: fixtureTime(300),
      }
      session.response_document = cascadeWaitingDocument(session, definition, 2)
      session.response_document = {
        ...session.response_document,
        revision: 5,
        operation_id: 'pw-plan-rd-rejected',
      }
      return { status: 200, body: { status: 'WAITING_APPROVAL', plan_id: 'pw-plan-rd-rejected' } }
    },
    async onExecute() {
      return { status: 200, body: { status: 'WAITING_APPROVAL', session_id: null } }
    },
    onReject(session, approvalId) {
      session.status = 'FAILED'
      session.pending_approval = null
      session.response_document = rejectedDocument(session, definition)
      appendTimeline(session, {
        event_id: `${approvalId}-rejected`,
        turn_id: session.response_document_turn_id || session.current_turn_id,
        event_type: 'approval_decided',
        approval_id: approvalId,
        tool_name: 'typed_priority_update',
        content: 'Approval 2 rejected.',
        status: 'REJECTED',
        operation_id: 'pw-plan-rd-rejected',
        created_at: fixtureTime(7),
      })
      return { status: 200, body: { status: 'REJECTED', approval_id: approvalId } }
    },
    snapshot(session) {
      return snapshotFromSession(session)
    },
  }
}

function responseDocumentCancelledScenario() {
  return {
    name: 'responseDocumentCancelledRun',
    description: 'Response document cancelled run fixture.',
    prompts: [responseDocumentCancelledRunPrompt],
    onMessage(session, content) {
      beginResponseDocumentTurn(session, content || responseDocumentCancelledRunPrompt, 'responseDocumentCancelledRun')
    },
    onPlan(session) {
      const turnId = session.response_document_turn_id || session.current_turn_id || 'pw-turn-response-document-cancelled'
      installResponseDocumentPlan(session, {
        turnId,
        operationId: 'pw-plan-rd-cancellable',
        objective: 'Keep response_document run active until cancellation.',
      })
      session.response_document = runningCancellableDocument(session)
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-rd-cancellable' } }
    },
    async onExecute(session) {
      session.execute_count += 1
      session.status = 'EXECUTING'
      session.response_document = runningCancellableDocument(session)
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    onCancel(session) {
      session.status = 'FAILED'
      session.pending_approval = null
      session.response_document = cancelledDocument(session)
      return { status: 200, body: { status: 'FAILED', session_id: session.session_id } }
    },
    snapshot(session) {
      return snapshotFromSession(session)
    },
    notificationStream() {
      return longRunningNotificationStream()
    },
  }
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
  responseDocumentCascade: responseDocumentCascadeScenario('forward'),

  responseDocumentReverseCascade: responseDocumentCascadeScenario('reverse'),

  responseDocumentPartialNoOp: responseDocumentPartialNoOpScenario(),

  responseDocumentZeroMatchApproval: responseDocumentZeroMatchApprovalScenario(),

  responseDocumentAllNoOp: responseDocumentCompletionScenario({
    name: 'responseDocumentAllNoOp',
    prompt: responseDocumentAllNoOpPrompt,
    operationId: 'pw-plan-rd-all-noop',
    objective: 'Render response_document all-no-op mutation.',
    buildDocument: allNoOpDocument,
  }),

  responseDocumentReadStatus: responseDocumentCompletionScenario({
    name: 'responseDocumentReadStatus',
    prompt: responseDocumentReadStatusPrompt,
    operationId: 'pw-plan-rd-read-status',
    objective: 'Render response_document read-only machine status.',
    buildDocument: readStatusDocument,
  }),

  responseDocumentJobStatus: responseDocumentCompletionScenario({
    name: 'responseDocumentJobStatus',
    prompt: responseDocumentJobStatusPrompt,
    operationId: 'pw-plan-rd-job-status',
    objective: 'Render response_document read-only job status.',
    buildDocument: jobStatusDocument,
  }),

  responseDocumentMultiStatus: responseDocumentCompletionScenario({
    name: 'responseDocumentMultiStatus',
    prompt: responseDocumentMultiStatusPrompt,
    operationId: 'pw-plan-rd-multi-status',
    objective: 'Render response_document multi-status collection.',
    buildDocument: multiStatusDocument,
  }),

  responseDocumentMachineDetails: responseDocumentCompletionScenario({
    name: 'responseDocumentMachineDetails',
    prompt: responseDocumentMachineDetailsPrompt,
    operationId: 'pw-plan-rd-machine-details',
    objective: 'Render response_document machine details policy.',
    buildDocument: machineDetailsDocument,
  }),

  responseDocumentCollapsedResults: responseDocumentCompletionScenario({
    name: 'responseDocumentCollapsedResults',
    prompt: responseDocumentCollapsedResultsPrompt,
    operationId: 'pw-plan-rd-collapsed-results',
    objective: 'Render response_document collapsed filtered results policy.',
    buildDocument: collapsedResultsDocument,
  }),

  responseDocumentLoto: responseDocumentCompletionScenario({
    name: 'responseDocumentLoto',
    prompt: responseDocumentLotoPrompt,
    operationId: 'pw-plan-rd-loto',
    objective: 'Render response_document sourced LOTO answer.',
    buildDocument: lotoDocument,
  }),

  responseDocumentOshaReenergizing: responseDocumentCompletionScenario({
    name: 'responseDocumentOshaReenergizing',
    prompt: responseDocumentOshaReenergizingPrompt,
    operationId: 'pw-plan-rd-osha-reenergizing',
    objective: 'Render Phase 32 positive OSHA PDF-backed RAG proof.',
    buildDocument: oshaReenergizingDocument,
  }),

  responseDocumentLotoNotification: responseDocumentCompletionScenario({
    name: 'responseDocumentLotoNotification',
    prompt: responseDocumentLotoNotificationPrompt,
    operationId: 'pw-plan-rd-loto-notification',
    objective: 'Render response_document document-content LOTO notification answer.',
    buildDocument: lotoNotificationDocument,
  }),

  responseDocumentMixedOperationRag: responseDocumentCompletionScenario({
    name: 'responseDocumentMixedOperationRag',
    prompt: responseDocumentMixedOperationRagPrompt,
    operationId: 'pw-plan-rd-mixed-operation-rag',
    objective: 'Render response_document mixed operation and RAG sections.',
    buildDocument: mixedOperationRagDocument,
  }),

  responseDocumentSourcePdfLocator: responseDocumentCompletionScenario({
    name: 'responseDocumentSourcePdfLocator',
    prompt: responseDocumentSourcePdfPrompt,
    operationId: 'pw-plan-rd-source-pdf',
    objective: 'Render response_document source PDF locator and highlight evidence.',
    buildDocument: sourcePdfLocatorDocument,
  }),

  responseDocumentTextSearchPdfLocator: responseDocumentCompletionScenario({
    name: 'responseDocumentTextSearchPdfLocator',
    prompt: responseDocumentTextSearchPdfPrompt,
    operationId: 'pw-plan-rd-text-search-pdf',
    objective: 'Render response_document source PDF text-search locator and highlight evidence.',
    buildDocument: textSearchPdfLocatorDocument,
  }),

  responseDocumentExpandedParentPageOnly: responseDocumentCompletionScenario({
    name: 'responseDocumentExpandedParentPageOnly',
    prompt: responseDocumentExpandedParentPageOnlyPrompt,
    operationId: 'pw-plan-rd-expanded-parent-page-only',
    objective: 'Render response_document expanded parent PDF source as page-only.',
    buildDocument: expandedParentPageOnlyDocument,
  }),

  responseDocumentNoResults: responseDocumentCompletionScenario({
    name: 'responseDocumentNoResults',
    prompt: responseDocumentNoResultsPrompt,
    operationId: 'pw-plan-rd-no-results',
    objective: 'Render response_document no-results diagnostic.',
    buildDocument: noResultsDocument,
  }),

  responseDocumentPartialFailure: responseDocumentCompletionScenario({
    name: 'responseDocumentPartialFailure',
    prompt: responseDocumentPartialFailurePrompt,
    operationId: 'pw-plan-rd-partial-failure',
    objective: 'Render response_document partial failure.',
    buildDocument: partialFailureDocument,
    status: 'FAILED',
  }),

  responseDocumentTimeoutFailure: responseDocumentCompletionScenario({
    name: 'responseDocumentTimeoutFailure',
    prompt: responseDocumentTimeoutPrompt,
    operationId: 'pw-plan-rd-timeout',
    objective: 'Render response_document planner timeout diagnostic.',
    buildDocument: timeoutDocument,
    status: 'FAILED',
  }),

  responseDocumentRejectedApproval: responseDocumentRejectedScenario(),

  responseDocumentExpiredApproval: responseDocumentCompletionScenario({
    name: 'responseDocumentExpiredApproval',
    prompt: responseDocumentExpiredApprovalPrompt,
    operationId: 'pw-plan-rd-expired',
    objective: 'Render response_document expired approval diagnostic.',
    buildDocument: (session) => closedApprovalDocument(session, 'approval_expired'),
    status: 'FAILED',
  }),

  responseDocumentStaleApproval: responseDocumentCompletionScenario({
    name: 'responseDocumentStaleApproval',
    prompt: responseDocumentStaleApprovalPrompt,
    operationId: 'pw-plan-rd-stale',
    objective: 'Render response_document stale approval diagnostic.',
    buildDocument: (session) => closedApprovalDocument(session, 'approval_stale'),
    status: 'FAILED',
  }),

  responseDocumentCancelledRun: responseDocumentCancelledScenario(),

  responseDocumentCompatibility: responseDocumentCompletionScenario({
    name: 'responseDocumentCompatibility',
    prompt: responseDocumentCompatibilityPrompt,
    operationId: 'pw-plan-rd-compatibility',
    objective: 'Render valid response_document while stale presentation is present.',
    buildDocument: readStatusDocument,
  }),

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

  reliabilityStartedExecutionTimeout: {
    name: 'reliabilityStartedExecutionTimeout',
    description: 'Started execution can outlive a client timeout without showing startup-failure UX.',
    prompts: [reliabilityStartedTimeoutPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || reliabilityStartedTimeoutPrompt, 'pw-turn-reliability-started-timeout')
    },
    onPlan(session) {
      const ids = reliabilityIds(session, 'started-timeout')
      session.status = 'EXECUTING'
      session.operation_id = ids.planId
      session.plan = buildFactoryAgentPlan(session, {
        planId: ids.planId,
        objective: 'Execution starts and finishes even when the client request times out.',
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
          content: 'The run has enough structure to start execution.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: ids.planId } }
    },
    async onExecute(session, sleep) {
      const ids = reliabilityIds(session, 'started-timeout')
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
        toolResultEvent({
          turnId: ids.turnId,
          eventId: `${ids.planId}-tool-result`,
          stepId: ids.stepId,
          planId: ids.planId,
          toolName: 'slow_reliability_tool',
          content: reliabilityStartedTimeoutAnswer,
          details: {
            result: {
              status: 'completed',
              _summary: reliabilityStartedTimeoutAnswer,
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
          content: reliabilityStartedTimeoutAnswer,
          reason: 'reliability_started_timeout_fixture',
        }),
      )
      return { status: 200, body: { status: 'COMPLETED', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'COMPLETED') {
        return snapshotFromSession(session, reliabilityStartedTimeoutActivitySteps({ terminal: true }))
      }
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') {
        return snapshotFromSession(session, reliabilityStartedTimeoutActivitySteps())
      }
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
    prompts: [securityUnsafeActionPrompt, ...securityUnsupportedDangerousPrompts],
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

  typedPresentationPendingApproval: {
    name: 'typedPresentationPendingApproval',
    description: 'Phase 7 typed pending approval renders without approval phrase matching.',
    prompts: [typedPendingApprovalPrompt],
    onMessage(session, content) {
      const turnId = addUserTurn(session, content || typedPendingApprovalPrompt, 'pw-turn-typed-pending')
      session.typed_pending_turn_id = turnId
    },
    onPlan(session) {
      const turnId = session.typed_pending_turn_id || session.current_turn_id || 'pw-turn-typed-pending'
      session.status = 'WAITING_APPROVAL'
      session.operation_id = 'pw-plan-typed-pending'
      session.presentation = {
        kind: 'approval_required',
        state: 'pending',
        operation_id: 'pw-plan-typed-pending',
        approval_id: 'pw-approval-typed-pending',
        summary: 'Review the proposed priority update batch.',
        rows: [
          { job_id: 'JOB-SEED-005', previous_priority: 'low', new_priority: 'high', outcome: 'pending' },
        ],
      }
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-typed-pending',
        objective: 'Typed pending approval fixture.',
        stepId: 'pw-step-typed-pending',
        toolName: 'typed_priority_update',
        status: 'PENDING_APPROVAL',
      })
      session.steps = session.plan.steps.map((step) => ({ ...step, status: 'WAITING_APPROVAL' }))
      session.pending_approval = {
        approval_id: 'pw-approval-typed-pending',
        session_id: session.session_id,
        subject_type: 'tool',
        tool_name: 'typed_priority_update',
        side_effect_level: 'HIGH',
        risk_summary: 'Operator review required for one low-priority job.',
        args: { job_id: 'JOB-SEED-005', priority: 'high' },
        status: 'PENDING',
        created_at: fixtureTime(3),
        expires_at: fixtureTime(300),
      }
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-typed-pending-plan-created',
          planId: 'pw-plan-typed-pending',
          content: 'Preparing a typed approval contract.',
          status: 'PENDING_APPROVAL',
        }),
      )
      appendTimeline(session, {
        event_id: 'pw-typed-pending-approval-required',
        turn_id: turnId,
        event_type: 'approval_required',
        approval_id: session.pending_approval.approval_id,
        tool_name: session.pending_approval.tool_name,
        content: 'Operator review required for one low-priority job.',
        status: 'PENDING',
        operation_id: 'pw-plan-typed-pending',
        details: {
          args: session.pending_approval.args,
          side_effect_level: session.pending_approval.side_effect_level,
        },
        presentation: session.presentation,
        created_at: fixtureTime(3),
      })
      appendTimeline(
        session,
        sessionCompletedEvent({
          turnId,
          eventId: 'pw-typed-pending-stale-completed',
          planId: 'pw-plan-typed-pending',
          content: 'All requested changes completed.',
          reason: 'stale_success_detail',
          offsetSeconds: 4,
        }),
      )
      return { status: 200, body: { status: 'WAITING_APPROVAL', plan_id: 'pw-plan-typed-pending' } }
    },
    async onExecute() {
      return { status: 200, body: { status: 'WAITING_APPROVAL', session_id: null } }
    },
    snapshot(session) {
      return snapshotFromSession(session)
    },
  },

  responseDocumentApprovalPending: {
    name: 'responseDocumentApprovalPending',
    description: 'Phase 4 response_document renderer preserves completed evidence while latest approval is pending.',
    prompts: [responseDocumentRendererPrompt],
    onMessage(session, content) {
      const turnId = addUserTurn(session, content || responseDocumentRendererPrompt, 'pw-turn-response-document')
      session.response_document_turn_id = turnId
    },
    onPlan(session) {
      const turnId = session.response_document_turn_id || session.current_turn_id || 'pw-turn-response-document'
      const operationId = 'pw-plan-response-document'
      session.status = 'WAITING_APPROVAL'
      session.operation_id = operationId
      session.presentation = {
        kind: 'mutation_result',
        state: 'completed',
        operation_id: operationId,
        summary: 'All requested changes completed.',
        rows: [{ job_id: 'JOB-STALE-001', priority: 'low' }],
      }
      session.plan = buildFactoryAgentPlan(session, {
        planId: operationId,
        objective: 'Render response document approval fixture.',
        stepId: 'pw-step-response-document',
        toolName: 'typed_priority_update',
        status: 'PENDING_APPROVAL',
      })
      session.steps = session.plan.steps.map((step) => ({ ...step, status: 'DONE' }))
      const pendingRows = [
        { job_id: 'JOB-SEED-001', previous_priority: 'high', new_priority: 'low' },
        { job_id: 'JOB-SEED-003', previous_priority: 'high', new_priority: 'low' },
        { job_id: 'JOB-SEED-006', previous_priority: 'high', new_priority: 'low' },
        { job_id: 'JOB-SEED-008', previous_priority: 'high', new_priority: 'low' },
        { job_id: 'JOB-SEED-011', previous_priority: 'high', new_priority: 'low' },
        { job_id: 'JOB-SEED-014', previous_priority: 'high', new_priority: 'low' },
      ]
      session.pending_approval = {
        approval_id: 'pw-approval-response-document-2',
        session_id: session.session_id,
        subject_type: 'tool',
        tool_name: 'typed_priority_update',
        side_effect_level: 'HIGH',
        risk_summary: 'Update 11 jobs from high to low.',
        args: { bundle_ui: { rows: pendingRows } },
        status: 'PENDING',
        created_at: fixtureTime(4),
        expires_at: fixtureTime(300),
      }
      session.response_document = {
        version: 1,
        id: `rd:${session.session_id}:${turnId}`,
        document_id: `rd:${session.session_id}:${turnId}`,
        turn_id: turnId,
        operation_id: operationId,
        revision: 4,
        revision_source: 'mock_fixture',
        state: 'waiting_approval',
        status: 'waiting_approval',
        summary: 'Done. Updated 10 jobs from medium to high. Please review approval 2 before I update original high-priority jobs.',
        message: 'Done. Updated 10 jobs from medium to high. Please review approval 2 before I update original high-priority jobs.',
        current_step_id: 'approval-2',
        run_steps: [
          { step_id: 'analysis-1', kind: 'analysis', state: 'completed', title: 'Understood request', summary: 'Parsed the two-step priority update.' },
          { step_id: 'approval-1', kind: 'approval', state: 'completed', title: 'Approval 1 received', summary: 'The first approval was accepted.' },
          { step_id: 'mutation-1', kind: 'mutation', state: 'completed', title: 'Updated 10 jobs: medium -> high', summary: 'First-step result remains visible.' },
          { step_id: 'approval-2', kind: 'approval', state: 'waiting', title: 'Waiting for approval 2', summary: '11 original high-priority jobs are ready for review.', current: true },
        ],
        blocks: [
          { id: 'activity:response-document', type: 'run_activity', step_ids: ['analysis-1', 'approval-1', 'mutation-1', 'approval-2'] },
          {
            id: 'message:approval-2',
            type: 'short_message',
            message: 'Done. Updated 10 jobs from medium to high. Please review approval 2 before I update original high-priority jobs.',
            status: 'waiting_approval',
          },
          {
            id: 'completed-step:approval-1',
            type: 'completed_step',
            approval_id: 'pw-approval-response-document-1',
            title: 'Completed step',
            summary: 'Updated 10 jobs from medium to high.',
            rows: [{ job_id: 'JOB-SEED-002', previous_priority: 'medium', new_priority: 'high' }],
          },
          {
            id: 'approval:approval-2',
            type: 'approval_required',
            approval_id: 'pw-approval-response-document-2',
            title: 'Approval required',
            summary: 'Update 11 jobs from high to low',
            rows: pendingRows,
            details_collapsed: true,
          },
        ],
        invariants: { full_success_forbidden: true },
        diagnostics: {},
      }
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-response-document-plan-created',
          planId: operationId,
          content: 'Preparing response document approval fixture.',
          status: 'PENDING_APPROVAL',
        }),
      )
      appendTimeline(session, {
        event_id: 'pw-response-document-approval-required',
        turn_id: turnId,
        event_type: 'approval_required',
        approval_id: session.pending_approval.approval_id,
        tool_name: session.pending_approval.tool_name,
        content: 'Update 11 jobs from high to low',
        status: 'PENDING',
        operation_id: operationId,
        details: {
          args: session.pending_approval.args,
          side_effect_level: session.pending_approval.side_effect_level,
        },
        created_at: fixtureTime(4),
      })
      return { status: 200, body: { status: 'WAITING_APPROVAL', plan_id: operationId } }
    },
    async onExecute() {
      return { status: 200, body: { status: 'WAITING_APPROVAL', session_id: null } }
    },
    snapshot(session) {
      return snapshotFromSession(session)
    },
  },

  responseDocumentRevisionEventStorm: {
    name: 'responseDocumentRevisionEventStorm',
    description: 'Phase 5 response_document revision event storm with stale, invalid, duplicate, SSE, and polling snapshots.',
    prompts: [responseDocumentTrafficPrompt],
    onMessage(session, content) {
      const turnId = addUserTurn(session, content || responseDocumentTrafficPrompt, 'pw-turn-response-document-traffic')
      session.response_document_turn_id = turnId
      session.response_document_snapshot_count = 0
    },
    onPlan(session) {
      const turnId = session.response_document_turn_id || session.current_turn_id || 'pw-turn-response-document-traffic'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-response-document-traffic'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-response-document-traffic',
        objective: 'Exercise response_document revision ordering under busy traffic.',
        stepId: 'pw-step-response-document-traffic',
        toolName: 'typed_priority_update',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-response-document-traffic-plan-created',
          planId: 'pw-plan-response-document-traffic',
          content: 'Starting response_document revision event storm fixture.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-response-document-traffic' } }
    },
    async onExecute(session, sleep) {
      const turnId = session.response_document_turn_id || session.current_turn_id || 'pw-turn-response-document-traffic'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-response-document-traffic-execution-started',
          planId: 'pw-plan-response-document-traffic',
        }),
      )
      await sleep(40)
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      return responseDocumentTrafficSnapshot(session)
    },
    notificationStream() {
      return responseDocumentTrafficNotificationStream()
    },
  },

  typedPresentationRejectedStaleSuccess: {
    name: 'typedPresentationRejectedStaleSuccess',
    description: 'Phase 7 typed rejected state suppresses stale success details.',
    prompts: [typedRejectedPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || typedRejectedPrompt, 'pw-turn-typed-rejected')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-typed-rejected'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-typed-rejected'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-typed-rejected',
        objective: 'Render typed rejected presentation.',
        stepId: 'pw-step-typed-rejected',
        toolName: 'typed_rejected_fixture',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-typed-rejected-plan-created',
          planId: 'pw-plan-typed-rejected',
          content: 'Checking typed rejected state.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-typed-rejected' } }
    },
    async onExecute(session, sleep) {
      const turnId = session.current_turn_id || 'pw-turn-typed-rejected'
      await sleep(120)
      session.status = 'FAILED'
      completeSteps(session)
      session.presentation = {
        kind: 'rejected',
        state: 'rejected',
        operation_id: 'pw-plan-typed-rejected',
        approval_id: 'pw-approval-typed-rejected',
        summary: 'Operator rejected the requested priority update.',
        diagnostics: { reason: 'operator_rejected' },
        invariants: { full_success_forbidden: true },
      }
      appendTimeline(
        session,
        sessionCompletedEvent({
          turnId,
          eventId: 'pw-typed-rejected-stale-completed',
          planId: 'pw-plan-typed-rejected',
          content: 'All requested changes completed. Run complete.',
          reason: 'stale_success_detail',
          details: { hidden_details: 'Updated **99** jobs successfully.' },
          offsetSeconds: 4,
        }),
      )
      return { status: 200, body: { status: 'FAILED', session_id: session.session_id } }
    },
    snapshot(session) {
      return snapshotFromSession(session)
    },
  },

  typedPresentationKnowledgeSources: {
    name: 'typedPresentationKnowledgeSources',
    description: 'Phase 7 typed knowledge_answer sources render without details.sources fallback.',
    prompts: [typedKnowledgeSourcePrompt],
    onMessage(session, content) {
      addUserTurn(session, content || typedKnowledgeSourcePrompt, 'pw-turn-typed-knowledge')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-typed-knowledge'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-typed-knowledge'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-typed-knowledge',
        objective: 'Render typed knowledge answer sources.',
        stepId: 'pw-step-typed-knowledge',
        toolName: 'typed_knowledge_fixture',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-typed-knowledge-plan-created',
          planId: 'pw-plan-typed-knowledge',
          content: 'Preparing typed knowledge answer.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-typed-knowledge' } }
    },
    async onExecute(session, sleep) {
      const turnId = session.current_turn_id || 'pw-turn-typed-knowledge'
      await sleep(120)
      session.status = 'COMPLETED'
      completeSteps(session)
      session.presentation = {
        kind: 'knowledge_answer',
        state: 'completed',
        operation_id: 'pw-plan-typed-knowledge',
        summary: 'Use the cited LOTO procedure before lockout.',
        sources: [
          {
            source_number: 1,
            title: 'Typed LOTO Procedure',
            doc_id: 'LOTO-M-CNC-01',
            machine_id: 'M-CNC-01',
          },
        ],
      }
      appendTimeline(
        session,
        sessionCompletedEvent({
          turnId,
          eventId: 'pw-typed-knowledge-completed',
          planId: 'pw-plan-typed-knowledge',
          content: 'Knowledge response ready.',
          reason: 'typed_knowledge_fixture',
          offsetSeconds: 4,
        }),
      )
      session.timeline[session.timeline.length - 1].presentation = session.presentation
      return { status: 200, body: { status: 'COMPLETED', session_id: session.session_id } }
    },
    snapshot(session) {
      return snapshotFromSession(session)
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
    async onExecute(session) {
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
      completeAfterStream(session, {
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
      const frames = orderedActivityStream()
      const lastActivityId = [...frames].reverse().find((frame) => frame.event === 'activity')?.id
      return frames.map((frame) => (
        frame.id === lastActivityId
          ? { ...frame, afterSent: (session) => completePendingStream(session) }
          : frame
      ))
    },
  },

  activitySseResponseDocument: {
    name: 'activitySseResponseDocument',
    description: 'Response-document turns render live activity SSE rows while the run is active.',
    prompts: [activitySseResponseDocumentPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || activitySseResponseDocumentPrompt, 'pw-turn-activity-sse-rd')
      session.response_document_revision = 1
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-sse-rd'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-activity-sse-rd'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-activity-sse-rd',
        objective: 'Validate response-document browser activity stream behavior',
        stepId: 'pw-step-activity-sse-rd',
        toolName: 'get_machine_status',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-activity-sse-rd-plan-created',
          planId: 'pw-plan-activity-sse-rd',
          content: 'Keeping a response document active while activity SSE rows arrive.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-activity-sse-rd' } }
    },
    async onExecute(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-sse-rd'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-activity-sse-rd-execution-started',
          planId: 'pw-plan-activity-sse-rd',
        }),
      )
      completeAfterStream(session, {
        turnId,
        planId: 'pw-plan-activity-sse-rd',
        stepId: 'pw-step-activity-sse-rd',
        toolName: 'get_machine_status',
        answer: activitySseAnswer,
        eventPrefix: 'pw-activity-sse-rd',
      })
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-sse-rd'
      const base = session.status === 'COMPLETED'
        ? snapshotFromSession(session, orderedSseActivitySteps({ terminal: true }))
        : snapshotFromSession(session)
      const completed = session.status === 'COMPLETED'
      const revision = completed ? 2 : Number(session.response_document_revision || 1)
      const documentId = `rd:${session.session_id}:${turnId}`
      return {
        ...base,
        snapshot_revision: revision,
        response_document: {
          version: 1,
          id: documentId,
          document_id: documentId,
          turn_id: turnId,
          operation_id: 'pw-plan-activity-sse-rd',
          revision,
          revision_source: 'mock_activity_sse_response_document',
          state: completed ? 'completed' : 'running',
          status: completed ? 'completed' : 'running',
          message: completed ? activitySseAnswer : 'Working on response-document activity stream.',
          summary: completed ? activitySseAnswer : 'Working on response-document activity stream.',
          current_step_id: completed ? 'completed:activity-sse-rd' : 'analysis:activity-sse-rd',
          run_steps: completed
            ? [
              {
                step_id: 'analysis:activity-sse-rd',
                kind: 'analysis',
                state: 'completed',
                title: 'Understood request',
                summary: 'Request parsed.',
              },
              {
                step_id: 'knowledge:activity-sse-rd',
                kind: 'knowledge',
                state: 'completed',
                title: 'Prepared sourced answer',
                summary: '1 source attached.',
              },
              {
                step_id: 'completed:activity-sse-rd',
                kind: 'completed',
                state: 'completed',
                title: 'Run complete',
                summary: 'Source-backed answer is ready.',
              },
            ]
            : [
              {
                step_id: 'analysis:activity-sse-rd',
                kind: 'analysis',
                state: 'completed',
                title: 'Understood request',
                summary: 'Request parsed.',
              },
            ],
          blocks: [
            {
              id: 'activity:activity-sse-rd',
              type: 'run_activity',
              step_ids: completed
                ? ['analysis:activity-sse-rd', 'knowledge:activity-sse-rd', 'completed:activity-sse-rd']
                : ['analysis:activity-sse-rd'],
            },
            {
              id: 'message:activity-sse-rd',
              type: 'short_message',
              message: completed ? activitySseAnswer : 'Working on response-document activity stream.',
              status: completed ? 'completed' : 'running',
            },
          ],
          invariants: { fixture: 'activity_sse_response_document' },
          diagnostics: {},
        },
      }
    },
    notificationStream() {
      return activeSnapshotRaceNotificationStream()
    },
    activityStream() {
      const frames = orderedActivityStream({ prematureTerminal: true })
      const lastActivityId = [...frames].reverse().find((frame) => frame.event === 'activity')?.id
      return frames.map((frame) => (
        frame.id === lastActivityId
          ? { ...frame, afterSent: (session) => setTimeout(() => completePendingStream(session), 800) }
          : frame
      ))
    },
  },

  activitySseDelayedFallback: {
    name: 'activitySseDelayedFallback',
    description: 'Delayed activity SSE replaces the one client fallback row without generic progress spam.',
    prompts: [activitySseDelayedFallbackPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || activitySseDelayedFallbackPrompt, 'pw-turn-activity-sse-delayed')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-sse-delayed'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-activity-sse-delayed'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-activity-sse-delayed',
        objective: 'Validate delayed activity stream replaces client fallback',
        stepId: 'pw-step-activity-sse-delayed',
        toolName: 'get_machine_status',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-activity-sse-delayed-plan-created',
          planId: 'pw-plan-activity-sse-delayed',
          content: 'Activity SSE is intentionally delayed for fallback replacement coverage.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-activity-sse-delayed' } }
    },
    async onExecute(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-sse-delayed'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-activity-sse-delayed-execution-started',
          planId: 'pw-plan-activity-sse-delayed',
        }),
      )
      completeAfterStream(session, {
        turnId,
        planId: 'pw-plan-activity-sse-delayed',
        stepId: 'pw-step-activity-sse-delayed',
        toolName: 'get_machine_status',
        answer: activitySseAnswer,
        eventPrefix: 'pw-activity-sse-delayed',
      })
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'COMPLETED') return snapshotFromSession(session, orderedSseActivitySteps({ terminal: true }))
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return snapshotFromSession(session)
      return defaultIdleSnapshot(session)
    },
    notificationStream() {
      return activeSnapshotRaceNotificationStream()
    },
    activityStream() {
      const frames = orderedActivityStream({ firstActivityDelayMs: 1250 })
      const lastActivityId = [...frames].reverse().find((frame) => frame.event === 'activity')?.id
      return frames.map((frame) => (
        frame.id === lastActivityId
          ? { ...frame, afterSent: (session) => completePendingStream(session) }
          : frame
      ))
    },
  },

  activitySseGraphDuplicate: {
    name: 'activitySseGraphDuplicate',
    description: 'Graph activity SSE rows do not duplicate matching snapshot timeline rows.',
    prompts: [activitySseGraphDuplicatePrompt],
    onMessage(session, content) {
      addUserTurn(session, content || activitySseGraphDuplicatePrompt, 'pw-turn-activity-sse-graph-dup')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-sse-graph-dup'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-activity-sse-graph-dup'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-activity-sse-graph-dup',
        objective: 'Validate graph activity does not duplicate snapshot fallback rows',
        stepId: 'pw-step-activity-sse-graph-dup',
        toolName: 'rag_search_documents',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-activity-sse-graph-dup-plan-created',
          planId: 'pw-plan-activity-sse-graph-dup',
          content: 'Preparing a source-backed answer from retrieved documents.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-activity-sse-graph-dup' } }
    },
    async onExecute(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-sse-graph-dup'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-activity-sse-graph-dup-execution-started',
          planId: 'pw-plan-activity-sse-graph-dup',
        }),
      )
      completeAfterStream(session, {
        turnId,
        planId: 'pw-plan-activity-sse-graph-dup',
        stepId: 'pw-step-activity-sse-graph-dup',
        toolName: 'rag_search_documents',
        answer: activitySseAnswer,
        eventPrefix: 'pw-activity-sse-graph-dup',
      })
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'COMPLETED') return snapshotFromSession(session, completedActivitySteps())
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') return snapshotFromSession(session)
      return defaultIdleSnapshot(session)
    },
    notificationStream() {
      return activeSnapshotRaceNotificationStream()
    },
    activityStream() {
      const frames = [
        { id: 1, event: 'control', data: { type: 'STREAM_READY' } },
        {
          id: 2,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:semantic_intake_node',
            timestamp: Date.parse(fixtureTime(1)) / 1000,
            group: 'planning',
            label: 'Understood request',
            detail: 'Reviewing your request and recent context',
            state: 'running',
          },
        },
        {
          id: 3,
          event: 'activity',
          delayMs: 450,
          data: {
            id: 'graph:tool_execution_node',
            timestamp: Date.parse(fixtureTime(2)) / 1000,
            group: 'research',
            label: 'Searching knowledge sources',
            detail: 'Searching retrieved documents',
            state: 'running',
          },
        },
        {
          id: 4,
          event: 'activity',
          delayMs: 550,
          data: {
            id: 'graph:satisfaction_node',
            timestamp: Date.parse(fixtureTime(3)) / 1000,
            group: 'response',
            label: 'Checking result',
            detail: 'Verifying the result',
            state: 'running',
          },
        },
        {
          id: 5,
          event: 'activity',
          delayMs: 550,
          data: {
            id: 'graph:session_completed',
            timestamp: Date.parse(fixtureTime(4)) / 1000,
            group: 'response',
            label: 'Run complete',
            detail: 'All steps finished. See the thread below.',
            state: 'complete',
          },
        },
      ]
      const lastActivityId = [...frames].reverse().find((frame) => frame.event === 'activity')?.id
      return frames.map((frame) => (
        frame.id === lastActivityId
          ? { ...frame, afterSent: (session) => completePendingStream(session) }
          : frame
      ))
    },
  },

  activitySseApprovalResume: {
    name: 'activitySseApprovalResume',
    description: 'Approval resume activity SSE renders one semantic timeline without raw graph-node rows.',
    prompts: [activitySseApprovalResumePrompt],
    onMessage(session, content) {
      addUserTurn(session, content || activitySseApprovalResumePrompt, 'pw-turn-activity-sse-approval-resume')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-sse-approval-resume'
      session.status = 'WAITING_APPROVAL'
      session.operation_id = 'pw-plan-activity-sse-approval-resume'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-activity-sse-approval-resume',
        objective: 'Validate approval resume activity SSE display timeline',
        stepId: 'pw-step-activity-sse-approval-resume',
        toolName: 'patch__jobs_{id}',
        status: 'PENDING_APPROVAL',
      })
      session.steps = session.plan.steps.map((step) => ({ ...step, status: 'WAITING_APPROVAL' }))
      session.pending_approval = {
        approval_id: 'pw-approval-activity-sse-resume',
        session_id: session.session_id,
        subject_type: 'graph',
        subject_id: 'pw-plan-activity-sse-approval-resume',
        tool_name: '__langgraph_commit__',
        side_effect_level: 'HIGH',
        risk_summary: '5 jobs will be updated from low to medium priority.',
        args: {
          kind: 'graph_write_approval_required',
          approval_label: 'Approval 1',
          write_set: [
            'JOB-SEED-005',
            'JOB-SEED-009',
            'JOB-SEED-012',
            'JOB-SEED-017',
            'JOB-SEED-024',
          ],
        },
        status: 'PENDING',
        created_at: fixtureTime(3),
        expires_at: fixtureTime(300),
      }
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-activity-sse-approval-resume-plan-created',
          planId: 'pw-plan-activity-sse-approval-resume',
          content: 'Preparing approval resume activity fixture.',
          status: 'PENDING_APPROVAL',
        }),
      )
      appendTimeline(session, {
        event_id: 'pw-activity-sse-approval-resume-required',
        turn_id: turnId,
        event_type: 'approval_required',
        approval_id: session.pending_approval.approval_id,
        tool_name: session.pending_approval.tool_name,
        content: 'Waiting for your approval: 5 jobs will be updated from low to medium priority.',
        status: 'PENDING',
        operation_id: 'pw-plan-activity-sse-approval-resume',
        details: {
          args: session.pending_approval.args,
          side_effect_level: session.pending_approval.side_effect_level,
        },
        created_at: fixtureTime(3),
      })
      return { status: 200, body: { status: 'WAITING_APPROVAL', plan_id: 'pw-plan-activity-sse-approval-resume' } }
    },
    async onExecute() {
      return { status: 200, body: { status: 'WAITING_APPROVAL', session_id: null } }
    },
    onApprove(session, approvalId) {
      if (approvalId !== 'pw-approval-activity-sse-resume') {
        return { status: 404, body: { detail: 'Unknown approval id for activity SSE resume fixture.' } }
      }
      const turnId = session.current_turn_id || 'pw-turn-activity-sse-approval-resume'
      session.pending_approval = null
      session.status = 'EXECUTING'
      appendTimeline(session, {
        event_id: 'pw-activity-sse-approval-resume-approved',
        turn_id: turnId,
        event_type: 'approval_decided',
        approval_id: approvalId,
        content: 'Approval received. Continuing with approved changes.',
        status: 'APPROVED',
        operation_id: 'pw-plan-activity-sse-approval-resume',
        created_at: fixtureTime(5),
      })
      completeAfterStream(session, {
        turnId,
        planId: 'pw-plan-activity-sse-approval-resume',
        stepId: 'pw-step-activity-sse-approval-resume',
        toolName: 'patch__jobs_{id}',
        answer: 'Approval activity SSE rendered one clean timeline after approval.',
        eventPrefix: 'pw-activity-sse-approval-resume',
      })
      return { status: 200, body: { status: 'EXECUTING', approval_id: approvalId } }
    },
    snapshot(session) {
      const rawApprovalRows = [
        {
          id: 'graph:000001:semantic_intake_node',
          timestamp: Date.parse(fixtureTime(1)) / 1000,
          order: 1,
          group: 'planning',
          label: 'Understood request',
          detail: 'Reviewing your request and recent context',
          state: 'success',
        },
        {
          id: 'graph:000002:requirement_ledger_node',
          timestamp: Date.parse(fixtureTime(1.5)) / 1000,
          order: 2,
          group: 'planning',
          label: 'Structuring request',
          detail: 'Structuring the request',
          state: 'success',
        },
        {
          id: 'graph:000003:dependency_wait_node',
          timestamp: Date.parse(fixtureTime(1.75)) / 1000,
          order: 3,
          group: 'planning',
          label: 'Waiting for parent evidence',
          detail: 'Dependent read needs parent evidence first',
          state: 'success',
        },
        {
          id: 'graph:000004:tool_retrieval_node',
          timestamp: Date.parse(fixtureTime(2)) / 1000,
          order: 4,
          group: 'research',
          label: 'Finding information path',
          detail: 'Finding the right information path',
          state: 'success',
        },
        {
          id: 'graph:000005:planner_choose_tool_node',
          timestamp: Date.parse(fixtureTime(2.25)) / 1000,
          order: 5,
          group: 'action',
          label: 'Selecting safe action',
          detail: 'Selecting a safe action',
          state: 'success',
        },
        {
          id: 'graph:000006:tool_execution_node',
          timestamp: Date.parse(fixtureTime(2.5)) / 1000,
          order: 6,
          group: 'action',
          label: 'Preparing backend action',
          detail: 'Checking whether the action can run safely',
          state: 'success',
        },
        {
          id: 'graph:000007:approval_gate_node',
          timestamp: Date.parse(fixtureTime(2.75)) / 1000,
          order: 7,
          group: 'approval',
          label: 'Preparing write approval',
          detail: 'Building the exact write set before approval',
          state: 'success',
        },
        {
          id: 'graph:000008:approval_node',
          timestamp: Date.parse(fixtureTime(3)) / 1000,
          order: 8,
          group: 'approval',
          label: 'Waiting for your approval',
          detail: 'Approval is required before committing staged changes',
          state: 'success',
        },
        {
          id: 'graph:000009:evidence_observation_node',
          timestamp: Date.parse(fixtureTime(3.25)) / 1000,
          order: 9,
          group: 'response',
          label: 'Checking result',
          detail: 'Checking tool evidence',
          state: 'success',
        },
        {
          id: 'graph:000010:satisfaction_node',
          timestamp: Date.parse(fixtureTime(3.5)) / 1000,
          order: 10,
          group: 'response',
          label: 'Verifying result',
          detail: 'Verifying the result',
          state: 'running',
        },
      ]
      if (session.status === 'COMPLETED') {
        return snapshotFromSession(session, [
          {
            id: 'act:display:understood_request',
            timestamp: Date.parse(fixtureTime(1)) / 1000,
            order: 1,
            group: 'planning',
            label: 'Understood request',
            detail: 'Reviewing your request and recent context',
            state: 'success',
          },
          {
            id: 'act:display:matched_records',
            timestamp: Date.parse(fixtureTime(2)) / 1000,
            order: 2,
            group: 'research',
            label: 'Found 5 low-priority jobs',
            detail: 'Ready to update them to medium priority',
            state: 'success',
          },
          {
            id: 'act:display:approval_preview',
            timestamp: Date.parse(fixtureTime(3)) / 1000,
            order: 3,
            group: 'approval',
            label: 'Prepared change preview',
            detail: '5 jobs will be updated from low to medium priority.',
            state: 'success',
          },
          {
            id: 'act:display:approval_waiting',
            timestamp: Date.parse(fixtureTime(4)) / 1000,
            order: 4,
            group: 'approval',
            label: 'Waiting for your approval',
            detail: 'Approval is required before committing staged changes',
            state: 'success',
          },
          {
            id: 'act:display:approval_received',
            timestamp: Date.parse(fixtureTime(5)) / 1000,
            order: 5,
            group: 'approval',
            label: 'Approval received',
            detail: 'Continuing with your approved changes',
            state: 'success',
          },
          {
            id: 'act:display:write_committed',
            timestamp: Date.parse(fixtureTime(6)) / 1000,
            order: 6,
            group: 'approval',
            label: 'Applied approved change',
            detail: 'Applied the approved backend write',
            state: 'success',
          },
          {
            id: 'act:display:post_write_read',
            timestamp: Date.parse(fixtureTime(7)) / 1000,
            order: 7,
            group: 'research',
            label: 'Read updated jobs',
            detail: 'Checked the records after the approved change',
            state: 'success',
          },
          {
            id: 'act:display:verified_result',
            timestamp: Date.parse(fixtureTime(8)) / 1000,
            order: 8,
            group: 'response',
            label: 'Verified updated result',
            detail: 'Verified the result after the approved change',
            state: 'success',
          },
          {
            id: 'act:display:run_complete',
            timestamp: Date.parse(fixtureTime(9)) / 1000,
            order: 9,
            group: 'response',
            label: 'Run complete',
            detail: 'All steps finished. See the thread below.',
            state: 'complete',
          },
        ])
      }
      if (session.status === 'WAITING_APPROVAL') {
        return snapshotFromSession(session, [
          {
            id: 'act:display:understood_request',
            timestamp: Date.parse(fixtureTime(1)) / 1000,
            order: 1,
            group: 'planning',
            label: 'Understood request',
            detail: 'Reviewing your request and recent context',
            state: 'success',
          },
          {
            id: 'act:display:matched_records',
            timestamp: Date.parse(fixtureTime(2)) / 1000,
            order: 2,
            group: 'research',
            label: 'Found 5 low-priority jobs',
            detail: 'Ready to update them to medium priority',
            state: 'success',
          },
          {
            id: 'act:display:approval_preview',
            timestamp: Date.parse(fixtureTime(3)) / 1000,
            order: 3,
            group: 'approval',
            label: 'Prepared change preview',
            detail: '5 jobs will be updated from low to medium priority.',
            state: 'success',
          },
          {
            id: 'act:display:approval_waiting',
            timestamp: Date.parse(fixtureTime(4)) / 1000,
            order: 4,
            group: 'approval',
            label: 'Waiting for your approval',
            detail: 'Approval is required before committing staged changes',
            state: 'waiting',
          },
        ])
      }
      return snapshotFromSession(session)
    },
    notificationStream() {
      return activeSnapshotRaceNotificationStream().map((frame) => {
        const terminal = frame?.data?.session_status === 'COMPLETED' || frame?.data?.status === 'COMPLETED'
        return terminal ? { ...frame, waitForSessionStatus: 'COMPLETED' } : frame
      })
    },
    activityStream() {
      const frames = [
        { id: 1, event: 'control', data: { type: 'STREAM_READY' } },
        {
          id: 2,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000001:semantic_intake_node',
            timestamp: Date.parse(fixtureTime(1)) / 1000,
            order: 1,
            group: 'planning',
            label: 'Understood request',
            detail: 'Reviewing your request and recent context',
            state: 'success',
          },
        },
        {
          id: 3,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000002:requirement_ledger_node',
            timestamp: Date.parse(fixtureTime(1.5)) / 1000,
            order: 2,
            group: 'planning',
            label: 'Structuring request',
            detail: 'Structuring the request',
            state: 'success',
          },
        },
        {
          id: 4,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000003:dependency_wait_node',
            timestamp: Date.parse(fixtureTime(1.75)) / 1000,
            order: 3,
            group: 'planning',
            label: 'Waiting for parent evidence',
            detail: 'Dependent read needs parent evidence first',
            state: 'success',
          },
        },
        {
          id: 5,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000004:tool_retrieval_node',
            timestamp: Date.parse(fixtureTime(2)) / 1000,
            order: 4,
            group: 'research',
            label: 'Finding information path',
            detail: 'Finding the right information path',
            state: 'success',
          },
        },
        {
          id: 6,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000005:planner_choose_tool_node',
            timestamp: Date.parse(fixtureTime(2.25)) / 1000,
            order: 5,
            group: 'action',
            label: 'Selecting safe action',
            detail: 'Selecting a safe action',
            state: 'running',
          },
        },
        {
          id: 7,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000006:tool_execution_node',
            timestamp: Date.parse(fixtureTime(2.5)) / 1000,
            order: 6,
            group: 'action',
            label: 'Preparing backend action',
            detail: 'Checking whether the action can run safely',
            state: 'success',
          },
        },
        {
          id: 8,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000007:approval_gate_node',
            timestamp: Date.parse(fixtureTime(2.75)) / 1000,
            order: 7,
            group: 'approval',
            label: 'Preparing write approval',
            detail: 'Building the exact write set before approval',
            state: 'success',
          },
        },
        {
          id: 9,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000008:approval_node',
            timestamp: Date.parse(fixtureTime(3)) / 1000,
            order: 8,
            group: 'approval',
            label: 'Waiting for your approval',
            detail: 'Approval is required before committing staged changes',
            state: 'success',
          },
        },
        {
          id: 10,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000009:evidence_observation_node',
            timestamp: Date.parse(fixtureTime(3.25)) / 1000,
            order: 9,
            group: 'response',
            label: 'Checking result',
            detail: 'Checking tool evidence',
            state: 'success',
          },
        },
        {
          id: 11,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000010:satisfaction_node',
            timestamp: Date.parse(fixtureTime(3.5)) / 1000,
            order: 10,
            group: 'response',
            label: 'Verifying result',
            detail: 'Verifying the result',
            state: 'running',
          },
        },
        {
          id: 12,
          event: 'activity',
          delayMs: 900,
          data: {
            id: 'act:display:understood_request',
            timestamp: Date.parse(fixtureTime(1)) / 1000,
            order: 1,
            group: 'planning',
            label: 'Understood request',
            detail: 'Reviewing your request and recent context',
            state: 'success',
          },
        },
        {
          id: 13,
          event: 'activity',
          delayMs: 140,
          data: {
            id: 'act:display:approval_preview',
            timestamp: Date.parse(fixtureTime(3)) / 1000,
            order: 3,
            group: 'approval',
            label: 'Prepared change preview',
            detail: '5 jobs will be updated from low to medium priority.',
            state: 'success',
          },
        },
        {
          id: 14,
          event: 'activity',
          delayMs: 140,
          data: {
            id: 'act:display:approval_waiting',
            timestamp: Date.parse(fixtureTime(4)) / 1000,
            order: 4,
            group: 'approval',
            label: 'Waiting for your approval',
            detail: 'Approval is required before committing staged changes',
            state: 'waiting',
          },
        },
        {
          id: 15,
          event: 'activity',
          delayMs: 1800,
          data: {
            id: 'act:display:matched_records',
            timestamp: Date.parse(fixtureTime(2)) / 1000,
            order: 2,
            group: 'research',
            label: 'Found 5 low-priority jobs',
            detail: 'Ready to update them to medium priority',
            state: 'success',
          },
        },
        {
          id: 16,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'act:caption:dependency_wait:req-002',
            timestamp: Date.parse(fixtureTime(4.2)) / 1000,
            order: 5,
            group: 'planning',
            label: 'Waiting for parent evidence',
            detail: 'Dependent read needs parent evidence first',
            state: 'success',
          },
        },
        {
          id: 17,
          event: 'activity',
          delayMs: 1250,
          data: {
            id: 'act:approval-decided:pw-approval-activity-sse-resume',
            timestamp: Date.parse(fixtureTime(5)) / 1000,
            order: 6,
            group: 'approval',
            label: 'Approval received',
            detail: 'Continuing with your approved changes',
            state: 'success',
          },
        },
        {
          id: 18,
          event: 'activity',
          delayMs: 1250,
          data: {
            id: 'act:display:approval_received',
            timestamp: Date.parse(fixtureTime(5)) / 1000,
            order: 5,
            group: 'approval',
            label: 'Approval received',
            detail: 'Continuing with your approved changes',
            state: 'success',
          },
        },
        {
          id: 19,
          event: 'activity',
          delayMs: 360,
          data: {
            id: 'act:display:write_committed',
            timestamp: Date.parse(fixtureTime(6)) / 1000,
            order: 6,
            group: 'approval',
            label: 'Applied approved change',
            detail: 'Applied the approved backend write',
            state: 'success',
          },
        },
        {
          id: 20,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'act:caption:parallel_read_batch:dependency-group-001',
            timestamp: Date.parse(fixtureTime(6.5)) / 1000,
            order: 7,
            group: 'research',
            label: 'Reading 3 job records',
            detail: 'Parallel read batch scheduled',
            state: 'success',
          },
        },
        {
          id: 21,
          event: 'activity',
          delayMs: 360,
          data: {
            id: 'act:display:post_write_read',
            timestamp: Date.parse(fixtureTime(7)) / 1000,
            order: 7,
            group: 'research',
            label: 'Read updated jobs',
            detail: 'Checked the records after the approved change',
            state: 'success',
          },
        },
        {
          id: 22,
          event: 'activity',
          delayMs: 360,
          data: {
            id: 'act:display:verified_result',
            timestamp: Date.parse(fixtureTime(8)) / 1000,
            order: 8,
            group: 'response',
            label: 'Verified updated result',
            detail: 'Verified the result after the approved change',
            state: 'running',
          },
        },
      ]
      return frames.map((frame) => (
        frame.id === 22
          ? { ...frame, afterSent: (session) => setTimeout(() => completePendingStream(session), 4200) }
          : frame
      ))
    },
  },

  activitySseApprovalNoPending: {
    name: 'activitySseApprovalNoPending',
    description: 'Approval activity SSE projects raw graph rows even when no pending approval object exists yet.',
    prompts: [activitySseApprovalNoPendingPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || activitySseApprovalNoPendingPrompt, 'pw-turn-activity-sse-approval-no-pending')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-sse-approval-no-pending'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-activity-sse-approval-no-pending'
      session.replan_context = {
        planner_owned_agent_graph: {
          dependency_plan: {
            requirements: [
              { requirement_id: 'req-001', label: 'approval_required', ready: true },
            ],
          },
          response_document_context: {
            state: 'rendering',
            diagnostics: {
              summary: '',
              final_validation_status: 'deferred',
            },
          },
        },
      }
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-activity-sse-approval-no-pending',
        objective: 'Validate clean approval activity without pending approval object',
        stepId: 'pw-step-activity-sse-approval-no-pending',
        toolName: 'patch__jobs_{id}',
      })
      session.steps = session.plan.steps.map((step) => ({ ...step, status: 'IN_PROGRESS' }))
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-activity-sse-approval-no-pending-plan-created',
          planId: 'pw-plan-activity-sse-approval-no-pending',
          content: 'Preparing approval activity fixture without a pending approval object.',
          status: 'EXECUTING',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-activity-sse-approval-no-pending' } }
    },
    async onExecute(session) {
      session.status = 'EXECUTING'
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      return snapshotFromSession(session)
    },
    notificationStream() {
      return longRunningNotificationStream()
    },
    activityStream() {
      return [
        { id: 1, event: 'control', data: { type: 'STREAM_READY' } },
        {
          id: 2,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000001:semantic_intake_node',
            timestamp: Date.parse(fixtureTime(1)) / 1000,
            order: 1,
            group: 'planning',
            label: 'Understood request',
            detail: 'Reviewing your request and recent context',
            state: 'success',
          },
        },
        {
          id: 3,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000002:requirement_ledger_node',
            timestamp: Date.parse(fixtureTime(1.5)) / 1000,
            order: 2,
            group: 'planning',
            label: 'Structuring request',
            detail: 'Structuring the request',
            state: 'success',
          },
        },
        {
          id: 4,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000003:dependency_wait_node',
            timestamp: Date.parse(fixtureTime(1.75)) / 1000,
            order: 3,
            group: 'planning',
            label: 'Waiting for parent evidence',
            detail: 'Dependent read needs parent evidence first',
            state: 'success',
          },
        },
        {
          id: 5,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000004:tool_retrieval_node',
            timestamp: Date.parse(fixtureTime(2)) / 1000,
            order: 4,
            group: 'planning',
            label: 'Finding information path',
            detail: 'Finding the right information path',
            state: 'success',
          },
        },
        {
          id: 6,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000005:planner_choose_tool_node',
            timestamp: Date.parse(fixtureTime(2.25)) / 1000,
            order: 5,
            group: 'planning',
            label: 'Selecting safe action',
            detail: 'Selecting a safe action',
            state: 'success',
          },
        },
        {
          id: 7,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000006:tool_execution_node',
            timestamp: Date.parse(fixtureTime(2.5)) / 1000,
            order: 6,
            group: 'research',
            label: 'Preparing backend action',
            detail: 'Checking whether the action can run safely',
            state: 'success',
          },
        },
        {
          id: 8,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000007:write_staging_node',
            timestamp: Date.parse(fixtureTime(2.75)) / 1000,
            order: 7,
            group: 'approval',
            label: 'Preparing write approval',
            detail: 'Building the exact write set before approval',
            state: 'success',
          },
        },
        {
          id: 9,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000008:approval_gate_node',
            timestamp: Date.parse(fixtureTime(3)) / 1000,
            order: 8,
            group: 'approval',
            label: 'Waiting for your approval',
            detail: 'Approval is required before committing staged changes',
            state: 'success',
          },
        },
        {
          id: 10,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000009:evidence_observation_node',
            timestamp: Date.parse(fixtureTime(3.25)) / 1000,
            order: 9,
            group: 'response',
            label: 'Checking result',
            detail: 'Checking tool evidence',
            state: 'success',
          },
        },
        {
          id: 11,
          event: 'activity',
          delayMs: 80,
          data: {
            id: 'graph:000010:satisfaction_node',
            timestamp: Date.parse(fixtureTime(3.5)) / 1000,
            order: 10,
            group: 'response',
            label: 'Verifying result',
            detail: 'Verifying the result',
            state: 'running',
          },
        },
      ]
    },
  },

  activitySharedTimestampOrder: {
    name: 'activitySharedTimestampOrder',
    description: 'Active graph activity rows use structured order when timestamps collide.',
    prompts: [activitySharedTimestampOrderPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || activitySharedTimestampOrderPrompt, 'pw-turn-activity-shared-order')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-shared-order'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-activity-shared-order'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-activity-shared-order',
        objective: 'Validate stable activity ordering when graph rows share timestamps',
        stepId: 'pw-step-activity-shared-order',
        toolName: 'get_machine_status',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-activity-shared-order-plan-created',
          planId: 'pw-plan-activity-shared-order',
          content: 'Activity rows share a timestamp while retaining graph progress order.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-activity-shared-order' } }
    },
    async onExecute(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-shared-order'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-activity-shared-order-execution-started',
          planId: 'pw-plan-activity-shared-order',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') {
        return snapshotFromSession(session, sharedTimestampActivitySteps())
      }
      return defaultIdleSnapshot(session)
    },
    notificationStream() {
      return longRunningNotificationStream()
    },
    activityStream() {
      return [{ id: 1, event: 'control', data: { type: 'STREAM_READY' } }]
    },
  },

  activityActiveRetryStory: {
    name: 'activityActiveRetryStory',
    description: 'Active retry story rows suppress stale graph-stage activity frames.',
    prompts: [activityActiveRetryStoryPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || activityActiveRetryStoryPrompt, 'pw-turn-activity-active-retry-story')
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-active-retry-story'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-activity-active-retry-story'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-activity-active-retry-story',
        objective: 'Validate active retry activity stays on an attempt story',
        stepId: 'pw-step-activity-active-retry-story',
        toolName: 'get_jobs',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-activity-active-retry-story-plan-created',
          planId: 'pw-plan-activity-active-retry-story',
          content: 'Retry diagnostics are active while graph rows are still arriving.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-activity-active-retry-story' } }
    },
    async onExecute(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-active-retry-story'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-activity-active-retry-story-execution-started',
          planId: 'pw-plan-activity-active-retry-story',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') {
        return snapshotFromSession(session, activeRetryStoryActivitySteps())
      }
      return defaultIdleSnapshot(session)
    },
    notificationStream() {
      return longRunningNotificationStream()
    },
    activityStream() {
      const timestamp = Date.parse(fixtureTime(8)) / 1000
      return [
        { id: 1, event: 'control', data: { type: 'STREAM_READY' } },
        {
          id: 2,
          event: 'activity',
          delayMs: 250,
          data: {
            id: 'graph:planner_choose_tool_node',
            timestamp,
            order: 7,
            group: 'planning',
            label: 'Selecting safe action',
            detail: 'Selecting a safe action',
            state: 'running',
          },
        },
        {
          id: 3,
          event: 'activity',
          delayMs: 450,
          data: {
            id: 'graph:tool_retrieval_node',
            timestamp,
            order: 6,
            group: 'planning',
            label: 'Finding information path',
            detail: 'Finding the right information path',
            state: 'running',
          },
        },
        {
          id: 4,
          event: 'activity',
          delayMs: 650,
          data: {
            id: 'graph:planner_decision_node',
            timestamp,
            order: 5,
            group: 'planning',
            label: 'Choosing next action',
            detail: 'Choosing the next backend action',
            state: 'running',
          },
        },
      ]
    },
  },

  activityRetryCollapseHandoff: {
    name: 'activityRetryCollapseHandoff',
    description: 'Active retry story rows stay uncollapsed as later snapshots append new attempts.',
    prompts: [activityRetryCollapseHandoffPrompt],
    onMessage(session, content) {
      addUserTurn(session, content || activityRetryCollapseHandoffPrompt, 'pw-turn-activity-retry-collapse')
      session.retry_collapse_snapshot_count = 0
    },
    onPlan(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-retry-collapse'
      session.status = 'EXECUTING'
      session.operation_id = 'pw-plan-activity-retry-collapse'
      session.plan = buildFactoryAgentPlan(session, {
        planId: 'pw-plan-activity-retry-collapse',
        objective: 'Validate active retry collapsed snapshot handoff',
        stepId: 'pw-step-activity-retry-collapse',
        toolName: 'get_jobs',
      })
      session.steps = [...session.plan.steps]
      appendTimeline(
        session,
        planCreatedEvent({
          turnId,
          eventId: 'pw-activity-retry-collapse-plan-created',
          planId: 'pw-plan-activity-retry-collapse',
          content: 'Retry attempts are being compacted while the run remains active.',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', plan_id: 'pw-plan-activity-retry-collapse' } }
    },
    async onExecute(session) {
      const turnId = session.current_turn_id || 'pw-turn-activity-retry-collapse'
      session.execute_count += 1
      session.status = 'EXECUTING'
      appendTimeline(
        session,
        executionStartedEvent({
          turnId,
          eventId: 'pw-activity-retry-collapse-execution-started',
          planId: 'pw-plan-activity-retry-collapse',
        }),
      )
      return { status: 200, body: { status: 'EXECUTING', session_id: session.session_id } }
    },
    snapshot(session) {
      if (session.status === 'PLANNING' || session.status === 'EXECUTING') {
        const count = Number(session.retry_collapse_snapshot_count || 0) + 1
        session.retry_collapse_snapshot_count = count
        const steps = activeRetryFullNoisyStoryActivitySteps({ activeAttempt: count <= 3 ? 5 : 6 })
        return snapshotFromSession(session, steps)
      }
      return defaultIdleSnapshot(session)
    },
    notificationStream() {
      return longRunningNotificationStream()
    },
    activityStream() {
      return [{ id: 1, event: 'control', data: { type: 'STREAM_READY' } }]
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
