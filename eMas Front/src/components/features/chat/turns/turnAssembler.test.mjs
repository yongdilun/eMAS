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
