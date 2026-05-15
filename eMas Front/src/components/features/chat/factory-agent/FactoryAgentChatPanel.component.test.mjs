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
