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

test('user-only in-flight turn shows intent progress instead of generic working', () => {
  const turns = assembleFactoryAgentTurns([userEvent])

  assert.equal(computeFactoryAgentTurnSummary(turns[0]), 'Splitting intent...')
})

test('plan-only in-flight turn shows planning progress', () => {
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

  assert.equal(computeFactoryAgentTurnSummary(turns[0]), 'Planning...')
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
