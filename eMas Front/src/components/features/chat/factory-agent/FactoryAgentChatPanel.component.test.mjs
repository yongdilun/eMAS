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

function createChatState(overrides = {}) {
  return {
    session: null,
    messages: [],
    turns: [],
    activitySteps: [],
    sessionList: [],
    activeSessionName: null,
    input: '',
    setInput: () => {},
    loading: false,
    isSending: false,
    isCancelling: false,
    isRetryingConnection: false,
    error: null,
    streamDiagnostics: [],
    pendingApproval: null,
    approvalReason: '',
    messageMode: 'normal',
    clientProgress: null,
    setApprovalReason: () => {},
    setMessageMode: () => {},
    isDecidingApproval: false,
    isPollingSession: false,
    getStashedBundlePresentation: () => null,
    isResumingAfterApproval: false,
    handleSend: () => {},
    handleCancel: () => {},
    retryConnection: () => {},
    decideApproval: () => {},
    decideConfirmation: () => {},
    startNewSession: () => {},
    switchSession: () => {},
    renameSession: () => {},
    deleteSession: () => {},
    ...overrides,
  }
}

test('FactoryAgentChatPanel renders pending approval card and follow-up guidance', async () => {
  const { factoryAgentApi } = await server.ssrLoadModule('/src/services/factoryAgentApi.js')
  factoryAgentApi.listTools = async () => []
  const { default: FactoryAgentChatPanel } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx')
  const pendingApproval = {
    approval_id: 'approval-1',
    subject_type: 'tool',
    tool_name: 'update_job_priority',
    side_effect_level: 'HIGH',
    risk_summary: 'Priority changes require operator approval.',
    args: { job_id: 'JOB-1', priority: 'high' },
  }
  const chatState = createChatState({
    session: { session_id: 'session-1', name: 'Priority review', status: 'WAITING_APPROVAL' },
    sessionList: [{ session_id: 'session-1', name: 'Priority review', status: 'WAITING_APPROVAL' }],
    activeSessionName: 'Priority review',
    pendingApproval,
    turns: [
      {
        id: 'turn-1',
        user: { content: 'Set JOB-1 priority to high', created_at: '2026-05-15T12:00:00Z' },
        summary: 'Waiting for your approval.',
        created_at: '2026-05-15T12:00:01Z',
        approvals: [{ event_type: 'approval_required', approval_id: 'approval-1' }],
      },
    ],
    activitySteps: [
      {
        id: 'activity-1',
        timestamp: 1,
        group: 'approval',
        label: 'Waiting for approval',
        detail: null,
        state: 'waiting',
      },
    ],
  })

  const view = await render(
    React.createElement(FactoryAgentChatPanel, {
      useChatState: () => chatState,
    }),
  )

  await waitFor(() => assert.match(view.text(), /Priority review/))
  assert.match(view.text(), /Set JOB-1 priority to high/)
  assert.match(view.text(), /Approval required/)
  assert.match(view.text(), /Priority changes require operator approval/)
  assert.match(view.text(), /Follow-up messages can revise the plan/)
  assert.match(view.container.querySelector('textarea[placeholder="Send a revision; pending approval stays open..."]')?.outerHTML || '', /textarea/)

  await view.unmount()
})

test('FactoryAgentChatPanel renders pending approval even when the approval timeline row lags', async () => {
  const { factoryAgentApi } = await server.ssrLoadModule('/src/services/factoryAgentApi.js')
  factoryAgentApi.listTools = async () => []
  const { default: FactoryAgentChatPanel } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx')
  const pendingApproval = {
    approval_id: 'approval-2',
    subject_type: 'tool',
    tool_name: 'update_job_priority',
    side_effect_level: 'HIGH',
    risk_summary: 'Approval 2 required: original HIGH-priority jobs will become MEDIUM.',
    args: {
      bundle_ui: {
        headline: 'Approval 2 required: original HIGH-priority jobs will become MEDIUM.',
        rows: [{ job_id: 'JOB-SEED-001', original_priority: 'high', new_priority: 'medium' }],
      },
    },
  }
  const chatState = createChatState({
    session: { session_id: 'session-2', name: 'Cascade review', status: 'COMPLETED' },
    sessionList: [{ session_id: 'session-2', name: 'Cascade review', status: 'WAITING_APPROVAL' }],
    activeSessionName: 'Cascade review',
    pendingApproval,
    turns: [
      {
        id: 'turn-2',
        user: {
          content: 'change all medium priority job to high then change all high priority job to medium',
          created_at: '2026-05-15T12:00:00Z',
        },
        summary: 'Waiting for your approval.',
        created_at: '2026-05-15T12:00:01Z',
        approvals: [],
      },
    ],
  })

  const view = await render(
    React.createElement(FactoryAgentChatPanel, {
      useChatState: () => chatState,
    }),
  )

  await waitFor(() => assert.match(view.text(), /Approval required/))
  assert.match(view.text(), /Approval 2 required: original HIGH-priority jobs will become MEDIUM/)
  assert.match(view.text(), /Follow-up messages can revise the plan/)

  await view.unmount()
})

test('FactoryAgentChatPanel uses current pending approval copy when previous approval text is still in the turn', async () => {
  const { factoryAgentApi } = await server.ssrLoadModule('/src/services/factoryAgentApi.js')
  factoryAgentApi.listTools = async () => []
  const { default: FactoryAgentChatPanel } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx')
  const pendingApproval = {
    approval_id: 'approval-2',
    subject_type: 'tool',
    tool_name: '__langgraph_commit__',
    side_effect_level: 'HIGH',
    risk_summary: 'Stage priority update for 11 high-priority job(s) in one approval bundle.',
    args: {
      bundle_ui: {
        kind: 'job_priority_bundle',
        headline: '11 jobs will be updated from high to low priority.',
        previous_priority: 'high',
        new_priority: 'low',
        rows: [
          { job_id: 'JOB-SEED-001', previous_priority: 'high', new_priority: 'low' },
          { job_id: 'JOB-SEED-003', previous_priority: 'high', new_priority: 'low' },
        ],
      },
    },
  }
  const chatState = createChatState({
    session: { session_id: 'session-3', name: 'Cascade review', status: 'WAITING_APPROVAL' },
    sessionList: [{ session_id: 'session-3', name: 'Cascade review', status: 'WAITING_APPROVAL' }],
    activeSessionName: 'Cascade review',
    pendingApproval,
    turns: [
      {
        id: 'turn-3',
        user: {
          content: 'change all medium priority job to high then change all high priority job to low',
          created_at: '2026-05-15T12:00:00Z',
        },
        summary: 'Approved request to change record.',
        created_at: '2026-05-15T12:00:01Z',
        approvals: [
          {
            event_type: 'approval_required',
            approval_id: 'approval-1',
            content: 'Waiting for your approval: 10 jobs will be updated from medium to high priority.',
          },
          {
            event_type: 'approval_decided',
            approval_id: 'approval-1',
            content: 'Approved request to change record.',
            status: 'APPROVED',
          },
        ],
      },
    ],
    activitySteps: [
      {
        id: 'activity-approval-2',
        timestamp: 2,
        group: 'approval',
        label: 'Waiting for approval',
        detail: null,
        state: 'waiting',
      },
    ],
  })

  const view = await render(
    React.createElement(FactoryAgentChatPanel, {
      useChatState: () => chatState,
    }),
  )

  await waitFor(() => assert.match(view.text(), /11 jobs will be updated from high to low priority/))
  assert.doesNotMatch(view.text(), /Approved request to change record/)
  assert.doesNotMatch(view.text(), /10 jobs will be updated from medium to high priority/)

  await view.unmount()
})

test('FactoryAgentChatPanel completed cascade shows final summary instead of stale approval bundle', async () => {
  const { factoryAgentApi } = await server.ssrLoadModule('/src/services/factoryAgentApi.js')
  factoryAgentApi.listTools = async () => []
  const { default: FactoryAgentChatPanel } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx')
  const finalSummary = [
    '10 medium priority jobs changed to high.',
    '11 original high priority jobs changed to low.',
  ].join('\n')
  const chatState = createChatState({
    session: { session_id: 'session-4', name: 'Cascade complete', status: 'COMPLETED' },
    sessionList: [{ session_id: 'session-4', name: 'Cascade complete', status: 'COMPLETED' }],
    activeSessionName: 'Cascade complete',
    turns: [
      {
        id: 'turn-4',
        user: {
          content: 'change all medium priority job to high then change all high priority job to low',
          created_at: '2026-05-15T12:00:00Z',
        },
        summary: finalSummary,
        created_at: '2026-05-15T12:00:01Z',
        terminal: {
          event_type: 'session_completed',
          content: finalSummary,
          created_at: '2026-05-15T12:00:10Z',
        },
        approvals: [
          {
            event_type: 'approval_required',
            approval_id: 'approval-1',
            tool_name: '__langgraph_commit__',
            content: 'Waiting for your approval: 10 jobs will be updated from medium to high priority.',
          },
          {
            event_type: 'approval_decided',
            approval_id: 'approval-1',
            tool_name: '__langgraph_commit__',
            content: 'Approved request to change record.',
            status: 'APPROVED',
          },
          {
            event_type: 'approval_required',
            approval_id: 'approval-2',
            tool_name: '__langgraph_commit__',
            content: 'Waiting for your approval: 11 jobs will be updated from high to low priority.',
            details: {
              args: {
                bundle_ui: {
                  kind: 'job_priority_bundle',
                  headline: '11 jobs will be updated from high to low priority.',
                  rows: [
                    { job_id: 'JOB-SEED-001', previous_priority: 'high', new_priority: 'low' },
                    { job_id: 'JOB-SEED-003', previous_priority: 'high', new_priority: 'low' },
                  ],
                },
              },
            },
          },
          {
            event_type: 'approval_decided',
            approval_id: 'approval-2',
            tool_name: '__langgraph_commit__',
            content: 'Approved request to change record.',
            status: 'APPROVED',
          },
        ],
      },
    ],
    activitySteps: [
      {
        id: 'activity-complete',
        timestamp: 3,
        group: 'response',
        label: 'Run complete',
        detail: 'All steps finished. See the thread below.',
        state: 'complete',
      },
    ],
  })

  const view = await render(
    React.createElement(FactoryAgentChatPanel, {
      useChatState: () => chatState,
    }),
  )

  await waitFor(() => assert.match(view.text(), /10 medium priority jobs changed to high/))
  await waitFor(() => assert.match(view.text(), /11 original high priority jobs changed to low/))
  assert.doesNotMatch(view.text(), /Approved request to change record/)
  assert.doesNotMatch(view.text(), /Please approve to continue/)
  assert.doesNotMatch(view.text(), /Affected records \(2\)/)
  assert.doesNotMatch(view.text(), /JOB-SEED-001/)

  await view.unmount()
})

test('FactoryAgentChatPanel renders backend unavailable errors without fake success', async () => {
  const { default: FactoryAgentChatPanel } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx')
  let retryCount = 0
  const chatState = createChatState({
    error: 'Could not restore active session: Cannot connect to factory-agent.',
    retryConnection: () => {
      retryCount += 1
    },
  })

  const view = await render(
    React.createElement(FactoryAgentChatPanel, {
      useChatState: () => chatState,
    }),
  )

  assert.match(view.text(), /Cannot connect to factory-agent/)
  assert.match(view.text(), /Factory Agent backend unavailable/)
  assert.match(view.text(), /Retry connection/)
  assert.match(view.text(), /Start a session from the sidebar/)
  assert.doesNotMatch(view.text(), /Run complete/)
  assert.doesNotMatch(view.text(), /Approval received/)

  const retryButton = Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent.includes('Retry connection'))
  await click(retryButton)
  assert.equal(retryCount, 1)

  await view.unmount()
})

test('FactoryAgentChatPanel renders failed commit diagnostics without stale success copy', async () => {
  const { default: FactoryAgentChatPanel } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx')
  const safeSummary =
    'Could not complete the requested job priority change because the Go API returned database unavailable. No job rows were changed and no audit rows were created. Please retry after the backend recovers.'
  const chatState = createChatState({
    session: { session_id: 'session-so-029', name: 'Go API failure', status: 'FAILED' },
    sessionList: [{ session_id: 'session-so-029', name: 'Go API failure', status: 'FAILED' }],
    activeSessionName: 'Go API failure',
    turns: [
      {
        id: 'turn-so-029',
        created_at: '2026-05-16T10:00:00.000Z',
        user: {
          content: 'Run Phase 14 Go API 500 commit failure for JOB-SEED-001',
          created_at: '2026-05-16T10:00:00.000Z',
        },
        summary: safeSummary,
        thinking: [],
        tools: [
          {
            tool_name: 'put__jobs_{id}',
            status: 'FAILED',
            content: 'put__jobs_{id} failed: HTTP 500: database unavailable',
            details: { last_error: 'HTTP 500: database unavailable' },
          },
        ],
        approvals: [],
        confirmations: [],
        status: [],
        terminal: {
          event_type: 'session_failed',
          content: 'HTTP 500: database unavailable',
          status: 'FAILED',
        },
        sources: [],
        safetyContent: null,
      },
    ],
    activitySteps: [
      {
        id: 'failed',
        timestamp: Date.parse('2026-05-16T10:00:03.000Z') / 1000,
        group: 'system',
        label: 'Something needs attention',
        detail: 'The request could not be completed',
        state: 'error',
      },
    ],
  })

  const view = await render(
    React.createElement(FactoryAgentChatPanel, {
      useChatState: () => chatState,
    }),
  )

  await waitFor(() => assert.match(view.text(), /Could not complete/))
  await waitFor(() => assert.match(view.text(), /database unavailable/))
  await waitFor(() => assert.match(view.text(), /Please retry/))
  assert.doesNotMatch(view.text(), /Run complete/)
  assert.doesNotMatch(view.text(), /Updated\s+1\s+job/i)
  assert.doesNotMatch(view.text(), /Priority:\s+medium/i)

  await view.unmount()
})

test('FactoryAgentChatPanel empty final response safe diagnostic', async () => {
  const { default: FactoryAgentChatPanel } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx')
  const safeSummary =
    'Unable to render final response. The run completed, but the backend returned empty assistant content.'
  const chatState = createChatState({
    session: { session_id: 'session-so-020', name: 'Empty answer', status: 'COMPLETED' },
    sessionList: [{ session_id: 'session-so-020', name: 'Empty answer', status: 'COMPLETED' }],
    activeSessionName: 'Empty answer',
    turns: [
      {
        id: 'turn-so-020',
        created_at: '2026-05-16T10:00:00.000Z',
        user: {
          content: 'Return an empty completed answer',
          created_at: '2026-05-16T10:00:00.000Z',
        },
        summary: safeSummary,
        thinking: [],
        tools: [],
        approvals: [],
        confirmations: [],
        status: [],
        terminal: {
          event_type: 'session_completed',
          content: '',
          status: 'COMPLETED',
        },
        sources: [],
        safetyContent: null,
      },
    ],
    activitySteps: [
      {
        id: 'complete',
        timestamp: Date.parse('2026-05-16T10:00:03.000Z') / 1000,
        group: 'response',
        label: 'Run complete',
        detail: 'All steps finished. See the thread below.',
        state: 'complete',
      },
    ],
  })

  const view = await render(
    React.createElement(FactoryAgentChatPanel, {
      useChatState: () => chatState,
    }),
  )

  await waitFor(() => assert.match(view.text(), /Unable to render final response/))
  assert.doesNotMatch(view.text(), /Execution completed\./)
  assert.doesNotMatch(view.text(), /Previous answer that must not be reused/)

  await view.unmount()
})

test('FactoryAgentChatPanel renders stream diagnostics without hiding the chat', async () => {
  const { default: FactoryAgentChatPanel } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx')
  const chatState = createChatState({
    streamDiagnostics: [
      {
        source: 'session-events',
        status: 'fallback',
        message: 'Snapshot stream disconnected. Polling every 4 seconds while reconnecting.',
      },
    ],
  })

  const view = await render(
    React.createElement(FactoryAgentChatPanel, {
      useChatState: () => chatState,
    }),
  )

  assert.match(view.text(), /Snapshot stream disconnected/)
  assert.match(view.text(), /Start a session from the sidebar/)

  await view.unmount()
})

test('FactoryAgentSessionSidebar uses separate controls for select, rename, and delete', async () => {
  const { default: FactoryAgentSessionSidebar } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/FactoryAgentSessionSidebar.jsx')
  const calls = []
  const session = { session_id: 'session-1', name: 'Priority review', status: 'WAITING_APPROVAL' }

  const view = await render(
    React.createElement(FactoryAgentSessionSidebar, {
      collapsed: false,
      onCollapsedChange: (value) => calls.push(['collapse', value]),
      sessions: [session],
      activeSessionId: 'session-1',
      editingSessionId: null,
      editingName: '',
      onEditingNameChange: (value) => calls.push(['edit-name', value]),
      onStartNewSession: () => calls.push(['new']),
      onSwitchSession: (id) => calls.push(['switch', id]),
      onStartEditing: (item) => calls.push(['edit', item.session_id]),
      onStopEditing: () => calls.push(['stop-edit']),
      onRenameSession: (id, name) => calls.push(['rename', id, name]),
      onDeleteSession: (item) => calls.push(['delete', item.session_id]),
    }),
  )

  assert.equal(view.container.querySelector('button button'), null)

  await click(view.container.querySelector('button[aria-label="Rename session Priority review"]'))
  assert.deepEqual(calls.at(-1), ['edit', 'session-1'])

  await click(view.container.querySelector('button[aria-label="Delete session Priority review"]'))
  assert.deepEqual(calls.at(-1), ['delete', 'session-1'])

  await click(view.container.querySelector('button[aria-label="Open session Priority review"]'))
  assert.deepEqual(calls.at(-1), ['switch', 'session-1'])

  await view.unmount()
})
