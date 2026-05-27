import fs from 'node:fs'
import path from 'node:path'

import { expect } from '@playwright/test'

import {
  buildSemanticProbe,
  collectVisibleResponseDocumentUi,
  compactText,
  serializeSemanticProbe,
} from './responseDocumentProbe.js'
import { HARD_QUERY_FORBIDDEN_RUNTIME_PATTERNS } from './hardQueryScenarios.js'

const PASS = '__hard_query_oracle_pass__'
const WRITE_TOOL_RE = /^(post|put|patch|delete)__/i

function asArray(value) {
  if (value === undefined || value === null) return []
  return Array.isArray(value) ? value : [value]
}

function matches(value, pattern) {
  const text = String(value || '')
  if (pattern instanceof RegExp) return pattern.test(text)
  return text.includes(String(pattern))
}

function labelForPattern(pattern) {
  if (pattern?.label) return pattern.label
  if (pattern instanceof RegExp) return String(pattern)
  return JSON.stringify(pattern)
}

function canonicalField(value) {
  return String(value || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
}

function fieldsFromArg(value) {
  if (Array.isArray(value)) return value.map(canonicalField).filter(Boolean)
  return String(value || '').split(',').map(canonicalField).filter(Boolean)
}

function normalizeExpectedArg(value) {
  if (Array.isArray(value)) return value.map(canonicalField).filter(Boolean)
  return value
}

function valuesEqual(actual, expected) {
  if (Array.isArray(expected)) {
    return JSON.stringify(fieldsFromArg(actual)) === JSON.stringify(normalizeExpectedArg(expected))
  }
  if (typeof expected === 'number') return Number(actual) === expected
  return String(actual ?? '').toLowerCase() === String(expected ?? '').toLowerCase()
}

function arrayContainsAll(actual, expected) {
  const actualSet = new Set(asArray(actual).map(canonicalField))
  return asArray(expected).every((value) => actualSet.has(canonicalField(value)))
}

function arrayEquals(actual, expected) {
  return JSON.stringify(asArray(actual).map(canonicalField)) === JSON.stringify(asArray(expected).map(canonicalField))
}

function compactStep(step) {
  return {
    tool_name: step?.tool_name || step?.toolName || null,
    status: step?.status || null,
    args: step?.args || {},
    result_summary: compactText(step?.result_summary || '', 160),
  }
}

function backendSteps(snapshot) {
  return Array.isArray(snapshot?.steps) ? snapshot.steps.map(compactStep) : []
}

function backendBlocks(snapshot) {
  return Array.isArray(snapshot?.response_document?.blocks) ? snapshot.response_document.blocks : []
}

function backendRunSteps(snapshot) {
  return Array.isArray(snapshot?.response_document?.run_steps) ? snapshot.response_document.run_steps : []
}

function plannerOwnedGraphPayload(snapshot) {
  const context = snapshot?.session?.replan_context && typeof snapshot.session.replan_context === 'object'
    ? snapshot.session.replan_context
    : {}
  const intentContract = context.intent_contract && typeof context.intent_contract === 'object'
    ? context.intent_contract
    : {}
  const graphState = intentContract.planner_owned_agent_graph_state && typeof intentContract.planner_owned_agent_graph_state === 'object'
    ? intentContract.planner_owned_agent_graph_state
    : {}
  const graphContext = context.planner_owned_agent_graph && typeof context.planner_owned_agent_graph === 'object'
    ? context.planner_owned_agent_graph
    : {}
  const responseDocumentContext = intentContract.response_document_context && typeof intentContract.response_document_context === 'object'
    ? intentContract.response_document_context
    : graphContext.response_document_context && typeof graphContext.response_document_context === 'object'
      ? graphContext.response_document_context
      : {}
  const v2State = intentContract.v2_state && typeof intentContract.v2_state === 'object' ? intentContract.v2_state : {}
  const executionTrace = intentContract.execution_trace && typeof intentContract.execution_trace === 'object'
    ? intentContract.execution_trace
    : graphState.execution_trace && typeof graphState.execution_trace === 'object'
      ? graphState.execution_trace
      : {}
  const graphDiagnostics = executionTrace.diagnostics && typeof executionTrace.diagnostics === 'object'
    ? executionTrace.diagnostics
    : {}
  const replanSpine = intentContract.replan_spine && typeof intentContract.replan_spine === 'object'
    ? intentContract.replan_spine
    : graphContext.replan_spine && typeof graphContext.replan_spine === 'object'
      ? graphContext.replan_spine
      : graphDiagnostics.replan_spine && typeof graphDiagnostics.replan_spine === 'object'
        ? graphDiagnostics.replan_spine
        : {}
  const graphEvidence = graphState.evidence_ledger?.evidence
  const v2Evidence = v2State.evidence_ledger?.evidence
  const evidence = Array.isArray(graphEvidence) ? graphEvidence : Array.isArray(v2Evidence) ? v2Evidence : []
  return { context: graphContext, intentContract, executionTrace, graphState, v2State, evidence, responseDocumentContext, replanSpine }
}

function toolName(step) {
  return step?.tool_name || step?.toolName || ''
}

function stepMatches(step, expected) {
  if (expected.toolName && toolName(step) !== expected.toolName) return false
  const args = step?.args || {}
  for (const [key, expectedValue] of Object.entries(expected.args || {})) {
    if (!valuesEqual(args[key], expectedValue)) return false
  }
  return true
}

function forbiddenStepMatches(step, expected) {
  if (expected.toolName && toolName(step) !== expected.toolName) return false
  const args = step?.args || {}
  if (expected.emptyArgs) return Object.keys(args).length === 0
  return stepMatches(step, expected)
}

function addStepViolations(violations, snapshot, expected) {
  const steps = backendSteps(snapshot)
  if (Object.hasOwn(expected, 'minStepCount') && steps.length < expected.minStepCount) {
    violations.push(`expected at least ${expected.minStepCount} backend steps but saw ${steps.length}`)
  }
  if (Object.hasOwn(expected, 'maxStepCount') && steps.length > expected.maxStepCount) {
    violations.push(`expected at most ${expected.maxStepCount} backend steps but saw ${steps.length}`)
  }
  for (const expectedToolName of asArray(expected.toolNames)) {
    if (!steps.some((step) => toolName(step) === expectedToolName)) {
      violations.push(`backend steps missing tool ${expectedToolName}`)
    }
  }
  let cursor = 0
  for (const expectedStep of asArray(expected.stepSequence)) {
    const found = steps.findIndex((step, index) => index >= cursor && stepMatches(step, expectedStep))
    if (found < 0) {
      violations.push(`backend step sequence missing ${expectedStep.toolName} with args ${JSON.stringify(expectedStep.args || {})}`)
      continue
    }
    cursor = found + 1
  }
  for (const forbiddenStep of asArray(expected.forbiddenStepSequence)) {
    const found = steps.find((step) => forbiddenStepMatches(step, forbiddenStep))
    if (found) {
      violations.push(`backend step sequence unexpectedly included ${forbiddenStep.toolName} with args ${JSON.stringify(found.args || {})}`)
    }
  }
  if (expected.noMutation) {
    const writeSteps = steps.filter((step) => WRITE_TOOL_RE.test(toolName(step)))
    if (writeSteps.length) {
      violations.push(`read-only scenario executed write tools: ${writeSteps.map(toolName).join(', ')}`)
    }
  }
}

function blockMatches(block, expectedBlock) {
  if (expectedBlock.type && block?.type !== expectedBlock.type) return false
  if (expectedBlock.contract && block?.contract !== expectedBlock.contract) return false
  if (expectedBlock.readScope && block?.read_scope !== expectedBlock.readScope) return false
  if (expectedBlock.displayMode && block?.display_mode !== expectedBlock.displayMode) return false
  if (expectedBlock.entityType && block?.entity_type !== expectedBlock.entityType) return false
  if (Object.hasOwn(expectedBlock, 'entityCount') && Number(block?.entity_count) !== Number(expectedBlock.entityCount)) return false
  if (expectedBlock.requestedFields && !arrayEquals(block?.requested_fields || [], expectedBlock.requestedFields)) return false
  if (Object.hasOwn(expectedBlock, 'maxRows') && Array.isArray(block?.rows) && block.rows.length > expectedBlock.maxRows) return false
  return true
}

function addResponseDocumentViolations(violations, snapshot, expected) {
  const document = snapshot?.response_document || {}
  const blocks = backendBlocks(snapshot)
  const blockTypes = blocks.map((block) => block?.type).filter(Boolean)
  const contracts = [
    ...blocks.map((block) => block?.contract),
    ...blocks.flatMap((block) => Array.isArray(block?.citations) ? block.citations.map((citation) => citation?.contract) : []),
    ...blocks.flatMap((block) => Array.isArray(block?.sources) ? block.sources.map((source) => source?.contract) : []),
    document.invariants?.read_status_contract,
    document.invariants?.mutation_business_contract,
    document.invariants?.no_op_mutation_contract,
    document.invariants?.source_list_contract,
    document.invariants?.source_locator_contract,
  ].filter(Boolean)
  const responseExpected = expected.responseDocument || {}
  for (const type of asArray(responseExpected.blockTypes)) {
    if (!blockTypes.includes(type)) violations.push(`response_document missing block type ${type}`)
  }
  for (const type of asArray(responseExpected.hiddenBlockTypes)) {
    if (blockTypes.includes(type)) violations.push(`response_document unexpectedly exposed block type ${type}`)
  }
  for (const contract of asArray(responseExpected.contracts)) {
    if (!contracts.includes(contract)) violations.push(`response_document missing contract ${contract}`)
  }
  for (const expectedBlock of asArray(responseExpected.blocks)) {
    if (!blocks.some((block) => blockMatches(block, expectedBlock))) {
      violations.push(`response_document missing semantic block ${JSON.stringify(expectedBlock)}`)
    }
  }
  if (Object.hasOwn(responseExpected, 'minReadRunSteps')) {
    const readRunSteps = backendRunSteps(snapshot).filter((step) => step?.kind === 'read')
    if (readRunSteps.length < responseExpected.minReadRunSteps) {
      violations.push(`response_document expected at least ${responseExpected.minReadRunSteps} read run_steps but saw ${readRunSteps.length}`)
    }
  }
  if (expected.noMutation && blockTypes.some((type) => ['approval_required', 'mutation_result'].includes(type))) {
    violations.push(`read-only scenario response_document contained mutation/approval block: ${blockTypes.join(', ')}`)
  }
}

function addPlannerOwnedGraphViolations(violations, snapshot, expected) {
  const graphExpected = expected.plannerOwnedGraph || {}
  if (!Object.keys(graphExpected).length) return

  const payload = plannerOwnedGraphPayload(snapshot)
  const trace = payload.executionTrace
  const graphContext = payload.context
  const evidenceSourceTypes = payload.evidence.map((entry) => entry?.source_type).filter(Boolean)

  if (graphExpected.engineVersion && (trace.engine_version || payload.intentContract.engine_version) !== graphExpected.engineVersion) {
    violations.push(
      `planner-owned graph engine_version expected ${graphExpected.engineVersion} but saw ${trace.engine_version || payload.intentContract.engine_version || '<missing>'}`,
    )
  }
  if (graphExpected.traceId && trace.generated_by !== graphExpected.traceId) {
    violations.push(`planner-owned graph trace expected ${graphExpected.traceId} but saw ${trace.generated_by || '<missing>'}`)
  }
  if (graphExpected.runtimeAdapter && graphContext.runtime_adapter !== graphExpected.runtimeAdapter) {
    violations.push(
      `planner-owned graph runtime adapter expected ${graphExpected.runtimeAdapter} but saw ${graphContext.runtime_adapter || '<missing>'}`,
    )
  }
  if (
    Object.hasOwn(graphExpected, 'graphExecutionAuthority')
    && Boolean(graphContext.graph_execution_authority) !== Boolean(graphExpected.graphExecutionAuthority)
  ) {
    violations.push(
      `planner-owned graph execution authority expected ${graphExpected.graphExecutionAuthority} but saw ${graphContext.graph_execution_authority ?? '<missing>'}`,
    )
  }
  if (
    Object.hasOwn(graphExpected, 'nativeLangGraphCheckpointUsed')
    && Boolean(graphContext.native_langgraph_checkpoint_used) !== Boolean(graphExpected.nativeLangGraphCheckpointUsed)
  ) {
    violations.push(
      `planner-owned graph native checkpoint expected ${graphExpected.nativeLangGraphCheckpointUsed} but saw ${graphContext.native_langgraph_checkpoint_used ?? '<missing>'}`,
    )
  }
  for (const sourceType of asArray(graphExpected.requiredEvidenceSourceTypes)) {
    if (!evidenceSourceTypes.includes(sourceType)) {
      violations.push(`planner-owned graph evidence missing source_type ${sourceType}`)
    }
  }
  const allowedSourceTypes = new Set(asArray(graphExpected.allowedEvidenceSourceTypes))
  if (allowedSourceTypes.size) {
    const unexpected = Array.from(new Set(evidenceSourceTypes.filter((sourceType) => !allowedSourceTypes.has(sourceType))))
    if (unexpected.length) {
      violations.push(`planner-owned graph evidence had unexpected source_type ${unexpected.join(', ')}`)
    }
  }
}

function addReplanSpineViolations(violations, snapshot, expected) {
  const replanExpected = expected.replanSpine || {}
  if (!Object.keys(replanExpected).length) return

  const payload = plannerOwnedGraphPayload(snapshot)
  const replan = payload.replanSpine && typeof payload.replanSpine === 'object' ? payload.replanSpine : {}
  const attemptCount = Number(replan.attempt_count || 0)
  const maxAttempts = Number(replan.max_attempts || 0)
  const missingReasons = Array.isArray(replan.missing_evidence_reasons) ? replan.missing_evidence_reasons : []
  const failedToolCalls = Array.isArray(replan.failed_tool_calls) ? replan.failed_tool_calls : []
  const staleRefs = asArray(replan.stale_attempt_evidence_refs || replan.stale_evidence_refs)
  const historicalRefs = asArray(replan.historical_evidence_refs)
  const activeFinalRefs = asArray(replan.active_final_evidence_refs)
  const responseEvidenceRefs = asArray(snapshot?.response_document?.evidence_refs)
    .concat(asArray(payload.responseDocumentContext?.evidence_refs))
  const responseEvidenceSet = new Set(responseEvidenceRefs)

  if (Object.hasOwn(replanExpected, 'minAttempts') && attemptCount < Number(replanExpected.minAttempts)) {
    violations.push(`replan_spine expected at least ${replanExpected.minAttempts} attempts but saw ${attemptCount}`)
  }
  if (Object.hasOwn(replanExpected, 'maxAttempts') && attemptCount > Number(replanExpected.maxAttempts)) {
    violations.push(`replan_spine expected at most ${replanExpected.maxAttempts} attempts but saw ${attemptCount}`)
  }
  if (replanExpected.attemptCountEqualsMaxAttempts && attemptCount !== maxAttempts) {
    violations.push(`replan_spine attempt_count ${attemptCount} did not equal max_attempts ${maxAttempts}`)
  }
  if (Object.hasOwn(replanExpected, 'limitReached') && Boolean(replan.replan_limit_reached) !== Boolean(replanExpected.limitReached)) {
    violations.push(`replan_spine limitReached expected ${replanExpected.limitReached} but saw ${Boolean(replan.replan_limit_reached)}`)
  }
  if (replanExpected.requiresMissingEvidenceReason && !missingReasons.length) {
    violations.push('replan_spine missing persisted missing_evidence_reasons')
  }
  if (
    replanExpected.missingEvidenceReason
    && !missingReasons.some((reason) => reason?.reason === replanExpected.missingEvidenceReason)
  ) {
    violations.push(`replan_spine missing evidence reason ${replanExpected.missingEvidenceReason}`)
  }
  if (replanExpected.requiresFailedToolMemory && !failedToolCalls.length) {
    violations.push('replan_spine missing persisted failed_tool_calls')
  }
  if (
    replanExpected.failedToolReason
    && !failedToolCalls.some((call) => call?.reason === replanExpected.failedToolReason)
  ) {
    violations.push(`replan_spine failed_tool_calls missing reason ${replanExpected.failedToolReason}`)
  }
  if (replanExpected.requiresStaleAttemptEvidence && !staleRefs.length) {
    violations.push('replan_spine missing stale attempt evidence refs')
  }
  if (replanExpected.requiresHistoricalEvidence && !historicalRefs.length) {
    violations.push('replan_spine missing historical evidence refs')
  }
  if (replanExpected.requiresActiveFinalEvidence && !activeFinalRefs.length) {
    violations.push('replan_spine missing active final evidence refs')
  }
  if (replanExpected.forbidActiveFinalEvidence && activeFinalRefs.length) {
    violations.push(`replan_spine unexpectedly had active final evidence refs ${activeFinalRefs.join(', ')}`)
  }
  if (replanExpected.forbidStaleFinalEvidence) {
    const staleFinalRefs = staleRefs.filter((ref) => activeFinalRefs.includes(ref) || responseEvidenceSet.has(ref))
    if (staleFinalRefs.length) {
      violations.push(`replan_spine stale evidence leaked into final response refs: ${staleFinalRefs.join(', ')}`)
    }
  }
  if (replanExpected.activeFinalEvidenceInResponse) {
    const missing = activeFinalRefs.filter((ref) => !responseEvidenceSet.has(ref))
    if (missing.length) {
      violations.push(`replan_spine active final evidence missing from response refs: ${missing.join(', ')}`)
    }
  }
  if (replanExpected.forbidResponseEvidenceRefs && responseEvidenceRefs.length) {
    violations.push(`replan_spine safe failure unexpectedly exposed response evidence refs: ${responseEvidenceRefs.join(', ')}`)
  }
}

function evidenceIsActiveForFinalAnswer(evidence) {
  const metadata = evidence?.diagnostic_metadata && typeof evidence.diagnostic_metadata === 'object'
    ? evidence.diagnostic_metadata
    : {}
  return (
    metadata.active_revision_satisfaction !== false
    && metadata.stale_after_graph_revision !== true
    && metadata.stale_after_graph_replan !== true
    && metadata.stale_after_user_interrupt !== true
  )
}

function selectedToolCalls(decision) {
  return [
    ...(decision?.selected_tool_call ? [decision.selected_tool_call] : []),
    ...(Array.isArray(decision?.selected_tool_calls) ? decision.selected_tool_calls : []),
  ]
}

function conditionalBranchesForPayload(payload, snapshot) {
  const graphStateBranches = payload.graphState?.requirement_ledger?.conditional_branches
  const v2Branches = payload.v2State?.requirement_ledger?.conditional_branches
  const contractBranches = payload.intentContract?.conditional_branches
  const contextBranches = payload.context?.conditional_branches
  const responseBranches = snapshot?.response_document?.diagnostics?.conditional_branches
  for (const candidate of [contractBranches, contextBranches, responseBranches, graphStateBranches, v2Branches]) {
    if (Array.isArray(candidate)) return candidate
  }
  return []
}

function addConditionalBranchViolations(violations, snapshot, expected) {
  const branchExpected = asArray(expected.conditionalBranches)
  if (!branchExpected.length) return

  const payload = plannerOwnedGraphPayload(snapshot)
  const branches = conditionalBranchesForPayload(payload, snapshot)
  if (!branches.length) {
    violations.push('conditional_branch expected branch diagnostics but none were exposed')
    return
  }

  for (const expectedBranch of branchExpected) {
    const found = branches.find((branch) => {
      const condition = branch?.condition || {}
      if (expectedBranch.status && branch?.status !== expectedBranch.status) return false
      if (expectedBranch.skippedReason && branch?.skipped_reason !== expectedBranch.skippedReason) return false
      if (expectedBranch.conditionType && condition.type !== expectedBranch.conditionType) return false
      if (expectedBranch.conditionField && condition.field !== expectedBranch.conditionField) return false
      if (Object.hasOwn(expectedBranch, 'conditionValue') && String(condition.value ?? '') !== String(expectedBranch.conditionValue)) return false
      if (expectedBranch.fieldAny) {
        const actualFields = new Set(asArray(condition.field_any))
        if (!expectedBranch.fieldAny.every((field) => actualFields.has(field))) return false
      }
      return true
    })
    if (!found) {
      violations.push(`conditional_branch missing expected diagnostics ${JSON.stringify(expectedBranch)}`)
    }
  }
}

function addRequirementExpansionViolations(violations, snapshot, expected) {
  const expansionExpected = expected.requirementExpansion || {}
  if (!Object.keys(expansionExpected).length) return

  const payload = plannerOwnedGraphPayload(snapshot)
  const graphState = payload.graphState || {}
  const v2State = payload.v2State || {}
  const ledger = graphState.requirement_ledger || v2State.requirement_ledger || {}
  const requirements = Array.isArray(ledger.requirements) ? ledger.requirements : []
  const lineage = Array.isArray(payload.intentContract.child_requirement_lineage)
    ? payload.intentContract.child_requirement_lineage
    : Array.isArray(payload.context.child_requirement_lineage)
      ? payload.context.child_requirement_lineage
      : Array.isArray(snapshot?.response_document?.diagnostics?.child_requirement_lineage)
        ? snapshot.response_document.diagnostics.child_requirement_lineage
        : []
  const childRequirements = requirements.filter((requirement) => requirement?.parent_requirement_id)
  const parentRequirementIds = new Set(childRequirements.map((requirement) => requirement.parent_requirement_id))
  const childRequirementIds = new Set(childRequirements.map((requirement) => requirement.id))
  const candidateRequirementIds = new Set(asArray(graphState.candidate_tool_windows || v2State.candidate_tool_windows).map((window) => window?.requirement_id))
  const hydratedRequirementIds = new Set(asArray(graphState.hydrated_tool_cards || v2State.hydrated_tool_cards).map((cards) => cards?.requirement_id))
  const decisions = Array.isArray(graphState.planner_decisions) ? graphState.planner_decisions : []
  const chooseDecisions = decisions.filter((decision) => decision?.decision_kind === 'choose_tool')
  const evidence = payload.evidence
  const evidenceById = new Map(evidence.map((entry) => [entry?.id, entry]))
  const responseEvidenceRefs = new Set(
    asArray(snapshot?.response_document?.evidence_refs)
      .concat(asArray(payload.responseDocumentContext?.evidence_refs))
      .concat(asArray(snapshot?.response_document?.diagnostics?.response_evidence_refs)),
  )

  if (expansionExpected.expectNoChildLineage && (lineage.length || childRequirements.length)) {
    violations.push('requirement_expansion expected empty child lineage but found child requirements')
  }

  if (expansionExpected.requireChildLineage && (!lineage.length || !childRequirements.length)) {
    violations.push('requirement_expansion missing child lineage in intent contract or response diagnostics')
  }

  for (const parentId of asArray(expansionExpected.parentRequirementIds || expansionExpected.parentRequirementId)) {
    if (!parentRequirementIds.has(parentId)) {
      violations.push(`requirement_expansion missing child under parent ${parentId}`)
    }
  }

  for (const child of childRequirements) {
    if (expansionExpected.childEntity && child.entity !== expansionExpected.childEntity) {
      violations.push(`requirement_expansion child ${child.id} entity expected ${expansionExpected.childEntity} but saw ${child.entity || '<missing>'}`)
    }
    if (
      expansionExpected.childConstraintKey
      && Object.hasOwn(expansionExpected, 'childConstraintValue')
      && String(child.constraints?.[expansionExpected.childConstraintKey] ?? '') !== String(expansionExpected.childConstraintValue)
    ) {
      violations.push(
        `requirement_expansion child ${child.id} constraint ${expansionExpected.childConstraintKey} expected ${expansionExpected.childConstraintValue}`,
      )
    }
  }

  if (expansionExpected.requireFreshChildRetrieval) {
    for (const childId of childRequirementIds) {
      if (!candidateRequirementIds.has(childId)) violations.push(`requirement_expansion child ${childId} missing child-scoped candidate window`)
      if (!hydratedRequirementIds.has(childId)) violations.push(`requirement_expansion child ${childId} missing child-scoped hydrated cards`)
      const childChoices = chooseDecisions.filter((decision) => decision.requirement_id === childId)
      if (!childChoices.length) violations.push(`requirement_expansion child ${childId} missing child-scoped choose_tool decision`)
      for (const call of childChoices.flatMap(selectedToolCalls)) {
        if (call.requirement_id !== childId) {
          violations.push(`requirement_expansion child ${childId} selected tool call targeted ${call.requirement_id || '<missing>'}`)
        }
        if (!call.candidate_window_id) {
          violations.push(`requirement_expansion child ${childId} selected tool call missing candidate_window_id`)
        }
      }
    }
  }

  for (const toolName of asArray(expansionExpected.childToolNames)) {
    const childToolNames = chooseDecisions
      .filter((decision) => childRequirementIds.has(decision.requirement_id))
      .flatMap(selectedToolCalls)
      .map((call) => call.tool_name)
    if (!childToolNames.includes(toolName)) {
      violations.push(`requirement_expansion child choices missing tool ${toolName}`)
    }
  }

  if (expansionExpected.forbidParentToolExecutableReuse) {
    const parentCallIds = new Set(
      chooseDecisions
        .filter((decision) => parentRequirementIds.has(decision.requirement_id))
        .flatMap(selectedToolCalls)
        .map((call) => call.call_id)
        .filter(Boolean),
    )
    const parentToolNames = new Set(asArray(expansionExpected.parentToolNames))
    for (const childCall of chooseDecisions.filter((decision) => childRequirementIds.has(decision.requirement_id)).flatMap(selectedToolCalls)) {
      if (parentCallIds.has(childCall.call_id)) {
        violations.push(`requirement_expansion child reused parent executable call id ${childCall.call_id}`)
      }
      if (parentToolNames.has(childCall.tool_name)) {
        violations.push(`requirement_expansion child reused parent executable tool ${childCall.tool_name}`)
      }
    }
  }

  if (expansionExpected.requireFinalParentAndChildEvidence) {
    for (const requirement of requirements.filter((item) => parentRequirementIds.has(item.id) || childRequirementIds.has(item.id))) {
      const refs = asArray(requirement.evidence_refs)
      if (!refs.length) violations.push(`requirement_expansion requirement ${requirement.id} missing evidence_refs`)
      for (const ref of refs) {
        const item = evidenceById.get(ref)
        if (!item) {
          violations.push(`requirement_expansion evidence ref ${ref} missing from ledger`)
          continue
        }
        if (!evidenceIsActiveForFinalAnswer(item)) {
          violations.push(`requirement_expansion evidence ref ${ref} is not active for final answer`)
        }
        if (!responseEvidenceRefs.has(ref)) {
          violations.push(`requirement_expansion active evidence ref ${ref} missing from final response refs`)
        }
      }
    }
  }

  if (expansionExpected.forbidStaleFinalEvidence) {
    const staleFinalRefs = evidence
      .filter((item) => !evidenceIsActiveForFinalAnswer(item))
      .map((item) => item?.id)
      .filter((ref) => ref && responseEvidenceRefs.has(ref))
    if (staleFinalRefs.length) {
      violations.push(`requirement_expansion stale or failed evidence leaked into final response refs: ${staleFinalRefs.join(', ')}`)
    }
  }
}

function visibleBlockMatches(block, expectedBlock) {
  if (expectedBlock.type && block?.type !== expectedBlock.type) return false
  if (expectedBlock.contract && block?.contract !== expectedBlock.contract) return false
  if (expectedBlock.readScope && block?.readScope !== expectedBlock.readScope) return false
  if (expectedBlock.displayMode && block?.displayMode !== expectedBlock.displayMode) return false
  if (expectedBlock.entityType && block?.entityType !== expectedBlock.entityType) return false
  if (expectedBlock.title && !matches(block?.title || '', expectedBlock.title)) return false
  for (const pattern of asArray(expectedBlock.textIncludes)) {
    if (!matches(block?.text || '', pattern)) return false
  }
  for (const pattern of asArray(expectedBlock.forbiddenText)) {
    if (matches(block?.text || '', pattern)) return false
  }
  if (expectedBlock.requestedFields && !arrayEquals(block?.requestedFields || [], expectedBlock.requestedFields)) return false
  if (expectedBlock.statusFieldKeys && !arrayEquals(block?.statusFieldKeys || [], expectedBlock.statusFieldKeys)) return false
  if (expectedBlock.tableColumnKeys && !arrayEquals(block?.tableColumnKeys || [], expectedBlock.tableColumnKeys)) return false
  if (Object.hasOwn(expectedBlock, 'maxRows')) {
    const rowCount = Number(block?.tableRenderedRowCount ?? block?.tableRowCount ?? block?.entityCount ?? 0)
    if (Number.isFinite(rowCount) && rowCount > Number(expectedBlock.maxRows)) return false
  }
  return true
}

function addVisibleBlockViolations(violations, ui, expected) {
  const blocks = Array.isArray(ui?.visibleBlocks) ? ui.visibleBlocks : []
  for (const expectedBlock of asArray(expected.visibleSemanticBlocks)) {
    const block = blocks.find((candidate) => visibleBlockMatches(candidate, expectedBlock))
    if (!block) {
      violations.push(`visible DOM missing semantic block ${JSON.stringify(expectedBlock)}`)
      continue
    }
    for (const key of asArray(expectedBlock.forbiddenStatusFieldKeys)) {
      if (arrayContainsAll(block.statusFieldKeys || [], [key]) || arrayContainsAll(block.statusSecondaryFieldKeys || [], [key])) {
        violations.push(`visible status block leaked field ${key}`)
      }
    }
    for (const key of asArray(expectedBlock.forbiddenTableColumnKeys)) {
      if (arrayContainsAll(block.tableColumnKeys || [], [key])) {
        violations.push(`visible result table leaked column ${key}`)
      }
    }
  }
  const expectedRunSteps = asArray(expected.visibleRunSteps)
  if (expectedRunSteps.length) {
    const titles = asArray(ui?.visibleRunSteps).map((step) => step?.title || '')
    let cursor = 0
    for (const expectedStep of expectedRunSteps) {
      const found = titles.findIndex((title, index) => index >= cursor && matches(title, expectedStep.title))
      if (found < 0) violations.push(`visible run steps missing ordered title ${labelForPattern(expectedStep.title)}`)
      else cursor = found + 1
    }
  }
}

function addApprovalViolations(violations, snapshot, pendingApprovals, expected) {
  if (!Object.hasOwn(expected, 'approvalCount')) return
  const pending = Array.isArray(pendingApprovals) ? pendingApprovals : []
  if (pending.length !== expected.approvalCount) {
    violations.push(`pending approval count expected ${expected.approvalCount} but saw ${pending.length}`)
  }
  if (expected.approvalCount === 0 && snapshot?.pending_approval) {
    violations.push(`snapshot still has pending approval ${snapshot.pending_approval.approval_id || '<unknown>'}`)
  }
}

function addForbiddenTextViolations(violations, snapshot, ui, expected) {
  const visibleText = String(ui?.latestAssistantText || ui?.latestAssistantMessage || '')
  const visibleUiText = String(ui?.visibleText || '')
  const backendContractText = JSON.stringify({
    response_document: snapshot?.response_document || {},
    steps: backendSteps(snapshot).map((step) => ({
      tool_name: step.tool_name,
      status: step.status,
      args: step.args,
      result_summary: step.result_summary,
    })),
  })
  for (const item of [...HARD_QUERY_FORBIDDEN_RUNTIME_PATTERNS, ...asArray(expected.forbiddenVisibleText)]) {
    const pattern = item?.pattern || item
    if (matches(visibleText, pattern)) {
      violations.push(`forbidden visible text matched ${item?.label || labelForPattern(pattern)}`)
    }
  }
  for (const item of asArray(expected.forbiddenUiText)) {
    const pattern = item?.pattern || item
    if (matches(visibleUiText, pattern)) {
      violations.push(`forbidden visible UI text matched ${item?.label || labelForPattern(pattern)}`)
    }
  }
  for (const item of [...HARD_QUERY_FORBIDDEN_RUNTIME_PATTERNS, ...asArray(expected.forbiddenBackendText)]) {
    const pattern = item?.pattern || item
    if (matches(backendContractText, pattern)) {
      violations.push(`forbidden backend contract text matched ${item?.label || labelForPattern(pattern)}`)
    }
  }
  for (const item of asArray(expected.visibleTextIncludes)) {
    const pattern = item?.pattern || item
    if (!matches(visibleText, pattern)) {
      violations.push(`visible text missing ${item?.label || labelForPattern(pattern)}`)
    }
  }
  for (const item of asArray(expected.visibleUiTextIncludes)) {
    const pattern = item?.pattern || item
    if (!matches(visibleUiText, pattern)) {
      violations.push(`visible UI text missing ${item?.label || labelForPattern(pattern)}`)
    }
  }
  for (const item of asArray(expected.backendTextIncludes)) {
    const pattern = item?.pattern || item
    if (!matches(backendContractText, pattern)) {
      violations.push(`backend contract text missing ${item?.label || labelForPattern(pattern)}`)
    }
  }
}

function evaluateHardQueryProbe({ snapshot, ui, pendingApprovals, scenario }) {
  const expected = scenario.expected || {}
  const violations = []
  const sessionStatus = snapshot?.session?.status || null
  const responseState = snapshot?.response_document?.state || null
  const graphPayload = plannerOwnedGraphPayload(snapshot)

  if (expected.sessionStatus && sessionStatus !== expected.sessionStatus) {
    violations.push(`backend session.status expected ${expected.sessionStatus} but saw ${sessionStatus || '<missing>'}`)
  }
  if (expected.responseState && responseState !== expected.responseState) {
    violations.push(`response_document.state expected ${expected.responseState} but saw ${responseState || '<missing>'}`)
  }

  addStepViolations(violations, snapshot, expected)
  addResponseDocumentViolations(violations, snapshot, expected)
  addPlannerOwnedGraphViolations(violations, snapshot, expected)
  addReplanSpineViolations(violations, snapshot, expected)
  addConditionalBranchViolations(violations, snapshot, expected)
  addRequirementExpansionViolations(violations, snapshot, expected)
  addVisibleBlockViolations(violations, ui, expected)
  addApprovalViolations(violations, snapshot, pendingApprovals, expected)
  addForbiddenTextViolations(violations, snapshot, ui, expected)

  return {
    ok: violations.length === 0,
    violations,
    semanticProbe: buildSemanticProbe({
      checkpoint: `${scenario.id} hard query oracle`,
      snapshot,
      ui,
      expected,
      violations,
    }),
    hardQuery: {
      scenarioId: scenario.id,
      prompt: scenario.prompt,
      backendSteps: backendSteps(snapshot),
      backendRunSteps: backendRunSteps(snapshot).map((step) => ({
        kind: step.kind,
        title: step.title,
        state: step.state,
        record_count: step.record_count,
      })),
      responseBlocks: backendBlocks(snapshot).map((block) => ({
        type: block.type,
        contract: block.contract,
        read_scope: block.read_scope,
        requested_fields: block.requested_fields,
        display_mode: block.display_mode,
        entity_type: block.entity_type,
        entity_count: block.entity_count,
        row_count: Array.isArray(block.rows) ? block.rows.length : null,
      })),
      visibleBlocks: asArray(ui?.visibleBlocks).map((block) => ({
        type: block.type,
        contract: block.contract,
        readScope: block.readScope,
        requestedFields: block.requestedFields,
        displayMode: block.displayMode,
        entityType: block.entityType,
        statusFieldKeys: block.statusFieldKeys,
        tableColumnKeys: block.tableColumnKeys,
        tableRenderedRowCount: block.tableRenderedRowCount,
      })),
      visibleRunSteps: ui?.visibleRunSteps || [],
      plannerOwnedGraph: {
        runtimeAdapter: graphPayload.context.runtime_adapter || null,
        graphExecutionAuthority: graphPayload.context.graph_execution_authority ?? null,
        nativeLangGraphCheckpointUsed: graphPayload.context.native_langgraph_checkpoint_used ?? null,
        engineVersion: graphPayload.executionTrace.engine_version || graphPayload.intentContract.engine_version || null,
        traceId: graphPayload.executionTrace.generated_by || null,
        evidenceSourceTypes: Array.from(
          new Set(graphPayload.evidence.map((entry) => entry?.source_type).filter(Boolean)),
        ),
      },
      replanSpine: {
        attemptCount: graphPayload.replanSpine.attempt_count ?? null,
        maxAttempts: graphPayload.replanSpine.max_attempts ?? null,
        limitReached: graphPayload.replanSpine.replan_limit_reached ?? false,
        missingEvidenceReasonCount: asArray(graphPayload.replanSpine.missing_evidence_reasons).length,
        failedToolCallCount: asArray(graphPayload.replanSpine.failed_tool_calls).length,
        staleAttemptEvidenceRefs: asArray(
          graphPayload.replanSpine.stale_attempt_evidence_refs || graphPayload.replanSpine.stale_evidence_refs,
        ),
        activeFinalEvidenceRefs: asArray(graphPayload.replanSpine.active_final_evidence_refs),
        historicalEvidenceRefs: asArray(graphPayload.replanSpine.historical_evidence_refs),
      },
      requirementExpansion: {
        lineageCount: asArray(graphPayload.intentContract.child_requirement_lineage || graphPayload.context.child_requirement_lineage).length,
        childRequirementIds: asArray(
          graphPayload.graphState?.requirement_ledger?.requirements || graphPayload.v2State?.requirement_ledger?.requirements,
        )
          .filter((requirement) => requirement?.parent_requirement_id)
          .map((requirement) => requirement.id),
        candidateRequirementIds: asArray(
          graphPayload.graphState?.candidate_tool_windows || graphPayload.v2State?.candidate_tool_windows,
        ).map((window) => window?.requirement_id),
        hydratedRequirementIds: asArray(
          graphPayload.graphState?.hydrated_tool_cards || graphPayload.v2State?.hydrated_tool_cards,
        ).map((cards) => cards?.requirement_id),
      },
      pendingApprovals,
      violations,
    },
  }
}

function safeArtifactName(value) {
  return String(value || 'hard-query')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
    .slice(0, 80) || 'hard-query'
}

async function attachHardQueryArtifact(testInfo, scenario, payload) {
  if (!testInfo) return
  const name = `${safeArtifactName(scenario.id)}-hard-query-oracle.json`
  const artifactPath = testInfo.outputPath(name)
  fs.mkdirSync(path.dirname(artifactPath), { recursive: true })
  fs.writeFileSync(artifactPath, serializeSemanticProbe(payload))
  await testInfo.attach(name, {
    path: artifactPath,
    contentType: 'application/json',
  })
}

export async function collectHardQueryProbe(page, scenario, { snapshotForPage, pendingApprovalsForPage }) {
  const [snapshot, ui, pendingApprovals] = await Promise.all([
    snapshotForPage(page),
    collectVisibleResponseDocumentUi(page),
    pendingApprovalsForPage(page),
  ])
  return { snapshot, ui, pendingApprovals, scenario }
}

export async function expectHardQueryScenario(page, scenario, {
  snapshotForPage,
  pendingApprovalsForPage,
  testInfo = null,
  timeout = 30_000,
}) {
  let lastEvaluation = null
  try {
    await expect
      .poll(async () => {
        const probe = await collectHardQueryProbe(page, scenario, { snapshotForPage, pendingApprovalsForPage })
        lastEvaluation = evaluateHardQueryProbe(probe)
        return lastEvaluation.ok ? PASS : JSON.stringify(lastEvaluation.hardQuery, null, 2)
      }, {
        timeout,
        message: `Hard query scenario ${scenario.id} did not converge`,
      })
      .toBe(PASS)
  } catch (error) {
    const payload = {
      ...(lastEvaluation?.semanticProbe || {}),
      hardQuery: lastEvaluation?.hardQuery || { scenarioId: scenario.id, violations: [String(error?.message || error)] },
    }
    await attachHardQueryArtifact(testInfo, scenario, payload)
    throw new Error(
      `Hard query oracle failed for ${scenario.id}: ${scenario.prompt}\n` +
      `${(lastEvaluation?.hardQuery?.violations || [String(error?.message || error)]).join('\n')}\n` +
      `Semantic probe JSON:\n${serializeSemanticProbe(payload)}`,
    )
  }
  return lastEvaluation
}

export const hardQueryOracleInternalsForTest = Object.freeze({
  evaluateHardQueryProbe,
  fieldsFromArg,
  visibleBlockMatches,
  stepMatches,
})
