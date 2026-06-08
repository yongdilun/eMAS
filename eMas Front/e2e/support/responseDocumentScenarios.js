export const responseDocumentCascadePrompt =
  'change all medium priority job to high then change all high priority job to low'
export const responseDocumentReverseCascadePrompt =
  'change all high priority job to low then change all low priority job to medium'
export const responseDocumentReadStatusPrompt = 'Show status for machine with machine id M-CNC-01'
export const responseDocumentJobStatusPrompt = 'find status for job with job id JOB-SEED-001'
export const responseDocumentMultiStatusPrompt = 'find status for job with job id JOB-SEED-001 and JOB-SEED-002'
export const responseDocumentMachineDetailsPrompt = 'Show full details for machine with machine id M-CNC-01'
export const responseDocumentCollapsedResultsPrompt = 'Show collapsed results for low priority jobs display policy'
export const responseDocumentLotoPrompt = 'Render response_document LOTO procedure answer for M-CNC-01'
export const responseDocumentOshaReenergizingPrompt =
  'According to the OSHA lockout/tagout guide, what notification is required before reenergizing a machine after removing lockout or tagout devices?'
export const responseDocumentOshaUnsupportedNotificationPrompt =
  'According to the OSHA lockout/tagout guide, what notification is required before starting lockout?'
export const responseDocumentLotoNotificationPrompt = responseDocumentOshaUnsupportedNotificationPrompt
export const responseDocumentMixedOperationRagPrompt =
  'Show M-CNC-01 status and OSHA lockout/tagout reenergizing notification guidance as separate sections'
export const responseDocumentSourcePdfPrompt = 'Render response_document source PDF highlight fixture'
export const responseDocumentTextSearchPdfPrompt = 'Render response_document source PDF text-search highlight fixture'
export const responseDocumentExpandedParentPageOnlyPrompt =
  'Render response_document expanded parent PDF page-only fixture'
export const responseDocumentNoResultsPrompt = 'Find response_document jobs that do not exist'
export const responseDocumentPartialFailurePrompt = 'Run response_document partial failure fixture'
export const responseDocumentTimeoutPrompt = 'Run response_document planner timeout fixture'
export const responseDocumentRejectedApprovalPrompt = 'Run response_document rejected approval fixture'
export const responseDocumentExpiredApprovalPrompt = 'Run response_document expired approval fixture'
export const responseDocumentStaleApprovalPrompt = 'Run response_document stale approval fixture'
export const responseDocumentCancelledRunPrompt = 'Start response_document active run that I will cancel'
export const responseDocumentCompatibilityPrompt = 'Render response_document with stale legacy presentation fixture'
export const responseDocumentPartialNoOpPrompt = 'Run response_document partial no-op mutation fixture'
export const responseDocumentZeroMatchApprovalPrompt = 'Run response_document zero-match first approval fixture'
export const responseDocumentAllNoOpPrompt = 'Run response_document all no-op mutation fixture'

export const forbiddenResponseDocumentText = [
  /All requested changes completed/i,
  /Waiting for your approval: stale/i,
  /Approved request to change record/i,
  /Execution completed successfully/i,
  /Response document invalid/i,
  /Traceback/i,
  /super-secret/i,
  /api_key/i,
  /raw-secret-token/i,
]

export const mediumPriorityRows = Object.freeze([
  'JOB-SEED-002',
  'JOB-SEED-004',
  'JOB-SEED-007',
  'JOB-SEED-010',
  'JOB-SEED-014',
  'JOB-SEED-016',
  'JOB-SEED-018',
  'JOB-SEED-020',
  'JOB-SEED-022',
  'JOB-SEED-025',
].map((jobId) => ({ job_id: jobId, previous_priority: 'medium', new_priority: 'high' })))

export const highPriorityRows = Object.freeze([
  'JOB-SEED-001',
  'JOB-SEED-003',
  'JOB-SEED-006',
  'JOB-SEED-008',
  'JOB-SEED-011',
  'JOB-SEED-013',
  'JOB-SEED-015',
  'JOB-SEED-019',
  'JOB-SEED-021',
  'JOB-SEED-023',
  'JOB-SEED-026',
].map((jobId) => ({ job_id: jobId, previous_priority: 'high', new_priority: 'low' })))

export const lowPriorityRows = Object.freeze([
  'JOB-SEED-005',
  'JOB-SEED-009',
  'JOB-SEED-012',
  'JOB-SEED-017',
  'JOB-SEED-024',
].map((jobId) => ({ job_id: jobId, previous_priority: 'low', new_priority: 'medium' })))

const BUSINESS_CHANGE_CONTRACT = 'business_change_v1'
const NO_OP_MUTATION_CONTRACT = 'entity_agnostic_no_matching_records_v1'
const ENTITY_STATUS_CONTRACT = 'entity_status_v1'
const SAFETY_NOTICE_CONTRACT = 'safety_notice_v1'
const KNOWLEDGE_ANSWER_CONTRACT = 'knowledge_answer_v1'
const SOURCE_CITATION_CONTRACT = 'source_citation_v1'
const SOURCE_LOCATOR_CONTRACT = 'source_locator_v1'
const SOURCE_LIST_CONTRACT = 'source_list_v1'
const READ_DISPLAY_PREVIEW_LIMIT = 5

function priorityBusinessChangeId(source, target) {
  return `job-priority-original-${source}-to-${target}`
}

function priorityFieldChanges(source, target) {
  return [{ field: 'priority', label: 'Priority', from: source, to: target }]
}

function typedPriorityRows(rows, { label, source, target }) {
  return rows.map((row) => ({
    business_change: label,
    contract: BUSINESS_CHANGE_CONTRACT,
    business_change_id: priorityBusinessChangeId(source, target),
    entity_type: 'job',
    record_id: row.job_id,
    display_id: row.job_id,
    change_type: 'update',
    selector_summary: `priority = ${source}`,
    source_state_basis: 'original',
    field_changes: priorityFieldChanges(source, target),
    change: `Priority: ${source} -> ${target}`,
    status: 'succeeded',
    outcome: 'succeeded',
  }))
}

function typedPriorityGroup({ label, source, target, rows }) {
  return {
    contract: BUSINESS_CHANGE_CONTRACT,
    business_change: label,
    business_change_id: priorityBusinessChangeId(source, target),
    entity_type: 'job',
    change_type: 'update',
    selector_summary: `priority = ${source}`,
    source_state_basis: 'original',
    field_changes: priorityFieldChanges(source, target),
    summary: `${label}: ${rows.length} jobs`,
    record_count: rows.length,
    rows,
  }
}

function docId(session) {
  const turnId = session.response_document_turn_id || session.current_turn_id || 'pw-response-document-turn'
  return {
    turnId,
    documentId: `rd:${session.session_id}:${turnId}`,
  }
}

export function cascadeDefinition(kind = 'forward') {
  if (kind === 'reverse') {
    return {
      prompt: responseDocumentReverseCascadePrompt,
      operationId: 'pw-plan-rd-reverse-cascade',
      first: {
        approvalId: 'pw-rd-reverse-approval-1',
        source: 'high',
        target: 'low',
        rows: highPriorityRows,
      },
      second: {
        approvalId: 'pw-rd-reverse-approval-2',
        source: 'low',
        target: 'medium',
        rows: lowPriorityRows,
      },
      finalMessage: 'Done. I updated 16 jobs across 2 approved business changes.',
    }
  }
  return {
    prompt: responseDocumentCascadePrompt,
    operationId: 'pw-plan-rd-forward-cascade',
    first: {
      approvalId: 'pw-rd-forward-approval-1',
      source: 'medium',
      target: 'high',
      rows: mediumPriorityRows,
    },
    second: {
      approvalId: 'pw-rd-forward-approval-2',
      source: 'high',
      target: 'low',
      rows: highPriorityRows,
    },
    finalMessage: 'Done. I updated 21 jobs across 2 approved business changes.',
  }
}

export function approvalPayload(session, step) {
  return {
    approval_id: step.approvalId,
    session_id: session.session_id,
    subject_type: 'tool',
    tool_name: 'typed_priority_update',
    side_effect_level: 'HIGH',
    risk_summary: `Update ${step.rows.length} jobs from ${step.source} to ${step.target}.`,
    args: {
      count: step.rows.length,
      bundle_ui: {
        kind: 'response_document_priority_cascade',
        write_set: `original_${step.source}_to_${step.target}`,
        headline: `Update ${step.rows.length} jobs from ${step.source} to ${step.target}`,
        rows: step.rows,
      },
    },
    status: 'PENDING',
  }
}

function baseDocument(session, {
  operationId,
  revision,
  state,
  message,
  currentStepId,
  runSteps,
  blocks,
  invariants = {},
  diagnostics = {},
}) {
  const ids = docId(session)
  const revisionBase = Number(session.response_document_revision_base || 0)
  const documentRevision = revisionBase + Number(revision || 0)
  return {
    version: 1,
    id: ids.documentId,
    document_id: ids.documentId,
    turn_id: ids.turnId,
    operation_id: operationId,
    revision: documentRevision,
    revision_source: 'mock_response_document_quality',
    state,
    status: state,
    summary: message,
    message,
    current_step_id: currentStepId,
    run_steps: runSteps,
    blocks: [
      { id: `activity:${ids.documentId}`, type: 'run_activity', step_ids: runSteps.map((step) => step.step_id) },
      { id: `message:${operationId}:${revision}`, type: 'short_message', message, status: state },
      ...blocks,
    ],
    invariants: {
      response_document_fixture: true,
      ...invariants,
    },
    diagnostics,
  }
}

function approvalBlock(step, approvalNumber) {
  return {
    id: `approval:${step.approvalId}`,
    type: 'approval_required',
    approval_id: step.approvalId,
    operation_id: `op:${step.approvalId}`,
    title: 'Approval required',
    summary: `Update ${step.rows.length} jobs from ${step.source} to ${step.target}`,
    rows: step.rows,
    details_collapsed: true,
  }
}

export function cascadeWaitingDocument(session, definition, approvalNumber = 1) {
  const first = definition.first
  const second = definition.second
  if (approvalNumber === 2) {
    const completedSummary = `Updated ${first.rows.length} jobs from ${first.source} to ${first.target}.`
    const pendingSummary = `Update ${second.rows.length} jobs from ${second.source} to ${second.target}`
    return baseDocument(session, {
      operationId: definition.operationId,
      revision: 4,
      state: 'waiting_approval',
      message: `Done. ${completedSummary} Please review approval 2 before I update original ${second.source}-priority jobs.`,
      currentStepId: 'approval-2',
      runSteps: [
        { step_id: 'analysis-1', kind: 'analysis', state: 'completed', title: 'Understood request', summary: 'Parsed the two-step priority update.' },
        { step_id: 'approval-1', kind: 'approval', state: 'completed', title: 'Approval 1 received', summary: 'The first approval was accepted.' },
        { step_id: 'mutation-1', kind: 'mutation', state: 'completed', title: `Updated ${first.rows.length} jobs: ${first.source} to ${first.target}`, summary: completedSummary },
        { step_id: 'read-2', kind: 'read', state: 'completed', title: `Found ${second.rows.length} original ${second.source}-priority jobs`, summary: `${second.rows.length} jobs are ready for approval 2.` },
        { step_id: 'approval-2', kind: 'approval', state: 'waiting', title: 'Waiting for approval 2', summary: `${second.rows.length} original ${second.source}-priority jobs are ready for review.`, approval_id: second.approvalId, current: true },
      ],
      blocks: [
        {
          id: `completed-step:${first.approvalId}`,
          type: 'completed_step',
          approval_id: first.approvalId,
          operation_id: `op:${first.approvalId}`,
          title: 'Completed step',
          summary: completedSummary,
          rows: first.rows,
          details_collapsed: true,
        },
        approvalBlock(second, 2),
        {
          id: `record-preview:${second.approvalId}:pending`,
          type: 'record_preview',
          approval_id: second.approvalId,
          operation_id: `op:${second.approvalId}`,
          title: 'Affected records',
          rows: second.rows.slice(0, 5),
        },
        {
          id: `table:${second.approvalId}:affected-records`,
          type: 'result_table',
          approval_id: second.approvalId,
          operation_id: `op:${second.approvalId}`,
          title: 'Affected records',
          rows: second.rows,
        },
      ],
      invariants: { full_success_forbidden: true, latest_pending_approval_id: second.approvalId },
      diagnostics: { reason: 'approval_pending' },
    })
  }

  return baseDocument(session, {
    operationId: definition.operationId,
    revision: Number(session.response_document_snapshot_count || 0) + 1,
    state: 'waiting_approval',
    message: `I found ${first.rows.length} jobs that are currently ${first.source} priority. Please review before I update them to ${first.target} priority.`,
    currentStepId: 'approval-1',
    runSteps: [
      { step_id: 'analysis-1', kind: 'analysis', state: 'completed', title: 'Understood request', summary: 'Parsed the two-step priority update.' },
      { step_id: 'read-1', kind: 'read', state: 'completed', title: `Found ${first.rows.length} original ${first.source}-priority jobs`, summary: `${first.rows.length} records matched the first step.` },
      { step_id: 'approval-1', kind: 'approval', state: 'waiting', title: 'Waiting for approval 1', summary: `${first.rows.length} jobs are ready for review.`, approval_id: first.approvalId, current: true },
    ],
    blocks: [
      approvalBlock(first, 1),
      {
        id: `record-preview:${first.approvalId}:pending`,
        type: 'record_preview',
        approval_id: first.approvalId,
        operation_id: `op:${first.approvalId}`,
        title: 'Affected records',
        rows: first.rows.slice(0, 5),
      },
      {
        id: `table:${first.approvalId}:affected-records`,
        type: 'result_table',
        approval_id: first.approvalId,
        operation_id: `op:${first.approvalId}`,
        title: 'Affected records',
        rows: first.rows,
      },
    ],
    invariants: { full_success_forbidden: true, latest_pending_approval_id: first.approvalId },
    diagnostics: { reason: 'approval_pending' },
  })
}

export function cascadeFinalDocument(session, definition) {
  const firstLabel = `${definition.first.source[0].toUpperCase()}${definition.first.source.slice(1)} -> ${definition.first.target[0].toUpperCase()}${definition.first.target.slice(1)}`
  const secondLabel = `Original ${definition.second.source[0].toUpperCase()}${definition.second.source.slice(1)} -> ${definition.second.target[0].toUpperCase()}${definition.second.target.slice(1)}`
  const firstRows = typedPriorityRows(definition.first.rows, {
    label: firstLabel,
    source: definition.first.source,
    target: definition.first.target,
  })
  const secondRows = typedPriorityRows(definition.second.rows, {
    label: secondLabel,
    source: definition.second.source,
    target: definition.second.target,
  })
  const rows = [...firstRows, ...secondRows]
  const firstGroup = typedPriorityGroup({
    label: firstLabel,
    source: definition.first.source,
    target: definition.first.target,
    rows: firstRows,
  })
  const secondGroup = typedPriorityGroup({
    label: secondLabel,
    source: definition.second.source,
    target: definition.second.target,
    rows: secondRows,
  })
  return baseDocument(session, {
    operationId: definition.operationId,
    revision: 8,
    state: 'completed',
    message: definition.finalMessage,
    currentStepId: 'completed-1',
    runSteps: [
      { step_id: 'analysis-1', kind: 'analysis', state: 'completed', title: 'Understood request', summary: 'Parsed the two-step priority update.' },
      { step_id: 'approval-1', kind: 'approval', state: 'completed', title: 'Approval 1 received', approval_id: definition.first.approvalId },
      { step_id: 'mutation-1', kind: 'mutation', state: 'completed', title: `Updated ${definition.first.rows.length} jobs: ${definition.first.source} to ${definition.first.target}` },
      { step_id: 'approval-2', kind: 'approval', state: 'completed', title: 'Approval 2 received', approval_id: definition.second.approvalId },
      { step_id: 'mutation-2', kind: 'mutation', state: 'completed', title: `Updated ${definition.second.rows.length} jobs: ${definition.second.source} to ${definition.second.target}` },
      { step_id: 'completed-1', kind: 'completed', state: 'completed', title: 'Run complete', summary: definition.finalMessage },
    ],
    blocks: [
      {
        id: `result-summary:${definition.operationId}`,
        type: 'result_summary',
        operation_id: definition.operationId,
        title: 'Changes completed',
        summary: definition.finalMessage,
        steps: [
          { step_number: 1, ...firstGroup, rows: undefined, status: 'completed' },
          { step_number: 2, ...secondGroup, rows: undefined, status: 'completed' },
        ],
        total_count: rows.length,
        status: 'completed',
      },
      {
        id: `mutation:${definition.operationId}`,
        type: 'mutation_result',
        contract: BUSINESS_CHANGE_CONTRACT,
        operation_id: definition.operationId,
        title: 'Affected records',
        summary: definition.finalMessage,
        rows,
        groups: [firstGroup, secondGroup],
        preview_limit: 5,
        details_collapsed: true,
        status: 'completed',
      },
    ],
    invariants: {
      latest_pending_approval_id: null,
      completed_approval_ids: [definition.first.approvalId, definition.second.approvalId],
      mutation_group_count: 2,
      mutation_business_contract: BUSINESS_CHANGE_CONTRACT,
      affected_record_count: rows.length,
      approved_business_change_count: 2,
      affected_record_preview_limit: 5,
    },
  })
}

export function partialNoOpDefinition() {
  return {
    prompt: responseDocumentPartialNoOpPrompt,
    operationId: 'pw-plan-rd-partial-noop',
    approvalId: 'pw-rd-partial-noop-approval',
    noOp: {
      contract: NO_OP_MUTATION_CONTRACT,
      entity_type: 'job',
      selector_summary: 'priority = archived',
      change_summary: 'priority -> high',
      matched_count: 0,
      changed_count: 0,
      status: 'not_changed',
      reason: 'no_matching_records',
    },
    rows: highPriorityRows.slice(0, 3),
    finalMessage: 'Done. I updated 3 jobs across 1 approved business change. 1 business change not changed because no matching records were found.',
  }
}

export function partialNoOpApprovalPayload(session, definition = partialNoOpDefinition()) {
  return {
    approval_id: definition.approvalId,
    session_id: session.session_id,
    subject_type: 'tool',
    tool_name: 'typed_priority_update',
    side_effect_level: 'HIGH',
    risk_summary: 'Update 3 jobs from high to low.',
    args: {
      count: definition.rows.length,
      no_op_mutations: [definition.noOp],
      bundle_ui: {
        kind: 'response_document_partial_noop',
        write_set: 'original_high_to_low',
        headline: 'Update 3 jobs from high to low',
        rows: definition.rows,
      },
    },
    status: 'PENDING',
  }
}

export function partialNoOpWaitingDocument(session, definition = partialNoOpDefinition()) {
  const noopSummary = 'Not changed: no matching jobs for priority = archived; priority -> high.'
  return baseDocument(session, {
    operationId: definition.operationId,
    revision: 2,
    state: 'waiting_approval',
    message: `${noopSummary} Update 3 jobs from high to low`,
    currentStepId: 'approval-partial-noop',
    runSteps: [
      { step_id: 'analysis-1', kind: 'analysis', state: 'completed', title: 'Understood request', summary: 'Parsed the no-op plus valid mutation request.' },
      { step_id: 'mutation-noop-1', kind: 'mutation', state: 'completed', title: 'Not changed', summary: noopSummary, record_count: 0 },
      { step_id: 'read-valid-1', kind: 'read', state: 'completed', title: 'Found 3 records', summary: '3 jobs are ready for review.' },
      { step_id: 'approval-partial-noop', kind: 'approval', state: 'waiting', title: 'Waiting for approval 1', summary: '3 jobs are ready for review.', approval_id: definition.approvalId, current: true },
    ],
    blocks: [
      {
        id: 'completed-step:partial-noop',
        type: 'completed_step',
        title: 'Completed step',
        summary: noopSummary,
        rows: [],
        details_collapsed: true,
      },
      {
        id: `approval:${definition.approvalId}`,
        type: 'approval_required',
        approval_id: definition.approvalId,
        operation_id: definition.operationId,
        title: 'Approval required',
        summary: 'Update 3 jobs from high to low',
        rows: definition.rows,
        details_collapsed: true,
      },
    ],
    invariants: {
      latest_pending_approval_id: definition.approvalId,
      no_op_mutation_contract: 'entity_agnostic_no_matching_records_v1',
      not_changed_group_count: 1,
    },
  })
}

export function partialNoOpFinalDocument(session, definition = partialNoOpDefinition()) {
  const changedLabel = 'High -> Low'
  const changedRows = typedPriorityRows(definition.rows, {
    label: changedLabel,
    source: 'high',
    target: 'low',
  })
  const noopGroup = {
    business_change: 'Not changed',
    summary: 'Not changed: no matching jobs for priority = archived; priority -> high.',
    record_count: 0,
    rows: [],
    ...definition.noOp,
  }
  const changedGroup = typedPriorityGroup({ label: changedLabel, source: 'high', target: 'low', rows: changedRows })
  return baseDocument(session, {
    operationId: definition.operationId,
    revision: 5,
    state: 'completed',
    message: definition.finalMessage,
    currentStepId: 'completed-partial-noop',
    runSteps: [
      { step_id: 'analysis-1', kind: 'analysis', state: 'completed', title: 'Understood request' },
      { step_id: 'mutation-noop-1', kind: 'mutation', state: 'completed', title: 'Not changed', summary: noopGroup.summary, record_count: 0 },
      { step_id: 'approval-partial-noop', kind: 'approval', state: 'completed', title: 'Approval 1 received', approval_id: definition.approvalId },
      { step_id: 'mutation-valid-1', kind: 'mutation', state: 'completed', title: 'Updated 3 records', summary: '3 high priority jobs changed to low.' },
      { step_id: 'completed-partial-noop', kind: 'completed', state: 'completed', title: 'Run complete', summary: definition.finalMessage },
    ],
    blocks: [
      {
        id: `result-summary:${definition.operationId}`,
        type: 'result_summary',
        operation_id: definition.operationId,
        title: 'Changes completed',
        summary: definition.finalMessage,
        steps: [
          { step_number: 1, business_change: 'Not changed', summary: noopGroup.summary, record_count: 0, status: 'not_changed', ...definition.noOp },
          { step_number: 2, ...changedGroup, rows: undefined, status: 'completed' },
        ],
        total_count: changedRows.length,
        status: 'completed',
      },
      {
        id: `mutation:${definition.operationId}`,
        type: 'mutation_result',
        contract: BUSINESS_CHANGE_CONTRACT,
        operation_id: definition.operationId,
        title: 'Affected records',
        summary: definition.finalMessage,
        rows: changedRows,
        groups: [noopGroup, changedGroup],
        preview_limit: 5,
        details_collapsed: true,
        status: 'completed',
      },
    ],
    invariants: {
      latest_pending_approval_id: null,
      completed_approval_ids: [definition.approvalId],
      mutation_group_count: 2,
      not_changed_group_count: 1,
      no_op_mutation_count: 1,
      no_op_mutation_contract: 'entity_agnostic_no_matching_records_v1',
      mutation_business_contract: BUSINESS_CHANGE_CONTRACT,
      affected_record_count: changedRows.length,
      approved_business_change_count: 1,
      affected_record_preview_limit: 5,
    },
  })
}

export function zeroMatchApprovalDefinition() {
  return {
    prompt: responseDocumentZeroMatchApprovalPrompt,
    operationId: 'pw-plan-rd-zero-match-approval',
    approvalId: 'pw-rd-zero-match-medium-high',
    noOp: {
      contract: NO_OP_MUTATION_CONTRACT,
      entity_type: 'job',
      selector_summary: 'priority = low',
      change_summary: 'priority -> medium',
      matched_count: 0,
      changed_count: 0,
      status: 'not_changed',
      reason: 'no_matching_records',
    },
    rows: mediumPriorityRows.slice(0, 2),
  }
}

export function zeroMatchApprovalPayload(session, definition = zeroMatchApprovalDefinition()) {
  return {
    approval_id: definition.approvalId,
    session_id: session.session_id,
    subject_type: 'tool',
    tool_name: 'typed_priority_update',
    side_effect_level: 'HIGH',
    risk_summary: 'Update 2 jobs from medium to high.',
    args: {
      count: definition.rows.length,
      no_op_mutations: [definition.noOp],
      bundle_ui: {
        kind: 'response_document_zero_match_first',
        write_set: 'medium_to_high',
        headline: 'Update 2 jobs from medium to high',
        rows: definition.rows,
      },
    },
    status: 'PENDING',
  }
}

export function zeroMatchApprovalWaitingDocument(session, definition = zeroMatchApprovalDefinition()) {
  const noopSummary = 'Not changed: no matching jobs for priority = low; priority -> medium.'
  const approvalSummary = '2 jobs will be updated from medium to high priority.'
  return baseDocument(session, {
    operationId: definition.operationId,
    revision: 2,
    state: 'waiting_approval',
    message: `Done. ${noopSummary} ${approvalSummary}`,
    currentStepId: 'approval-zero-match',
    runSteps: [
      { step_id: 'analysis-1', kind: 'analysis', state: 'completed', title: 'Understood request', summary: 'Parsed the zero-match plus valid mutation request.' },
      { step_id: 'mutation-noop-low', kind: 'mutation', state: 'completed', title: 'Not changed', summary: noopSummary, record_count: 0 },
      { step_id: 'approval-zero-match', kind: 'approval', state: 'waiting', title: 'Waiting for approval 1', summary: approvalSummary, approval_id: definition.approvalId, current: true },
    ],
    blocks: [
      {
        id: 'completed-step:zero-match-low',
        type: 'completed_step',
        title: 'Completed step',
        summary: noopSummary,
        rows: [],
        details_collapsed: true,
      },
      {
        id: `approval:${definition.approvalId}`,
        type: 'approval_required',
        contract: BUSINESS_CHANGE_CONTRACT,
        approval_id: definition.approvalId,
        operation_id: definition.operationId,
        title: 'Approval required',
        summary: approvalSummary,
        rows: definition.rows,
        details_collapsed: true,
      },
    ],
    invariants: {
      latest_pending_approval_id: definition.approvalId,
      no_op_mutation_contract: NO_OP_MUTATION_CONTRACT,
      not_changed_group_count: 1,
      mutation_group_count: 2,
    },
  })
}

export function allNoOpDocument(session) {
  const summary = 'No changes were made.'
  const noopGroup = {
    contract: NO_OP_MUTATION_CONTRACT,
    business_change: 'Not changed',
    summary: 'Not changed: no matching jobs for priority = archived; priority -> high.',
    record_count: 0,
    rows: [],
    entity_type: 'job',
    selector_summary: 'priority = archived',
    change_summary: 'priority -> high',
    matched_count: 0,
    changed_count: 0,
    status: 'not_changed',
    reason: 'no_matching_records',
  }
  return baseDocument(session, {
    operationId: 'pw-plan-rd-all-noop',
    revision: 3,
    state: 'completed',
    message: summary,
    currentStepId: 'completed-all-noop',
    runSteps: [
      { step_id: 'analysis-1', kind: 'analysis', state: 'completed', title: 'Understood request' },
      { step_id: 'mutation-noop-1', kind: 'mutation', state: 'completed', title: 'Not changed', summary: noopGroup.summary, record_count: 0 },
      { step_id: 'completed-all-noop', kind: 'completed', state: 'completed', title: 'Run complete', summary },
    ],
    blocks: [
      {
        id: 'result-summary:all-noop',
        type: 'result_summary',
        operation_id: 'pw-plan-rd-all-noop',
        title: 'No changes made',
        summary,
        steps: [{ step_number: 1, business_change: 'Not changed', summary: noopGroup.summary, record_count: 0, status: 'not_changed', ...noopGroup, rows: undefined }],
        total_count: 0,
        status: 'completed',
      },
      {
        id: 'mutation:all-noop',
        type: 'mutation_result',
        operation_id: 'pw-plan-rd-all-noop',
        title: 'Not changed',
        summary,
        rows: [],
        groups: [noopGroup],
        preview_limit: 5,
        details_collapsed: true,
        status: 'completed',
      },
    ],
    invariants: {
      latest_pending_approval_id: null,
      mutation_group_count: 1,
      not_changed_group_count: 1,
      no_op_mutation_count: 1,
      no_op_mutation_contract: 'entity_agnostic_no_matching_records_v1',
      mutation_business_contract: 'business_level_v1',
      affected_record_count: 0,
      approved_business_change_count: 0,
      affected_record_preview_limit: 5,
    },
  })
}

export function readStatusDocument(session) {
  const summary = 'Machine M-CNC-01 is running.'
  return baseDocument(session, {
    operationId: 'pw-plan-rd-read-status',
    revision: 3,
    state: 'completed',
    message: summary,
    currentStepId: 'completed-read',
    runSteps: [
      { step_id: 'read-machine-status', kind: 'read', state: 'completed', title: 'Read machine status', summary: 'M-CNC-01 status was retrieved.' },
      { step_id: 'completed-read', kind: 'completed', state: 'completed', title: 'Run complete', summary: 'Machine status answer is ready.' },
    ],
    blocks: [
      {
        id: 'status:machine-status',
        type: 'status_result',
        contract: ENTITY_STATUS_CONTRACT,
        operation_id: 'pw-plan-rd-read-status',
        title: 'Machine status',
        summary,
        entity_type: 'machine',
        entity_id: 'M-CNC-01',
        primary_status: 'running',
        fields: [
          { key: 'machine_id', label: 'Machine ID', value: 'M-CNC-01' },
          { key: 'status', label: 'Status', value: 'running', primary: true },
        ],
        secondary_fields: [],
        read_scope: 'status_only',
        requested_fields: ['machine_id', 'status'],
        display_mode: 'compact_status_card',
        entity_count: 1,
        preview_limit: READ_DISPLAY_PREVIEW_LIMIT,
        details_collapsed: true,
      },
    ],
    invariants: {
      read_result_shape: 'status',
      read_scope: 'status_only',
      requested_fields: ['machine_id', 'status'],
      display_mode: 'compact_status_card',
      entity_count: 1,
      preview_limit: READ_DISPLAY_PREVIEW_LIMIT,
      read_details_collapsed: true,
      read_status_contract: 'entity_status_v1',
      read_status_entity_type: 'machine',
    },
  })
}

export function jobStatusDocument(session) {
  const summary = 'Job JOB-SEED-001 is running.'
  return baseDocument(session, {
    operationId: 'pw-plan-rd-job-status',
    revision: 3,
    state: 'completed',
    message: summary,
    currentStepId: 'completed-job-status',
    runSteps: [
      { step_id: 'read-job-status', kind: 'read', state: 'completed', title: 'Read job status', summary: 'JOB-SEED-001 status was retrieved.' },
      { step_id: 'completed-job-status', kind: 'completed', state: 'completed', title: 'Run complete', summary: 'Job status answer is ready.' },
    ],
    blocks: [
      {
        id: 'status:job-status',
        type: 'status_result',
        contract: ENTITY_STATUS_CONTRACT,
        operation_id: 'pw-plan-rd-job-status',
        title: 'Job status',
        summary,
        entity_type: 'job',
        entity_id: 'JOB-SEED-001',
        primary_status: 'running',
        fields: [
          { key: 'job_id', label: 'Job ID', value: 'JOB-SEED-001' },
          { key: 'status', label: 'Status', value: 'running', primary: true },
        ],
        secondary_fields: [],
        read_scope: 'status_only',
        requested_fields: ['job_id', 'status'],
        display_mode: 'compact_status_card',
        entity_count: 1,
        preview_limit: READ_DISPLAY_PREVIEW_LIMIT,
        details_collapsed: true,
      },
    ],
    invariants: {
      read_result_shape: 'status',
      read_scope: 'status_only',
      requested_fields: ['job_id', 'status'],
      display_mode: 'compact_status_card',
      entity_count: 1,
      preview_limit: READ_DISPLAY_PREVIEW_LIMIT,
      read_details_collapsed: true,
      read_status_contract: ENTITY_STATUS_CONTRACT,
      read_status_entity_type: 'job',
    },
  })
}

export function machineDetailsDocument(session) {
  const summary = 'Machine M-CNC-01 is running.'
  return baseDocument(session, {
    operationId: 'pw-plan-rd-machine-details',
    revision: 3,
    state: 'completed',
    message: summary,
    currentStepId: 'completed-machine-details',
    runSteps: [
      { step_id: 'read-machine-details', kind: 'read', state: 'completed', title: 'Read machine details', summary: 'M-CNC-01 details were retrieved.' },
      { step_id: 'completed-machine-details', kind: 'completed', state: 'completed', title: 'Run complete', summary: 'Machine details answer is ready.' },
    ],
    blocks: [
      {
        id: 'status:machine-details',
        type: 'status_result',
        contract: ENTITY_STATUS_CONTRACT,
        operation_id: 'pw-plan-rd-machine-details',
        title: 'Machine status',
        summary,
        entity_type: 'machine',
        entity_id: 'M-CNC-01',
        primary_status: 'running',
        fields: [
          { key: 'machine_id', label: 'Machine ID', value: 'M-CNC-01' },
          { key: 'status', label: 'Status', value: 'running', primary: true },
        ],
        secondary_fields: [
          { key: 'machine_name', label: 'Machine name', value: 'CNC Mill 01' },
          { key: 'machine_type', label: 'Machine type', value: 'CNC mill' },
          { key: 'location', label: 'Location', value: 'Line 1' },
          { key: 'capacity_per_hour', label: 'Capacity per hour', value: '40' },
          { key: 'last_maintenance_date', label: 'Last maintenance date', value: '2026-05-01' },
          { key: 'maintenance_interval_days', label: 'Maintenance interval days', value: '30' },
        ],
        read_scope: 'details',
        requested_fields: ['machine_id', 'status', 'details'],
        display_mode: 'detail_status_card',
        entity_count: 1,
        preview_limit: READ_DISPLAY_PREVIEW_LIMIT,
        details_collapsed: true,
      },
    ],
    invariants: {
      read_result_shape: 'status',
      read_scope: 'details',
      requested_fields: ['machine_id', 'status', 'details'],
      display_mode: 'detail_status_card',
      entity_count: 1,
      preview_limit: READ_DISPLAY_PREVIEW_LIMIT,
      read_details_collapsed: true,
      read_status_contract: ENTITY_STATUS_CONTRACT,
      read_status_entity_type: 'machine',
    },
  })
}

export function multiStatusDocument(session) {
  const rows = [
    { job_id: 'JOB-SEED-001', status: 'running' },
    { job_id: 'JOB-SEED-002', status: 'planned' },
  ]
  return baseDocument(session, {
    operationId: 'pw-plan-rd-multi-status',
    revision: 3,
    state: 'completed',
    message: 'Found 2 job statuses.',
    currentStepId: 'completed-multi-status',
    runSteps: [
      { step_id: 'read-job-status-1', kind: 'read', state: 'completed', title: 'Read job status', summary: 'JOB-SEED-001 status was retrieved.' },
      { step_id: 'read-job-status-2', kind: 'read', state: 'completed', title: 'Read job status', summary: 'JOB-SEED-002 status was retrieved.' },
      { step_id: 'completed-multi-status', kind: 'completed', state: 'completed', title: 'Run complete', summary: 'Job status collection is ready.' },
    ],
    blocks: [
      {
        id: 'table:multi-job-status',
        type: 'result_table',
        contract: ENTITY_STATUS_CONTRACT,
        operation_id: 'pw-plan-rd-multi-status',
        title: 'Results',
        rows,
        read_scope: 'status_only',
        requested_fields: ['job_id', 'status'],
        display_mode: 'collection_table',
        entity_type: 'job',
        entity_count: rows.length,
        preview_limit: READ_DISPLAY_PREVIEW_LIMIT,
        details_collapsed: false,
      },
    ],
    invariants: {
      read_result_shape: 'list',
      read_scope: 'status_only',
      requested_fields: ['job_id', 'status'],
      display_mode: 'collection_table',
      entity_count: rows.length,
      preview_limit: READ_DISPLAY_PREVIEW_LIMIT,
      read_details_collapsed: false,
      read_status_contract: ENTITY_STATUS_CONTRACT,
      read_status_entity_type: 'job',
    },
  })
}

export function collapsedResultsDocument(session) {
  const rows = [
    ...lowPriorityRows.map((row) => ({ job_id: row.job_id, priority: 'low', status: 'planned' })),
    { job_id: 'JOB-SEED-027', priority: 'low', status: 'queued' },
  ]
  return baseDocument(session, {
    operationId: 'pw-plan-rd-collapsed-results',
    revision: 3,
    state: 'completed',
    message: 'Found 6 low-priority jobs.',
    currentStepId: 'completed-collapsed-results',
    runSteps: [
      { step_id: 'read-low-priority-jobs', kind: 'read', state: 'completed', title: 'Read filtered jobs', summary: '6 low-priority jobs matched.' },
      { step_id: 'completed-collapsed-results', kind: 'completed', state: 'completed', title: 'Run complete', summary: 'Collapsed results are ready.' },
    ],
    blocks: [
      {
        id: 'table:collapsed-results',
        type: 'result_table',
        title: 'Results',
        rows,
        read_scope: 'records',
        requested_fields: [],
        display_mode: 'collapsed_collection_table',
        entity_type: 'job',
        entity_count: rows.length,
        preview_limit: READ_DISPLAY_PREVIEW_LIMIT,
        details_collapsed: true,
      },
    ],
    invariants: {
      read_result_shape: 'table',
      read_scope: 'records',
      requested_fields: [],
      display_mode: 'collapsed_collection_table',
      entity_count: rows.length,
      preview_limit: READ_DISPLAY_PREVIEW_LIMIT,
      read_details_collapsed: true,
    },
  })
}

export function lotoDocument(session) {
  const answer = 'Use the M-CNC-01 lockout/tagout procedure before opening the CNC enclosure: notify operations, stop the machine, isolate electrical and pneumatic energy, apply locks, and verify zero energy before work begins.'
  const citation = {
    contract: 'source_citation_v1',
    citation_id: 'citation:LOTO-M-CNC-01#chunk-loto-m-cnc-01',
    source_id: 'LOTO-M-CNC-01#chunk-loto-m-cnc-01',
    source_number: 1,
    title: 'M-CNC-01 Lockout/Tagout Procedure',
    doc_id: 'LOTO-M-CNC-01',
    chunk_id: 'chunk-loto-m-cnc-01',
    machine_id: 'M-CNC-01',
    organization: 'Factory Safety',
    snippet: 'Notify operations, isolate electrical and pneumatic energy, apply locks, and verify zero energy before work begins.',
  }
  return baseDocument(session, {
    operationId: 'pw-plan-rd-loto',
    revision: 3,
    state: 'completed',
    message: 'I found a source-backed answer.',
    currentStepId: 'completed-loto',
    runSteps: [
      { step_id: 'knowledge-loto', kind: 'knowledge', state: 'completed', title: 'Prepared sourced answer', summary: '1 source attached.' },
      { step_id: 'completed-loto', kind: 'completed', state: 'completed', title: 'Run complete', summary: 'LOTO answer is ready.' },
    ],
    blocks: [
      {
        id: 'safety:loto',
        type: 'safety_notice',
        contract: 'safety_notice_v1',
        operation_id: 'pw-plan-rd-loto',
        safety_content: 'LOTO is safety critical. Follow the site-approved SOP and verify zero energy before work begins.',
      },
      {
        id: 'knowledge:loto',
        type: 'knowledge_answer',
        contract: 'knowledge_answer_v1',
        operation_id: 'pw-plan-rd-loto',
        answer,
        segments: [{ text: answer, citation_ids: [citation.citation_id] }],
        citations: [citation],
      },
      {
        id: 'sources:loto',
        type: 'source_list',
        contract: 'source_list_v1',
        operation_id: 'pw-plan-rd-loto',
        sources: [
          {
            contract: 'source_locator_v1',
            source_id: 'LOTO-M-CNC-01#chunk-loto-m-cnc-01',
            source_number: 1,
            title: 'M-CNC-01 Lockout/Tagout Procedure',
            doc_id: 'LOTO-M-CNC-01',
            chunk_id: 'chunk-loto-m-cnc-01',
            machine_id: 'M-CNC-01',
            organization: 'Factory Safety',
            snippet: 'Notify operations, isolate electrical and pneumatic energy, apply locks, and verify zero energy before work begins.',
          },
        ],
      },
    ],
  })
}

function oshaReenergizingCitation() {
  return {
    contract: SOURCE_CITATION_CONTRACT,
    citation_id: 'citation:osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0029',
    source_id: 'osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0029',
    source_number: 1,
    title: 'Control of Hazardous Energy Lockout/Tagout',
    doc_id: 'osha_3120_lockout_tagout',
    chunk_id: 'osha_3120_lockout_tagout_c0029',
    organization: 'OSHA',
    snippet: 'After removing lockout or tagout devices but before reenergizing the machine, the employer must assure that employees know the devices have been removed and that the machine is capable of being reenergized.',
    pdf_url: '/documents/osha_3120_lockout_tagout/pdf',
    page: 15,
    char_range: [0, 1017],
    text_search: 'After removing the lockout or tagout devices but before reenergizing the machine',
  }
}

function oshaReenergizingRelatedSource() {
  return {
    contract: SOURCE_LOCATOR_CONTRACT,
    source_id: 'osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0030',
    source_number: 2,
    title: 'Control of Hazardous Energy Lockout/Tagout',
    doc_id: 'osha_3120_lockout_tagout',
    chunk_id: 'osha_3120_lockout_tagout_c0030',
    organization: 'OSHA',
    snippet: 'Before removing lockout or tagout devices and restoring energy, OSHA describes checks for personnel, tools, and machine components.',
    pdf_url: '/documents/osha_3120_lockout_tagout/pdf',
    page: 15,
    text_search: 'Before lockout or tagout devices are removed and energy is restored',
  }
}

export function oshaReenergizingDocument(session) {
  const answer = 'Before reenergizing, notify affected employees who operate or work with the machine and employees in the service area that the lockout or tagout devices have been removed and that the machine can be reenergized.'
  const citation = oshaReenergizingCitation()
  const relatedSource = oshaReenergizingRelatedSource()
  return baseDocument(session, {
    operationId: 'pw-plan-rd-osha-reenergizing',
    revision: 3,
    state: 'completed',
    message: 'I found a source-backed answer.',
    currentStepId: 'completed-osha-reenergizing',
    runSteps: [
      { step_id: 'knowledge-osha-reenergizing', kind: 'knowledge', state: 'completed', title: 'Prepared sourced answer', summary: '1 PDF source attached.' },
      { step_id: 'completed-osha-reenergizing', kind: 'completed', state: 'completed', title: 'Run complete', summary: 'OSHA reenergizing notification answer is ready.' },
    ],
    blocks: [
      {
        id: 'safety:osha-reenergizing',
        type: 'safety_notice',
        contract: SAFETY_NOTICE_CONTRACT,
        operation_id: 'pw-plan-rd-osha-reenergizing',
        safety_content: 'This topic involves high-risk industrial procedures. Follow the site-approved SOP before acting.',
      },
      {
        id: 'knowledge:osha-reenergizing',
        type: 'knowledge_answer',
        contract: KNOWLEDGE_ANSWER_CONTRACT,
        operation_id: 'pw-plan-rd-osha-reenergizing',
        answer,
        segments: [{ text: answer, citation_ids: [citation.citation_id] }],
        citations: [citation],
      },
      {
        id: 'sources:osha-reenergizing',
        type: 'source_list',
        contract: SOURCE_LIST_CONTRACT,
        operation_id: 'pw-plan-rd-osha-reenergizing',
        sources: [
          {
            contract: SOURCE_LOCATOR_CONTRACT,
            source_id: citation.source_id,
            source_number: citation.source_number,
            title: citation.title,
            doc_id: citation.doc_id,
            chunk_id: citation.chunk_id,
            organization: citation.organization,
            snippet: citation.snippet,
            pdf_url: citation.pdf_url,
            page: citation.page,
            char_range: citation.char_range,
            text_search: citation.text_search,
          },
          relatedSource,
        ],
      },
    ],
    invariants: {
      safety_notice_contract: SAFETY_NOTICE_CONTRACT,
      knowledge_answer_contract: KNOWLEDGE_ANSWER_CONTRACT,
      source_list_contract: SOURCE_LIST_CONTRACT,
      source_locator_contract: SOURCE_LOCATOR_CONTRACT,
      pdf_source_locator: true,
      phase32_positive_rag_proof: true,
    },
  })
}

export function lotoNotificationDocument(session) {
  const answer = 'I do not have enough retrieved evidence to answer that safely. The related sources checked are listed below, but they do not prove the requested claim.'
  const message = 'I do not have enough retrieved evidence to answer that safely.'
  const citation = {
    contract: SOURCE_LOCATOR_CONTRACT,
    source_id: 'osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0028',
    source_number: 1,
    title: 'Control of Hazardous Energy Lockout/Tagout',
    doc_id: 'osha_3120_lockout_tagout',
    chunk_id: 'osha_3120_lockout_tagout_c0028',
    organization: 'OSHA',
    snippet: 'Before beginning service or maintenance, OSHA lists preparation, shutdown, isolation, applying lockout or tagout devices, controlling stored energy, and verifying deenergization.',
    pdf_url: '/documents/osha_3120_lockout_tagout/pdf',
    page: 14,
    text_search: 'Before beginning service or maintenance, the following steps must be accomplished in sequence',
  }
  return baseDocument(session, {
    operationId: 'pw-plan-rd-loto-notification',
    revision: 3,
    state: 'completed',
    message,
    currentStepId: 'completed-loto-notification',
    runSteps: [
      { step_id: 'knowledge-loto-notification', kind: 'knowledge', state: 'completed', title: 'Checked related sources', summary: '1 related source checked.' },
      { step_id: 'completed-loto-notification', kind: 'completed', state: 'completed', title: 'Run complete', summary: 'Insufficient context response is ready.' },
    ],
    blocks: [
      {
        id: 'safety:loto-notification',
        type: 'safety_notice',
        contract: SAFETY_NOTICE_CONTRACT,
        operation_id: 'pw-plan-rd-loto-notification',
        safety_content: 'LOTO is safety-critical. Follow the site-approved SOP before acting.',
      },
      {
        id: 'knowledge:loto-notification',
        type: 'knowledge_answer',
        contract: KNOWLEDGE_ANSWER_CONTRACT,
        operation_id: 'pw-plan-rd-loto-notification',
        answer,
        segments: [{ text: answer, citation_ids: [] }],
        citations: [],
      },
      {
        id: 'sources:loto-notification',
        type: 'source_list',
        contract: SOURCE_LIST_CONTRACT,
        operation_id: 'pw-plan-rd-loto-notification',
        sources: [
          {
            contract: SOURCE_LOCATOR_CONTRACT,
            source_id: citation.source_id,
            source_number: 1,
            title: citation.title,
            doc_id: citation.doc_id,
            chunk_id: citation.chunk_id,
            organization: citation.organization,
            snippet: citation.snippet,
            pdf_url: citation.pdf_url,
            page: citation.page,
            text_search: citation.text_search,
          },
        ],
      },
    ],
    invariants: {
      rag_question_type: 'document_content_question',
      missing_required_entities: [],
      phase32_negative_rag_proof: true,
    },
  })
}

export function mixedOperationRagDocument(session) {
  const guidance = 'Before reenergizing after lockout or tagout devices are removed, affected employees who operate or work with the machine and employees in the service area must know the devices were removed and the machine can be reenergized.'
  const citation = oshaReenergizingCitation()
  return baseDocument(session, {
    operationId: 'pw-plan-rd-mixed-operation-rag',
    revision: 3,
    state: 'completed',
    message: 'Machine status and sourced LOTO guidance are ready.',
    currentStepId: 'completed-mixed-operation-rag',
    runSteps: [
      { step_id: 'read-mixed-status', kind: 'read', state: 'completed', title: 'Read machine status', summary: 'M-CNC-01 status is running.' },
      { step_id: 'knowledge-mixed-loto', kind: 'knowledge', state: 'completed', title: 'Prepared sourced guidance', summary: '1 PDF source attached.' },
      { step_id: 'completed-mixed-operation-rag', kind: 'completed', state: 'completed', title: 'Run complete', summary: 'Status and LOTO guidance are ready.' },
    ],
    blocks: [
      {
        id: 'status:mixed-operation',
        type: 'status_result',
        contract: ENTITY_STATUS_CONTRACT,
        operation_id: 'pw-plan-rd-mixed-operation-rag',
        title: 'Machine status',
        summary: 'M-CNC-01 is running.',
        entity_type: 'machine',
        entity_id: 'M-CNC-01',
        primary_status: 'running',
        fields: [
          { key: 'machine_id', label: 'Machine ID', value: 'M-CNC-01' },
          { key: 'status', label: 'Status', value: 'running', primary: true },
        ],
        secondary_fields: [],
        read_scope: 'status_only',
        requested_fields: ['machine_id', 'status'],
        display_mode: 'compact_status_card',
        entity_count: 1,
        preview_limit: READ_DISPLAY_PREVIEW_LIMIT,
        details_collapsed: true,
      },
      {
        id: 'safety:mixed-loto',
        type: 'safety_notice',
        contract: SAFETY_NOTICE_CONTRACT,
        operation_id: 'pw-plan-rd-mixed-operation-rag',
        safety_content: 'LOTO guidance is safety critical. Follow the site-approved SOP before acting.',
      },
      {
        id: 'knowledge:mixed-loto',
        type: 'knowledge_answer',
        contract: KNOWLEDGE_ANSWER_CONTRACT,
        operation_id: 'pw-plan-rd-mixed-operation-rag',
        title: 'Procedure guidance',
        answer: guidance,
        segments: [{ text: guidance, citation_ids: [citation.citation_id] }],
        citations: [citation],
      },
      {
        id: 'sources:mixed-loto',
        type: 'source_list',
        contract: SOURCE_LIST_CONTRACT,
        operation_id: 'pw-plan-rd-mixed-operation-rag',
        sources: [
          {
            contract: SOURCE_LOCATOR_CONTRACT,
            source_id: citation.source_id,
            source_number: citation.source_number,
            title: citation.title,
            doc_id: citation.doc_id,
            chunk_id: citation.chunk_id,
            organization: citation.organization,
            snippet: citation.snippet,
            pdf_url: citation.pdf_url,
            page: citation.page,
            char_range: citation.char_range,
            text_search: citation.text_search,
          },
        ],
      },
    ],
    invariants: {
      read_scope: 'status_only',
      requested_fields: ['machine_id', 'status'],
      display_mode: 'compact_status_card',
      entity_count: 1,
      preview_limit: READ_DISPLAY_PREVIEW_LIMIT,
      read_details_collapsed: true,
      read_status_contract: ENTITY_STATUS_CONTRACT,
      read_status_entity_type: 'machine',
      mixed_operation_rag_sections: true,
    },
  })
}

export function sourcePdfLocatorDocument(session) {
  const answer = 'The PDF-backed LOTO source opens on the cited page with text-layer highlight metadata.'
  const citation = {
    contract: SOURCE_CITATION_CONTRACT,
    citation_id: 'citation:osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0007',
    source_id: 'osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0007',
    source_number: 1,
    title: 'Control of Hazardous Energy Lockout/Tagout',
    doc_id: 'osha_3120_lockout_tagout',
    chunk_id: 'osha_3120_lockout_tagout_c0007',
    organization: 'OSHA',
    snippet: 'Affected employees must be notified by the employer before lockout or tagout devices are applied.',
    pdf_url: '/documents/osha_3120_lockout_tagout/pdf',
    page: 9,
    char_range: [488, 606],
    text_search: 'Affected employees must be notified by the employer before lockout or tagout devices are applied.',
  }
  return baseDocument(session, {
    operationId: 'pw-plan-rd-source-pdf',
    revision: 3,
    state: 'completed',
    message: 'I found PDF-backed source locator evidence.',
    currentStepId: 'completed-source-pdf',
    runSteps: [
      { step_id: 'knowledge-source-pdf', kind: 'knowledge', state: 'completed', title: 'Prepared sourced answer', summary: '1 PDF source attached.' },
      { step_id: 'completed-source-pdf', kind: 'completed', state: 'completed', title: 'Run complete', summary: 'PDF source locator is ready.' },
    ],
    blocks: [
      {
        id: 'knowledge:source-pdf',
        type: 'knowledge_answer',
        contract: KNOWLEDGE_ANSWER_CONTRACT,
        operation_id: 'pw-plan-rd-source-pdf',
        answer,
        segments: [{ text: answer, citation_ids: [citation.citation_id] }],
        citations: [citation],
      },
      {
        id: 'sources:source-pdf',
        type: 'source_list',
        contract: SOURCE_LIST_CONTRACT,
        operation_id: 'pw-plan-rd-source-pdf',
        sources: [
          {
            contract: SOURCE_LOCATOR_CONTRACT,
            source_id: citation.source_id,
            source_number: citation.source_number,
            title: citation.title,
            doc_id: citation.doc_id,
            chunk_id: citation.chunk_id,
            organization: citation.organization,
            snippet: citation.snippet,
            pdf_url: citation.pdf_url,
            page: citation.page,
            char_range: citation.char_range,
            text_search: citation.text_search,
          },
        ],
      },
    ],
    invariants: {
      source_locator_contract: SOURCE_LOCATOR_CONTRACT,
      pdf_source_locator: true,
    },
  })
}

export function textSearchPdfLocatorDocument(session) {
  const answer = 'The cited LOTO source opens with a claim-specific text-search highlight.'
  const textSearch = 'After removing the lockout'
  const citation = {
    contract: SOURCE_CITATION_CONTRACT,
    citation_id: 'citation:osha_3120_lockout_tagout#text-search-claim',
    source_id: 'osha_3120_lockout_tagout#text-search-claim',
    source_number: 1,
    title: 'Control of Hazardous Energy Lockout/Tagout',
    doc_id: 'osha_3120_lockout_tagout',
    chunk_id: 'osha_3120_lockout_tagout_c0029',
    organization: 'OSHA',
    snippet: textSearch,
    pdf_url: '/documents/osha_3120_lockout_tagout/pdf',
    page: 15,
    text_search: textSearch,
    evidence: [
      {
        contract: 'source_evidence_v1',
        evidence_id: 'citation:osha_3120_lockout_tagout#text-search-claim:evidence-1',
        source_id: 'osha_3120_lockout_tagout#text-search-claim:evidence-1',
        source_number: 1,
        title: 'Control of Hazardous Energy Lockout/Tagout',
        doc_id: 'osha_3120_lockout_tagout',
        chunk_id: 'osha_3120_lockout_tagout_c0029',
        organization: 'OSHA',
        snippet: textSearch,
        pdf_url: '/documents/osha_3120_lockout_tagout/pdf',
        page: 15,
        text_search: textSearch,
        locator_confidence: 'exact',
      },
    ],
  }
  return baseDocument(session, {
    operationId: 'pw-plan-rd-text-search-pdf',
    revision: 3,
    state: 'completed',
    message: 'I found PDF-backed text-search locator evidence.',
    currentStepId: 'completed-text-search-pdf',
    runSteps: [
      { step_id: 'knowledge-text-search-pdf', kind: 'knowledge', state: 'completed', title: 'Prepared sourced answer', summary: '1 text-search PDF source attached.' },
      { step_id: 'completed-text-search-pdf', kind: 'completed', state: 'completed', title: 'Run complete', summary: 'PDF text-search locator is ready.' },
    ],
    blocks: [
      {
        id: 'knowledge:text-search-pdf',
        type: 'knowledge_answer',
        contract: KNOWLEDGE_ANSWER_CONTRACT,
        operation_id: 'pw-plan-rd-text-search-pdf',
        answer,
        segments: [{ text: answer, citation_ids: [citation.citation_id] }],
        citations: [citation],
      },
      {
        id: 'sources:text-search-pdf',
        type: 'source_list',
        contract: SOURCE_LIST_CONTRACT,
        operation_id: 'pw-plan-rd-text-search-pdf',
        sources: [
          {
            contract: SOURCE_LOCATOR_CONTRACT,
            source_id: citation.source_id,
            source_number: citation.source_number,
            title: citation.title,
            doc_id: citation.doc_id,
            chunk_id: citation.chunk_id,
            organization: citation.organization,
            snippet: citation.snippet,
            pdf_url: citation.pdf_url,
            page: citation.page,
            text_search: citation.text_search,
          },
        ],
      },
    ],
    invariants: {
      source_locator_contract: SOURCE_LOCATOR_CONTRACT,
      pdf_source_locator: true,
      pdf_text_search_locator: true,
    },
  })
}

export function expandedParentPageOnlyDocument(session) {
  const answer = 'The cited CSF source opens on the source page without creating hidden parent highlights.'
  const hiddenParentText =
    'The GOVERN Function provides outcomes to inform what an organization may do to achieve and prioritize the outcomes of the other five Functions.'
  const citation = {
    contract: SOURCE_CITATION_CONTRACT,
    citation_id: 'citation:nist_csf_2_0#brse-parent',
    source_id: 'nist_csf_2_0#brse-parent',
    source_number: 1,
    title: 'The NIST Cybersecurity Framework (CSF) 2.0',
    doc_id: 'nist_csf_2_0',
    chunk_id: 'brse:nist_csf_2_0:01:nist_csf_2_0_c0013',
    organization: 'NIST',
    snippet: hiddenParentText,
    pdf_url: '/documents/nist_csf_2_0/pdf',
    page: 8,
    text_search: hiddenParentText,
  }
  return baseDocument(session, {
    operationId: 'pw-plan-rd-expanded-parent-page-only',
    revision: 3,
    state: 'completed',
    message: 'I found a source-backed answer with a parent source reference.',
    currentStepId: 'completed-expanded-parent-page-only',
    runSteps: [
      { step_id: 'knowledge-expanded-parent-page-only', kind: 'knowledge', state: 'completed', title: 'Prepared sourced answer', summary: '1 parent PDF source attached.' },
      { step_id: 'completed-expanded-parent-page-only', kind: 'completed', state: 'completed', title: 'Run complete', summary: 'Parent source locator is page-only.' },
    ],
    blocks: [
      {
        id: 'knowledge:expanded-parent-page-only',
        type: 'knowledge_answer',
        contract: KNOWLEDGE_ANSWER_CONTRACT,
        operation_id: 'pw-plan-rd-expanded-parent-page-only',
        answer,
        segments: [{ text: answer, citation_ids: [citation.citation_id] }],
        citations: [citation],
      },
      {
        id: 'sources:expanded-parent-page-only',
        type: 'source_list',
        contract: SOURCE_LIST_CONTRACT,
        operation_id: 'pw-plan-rd-expanded-parent-page-only',
        sources: [
          {
            contract: SOURCE_LOCATOR_CONTRACT,
            source_id: citation.source_id,
            source_number: citation.source_number,
            title: citation.title,
            doc_id: citation.doc_id,
            chunk_id: citation.chunk_id,
            organization: citation.organization,
            snippet: citation.snippet,
            pdf_url: citation.pdf_url,
            page: citation.page,
            text_search: citation.text_search,
          },
        ],
      },
    ],
    invariants: {
      source_locator_contract: SOURCE_LOCATOR_CONTRACT,
      expanded_parent_page_only: true,
    },
  })
}

export function noResultsDocument(session) {
  return baseDocument(session, {
    operationId: 'pw-plan-rd-no-results',
    revision: 3,
    state: 'completed',
    message: 'No matching jobs were found. No changes were applied.',
    currentStepId: 'diagnostic:no-results',
    runSteps: [
      { step_id: 'read-empty', kind: 'read', state: 'completed', title: 'Read matching jobs', summary: 'No matching rows returned.' },
      { step_id: 'diagnostic:no-results', kind: 'diagnostic', state: 'failed', title: 'No results', summary: 'No successful result is being claimed.', current: true },
    ],
    blocks: [
      {
        id: 'diagnostic:no-results',
        type: 'diagnostic',
        severity: 'info',
        reason: 'no_results',
        title: 'No results',
        user_message: 'No matching jobs were found. No changes were applied.',
        cause: 'The read returned an empty result set.',
        impact: { changes_applied: false, matched_rows: 0 },
        current_state: 'No successful result is being claimed.',
        next_action: 'Start a new request with a different filter.',
        technical_details: { reason: 'no_results', sanitized: true },
        details_collapsed: true,
      },
    ],
    diagnostics: { reason: 'no_results', sanitized: true },
  })
}

export function partialFailureDocument(session) {
  const rows = [
    { job_id: 'JOB-SEED-005', previous_priority: 'low', new_priority: 'high', status: 'succeeded' },
    { job_id: 'JOB-SEED-009', previous_priority: 'low', new_priority: 'high', status: 'failed', reason: 'version_conflict' },
  ]
  return baseDocument(session, {
    operationId: 'pw-plan-rd-partial-failure',
    revision: 5,
    state: 'failed',
    message: 'Some rows were updated, but other rows failed.',
    currentStepId: 'diagnostic:partial',
    runSteps: [
      { step_id: 'approval-partial', kind: 'approval', state: 'completed', title: 'Approval received' },
      { step_id: 'mutation-partial', kind: 'mutation', state: 'failed', title: 'Updated 1 of 2 jobs', summary: 'One row succeeded and one row failed.' },
      { step_id: 'diagnostic:partial', kind: 'diagnostic', state: 'failed', title: 'Partial failure', current: true },
    ],
    blocks: [
      {
        id: 'result-summary:partial',
        type: 'result_summary',
        summary: 'Updated 1 of 2 jobs; 1 row failed.',
        steps: [{ step_number: 1, summary: 'JOB-SEED-005 succeeded; JOB-SEED-009 failed.', record_count: 2, status: 'partial_failure' }],
        total_count: 2,
        status: 'partial_failure',
      },
      { id: 'mutation:partial', type: 'mutation_result', summary: 'Updated 1 of 2 jobs; 1 row failed.', rows, status: 'partial_failure' },
      {
        id: 'diagnostic:partial',
        type: 'diagnostic',
        severity: 'error',
        reason: 'partial_commit_failure',
        title: 'Partial failure',
        user_message: 'Some rows were updated, but other rows failed.',
        cause: 'A row-level conflict stopped part of the write set.',
        impact: { succeeded_rows: ['JOB-SEED-005'], failed_rows: ['JOB-SEED-009'], changes_applied: true },
        current_state: 'Successful rows remain applied; failed rows need attention.',
        next_action: 'Retry failed rows only after checking current status.',
        technical_details: { error_code: 'version_conflict', sanitized: true },
        details_collapsed: true,
      },
    ],
    diagnostics: { reason: 'partial_commit_failure', sanitized: true },
  })
}

export function timeoutDocument(session) {
  return baseDocument(session, {
    operationId: 'pw-plan-rd-timeout',
    revision: 3,
    state: 'failed',
    message: 'I could not finish this request because the planner timed out while preparing the next step.',
    currentStepId: 'diagnostic:planner-timeout',
    runSteps: [
      { step_id: 'analysis-timeout', kind: 'analysis', state: 'completed', title: 'Understood request' },
      { step_id: 'diagnostic:planner-timeout', kind: 'diagnostic', state: 'failed', title: 'Run interrupted', current: true },
    ],
    blocks: [
      {
        id: 'diagnostic:planner-timeout',
        type: 'diagnostic',
        severity: 'error',
        reason: 'planner_timeout',
        title: 'Run interrupted',
        user_message: 'I could not finish this request because the planner timed out while preparing the next step.',
        cause: 'The planner timed out before it produced a safe next step.',
        impact: { changes_applied: false, incomplete_steps: ['diagnostic:planner-timeout'], safe_to_retry: true },
        current_state: 'The run stopped before any unconfirmed next action could continue.',
        next_action: 'Retry from the last safe point, or start a new request if the context changed.',
        next_actions: [{ id: 'retry_from_checkpoint', label: 'Retry from last safe point' }],
        retry_safety: { safe_to_retry: true, policy: 'safe_from_checkpoint' },
        technical_details: { error_code: 'planner_timeout', sanitized: true },
        details_collapsed: true,
      },
    ],
    diagnostics: { reason: 'planner_timeout', sanitized: true },
  })
}

export function rejectedDocument(session, definition = cascadeDefinition('forward')) {
  return baseDocument(session, {
    operationId: 'pw-plan-rd-rejected',
    revision: 6,
    state: 'rejected',
    message: 'The approval was rejected, so I did not apply that pending change.',
    currentStepId: 'diagnostic:approval-rejected',
    runSteps: [
      { step_id: 'approval-1', kind: 'approval', state: 'completed', title: 'Approval 1 received' },
      { step_id: 'mutation-1', kind: 'mutation', state: 'completed', title: 'Updated 10 jobs: medium to high' },
      { step_id: 'approval-2', kind: 'approval', state: 'rejected', title: 'Approval 2 rejected' },
      { step_id: 'diagnostic:approval-rejected', kind: 'diagnostic', state: 'rejected', title: 'Approval rejected', current: true },
    ],
    blocks: [
      {
        id: `completed-step:${definition.first.approvalId}`,
        type: 'completed_step',
        approval_id: definition.first.approvalId,
        title: 'Completed step',
        summary: `Updated ${definition.first.rows.length} jobs from ${definition.first.source} to ${definition.first.target}.`,
        rows: definition.first.rows,
        details_collapsed: true,
      },
      {
        id: 'diagnostic:approval-rejected',
        type: 'diagnostic',
        severity: 'error',
        reason: 'approval_rejected',
        title: 'Approval rejected',
        user_message: 'The approval was rejected, so I did not apply that pending change.',
        cause: 'The operator rejected approval 2.',
        impact: { changes_applied: true, completed_steps: ['mutation-1'], incomplete_steps: ['approval-2'] },
        current_state: 'The rejected approval is closed and cannot be applied.',
        next_action: 'Start a new request if you want a different change.',
        technical_details: { reason: 'approval_rejected', sanitized: true },
        details_collapsed: true,
      },
    ],
    diagnostics: { reason: 'approval_rejected', sanitized: true },
  })
}

export function closedApprovalDocument(session, reason = 'approval_expired') {
  const stale = reason === 'approval_stale'
  return baseDocument(session, {
    operationId: `pw-plan-rd-${stale ? 'stale' : 'expired'}`,
    revision: 3,
    state: 'expired',
    message: stale
      ? 'That approval is stale because the session changed state, so I did not apply it.'
      : 'The approval expired, so I did not apply that pending change.',
    currentStepId: `diagnostic:${reason}`,
    runSteps: [
      { step_id: `approval:${reason}`, kind: 'approval', state: 'expired', title: stale ? 'Approval is stale' : 'Approval expired' },
      { step_id: `diagnostic:${reason}`, kind: 'diagnostic', state: 'expired', title: stale ? 'Approval is stale' : 'Approval expired', current: true },
    ],
    blocks: [
      {
        id: `diagnostic:${reason}`,
        type: 'diagnostic',
        severity: 'error',
        reason,
        title: stale ? 'Approval is stale' : 'Approval expired',
        user_message: stale
          ? 'That approval is stale because the session changed state, so I did not apply it.'
          : 'The approval expired, so I did not apply that pending change.',
        cause: stale ? 'The approval no longer matched the current session state.' : 'The approval reached its expiry time before it was accepted.',
        impact: { changes_applied: false, approval_closed: true },
        current_state: 'No action is available on the closed approval.',
        next_action: 'Request a new approval if you still want to make the change.',
        technical_details: { reason, sanitized: true },
        details_collapsed: true,
      },
    ],
    diagnostics: { reason, sanitized: true },
  })
}

export function runningCancellableDocument(session) {
  return baseDocument(session, {
    operationId: 'pw-plan-rd-cancellable',
    revision: 1,
    state: 'running',
    message: 'I am checking records and can still be cancelled.',
    currentStepId: 'read-cancellable',
    runSteps: [
      { step_id: 'analysis-cancellable', kind: 'analysis', state: 'completed', title: 'Understood request' },
      { step_id: 'read-cancellable', kind: 'read', state: 'current', title: 'Checking records', summary: 'Cancellation is still available.', current: true },
    ],
    blocks: [],
  })
}

export function cancelledDocument(session) {
  return baseDocument(session, {
    operationId: 'pw-plan-rd-cancellable',
    revision: 2,
    state: 'cancelled',
    message: 'The run was cancelled. I stopped work and did not continue pending actions.',
    currentStepId: 'diagnostic:cancelled',
    runSteps: [
      { step_id: 'analysis-cancellable', kind: 'analysis', state: 'completed', title: 'Understood request' },
      { step_id: 'diagnostic:cancelled', kind: 'cancelled', state: 'cancelled', title: 'Run cancelled', current: true },
    ],
    blocks: [
      {
        id: 'diagnostic:cancelled',
        type: 'diagnostic',
        severity: 'error',
        reason: 'cancelled_by_user',
        title: 'Run cancelled',
        user_message: 'The run was cancelled. I stopped work and did not continue pending actions.',
        cause: 'The operator cancelled the run.',
        impact: { changes_applied: false, incomplete_steps: ['read-cancellable'] },
        current_state: 'The run is closed in a cancelled state.',
        next_action: 'Start a new request if you want to run it again.',
        technical_details: { reason: 'cancelled_by_user', sanitized: true },
        details_collapsed: true,
      },
    ],
    diagnostics: { reason: 'cancelled_by_user', sanitized: true },
  })
}
