import assert from 'node:assert/strict'
import test from 'node:test'

import { findSensitiveArtifactLeaks, sensitiveArtifactSamples } from './artifactRedaction.js'
import {
  buildSemanticProbe,
  finalResponseQualityViolations,
  serializeSemanticProbe,
} from './responseDocumentProbe.js'

function baseSnapshot(overrides = {}) {
  return {
    session: {
      session_id: 'session-phase12',
      name: 'Chat 12',
      status: 'WAITING_APPROVAL',
    },
    phase: 'WAITING_APPROVAL',
    pending_approval: { approval_id: 'approval-2' },
    response_document: {
      state: 'waiting_approval',
      revision: 8,
      current_step_id: 'approval-2',
      run_steps: [
        { step_id: 'analysis-1', kind: 'analysis', state: 'completed', title: 'Understood request' },
        { step_id: 'approval-2', kind: 'approval', state: 'waiting', title: 'Waiting for approval 2', approval_id: 'approval-2', current: true },
      ],
      blocks: [
        { id: 'completed-step:approval-1', type: 'completed_step', title: 'Completed step', summary: 'Updated 10 jobs.', approval_id: 'approval-1' },
        { id: 'approval:approval-2', type: 'approval_required', title: 'Approval required', summary: 'Update 11 jobs.', approval_id: 'approval-2' },
      ],
    },
    ...overrides,
  }
}

function baseUi(overrides = {}) {
  return {
    activeSessionId: 'session-phase12',
    activeSessionName: 'Chat 12',
    headerStatus: 'Waiting for approval',
    activeSidebarStatus: 'Waiting for approval',
    latestUserPrompt: 'change all medium priority job to high then change all high priority job to low',
    latestAssistantTitle: 'eMAS Response',
    latestAssistantMessage: 'Done. Please review approval 2 before I update original high-priority jobs.',
    visibleBlockTypes: ['completed_step', 'approval_required'],
    visibleBlockIds: ['completed-step:approval-1', 'approval:approval-2'],
    visibleBlocks: [
      { type: 'completed_step', id: 'completed-step:approval-1', title: 'Completed step', text: 'Completed step Updated 10 jobs.', buttons: [] },
      { type: 'approval_required', id: 'approval:approval-2', title: 'Approval required', text: 'Approval required Update 11 jobs.', buttons: ['Approve', 'Reject'] },
    ],
    visibleRunSteps: [
      { title: 'Waiting for approval 2', state: 'waiting' },
    ],
    visibleApprovalIds: ['approval-2'],
    approvalActionLabels: ['Approve', 'Reject'],
    visibleText: 'Done. Waiting for approval 2. Approval required Update 11 jobs.',
    ...overrides,
  }
}

test('semantic probe builds compact current-turn summary from mocked UI and backend evidence', () => {
  const probe = buildSemanticProbe({
    checkpoint: 'after approval 1',
    snapshot: baseSnapshot(),
    ui: baseUi(),
    expected: {
      sessionStatus: 'WAITING_APPROVAL',
      responseState: 'waiting_approval',
      pendingApprovalId: 'approval-2',
      visibleBlockTypes: ['completed_step', 'approval_required'],
    },
  })

  assert.equal(probe.kind, 'factory_agent_response_document_semantic_probe')
  assert.equal(probe.activeSession.id, 'session-phase12')
  assert.equal(probe.visible.latestUserPrompt, 'change all medium priority job to high then change all high priority job to low')
  assert.deepEqual(probe.visible.visibleBlockTypes, ['completed_step', 'approval_required'])
  assert.deepEqual(probe.visible.visibleRunSteps, [{ title: 'Waiting for approval 2', state: 'waiting' }])
  assert.equal(probe.backend.sessionStatus, 'WAITING_APPROVAL')
  assert.equal(probe.backend.responseDocument.revision, 8)
  assert.deepEqual(probe.backend.responseDocument.blockTypes, ['completed_step', 'approval_required'])
  assert.equal(probe.diagnosis.classification, 'unknown')
})

test('semantic probe classifies header/sidebar/backend mismatch as session_list_sync_gap', () => {
  const probe = buildSemanticProbe({
    checkpoint: 'status mismatch',
    snapshot: baseSnapshot(),
    ui: baseUi({
      headerStatus: 'Ready',
      activeSidebarStatus: 'Complete',
    }),
    expected: { sessionStatus: 'WAITING_APPROVAL', responseState: 'waiting_approval' },
  })

  assert.equal(probe.diagnosis.classification, 'session_list_sync_gap')
  assert.match(probe.diagnosis.reasons.join('\n'), /header shows Ready/)
})

test('semantic probe classifies response_document state mismatch as response_document_gap', () => {
  const probe = buildSemanticProbe({
    checkpoint: 'document mismatch',
    snapshot: baseSnapshot({
      response_document: {
        state: 'completed',
        revision: 8,
        current_step_id: 'completed',
        run_steps: [{ step_id: 'completed', state: 'completed', title: 'Run complete' }],
        blocks: [{ id: 'result-summary:1', type: 'result_summary', summary: 'Updated 21 jobs.' }],
      },
    }),
    ui: baseUi(),
    expected: { sessionStatus: 'WAITING_APPROVAL', responseState: 'waiting_approval' },
  })

  assert.equal(probe.diagnosis.classification, 'response_document_gap')
  assert.match(probe.diagnosis.reasons.join('\n'), /response_document\.state expected waiting_approval/)
})

test('semantic probe classifies stale approval UI after backend completion as reducer_ordering_gap', () => {
  const probe = buildSemanticProbe({
    checkpoint: 'final completion with stale approval visible',
    snapshot: baseSnapshot({
      session: { session_id: 'session-phase12', name: 'Chat 12', status: 'COMPLETED' },
      phase: 'COMPLETED',
      pending_approval: null,
      response_document: {
        state: 'completed',
        revision: 12,
        current_step_id: 'completed',
        run_steps: [{ step_id: 'completed', kind: 'completed', state: 'completed', title: 'Run complete' }],
        blocks: [{ id: 'result-summary:final', type: 'result_summary', title: 'Run complete', summary: 'Updated 21 jobs.' }],
      },
    }),
    ui: baseUi({
      headerStatus: 'Complete',
      activeSidebarStatus: 'Complete',
      visibleBlockTypes: ['approval_required'],
      visibleBlockIds: ['approval:approval-2'],
      visibleBlocks: [
        { type: 'approval_required', id: 'approval:approval-2', title: 'Approval required', text: 'Approval required Update 11 jobs.', buttons: ['Approve', 'Reject'] },
      ],
      visibleApprovalIds: ['approval-2'],
      approvalActionLabels: ['Approve', 'Reject'],
      visibleText: 'Complete Approval required Update 11 jobs.',
    }),
    expected: { sessionStatus: 'COMPLETED', responseState: 'completed', pendingApprovalId: null },
  })

  assert.equal(probe.diagnosis.classification, 'reducer_ordering_gap')
  assert.match(probe.diagnosis.reasons.join('\n'), /completed.*approval UI/)
})

test('semantic probe redacts or avoids raw secrets, tokens, and stack traces', () => {
  const probe = buildSemanticProbe({
    checkpoint: 'redaction',
    snapshot: baseSnapshot(),
    ui: baseUi({
      latestAssistantMessage: `Authorization: ${sensitiveArtifactSamples.bearer}\nTraceback (most recent call last):\n  at unsafe.js:1:2`,
      visibleBlocks: [
        { type: 'diagnostic', id: 'diagnostic:unsafe', title: 'Needs attention', text: `password=${sensitiveArtifactSamples.queryToken} sk-phase16unsafeartifact123456`, buttons: [] },
      ],
      visibleText: `Needs attention token=${sensitiveArtifactSamples.queryToken}\nTraceback (most recent call last):\n  at unsafe.js:1:2`,
    }),
    violations: [`raw failure ${sensitiveArtifactSamples.apiKey} stack trace at unsafe.js:1:2`],
  })
  const body = serializeSemanticProbe(probe)

  assert.deepEqual(findSensitiveArtifactLeaks(body), [])
  assert.doesNotMatch(body, /phase16-visible-token-abcdef123456/)
  assert.doesNotMatch(body, /phase16-query-token-abcdef123456/)
  assert.doesNotMatch(body, /sk-phase16unsafeartifact123456/)
  assert.doesNotMatch(body, /at unsafe\.js:1:2/)
  assert.match(body, /\[stack trace redacted\]|stack trace at unsafe\.js/)
})

test('semantic probe stays under the artifact size and readability budget', () => {
  const probe = buildSemanticProbe({
    checkpoint: 'budget',
    snapshot: baseSnapshot(),
    ui: baseUi({
      latestAssistantMessage: 'x '.repeat(2000),
      visibleBlocks: Array.from({ length: 40 }, (_, index) => ({
        type: index % 2 === 0 ? 'completed_step' : 'approval_required',
        id: `block:${index}`,
        title: `Block ${index}`,
        text: `Long block ${index} ${'details '.repeat(100)}`,
        buttons: index === 39 ? ['Approve', 'Reject'] : [],
      })),
    }),
  })
  const lines = serializeSemanticProbe(probe).split(/\r?\n/)

  assert.ok(lines.length < 200, `expected probe under 200 lines, saw ${lines.length}`)
})

test('semantic probe summarizes final response visual quality evidence', () => {
  const probe = buildSemanticProbe({
    checkpoint: 'final visual quality',
    snapshot: baseSnapshot({
      session: { session_id: 'session-phase15', name: 'Chat 15', status: 'COMPLETED' },
      phase: 'COMPLETED',
      pending_approval: null,
      response_document: {
        state: 'completed',
        revision: 15,
        current_step_id: 'completed-1',
        run_steps: [{ step_id: 'completed-1', kind: 'completed', state: 'completed', title: 'Run complete' }],
        blocks: [
          { id: 'result-summary:rd-001', type: 'result_summary', title: 'Changes completed', summary: 'Done. I updated 21 jobs across 2 approved business changes.' },
          { id: 'mutation:rd-001', type: 'mutation_result', contract: 'business_change_v1', title: 'Affected records', summary: 'Done. I updated 21 jobs across 2 approved business changes.' },
        ],
      },
    }),
    ui: baseUi({
      headerStatus: 'Complete',
      activeSidebarStatus: 'Complete',
      visibleBlockTypes: ['result_summary', 'mutation_result'],
      visibleBlockIds: ['result-summary:rd-001', 'mutation:rd-001'],
      visibleBlocks: [
        { type: 'result_summary', id: 'result-summary:rd-001', title: 'Changes completed', text: 'Done. I updated 21 jobs across 2 approved business changes.', buttons: [] },
        { type: 'mutation_result', id: 'mutation:rd-001', contract: 'business_change_v1', title: 'Affected records', text: 'Medium -> High: 10 jobs Original High -> Low: 11 jobs', buttons: [] },
      ],
      visibleContracts: ['business_change_v1'],
      approvalActionLabels: [],
      visibleApprovalIds: [],
      visibleText: 'Done. I updated 21 jobs across 2 approved business changes. Medium -> High: 10 jobs Original High -> Low: 11 jobs',
      finalResponseQuality: {
        finalResultCardCount: 1,
        finalSummaryText: 'Done. I updated 21 jobs across 2 approved business changes.',
        businessGroups: [
          { label: 'Medium -> High', count: 10, contract: 'business_change_v1', entityType: 'job', fieldChangeCount: 1, text: 'Medium -> High: 10 jobs' },
          { label: 'Original High -> Low', count: 11, contract: 'business_change_v1', entityType: 'job', fieldChangeCount: 1, text: 'Original High -> Low: 11 jobs' },
        ],
        affectedRecordPreviewCount: 5,
        expandableAuditPresent: true,
        auditExpanded: false,
        expandedAuditGroups: [],
        forbiddenTextHits: [],
        duplicateAffectedRecordEvidence: [],
      },
    }),
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      pendingApprovalId: null,
      finalResponseQuality: {
        finalResultCardCount: 1,
        finalSummaryText: /21 jobs across 2 approved business changes/,
        businessGroups: [
          { label: 'Medium -> High', count: 10, contract: 'business_change_v1', entityType: 'job', fieldChangeCountMin: 1 },
          { label: 'Original High -> Low', count: 11, contract: 'business_change_v1', entityType: 'job', fieldChangeCountMin: 1 },
        ],
        affectedRecordPreviewMax: 5,
        expandableAuditPresent: true,
      },
    },
  })

  assert.equal(probe.diagnosis.classification, 'unknown')
  assert.equal(probe.visible.finalResponseQuality.finalResultCardCount, 1)
  assert.deepEqual(probe.visible.visibleContracts, ['business_change_v1'])
  assert.deepEqual(probe.backend.responseContracts, ['business_change_v1'])
  assert.deepEqual(
    probe.visible.finalResponseQuality.businessGroups.map((group) => [group.label, group.count, group.contract]),
    [['Medium -> High', 10, 'business_change_v1'], ['Original High -> Low', 11, 'business_change_v1']],
  )
})

test('final response quality violations explain noisy or duplicated rendered output', () => {
  const violations = finalResponseQualityViolations({
    finalResultCardCount: 2,
    finalSummaryText: 'Updated 63 jobs across 22 approved steps.',
    businessGroups: [{ label: 'Medium -> High', count: 10 }],
    affectedRecordPreviewCount: 21,
    expandableAuditPresent: false,
    auditExpanded: false,
    expandedAuditGroups: [],
    forbiddenTextHits: ['backend operation aggregate leak', 'internal Operation ID'],
    duplicateAffectedRecordEvidence: [{ section: 'clean-audit:Medium -> High', records: ['JOB-SEED-002'] }],
  }, {
    finalResponseQuality: {
      finalResultCardCount: 1,
      finalSummaryText: /21 jobs across 2 approved business changes/,
      businessGroups: [
        { label: 'Medium -> High', count: 10 },
        { label: 'Original High -> Low', count: 11 },
      ],
      affectedRecordPreviewMax: 5,
      expandableAuditPresent: true,
      forbidDuplicateAffectedRecords: true,
    },
  })

  assert.match(violations.join('\n'), /final result card count expected 1 but saw 2/)
  assert.match(violations.join('\n'), /business change group missing Original High -> Low/)
  assert.match(violations.join('\n'), /affected-record preview expected at most 5/)
  assert.match(violations.join('\n'), /forbidden final response text/)
  assert.match(violations.join('\n'), /duplicate affected records/)
})
