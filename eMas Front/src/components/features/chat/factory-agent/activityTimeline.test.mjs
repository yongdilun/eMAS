import assert from 'node:assert/strict'
import test from 'node:test'

import {
  assistantAnswerAllowed,
  friendlySessionStatus,
  buildActivityStepsFromSnapshot,
  buildActivityStepsFromTimeline,
  coalesceActivitySteps,
  compareActivitySteps,
  mergeActivityStep,
  normalizeActivityStep,
  shouldAutoCollapseActivity,
  shouldShowActivityTimeline,
  stripPrematureTerminalActivitySteps,
  truncateActivityAfterTerminal,
} from './activityTimelineUtils.js'

test('assistantAnswerAllowed: defers until activity terminal when steps exist', () => {
  const turn = { summary: 'Long OSHA answer…', terminal: null }
  const steps = [{ id: '1', label: 'Working', state: 'running', group: 'g', timestamp: 1 }]
  assert.equal(
    assistantAnswerAllowed({
      activityTimelineEnabled: true,
      isLatestTurn: true,
      sessionStatus: 'EXECUTING',
      activitySteps: steps,
      turn,
    }),
    false,
  )
  assert.equal(
    assistantAnswerAllowed({
      activityTimelineEnabled: true,
      isLatestTurn: true,
      sessionStatus: 'COMPLETED',
      activitySteps: [...steps, { id: '2', label: 'Run complete', state: 'complete', group: 'g', timestamp: 2 }],
      turn,
    }),
    true,
  )
})

test('activity ordering uses backend order when timestamps collide', () => {
  const timestamp = 1770000000
  const ordered = [
    {
      id: 'graph:aaa-last',
      timestamp,
      order: 3,
      label: 'Checking result',
      detail: 'Checking tool evidence',
      group: 'response',
      state: 'running',
    },
    {
      id: 'graph:zzz-first',
      timestamp,
      order: 1,
      label: 'Understood request',
      detail: 'Structuring the request',
      group: 'planning',
      state: 'success',
    },
    {
      id: 'graph:mmm-second',
      timestamp,
      order: 2,
      label: 'Running selected tool',
      detail: 'Checking relevant records',
      group: 'research',
      state: 'success',
    },
  ].sort(compareActivitySteps)

  assert.deepEqual(ordered.map((step) => step.detail), [
    'Structuring the request',
    'Checking relevant records',
    'Checking tool evidence',
  ])
  assert.equal(normalizeActivityStep(ordered[0]).order, 1)
})

test('assistantAnswerAllowed: active sessions do not unlock on activity terminal before final snapshot', () => {
  assert.equal(
    assistantAnswerAllowed({
      activityTimelineEnabled: true,
      isLatestTurn: true,
      sessionStatus: 'EXECUTING',
      activitySteps: [
        { id: '1', label: 'Checking citations', state: 'success', group: 'response', timestamp: 1 },
        { id: '2', label: 'Run complete', state: 'complete', group: 'response', timestamp: 2 },
      ],
      turn: { terminal: null },
    }),
    false,
  )
})

test('assistantAnswerAllowed: without steps, requires turn terminal', () => {
  assert.equal(
    assistantAnswerAllowed({
      activityTimelineEnabled: true,
      isLatestTurn: true,
      sessionStatus: 'EXECUTING',
      activitySteps: [],
      turn: { terminal: null },
    }),
    false,
  )
  assert.equal(
    assistantAnswerAllowed({
      activityTimelineEnabled: true,
      isLatestTurn: true,
      sessionStatus: 'EXECUTING',
      activitySteps: [],
      turn: { terminal: { event_type: 'session_completed' } },
    }),
    true,
  )
})

test('assistantAnswerAllowed: always allows when not latest or timeline off', () => {
  assert.equal(
    assistantAnswerAllowed({
      activityTimelineEnabled: true,
      isLatestTurn: false,
      sessionStatus: 'EXECUTING',
      activitySteps: [{ id: '1', state: 'running', label: 'x', group: 'g', timestamp: 1 }],
      turn: {},
    }),
    true,
  )
  assert.equal(
    assistantAnswerAllowed({
      activityTimelineEnabled: false,
      isLatestTurn: true,
      sessionStatus: 'EXECUTING',
      activitySteps: [{ id: '1', state: 'running', label: 'x', group: 'g', timestamp: 1 }],
      turn: {},
    }),
    true,
  )
})

test('assistantAnswerAllowed: allows during waiting approval', () => {
  assert.equal(
    assistantAnswerAllowed({
      activityTimelineEnabled: true,
      isLatestTurn: true,
      sessionStatus: 'WAITING_APPROVAL',
      activitySteps: [{ id: '1', state: 'running', label: 'x', group: 'g', timestamp: 1 }],
      turn: {},
    }),
    true,
  )
})

test('assistantAnswerAllowed: COMPLETED still defers until last activity row is terminal', () => {
  assert.equal(
    assistantAnswerAllowed({
      activityTimelineEnabled: true,
      isLatestTurn: true,
      sessionStatus: 'COMPLETED',
      activitySteps: [{ id: '1', label: 'Wrapping up', state: 'running', group: 'g', timestamp: 1 }],
      turn: { terminal: { event_type: 'session_completed' } },
    }),
    false,
  )
  assert.equal(
    assistantAnswerAllowed({
      activityTimelineEnabled: true,
      isLatestTurn: true,
      sessionStatus: 'COMPLETED',
      activitySteps: [{ id: '1', label: 'Run complete', state: 'complete', group: 'g', timestamp: 1 }],
      turn: { terminal: { event_type: 'session_completed' } },
    }),
    true,
  )
})

test('assistantAnswerAllowed: completed turns ignore stale rows after terminal activity', () => {
  const steps = [
    { id: '1', label: 'Checking result', state: 'success', group: 'response', timestamp: 1 },
    { id: '2', label: 'Run complete', state: 'complete', group: 'response', timestamp: 2 },
    { id: '3', label: 'Understood request', state: 'running', group: 'planning', timestamp: 3 },
  ]

  assert.deepEqual(
    truncateActivityAfterTerminal(steps).map((step) => step.label),
    ['Checking result', 'Run complete'],
  )
  assert.equal(
    assistantAnswerAllowed({
      activityTimelineEnabled: true,
      isLatestTurn: true,
      sessionStatus: 'COMPLETED',
      activitySteps: steps,
      turn: { terminal: { event_type: 'session_completed' } },
    }),
    true,
  )
})

test('assistantAnswerAllowed: IDLE with in-flight activity rows defers like EXECUTING', () => {
  assert.equal(
    assistantAnswerAllowed({
      activityTimelineEnabled: true,
      isLatestTurn: true,
      sessionStatus: 'IDLE',
      activitySteps: [{ id: '1', label: 'Understanding your request...', state: 'running', group: 'g', timestamp: 1 }],
      turn: { terminal: null },
    }),
    false,
  )
})

test('normalizes activity steps to the stable user-facing schema', () => {
  const step = normalizeActivityStep({
    id: 'activity_1',
    timestamp: 1710000000,
    group: 'research',
    label: 'Gathering information',
    detail: 'Checking machine records',
    state: 'running',
    tool_name: 'get__machines_{id}',
  })

  assert.deepEqual(step, {
    id: 'activity_1',
    timestamp: 1710000000,
    group: 'research',
    label: 'Gathering information',
    detail: 'Checking machine records',
    state: 'running',
  })
  assert.equal(JSON.stringify(step).includes('get__machines'), false)
})

test('auto-collapse only when the latest step is terminal', () => {
  assert.equal(
    shouldAutoCollapseActivity([
      { id: '1', group: 'r', label: 'A', state: 'complete', timestamp: 1 },
      { id: '2', group: 'r', label: 'B', state: 'waiting', timestamp: 2 },
    ]),
    false,
  )
  assert.equal(
    shouldAutoCollapseActivity([
      { id: '1', group: 'r', label: 'A', state: 'waiting', timestamp: 1 },
      { id: '2', group: 'r', label: 'B', state: 'complete', timestamp: 2 },
    ]),
    true,
  )
  assert.equal(
    shouldAutoCollapseActivity([
      { id: '1', group: 'r', label: 'A', state: 'running', timestamp: 1 },
      { id: '2', group: 'r', label: 'B', state: 'error', timestamp: 2 },
    ]),
    true,
  )
})

test('merges activity by id and auto-collapses on complete', () => {
  const steps = mergeActivityStep([], {
    id: 'activity_1',
    timestamp: 2,
    group: 'research',
    label: 'Gathering information',
    state: 'running',
  })
  const merged = mergeActivityStep(steps, {
    id: 'activity_2',
    timestamp: 3,
    group: 'response',
    label: 'Run complete',
    state: 'complete',
  })

  assert.equal(merged.length, 2)
  assert.equal(shouldAutoCollapseActivity(merged), true)
})

test('coalesces duplicate timeline and live graph activity rows by visible meaning', () => {
  const rows = coalesceActivitySteps([
    {
      id: 'act:plan-created',
      timestamp: 1,
      group: 'planning',
      label: 'Understood request',
      detail: 'Reviewing your request and recent context',
      state: 'success',
    },
    {
      id: 'graph:semantic_intake_node',
      timestamp: 2,
      group: 'planning',
      label: 'Understood request',
      detail: 'Reviewing your request and recent context',
      state: 'running',
    },
    {
      id: 'graph:satisfaction_node',
      timestamp: 3,
      group: 'response',
      label: 'Checking result',
      detail: 'Verifying the result',
      state: 'running',
    },
  ])

  assert.deepEqual(rows.map((step) => step.label), ['Understood request', 'Checking result'])
  assert.equal(rows[0].id, 'graph:semantic_intake_node')
  assert.equal(rows[0].state, 'success')
})

test('completed activity remains available as a collapsed summary', () => {
  assert.equal(shouldShowActivityTimeline([{
    id: 'activity_3',
    timestamp: 1710000002,
    group: 'response',
    label: 'Run complete',
    detail: 'All steps finished. See the thread below.',
    state: 'complete',
  }]), true)
})

test('friendly session status hides raw execution constants', () => {
  assert.equal(friendlySessionStatus('EXECUTING'), 'Checking')
  assert.equal(friendlySessionStatus('PLANNING'), 'Understanding')
  assert.equal(friendlySessionStatus('WAITING_APPROVAL'), 'Waiting for approval')
  assert.equal(friendlySessionStatus('COMPLETED'), 'Complete')
  assert.equal(friendlySessionStatus('EXECUTING', true), 'Working')
})

test('builds sanitized activity from snapshot timeline fallback', () => {
  const steps = buildActivityStepsFromTimeline([
    {
      event_type: 'user_message',
      content: 'show jobs',
      created_at: '2026-05-13T09:00:00Z',
    },
    {
      event_type: 'plan_created',
      content: 'planner_reentered',
      created_at: '2026-05-13T09:00:01Z',
      details: { node: 'planner_reentered' },
    },
    {
      event_type: 'tool_result',
      content: 'get__jobs completed.',
      created_at: '2026-05-13T09:00:02Z',
      tool_name: 'get__jobs_{id}',
      status: 'DONE',
      details: { args: { id: 1 }, result: { ok: true } },
    },
    {
      event_type: 'session_completed',
      content: 'Execution completed successfully.',
      created_at: '2026-05-13T09:00:03Z',
      status: 'COMPLETED',
    },
  ])

  assert.deepEqual(steps.map((step) => step.label), [
    'Understood request',
    'Checked job records',
    'Run complete',
  ])
  assert.equal(steps[1].detail, 'Checked job records')
  assert.equal(JSON.stringify(steps).includes('get__jobs'), false)
  assert.equal(JSON.stringify(steps).includes('planner_reentered'), false)
  assert.equal(JSON.stringify(steps).includes('DONE'), false)
})

test('groups repeated checked records and finalizes historical retry states', () => {
  const timeline = [
    {
      event_type: 'user_message',
      content: 'change all medium priority job to high',
      created_at: '2026-05-13T09:00:00Z',
    },
    ...Array.from({ length: 10 }, (_, idx) => ({
      event_type: 'tool_result',
      content: 'put__jobs_{id} completed.',
      created_at: `2026-05-13T09:00:${String(idx + 1).padStart(2, '0')}Z`,
      tool_name: 'put__jobs_{id}',
      status: 'DONE',
    })),
    {
      event_type: 'replan_requested',
      content: 'tool_rerun after approval',
      created_at: '2026-05-13T09:00:20Z',
    },
    {
      event_type: 'session_completed',
      content: 'Execution completed successfully.',
      created_at: '2026-05-13T09:00:21Z',
      status: 'COMPLETED',
    },
  ]

  const steps = buildActivityStepsFromTimeline(timeline)

  assert.deepEqual(steps.map((step) => step.label), [
    'Checked job records',
    'Improving the response',
    'Run complete',
  ])
  assert.equal(steps[0].detail, 'Checked job records (10 updates)')
  assert.equal(steps[1].state, 'success')
})

test('builds current activity from session status when timeline is delayed', () => {
  const executing = buildActivityStepsFromSnapshot({
    session: { status: 'EXECUTING' },
    steps: [{ status: 'IN_PROGRESS', tool_name: 'get__jobs_{id}' }],
    timeline: [],
  })

  assert.equal(executing.at(-1).label, 'Gathering information')
  assert.equal(executing.at(-1).detail, 'Checking job records')
  assert.equal(executing.at(-1).state, 'running')

  const completed = buildActivityStepsFromSnapshot({
    session: { status: 'COMPLETED' },
    steps: [],
    timeline: executing,
  })

  assert.equal(completed.at(-1).label, 'Run complete')
  assert.equal(completed.at(-1).state, 'complete')

  const waitingDup = buildActivityStepsFromSnapshot({
    session: { status: 'WAITING_APPROVAL' },
    steps: [],
    timeline: [
      {
        event_type: 'user_message',
        content: 'bulk update',
        created_at: '2026-05-13T09:00:00Z',
        turn_id: 't1',
      },
      {
        event_type: 'approval_required',
        content: 'Jobs affected:\n1. JOB-1',
        created_at: '2026-05-13T09:00:01Z',
        turn_id: 't1',
        approval_id: 'a1',
      },
    ],
  })
  const waitingLabels = waitingDup.filter((s) => s.label === 'Waiting for approval')
  assert.equal(waitingLabels.length, 1)
  assert.equal(waitingLabels[0].detail, null)
})

test('active approval resume suppresses stale completion rows before the next approval', () => {
  const steps = buildActivityStepsFromSnapshot({
    session: { status: 'EXECUTING' },
    steps: [],
    timeline: [
      {
        event_type: 'user_message',
        content: 'change high to low then low to medium',
        created_at: '2026-05-16T09:00:00Z',
        turn_id: 't1',
      },
      {
        event_type: 'approval_decided',
        content: 'Approved request to change record.',
        created_at: '2026-05-16T09:00:01Z',
        turn_id: 't1',
        status: 'APPROVED',
      },
      {
        event_type: 'session_completed',
        content: 'Execution completed successfully.',
        created_at: '2026-05-16T09:00:02Z',
        turn_id: 't1',
        status: 'COMPLETED',
      },
    ],
  })

  assert.equal(steps.some((step) => step.label === 'Run complete'), false)
  assert.equal(steps.at(-1).label, 'Applying approved changes')
  assert.equal(steps.at(-1).state, 'running')
})

test('second approval keeps activity waiting despite stale completion after approval one', () => {
  const steps = buildActivityStepsFromSnapshot({
    session: { status: 'WAITING_APPROVAL', plan_id: 'plan-so-001', operation_id: 'plan-so-001' },
    plan: { plan_id: 'plan-so-001' },
    pending_approval: { approval_id: 'approval-so-001-2' },
    steps: [],
    timeline: [
      {
        event_type: 'user_message',
        content: 'change all medium priority job to high then change all high priority job to medium',
        created_at: '2026-05-16T10:00:00.000Z',
        turn_id: 't1',
        operation_id: 'plan-so-001',
      },
      {
        event_type: 'approval_required',
        content: '2 medium priority jobs need approval.',
        created_at: '2026-05-16T10:00:01.000Z',
        turn_id: 't1',
        approval_id: 'approval-so-001-1',
        status: 'PENDING',
        operation_id: 'plan-so-001',
      },
      {
        event_type: 'approval_decided',
        content: 'Approval approval-so-001-1 accepted.',
        created_at: '2026-05-16T10:00:02.000Z',
        turn_id: 't1',
        approval_id: 'approval-so-001-1',
        status: 'APPROVED',
        operation_id: 'plan-so-001',
      },
      {
        event_type: 'session_completed',
        content: 'All requested changes completed.',
        created_at: '2026-05-16T10:00:03.000Z',
        turn_id: 't1',
        status: 'COMPLETED',
        operation_id: 'plan-so-001',
      },
      {
        event_type: 'approval_required',
        content: '1 original high priority job needs approval.',
        created_at: '2026-05-16T10:00:04.000Z',
        turn_id: 't1',
        approval_id: 'approval-so-001-2',
        status: 'PENDING',
        operation_id: 'plan-so-001',
      },
    ],
  })

  assert.equal(steps.some((step) => step.label === 'Run complete'), false)
  assert.equal(steps.at(-1).label, 'Waiting for approval')
  assert.equal(steps.at(-1).state, 'waiting')
})

test('pending approval suppresses later retry rows from stale snapshot projection', () => {
  const steps = buildActivityStepsFromSnapshot({
    session: { status: 'WAITING_APPROVAL', plan_id: 'plan-so-041', operation_id: 'plan-so-041' },
    plan: { plan_id: 'plan-so-041' },
    pending_approval: { approval_id: 'approval-so-041-2' },
    steps: [],
    timeline: [
      {
        event_type: 'user_message',
        content: 'change all medium priority job to high then change all high priority job to low',
        created_at: '2026-05-16T10:00:00.000Z',
        turn_id: 't1',
        operation_id: 'plan-so-041',
      },
      {
        event_type: 'approval_required',
        content: '10 medium jobs need approval.',
        created_at: '2026-05-16T10:00:01.000Z',
        turn_id: 't1',
        approval_id: 'approval-so-041-1',
        status: 'PENDING',
        operation_id: 'plan-so-041',
      },
      {
        event_type: 'approval_decided',
        content: 'Approval approval-so-041-1 accepted.',
        created_at: '2026-05-16T10:00:02.000Z',
        turn_id: 't1',
        approval_id: 'approval-so-041-1',
        status: 'APPROVED',
        operation_id: 'plan-so-041',
      },
      {
        event_type: 'approval_required',
        content: '11 high jobs need approval.',
        created_at: '2026-05-16T10:00:03.000Z',
        turn_id: 't1',
        approval_id: 'approval-so-041-2',
        status: 'PENDING',
        operation_id: 'plan-so-041',
      },
      {
        event_type: 'replan_requested',
        content: 'Refining after approval 1.',
        created_at: '2026-05-16T10:00:04.000Z',
        turn_id: 't1',
        operation_id: 'plan-so-041',
      },
    ],
  })

  assert.equal(steps.at(-1).label, 'Waiting for approval')
  assert.equal(steps.at(-1).state, 'waiting')
  assert.equal(steps.some((step) => step.label === 'Improving the response' && step.state === 'retry'), false)
})

test('server activity label for pending approval suppresses later retry rows', () => {
  const steps = stripPrematureTerminalActivitySteps([
    {
      id: 'activity-1',
      timestamp: 1,
      group: 'approval',
      label: 'Waiting for your approval',
      detail: 'Reviewing approval requirements',
      state: 'waiting',
    },
    {
      id: 'activity-2',
      timestamp: 2,
      group: 'planning',
      label: 'Improving the response',
      detail: 'Refining the response with updated information',
      state: 'retry',
    },
  ], 'WAITING_APPROVAL')

  assert.equal(steps.length, 1)
  assert.equal(steps.at(-1).label, 'Waiting for your approval')
  assert.equal(steps.at(-1).state, 'waiting')
})

test('uses full operation-scoped timeline across turns when operation_id matches plan', () => {
  const steps = buildActivityStepsFromSnapshot({
    session: { status: 'COMPLETED', plan_id: 'plan-1', operation_id: 'plan-1' },
    plan: { plan_id: 'plan-1' },
    steps: [],
    timeline: [
      { event_type: 'user_message', content: 'u1', created_at: '2026-05-14T10:00:00.000Z', turn_id: 't1' },
      {
        event_type: 'plan_created',
        content: 'plan',
        created_at: '2026-05-14T10:00:01.000Z',
        turn_id: 't1',
        details: { plan_id: 'plan-1' },
        operation_id: 'plan-1',
      },
      {
        event_type: 'execution_started',
        content: 'preparing',
        created_at: '2026-05-14T10:00:01.500Z',
        turn_id: 't1',
        operation_id: 'plan-1',
      },
      {
        event_type: 'approval_required',
        content: 'wait',
        created_at: '2026-05-14T10:00:02.000Z',
        turn_id: 't1',
        operation_id: 'plan-1',
      },
      {
        event_type: 'approval_decided',
        content: 'ok',
        created_at: '2026-05-14T10:00:03.000Z',
        turn_id: 't2',
        status: 'APPROVED',
        operation_id: 'plan-1',
      },
      {
        event_type: 'execution_started',
        content: 'resumed',
        created_at: '2026-05-14T10:00:03.500Z',
        turn_id: 't2',
        operation_id: 'plan-1',
      },
      {
        event_type: 'tool_result',
        content: 'a',
        created_at: '2026-05-14T10:00:04.000Z',
        turn_id: 't2',
        tool_name: 'put__jobs_{id}',
        status: 'DONE',
        operation_id: 'plan-1',
      },
      {
        event_type: 'tool_result',
        content: 'b',
        created_at: '2026-05-14T10:00:05.000Z',
        turn_id: 't2',
        tool_name: 'put__jobs_{id}',
        status: 'DONE',
        operation_id: 'plan-1',
      },
      {
        event_type: 'session_completed',
        content: 'done',
        created_at: '2026-05-14T10:00:06.000Z',
        turn_id: 't2',
        operation_id: 'plan-1',
      },
    ],
  })
  const labels = steps.map((s) => s.label)
  assert.ok(labels.includes('Understood request'))
  assert.ok(labels.includes('Preparing changes'))
  assert.ok(labels.includes('Waiting for approval'))
  assert.ok(labels.includes('Approval received'))
  assert.ok(labels.includes('Applying approved changes'))
  assert.ok(labels.includes('Updating job records'))
  assert.ok(labels.includes('Verifying result'))
  assert.ok(labels.includes('Run complete'))
})

test('retry and replan timeline remains append-only with distinct activity rows', () => {
  const initialTimeline = [
    {
      event_type: 'user_message',
      content: 'show machine status',
      created_at: '2026-05-18T09:00:00.000Z',
      turn_id: 't1',
      operation_id: 'op-retry',
    },
    {
      event_type: 'plan_created',
      content: 'plan',
      created_at: '2026-05-18T09:00:01.000Z',
      turn_id: 't1',
      operation_id: 'op-retry',
    },
    {
      event_type: 'execution_started',
      content: 'execute selected read',
      created_at: '2026-05-18T09:00:02.000Z',
      turn_id: 't1',
      operation_id: 'op-retry',
    },
    {
      event_type: 'tool_result',
      content: 'read timed out',
      created_at: '2026-05-18T09:00:03.000Z',
      turn_id: 't1',
      operation_id: 'op-retry',
      tool_name: 'get__machines_{id}',
      status: 'FAILED',
      details: { reason: 'tool_timeout' },
    },
  ]
  const retriedTimeline = [
    ...initialTimeline,
    {
      event_type: 'replan_requested',
      content: 'retry with updated evidence memory',
      created_at: '2026-05-18T09:00:04.000Z',
      turn_id: 't1',
      operation_id: 'op-retry',
      details: { reason: 'tool_timeout' },
    },
    {
      event_type: 'execution_started',
      content: 'retry selected read',
      created_at: '2026-05-18T09:00:05.000Z',
      turn_id: 't1',
      operation_id: 'op-retry',
    },
    {
      event_type: 'tool_result',
      content: 'read succeeded',
      created_at: '2026-05-18T09:00:06.000Z',
      turn_id: 't1',
      operation_id: 'op-retry',
      tool_name: 'get__machines_{id}',
      status: 'DONE',
    },
    {
      event_type: 'session_completed',
      content: 'done',
      created_at: '2026-05-18T09:00:07.000Z',
      turn_id: 't1',
      operation_id: 'op-retry',
    },
  ]

  const beforeRetry = buildActivityStepsFromTimeline(initialTimeline, {
    mode: 'operational',
    sessionStatus: 'EXECUTING',
  }).map((step) => step.label)
  const afterRetry = buildActivityStepsFromTimeline(retriedTimeline, {
    mode: 'operational',
    sessionStatus: 'COMPLETED',
  }).map((step) => step.label)

  assert.deepEqual(beforeRetry, [
    'Understood request',
    'Running selected tool',
    'Checking evidence',
  ])
  assert.deepEqual(afterRetry.slice(0, beforeRetry.length), beforeRetry)
  assert.deepEqual(afterRetry, [
    'Understood request',
    'Running selected tool',
    'Checking evidence',
    'Replanning',
    'Retrying tool',
    'Checking evidence',
    'Run complete',
  ])
  assert.equal(afterRetry.includes('Preparing changes'), false)
})

test('replan spine snapshot timeline shows attempt numbers and retry reason from diagnostics', () => {
  const steps = buildActivityStepsFromSnapshot({
    session: {
      status: 'COMPLETED',
      operation_id: 'op-retry-story',
      replan_context: {
        intent_contract: {
          replan_spine: {
            attempt_count: 1,
            max_attempts: 2,
            attempts: [
              {
                attempt: 1,
                missing_evidence_reasons: [
                  {
                    reason: 'tool_error',
                    requirement_id: 'req-machine-status',
                    evidence_refs: ['ev-timeout'],
                    retriable: true,
                  },
                ],
                failed_tool_calls: [
                  {
                    tool_name: 'get__machines_{id}',
                    args: { id: 'M-001', fields: 'status' },
                    requirement_id: 'req-machine-status',
                    evidence_ref: 'ev-timeout',
                    reason: 'tool_error',
                    attempt: 1,
                  },
                ],
              },
            ],
            missing_evidence_reasons: [
              {
                reason: 'tool_error',
                requirement_id: 'req-machine-status',
                evidence_refs: ['ev-timeout'],
                retriable: true,
              },
            ],
          },
        },
      },
    },
    timeline: [
      {
        event_type: 'user_message',
        content: 'show machine status',
        created_at: '2026-05-18T09:00:00.000Z',
        turn_id: 't1',
        operation_id: 'op-retry-story',
      },
      {
        event_type: 'plan_created',
        content: 'plan',
        created_at: '2026-05-18T09:00:01.000Z',
        turn_id: 't1',
        operation_id: 'op-retry-story',
      },
      {
        event_type: 'execution_started',
        content: 'execute selected read',
        created_at: '2026-05-18T09:00:02.000Z',
        turn_id: 't1',
        operation_id: 'op-retry-story',
      },
      {
        event_type: 'tool_result',
        content: 'read timed out',
        created_at: '2026-05-18T09:00:03.000Z',
        turn_id: 't1',
        operation_id: 'op-retry-story',
        tool_name: 'get__machines_{id}',
        status: 'FAILED',
        details: {
          args: { id: 'M-001', fields: 'status' },
          result: {
            status: 'tool_failed',
            status_code: 504,
            error: { code: 'tool_error', error_type: 'timeout' },
          },
        },
      },
      {
        event_type: 'replan_requested',
        content: 'retry with updated evidence memory',
        created_at: '2026-05-18T09:00:04.000Z',
        turn_id: 't1',
        operation_id: 'op-retry-story',
        details: { reason: 'tool_error' },
      },
      {
        event_type: 'execution_started',
        content: 'retry selected read',
        created_at: '2026-05-18T09:00:05.000Z',
        turn_id: 't1',
        operation_id: 'op-retry-story',
      },
      {
        event_type: 'tool_result',
        content: 'read succeeded',
        created_at: '2026-05-18T09:00:06.000Z',
        turn_id: 't1',
        operation_id: 'op-retry-story',
        tool_name: 'get__machines_{id}',
        status: 'DONE',
        details: { args: { id: 'M-001', fields: 'status' } },
      },
      {
        event_type: 'session_completed',
        content: 'done',
        created_at: '2026-05-18T09:00:07.000Z',
        turn_id: 't1',
        operation_id: 'op-retry-story',
      },
    ],
  })

  assert.deepEqual(steps.map((step) => step.label), [
    'Understood request',
    'Running selected tool',
    'Checking evidence',
    'Replanning after timeout',
    'Retrying machine status read',
    'Checking new evidence',
    'Run complete',
  ])
  assert.match(steps[1].detail, /Attempt 1 of 3/)
  assert.match(steps[2].detail, /Previous read timed out/)
  assert.match(steps[3].detail, /Attempt 2 of 3/)
  assert.match(steps.at(-1).detail, /Attempt 2 of 3/)
})

test('replan spine timeline collapses older retry attempts when retry budget is noisy', () => {
  const timeline = [
    {
      event_type: 'user_message',
      content: 'show machine status',
      created_at: '2026-05-18T09:00:00.000Z',
      operation_id: 'op-noisy-retry',
    },
    {
      event_type: 'plan_created',
      content: 'plan',
      created_at: '2026-05-18T09:00:01.000Z',
      operation_id: 'op-noisy-retry',
    },
  ]
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    timeline.push(
      {
        event_type: 'execution_started',
        content: `attempt ${attempt}`,
        created_at: `2026-05-18T09:00:${String(1 + attempt * 3).padStart(2, '0')}.000Z`,
        operation_id: 'op-noisy-retry',
      },
      {
        event_type: 'tool_result',
        content: 'read timed out',
        created_at: `2026-05-18T09:00:${String(2 + attempt * 3).padStart(2, '0')}.000Z`,
        operation_id: 'op-noisy-retry',
        tool_name: 'get__machines_{id}',
        status: 'FAILED',
        details: {
          args: { id: 'M-001', fields: 'status' },
          result: {
            status: 'tool_failed',
            error: { code: 'tool_error', error_type: 'timeout' },
          },
        },
      },
      {
        event_type: 'replan_requested',
        content: 'retry',
        created_at: `2026-05-18T09:00:${String(3 + attempt * 3).padStart(2, '0')}.000Z`,
        operation_id: 'op-noisy-retry',
      },
    )
  }
  timeline.push(
    {
      event_type: 'execution_started',
      content: 'final retry',
      created_at: '2026-05-18T09:00:20.000Z',
      operation_id: 'op-noisy-retry',
    },
    {
      event_type: 'session_blocked',
      content: 'blocked',
      created_at: '2026-05-18T09:00:21.000Z',
      operation_id: 'op-noisy-retry',
    },
  )

  const steps = buildActivityStepsFromTimeline(timeline, {
    mode: 'operational',
    sessionStatus: 'BLOCKED',
    replanSpine: {
      attempt_count: 5,
      max_attempts: 5,
      replan_limit_reached: true,
      attempts: [1, 2, 3, 4, 5].map((attempt) => ({
        attempt,
        missing_evidence_reasons: [{ reason: 'tool_error', evidence_refs: [`ev-${attempt}`], retriable: true }],
      })),
      missing_evidence_reasons: [{ reason: 'tool_error', evidence_refs: ['ev-1'], retriable: true }],
    },
  })

  const labels = steps.map((step) => step.label)
  assert.ok(labels.includes('Earlier retry attempts'))
  assert.match(steps.find((step) => step.label === 'Earlier retry attempts')?.detail || '', /4 earlier attempts collapsed/)
  assert.equal(labels.filter((label) => label.startsWith('Replanning')).length, 1)
  assert.match(steps.at(-2).detail || '', /Attempt 6 of 6/)
  assert.equal(steps.at(-1).label, 'Something needs attention')
})

test('active replan spine fallback keeps retry attempts uncollapsed while executing', () => {
  const timeline = [
    {
      event_type: 'user_message',
      content: 'show machine status',
      created_at: '2026-05-18T09:00:00.000Z',
      operation_id: 'op-active-retry',
    },
    {
      event_type: 'plan_created',
      content: 'plan',
      created_at: '2026-05-18T09:00:01.000Z',
      operation_id: 'op-active-retry',
    },
  ]
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    timeline.push(
      {
        event_type: 'execution_started',
        content: `attempt ${attempt}`,
        created_at: `2026-05-18T09:00:${String(1 + attempt * 3).padStart(2, '0')}.000Z`,
        operation_id: 'op-active-retry',
      },
      {
        event_type: 'tool_result',
        content: 'read timed out',
        created_at: `2026-05-18T09:00:${String(2 + attempt * 3).padStart(2, '0')}.000Z`,
        operation_id: 'op-active-retry',
        tool_name: 'get__machines_{id}',
        status: 'FAILED',
        details: {
          args: { id: 'M-001', fields: 'status' },
          result: {
            status: 'tool_failed',
            error: { code: 'tool_error', error_type: 'timeout' },
          },
        },
      },
      {
        event_type: 'replan_requested',
        content: 'retry',
        created_at: `2026-05-18T09:00:${String(3 + attempt * 3).padStart(2, '0')}.000Z`,
        operation_id: 'op-active-retry',
      },
    )
  }
  timeline.push({
    event_type: 'execution_started',
    content: 'current retry',
    created_at: '2026-05-18T09:00:18.000Z',
    operation_id: 'op-active-retry',
  })

  const steps = buildActivityStepsFromTimeline(timeline, {
    mode: 'operational',
    sessionStatus: 'EXECUTING',
    replanSpine: {
      attempt_count: 4,
      max_attempts: 5,
      attempts: [1, 2, 3, 4].map((attempt) => ({
        attempt,
        missing_evidence_reasons: [{ reason: 'tool_error', evidence_refs: [`ev-${attempt}`], retriable: true }],
      })),
      missing_evidence_reasons: [{ reason: 'tool_error', evidence_refs: ['ev-1'], retriable: true }],
    },
  })

  const labels = steps.map((step) => step.label)
  const details = steps.map((step) => step.detail || '')
  assert.equal(labels.includes('Earlier retry attempts'), false)
  assert.equal(labels.includes('Earlier activity'), false)
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    assert.ok(details.some((detail) => detail.startsWith(`Attempt ${attempt} of 6`)))
  }
  assert.equal(steps.at(-1).state, 'running')
})

test('completed approval snapshot uses post-approval progress when tool events are projected from plan steps', () => {
  const steps = buildActivityStepsFromSnapshot({
    session: { status: 'COMPLETED', plan_id: 'plan-final', operation_id: 'plan-final' },
    plan: { plan_id: 'plan-final' },
    steps: Array.from({ length: 9 }, (_, idx) => ({
      plan_id: 'plan-final',
      step_index: idx,
      status: 'DONE',
      tool_name: 'put__jobs_{id}',
    })),
    timeline: [
      { event_type: 'user_message', content: 'u1', created_at: '2026-05-14T10:00:00.000Z', turn_id: 't1' },
      {
        event_type: 'plan_created',
        content: 'approval bundle',
        created_at: '2026-05-14T10:00:00.010Z',
        turn_id: 't1',
        operation_id: 'plan-final',
        details: { plan_id: 'plan-approval', status: 'INVALIDATED' },
      },
      {
        event_type: 'plan_created',
        content: 'final answer',
        created_at: '2026-05-14T10:00:00.011Z',
        turn_id: 't1',
        operation_id: 'plan-final',
        details: { plan_id: 'plan-final', status: 'COMPLETED' },
      },
      {
        event_type: 'approval_required',
        content: 'wait',
        created_at: '2026-05-14T10:00:01.000Z',
        turn_id: 't1',
        status: 'PENDING',
        operation_id: 'plan-final',
      },
      {
        event_type: 'approval_decided',
        content: 'ok',
        created_at: '2026-05-14T10:00:02.000Z',
        turn_id: 't1',
        status: 'APPROVED',
        operation_id: 'plan-final',
      },
      {
        event_type: 'session_completed',
        content: 'done',
        created_at: '2026-05-14T10:00:05.000Z',
        turn_id: 't1',
        status: 'COMPLETED',
        operation_id: 'plan-final',
      },
    ],
  })

  const labels = steps.map((s) => s.label)
  assert.ok(labels.includes('Approval received'))
  assert.ok(labels.includes('Updating job records'))
  assert.ok(labels.includes('Run complete'))
  assert.equal(labels.includes('11 jobs will be updated from high to low priority.'), false)
})

test('widens plan scope when approval events use a different plan id than current operation', () => {
  const steps = buildActivityStepsFromSnapshot({
    session: { status: 'COMPLETED', plan_id: 'plan-final', operation_id: 'plan-final' },
    plan: { plan_id: 'plan-final' },
    steps: [],
    timeline: [
      { event_type: 'user_message', content: 'u', created_at: '2026-05-14T11:00:00.000Z', turn_id: 't1' },
      {
        event_type: 'plan_created',
        content: 'draft',
        created_at: '2026-05-14T11:00:00.500Z',
        turn_id: 't1',
        details: { plan_id: 'plan-prior' },
        operation_id: 'plan-prior',
      },
      {
        event_type: 'tool_result',
        content: 'lookup ok',
        created_at: '2026-05-14T11:00:01.000Z',
        turn_id: 't1',
        tool_name: 'get__jobs',
        status: 'DONE',
        operation_id: 'plan-prior',
      },
      {
        event_type: 'approval_required',
        content: 'approve bundle',
        created_at: '2026-05-14T11:00:01.500Z',
        turn_id: 't1',
        status: 'PENDING',
        details: { plan_id: 'plan-prior' },
        operation_id: 'plan-prior',
      },
      {
        event_type: 'approval_decided',
        content: 'ok',
        created_at: '2026-05-14T11:00:02.000Z',
        turn_id: 't1',
        status: 'APPROVED',
        details: { plan_id: 'plan-prior' },
        operation_id: 'plan-prior',
      },
      {
        event_type: 'plan_created',
        content: 'final',
        created_at: '2026-05-14T11:00:02.200Z',
        turn_id: 't1',
        details: { plan_id: 'plan-final' },
        operation_id: 'plan-final',
      },
      {
        event_type: 'tool_result',
        content: 'put ok',
        created_at: '2026-05-14T11:00:03.000Z',
        turn_id: 't1',
        tool_name: 'put__jobs_{id}',
        status: 'DONE',
        operation_id: 'plan-final',
      },
      {
        event_type: 'session_completed',
        content: 'done',
        created_at: '2026-05-14T11:00:04.000Z',
        turn_id: 't1',
        operation_id: 'plan-final',
      },
    ],
  })
  const labels = steps.map((s) => s.label)
  assert.ok(labels.includes('Waiting for approval'))
  assert.ok(labels.includes('Approval received'))
  assert.ok(labels.includes('Updating job records'))
  assert.ok(labels.includes('Run complete'))
})

test('injects execution summary when plan steps exist but timeline has no tool rows', () => {
  const steps = buildActivityStepsFromSnapshot({
    session: { status: 'COMPLETED' },
    plan: { plan_id: 'p1' },
    steps: [
      { plan_id: 'p1', status: 'DONE', tool_name: 'put__jobs_{id}' },
      { plan_id: 'p1', status: 'DONE', tool_name: 'put__jobs_{id}' },
    ],
    timeline: [
      {
        event_type: 'user_message',
        content: 'change priorities',
        created_at: '2026-05-14T10:00:00.000Z',
        turn_id: 'u1',
      },
      {
        event_type: 'plan_created',
        content: 'plan',
        created_at: '2026-05-14T10:00:01.000Z',
        turn_id: 'u1',
      },
      {
        event_type: 'session_completed',
        content: 'done',
        created_at: '2026-05-14T10:00:02.000Z',
        turn_id: 'u1',
        status: 'COMPLETED',
      },
    ],
  })
  const labels = steps.map((s) => s.label)
  assert.ok(labels.includes('Understood request'))
  assert.ok(labels.includes('Updating job records'))
  assert.ok(labels.includes('Run complete'))
  const info = steps.find((s) => s.label === 'Updating job records')
  assert.ok(String(info.detail || '').includes('job records'))
  assert.ok(String(info.detail || '').includes('2 updates'))
})

test('replan after session_completed is trimmed so the last row is the terminal step', () => {
  const steps = buildActivityStepsFromTimeline([
    {
      event_type: 'user_message',
      content: 'bulk',
      created_at: '2026-05-13T09:00:00Z',
      turn_id: 't1',
    },
    {
      event_type: 'replan_requested',
      content: 'first replan',
      created_at: '2026-05-13T09:00:05Z',
      turn_id: 't1',
    },
    {
      event_type: 'session_completed',
      content: 'done',
      created_at: '2026-05-13T09:00:10Z',
      turn_id: 't1',
      status: 'COMPLETED',
    },
    {
      event_type: 'replan_requested',
      content: 'Jobs affected:\n1. JOB-1',
      created_at: '2026-05-13T09:00:11Z',
      turn_id: 't1',
    },
  ])
  const last = steps[steps.length - 1]
  assert.equal(last.label, 'Run complete')
  assert.equal(last.state, 'complete')
  assert.equal(last.detail, 'All steps finished. See the thread below.')
})

test('snapshot fallback only uses the latest user turn', () => {
  const steps = buildActivityStepsFromSnapshot({
    session: { status: 'EXECUTING' },
    steps: [{ status: 'IN_PROGRESS', tool_name: 'get__machines' }],
    timeline: [
      {
        event_id: 'user:old',
        event_type: 'user_message',
        content: 'old request',
        created_at: '2026-05-13T09:00:00Z',
        turn_id: 'old',
      },
      {
        event_id: 'completed:old',
        event_type: 'session_completed',
        content: 'old answer',
        created_at: '2026-05-13T09:00:02Z',
        turn_id: 'old',
        status: 'COMPLETED',
      },
      {
        event_id: 'user:new',
        event_type: 'user_message',
        content: 'new request',
        created_at: '2026-05-13T09:01:00Z',
        turn_id: 'new',
      },
    ],
  })

  assert.equal(steps.some((step) => step.label === 'Run complete'), false)
  assert.equal(steps.at(-1).label, 'Gathering information')
  assert.equal(steps.at(-1).state, 'running')
})

test('terminal snapshot fallback uses full timeline across user turns', () => {
  const steps = buildActivityStepsFromSnapshot({
    session: { status: 'COMPLETED' },
    plan: null,
    steps: [],
    timeline: [
      { event_type: 'user_message', content: 'first', created_at: '2026-05-13T09:00:00Z', turn_id: 't1' },
      {
        event_type: 'plan_created',
        content: 'plan a',
        created_at: '2026-05-13T09:00:01Z',
        turn_id: 't1',
      },
      {
        event_type: 'tool_result',
        content: 'get__machines ok',
        created_at: '2026-05-13T09:00:02Z',
        turn_id: 't1',
        tool_name: 'get__machines_{id}',
        status: 'DONE',
      },
      {
        event_type: 'session_completed',
        content: 'done a',
        created_at: '2026-05-13T09:00:03Z',
        turn_id: 't1',
        status: 'COMPLETED',
      },
      { event_type: 'user_message', content: 'second', created_at: '2026-05-13T09:05:00Z', turn_id: 't2' },
      {
        event_type: 'plan_created',
        content: 'plan b',
        created_at: '2026-05-13T09:05:01Z',
        turn_id: 't2',
      },
      {
        event_type: 'session_completed',
        content: 'done b',
        created_at: '2026-05-13T09:05:02Z',
        turn_id: 't2',
        status: 'COMPLETED',
      },
    ],
  })
  // Latest-turn-only fallback would drop turn 1; merged plan rows still collapse to one "Understanding".
  assert.ok(steps.some((s) => s.label === 'Checked machine records'), 'turn 1 tool_result must be included')
  assert.ok(steps.some((s) => s.label === 'Understood request'))
  assert.equal(steps.at(-1).label, 'Run complete')
  assert.equal(steps.at(-1).state, 'complete')
})

test('typed rejected presentation suppresses stale completion activity', () => {
  const steps = buildActivityStepsFromSnapshot({
    session: { status: 'COMPLETED' },
    presentation: {
      kind: 'rejected',
      state: 'rejected',
      summary: 'Operator rejected the pending priority change.',
    },
    timeline: [
      {
        event_type: 'user_message',
        content: 'change priority',
        created_at: '2026-05-16T10:00:00Z',
        turn_id: 't1',
      },
      {
        event_type: 'session_completed',
        content: 'All requested changes completed.',
        created_at: '2026-05-16T10:00:02Z',
        turn_id: 't1',
        status: 'COMPLETED',
      },
    ],
  })

  assert.equal(steps.some((step) => step.label === 'Run complete'), false)
  assert.equal(steps.at(-1).label, 'Approval declined')
  assert.equal(steps.at(-1).state, 'error')
})

test('typed pending presentation keeps timeline waiting despite stale success and retry rows', () => {
  const steps = buildActivityStepsFromSnapshot({
    session: { status: 'COMPLETED' },
    presentation: {
      kind: 'approval_required',
      state: 'pending',
      summary: 'Approval is still pending.',
    },
    timeline: [
      {
        event_type: 'user_message',
        content: 'change priority',
        created_at: '2026-05-16T10:00:00Z',
        turn_id: 't1',
      },
      {
        event_type: 'session_completed',
        content: 'Run complete.',
        created_at: '2026-05-16T10:00:01Z',
        turn_id: 't1',
      },
      {
        event_type: 'replan_requested',
        content: 'Improving stale response.',
        created_at: '2026-05-16T10:00:02Z',
        turn_id: 't1',
      },
    ],
  })

  assert.equal(steps.some((step) => step.label === 'Run complete'), false)
  assert.equal(steps.some((step) => step.label === 'Improving the response'), false)
  assert.equal(steps.at(-1).label, 'Waiting for approval')
  assert.equal(steps.at(-1).state, 'waiting')
})

test('stripPrematureTerminalActivitySteps drops early terminal and stale trailing current rows while active', () => {
  const steps = stripPrematureTerminalActivitySteps([
    { id: '1', label: 'Understood request', state: 'success', group: 'planning', timestamp: 1 },
    { id: '2', label: 'Checking citations', state: 'running', group: 'response', timestamp: 2 },
    { id: '3', label: 'Run complete', state: 'complete', group: 'response', timestamp: 3 },
    { id: '4', label: 'Understanding your request', state: 'running', group: 'planning', timestamp: 4 },
  ], 'EXECUTING')

  assert.deepEqual(steps.map((step) => step.label), [
    'Understood request',
    'Checking citations',
  ])
  assert.equal(steps.some((step) => step.label === 'Run complete'), false)
  assert.equal(steps.some((step) => step.label === 'Understanding your request'), false)
})
