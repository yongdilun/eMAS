import assert from 'node:assert/strict'
import test from 'node:test'
import { act } from 'react'
import { Simulate } from 'react-dom/test-utils'
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

const createJobToolSchema = {
  name: 'post__jobs',
  method: 'POST',
  endpoint: '/jobs',
  input_schema: {
    required: ['product_id', 'quantity_total'],
    properties: {
      product_id: { type: 'string', 'x-ai-entity': 'product', 'x-ai-id-field': 'product_id' },
      quantity_total: { type: 'integer' },
      deadline: { type: 'string' },
      priority: { type: 'string', enum: ['low', 'medium', 'high', 'urgent'] },
      slots: {
        description: 'optional split slots',
        type: 'array',
        items: {
          type: 'object',
          properties: {
            machine_id: { type: 'string' },
            start_time: { type: 'string' },
            duration_mins: { type: 'integer' },
            quantity: { type: 'integer' },
          },
        },
      },
    },
  },
}

async function changeValue(element, value) {
  assert.ok(element, 'Expected element to change')
  await act(async () => {
    const descriptor = Object.getOwnPropertyDescriptor(element.constructor.prototype, 'value')
    if (descriptor?.set) descriptor.set.call(element, value)
    else element.value = value
    Simulate.change(element, { target: { value } })
  })
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

test('ApprovalCard uses product records for create-job product choice and hides scheduler-managed slots', async () => {
  const { factoryAgentApi } = await server.ssrLoadModule('/src/services/factoryAgentApi.js')
  factoryAgentApi.listTools = async () => [createJobToolSchema]
  const originalFetch = globalThis.fetch
  const fetchedUrls = []
  globalThis.fetch = async (url) => {
    fetchedUrls.push(String(url))
    if (String(url).includes('/products')) {
      return {
        ok: true,
        json: async () => ({
          data: [
            { productID: 'P-001', productName: 'Precision Gear', productType: 'Mechanical Parts' },
            { productID: 'P-002', productName: 'Valve Assembly', productType: 'Assembly / Sub-assembly' },
          ],
        }),
      }
    }
    return {
      ok: true,
      json: async () => ({ data: ['Assembly / Sub-assembly', 'Chemical / Fluid'] }),
    }
  }

  try {
    const { default: ApprovalCard } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/ApprovalCard.jsx')
    const view = await render(
      React.createElement(ApprovalCard, {
        approval: {
          approval_id: 'approval-create-job',
          subject_type: 'graph',
          tool_name: 'post__jobs',
          side_effect_level: 'HIGH',
          risk_summary: 'Approve 1 backend write: post__jobs',
          args: {},
        },
        reason: '',
        onReasonChange: () => {},
        onApprove: () => {},
        onReject: () => {},
        deciding: false,
      }),
    )

    await waitFor(() => {
      assert.match(view.text(), /Product \*/)
      const options = Array.from(view.container.querySelectorAll('select option')).map((option) => option.textContent)
      assert.ok(options.includes('Precision Gear (P-001)'))
    })

    assert.doesNotMatch(view.text(), /\bslots\b/i)
    assert.doesNotMatch(view.text(), /Assembly \/ Sub-assembly/)
    assert.ok(fetchedUrls.some((url) => url.includes('/products')))

    await view.unmount()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('ApprovalCard keeps in-progress create-job edits when same approval refreshes', async () => {
  const { factoryAgentApi } = await server.ssrLoadModule('/src/services/factoryAgentApi.js')
  factoryAgentApi.listTools = async () => [createJobToolSchema]
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url) => {
    if (String(url).includes('/products')) {
      return {
        ok: true,
        json: async () => ({
          data: [
            { productID: 'P-001', productName: 'Precision Gear' },
            { productID: 'P-002', productName: 'Valve Assembly' },
          ],
        }),
      }
    }
    return { ok: true, json: async () => ({ data: [] }) }
  }

  const approvalFor = (args = {}) => ({
    approval_id: 'approval-create-job-edit',
    subject_type: 'graph',
    tool_name: 'post__jobs',
    side_effect_level: 'HIGH',
    risk_summary: 'Approve 1 backend write: post__jobs',
    args,
  })

  try {
    const { default: ApprovalCard } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/ApprovalCard.jsx')
    const props = {
      reason: '',
      onReasonChange: () => {},
      onApprove: () => {},
      onReject: () => {},
      deciding: false,
    }
    const view = await render(
      React.createElement(ApprovalCard, {
        ...props,
        approval: approvalFor({}),
      }),
    )

    await waitFor(() => {
      const options = Array.from(view.container.querySelectorAll('select option')).map((option) => option.textContent)
      assert.ok(options.includes('Precision Gear (P-001)'))
    })

    const productSelect = view.container.querySelector('select[id$="-product_id"]')
    const quantityInput = view.container.querySelector('input[id$="-quantity_total"]')
    await changeValue(productSelect, 'P-001')
    await changeValue(quantityInput, '25')

    assert.equal(productSelect.value, 'P-001')
    assert.equal(quantityInput.value, '25')

    await view.rerender(
      React.createElement(ApprovalCard, {
        ...props,
        approval: approvalFor({ preview_details: { manual_input_required: true } }),
      }),
    )

    assert.equal(view.container.querySelector('select[id$="-product_id"]').value, 'P-001')
    assert.equal(view.container.querySelector('input[id$="-quantity_total"]').value, '25')

    await view.unmount()
  } finally {
    globalThis.fetch = originalFetch
  }
})
