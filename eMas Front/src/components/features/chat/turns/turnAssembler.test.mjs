import assert from 'node:assert/strict'
import test from 'node:test'

import { assembleFactoryAgentTurns, computeFactoryAgentTurnSummary } from './turnAssembler.js'

const userEvent = {
  event_id: 'user:1',
  event_type: 'user_message',
  content: 'Check machine 5 status',
  created_at: '2026-05-13T09:35:35',
  role: 'user',
  turn_id: 'turn-1',
}

test('completed LangGraph plan without terminal event renders the plan summary', () => {
  const turns = assembleFactoryAgentTurns([
    userEvent,
    {
      event_id: 'plan:1',
      event_type: 'plan_created',
      content: 'Machine 5 was not found.',
      created_at: '2026-05-13T09:36:21',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'PLANNING',
      details: {
        status: 'COMPLETED',
        plan_explanation: 'Machine 5 was not found.',
      },
    },
    {
      event_id: 'step:1',
      event_type: 'tool_result',
      content: 'get__machines_{id} completed.',
      created_at: '2026-05-13T09:36:21',
      role: 'assistant',
      turn_id: 'turn-1',
      step_id: 'step-1',
      tool_name: 'get__machines_{id}',
      status: 'DONE',
      details: { result: null },
    },
  ])

  assert.equal(computeFactoryAgentTurnSummary(turns[0]), 'Machine 5 was not found.')
})

test('generic completion terminal prefers plan summary over generic tool result', () => {
  const turns = assembleFactoryAgentTurns([
    userEvent,
    {
      event_id: 'plan:1',
      event_type: 'plan_created',
      content: 'Machine 5 was not found.',
      created_at: '2026-05-13T09:36:21',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'PLANNING',
      details: {
        status: 'COMPLETED',
        plan_explanation: 'Machine 5 was not found.',
      },
    },
    {
      event_id: 'step:1',
      event_type: 'tool_result',
      content: 'get__machines_{id} completed.',
      created_at: '2026-05-13T09:36:21',
      role: 'assistant',
      turn_id: 'turn-1',
      step_id: 'step-1',
      tool_name: 'get__machines_{id}',
      status: 'DONE',
      details: { result: null },
    },
    {
      event_id: 'completed:1',
      event_type: 'session_completed',
      content: 'Execution completed successfully.',
      created_at: '2026-05-13T09:36:22',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
    },
  ])

  assert.equal(computeFactoryAgentTurnSummary(turns[0]), 'Machine 5 was not found.')
})

test('generic completion terminal keeps completed plan summary even when a tool card is available', () => {
  const turns = assembleFactoryAgentTurns([
    userEvent,
    {
      event_id: 'plan:1',
      event_type: 'plan_created',
      content: 'Plan created.',
      created_at: '2026-05-13T09:36:21',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'PLANNING',
      details: {
        status: 'COMPLETED',
        plan_explanation: 'Stream drop recovered by snapshot polling.',
      },
    },
    {
      event_id: 'step:1',
      event_type: 'tool_result',
      content: 'Machine M-CNC-01 is currently RUNNING.',
      created_at: '2026-05-13T09:36:21',
      role: 'assistant',
      turn_id: 'turn-1',
      step_id: 'step-1',
      tool_name: 'get__machines_{id}',
      status: 'DONE',
      details: {
        result: { data: { machine_id: 'M-CNC-01', status: 'RUNNING' } },
      },
    },
    {
      event_id: 'completed:1',
      event_type: 'session_completed',
      content: 'Execution completed successfully.',
      created_at: '2026-05-13T09:36:22',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
    },
  ])

  assert.equal(computeFactoryAgentTurnSummary(turns[0]), 'Stream drop recovered by snapshot polling.')
})

test('tool results with identical timestamps are ordered by step index', () => {
  const createdAt = '2026-05-13T09:36:21'
  const turns = assembleFactoryAgentTurns([
    userEvent,
    {
      event_id: 'step:final',
      event_type: 'tool_result',
      content: 'final rule summary',
      created_at: createdAt,
      role: 'assistant',
      turn_id: 'turn-1',
      step_id: 'step-final',
      tool_name: 'get__jobs',
      status: 'DONE',
      step_context: { step_index: 2 },
      details: { result: { data: [{ job_id: 'JOB-SEED-005', rule: 'expedite' }] } },
    },
    {
      event_id: 'step:first',
      event_type: 'tool_result',
      content: 'first read summary',
      created_at: createdAt,
      role: 'assistant',
      turn_id: 'turn-1',
      step_id: 'step-first',
      tool_name: 'get__jobs',
      status: 'DONE',
      step_context: { step_index: 0 },
      details: { result: { data: [{ job_id: 'JOB-SEED-005', priority: 'low' }] } },
    },
    {
      event_id: 'completed:1',
      event_type: 'session_completed',
      content: 'Execution completed successfully.',
      created_at: '2026-05-13T09:36:22',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
    },
  ])

  assert.equal(turns[0].tools.at(-1).content, 'final rule summary')
})

test('failed commit terminal prefers safe diagnostic over stale success plan text', () => {
  const turns = assembleFactoryAgentTurns([
    {
      ...userEvent,
      content: 'Run Phase 14 Go API 500 commit failure for JOB-SEED-001',
    },
    {
      event_id: 'approval:1-required',
      event_type: 'approval_required',
      content: '1 high priority job will be updated to medium.',
      created_at: '2026-05-13T09:36:20',
      role: 'assistant',
      turn_id: 'turn-1',
      approval_id: 'approval-so-029-1',
      status: 'PENDING',
    },
    {
      event_id: 'approval:1-decided',
      event_type: 'approval_decided',
      content: 'Approval approval-so-029-1 accepted.',
      created_at: '2026-05-13T09:36:21',
      role: 'assistant',
      turn_id: 'turn-1',
      approval_id: 'approval-so-029-1',
      status: 'APPROVED',
    },
    {
      event_id: 'step:1',
      event_type: 'tool_result',
      content: 'put__jobs_{id} failed: HTTP 500: database unavailable',
      created_at: '2026-05-13T09:36:22',
      role: 'assistant',
      turn_id: 'turn-1',
      step_id: 'step-1',
      tool_name: 'put__jobs_{id}',
      status: 'FAILED',
      details: {
        result: null,
        last_error: 'HTTP 500: database unavailable',
      },
    },
    {
      event_id: 'plan:stale-success',
      event_type: 'plan_created',
      content: '**Success**\n\nUpdated **1** job(s).\n\nPriority: **medium**',
      created_at: '2026-05-13T09:36:23',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
      details: {
        status: 'COMPLETED',
        plan_explanation:
          'Could not complete the requested job priority change because the Go API returned database unavailable. No job rows were changed and no audit rows were created. Please retry after the backend recovers.',
      },
    },
    {
      event_id: 'failed:1',
      event_type: 'session_failed',
      content: 'HTTP 500: database unavailable',
      created_at: '2026-05-13T09:36:24',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'FAILED',
    },
  ])

  const summary = computeFactoryAgentTurnSummary(turns[0])
  assert.match(summary, /Could not complete/)
  assert.match(summary, /database unavailable/)
  assert.match(summary, /Please retry/)
  assert.doesNotMatch(summary, /Updated \*\*1\*\* job/)
  assert.doesNotMatch(summary, /Priority: \*\*medium\*\*/)
})

test('cancelled terminal prefers operator cancellation over stale active plan text', () => {
  const turns = assembleFactoryAgentTurns([
    {
      ...userEvent,
      content: 'Start an active run that I will cancel',
    },
    {
      event_id: 'plan:active',
      event_type: 'plan_created',
      content: 'The run is active and can be cancelled.',
      created_at: '2026-05-13T09:36:21',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
      details: {
        status: 'COMPLETED',
        plan_explanation: 'The run is active and can be cancelled.',
      },
    },
    {
      event_id: 'failed:cancelled',
      event_type: 'session_failed',
      content: 'Run cancelled by operator request.',
      created_at: '2026-05-13T09:36:24',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'FAILED',
      details: { reason: 'cancelled_by_user' },
    },
  ])

  assert.equal(computeFactoryAgentTurnSummary(turns[0]), 'Run cancelled by operator request.')
})

test('empty completed terminal renders safe empty-response diagnostic', () => {
  const turns = assembleFactoryAgentTurns([
    {
      ...userEvent,
      content: 'Return an empty completed answer',
    },
    {
      event_id: 'plan:empty',
      event_type: 'plan_created',
      content: '',
      created_at: '2026-05-13T09:36:21',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
      details: {
        status: 'COMPLETED',
        plan_explanation: '',
      },
    },
    {
      event_id: 'completed:empty',
      event_type: 'session_completed',
      content: '',
      created_at: '2026-05-13T09:36:22',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
    },
  ])

  const summary = computeFactoryAgentTurnSummary(turns[0])
  assert.equal(
    summary,
    'Unable to render final response. The run completed, but the backend returned empty assistant content.',
  )
  assert.doesNotMatch(summary, /Execution completed/)
  assert.doesNotMatch(summary, /Previous answer/)
})

test('user-only in-flight turn uses semantic progress instead of internal intent text', () => {
  const turns = assembleFactoryAgentTurns([userEvent])

  assert.equal(computeFactoryAgentTurnSummary(turns[0]), 'Understanding your request...')
})

test('plan-only in-flight turn uses semantic progress', () => {
  const turns = assembleFactoryAgentTurns([
    userEvent,
    {
      event_id: 'plan:1',
      event_type: 'plan_created',
      content: 'Fetch low priority jobs.',
      created_at: '2026-05-13T09:36:21',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'PLANNING',
      details: {
        status: 'DRAFT',
        plan_explanation: 'Fetch low priority jobs.',
      },
    },
  ])

  assert.equal(computeFactoryAgentTurnSummary(turns[0]), 'Understanding your request...')
})

test('plan-like completed answer is replaced by result summary from tool rows', () => {
  const turns = assembleFactoryAgentTurns([
    {
      ...userEvent,
      content: 'find low priority job',
    },
    {
      event_id: 'plan:1',
      event_type: 'plan_created',
      content: 'Operators can find low priority jobs by executing the following plan:\n\n1. Fetch low priority jobs.\n\nRisk summary:\nBefore executing, review tool calls.',
      created_at: '2026-05-13T09:36:21',
      role: 'assistant',
      turn_id: 'turn-1',
      details: {
        status: 'COMPLETED',
        plan_explanation: 'Fetch low priority jobs.',
      },
    },
    {
      event_id: 'step:1',
      event_type: 'tool_result',
      content: '{"success":true,"data":[{"job_id":"JOB-SEED-005","priority":"low"},{"job_id":"JOB-SEED-009","priority":"low"}]}',
      created_at: '2026-05-13T09:36:21',
      role: 'assistant',
      turn_id: 'turn-1',
      step_id: 'step-1',
      tool_name: 'get__jobs',
      status: 'DONE',
      details: {
        args: { priority: 'low' },
        result: {
          success: true,
          data: [
            { job_id: 'JOB-SEED-005', priority: 'low' },
            { job_id: 'JOB-SEED-009', priority: 'low' },
          ],
        },
      },
    },
    {
      event_id: 'completed:1',
      event_type: 'session_completed',
      content: 'Operators can find low priority jobs by executing the following plan:\n\n1. Fetch low priority jobs.\n\nRisk summary:\nBefore executing, review tool calls.',
      created_at: '2026-05-13T09:36:22',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
    },
  ])

  assert.equal(
    computeFactoryAgentTurnSummary(turns[0]),
    'Found 2 low-priority jobs: JOB-SEED-005, JOB-SEED-009. Details are shown in the table below.',
  )
})

test('interrupt-style approval_required uses compact headline instead of full bundle', () => {
  const turns = assembleFactoryAgentTurns([
    userEvent,
    {
      event_id: 'tool:1',
      event_type: 'tool_result',
      content: 'done',
      created_at: '2026-05-13T09:36:20Z',
      role: 'assistant',
      turn_id: 'turn-1',
      step_id: 'step-1',
      tool_name: 'patch__jobs',
      status: 'DONE',
      details: {},
    },
    {
      event_id: 'appr:1',
      event_type: 'approval_required',
      content: `Jobs affected:
1. JOB-SEED-002 (priority set to high)

Current vs requested priority:
- JOB-SEED-002: priority set to high (from medium)`,
      created_at: '2026-05-13T09:36:21Z',
      role: 'assistant',
      turn_id: 'turn-1',
      approval_id: 'apr-1',
      tool_name: '__langgraph_commit__',
      status: 'PENDING',
    },
  ])

  const summary = computeFactoryAgentTurnSummary(turns[0])
  assert.match(summary, /1 job/)
  assert.match(summary, /will be updated/)
  assert.match(summary, /medium/)
  assert.match(summary, /high/)
  assert.equal(summary.includes('Jobs affected:'), false)
})

test('completed approval turn ignores invalidated approval bundle plan when plan timestamps tie', () => {
  const turns = assembleFactoryAgentTurns([
    {
      ...userEvent,
      content: 'change high priority jobs to low',
      created_at: '2026-05-14T10:00:00.000Z',
    },
    {
      event_id: 'plan:a-final',
      event_type: 'plan_created',
      content: 'Updated 11 jobs from high to low priority.',
      created_at: '2026-05-14T10:00:00.010Z',
      role: 'assistant',
      turn_id: 'turn-1',
      details: {
        plan_id: 'plan-final',
        status: 'COMPLETED',
        plan_explanation: 'Updated 11 jobs from high to low priority.',
      },
    },
    {
      event_id: 'plan:z-invalidated-approval-bundle',
      event_type: 'plan_created',
      content: '11 jobs will be updated from high to low priority.\n\nJob ID Previous Priority New Priority',
      created_at: '2026-05-14T10:00:00.010Z',
      role: 'assistant',
      turn_id: 'turn-1',
      details: {
        plan_id: 'plan-approval',
        status: 'INVALIDATED',
        plan_explanation: '11 jobs will be updated from high to low priority.',
      },
    },
    {
      event_id: 'approval:1',
      event_type: 'approval_required',
      content: 'Waiting for approval.',
      created_at: '2026-05-14T10:00:01.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      approval_id: 'approval-1',
      tool_name: '__langgraph_commit__',
      status: 'PENDING',
    },
    {
      event_id: 'completed:1',
      event_type: 'session_completed',
      content: 'Execution completed successfully.',
      created_at: '2026-05-14T10:00:05.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
    },
  ])

  assert.equal(computeFactoryAgentTurnSummary(turns[0]), 'Updated 11 jobs from high to low priority.')
})

test('completed approval turn prefers completed tool result over stale approval wait terminal text', () => {
  const turns = assembleFactoryAgentTurns([
    {
      ...userEvent,
      content: 'change low priority jobs to high',
      created_at: '2026-05-14T10:00:00.000Z',
    },
    {
      event_id: 'approval:1',
      event_type: 'approval_required',
      content: 'Waiting for your approval: 2 job(s) will be updated from LOW to HIGH priority.',
      created_at: '2026-05-14T10:00:01.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      approval_id: 'approval-1',
      tool_name: '__langgraph_commit__',
      status: 'PENDING',
    },
    {
      event_id: 'step:1',
      event_type: 'tool_result',
      content: 'Approved seeded change completed: JOB-SEED-005 is now high priority.',
      created_at: '2026-05-14T10:00:03.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      step_id: 'step-1',
      tool_name: 'put__jobs_{id}',
      status: 'DONE',
      details: {
        args: { id: 'JOB-SEED-005', priority: 'high' },
        result: {
          success: true,
          data: { job_id: 'JOB-SEED-005', priority: 'high' },
        },
      },
    },
    {
      event_id: 'completed:1',
      event_type: 'session_completed',
      content: '2 job(s) will be updated from LOW to HIGH priority.\n\nThe change list is shown in the in-app table below.',
      created_at: '2026-05-14T10:00:04.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
    },
  ])

  assert.equal(
    computeFactoryAgentTurnSummary(turns[0]),
    'Approved seeded change completed: JOB-SEED-005 is now high priority.',
  )
})

test('completed multi-approval turn does not let approval decision text outrank final response', () => {
  const turns = assembleFactoryAgentTurns([
    {
      ...userEvent,
      content: 'change all medium priority job to high then change all high priority job to low',
      created_at: '2026-05-16T10:00:00.000Z',
    },
    {
      event_id: 'completed:1',
      event_type: 'session_completed',
      content: '10 medium priority jobs changed to high\n11 original high priority jobs changed to low',
      created_at: '2026-05-16T10:00:05.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
    },
    {
      event_id: 'approval:2-decided',
      event_type: 'approval_decided',
      content: 'Approved request to change record.',
      created_at: '2026-05-16T10:00:06.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      approval_id: 'approval-so-041-2',
      status: 'APPROVED',
    },
  ])

  assert.equal(
    computeFactoryAgentTurnSummary(turns[0]),
    '10 medium priority jobs changed to high\n11 original high priority jobs changed to low',
  )
})

test('terminal typed presentation outranks later tool table presentations', () => {
  const finalSummary = '10 medium priority jobs changed to high\n11 original high priority jobs changed to low'
  const turns = assembleFactoryAgentTurns([
    {
      ...userEvent,
      content: 'change all medium priority job to high then change all high priority job to low',
      created_at: '2026-05-16T10:00:00.000Z',
    },
    {
      event_id: 'completed:1',
      event_type: 'session_completed',
      content: finalSummary,
      created_at: '2026-05-16T10:00:05.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
      presentation: {
        kind: 'mutation_result',
        state: 'completed',
        summary: finalSummary,
        rows: [
          { job_id: 'JOB-SEED-002', previous_priority: 'medium', priority: 'high' },
          { job_id: 'JOB-SEED-001', previous_priority: 'high', priority: 'low' },
        ],
      },
    },
    {
      event_id: 'step:late-read',
      event_type: 'tool_result',
      content: 'Found 11 high-priority jobs: JOB-SEED-001, JOB-SEED-003, +9 more. Details are shown in the table below.',
      created_at: '2026-05-16T10:00:06.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      step_id: 'step-late-read',
      tool_name: 'get__jobs',
      status: 'DONE',
      details: {
        args: { priority: 'high' },
        result: {
          success: true,
          data: [
            { job_id: 'JOB-SEED-001', priority: 'high' },
            { job_id: 'JOB-SEED-003', priority: 'high' },
          ],
        },
      },
      presentation: {
        kind: 'answer',
        state: 'completed',
        summary: 'Found 11 high-priority jobs: JOB-SEED-001, JOB-SEED-003, +9 more. Details are shown in the table below.',
        rows: [
          { job_id: 'JOB-SEED-001', priority: 'high' },
          { job_id: 'JOB-SEED-003', priority: 'high' },
        ],
      },
    },
  ])

  assert.equal(turns[0].presentation.kind, 'mutation_result')
  assert.equal(computeFactoryAgentTurnSummary(turns[0]), finalSummary)
})

test('new pending approval outranks stale terminal completion from previous approval', () => {
  const turns = assembleFactoryAgentTurns([
    {
      ...userEvent,
      content: 'change all medium priority job to high then change all high priority job to medium',
      created_at: '2026-05-16T10:00:00.000Z',
    },
    {
      event_id: 'approval:1-required',
      event_type: 'approval_required',
      content: '2 jobs will be updated from medium to high priority.',
      created_at: '2026-05-16T10:00:01.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      approval_id: 'approval-so-001-1',
      status: 'PENDING',
    },
    {
      event_id: 'approval:1-decided',
      event_type: 'approval_decided',
      content: 'Approval approval-so-001-1 accepted.',
      created_at: '2026-05-16T10:00:02.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      approval_id: 'approval-so-001-1',
      status: 'APPROVED',
    },
    {
      event_id: 'completed:stale-after-approval-1',
      event_type: 'session_completed',
      content: 'All requested changes completed.',
      created_at: '2026-05-16T10:00:03.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
    },
    {
      event_id: 'approval:2-required',
      event_type: 'approval_required',
      content: '1 job will be updated from high to medium priority.',
      created_at: '2026-05-16T10:00:04.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      approval_id: 'approval-so-001-2',
      status: 'PENDING',
      details: {
        args: {
          bundle_ui: {
            headline: '1 job will be updated from high to medium priority.',
          },
        },
      },
    },
  ])

  assert.equal(
    computeFactoryAgentTurnSummary(turns[0]),
    '1 job will be updated from high to medium priority.',
  )
})

test('typed pending approval renders from presentation despite changed approval wording', () => {
  const turns = assembleFactoryAgentTurns([
    userEvent,
    {
      event_id: 'appr:typed',
      event_type: 'approval_required',
      content: 'Operator gate is open for review.',
      created_at: '2026-05-16T10:00:01.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      approval_id: 'approval-typed-1',
      status: 'PENDING',
      presentation: {
        kind: 'approval_required',
        state: 'pending',
        approval_id: 'approval-typed-1',
        summary: 'Review the proposed job priority update.',
      },
    },
  ])

  assert.equal(computeFactoryAgentTurnSummary(turns[0]), 'Review the proposed job priority update.')
})

test('typed terminal states override stale success text', () => {
  const cases = [
    ['rejected', 'rejected', 'Operator rejected this request.'],
    ['expired', 'expired', 'Approval expired before execution.'],
    ['partial_failure', 'failed', 'Updated 1 job; 1 job failed validation.'],
    ['diagnostic', 'failed', 'The backend returned an empty final response.'],
  ]

  for (const [kind, state, summary] of cases) {
    const turns = assembleFactoryAgentTurns([
      {
        ...userEvent,
        turn_id: `turn-${kind}`,
      },
      {
        event_id: `completed:${kind}`,
        event_type: 'session_completed',
        content: 'All requested changes completed. Run complete.',
        created_at: '2026-05-16T10:00:02.000Z',
        role: 'assistant',
        turn_id: `turn-${kind}`,
        status: 'COMPLETED',
        details: {
          hidden_details: 'Updated **99** jobs successfully.',
        },
        presentation: {
          kind,
          state,
          summary,
          diagnostics: { reason: `${kind}_contract` },
        },
      },
    ])

    const actual = computeFactoryAgentTurnSummary(turns[0])
    assert.equal(actual, summary)
    assert.doesNotMatch(actual, /All requested changes completed|Updated \*\*99\*\* jobs/)
  }
})

test('typed failed diagnostic keeps richer safe recovery guidance when typed summary is terse', () => {
  const turns = assembleFactoryAgentTurns([
    userEvent,
    {
      event_id: 'plan:failed-guidance',
      event_type: 'plan_created',
      content: 'Intent: update job. Risk summary: approval required.',
      created_at: '2026-05-16T10:00:01.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      details: {
        status: 'COMPLETED',
        plan_explanation:
          'Could not complete the requested job priority update because the Go API returned HTTP 500: database unavailable. No job rows were changed and no audit rows were created. Please retry after the backend recovers.',
      },
    },
    {
      event_id: 'failed:typed',
      event_type: 'session_failed',
      content: 'HTTP 500: database unavailable',
      created_at: '2026-05-16T10:00:02.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'FAILED',
      presentation: {
        kind: 'diagnostic',
        state: 'failed',
        summary: 'HTTP 500: database unavailable',
        diagnostics: { reason: 'session_failed' },
      },
    },
  ])

  const summary = computeFactoryAgentTurnSummary(turns[0])
  assert.match(summary, /Could not complete/)
  assert.match(summary, /Please retry/)
  assert.doesNotMatch(summary, /Risk summary/)
})

test('typed mutation result provides stable affected rows when wording changes', () => {
  const turns = assembleFactoryAgentTurns([
    userEvent,
    {
      event_id: 'completed:mutation',
      event_type: 'session_completed',
      content: 'Done.',
      created_at: '2026-05-16T10:00:02.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
      presentation: {
        kind: 'mutation_result',
        state: 'completed',
        summary: 'Priority update finished.',
        rows: [
          { job_id: 'JOB-SEED-005', previous_priority: 'low', new_priority: 'high', outcome: 'updated' },
          { job_id: 'JOB-SEED-009', previous_priority: 'low', new_priority: 'high', outcome: 'updated' },
        ],
      },
    },
  ])

  assert.equal(computeFactoryAgentTurnSummary(turns[0]), 'Priority update finished.')
  assert.deepEqual(
    turns[0].typedTablePresentation.table.rows.map((row) => row.job_id),
    ['JOB-SEED-005', 'JOB-SEED-009'],
  )
})

test('typed knowledge answer carries sources independently of exact answer text', () => {
  const turns = assembleFactoryAgentTurns([
    userEvent,
    {
      event_id: 'completed:knowledge',
      event_type: 'session_completed',
      content: 'Guidance is ready.',
      created_at: '2026-05-16T10:00:02.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
      presentation: {
        kind: 'knowledge_answer',
        state: 'completed',
        summary: 'Follow the machine-specific LOTO notification procedure.',
        sources: [
          {
            source_number: 1,
            title: 'LOTO Procedure M-CNC-01',
            doc_id: 'LOTO-M-CNC-01',
            machine_id: 'M-CNC-01',
          },
        ],
      },
    },
  ])

  assert.equal(computeFactoryAgentTurnSummary(turns[0]), 'Follow the machine-specific LOTO notification procedure.')
  assert.equal(turns[0].sources[0].doc_id, 'LOTO-M-CNC-01')
})

test('snapshot response_document overrides stale presentation summary', () => {
  const turns = assembleFactoryAgentTurns([
    userEvent,
    {
      event_id: 'completed:stale',
      event_type: 'session_completed',
      content: 'All requested changes completed.',
      created_at: '2026-05-16T10:00:02.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
    },
  ], {
    snapshotPresentation: {
      kind: 'mutation_result',
      state: 'completed',
      summary: 'Stale presentation success.',
      rows: [{ job_id: 'JOB-STALE-001' }],
    },
    snapshotResponseDocument: {
      version: 1,
      id: 'rd-session-turn-1',
      document_id: 'rd-session-turn-1',
      turn_id: 'turn-1',
      revision: 7,
      revision_source: 'test',
      state: 'waiting_approval',
      status: 'waiting_approval',
      run_steps: [
        { step_id: 'approval-2', kind: 'approval', state: 'waiting', title: 'Waiting for approval 2', current: true },
      ],
      blocks: [
        {
          id: 'message:approval-2',
          type: 'short_message',
          message: 'Approval 2 is pending.',
          status: 'waiting_approval',
        },
      ],
    },
  })

  assert.equal(computeFactoryAgentTurnSummary(turns[0]), 'Approval 2 is pending.')
  assert.equal(turns[0].responseDocument.state, 'waiting_approval')
  assert.equal(turns[0].responseDocumentStatus, 'valid')
  assert.equal(turns[0].presentation, null)
})

test('invalid snapshot response_document becomes safe diagnostic instead of presentation fallback', () => {
  const turns = assembleFactoryAgentTurns([
    userEvent,
    {
      event_id: 'completed:stale',
      event_type: 'session_completed',
      content: 'All requested changes completed.',
      created_at: '2026-05-16T10:00:02.000Z',
      role: 'assistant',
      turn_id: 'turn-1',
      status: 'COMPLETED',
    },
  ], {
    snapshotPresentation: {
      kind: 'mutation_result',
      state: 'completed',
      summary: 'Stale presentation success.',
      rows: [{ job_id: 'JOB-STALE-001' }],
    },
    snapshotResponseDocument: {
      version: 1,
      state: 'completed',
      blocks: [],
    },
  })

  const summary = computeFactoryAgentTurnSummary(turns[0])
  assert.equal(summary, 'I could not render a valid response document for this run.')
  assert.equal(turns[0].responseDocumentStatus, 'invalid')
  assert.equal(turns[0].responseDocument.diagnostics.reason, 'response_document_invalid')
  assert.doesNotMatch(summary, /Stale presentation/)
  assert.equal(turns[0].presentation, null)
})
