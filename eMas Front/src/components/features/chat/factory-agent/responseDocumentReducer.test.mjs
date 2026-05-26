import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyResponseDocumentSnapshotUpdate,
  createResponseDocumentReducerState,
} from './responseDocumentReducer.js'

function doc(overrides = {}) {
  const revision = overrides.revision ?? 1
  return {
    version: 1,
    id: 'rd-session-1-turn-1',
    document_id: 'rd-session-1-turn-1',
    turn_id: 'turn-1',
    operation_id: 'op-1',
    revision,
    revision_source: 'test',
    state: 'completed',
    status: 'completed',
    summary: `Revision ${revision} complete.`,
    message: `Revision ${revision} complete.`,
    current_step_id: 'completed-1',
    run_steps: [
      {
        step_id: 'completed-1',
        kind: 'completed',
        state: 'completed',
        title: 'Run complete',
        summary: `Revision ${revision} complete.`,
      },
    ],
    blocks: [
      {
        id: 'activity:rd-session-1-turn-1',
        type: 'run_activity',
        step_ids: ['completed-1'],
      },
      {
        id: `message:revision-${revision}`,
        type: 'short_message',
        message: `Revision ${revision} complete.`,
        status: 'completed',
      },
    ],
    invariants: {},
    diagnostics: {},
    ...overrides,
  }
}

function snapshot(responseDocument, overrides = {}) {
  return {
    session: {
      session_id: 'session-1',
      status: responseDocument?.status === 'waiting_approval' ? 'WAITING_APPROVAL' : 'COMPLETED',
    },
    snapshot_revision: responseDocument?.revision ?? 0,
    response_document: responseDocument,
    ...overrides,
  }
}

test('response document reducer keeps the highest valid revision', () => {
  let state = createResponseDocumentReducerState()
  let result = applyResponseDocumentSnapshotUpdate(state, snapshot(doc({ revision: 1 })), { transport: 'polling' })
  assert.equal(result.accepted, true)
  state = result.state

  result = applyResponseDocumentSnapshotUpdate(state, snapshot(doc({ revision: 3 })), { transport: 'sse' })
  assert.equal(result.accepted, true)
  assert.equal(result.state.document.revision, 3)
  assert.equal(result.state.document.message, 'Revision 3 complete.')
})

test('response document reducer ignores stale lower revisions', () => {
  const current = applyResponseDocumentSnapshotUpdate(
    createResponseDocumentReducerState(),
    snapshot(doc({ revision: 5 })),
    { transport: 'sse' },
  ).state

  const result = applyResponseDocumentSnapshotUpdate(current, snapshot(doc({ revision: 4 })), { transport: 'polling' })
  assert.equal(result.accepted, false)
  assert.equal(result.decision, 'ignored_stale_revision')
  assert.equal(result.state.document.revision, 5)
  assert.equal(result.state.document.message, 'Revision 5 complete.')
})

test('response document reducer treats duplicate equal revisions as idempotent', () => {
  const first = applyResponseDocumentSnapshotUpdate(
    createResponseDocumentReducerState(),
    snapshot(doc({ revision: 2 })),
    { transport: 'polling' },
  ).state

  const duplicate = applyResponseDocumentSnapshotUpdate(first, snapshot(doc({ revision: 2 })), { transport: 'sse' })
  assert.equal(duplicate.accepted, false)
  assert.equal(duplicate.decision, 'ignored_duplicate_revision')
  assert.deepEqual(duplicate.state.document, first.document)
  assert.equal(duplicate.state.revision, first.revision)
})

test('response document reducer shows a safe diagnostic for the current invalid winning revision', () => {
  const invalid = {
    version: 1,
    id: 'rd-session-1-turn-1',
    document_id: 'rd-session-1-turn-1',
    turn_id: 'turn-1',
    revision: 7,
    state: 'completed',
    status: 'completed',
    run_steps: [],
  }

  const result = applyResponseDocumentSnapshotUpdate(
    createResponseDocumentReducerState(),
    snapshot(invalid, { snapshot_revision: 7 }),
    { transport: 'polling' },
  )

  assert.equal(result.accepted, true)
  assert.equal(result.state.status, 'invalid')
  assert.equal(result.state.document.revision, 7)
  assert.equal(result.state.document.blocks.some((block) => block.type === 'diagnostic'), true)
  assert.match(result.state.document.message, /could not render a valid response document/i)
})

test('response document reducer keeps a newer valid document when a stale invalid document arrives', () => {
  const current = applyResponseDocumentSnapshotUpdate(
    createResponseDocumentReducerState(),
    snapshot(doc({ revision: 8 })),
    { transport: 'sse' },
  ).state
  const staleInvalid = {
    version: 1,
    id: 'rd-session-1-turn-1',
    document_id: 'rd-session-1-turn-1',
    turn_id: 'turn-1',
    revision: 7,
    state: 'waiting_approval',
    status: 'waiting_approval',
    run_steps: [],
  }

  const result = applyResponseDocumentSnapshotUpdate(current, snapshot(staleInvalid, { snapshot_revision: 7 }), { transport: 'polling' })
  assert.equal(result.accepted, false)
  assert.equal(result.decision, 'ignored_stale_revision')
  assert.equal(result.state.document.revision, 8)
  assert.equal(result.state.document.invalid, false)
})

test('response document reducer lets a valid same-revision document repair an invalid current document', () => {
  const invalid = {
    version: 1,
    id: 'rd-session-1-turn-1',
    document_id: 'rd-session-1-turn-1',
    turn_id: 'turn-1',
    revision: 9,
    state: 'completed',
    status: 'completed',
    run_steps: [],
  }
  const invalidState = applyResponseDocumentSnapshotUpdate(
    createResponseDocumentReducerState(),
    snapshot(invalid, { snapshot_revision: 9 }),
    { transport: 'polling' },
  ).state

  const repaired = applyResponseDocumentSnapshotUpdate(invalidState, snapshot(doc({ revision: 9 })), { transport: 'sse' })
  assert.equal(repaired.accepted, true)
  assert.equal(repaired.decision, 'accepted_valid_same_revision_over_invalid')
  assert.equal(repaired.state.status, 'valid')
  assert.equal(repaired.state.document.invalid, false)
})

test('response document reducer applies SSE and polling through the same ordering path', () => {
  let state = createResponseDocumentReducerState()
  state = applyResponseDocumentSnapshotUpdate(state, snapshot(doc({ revision: 10 })), { transport: 'sse' }).state

  const pollingResult = applyResponseDocumentSnapshotUpdate(state, snapshot(doc({ revision: 6 })), { transport: 'polling' })
  assert.equal(pollingResult.accepted, false)
  assert.equal(pollingResult.decision, 'ignored_stale_revision')
  assert.equal(pollingResult.state.lastAcceptedTransport, 'sse')
  assert.equal(pollingResult.state.document.revision, 10)
})

test('response document reducer keeps the current document on conflicting equal revisions', () => {
  const first = doc({ revision: 11, message: 'Stable revision 11.', summary: 'Stable revision 11.' })
  const state = applyResponseDocumentSnapshotUpdate(
    createResponseDocumentReducerState(),
    snapshot(first),
    { transport: 'polling' },
  ).state
  const conflicting = doc({
    revision: 11,
    message: 'Conflicting revision 11.',
    summary: 'Conflicting revision 11.',
    blocks: [
      { id: 'activity:rd-session-1-turn-1', type: 'run_activity', step_ids: ['completed-1'] },
      { id: 'message:conflicting-revision-11', type: 'short_message', message: 'Conflicting revision 11.', status: 'completed' },
    ],
  })

  const result = applyResponseDocumentSnapshotUpdate(state, snapshot(conflicting), { transport: 'sse' })
  assert.equal(result.accepted, false)
  assert.equal(result.decision, 'ignored_conflicting_equal_revision')
  assert.equal(result.state.document.message, 'Stable revision 11.')
})

test('response document reducer accepts terminal equal revision over active progress', () => {
  const active = doc({
    revision: 11,
    state: 'running',
    status: 'running',
    message: 'Applying approved change.',
    summary: 'Applying approved change.',
    run_steps: [
      {
        step_id: 'applying-1',
        kind: 'mutation',
        state: 'current',
        title: 'Applying approved change',
        summary: 'Applying approved change.',
      },
    ],
    blocks: [
      { id: 'activity:rd-session-1-turn-1', type: 'run_activity', step_ids: ['applying-1'] },
      { id: 'message:active-revision-11', type: 'short_message', message: 'Applying approved change.', status: 'running' },
    ],
  })
  const state = applyResponseDocumentSnapshotUpdate(
    createResponseDocumentReducerState(),
    snapshot(active),
    { transport: 'sse' },
  ).state
  const terminal = doc({
    revision: 11,
    state: 'failed',
    status: 'failed',
    message: 'Some rows were updated, but other rows failed.',
    summary: 'Some rows were updated, but other rows failed.',
    run_steps: [
      {
        step_id: 'failed-1',
        kind: 'diagnostic',
        state: 'failed',
        title: 'Partial failure',
        summary: 'Some rows were updated, but other rows failed.',
      },
    ],
    blocks: [
      { id: 'activity:rd-session-1-turn-1', type: 'run_activity', step_ids: ['failed-1'] },
      { id: 'message:failed-revision-11', type: 'short_message', message: 'Some rows were updated, but other rows failed.', status: 'failed' },
    ],
  })

  const result = applyResponseDocumentSnapshotUpdate(state, snapshot(terminal), { transport: 'polling' })
  assert.equal(result.accepted, true)
  assert.equal(result.decision, 'accepted_terminal_equal_revision_over_active')
  assert.equal(result.state.document.message, 'Some rows were updated, but other rows failed.')
})

test('response document reducer accepts terminal lower revision over active progress', () => {
  const active = doc({
    revision: 8,
    state: 'running',
    status: 'running',
    message: "I'm working on the request and waiting for the next backend update.",
    summary: "I'm working on the request and waiting for the next backend update.",
    run_steps: [
      {
        step_id: 'checking-result',
        kind: 'mutation',
        state: 'current',
        title: 'Checking result',
        summary: 'Verifying the result',
      },
    ],
    blocks: [
      { id: 'activity:rd-session-1-turn-1', type: 'run_activity', step_ids: ['checking-result'] },
      {
        id: 'message:active-revision-8',
        type: 'short_message',
        message: "I'm working on the request and waiting for the next backend update.",
        status: 'running',
      },
    ],
  })
  const state = applyResponseDocumentSnapshotUpdate(
    createResponseDocumentReducerState(),
    snapshot(active, { snapshot_revision: 8 }),
    { transport: 'sse' },
  ).state

  const terminal = doc({
    revision: 3,
    state: 'completed',
    status: 'completed',
    message: 'I found a source-backed answer.',
    summary: 'I found a source-backed answer.',
    run_steps: [
      {
        step_id: 'completed-1',
        kind: 'completed',
        state: 'completed',
        title: 'Run complete',
        summary: 'I found a source-backed answer.',
      },
    ],
    blocks: [
      { id: 'activity:rd-session-1-turn-1', type: 'run_activity', step_ids: ['completed-1'] },
      { id: 'message:completed-revision-3', type: 'short_message', message: 'I found a source-backed answer.', status: 'completed' },
    ],
  })

  const result = applyResponseDocumentSnapshotUpdate(
    state,
    snapshot(terminal, { snapshot_revision: 3 }),
    { transport: 'polling' },
  )
  assert.equal(result.accepted, true)
  assert.equal(result.decision, 'accepted_terminal_lower_revision_over_active')
  assert.equal(result.state.document.revision, 3)
  assert.equal(result.state.document.message, 'I found a source-backed answer.')
})

test('response document reducer refuses older turn and document scopes', () => {
  const current = applyResponseDocumentSnapshotUpdate(
    createResponseDocumentReducerState(),
    snapshot(doc({ revision: 12, document_id: 'rd-session-1-turn-2', id: 'rd-session-1-turn-2', turn_id: 'turn-2' })),
    { transport: 'polling' },
  ).state
  const olderTurn = doc({
    revision: 8,
    document_id: 'rd-session-1-turn-1',
    id: 'rd-session-1-turn-1',
    turn_id: 'turn-1',
    message: 'Older turn should not win.',
    summary: 'Older turn should not win.',
  })

  const result = applyResponseDocumentSnapshotUpdate(
    current,
    snapshot(olderTurn, { snapshot_revision: 8 }),
    { transport: 'sse' },
  )
  assert.equal(result.accepted, false)
  assert.equal(result.decision, 'ignored_older_document_scope')
  assert.equal(result.state.turnId, 'turn-2')
})

test('response document reducer accepts a new session even when its revision is lower', () => {
  const current = applyResponseDocumentSnapshotUpdate(
    createResponseDocumentReducerState(),
    snapshot(doc({ revision: 12, document_id: 'rd-session-1-turn-2', id: 'rd-session-1-turn-2', turn_id: 'turn-2' }), {
      snapshot_revision: 12,
      session: { session_id: 'session-1', status: 'COMPLETED' },
    }),
    { transport: 'polling' },
  ).state
  const nextSessionDocument = doc({
    revision: 2,
    document_id: 'rd-session-2-turn-1',
    id: 'rd-session-2-turn-1',
    turn_id: 'turn-1',
    message: 'Session 2 approval is ready.',
    summary: 'Session 2 approval is ready.',
    state: 'waiting_approval',
    status: 'waiting_approval',
  })

  const result = applyResponseDocumentSnapshotUpdate(
    current,
    snapshot(nextSessionDocument, {
      snapshot_revision: 2,
      session: { session_id: 'session-2', status: 'WAITING_APPROVAL' },
      pending_approval: { approval_id: 'approval-session-2' },
    }),
    { transport: 'polling' },
  )

  assert.equal(result.accepted, true)
  assert.equal(result.decision, 'accepted_new_session_scope')
  assert.equal(result.state.sessionId, 'session-2')
  assert.equal(result.state.document.revision, 2)
  assert.equal(result.state.document.message, 'Session 2 approval is ready.')
})

test('response document reducer allows newer absent documents to use legacy fallback during migration', () => {
  const current = applyResponseDocumentSnapshotUpdate(
    createResponseDocumentReducerState(),
    snapshot(doc({ revision: 12 }), { snapshot_revision: 12 }),
    { transport: 'polling' },
  ).state

  const result = applyResponseDocumentSnapshotUpdate(
    current,
    {
      session: { session_id: 'session-1', status: 'EXECUTING' },
      snapshot_revision: 13,
      timeline: [],
    },
    { transport: 'polling' },
  )
  assert.equal(result.accepted, true)
  assert.equal(result.decision, 'accepted_newer_absent_response_document')
  assert.equal(result.state.status, 'absent')
  assert.equal(result.state.document, null)
})

test('response document reducer never merges old run_steps into a newer document', () => {
  let state = createResponseDocumentReducerState()
  const older = doc({
    revision: 3,
    run_steps: [
      { step_id: 'analysis-1', kind: 'analysis', state: 'completed', title: 'Understood request' },
      { step_id: 'approval-1', kind: 'approval', state: 'waiting', title: 'Waiting for approval 1', current: true },
    ],
  })
  state = applyResponseDocumentSnapshotUpdate(state, snapshot(older), { transport: 'polling' }).state

  const newer = doc({
    revision: 4,
    run_steps: [
      { step_id: 'completed-1', kind: 'completed', state: 'completed', title: 'Run complete' },
    ],
    blocks: [
      { id: 'activity:rd-session-1-turn-1', type: 'run_activity', step_ids: ['completed-1'] },
      { id: 'message:revision-4', type: 'short_message', message: 'Revision 4 complete.', status: 'completed' },
    ],
  })
  state = applyResponseDocumentSnapshotUpdate(state, snapshot(newer), { transport: 'sse' }).state

  assert.deepEqual(state.document.run_steps.map((step) => step.step_id), ['completed-1'])

  const stale = applyResponseDocumentSnapshotUpdate(state, snapshot(older), { transport: 'polling' })
  assert.equal(stale.accepted, false)
  assert.deepEqual(stale.state.document.run_steps.map((step) => step.step_id), ['completed-1'])
})
