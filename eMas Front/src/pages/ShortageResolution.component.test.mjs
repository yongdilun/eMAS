import assert from 'node:assert/strict'
import test from 'node:test'
import {
  React,
  act,
  click,
  createViteSsrServer,
  installDom,
  render,
  waitFor,
} from '../test/reactComponentTestUtils.mjs'

let server
let cleanupDom
let originalFetch

test.before(async () => {
  cleanupDom = installDom()
  server = await createViteSsrServer()
  originalFetch = globalThis.fetch
})

test.after(async () => {
  globalThis.fetch = originalFetch
  await server?.close()
  cleanupDom?.()
})

function batchSummary() {
  return {
    material_replenishment_aggregate: [
      {
        material_id: 'MAT-010',
        material_name: 'M8 Hex Bolt',
        recommended_qty: 25,
        suggested_arrive_at: '2026-06-20T08:00:00.000Z',
        affected_job_ids: ['JOB-001', 'JOB-002'],
      },
    ],
  }
}

function seedProposals() {
  return [{ proposal_id: 'AIPROP-001', job_id: 'JOB-001', feasible: false }]
}

async function setFieldValue(field, value) {
  await act(async () => {
    const previous = field.value
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set
    if (setter) setter.call(field, value)
    else field.value = value
    field._valueTracker?.setValue(previous)
    field.dispatchEvent(new Event('input', { bubbles: true }))
    field.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

async function setSelectValue(field, value) {
  await act(async () => {
    const previous = field.value
    const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value')?.set
    if (setter) setter.call(field, value)
    else field.value = value
    field._valueTracker?.setValue(previous)
    field.dispatchEvent(new Event('input', { bubbles: true }))
    field.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

function checkbox(container, label) {
  const node = container.querySelector(`input[aria-label="${label}"]`)
  assert.ok(node, `Expected checkbox ${label}`)
  return node
}

function input(container, label) {
  const node = container.querySelector(`input[aria-label="${label}"]`)
  assert.ok(node, `Expected input ${label}`)
  return node
}

function select(container, label) {
  const node = container.querySelector(`select[aria-label="${label}"]`)
  assert.ok(node, `Expected select ${label}`)
  return node
}

function button(container, label) {
  const node = Array.from(container.querySelectorAll('button')).find((candidate) =>
    candidate.textContent.replace(/\s+/g, ' ').trim() === label ||
    candidate.getAttribute('aria-label') === label
  )
  assert.ok(node, `Expected button ${label}`)
  return node
}

async function renderShortageResolution({ fetchImpl, props = {} } = {}) {
  const { default: ShortageResolution } = await server.ssrLoadModule('/src/pages/ShortageResolution.jsx')
  const { ToastProvider } = await server.ssrLoadModule('/src/context/ToastContext.jsx')
  globalThis.fetch = fetchImpl || (async (url, options = {}) => {
    const path = new URL(String(url)).pathname
    if (path.endsWith('/ai/scheduling/apply-replenishment-batch')) {
      return jsonResponse({ success: true, data: { any_new_records: true, created_arrivals: [] } })
    }
    if (path.endsWith('/ai/scheduling/reschedule-all')) {
      return jsonResponse({ success: true, data: { proposals: seedProposals(), summary: batchSummary() } })
    }
    return jsonResponse({ success: true, data: [] })
  })

  return render(
    React.createElement(
      ToastProvider,
      null,
      React.createElement(ShortageResolution, {
        embedded: true,
        seedProposals: seedProposals(),
        batchSummary: batchSummary(),
        onClose: () => {},
        ...props,
      }),
    ),
  )
}

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    text: async () => JSON.stringify(body),
  }
}

test('ShortageResolution renders only material aggregate rows', async () => {
  const view = await renderShortageResolution()

  await waitFor(() => {
    assert.equal(checkbox(view.container, 'Include MAT-010').checked, true)
    assert.equal(view.container.querySelectorAll('[data-shortage-line-kind="schedule_production"]').length, 0)
    assert.equal(view.container.textContent.includes('P-007'), false)
  })

  await view.unmount()
})

test('ShortageResolution applies only selected aggregate rows with edited values', async () => {
  const calls = []
  const view = await renderShortageResolution({
    fetchImpl: async (url, options = {}) => {
      const path = new URL(String(url)).pathname
      if (path.endsWith('/ai/scheduling/apply-replenishment-batch')) {
        calls.push({ path, body: JSON.parse(options.body) })
        return jsonResponse({ success: true, data: { any_new_records: true, created_arrivals: [{}] } })
      }
      if (path.endsWith('/ai/scheduling/reschedule-all')) {
        calls.push({ path, body: JSON.parse(options.body) })
        return jsonResponse({ success: true, data: { proposals: seedProposals(), summary: batchSummary() } })
      }
      return jsonResponse({ success: true, data: [] })
    },
  })

  await waitFor(() => assert.equal(checkbox(view.container, 'Include MAT-010').checked, true))
  await setFieldValue(input(view.container, 'Quantity for MAT-010'), '40')
  await setFieldValue(input(view.container, 'Arrival time for MAT-010'), '2026-06-23T10:15')
  await click(button(view.container, 'Apply and Replan'))

  await waitFor(() => assert.equal(calls.some((call) => call.path.endsWith('/ai/scheduling/reschedule-all')), true))
  const applyCall = calls.find((call) => call.path.endsWith('/ai/scheduling/apply-replenishment-batch'))
  assert.ok(applyCall)
  assert.deepEqual(applyCall.body.suggestions.map((row) => row.material_id), ['MAT-010'])
  assert.equal(applyCall.body.suggestions[0].quantity, 40)
  assert.equal(applyCall.body.suggestions[0].option_type, undefined)
  assert.match(applyCall.body.suggestions[0].arrive_at, /^2026-06-23T/)

  await view.unmount()
})

test('ShortageResolution keeps applying follow-up material aggregate rows until shortage is clear', async () => {
  const calls = []
  const finalResponses = []
  let rescheduleCount = 0
  const view = await renderShortageResolution({
    props: {
      onApplySuccess: (resp) => finalResponses.push(resp),
    },
    fetchImpl: async (url, options = {}) => {
      const path = new URL(String(url)).pathname
      if (path.endsWith('/ai/scheduling/apply-replenishment-batch')) {
        calls.push({ path, body: JSON.parse(options.body) })
        return jsonResponse({ success: true, data: { any_new_records: true, created_arrivals: [{}] } })
      }
      if (path.endsWith('/ai/scheduling/reschedule-all')) {
        rescheduleCount += 1
        calls.push({ path, body: JSON.parse(options.body) })
        if (rescheduleCount === 1) {
          return jsonResponse({
            success: true,
            data: {
              proposals: [
                {
                  proposal_id: 'AIPROP-002',
                  job_id: 'JOB-002',
                  feasible: false,
                  blocked_reasons: ['reason_code=material_shortage'],
                },
              ],
              summary: {
                blocked: 1,
                material_replenishment_aggregate: [
                  {
                    material_id: 'MAT-011',
                    material_name: 'O-Ring Kit',
                    recommended_qty: 8,
                    suggested_arrive_at: '2026-06-21T08:00:00.000Z',
                    affected_job_ids: ['JOB-002'],
                  },
                ],
              },
            },
          })
        }
        return jsonResponse({
          success: true,
          data: {
            proposals: [
              {
                proposal_id: 'AIPROP-002',
                job_id: 'JOB-002',
                feasible: true,
                proposed_slots: [{ scheduled_start: '2026-06-21T09:00:00.000Z' }],
              },
            ],
            summary: {
              blocked: 0,
              material_replenishment_aggregate: [],
            },
          },
        })
      }
      return jsonResponse({ success: true, data: [] })
    },
  })

  await waitFor(() => assert.equal(checkbox(view.container, 'Include MAT-010').checked, true))
  await click(button(view.container, 'Apply and Replan'))

  await waitFor(() => assert.equal(calls.filter((call) => call.path.endsWith('/ai/scheduling/apply-replenishment-batch')).length, 2))
  await waitFor(() => assert.equal(finalResponses.length, 1))

  const applyCalls = calls.filter((call) => call.path.endsWith('/ai/scheduling/apply-replenishment-batch'))
  assert.deepEqual(applyCalls[0].body.suggestions.map((row) => row.material_id), ['MAT-010'])
  assert.deepEqual(applyCalls[1].body.suggestions.map((row) => row.material_id), ['MAT-011'])
  assert.equal(calls.filter((call) => call.path.endsWith('/ai/scheduling/reschedule-all')).length, 2)
  assert.equal(finalResponses[0].data.summary.blocked, 0)
  assert.deepEqual(finalResponses[0].data.summary.material_replenishment_aggregate, [])

  await view.unmount()
})

test('ShortageResolution can remove a recommendation and add an existing material line', async () => {
  const calls = []
  const view = await renderShortageResolution({
    fetchImpl: async (url, options = {}) => {
      const path = new URL(String(url)).pathname
      if (path.endsWith('/inventory/materials')) {
        return jsonResponse({ success: true, data: [{ material_id: 'MAT-011', material_name: 'O-Ring Kit' }] })
      }
      if (path.endsWith('/ai/scheduling/apply-replenishment-batch')) {
        calls.push({ path, body: JSON.parse(options.body) })
        return jsonResponse({ success: true, data: { any_new_records: true, created_arrivals: [{}] } })
      }
      if (path.endsWith('/ai/scheduling/reschedule-all')) {
        return jsonResponse({ success: true, data: { proposals: seedProposals(), summary: batchSummary() } })
      }
      return jsonResponse({ success: true, data: [] })
    },
  })

  await waitFor(() => assert.ok(button(view.container, 'Remove MAT-010')))
  await click(button(view.container, 'Remove MAT-010'))
  await click(button(view.container, 'Add line'))
  await waitFor(() => assert.ok(select(view.container, 'Material')))
  await setSelectValue(select(view.container, 'Material'), 'MAT-011')
  await setFieldValue(input(view.container, 'New line quantity'), '7')
  await setFieldValue(input(view.container, 'New line arrival time'), '2026-06-24T12:00')
  await click(button(view.container, 'Add selected line'))
  await click(button(view.container, 'Apply and Replan'))

  await waitFor(() => assert.equal(calls.length, 1))
  assert.deepEqual(calls[0].body.suggestions.map((row) => row.material_id), ['MAT-011'])
  assert.equal(calls[0].body.suggestions[0].quantity, 7)
  assert.equal(calls[0].body.suggestions[0].option_type, undefined)

  await view.unmount()
})
