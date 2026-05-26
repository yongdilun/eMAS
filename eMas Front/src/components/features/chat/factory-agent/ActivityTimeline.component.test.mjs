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

test('ActivityTimeline marks only the newest retry activity as current', async () => {
  const { default: ActivityTimeline } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/ActivityTimeline.jsx')
  const view = await render(
    React.createElement(ActivityTimeline, {
      steps: [
        {
          id: 'step-1',
          timestamp: 1,
          group: 'research',
          label: 'Running selected tool',
          detail: 'Running the selected read',
          state: 'success',
        },
        {
          id: 'step-2',
          timestamp: 2,
          group: 'response',
          label: 'Checking evidence',
          detail: 'Evidence from machine records needs another attempt',
          state: 'success',
        },
        {
          id: 'step-3',
          timestamp: 3,
          group: 'planning',
          label: 'Replanning',
          detail: 'Preparing another safe attempt',
          state: 'success',
        },
        {
          id: 'step-4',
          timestamp: 4,
          group: 'research',
          label: 'Retrying tool',
          detail: 'Running the next selected read',
          state: 'running',
        },
      ],
    }),
  )

  await waitFor(() => assert.match(view.text(), /Session activity/))
  const currentBadges = Array.from(view.container.querySelectorAll('span'))
    .filter((node) => node.textContent.trim() === 'Current')
  assert.equal(currentBadges.length, 1)
  const currentRow = currentBadges[0].closest('li')
  assert.match(currentRow?.textContent || '', /Retrying tool/)
  assert.doesNotMatch(currentRow?.textContent || '', /Running selected tool/)

  await view.unmount()
})

test('ActivityTimeline keeps a terminal retry story expanded', async () => {
  const { default: ActivityTimeline } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/ActivityTimeline.jsx')
  const view = await render(
    React.createElement(ActivityTimeline, {
      steps: [
        {
          id: 'step-1',
          timestamp: 1,
          group: 'research',
          label: 'Running selected tool',
          detail: 'Attempt 1 of 3 - Running the selected read',
          state: 'success',
        },
        {
          id: 'step-2',
          timestamp: 2,
          group: 'response',
          label: 'Checking evidence',
          detail: 'Attempt 1 of 3 - Previous read timed out',
          state: 'success',
        },
        {
          id: 'step-3',
          timestamp: 3,
          group: 'planning',
          label: 'Replanning after timeout',
          detail: 'Attempt 2 of 3 - Previous read timed out',
          state: 'success',
        },
        {
          id: 'step-4',
          timestamp: 4,
          group: 'research',
          label: 'Retrying machine status read',
          detail: 'Attempt 2 of 3 - Running the next selected read',
          state: 'success',
        },
        {
          id: 'step-5',
          timestamp: 5,
          group: 'response',
          label: 'Run complete',
          detail: 'Attempt 2 of 3 - Completed with verified evidence',
          state: 'complete',
        },
      ],
    }),
  )

  await waitFor(() => assert.match(view.text(), /Replanning after timeout/))
  assert.match(view.text(), /Retrying machine status read/)
  assert.match(view.text(), /Attempt 2 of 3/)

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

test('ActivityTimeline ignores stale rows that arrive after a terminal row', async () => {
  const { default: ActivityTimeline } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/ActivityTimeline.jsx')
  const view = await render(
    React.createElement(ActivityTimeline, {
      steps: [
        {
          id: 'step-1',
          timestamp: 1,
          group: 'response',
          label: 'Checking citations',
          detail: 'Checking evidence support',
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
        {
          id: 'step-3',
          timestamp: 3,
          group: 'planning',
          label: 'Understanding your request',
          detail: 'Reviewing your request and recent context',
          state: 'running',
        },
      ],
    }),
  )

  assert.match(view.text(), /Run complete/)
  assert.doesNotMatch(view.text(), /Understanding your request/)
  assert.doesNotMatch(view.text(), /Current/)

  await click(view.container.querySelector('button'))
  assert.match(view.text(), /Checking citations/)
  assert.doesNotMatch(view.text(), /Understanding your request/)

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

test('ActivityTimeline marks only newly appended rows for gentle entry animation', async () => {
  const { default: ActivityTimeline } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/ActivityTimeline.jsx')
  const activeSteps = [
    {
      id: 'step-1',
      timestamp: 1,
      group: 'planning',
      label: 'Understood request',
      detail: 'Reviewing recent context',
      state: 'success',
    },
    {
      id: 'step-2',
      timestamp: 2,
      group: 'research',
      label: 'Running selected tool',
      detail: 'Attempt 1 of 6 - Running the selected read',
      state: 'success',
    },
  ]
  const view = await render(React.createElement(ActivityTimeline, { steps: activeSteps }))

  await waitFor(() => assert.match(view.text(), /Session activity/))
  assert.equal(view.container.querySelector('[data-activity-entry="appended"]'), null)

  await view.rerender(React.createElement(ActivityTimeline, {
    steps: [
      ...activeSteps,
      {
        id: 'step-3',
        timestamp: 3,
        group: 'response',
        label: 'Checking result',
        detail: 'Attempt 1 of 6 - Previous read failed',
        state: 'running',
      },
    ],
  }))

  await waitFor(() => {
    const appended = view.container.querySelector('[data-step-id="step-3"]')
    assert.equal(appended?.getAttribute('data-activity-entry'), 'appended')
  })
  assert.equal(view.container.querySelector('[data-step-id="step-1"]')?.getAttribute('data-activity-entry'), null)
  assert.equal(view.container.querySelector('[data-step-id="step-2"]')?.getAttribute('data-activity-entry'), null)
  assert.match(view.container.querySelector('[data-step-id="step-3"]')?.className || '', /activity-timeline-row--new/)

  await view.unmount()
})

test('ActivityTimeline does not entry-animate replacement rows', async () => {
  const { default: ActivityTimeline } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/ActivityTimeline.jsx')
  const view = await render(React.createElement(ActivityTimeline, {
    steps: [
      {
        id: 'first-run-1',
        timestamp: 1,
        group: 'planning',
        label: 'Understood request',
        detail: 'Reviewing recent context',
        state: 'success',
      },
      {
        id: 'first-run-2',
        timestamp: 2,
        group: 'research',
        label: 'Running selected tool',
        detail: 'Attempt 1 of 6 - Running the selected read',
        state: 'running',
      },
    ],
  }))

  await waitFor(() => assert.match(view.text(), /Session activity/))

  await view.rerender(React.createElement(ActivityTimeline, {
    steps: [
      {
        id: 'second-run-1',
        timestamp: 1,
        group: 'planning',
        label: 'Understood request',
        detail: 'Reviewing recent context',
        state: 'success',
      },
      {
        id: 'second-run-2',
        timestamp: 2,
        group: 'response',
        label: 'Checking result',
        detail: 'Checking tool evidence',
        state: 'running',
      },
    ],
  }))

  await flushEffects()
  assert.equal(view.container.querySelector('[data-activity-entry="appended"]'), null)

  await view.unmount()
})
