import assert from 'node:assert/strict'
import test from 'node:test'

import { findSensitiveArtifactLeaks, sensitiveArtifactSamples } from './artifactRedaction.js'
import {
  buildSemanticProbe,
  finalResponseQualityViolations,
  machineStatusOnlyForbiddenDetailProbeText,
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

test('semantic probe summarizes Phase 37 status display policy evidence', () => {
  const snapshot = baseSnapshot({
    session: { session_id: 'session-phase37', name: 'Machine status', status: 'COMPLETED' },
    phase: 'COMPLETED',
    pending_approval: null,
    response_document: {
      state: 'completed',
      revision: 37,
      current_step_id: 'completed-status',
      run_steps: [{ step_id: 'completed-status', kind: 'completed', state: 'completed', title: 'Run complete' }],
      blocks: [
        {
          id: 'status:machine',
          type: 'status_result',
          contract: 'entity_status_v1',
          title: 'Machine status',
          entity_type: 'machine',
          read_scope: 'status_only',
          requested_fields: ['machine_id', 'status'],
          display_mode: 'compact_status_card',
          entity_count: 1,
          preview_limit: 5,
          details_collapsed: true,
          fields: [
            { key: 'machine_id', label: 'Machine ID', value: 'M-CNC-01' },
            { key: 'status', label: 'Status', value: 'running', primary: true },
          ],
          secondary_fields: [],
        },
      ],
      invariants: {
        read_scope: 'status_only',
        requested_fields: ['machine_id', 'status'],
        display_mode: 'compact_status_card',
        entity_count: 1,
        preview_limit: 5,
        read_details_collapsed: true,
        read_status_contract: 'entity_status_v1',
      },
    },
  })
  const ui = baseUi({
    headerStatus: 'Complete',
    activeSidebarStatus: 'Complete',
    visibleBlockTypes: ['status_result'],
    visibleBlockIds: ['status:machine'],
    visibleContracts: ['entity_status_v1'],
    visibleBlocks: [
      {
        type: 'status_result',
        id: 'status:machine',
        contract: 'entity_status_v1',
        entityType: 'machine',
        readScope: 'status_only',
        requestedFields: ['machine_id', 'status'],
        displayMode: 'compact_status_card',
        entityCount: 1,
        previewLimit: 5,
        detailsCollapsed: true,
        fieldCount: 2,
        secondaryFieldCount: 0,
        title: 'Machine status',
        text: 'Machine status Machine ID M-CNC-01 Status running',
        buttons: [],
      },
    ],
    approvalActionLabels: [],
    visibleApprovalIds: [],
    visibleText: 'Machine status Machine ID M-CNC-01 Status running',
  })
  const probe = buildSemanticProbe({
    checkpoint: 'phase37 status evidence',
    snapshot,
    ui,
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      pendingApprovalId: null,
      visibleBlockTypes: ['status_result'],
      backendBlockTypes: ['status_result'],
      responseContracts: ['entity_status_v1'],
      forbiddenText: machineStatusOnlyForbiddenDetailProbeText,
    },
  })

  assert.equal(probe.diagnosis.classification, 'unknown')
  assert.deepEqual(probe.backend.responseDocument.readPolicy, {
    readScope: 'status_only',
    requestedFields: ['machine_id', 'status'],
    displayMode: 'compact_status_card',
    entityCount: 1,
    previewLimit: 5,
    detailsCollapsed: true,
  })
  assert.deepEqual(
    probe.backend.responseDocument.blocks.map((block) => [
      block.type,
      block.contract,
      block.readScope,
      block.requestedFields.join(','),
      block.displayMode,
      block.entityCount,
      block.fieldCount,
      block.secondaryFieldCount,
    ]),
    [['status_result', 'entity_status_v1', 'status_only', 'machine_id,status', 'compact_status_card', 1, 2, 0]],
  )
  assert.deepEqual(
    probe.visible.visibleBlocks.map((block) => [block.readScope, block.requestedFields.join(','), block.displayMode, block.entityCount, block.fieldCount, block.secondaryFieldCount]),
    [['status_only', 'machine_id,status', 'compact_status_card', 1, 2, 0]],
  )
})

test('semantic probe summarizes replan safe failure without startup wording', () => {
  const snapshot = baseSnapshot({
    session: { session_id: 'session-replan-limit', name: 'Machine status', status: 'BLOCKED' },
    phase: 'BLOCKED',
    pending_approval: null,
    response_document: {
      state: 'blocked',
      revision: 41,
      current_step_id: 'diagnostic:replan-limit',
      run_steps: [
        {
          step_id: 'diagnostic:replan-limit',
          kind: 'diagnostic',
          state: 'failed',
          title: 'Run needs attention',
          current: true,
          diagnostics: { error_code: 'replan_limit_reached', sanitized: true },
        },
      ],
      blocks: [
        {
          id: 'diagnostic:replan-limit',
          type: 'diagnostic',
          title: 'Run needs attention',
          reason: 'replan_limit_reached',
          user_message: 'I could not verify the requested evidence after bounded retries.',
          technical_details: { error_code: 'planner_no_action', sanitized: true },
          details_collapsed: true,
        },
      ],
      diagnostics: { reason: 'replan_limit_reached', sanitized: true },
    },
  })
  const ui = baseUi({
    headerStatus: 'Needs attention',
    activeSidebarStatus: 'Needs attention',
    latestAssistantTitle: 'eMAS Response',
    latestAssistantMessage: 'Run needs attention I could not verify the requested evidence after bounded retries. Technical details',
    visibleBlockTypes: ['diagnostic'],
    visibleBlockIds: ['diagnostic:replan-limit'],
    visibleBlocks: [
      {
        type: 'diagnostic',
        id: 'diagnostic:replan-limit',
        title: 'Run needs attention',
        text: 'Run needs attention I could not verify the requested evidence after bounded retries. Technical details',
        buttons: [],
      },
    ],
    visibleRunSteps: [{ title: 'Run needs attention', state: 'error' }],
    visibleApprovalIds: [],
    approvalActionLabels: [],
    visibleText: 'Needs attention Run needs attention I could not verify the requested evidence after bounded retries. Technical details',
  })
  const probe = buildSemanticProbe({
    checkpoint: 'replan safe failure',
    snapshot,
    ui,
    expected: {
      sessionStatus: 'BLOCKED',
      responseState: 'blocked',
      visibleBlockTypes: ['diagnostic'],
      backendBlockTypes: ['diagnostic'],
    },
  })

  assert.equal(probe.diagnosis.classification, 'unknown')
  assert.match(probe.visible.latestAssistant.message, /could not verify the requested evidence after bounded retries/i)
  assert.doesNotMatch(probe.visible.latestAssistant.message, /Request could not start|planner_no_action/i)
  assert.equal(probe.backend.responseDocument.blocks[0].title, 'Run needs attention')
  assert.match(probe.backend.responseDocument.blocks[0].summary, /could not verify the requested evidence/i)
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

test('final response quality guardrail rejects text-only business group expectations', () => {
  const violations = finalResponseQualityViolations({
    finalResultCardCount: 1,
    finalSummaryText: 'Done. I updated 21 jobs across 2 approved business changes.',
    businessGroups: [
      { label: 'Medium -> High', count: 10 },
      { label: 'Original High -> Low', count: 11 },
    ],
    affectedRecordPreviewCount: 5,
    expandableAuditPresent: true,
    forbiddenTextHits: [],
    duplicateAffectedRecordEvidence: [],
  }, {
    finalResponseQuality: {
      finalResultCardCount: 1,
      businessGroups: [
        { label: 'Medium -> High', count: 10 },
        { label: 'Original High -> Low', count: 11 },
      ],
    },
  })

  assert.match(violations.join('\n'), /text-only business group expectation Medium -> High/)
  assert.match(violations.join('\n'), /typed contract evidence/)
})

test('final response quality guardrail requires typed field evidence for business_change_v1 checks', () => {
  const violations = finalResponseQualityViolations({
    finalResultCardCount: 1,
    finalSummaryText: 'Done. I updated 1 material across 1 approved business change.',
    businessGroups: [
      { label: 'Material hold status', count: 1, contract: 'business_change_v1', entityType: 'material' },
    ],
    affectedRecordPreviewCount: 1,
    expandableAuditPresent: true,
    forbiddenTextHits: [],
    duplicateAffectedRecordEvidence: [],
  }, {
    finalResponseQuality: {
      finalResultCardCount: 1,
      businessGroups: [
        { label: 'Material hold status', count: 1, contract: 'business_change_v1', entityType: 'material' },
      ],
    },
  })

  assert.match(violations.join('\n'), /business_change_v1 expectation Material hold status must include typed field-change evidence/)
})

test('semantic probe summarizes typed RAG source chip and citation evidence', () => {
  const probe = buildSemanticProbe({
    checkpoint: 'typed RAG source citation',
    snapshot: baseSnapshot({
      session: { session_id: 'session-phase28', name: 'Chat 28', status: 'COMPLETED' },
      phase: 'COMPLETED',
      pending_approval: null,
      response_document: {
        state: 'completed',
        revision: 28,
        current_step_id: 'completed-rag',
        run_steps: [{ step_id: 'completed-rag', kind: 'completed', state: 'completed', title: 'Run complete' }],
        blocks: [
          { id: 'safety:loto', type: 'safety_notice', contract: 'safety_notice_v1', safety_content: 'Follow the site SOP.' },
          {
            id: 'knowledge:loto',
            type: 'knowledge_answer',
            contract: 'knowledge_answer_v1',
            answer: 'Notify affected employees before lockout.',
            citations: [
              {
                contract: 'source_citation_v1',
                citation_id: 'citation:LOTO#chunk-1',
                source_id: 'LOTO#chunk-1',
                source_number: 1,
                doc_id: 'LOTO',
                chunk_id: 'chunk-1',
                title: 'LOTO Procedure',
              },
            ],
          },
          {
            id: 'sources:loto',
            type: 'source_list',
            contract: 'source_list_v1',
            sources: [{ contract: 'source_locator_v1', source_id: 'LOTO#chunk-1', doc_id: 'LOTO', chunk_id: 'chunk-1' }],
          },
        ],
      },
    }),
    ui: baseUi({
      headerStatus: 'Complete',
      activeSidebarStatus: 'Complete',
      visibleBlockTypes: ['safety_notice', 'knowledge_answer', 'source_list'],
      visibleBlockIds: ['safety:loto', 'knowledge:loto', 'sources:loto'],
      visibleContracts: ['safety_notice_v1', 'knowledge_answer_v1', 'source_list_v1', 'source_locator_v1'],
      visibleBlocks: [
        { type: 'safety_notice', id: 'safety:loto', contract: 'safety_notice_v1', title: 'Safety notice', text: 'Safety notice Follow the site SOP.', buttons: [] },
        { type: 'knowledge_answer', id: 'knowledge:loto', contract: 'knowledge_answer_v1', title: 'Procedure guidance', text: 'Notify affected employees before lockout. [1]', buttons: ['[1]'] },
        { type: 'source_list', id: 'sources:loto', contract: 'source_list_v1', title: 'Knowledge sources', text: 'LOTO Procedure', buttons: [] },
      ],
      sourceChips: [{ sourceId: 'LOTO#chunk-1', docId: 'LOTO', chunkId: 'chunk-1', sourceNumber: '1', text: '[1]' }],
      sourceDrawer: { open: true, sourceId: 'LOTO#chunk-1', docId: 'LOTO', chunkId: 'chunk-1', text: 'LOTO Procedure Notify affected employees before lockout.' },
      approvalActionLabels: [],
      visibleApprovalIds: [],
      visibleText: 'Safety notice Follow the site SOP. Procedure guidance Notify affected employees before lockout. [1] Knowledge sources LOTO Procedure',
    }),
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      pendingApprovalId: null,
      visibleBlockTypes: ['safety_notice', 'knowledge_answer', 'source_list'],
      backendBlockTypes: ['safety_notice', 'knowledge_answer', 'source_list'],
      responseContracts: ['safety_notice_v1', 'knowledge_answer_v1', 'source_list_v1', 'source_locator_v1'],
    },
  })

  assert.equal(probe.diagnosis.classification, 'unknown')
  assert.deepEqual(probe.visible.sourceChips.map((chip) => [chip.sourceId, chip.docId, chip.chunkId]), [['LOTO#chunk-1', 'LOTO', 'chunk-1']])
  assert.equal(probe.visible.sourceDrawer.open, true)
  assert.deepEqual(probe.backend.responseDocument.sourceCitations.map((citation) => citation.contract), ['source_citation_v1'])
  assert.ok(probe.backend.responseContracts.includes('source_locator_v1'))
})

test('semantic probe summarizes side evidence drawer and in-panel PDF state', () => {
  const probe = buildSemanticProbe({
    checkpoint: 'side evidence PDF panel',
    snapshot: baseSnapshot({
      session: { session_id: 'session-phase33', name: 'Chat 33', status: 'COMPLETED' },
      phase: 'COMPLETED',
      pending_approval: null,
      response_document: {
        state: 'completed',
        revision: 33,
        current_step_id: 'completed-rag',
        run_steps: [{ step_id: 'completed-rag', kind: 'completed', state: 'completed', title: 'Run complete' }],
        blocks: [
          {
            id: 'knowledge:osha',
            type: 'knowledge_answer',
            contract: 'knowledge_answer_v1',
            answer: 'Notify affected employees before reenergizing.',
            citations: [
              {
                contract: 'source_citation_v1',
                citation_id: 'citation:osha#chunk-29',
                source_id: 'osha#chunk-29',
                source_number: 1,
                doc_id: 'osha',
                chunk_id: 'chunk-29',
                title: 'OSHA LOTO',
              },
            ],
          },
          {
            id: 'sources:osha',
            type: 'source_list',
            contract: 'source_list_v1',
            sources: [
              { contract: 'source_locator_v1', source_id: 'osha#chunk-29', source_number: 1, doc_id: 'osha', chunk_id: 'chunk-29', title: 'OSHA LOTO' },
              { contract: 'source_locator_v1', source_id: 'osha#chunk-30', source_number: 2, doc_id: 'osha', chunk_id: 'chunk-30', title: 'OSHA LOTO' },
            ],
          },
        ],
      },
    }),
    ui: baseUi({
      headerStatus: 'Complete',
      activeSidebarStatus: 'Complete',
      visibleBlockTypes: ['knowledge_answer', 'source_list'],
      visibleBlockIds: ['knowledge:osha', 'sources:osha'],
      visibleContracts: ['knowledge_answer_v1', 'source_list_v1', 'source_locator_v1'],
      visibleBlocks: [
        { type: 'knowledge_answer', id: 'knowledge:osha', contract: 'knowledge_answer_v1', title: 'Procedure guidance', text: 'Notify affected employees before reenergizing. [1]', buttons: ['[1]'] },
        { type: 'source_list', id: 'sources:osha', contract: 'source_list_v1', title: 'Knowledge sources', text: 'OSHA LOTO', buttons: [] },
      ],
      sourceChips: [{ sourceId: 'osha#chunk-29', docId: 'osha', chunkId: 'chunk-29', sourceNumber: '1', title: 'OSHA LOTO', text: '[1]' }],
      citedAnswerHighlights: [{ sourceId: 'osha#chunk-29', docId: 'osha', chunkId: 'chunk-29', sourceNumber: '1', title: 'OSHA LOTO', text: 'Notify affected employees before reenergizing.' }],
      sourceDrawer: {
        open: true,
        view: 'pdf',
        sourceId: 'osha#chunk-29',
        docId: 'osha',
        chunkId: 'chunk-29',
        sourceNumber: '1',
        title: 'OSHA LOTO',
        entries: [
          { role: 'cited', sourceId: 'osha#chunk-29', docId: 'osha', chunkId: 'chunk-29', sourceNumber: '1', title: 'OSHA LOTO', openMode: 'exact', highlightKind: 'char_range' },
          { role: 'related', sourceId: 'osha#chunk-30', docId: 'osha', chunkId: 'chunk-30', sourceNumber: '2', title: 'OSHA LOTO', openMode: 'search', highlightKind: 'text_search' },
        ],
        pdf: {
          sourceId: 'osha#chunk-29',
          docId: 'osha',
          chunkId: 'chunk-29',
          sourceNumber: '1',
          title: 'OSHA LOTO',
          src: '/documents/osha/pdf#page=15&highlight=char_range&char_start=0&char_end=1017',
          href: '/documents/osha/pdf#page=15&highlight=char_range&char_start=0&char_end=1017',
          openMode: 'exact',
          highlightKind: 'char_range',
          renderedHighlightKind: 'char_range',
          highlightCount: 2,
          routeOk: true,
          deadFrontendDocumentUrl: false,
        },
        shellLevel: true,
        insideAssistantCard: false,
        text: 'Side evidence Source 1 OSHA LOTO Text-layer highlight available on page 15.',
      },
      approvalActionLabels: [],
      visibleApprovalIds: [],
      visibleText: 'Notify affected employees before reenergizing. Side evidence Source 1 OSHA LOTO Back to evidence',
    }),
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      pendingApprovalId: null,
      visibleBlockTypes: ['knowledge_answer', 'source_list'],
      backendBlockTypes: ['knowledge_answer', 'source_list'],
      responseContracts: ['knowledge_answer_v1', 'source_list_v1', 'source_locator_v1'],
    },
  })

  assert.equal(probe.diagnosis.classification, 'unknown')
  assert.equal(probe.visible.sourceDrawer.view, 'pdf')
  assert.equal(probe.visible.sourceDrawer.entries[0].role, 'cited')
  assert.equal(probe.visible.sourceDrawer.entries[1].role, 'related')
  assert.equal(probe.visible.citedAnswerHighlights[0].sourceId, 'osha#chunk-29')
  assert.match(probe.visible.citedAnswerHighlights[0].text, /Notify affected employees/)
  assert.equal(probe.visible.sourceDrawer.pdf.sourceId, 'osha#chunk-29')
  assert.match(probe.visible.sourceDrawer.pdf.src, /highlight=char_range/)
  assert.equal(probe.visible.sourceDrawer.pdf.renderedHighlightKind, 'char_range')
  assert.equal(probe.visible.sourceDrawer.pdf.highlightCount, 2)
  assert.equal(probe.visible.sourceDrawer.pdf.routeOk, true)
  assert.notEqual(probe.visible.sourceDrawer.pdf.deadFrontendDocumentUrl, true)
  assert.equal(probe.visible.sourceDrawer.shellLevel, true)
  assert.notEqual(probe.visible.sourceDrawer.insideAssistantCard, true)
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
