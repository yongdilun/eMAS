import assert from 'node:assert/strict'
import test from 'node:test'
import {
  React,
  click,
  createViteSsrServer,
  installDom,
  render,
  waitFor,
} from '../../../../test/reactComponentTestUtils.mjs'

let server
let cleanupDom

test.before(async () => {
  cleanupDom = installDom()
  server = await createViteSsrServer()
})

test.after(async () => {
  await server?.close()
  cleanupDom?.()
})

const baseApproval = {
  approval_id: 'approval-1',
  subject_type: 'tool',
  tool_name: 'update_job_priority',
  side_effect_level: 'HIGH',
  risk_summary: 'This will update production job priority.',
  args: { job_id: 'JOB-1', priority: 'high', quantity: '12' },
}

const toolSchema = {
  name: 'update_job_priority',
  method: 'POST',
  endpoint: '/jobs/{job_id}',
  input_schema: {
    required: ['job_id', 'quantity'],
    properties: {
      job_id: { type: 'string' },
      priority: { type: 'string', enum: ['low', 'medium', 'high'] },
      quantity: { type: 'integer' },
    },
  },
}

test('ApprovalCard renders schema fields and submits cast approval args', async () => {
  const { factoryAgentApi } = await server.ssrLoadModule('/src/services/factoryAgentApi.js')
  factoryAgentApi.listTools = async () => [toolSchema]
  const { default: ApprovalCard } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/ApprovalCard.jsx')

  let approvedArgs = null
  const view = await render(
    React.createElement(ApprovalCard, {
      approval: baseApproval,
      reason: '',
      onReasonChange: () => {},
      onApprove: (args) => {
        approvedArgs = args
      },
      onReject: () => {},
      deciding: false,
    }),
  )

  await waitFor(() => assert.match(view.text(), /job ID \*/))
  assert.match(view.text(), /Approval required/)
  assert.match(view.text(), /This will update production job priority/)

  await click(Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent === 'Approve'))

  assert.equal(approvedArgs.job_id, 'JOB-1')
  assert.equal(approvedArgs.priority, 'high')
  assert.equal(approvedArgs.quantity, 12)

  await view.unmount()
})

test('ApprovalCard blocks approve when required schema fields are missing', async () => {
  const { factoryAgentApi } = await server.ssrLoadModule('/src/services/factoryAgentApi.js')
  factoryAgentApi.listTools = async () => [toolSchema]
  const { default: ApprovalCard } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/ApprovalCard.jsx')

  let approveCount = 0
  const view = await render(
    React.createElement(ApprovalCard, {
      approval: { ...baseApproval, approval_id: 'approval-2', args: { job_id: '', priority: 'high' } },
      reason: '',
      onReasonChange: () => {},
      onApprove: () => {
        approveCount += 1
      },
      onReject: () => {},
      deciding: false,
    }),
  )

  await waitFor(() => assert.match(view.text(), /job ID \*/))
  await click(Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent === 'Approve'))

  assert.equal(approveCount, 0)
  assert.match(view.text(), /job ID is required/)
  assert.match(view.text(), /quantity is required/)

  await view.unmount()
})
