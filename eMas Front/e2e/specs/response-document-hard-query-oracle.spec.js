import { expect, test } from '@playwright/test'

import { hardQueryScenarios } from '../support/hardQueryScenarios.js'

test('response_document hard query oracle catalog includes HQ-01 HQ-05 HQ-3S-01 semantic contracts', () => {
  expect(hardQueryScenarios.map((scenario) => scenario.id)).toEqual([
    'HQ-01',
    'HQ-05',
    'HQ-3S-01',
    'HQ-9-READ',
    'HQ-9-MULTI-ID',
    'HQ-9-MIXED-RAG',
    'HQ-9-RAG-INSUFFICIENT',
    'HQ-9-APPROVAL',
    'HQ-9-INTERRUPT',
    'HQ-9-TOOL-FAILURE',
  ])

  for (const scenario of hardQueryScenarios) {
    expect(scenario.prompt, `${scenario.id} prompt`).toBeTruthy()
    expect(scenario.expected.sessionStatus, `${scenario.id} session status`).toBeTruthy()
    expect(scenario.expected.responseState, `${scenario.id} response state`).toBeTruthy()
    expect(scenario.expected.engine, `${scenario.id} historical engine fixture`).toBeUndefined()
    expect(scenario.expected.visibleSemanticBlocks.length).toBeGreaterThan(0)
    expect(scenario.expected.responseDocument || scenario.expected.toolFailure || scenario.expected.interrupt).toBeTruthy()
  }

  const statusOnly = hardQueryScenarios.find((scenario) => scenario.id === 'HQ-01')
  expect(statusOnly.expected.responseDocument.contracts).toContain('entity_status_v1')
  expect(statusOnly.expected.visibleSemanticBlocks[0].requestedFields).toEqual(['machine_id', 'status'])
  expect(statusOnly.expected.visibleSemanticBlocks[0].displayMode).toBe('compact_status_card')

  const lowPriority = hardQueryScenarios.find((scenario) => scenario.id === 'HQ-05')
  expect(lowPriority.expected.stepSequence[0].args).toMatchObject({
    priority: 'low',
    sort_by: 'deadline',
    sort_dir: 'asc',
    limit: 3,
  })
  expect(lowPriority.expected.visibleSemanticBlocks[0].tableColumnKeys).toEqual(['job_id', 'deadline'])

  const ordered = hardQueryScenarios.find((scenario) => scenario.id === 'HQ-3S-01')
  expect(ordered.expected.stepSequence.map((step) => step.toolName)).toEqual([
    'get__machines_{id}',
    'get__jobs_{id}',
    'get__jobs',
  ])
  expect(ordered.expected.responseDocument.minReadRunSteps).toBeGreaterThanOrEqual(3)
})

test('response_document phase9 hard query oracle covers release-proof scenario families', () => {
  const byId = Object.fromEntries(hardQueryScenarios.map((scenario) => [scenario.id, scenario]))
  const requiredIds = [
    'HQ-9-READ',
    'HQ-9-MULTI-ID',
    'HQ-9-MIXED-RAG',
    'HQ-9-RAG-INSUFFICIENT',
    'HQ-9-APPROVAL',
    'HQ-9-INTERRUPT',
    'HQ-9-TOOL-FAILURE',
  ]

  for (const id of requiredIds) expect(byId[id], `${id} exists`).toBeTruthy()

  const hardRead = byId['HQ-9-READ']
  expect(hardRead.expected.plannerOwnedGraph).toMatchObject({
    engineVersion: 'v2',
    traceId: 'planner_owned_agent_graph',
    runtimeAdapter: 'planner_owned_graph_runtime',
    graphExecutionAuthority: true,
    nativeLangGraphCheckpointUsed: true,
    requiredEvidenceSourceTypes: ['api_tool'],
    allowedEvidenceSourceTypes: ['api_tool'],
  })
  expect(hardRead.expected.capabilityNeeds.map((need) => `${need.sourceOfTruth}:${need.entity}:${need.action}`)).toEqual([
    'operational_state:machine:read_one',
    'operational_state:job:read_one',
    'operational_state:job:read_one',
    'operational_state:job:list',
  ])
  expect(hardRead.expected.conditionalBranches[0]).toMatchObject({
    conditionField: 'status',
    conditionValue: 'blocked',
    requiredEvidence: 'typed_explanation',
  })
  expect(hardRead.expected.visibleSemanticBlocks[0].tableColumnKeys).toEqual([
    'job_id',
    'status',
    'priority',
    'deadline',
  ])

  const multiId = byId['HQ-9-MULTI-ID']
  expect(multiId.expected.responseDocument.blocks[0]).toMatchObject({
    contract: 'entity_status_v1',
    readScope: 'status_only',
    entityCount: 2,
  })
  expect(multiId.expected.plannerOwnedGraph).toMatchObject({
    traceId: 'planner_owned_agent_graph',
    requiredEvidenceSourceTypes: ['api_tool'],
    allowedEvidenceSourceTypes: ['api_tool'],
  })

  const mixed = byId['HQ-9-MIXED-RAG']
  expect(mixed.expected.capabilityNeeds.map((need) => need.sourceOfTruth)).toEqual([
    'operational_state',
    'document_knowledge',
  ])
  expect(mixed.expected.plannerOwnedGraph).toMatchObject({
    traceId: 'planner_owned_agent_graph',
    requiredEvidenceSourceTypes: ['api_tool', 'system_guard'],
    allowedEvidenceSourceTypes: ['api_tool', 'system_guard'],
  })
  expect(mixed.expected.sourceEvidence.requiredSourceFields).toEqual([
    'source_id',
    'doc_id',
    'chunk_id',
    'title',
    'snippet',
  ])

  const insufficient = byId['HQ-9-RAG-INSUFFICIENT']
  expect(insufficient.expected.ragEvidence).toMatchObject({
    insufficientContext: true,
    citationCount: 0,
    relatedSourcesChecked: true,
  })
  expect(insufficient.expected.ragEvidence.fakeSourcesForbidden).toContain('loto_notification_requirement')

  const approval = byId['HQ-9-APPROVAL']
  expect(approval.expected.sessionStatus).toBe('WAITING_APPROVAL')
  expect(approval.expected.plannerOwnedGraph).toMatchObject({
    traceId: 'planner_owned_agent_graph',
    graphExecutionAuthority: true,
    nativeLangGraphCheckpointUsed: true,
  })
  expect(approval.expected.lockedConstraints).toMatchObject({
    priority: 'high',
    new_priority: 'medium',
    date: 'this week',
    requires_approval: true,
  })
  expect(approval.expected.mutationPolicy).toMatchObject({
    commitBeforeApproval: false,
    stagedPayloadRequired: true,
    blockedRowsExcluded: true,
  })

  const interrupt = byId['HQ-9-INTERRUPT']
  expect(interrupt.expected.interrupt).toMatchObject({
    type: 'modify_requirement',
    ledgerRevisionIncrements: true,
    staleApprovalInvalidated: true,
    staleEvidenceInvalidated: true,
  })

  const failure = byId['HQ-9-TOOL-FAILURE']
  expect(failure.expected.toolFailure).toMatchObject({
    sourceType: 'api_tool',
    reason: 'tool_error',
    finalSuccessForbidden: true,
  })
})
