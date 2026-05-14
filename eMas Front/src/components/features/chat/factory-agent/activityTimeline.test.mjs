import assert from 'node:assert/strict'
import test from 'node:test'

import {
  friendlySessionStatus,
  buildActivityStepsFromSnapshot,
  buildActivityStepsFromTimeline,
  mergeActivityStep,
  normalizeActivityStep,
  shouldAutoCollapseActivity,
  shouldShowActivityTimeline,
} from './activityTimelineUtils.js'

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
    label: 'Finalizing answer',
    state: 'complete',
  })

  assert.equal(merged.length, 2)
  assert.equal(shouldAutoCollapseActivity(merged), true)
})

test('completed activity remains available as a collapsed summary', () => {
  assert.equal(shouldShowActivityTimeline([{
    id: 'activity_3',
    timestamp: 1710000002,
    group: 'response',
    label: 'Finalizing answer',
    detail: 'Ready to show the answer',
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
    'Understanding your request',
    'Information checked',
    'Finalizing answer',
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
    'Information checked',
    'Improving the response',
    'Finalizing answer',
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

  assert.equal(completed.at(-1).label, 'Finalizing answer')
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
  assert.ok(labels.includes('Understanding your request'))
  assert.ok(labels.includes('Preparing changes'))
  assert.ok(labels.includes('Waiting for approval'))
  assert.ok(labels.includes('Approval received'))
  assert.ok(labels.includes('Applying approved changes'))
  assert.ok(labels.includes('Updating job records'))
  assert.ok(labels.includes('Verifying result'))
  assert.ok(labels.includes('Finalizing answer'))
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
  assert.ok(labels.includes('Finalizing answer'))
  assert.equal(labels.includes('11 jobs will be updated from high to low priority.'), false)
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
  assert.ok(labels.includes('Understanding your request'))
  assert.ok(labels.includes('Updating job records'))
  assert.ok(labels.includes('Finalizing answer'))
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
  assert.equal(last.label, 'Finalizing answer')
  assert.equal(last.state, 'complete')
  assert.equal(last.detail, 'Ready to show the answer')
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

  assert.equal(steps.some((step) => step.label === 'Finalizing answer'), false)
  assert.equal(steps.at(-1).label, 'Gathering information')
  assert.equal(steps.at(-1).state, 'running')
})
