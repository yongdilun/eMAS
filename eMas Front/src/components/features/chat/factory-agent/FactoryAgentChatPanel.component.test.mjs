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

function baseResponseDocument(overrides = {}) {
  return {
    version: 1,
    id: 'rd-session-1-turn-1',
    document_id: 'rd-session-1-turn-1',
    turn_id: 'turn-1',
    revision: 1,
    revision_source: 'test',
    state: 'completed',
    status: 'completed',
    run_steps: [
      {
        step_id: 'analysis-1',
        kind: 'analysis',
        state: 'completed',
        title: 'Understood request',
        summary: 'Request parsed.',
      },
      {
        step_id: 'completed-1',
        kind: 'completed',
        state: 'completed',
        title: 'Run complete',
        summary: 'All steps finished.',
      },
    ],
    blocks: [
      {
        id: 'activity:rd-session-1-turn-1',
        type: 'run_activity',
        step_ids: ['analysis-1', 'completed-1'],
      },
      {
        id: 'message:rd-session-1-turn-1:completed',
        type: 'short_message',
        message: 'Typed document result is ready.',
        status: 'completed',
      },
    ],
    invariants: {},
    diagnostics: {},
    ...overrides,
  }
}

async function renderPanelWithState(chatState) {
  const { factoryAgentApi } = await server.ssrLoadModule('/src/services/factoryAgentApi.js')
  factoryAgentApi.listTools = async () => []
  const { default: FactoryAgentChatPanel } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx')
  return render(
    React.createElement(FactoryAgentChatPanel, {
      useChatState: () => chatState,
    }),
  )
}

function responseDocumentTurn(responseDocument, overrides = {}) {
  return {
    id: 'turn-rd-1',
    created_at: '2026-05-16T10:00:00.000Z',
    user: {
      content: 'Use typed response document',
      created_at: '2026-05-16T10:00:00.000Z',
    },
    summary: 'Legacy summary that should not win.',
    responseDocument,
    approvals: [],
    confirmations: [],
    tools: [],
    status: [],
    sources: [],
    safetyContent: null,
    ...overrides,
  }
}

test('FactoryAgentChatPanel renders pending approval card without normal pending guidance', async () => {
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
  assert.doesNotMatch(view.text(), /Follow-up messages can revise the plan/)
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
  assert.doesNotMatch(view.text(), /Follow-up messages can revise the plan/)

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

test('FactoryAgentChatPanel renders typed mutation rows when final wording changes', async () => {
  const { default: FactoryAgentChatPanel } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx')
  const chatState = createChatState({
    session: { session_id: 'session-typed-mutation', name: 'Typed mutation', status: 'COMPLETED' },
    sessionList: [{ session_id: 'session-typed-mutation', name: 'Typed mutation', status: 'COMPLETED' }],
    activeSessionName: 'Typed mutation',
    turns: [
      {
        id: 'turn-typed-mutation',
        created_at: '2026-05-16T10:00:00.000Z',
        user: {
          content: 'change low priority jobs to high',
          created_at: '2026-05-16T10:00:00.000Z',
        },
        summary: 'Priority update finished.',
        terminal: { event_type: 'session_completed', content: 'Done.', status: 'COMPLETED' },
        presentation: {
          kind: 'mutation_result',
          state: 'completed',
          summary: 'Priority update finished.',
          rows: [
            { job_id: 'JOB-SEED-005', previous_priority: 'low', new_priority: 'high', outcome: 'updated' },
          ],
        },
        typedTablePresentation: {
          render_hint: 'table',
          table: {
            columns: [
              { key: 'job_id', label: 'Job ID' },
              { key: 'previous_priority', label: 'Previous priority' },
              { key: 'new_priority', label: 'New priority' },
              { key: 'outcome', label: 'Outcome' },
            ],
            rows: [
              { job_id: 'JOB-SEED-005', previous_priority: 'low', new_priority: 'high', outcome: 'updated' },
            ],
            displayed_rows: 1,
            total_rows: 1,
          },
        },
      },
    ],
    activitySteps: [
      {
        id: 'complete',
        timestamp: 1,
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

  await waitFor(() => assert.match(view.text(), /Priority update finished/))
  assert.match(view.text(), /JOB-SEED-005/)
  assert.match(view.text(), /Previous priority/)
  assert.match(view.text(), /high/)

  await view.unmount()
})

test('FactoryAgentChatPanel renders typed knowledge sources without exact answer wording', async () => {
  const { default: FactoryAgentChatPanel } = await server.ssrLoadModule('/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx')
  const chatState = createChatState({
    session: { session_id: 'session-typed-rag', name: 'Typed RAG', status: 'COMPLETED' },
    sessionList: [{ session_id: 'session-typed-rag', name: 'Typed RAG', status: 'COMPLETED' }],
    activeSessionName: 'Typed RAG',
    turns: [
      {
        id: 'turn-typed-rag',
        created_at: '2026-05-16T10:00:00.000Z',
        user: {
          content: 'what does the LOTO procedure require',
          created_at: '2026-05-16T10:00:00.000Z',
        },
        summary: 'Use the cited LOTO procedure before lockout.',
        terminal: { event_type: 'session_completed', content: 'Answer ready.', status: 'COMPLETED' },
        sources: [
          {
            source_number: 1,
            title: 'Machine LOTO Procedure',
            doc_id: 'LOTO-M-CNC-01',
            machine_id: 'M-CNC-01',
          },
        ],
        presentation: {
          kind: 'knowledge_answer',
          state: 'completed',
          summary: 'Use the cited LOTO procedure before lockout.',
        },
      },
    ],
    activitySteps: [
      {
        id: 'complete',
        timestamp: 1,
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

  await waitFor(() => assert.match(view.text(), /Knowledge sources/))
  assert.match(view.text(), /Machine LOTO Procedure/)
  assert.match(view.text(), /Use the cited LOTO procedure/)

  await view.unmount()
})

test('FactoryAgentChatPanel renders valid response_document message, activity, and blocks', async () => {
  const document = baseResponseDocument({
    blocks: [
      { id: 'activity:rd-1', type: 'run_activity', step_ids: ['analysis-1', 'completed-1'] },
      { id: 'message:rd-1', type: 'short_message', message: 'Typed document result is ready.', status: 'completed' },
      {
        id: 'result-summary:op-1',
        type: 'result_summary',
        title: 'Result summary',
        summary: 'Updated 2 jobs across 1 approved step.',
        steps: [{ step_number: 1, summary: '2 jobs changed from low to high.' }],
        total_count: 2,
      },
    ],
  })
  const chatState = createChatState({
    session: { session_id: 'session-rd', name: 'Response document', status: 'COMPLETED' },
    sessionList: [{ session_id: 'session-rd', name: 'Response document', status: 'COMPLETED' }],
    activeSessionName: 'Response document',
    turns: [responseDocumentTurn(document)],
    activitySteps: [{ id: 'legacy', timestamp: 1, group: 'response', label: 'Legacy activity', state: 'complete' }],
  })

  const view = await renderPanelWithState(chatState)

  await waitFor(() => assert.match(view.text(), /Typed document result is ready/))
  assert.match(view.text(), /Run complete/)
  assert.match(view.text(), /Updated 2 jobs across 1 approved step/)
  assert.match(view.text(), /2 jobs changed from low to high/)
  assert.doesNotMatch(view.text(), /Legacy summary that should not win/)

  await view.unmount()
})

test('FactoryAgentChatPanel keeps legacy presentation fallback when response_document is absent', async () => {
  const chatState = createChatState({
    session: { session_id: 'session-legacy-fallback', name: 'Legacy fallback', status: 'COMPLETED' },
    sessionList: [{ session_id: 'session-legacy-fallback', name: 'Legacy fallback', status: 'COMPLETED' }],
    activeSessionName: 'Legacy fallback',
    turns: [
      {
        id: 'turn-legacy-fallback',
        created_at: '2026-05-16T10:00:00.000Z',
        user: { content: 'old snapshot', created_at: '2026-05-16T10:00:00.000Z' },
        summary: 'Legacy presentation summary is still supported.',
        terminal: { event_type: 'session_completed', content: 'Done.', status: 'COMPLETED' },
        presentation: {
          kind: 'mutation_result',
          state: 'completed',
          summary: 'Legacy presentation summary is still supported.',
          rows: [{ job_id: 'JOB-LEGACY-001', priority: 'high' }],
        },
      },
    ],
  })

  const view = await renderPanelWithState(chatState)

  await waitFor(() => assert.match(view.text(), /Legacy presentation summary is still supported/))
  assert.match(view.text(), /JOB-LEGACY-001/)

  await view.unmount()
})

test('FactoryAgentChatPanel renders invalid response_document diagnostic instead of stale presentation', async () => {
  const chatState = createChatState({
    session: { session_id: 'session-invalid-rd', name: 'Invalid document', status: 'COMPLETED' },
    sessionList: [{ session_id: 'session-invalid-rd', name: 'Invalid document', status: 'COMPLETED' }],
    activeSessionName: 'Invalid document',
    turns: [
      responseDocumentTurn(
        { version: 1, state: 'completed', blocks: [] },
        {
          summary: 'All requested changes completed.',
          presentation: {
            kind: 'mutation_result',
            state: 'completed',
            summary: 'Stale presentation success should not render.',
            rows: [{ job_id: 'JOB-STALE-001' }],
          },
        },
      ),
    ],
  })

  const view = await renderPanelWithState(chatState)

  await waitFor(() => assert.match(view.text(), /Response document invalid/))
  assert.match(view.text(), /did not match the expected contract/)
  assert.doesNotMatch(view.text(), /Stale presentation success/)
  assert.doesNotMatch(view.text(), /All requested changes completed/)
  assert.doesNotMatch(view.text(), /JOB-STALE-001/)

  await view.unmount()
})

test('FactoryAgentChatPanel renders pending response_document approval compact by default', async () => {
  const rows = Array.from({ length: 6 }, (_, index) => ({
    job_id: `JOB-SEED-${String(index + 1).padStart(3, '0')}`,
    previous_priority: 'medium',
    new_priority: 'high',
  }))
  const pendingApproval = {
    approval_id: 'approval-rd-1',
    tool_name: '__langgraph_commit__',
    side_effect_level: 'HIGH',
    risk_summary: 'Update 6 jobs from medium to high.',
    args: { bundle_ui: { rows } },
  }
  const document = baseResponseDocument({
    state: 'waiting_approval',
    status: 'waiting_approval',
    run_steps: [
      { step_id: 'analysis-1', kind: 'analysis', state: 'completed', title: 'Understood request' },
      { step_id: 'approval-rd-1', kind: 'approval', state: 'waiting', title: 'Waiting for approval 1', current: true },
    ],
    blocks: [
      { id: 'message:approval-rd-1', type: 'short_message', message: 'Please review before I update 6 jobs.', status: 'waiting_approval' },
      {
        id: 'approval:approval-rd-1',
        type: 'approval_required',
        approval_id: 'approval-rd-1',
        title: 'Approval required',
        summary: 'Update 6 jobs from medium to high',
        rows,
        details_collapsed: true,
      },
    ],
  })
  const chatState = createChatState({
    session: { session_id: 'session-rd-approval', name: 'RD approval', status: 'WAITING_APPROVAL' },
    sessionList: [{ session_id: 'session-rd-approval', name: 'RD approval', status: 'WAITING_APPROVAL' }],
    activeSessionName: 'RD approval',
    pendingApproval,
    turns: [
      responseDocumentTurn(document, {
        approvals: [{ event_type: 'approval_required', approval_id: 'approval-rd-1' }],
      }),
    ],
  })

  const view = await renderPanelWithState(chatState)

  await waitFor(() => assert.match(view.text(), /Update 6 jobs from medium to high/))
  assert.match(view.text(), /\+1 more/)
  assert.match(view.text(), /Approve/)
  assert.match(view.text(), /Reject/)
  assert.doesNotMatch(view.text(), /Follow-up messages can revise the plan/)
  assert.doesNotMatch(view.text(), /Review and edit request/)
  const affectedDetails = Array.from(view.container.querySelectorAll('details')).find((node) =>
    node.textContent.includes('Affected records (6)'),
  )
  assert.equal(affectedDetails?.hasAttribute('open'), false)
  assert.equal(view.container.querySelectorAll('[data-response-block-type="approval_required"]').length, 1)

  await view.unmount()
})

test('FactoryAgentChatPanel suppresses duplicate response_document approval tables and stale legacy tables', async () => {
  const rows = Array.from({ length: 8 }, (_, index) => ({
    job_id: `JOB-SEED-${String(index + 1).padStart(3, '0')}`,
    previous_priority: 'high',
    new_priority: 'low',
  }))
  const document = baseResponseDocument({
    state: 'waiting_approval',
    status: 'waiting_approval',
    run_steps: [
      { step_id: 'approval-2', kind: 'approval', state: 'waiting', title: 'Waiting for approval 2', current: true },
    ],
    blocks: [
      { id: 'message:approval-2', type: 'short_message', message: 'Approval 2 is pending.', status: 'waiting_approval' },
      {
        id: 'approval:approval-2',
        type: 'approval_required',
        approval_id: 'approval-2',
        operation_id: 'op-approval-2',
        summary: 'Update 8 jobs from high to low',
        rows,
      },
      {
        id: 'record-preview:approval-2',
        type: 'record_preview',
        approval_id: 'approval-2',
        operation_id: 'op-approval-2',
        title: 'Affected records',
        rows: rows.slice(0, 5),
      },
      {
        id: 'table:approval-2',
        type: 'result_table',
        approval_id: 'approval-2',
        operation_id: 'op-approval-2',
        title: 'Affected records',
        rows,
      },
    ],
  })
  const chatState = createChatState({
    session: { session_id: 'session-rd-guardrail', name: 'RD guardrail', status: 'WAITING_APPROVAL' },
    sessionList: [{ session_id: 'session-rd-guardrail', name: 'RD guardrail', status: 'WAITING_APPROVAL' }],
    activeSessionName: 'RD guardrail',
    pendingApproval: {
      approval_id: 'approval-2',
      tool_name: '__langgraph_commit__',
      side_effect_level: 'HIGH',
      risk_summary: 'Update 8 jobs from high to low',
      args: { bundle_ui: { rows } },
    },
    turns: [
      responseDocumentTurn(document, {
        summary: 'All requested changes completed.',
        presentation: {
          kind: 'mutation_result',
          state: 'completed',
          summary: 'Stale presentation success should not render.',
          rows: [{ job_id: 'JOB-STALE-PRESENTATION' }],
        },
        tools: [
          {
            tool_name: 'list__jobs',
            status: 'DONE',
            content: 'Stale table result.',
            details: {
              presentation: {
                render_hint: 'table',
                table: {
                  columns: [{ key: 'job_id', label: 'Job ID' }],
                  rows: [{ job_id: 'JOB-STALE-TOOL-TABLE' }],
                },
              },
            },
          },
        ],
        approvals: [{ event_type: 'approval_required', approval_id: 'approval-2' }],
      }),
    ],
  })

  const view = await renderPanelWithState(chatState)

  await waitFor(() => assert.match(view.text(), /Approval 2 is pending/))
  assert.match(view.text(), /Update 8 jobs from high to low/)
  assert.equal(view.container.querySelectorAll('[data-response-block-type="approval_required"]').length, 1)
  assert.equal(view.container.querySelectorAll('[data-response-block-type="record_preview"]').length, 0)
  assert.doesNotMatch(view.text(), /Stale presentation success/)
  assert.doesNotMatch(view.text(), /JOB-STALE-PRESENTATION/)
  assert.doesNotMatch(view.text(), /JOB-STALE-TOOL-TABLE/)
  assert.doesNotMatch(view.text(), /All requested changes completed/)

  await view.unmount()
})

test('FactoryAgentChatPanel renders mutation result table from response_document typed blocks', async () => {
  const rows = [
    { job_id: 'JOB-SEED-005', previous_priority: 'low', new_priority: 'high', outcome: 'updated' },
    { job_id: 'JOB-SEED-009', previous_priority: 'low', new_priority: 'high', outcome: 'updated' },
  ]
  const document = baseResponseDocument({
    blocks: [
      { id: 'message:mutation', type: 'short_message', message: 'Priority update finished.', status: 'completed' },
      { id: 'mutation:op-1', type: 'mutation_result', summary: 'Updated 2 jobs.', rows },
      { id: 'table:op-1', type: 'result_table', title: 'Affected records', rows },
    ],
  })
  const chatState = createChatState({
    session: { session_id: 'session-rd-table', name: 'RD table', status: 'COMPLETED' },
    sessionList: [{ session_id: 'session-rd-table', name: 'RD table', status: 'COMPLETED' }],
    activeSessionName: 'RD table',
    turns: [responseDocumentTurn(document)],
  })

  const view = await renderPanelWithState(chatState)

  await waitFor(() => assert.match(view.text(), /Priority update finished/))
  assert.match(view.text(), /Affected records/)
  assert.match(view.text(), /JOB-SEED-005/)
  assert.match(view.text(), /Previous priority/)
  assert.match(view.text(), /Outcome/)

  await view.unmount()
})

test('FactoryAgentChatPanel renders read-only machine status from typed status_result without raw markdown', async () => {
  const document = baseResponseDocument({
    message: 'Machine M-CNC-01 is running.',
    summary: 'Machine M-CNC-01 is running.',
    run_steps: [
      { step_id: 'read-machine-status', kind: 'read', state: 'completed', title: 'Read machine status' },
      { step_id: 'completed-read', kind: 'completed', state: 'completed', title: 'Run complete' },
    ],
    blocks: [
      { id: 'message:machine-status', type: 'short_message', message: 'Machine M-CNC-01 is running.', status: 'completed' },
      {
        id: 'status:machine-status',
        type: 'status_result',
        contract: 'entity_status_v1',
        title: 'Machine status',
        summary: 'Machine M-CNC-01 is running.',
        entity_type: 'machine',
        entity_id: 'M-CNC-01',
        primary_status: 'running',
        fields: [
          { key: 'machine_id', label: 'Machine ID', value: 'M-CNC-01' },
          { key: 'machine_name', label: 'Machine name', value: 'CNC Mill 01' },
          { key: 'machine_type', label: 'Machine type', value: 'CNC mill' },
          { key: 'location', label: 'Location', value: 'Line 1' },
          { key: 'status', label: 'Status', value: 'running', primary: true },
          { key: 'capacity_per_hour', label: 'Capacity per hour', value: '40' },
          { key: 'last_maintenance', label: 'Last maintenance', value: '2026-05-01' },
          { key: 'maintenance_interval', label: 'Maintenance interval', value: '30 days' },
        ],
        secondary_fields: [],
      },
    ],
  })
  const chatState = createChatState({
    session: { session_id: 'session-rd-machine-status', name: 'Machine status', status: 'COMPLETED' },
    sessionList: [{ session_id: 'session-rd-machine-status', name: 'Machine status', status: 'COMPLETED' }],
    activeSessionName: 'Machine status',
    turns: [responseDocumentTurn(document, {
      user: {
        content: 'Show status for machine with machine id M-CNC-01',
        created_at: '2026-05-16T10:00:00.000Z',
      },
      summary: 'done_all\n\n**Success**\n\nMachineid: M-CNC-01',
      tools: [{ rows: [{ Machineid: 'M-CNC-01', Defaultsetuptime: 0 }] }],
    })],
  })

  const view = await renderPanelWithState(chatState)

  await waitFor(() => assert.match(view.text(), /Machine M-CNC-01 is running\./))
  assert.equal((view.text().match(/Machine M-CNC-01 is running\./g) || []).length, 1)
  assert.equal(view.container.querySelectorAll('[data-response-block-type="status_result"]').length, 1)
  assert.equal(view.container.querySelectorAll('[data-response-block-type="status_result"][data-response-contract="entity_status_v1"]').length, 1)
  assert.equal(view.container.querySelectorAll('[data-response-block-type="approval_required"]').length, 0)
  assert.equal(view.container.querySelectorAll('[data-response-block-type="mutation_result"]').length, 0)
  assert.equal(view.container.querySelectorAll('[data-response-block-type="result_table"]').length, 0)
  assert.match(view.text(), /Machine ID/)
  assert.match(view.text(), /Machine name/)
  assert.match(view.text(), /Machine type/)
  assert.match(view.text(), /Capacity per hour/)
  assert.doesNotMatch(view.text(), /done_all/)
  assert.doesNotMatch(view.text(), /\*\*Success\*\*/)
  assert.doesNotMatch(view.text(), /Machineid/)
  assert.doesNotMatch(view.text(), /Defaultsetuptime/)

  await view.unmount()
})

test('FactoryAgentChatPanel renders completed mutation response_document as one grouped business result', async () => {
  const mediumRows = Array.from({ length: 10 }, (_, index) => ({
    record_id: `JOB-MED-${String(index + 1).padStart(3, '0')}`,
    display_id: `JOB-MED-${String(index + 1).padStart(3, '0')}`,
    business_change: 'Medium -> High',
    business_change_id: 'job-priority-original-medium-to-high',
    entity_type: 'job',
    field_changes: [{ field: 'priority', label: 'Priority', from: 'medium', to: 'high' }],
    change: 'Priority: medium -> high',
    status: 'succeeded',
  }))
  const highRows = Array.from({ length: 11 }, (_, index) => ({
    record_id: `JOB-HIGH-${String(index + 1).padStart(3, '0')}`,
    display_id: `JOB-HIGH-${String(index + 1).padStart(3, '0')}`,
    business_change: 'Original High -> Low',
    business_change_id: 'job-priority-original-high-to-low',
    entity_type: 'job',
    field_changes: [{ field: 'priority', label: 'Priority', from: 'high', to: 'low' }],
    change: 'Priority: high -> low',
    status: 'succeeded',
  }))
  const rows = [...mediumRows, ...highRows]
  const document = baseResponseDocument({
    blocks: [
      { id: 'message:business-result', type: 'short_message', message: 'Done. I updated 21 jobs across 2 approved business changes.', status: 'completed' },
      {
        id: 'result-summary:business-result',
        type: 'result_summary',
        title: 'Changes completed',
        summary: 'Done. I updated 21 jobs across 2 approved business changes.',
        steps: [
          { step_number: 1, business_change: 'Medium -> High', summary: 'Medium -> High: 10 jobs', record_count: 10, status: 'completed' },
          { step_number: 2, business_change: 'Original High -> Low', summary: 'Original High -> Low: 11 jobs', record_count: 11, status: 'completed' },
        ],
        total_count: 21,
        status: 'completed',
      },
      {
        id: 'mutation:business-result',
        type: 'mutation_result',
        contract: 'business_change_v1',
        title: 'Affected records',
        summary: 'Done. I updated 21 jobs across 2 approved business changes.',
        rows,
        groups: [
          {
            contract: 'business_change_v1',
            business_change: 'Medium -> High',
            business_change_id: 'job-priority-original-medium-to-high',
            entity_type: 'job',
            change_type: 'update',
            selector_summary: 'priority = medium',
            source_state_basis: 'original',
            field_changes: [{ field: 'priority', label: 'Priority', from: 'medium', to: 'high' }],
            summary: 'Medium -> High: 10 jobs',
            record_count: 10,
            rows: mediumRows,
          },
          {
            contract: 'business_change_v1',
            business_change: 'Original High -> Low',
            business_change_id: 'job-priority-original-high-to-low',
            entity_type: 'job',
            change_type: 'update',
            selector_summary: 'priority = high',
            source_state_basis: 'original',
            field_changes: [{ field: 'priority', label: 'Priority', from: 'high', to: 'low' }],
            summary: 'Original High -> Low: 11 jobs',
            record_count: 11,
            rows: highRows,
          },
        ],
        preview_limit: 5,
        details_collapsed: true,
        status: 'completed',
      },
    ],
  })
  const chatState = createChatState({
    session: { session_id: 'session-rd-business-result', name: 'RD business result', status: 'COMPLETED' },
    sessionList: [{ session_id: 'session-rd-business-result', name: 'RD business result', status: 'COMPLETED' }],
    activeSessionName: 'RD business result',
    turns: [responseDocumentTurn(document)],
  })

  const view = await renderPanelWithState(chatState)

  await waitFor(() => assert.match(view.text(), /Done\. I updated 21 jobs across 2 approved business changes/))
  assert.equal(view.container.querySelectorAll('[data-final-result-card]').length, 1)
  assert.equal(view.container.querySelectorAll('[data-response-block-type="result_summary"]').length, 1)
  assert.equal(view.container.querySelectorAll('[data-response-block-type="mutation_result"]').length, 1)
  assert.ok(view.container.querySelectorAll('[data-response-contract="business_change_v1"]').length >= 3)
  assert.equal(view.container.querySelectorAll('[data-business-change-group][data-response-contract="business_change_v1"][data-entity-type="job"]').length, 2)
  assert.match(view.text(), /Medium -> High: 10 jobs/)
  assert.match(view.text(), /Original High -> Low: 11 jobs/)
  assert.equal(view.container.querySelectorAll('[data-affected-record-preview] [data-affected-record-row]').length, 5)
  const audit = view.container.querySelector('details[data-clean-audit]')
  assert.equal(audit?.hasAttribute('open'), false)
  assert.doesNotMatch(view.text(), /Operation ID|Step ID|Row ID|Updated 63 jobs/)

  await view.unmount()
})

test('FactoryAgentChatPanel renders RAG source block from response_document typed sources', async () => {
  const answer = 'Use the cited LOTO procedure before lockout.'
  const citation = {
    contract: 'source_citation_v1',
    citation_id: 'citation:LOTO-M-CNC-01#chunk-1',
    source_id: 'LOTO-M-CNC-01#chunk-1',
    source_number: 1,
    title: 'Machine LOTO Procedure',
    doc_id: 'LOTO-M-CNC-01',
    chunk_id: 'chunk-1',
    organization: 'Factory Safety',
    snippet: 'Notify affected employees before lockout begins.',
  }
  const document = baseResponseDocument({
    blocks: [
      { id: 'message:knowledge', type: 'short_message', message: 'I found a source-backed answer.', status: 'completed' },
      {
        id: 'safety:op-1',
        type: 'safety_notice',
        contract: 'safety_notice_v1',
        title: 'Safety notice',
        safety_content: 'Follow the site-approved SOP and verify zero energy before acting.',
      },
      {
        id: 'knowledge:op-1',
        type: 'knowledge_answer',
        contract: 'knowledge_answer_v1',
        answer,
        segments: [{ text: answer, citation_ids: ['citation:LOTO-M-CNC-01#chunk-1'] }],
        citations: [citation],
      },
      {
        id: 'sources:op-1',
        type: 'source_list',
        contract: 'source_list_v1',
        sources: [
          {
            contract: 'source_locator_v1',
            source_id: 'LOTO-M-CNC-01#chunk-1',
            source_number: 1,
            title: 'Machine LOTO Procedure',
            doc_id: 'LOTO-M-CNC-01',
            chunk_id: 'chunk-1',
            machine_id: 'M-CNC-01',
            organization: 'Factory Safety',
            snippet: 'Notify affected employees before lockout begins.',
          },
        ],
      },
    ],
  })
  const chatState = createChatState({
    session: { session_id: 'session-rd-source', name: 'RD source', status: 'COMPLETED' },
    sessionList: [{ session_id: 'session-rd-source', name: 'RD source', status: 'COMPLETED' }],
    activeSessionName: 'RD source',
    turns: [responseDocumentTurn(document, {
      sources: [
        {
          source_number: 1,
          title: 'Legacy source chrome should not render',
          doc_id: 'LEGACY-SOURCE',
        },
      ],
      safetyContent: 'Legacy safety advisory should not render on response_document turns.',
    })],
  })

  const view = await renderPanelWithState(chatState)

  await waitFor(() => assert.match(view.text(), /Use the cited LOTO procedure/))
  assert.equal((view.text().match(new RegExp(answer.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) || []).length, 1)
  assert.match(view.text(), /I found a source-backed answer/)
  assert.match(view.text(), /Safety notice/)
  assert.match(view.text(), /Follow the site-approved SOP/)
  assert.match(view.text(), /Knowledge sources/)
  assert.match(view.text(), /Machine LOTO Procedure/)
  assert.match(view.text(), /LOTO-M-CNC-01/)
  assert.match(view.text(), /Chunk ID: chunk-1/)
  assert.match(view.text(), /Notify affected employees before lockout begins/)
  const sourceChip = view.container.querySelector('[data-source-chip][data-source-id="LOTO-M-CNC-01#chunk-1"]')
  assert.ok(sourceChip)
  assert.equal(sourceChip.textContent.trim(), '[1]')
  await click(sourceChip)
  await waitFor(() => assert.ok(view.container.querySelector('[data-source-drawer]')))
  const drawer = view.container.querySelector('[data-source-drawer]')
  assert.equal(drawer?.getAttribute('data-source-drawer-view'), 'list')
  assert.ok(drawer.closest('[data-chatbot-workspace]'))
  assert.equal(drawer.closest('[data-assistant-response-card]'), null)
  assert.equal(view.container.querySelector('[data-source-drawer-entry]')?.getAttribute('data-source-role'), 'cited')
  assert.match(view.text(), /Document/)
  assert.match(view.text(), /Chunk/)
  assert.match(view.text(), /Notify affected employees before lockout begins/)
  assert.doesNotMatch(view.text(), /Legacy source chrome should not render/)
  assert.doesNotMatch(view.text(), /Legacy safety advisory should not render/)
  assert.doesNotMatch(view.text(), /\[\^1\]/)

  await view.unmount()
})

test('FactoryAgentChatPanel strips legacy raw safety markdown from response_document answers', async () => {
  const document = baseResponseDocument({
    message: 'I found a source-backed answer.',
    blocks: [
      { id: 'message:knowledge', type: 'short_message', message: 'I found a source-backed answer.', status: 'completed' },
      {
        id: 'knowledge:op-1',
        type: 'knowledge_answer',
        answer: ':::safety\n**SAFETY WARNING**: raw markdown should be structured.\n:::\n\nNotify affected employees before lockout.',
      },
    ],
  })
  const chatState = createChatState({
    session: { session_id: 'session-rd-safety', name: 'RD safety', status: 'COMPLETED' },
    sessionList: [{ session_id: 'session-rd-safety', name: 'RD safety', status: 'COMPLETED' }],
    activeSessionName: 'RD safety',
    turns: [responseDocumentTurn(document)],
  })

  const view = await renderPanelWithState(chatState)

  await waitFor(() => assert.match(view.text(), /Notify affected employees before lockout/))
  assert.doesNotMatch(view.text(), /:::safety/)
  assert.doesNotMatch(view.text(), /SAFETY WARNING/)

  await view.unmount()
})

test('FactoryAgentChatPanel offers PDF page search link when source locator includes pdf_url, page, and snippet', async () => {
  const answer = 'Use page-specific LOTO notification guidance.'
  const document = baseResponseDocument({
    blocks: [
      { id: 'message:knowledge', type: 'short_message', message: 'I found a source-backed answer.', status: 'completed' },
      {
        id: 'knowledge:op-pdf',
        type: 'knowledge_answer',
        contract: 'knowledge_answer_v1',
        answer,
        segments: [{ text: answer, citation_ids: ['citation:PDF-LOTO#chunk-9'] }],
        citations: [
          {
            contract: 'source_citation_v1',
            citation_id: 'citation:PDF-LOTO#chunk-9',
            source_id: 'PDF-LOTO#chunk-9',
            source_number: 1,
            title: 'PDF LOTO Procedure',
            doc_id: 'PDF-LOTO',
            chunk_id: 'chunk-9',
            organization: 'Factory Safety',
            snippet: 'Page 9 covers notification timing.',
            pdf_url: '/documents/PDF-LOTO/pdf',
            page: 9,
          },
        ],
      },
      {
        id: 'sources:op-pdf',
        type: 'source_list',
        contract: 'source_list_v1',
        sources: [
          {
            contract: 'source_locator_v1',
            source_id: 'PDF-LOTO#chunk-9',
            source_number: 1,
            title: 'PDF LOTO Procedure',
            doc_id: 'PDF-LOTO',
            chunk_id: 'chunk-9',
            organization: 'Factory Safety',
            snippet: 'Page 9 covers notification timing.',
            pdf_url: '/documents/PDF-LOTO/pdf',
            page: 9,
          },
        ],
      },
    ],
  })
  const chatState = createChatState({
    session: { session_id: 'session-rd-pdf-source', name: 'RD PDF source', status: 'COMPLETED' },
    sessionList: [{ session_id: 'session-rd-pdf-source', name: 'RD PDF source', status: 'COMPLETED' }],
    activeSessionName: 'RD PDF source',
    turns: [responseDocumentTurn(document)],
  })

  const view = await renderPanelWithState(chatState)

  await waitFor(() => assert.ok(view.container.querySelector('[data-source-chip]')))
  await click(view.container.querySelector('[data-source-chip]'))
  const link = await waitFor(() => {
    const node = view.container.querySelector('[data-source-pdf-link]')
    assert.ok(node)
    return node
  })
  assert.equal(link.tagName, 'BUTTON')
  assert.match(link.textContent, /Open PDF search on page 9/)
  assert.match(link.getAttribute('data-source-pdf-href'), /^http:\/\/127\.0\.0\.1:8000\/documents\/PDF-LOTO\/pdf#page=9&search=Page\+9\+covers\+notification\+timing\.$/)
  const drawer = view.container.querySelector('[data-source-drawer]')
  assert.ok(drawer?.closest('[data-chatbot-workspace]'))
  assert.equal(drawer.closest('[data-assistant-response-card]'), null)
  await click(link)
  const frame = await waitFor(() => {
    const node = view.container.querySelector('[data-source-pdf-frame]')
    assert.ok(node)
    return node
  })
  assert.match(frame.getAttribute('src'), /^http:\/\/127\.0\.0\.1:8000\/documents\/PDF-LOTO\/pdf#page=9&search=Page\+9\+covers\+notification\+timing\.$/)
  assert.match(view.container.querySelector('[data-source-pdf-evidence]')?.textContent || '', /Exact highlight unavailable/)
  await click(view.container.querySelector('[data-source-pdf-back]'))
  await waitFor(() => assert.equal(view.container.querySelector('[data-source-drawer]')?.getAttribute('data-source-drawer-view'), 'list'))

  await view.unmount()
})

test('FactoryAgentChatPanel chooses deterministic source PDF highlight fallback order', async () => {
  const sourceRows = [
    {
      source_id: 'PDF-LOTO#exact-char',
      source_number: 1,
      title: 'PDF LOTO Procedure',
      doc_id: 'PDF-LOTO',
      chunk_id: 'exact-char',
      organization: 'Factory Safety',
      snippet: 'Exact text-layer notification range.',
      pdf_url: '/documents/PDF-LOTO/pdf',
      page: 4,
      char_range: [120, 188],
    },
    {
      source_id: 'PDF-LOTO#text-search',
      source_number: 2,
      title: 'PDF LOTO Procedure',
      doc_id: 'PDF-LOTO',
      chunk_id: 'text-search',
      organization: 'Factory Safety',
      snippet: 'Searchable notification fallback text.',
      pdf_url: '/documents/PDF-LOTO/pdf',
      page: 5,
    },
    {
      source_id: 'PDF-LOTO#page-only',
      source_number: 3,
      title: 'PDF LOTO Procedure',
      doc_id: 'PDF-LOTO',
      chunk_id: 'page-only',
      organization: 'Factory Safety',
      snippet: '',
      pdf_url: '/documents/PDF-LOTO/pdf',
      page: 6,
    },
    {
      source_id: 'DRAWER-ONLY#chunk',
      source_number: 4,
      title: 'Drawer Only Source',
      doc_id: 'DRAWER-ONLY',
      chunk_id: 'chunk',
      organization: 'Factory Safety',
      snippet: 'Drawer fallback remains available without PDF metadata.',
    },
  ].map((source) => ({
    contract: 'source_locator_v1',
    citation_id: `citation:${source.source_id}`,
    ...source,
  }))
  const document = baseResponseDocument({
    blocks: [
      { id: 'message:knowledge', type: 'short_message', message: 'I found source PDF locator evidence.', status: 'completed' },
      {
        id: 'knowledge:pdf-fallbacks',
        type: 'knowledge_answer',
        contract: 'knowledge_answer_v1',
        answer: 'Exact range. Text search. Page only. Drawer only.',
        segments: sourceRows.map((source) => ({
          text: source.snippet || source.title,
          citation_ids: [source.citation_id],
        })),
        citations: sourceRows.map((source) => ({ ...source, contract: 'source_citation_v1' })),
      },
      {
        id: 'sources:pdf-fallbacks',
        type: 'source_list',
        contract: 'source_list_v1',
        sources: sourceRows,
      },
    ],
  })
  const chatState = createChatState({
    session: { session_id: 'session-rd-pdf-fallbacks', name: 'RD PDF fallbacks', status: 'COMPLETED' },
    sessionList: [{ session_id: 'session-rd-pdf-fallbacks', name: 'RD PDF fallbacks', status: 'COMPLETED' }],
    activeSessionName: 'RD PDF fallbacks',
    turns: [responseDocumentTurn(document)],
  })

  const view = await renderPanelWithState(chatState)

  async function clickSource(sourceId, expectedMode) {
    const chip = view.container.querySelector(`[data-source-chip][data-source-id="${sourceId}"]`)
    assert.ok(chip)
    assert.equal(chip.getAttribute('data-source-open-mode'), expectedMode)
    await click(chip)
    return waitFor(() => {
      const drawer = view.container.querySelector('[data-source-drawer]')
      assert.equal(drawer?.getAttribute('data-source-id'), sourceId)
      assert.equal(drawer?.getAttribute('data-source-open-mode'), expectedMode)
      return drawer
    })
  }

  let drawer = await clickSource('PDF-LOTO#exact-char', 'exact')
  assert.equal(drawer.getAttribute('data-source-drawer-view'), 'list')
  assert.equal(drawer.querySelector('[data-source-drawer-resize-handle]')?.getAttribute('aria-label'), 'Resize evidence drawer')
  assert.equal(drawer.querySelector('[data-source-drawer-entry][data-source-role="cited"]')?.getAttribute('data-source-id'), 'PDF-LOTO#exact-char')
  assert.equal(drawer.querySelectorAll('[data-source-drawer-entry][data-source-role="related"]').length, 3)
  let link = drawer.querySelector('[data-source-pdf-link]')
  assert.ok(link)
  assert.equal(link.getAttribute('data-source-id'), 'PDF-LOTO#exact-char')
  assert.equal(link.getAttribute('data-doc-id'), 'PDF-LOTO')
  assert.equal(link.getAttribute('data-source-number'), '1')
  assert.equal(link.getAttribute('data-source-highlight-kind'), 'char_range')
  assert.match(link.getAttribute('data-source-pdf-href'), /^http:\/\/127\.0\.0\.1:8000\/documents\/PDF-LOTO\/pdf#page=4&highlight=char_range&char_start=120&char_end=188$/)
  const relatedLink = view.container.querySelector('[data-source-drawer-entry][data-source-id="PDF-LOTO#text-search"] [data-source-pdf-link]')
  assert.ok(relatedLink)
  assert.equal(relatedLink.getAttribute('data-source-number'), '2')
  assert.equal(relatedLink.getAttribute('data-source-open-mode'), 'search')

  drawer = await clickSource('PDF-LOTO#text-search', 'search')
  link = drawer.querySelector('[data-source-pdf-link]')
  assert.ok(link)
  assert.equal(link.getAttribute('data-source-highlight-kind'), 'text_search')
  assert.match(link.getAttribute('data-source-pdf-href'), /^http:\/\/127\.0\.0\.1:8000\/documents\/PDF-LOTO\/pdf#page=5&search=Searchable\+notification\+fallback\+text\.$/)

  drawer = await clickSource('PDF-LOTO#page-only', 'page')
  link = drawer.querySelector('[data-source-pdf-link]')
  assert.ok(link)
  assert.match(link.getAttribute('data-source-pdf-href'), /^http:\/\/127\.0\.0\.1:8000\/documents\/PDF-LOTO\/pdf#page=6$/)

  drawer = await clickSource('DRAWER-ONLY#chunk', 'drawer')
  assert.ok(!drawer.querySelector('[data-source-drawer-entry][data-source-role="cited"] [data-source-pdf-link]'))
  assert.match(view.text(), /Drawer fallback remains available/)

  await view.unmount()
})

test('FactoryAgentChatPanel renders response_document failure diagnostic safely', async () => {
  const document = baseResponseDocument({
    state: 'failed',
    status: 'failed',
    run_steps: [
      { step_id: 'diagnostic:tool_http_error', kind: 'diagnostic', state: 'failed', title: 'Backend tool failed', current: true },
    ],
    blocks: [
      { id: 'message:failure', type: 'short_message', message: 'I could not finish because a backend tool returned an error.', status: 'failed' },
      {
        id: 'diagnostic:tool_http_error',
        type: 'diagnostic',
        severity: 'error',
        reason: 'tool_http_error',
        title: 'Backend tool failed',
        user_message: 'I could not finish because a backend tool returned an error.',
        cause: 'A backend tool returned an unsuccessful HTTP response.',
        impact: { changes_applied: false, incomplete_steps: ['step-2'] },
        current_state: 'The run stopped at the failed backend tool call.',
        next_action: 'Check current status before retrying.',
        technical_details: { error_code: 'http_500_database_unavailable', sanitized: true },
        details_collapsed: true,
      },
    ],
  })
  const chatState = createChatState({
    session: { session_id: 'session-rd-failure', name: 'RD failure', status: 'FAILED' },
    sessionList: [{ session_id: 'session-rd-failure', name: 'RD failure', status: 'FAILED' }],
    activeSessionName: 'RD failure',
    turns: [responseDocumentTurn(document, { summary: 'Still running...' })],
  })

  const view = await renderPanelWithState(chatState)

  await waitFor(() => assert.match(view.text(), /Backend tool failed/))
  assert.match(view.text(), /Cause:/)
  assert.match(view.text(), /Current state:/)
  assert.match(view.text(), /Next action:/)
  assert.match(view.text(), /http_500_database_unavailable/)
  assert.doesNotMatch(view.text(), /Traceback/)
  assert.doesNotMatch(view.text(), /Still running/)

  await view.unmount()
})

test('FactoryAgentChatPanel preserves completed response_document evidence while approval 2 is pending', async () => {
  const approvalRows = [
    { job_id: 'JOB-SEED-001', previous_priority: 'high', new_priority: 'low' },
    { job_id: 'JOB-SEED-003', previous_priority: 'high', new_priority: 'low' },
  ]
  const completedRows = [{ job_id: 'JOB-SEED-002', previous_priority: 'medium', new_priority: 'high' }]
  const document = baseResponseDocument({
    state: 'waiting_approval',
    status: 'waiting_approval',
    run_steps: [
      { step_id: 'analysis-1', kind: 'analysis', state: 'completed', title: 'Understood request' },
      { step_id: 'approval-1', kind: 'approval', state: 'completed', title: 'Approval 1 received' },
      { step_id: 'mutation-1', kind: 'mutation', state: 'completed', title: 'Updated 10 jobs: medium -> high' },
      { step_id: 'approval-2', kind: 'approval', state: 'waiting', title: 'Waiting for approval 2', current: true },
    ],
    blocks: [
      {
        id: 'message:approval-2',
        type: 'short_message',
        message: 'Done. Updated 10 jobs from medium to high. Please review approval 2 before I update the original high-priority jobs.',
        status: 'waiting_approval',
      },
      {
        id: 'completed-step:approval-1',
        type: 'completed_step',
        title: 'Completed step',
        summary: 'Updated 10 jobs from medium to high.',
        rows: completedRows,
      },
      {
        id: 'approval:approval-2',
        type: 'approval_required',
        approval_id: 'approval-2',
        summary: 'Update 11 jobs from high to low',
        rows: approvalRows,
      },
    ],
  })
  const pendingApproval = {
    approval_id: 'approval-2',
    tool_name: '__langgraph_commit__',
    side_effect_level: 'HIGH',
    risk_summary: 'Update 11 jobs from high to low',
    args: { bundle_ui: { rows: approvalRows } },
  }
  const chatState = createChatState({
    session: { session_id: 'session-rd-two-step', name: 'RD two step', status: 'WAITING_APPROVAL' },
    sessionList: [{ session_id: 'session-rd-two-step', name: 'RD two step', status: 'WAITING_APPROVAL' }],
    activeSessionName: 'RD two step',
    pendingApproval,
    turns: [
      responseDocumentTurn(document, {
        summary: 'All requested changes completed.',
        approvals: [{ event_type: 'approval_required', approval_id: 'approval-2' }],
      }),
    ],
  })

  const view = await renderPanelWithState(chatState)

  await waitFor(() => assert.match(view.text(), /Approval 1 received/))
  assert.match(view.text(), /Updated 10 jobs from medium to high/)
  assert.match(view.text(), /Waiting for approval 2/)
  assert.match(view.text(), /Update 11 jobs from high to low/)
  assert.match(view.text(), /JOB-SEED-002/)
  assert.doesNotMatch(view.text(), /All requested changes completed/)
  assert.doesNotMatch(view.text(), /Run complete/)

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

  assert.ok(!view.container.querySelector('button button'))

  await click(view.container.querySelector('button[aria-label="Rename session Priority review"]'))
  assert.deepEqual(calls.at(-1), ['edit', 'session-1'])

  await click(view.container.querySelector('button[aria-label="Delete session Priority review"]'))
  assert.deepEqual(calls.at(-1), ['delete', 'session-1'])

  await click(view.container.querySelector('button[aria-label="Open session Priority review"]'))
  assert.deepEqual(calls.at(-1), ['switch', 'session-1'])

  await view.unmount()
})
