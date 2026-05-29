import assert from 'node:assert/strict'
import test from 'node:test'

import {
  evaluateTransitionProbe,
  formatTransitionFailure,
  summarizeTransitionProbe,
} from './factoryAgentTransitionOracle.js'

function probe(overrides = {}) {
  return {
    checkpoint: 'after approval',
    snapshot: {
      session: { status: 'WAITING_APPROVAL' },
      phase: 'WAITING_APPROVAL',
      pending_approval: { approval_id: 'approval-2' },
      response_document: {
        state: 'waiting_approval',
        revision: 8,
        current_step_id: 'approval-2',
        blocks: [
          { type: 'completed_step', approval_id: 'approval-1' },
          { type: 'approval_required', approval_id: 'approval-2' },
        ],
      },
    },
    ui: {
      headerStatus: 'Waiting for approval',
      activeSidebarStatus: 'Waiting for approval',
      visibleBlockTypes: ['completed_step', 'approval_required'],
      visibleBlockIds: ['completed-step:approval-1', 'approval:approval-2'],
      approvalActionLabels: ['Approve', 'Reject'],
      visibleBlocks: [
        { type: 'completed_step', id: 'completed-step:approval-1', text: 'Completed step Updated 10 jobs.' },
        { type: 'approval_required', id: 'approval:approval-2', text: 'Approval required Update 11 jobs.' },
      ],
      latestAssistantText: 'Done. Please review approval 2 before I update original high-priority jobs.',
      visibleText: 'Done. Please review approval 2 before I update original high-priority jobs. Approval required Update 11 jobs.',
    },
    ...overrides,
  }
}

test('transition oracle accepts matching backend, header, sidebar, document, and visible blocks', () => {
  const result = evaluateTransitionProbe(probe(), {
    sessionStatus: 'WAITING_APPROVAL',
    responseState: 'waiting_approval',
    pendingApprovalId: 'approval-2',
    revisionGreaterThan: 4,
    visibleBlockTypes: ['completed_step', 'approval_required'],
    hiddenBlockIds: ['approval:approval-1'],
    textIncludes: [/approval 2/i],
    approvalActionCount: 2,
  })

  assert.equal(result.ok, true)
  assert.deepEqual(result.violations, [])
})

test('transition oracle reports compact mismatches when visible UI is stale', () => {
  const result = evaluateTransitionProbe(probe({
    ui: {
      headerStatus: 'Waiting for approval',
      activeSidebarStatus: 'Waiting for approval',
      visibleBlockTypes: ['approval_required'],
      visibleBlockIds: ['approval:approval-1'],
      approvalActionLabels: ['Approve', 'Reject'],
      visibleBlocks: [
        { type: 'approval_required', id: 'approval:approval-1', text: 'Approval required Update 10 jobs.' },
      ],
      latestAssistantText: 'Waiting for approval 1 Approval required Update 10 jobs.',
      visibleText: 'Waiting for approval 1 Approval required Update 10 jobs.',
    },
  }), {
    sessionStatus: 'WAITING_APPROVAL',
    responseState: 'waiting_approval',
    pendingApprovalId: 'approval-2',
    visibleBlockIds: ['approval:approval-2'],
    hiddenBlockIds: ['approval:approval-1'],
    forbidWaitingApproval1: true,
  })

  assert.equal(result.ok, false)
  assert.match(result.violations.join('\n'), /visible block ids missing approval:approval-2/)
  assert.match(result.violations.join('\n'), /visible block ids still contained approval:approval-1/)
  assert.match(result.violations.join('\n'), /stale Waiting for approval 1/)

  const message = formatTransitionFailure({
    checkpoint: 'after approval 1',
    expected: { sessionStatus: 'WAITING_APPROVAL', responseState: 'waiting_approval' },
    result,
  })
  assert.match(message, /after approval 1/)
  assert.match(message, /approval:approval-1/)
  assert.equal(result.summary.diagnosis.classification, 'reducer_ordering_gap')
})

test('transition oracle forbids internal diagnostics and final stale approval text', () => {
  const result = evaluateTransitionProbe(probe({
    snapshot: {
      session: { status: 'COMPLETED' },
      phase: 'COMPLETED',
      pending_approval: null,
      response_document: {
        state: 'completed',
        revision: 12,
        blocks: [{ type: 'result_summary' }],
      },
    },
    ui: {
      headerStatus: 'Complete',
      activeSidebarStatus: 'Complete',
      visibleBlockTypes: ['result_summary', 'approval_required'],
      visibleBlockIds: ['result-summary:rd-1', 'approval:approval-2'],
      approvalActionLabels: ['Approve'],
      visibleBlocks: [
        { type: 'result_summary', id: 'result-summary:rd-1', text: 'Updated 21 jobs.' },
        { type: 'approval_required', id: 'approval:approval-2', text: 'Approval required' },
      ],
      latestAssistantText: 'Updated 21 jobs. Approval required. Reason: non_terminal_snapshot',
      visibleText: 'Updated 21 jobs. Approval required. Reason: non_terminal_snapshot',
    },
  }), {
    sessionStatus: 'COMPLETED',
    responseState: 'completed',
    pendingApprovalId: null,
    hiddenBlockTypes: ['approval_required'],
    approvalActionCount: 0,
  })

  assert.equal(result.ok, false)
  assert.match(result.violations.join('\n'), /visible block types still contained approval_required/)
  assert.match(result.violations.join('\n'), /internal non_terminal_snapshot reason/)
  assert.match(result.violations.join('\n'), /stale Approval required after completion/)
})

test('transition oracle scopes text checks to the active response instead of stale sidebar sessions', () => {
  const result = evaluateTransitionProbe(probe({
    snapshot: {
      session: { status: 'COMPLETED' },
      phase: 'COMPLETED',
      pending_approval: null,
      response_document: {
        state: 'completed',
        revision: 12,
        blocks: [{ type: 'result_summary' }],
      },
    },
    ui: {
      headerStatus: 'Complete',
      activeSidebarStatus: 'Complete',
      visibleBlockTypes: ['result_summary'],
      visibleBlockIds: ['result-summary:rd-1'],
      approvalActionLabels: [],
      visibleBlocks: [
        { type: 'result_summary', id: 'result-summary:rd-1', text: 'Run complete. Updated 21 jobs.' },
      ],
      latestAssistantText: 'Run complete. Updated 21 jobs.',
      visibleText: 'Chat 1 Complete Chat 2 Waiting for approval Run complete. Updated 21 jobs.',
    },
  }), {
    sessionStatus: 'COMPLETED',
    responseState: 'completed',
    pendingApprovalId: null,
    visibleBlockTypes: ['result_summary'],
    hiddenBlockTypes: ['approval_required'],
    approvalActionCount: 0,
    textIncludes: [/Run complete/i],
    textExcludes: [/Waiting for approval/i, /Approval required/i],
  })

  assert.equal(result.ok, true)
  assert.deepEqual(result.violations, [])
})

test('transition oracle includes final response visual-quality violations in compact summary', () => {
  const result = evaluateTransitionProbe(probe({
    snapshot: {
      session: { status: 'COMPLETED' },
      phase: 'COMPLETED',
      pending_approval: null,
      response_document: {
        state: 'completed',
        revision: 15,
        blocks: [{ type: 'result_summary' }, { type: 'mutation_result' }],
      },
    },
    ui: {
      headerStatus: 'Complete',
      activeSidebarStatus: 'Complete',
      visibleBlockTypes: ['result_summary', 'mutation_result'],
      visibleBlockIds: ['result-summary:rd-001', 'mutation:rd-001'],
      approvalActionLabels: [],
      visibleBlocks: [
        { type: 'result_summary', id: 'result-summary:rd-001', text: 'Updated 63 jobs across 22 approved steps.' },
        { type: 'mutation_result', id: 'mutation:rd-001', text: 'Operation ID: op-1' },
      ],
      latestAssistantText: 'Updated 63 jobs across 22 approved steps. Operation ID: op-1',
      visibleText: 'Updated 63 jobs across 22 approved steps. Operation ID: op-1',
      finalResponseQuality: {
        finalResultCardCount: 2,
        finalSummaryText: 'Updated 63 jobs across 22 approved steps.',
        businessGroups: [{ label: 'Medium -> High', count: 10 }],
        affectedRecordPreviewCount: 21,
        expandableAuditPresent: false,
        forbiddenTextHits: ['backend operation aggregate leak', 'internal Operation ID'],
        duplicateAffectedRecordEvidence: [],
      },
    },
  }), {
    sessionStatus: 'COMPLETED',
    responseState: 'completed',
    visibleBlockTypes: ['result_summary', 'mutation_result'],
    approvalActionCount: 0,
    finalResponseQuality: {
      finalResultCardCount: 1,
      finalSummaryText: /21 jobs across 2 approved business changes/,
      businessGroups: [
        { label: 'Medium -> High', count: 10 },
        { label: 'Original High -> Low', count: 11 },
      ],
      affectedRecordPreviewMax: 5,
      expandableAuditPresent: true,
    },
  })

  assert.equal(result.ok, false)
  assert.match(result.violations.join('\n'), /final result card count expected 1 but saw 2/)
  assert.match(result.violations.join('\n'), /forbidden final response text/)
  assert.equal(result.summary.diagnosis.classification, 'final_response_visual_quality_gap')
})

test('transition oracle summary keeps only high-signal fields', () => {
  const summary = summarizeTransitionProbe(probe())
  assert.equal(summary.kind, 'factory_agent_response_document_semantic_probe')
  assert.equal(summary.backend.sessionStatus, 'WAITING_APPROVAL')
  assert.equal(summary.backend.phase, 'WAITING_APPROVAL')
  assert.equal(summary.backend.pendingApprovalId, 'approval-2')
  assert.equal(summary.backend.responseDocumentState, 'waiting_approval')
  assert.equal(summary.backend.responseDocumentRevision, 8)
  assert.equal(summary.backend.responseDocumentCurrentStepId, 'approval-2')
  assert.deepEqual(summary.backend.responseBlockTypes, ['completed_step', 'approval_required'])
  assert.deepEqual(summary.backend.responseApprovalIds, ['approval-1', 'approval-2'])
  assert.deepEqual(summary.visible.visibleBlockTypes, ['completed_step', 'approval_required'])
  assert.equal(summary.artifactUse, 'Read this semantic probe first; screenshots and traces are supporting evidence.')
})
