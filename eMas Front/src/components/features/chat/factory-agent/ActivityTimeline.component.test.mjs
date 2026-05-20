import assert from 'node:assert/strict'
import test from 'node:test'
import {
  React,
  click,
  createViteSsrServer,
  flushEffects,
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

test('ActivityTimeline expands active multi-step runs and marks the current row', async () => {
  const { default: ActivityTimeline } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/ActivityTimeline.jsx')
  const view = await render(
    React.createElement(ActivityTimeline, {
      steps: [
        {
          id: 'step-1',
          timestamp: 1,
          group: 'planning',
          label: 'Understanding your request',
          detail: 'Reviewing recent context',
          state: 'success',
        },
        {
          id: 'step-2',
          timestamp: 2,
          group: 'approval',
          label: 'Waiting for approval',
          detail: null,
          state: 'waiting',
        },
      ],
    }),
  )

  await waitFor(() => assert.match(view.text(), /Session activity/))
  assert.match(view.text(), /Understanding your request/)
  assert.match(view.text(), /Waiting for approval/)
  assert.match(view.text(), /Current/)

  await view.unmount()
})

test('ActivityTimeline renders completed runs as a collapsed latest-step summary', async () => {
  const { default: ActivityTimeline } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/ActivityTimeline.jsx')
  const view = await render(
    React.createElement(ActivityTimeline, {
      steps: [
        {
          id: 'step-1',
          timestamp: 1,
          group: 'research',
          label: 'Updating job records',
          detail: 'Checked job records',
          state: 'success',
        },
        {
          id: 'step-2',
          timestamp: 2,
          group: 'response',
          label: 'Run complete',
          detail: 'All steps finished. See the thread below.',
          state: 'complete',
        },
      ],
    }),
  )

  assert.match(view.text(), /Run complete/)
  assert.match(view.text(), /All steps finished/)
  assert.doesNotMatch(view.text(), /Updating job records/)

  await click(view.container.querySelector('button'))
  assert.match(view.text(), /Updating job records/)

  await view.unmount()
})

test('ActivityTimeline keeps the latest successful action spinning until the run completes', async () => {
  const { default: ActivityTimeline } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/ActivityTimeline.jsx')
  const view = await render(
    React.createElement(ActivityTimeline, {
      steps: [
        {
          id: 'step-1',
          timestamp: 1,
          group: 'research',
          label: 'Checking knowledge sources',
          detail: 'Searching source documents',
          state: 'success',
        },
      ],
    }),
  )

  const spinnerIcon = view.container.querySelector('[data-icon="progress_activity"]')
  assert.ok(spinnerIcon)
  assert.match(spinnerIcon.className, /animate-spin/)
  assert.equal(view.container.querySelector('[data-icon="check"]'), null)

  await view.unmount()
})

test('ActivityTimeline respects manual collapse while active rows refresh', async () => {
  const { default: ActivityTimeline } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/ActivityTimeline.jsx')
  const activeSteps = [
    {
      id: 'step-1',
      timestamp: 1,
      group: 'planning',
      label: 'Understanding your request',
      detail: 'Reviewing recent context',
      state: 'success',
    },
    {
      id: 'step-2',
      timestamp: 2,
      group: 'approval',
      label: 'Waiting for approval',
      detail: null,
      state: 'waiting',
    },
  ]
  const view = await render(React.createElement(ActivityTimeline, { steps: activeSteps }))

  await waitFor(() => assert.match(view.text(), /Session activity/))
  await click(view.container.querySelector('button'))
  assert.doesNotMatch(view.text(), /Understanding your request/)

  await view.rerender(React.createElement(ActivityTimeline, { steps: activeSteps.map((step) => ({ ...step })) }))
  await flushEffects()

  assert.doesNotMatch(view.text(), /Understanding your request/)

  await view.unmount()
})
