export const HARD_QUERY_FORBIDDEN_RUNTIME_PATTERNS = Object.freeze([
  { label: 'planner recursion limit', pattern: /recursion limit|GraphRecursionError/i },
  { label: 'planner loop diagnostic', pattern: /\b(?:tool|planner|decision)\s+loop\b/i },
  { label: 'stale completion marker', pattern: /stale completion|non_terminal_snapshot/i },
  { label: 'raw assistant success markdown', pattern: /\*\*Success\*\*/i },
  { label: 'raw assistant done_all marker', pattern: /(?:^|\s)done_all(?:\s|$)/i },
  { label: 'fake success text', pattern: /fake success|pretend(?:ed)? success/i },
])

export const hardQueryScenarios = Object.freeze([
  {
    id: 'HQ-01',
    tags: ['hard query', 'status-only', 'response_document'],
    prompt: 'Show status for machine M-CNC-01 only. Do not show other machine details.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      maxStepCount: 3,
      stepSequence: [
        {
          toolName: 'get__machines_{id}',
          args: {
            id: 'M-CNC-01',
            fields: ['status'],
          },
        },
      ],
      toolNames: ['get__machines_{id}'],
      noMutation: true,
      responseDocument: {
        contracts: ['entity_status_v1'],
        blockTypes: ['status_result'],
        blocks: [
          {
            type: 'status_result',
            contract: 'entity_status_v1',
            readScope: 'status_only',
            requestedFields: ['machine_id', 'status'],
            displayMode: 'compact_status_card',
            entityType: 'machine',
            entityCount: 1,
          },
        ],
      },
      visibleSemanticBlocks: [
        {
          type: 'status_result',
          contract: 'entity_status_v1',
          readScope: 'status_only',
          requestedFields: ['machine_id', 'status'],
          displayMode: 'compact_status_card',
          entityType: 'machine',
          statusFieldKeys: ['machine_id', 'status'],
          forbiddenStatusFieldKeys: [
            'machine_name',
            'machine_type',
            'location',
            'capacity_per_hour',
            'last_maintenance',
            'maintenance_interval',
          ],
        },
      ],
      forbiddenVisibleText: [
        { label: 'machine name label', pattern: /\bMachine name\b/i },
        { label: 'machine type label', pattern: /\bMachine type\b/i },
        { label: 'location label', pattern: /\bLocation\b/i },
        { label: 'capacity label', pattern: /\bCapacity per hour\b/i },
        { label: 'last maintenance label', pattern: /\bLast maintenance\b/i },
        { label: 'maintenance interval label', pattern: /\bMaintenance interval\b/i },
        { label: 'seeded machine name value', pattern: /\bCNC Mill 01\b/i },
        { label: 'seeded floor/location value', pattern: /\bFloor\s+[A-Z]\b/i },
      ],
      forbiddenBackendText: [
        { label: 'response document machine name label', pattern: /\bMachine name\b/i },
        { label: 'response document machine type label', pattern: /\bMachine type\b/i },
        { label: 'response document location label', pattern: /\bLocation\b/i },
        { label: 'response document capacity label', pattern: /\bCapacity per hour\b/i },
        { label: 'response document last maintenance label', pattern: /\bLast maintenance\b/i },
        { label: 'response document maintenance interval label', pattern: /\bMaintenance interval\b/i },
      ],
    },
  },
  {
    id: 'HQ-05',
    tags: ['hard query', 'job-list', 'response_document'],
    prompt: 'List low priority jobs, only job id and deadline, sorted by deadline ascending, limit 3.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      maxStepCount: 3,
      stepSequence: [
        {
          toolName: 'get__jobs',
          args: {
            priority: 'low',
            fields: ['job_id', 'deadline'],
            sort_by: 'deadline',
            sort_dir: 'asc',
            limit: 3,
          },
        },
      ],
      toolNames: ['get__jobs'],
      noMutation: true,
      responseDocument: {
        blockTypes: ['result_table'],
        blocks: [
          {
            type: 'result_table',
            readScope: 'records',
            requestedFields: ['job_id', 'deadline'],
            displayMode: 'collection_table',
            entityType: 'job',
            maxRows: 3,
            tableColumnKeys: ['job_id', 'deadline'],
          },
        ],
      },
      visibleSemanticBlocks: [
        {
          type: 'result_table',
          readScope: 'records',
          requestedFields: ['job_id', 'deadline'],
          displayMode: 'collection_table',
          entityType: 'job',
          maxRows: 3,
          tableColumnKeys: ['job_id', 'deadline'],
          forbiddenTableColumnKeys: ['priority', 'product_id', 'status', 'row_id', 'operation_id', 'tool_name'],
        },
      ],
      forbiddenVisibleText: [
        { label: 'product column label', pattern: /\bProduct\b/i },
        { label: 'status column label', pattern: /\bStatus\b/i },
      ],
    },
  },
  {
    id: 'HQ-3S-01',
    tags: ['hard query', 'multi-read', 'response_document'],
    prompt: 'Show M-CNC-01 status, then show JOB-SEED-001 status, then list the next 3 low priority jobs sorted by deadline.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      minStepCount: 3,
      maxStepCount: 6,
      stepSequence: [
        {
          toolName: 'get__machines_{id}',
          args: {
            id: 'M-CNC-01',
            fields: ['status'],
          },
        },
        {
          toolName: 'get__jobs_{id}',
          args: {
            id: 'JOB-SEED-001',
            fields: ['status'],
          },
        },
        {
          toolName: 'get__jobs',
          args: {
            priority: 'low',
            sort_by: 'deadline',
            sort_dir: 'asc',
            limit: 3,
            fields: ['job_id', 'deadline'],
          },
        },
      ],
      toolNames: ['get__machines_{id}', 'get__jobs_{id}', 'get__jobs'],
      noMutation: true,
      responseDocument: {
        minReadRunSteps: 3,
        blockTypes: ['status_result', 'result_table'],
        blocks: [
          {
            type: 'status_result',
            contract: 'entity_status_v1',
            entityType: 'machine',
            displayMode: 'compact_status_card',
          },
          {
            type: 'status_result',
            contract: 'entity_status_v1',
            entityType: 'job',
            displayMode: 'compact_status_card',
          },
          {
            type: 'result_table',
            entityType: 'job',
            readScope: 'records',
            requestedFields: ['job_id', 'deadline'],
            maxRows: 5,
          },
        ],
        hiddenBlockTypes: ['approval_required'],
      },
      visibleSemanticBlocks: [
        {
          type: 'status_result',
          contract: 'entity_status_v1',
          entityType: 'machine',
          displayMode: 'compact_status_card',
          statusFieldKeys: ['machine_id', 'status'],
        },
        {
          type: 'status_result',
          contract: 'entity_status_v1',
          entityType: 'job',
          displayMode: 'compact_status_card',
          statusFieldKeys: ['job_id', 'status'],
        },
        {
          type: 'result_table',
          entityType: 'job',
          readScope: 'records',
          requestedFields: ['job_id', 'deadline'],
          tableColumnKeys: ['job_id', 'deadline'],
          maxRows: 5,
        },
      ],
      visibleTextIncludes: [
        { label: 'machine status summary', pattern: /Machine\s+M-CNC-01\s+is/i },
        { label: 'job status summary', pattern: /Job\s+JOB-SEED-001\s+is/i },
        { label: 'low priority collection summary', pattern: /Found\s+3\s+low-priority\s+jobs/i },
        { label: 'deadline evidence', pattern: /Deadline/i },
      ],
      backendTextIncludes: [
        { label: 'job identity field', pattern: /job_id/i },
        { label: 'deadline field', pattern: /deadline/i },
      ],
      forbiddenVisibleText: [
        { label: 'approval required after read-only multi-step', pattern: /Approval required/i },
      ],
    },
  },
  {
    id: 'HQ-9-READ',
    tags: ['hard query', 'phase9', 'multi-step read', 'conditional branch', 'response_document'],
    prompt: 'Show M-CNC-01 status, show JOB-SEED-001 and JOB-SEED-002 status, then list the next 3 low-priority jobs sorted by deadline with only job id, status, priority, and deadline. If any listed job is blocked, explain why before suggesting any update.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      minStepCount: 4,
      maxStepCount: 7,
      plannerOwnedGraph: {
        engineVersion: 'v2',
        traceId: 'planner_owned_agent_graph',
        runtimeAdapter: 'planner_owned_graph_runtime',
        graphExecutionAuthority: true,
        nativeLangGraphCheckpointUsed: true,
        requiredEvidenceSourceTypes: ['api_tool'],
        allowedEvidenceSourceTypes: ['api_tool'],
      },
      capabilityNeeds: [
        { sourceOfTruth: 'operational_state', entity: 'machine', action: 'read_one' },
        { sourceOfTruth: 'operational_state', entity: 'job', action: 'read_one' },
        { sourceOfTruth: 'operational_state', entity: 'job', action: 'read_one' },
        { sourceOfTruth: 'operational_state', entity: 'job', action: 'list' },
      ],
      stepSequence: [
        { toolName: 'get__machines_{id}', args: { id: 'M-CNC-01', fields: ['status'] } },
        { toolName: 'get__jobs_{id}', args: { id: 'JOB-SEED-001', fields: ['status'] } },
        { toolName: 'get__jobs_{id}', args: { id: 'JOB-SEED-002', fields: ['status'] } },
        {
          toolName: 'get__jobs',
          args: {
            priority: 'low',
            fields: ['job_id', 'status', 'priority', 'deadline'],
            sort_by: 'deadline',
            sort_dir: 'asc',
            limit: 3,
          },
        },
      ],
      conditionalBranches: [
        {
          conditionField: 'status',
          conditionValue: 'blocked',
          requiredEvidence: 'typed_explanation',
          ordering: 'explain_before_suggestion',
        },
      ],
      responseDocument: {
        blockTypes: ['status_result', 'result_table'],
        blocks: [
          {
            type: 'result_table',
            readScope: 'records',
            requestedFields: ['job_id', 'status', 'priority', 'deadline'],
            displayMode: 'collection_table',
            entityType: 'job',
            maxRows: 3,
            tableColumnKeys: ['job_id', 'status', 'priority', 'deadline'],
          },
        ],
      },
      visibleSemanticBlocks: [
        {
          type: 'result_table',
          readScope: 'records',
          requestedFields: ['job_id', 'status', 'priority', 'deadline'],
          displayMode: 'collection_table',
          entityType: 'job',
          maxRows: 3,
          tableColumnKeys: ['job_id', 'status', 'priority', 'deadline'],
          forbiddenTableColumnKeys: ['blocked_reason', 'product_id', 'row_id', 'operation_id', 'tool_name'],
        },
      ],
      noMutation: true,
      forbiddenVisibleText: [
        { label: 'approval card on hard read', pattern: /Approval required/i },
        { label: 'unrequested blocked reason table column', pattern: /\bBlocked reason\b/i },
      ],
    },
  },
  {
    id: 'HQ-9-MULTI-ID',
    tags: ['hard query', 'phase9', 'multi-ID read', 'response_document'],
    prompt: 'Find status for job with job id JOB-SEED-001 and JOB-SEED-002.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      plannerOwnedGraph: {
        engineVersion: 'v2',
        traceId: 'planner_owned_agent_graph',
        runtimeAdapter: 'planner_owned_graph_runtime',
        graphExecutionAuthority: true,
        nativeLangGraphCheckpointUsed: true,
        requiredEvidenceSourceTypes: ['api_tool'],
        allowedEvidenceSourceTypes: ['api_tool'],
      },
      responseDocument: {
        blockTypes: ['result_table'],
        blocks: [
          {
            type: 'result_table',
            contract: 'entity_status_v1',
            readScope: 'status_only',
            requestedFields: ['job_id', 'status'],
            entityType: 'job',
            entityCount: 2,
            tableColumnKeys: ['job_id', 'status'],
          },
        ],
      },
      visibleSemanticBlocks: [
        {
          type: 'result_table',
          readScope: 'status_only',
          requestedFields: ['job_id', 'status'],
          entityType: 'job',
          entityCount: 2,
          tableColumnKeys: ['job_id', 'status'],
          forbiddenTableColumnKeys: ['priority', 'deadline', 'operation_id', 'tool_name'],
        },
      ],
      noMutation: true,
    },
  },
  {
    id: 'HQ-9-MIXED-RAG',
    tags: ['hard query', 'phase9', 'mixed API + RAG', 'source UX', 'response_document'],
    prompt: 'Show machine M-CNC-01 status and OSHA lockout/tagout reenergizing notification guidance as separate sections.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      plannerOwnedGraph: {
        engineVersion: 'v2',
        traceId: 'planner_owned_agent_graph',
        runtimeAdapter: 'planner_owned_graph_runtime',
        graphExecutionAuthority: true,
        nativeLangGraphCheckpointUsed: true,
        requiredEvidenceSourceTypes: ['api_tool', 'system_guard'],
        allowedEvidenceSourceTypes: ['api_tool', 'system_guard'],
      },
      capabilityNeeds: [
        { sourceOfTruth: 'operational_state', entity: 'machine', action: 'read_one' },
        { sourceOfTruth: 'document_knowledge', entity: 'policy', action: 'search_documents' },
      ],
      responseDocument: {
        contracts: ['entity_status_v1', 'knowledge_answer_v1', 'source_list_v1', 'source_locator_v1'],
        blockTypes: ['status_result', 'knowledge_answer', 'source_list'],
      },
      visibleSemanticBlocks: [
        { type: 'status_result', contract: 'entity_status_v1', entityType: 'machine', displayMode: 'compact_status_card' },
        { type: 'knowledge_answer', contract: 'knowledge_answer_v1' },
        { type: 'source_list', contract: 'source_list_v1' },
      ],
      sourceEvidence: {
        citationCountMin: 1,
        requiredSourceFields: ['source_id', 'doc_id', 'chunk_id', 'title', 'snippet'],
        pdfLocatorRequired: true,
      },
      noMutation: true,
    },
  },
  {
    id: 'HQ-9-RAG-INSUFFICIENT',
    tags: ['hard query', 'phase9', 'RAG insufficient context', 'source UX', 'response_document'],
    prompt: 'According to OSHA, what notification is required before starting lockout?',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      responseDocument: {
        contracts: ['knowledge_answer_v1', 'source_list_v1'],
        blockTypes: ['knowledge_answer', 'source_list'],
      },
      ragEvidence: {
        insufficientContext: true,
        citationCount: 0,
        fakeSourcesForbidden: ['loto_notification_requirement', 'LOTO Notification Requirements'],
        relatedSourcesChecked: true,
      },
      visibleSemanticBlocks: [
        { type: 'knowledge_answer', contract: 'knowledge_answer_v1' },
        { type: 'source_list', contract: 'source_list_v1' },
      ],
      noMutation: true,
      forbiddenVisibleText: [
        { label: 'fake policy source id', pattern: /loto_notification_requirement/i },
        { label: 'fake policy source title', pattern: /LOTO Notification Requirements/i },
        { label: 'unsupported factual answer', pattern: /affected employees must be notified before lockout starts/i },
      ],
    },
  },
  {
    id: 'HQ-9-APPROVAL',
    tags: ['hard query', 'phase9', 'approval branch', 'write preview', 'response_document'],
    prompt: 'Change all high-priority jobs due this week to medium, but do not update blocked jobs. Show what would change and ask approval before applying.',
    expected: {
      sessionStatus: 'WAITING_APPROVAL',
      responseState: 'waiting_approval',
      approvalCount: 1,
      plannerOwnedGraph: {
        engineVersion: 'v2',
        traceId: 'planner_owned_agent_graph',
        runtimeAdapter: 'planner_owned_graph_runtime',
        graphExecutionAuthority: true,
        nativeLangGraphCheckpointUsed: true,
      },
      lockedConstraints: {
        priority: 'high',
        new_priority: 'medium',
        date: 'this week',
        excludes: ['blocked'],
        requires_approval: true,
      },
      mutationPolicy: {
        commitBeforeApproval: false,
        stagedPayloadRequired: true,
        blockedRowsExcluded: true,
      },
      responseDocument: {
        contracts: ['business_change_v1'],
        blockTypes: ['approval_required', 'record_preview', 'result_table'],
      },
      visibleSemanticBlocks: [
        {
          type: 'approval_required',
          contract: 'business_change_v1',
          detailsCollapsed: true,
          forbiddenTableColumnKeys: ['operation_id', 'step_id', 'row_id'],
        },
      ],
    },
  },
  {
    id: 'HQ-9-INTERRUPT',
    tags: ['hard query', 'phase9', 'user interruption', 'stale approval', 'response_document'],
    setup: {
      prompt: 'Change all high-priority jobs due this week to medium, but do not update blocked jobs. Show what would change and ask approval before applying.',
      waitFor: {
        sessionStatus: 'WAITING_APPROVAL',
        approvalCount: 1,
      },
    },
    prompt: 'Actually also exclude jobs missing a due date.',
    expected: {
      sessionStatus: 'WAITING_APPROVAL',
      responseState: 'waiting_approval',
      approvalCount: 1,
      interrupt: {
        type: 'modify_requirement',
        ledgerRevisionIncrements: true,
        staleApprovalInvalidated: true,
        staleEvidenceInvalidated: true,
      },
      responseDocument: {
        contracts: ['business_change_v1'],
        blockTypes: ['approval_required', 'record_preview', 'result_table'],
        hiddenBlockTypes: ['mutation_result'],
      },
      visibleSemanticBlocks: [
        { type: 'approval_required', contract: 'business_change_v1' },
      ],
      visibleRunSteps: [
        { title: /Approval 1 rejected/i },
        { title: /Waiting for approval 2/i },
      ],
      forbiddenVisibleText: [
        { label: 'stale final answer after interrupt', pattern: /Run complete/i },
        { label: 'stale approval still actionable', pattern: /Approved request to change/i },
      ],
    },
  },
  {
    id: 'HQ-REPLAN-SPINE-TIMEOUT-SAFE-FAILURE',
    tags: ['hard query', 'replan-spine', 'bounded timeout safe failure', 'response_document'],
    toolFaults: {
      rules: [
        {
          method: 'GET',
          fault: 'timeout',
          once: false,
          reason: 'Controlled repeated read timeout for replan limit proof.',
        },
      ],
    },
    prompt: 'Show status for machine M-CNC-01 only. Do not show other machine details.',
    expected: {
      sessionStatus: 'BLOCKED',
      responseState: 'blocked',
      approvalCount: 0,
      noMutation: true,
      replanSpine: {
        minAttempts: 1,
        attemptCountEqualsMaxAttempts: true,
        limitReached: true,
        requiresMissingEvidenceReason: true,
        missingEvidenceReason: 'tool_error',
        requiresFailedToolMemory: true,
        failedToolReason: 'tool_error',
        requiresStaleAttemptEvidence: true,
        requiresHistoricalEvidence: true,
        forbidActiveFinalEvidence: true,
        forbidStaleFinalEvidence: true,
        forbidResponseEvidenceRefs: true,
      },
      responseDocument: {
        blockTypes: ['diagnostic'],
        hiddenBlockTypes: ['status_result', 'result_table', 'approval_required'],
        blocks: [
          { type: 'diagnostic' },
        ],
      },
      visibleSemanticBlocks: [
        { type: 'diagnostic' },
      ],
      visibleTextIncludes: [
        { label: 'bounded timeout safe terminal diagnostic', pattern: /Request could not start|planner_no_action|blocked before execution|did not produce a safe plan/i },
      ],
      visibleUiTextIncludes: [
        { label: 'safe failure shell status', pattern: /Needs attention/i },
        { label: 'safe failure response title', pattern: /Request could not start|Run needs attention/i },
      ],
      forbiddenVisibleText: [
        { label: 'fake machine status after bounded timeout', pattern: /Machine M-CNC-01 is|Status\s+Running|CNC Mill 01/i },
        { label: 'approval required for read failure', pattern: /Approval required/i },
        { label: 'fake success text', pattern: /Run complete/i },
      ],
      forbiddenBackendText: [
        { label: 'stale failed read used as response evidence', pattern: /tool_failed.+response_evidence_refs/i },
      ],
      forbiddenUiText: [
        { label: 'misleading startup failure banner', pattern: /Factory Agent chat could not start/i },
        { label: 'misleading start retry action', pattern: /Try starting chat again/i },
        { label: 'raw backend error JSON', pattern: /["']errors["']\s*:/i },
      ],
    },
  },
  {
    id: 'HQ-REPLAN-SPINE-LIMIT-SAFE-FAILURE',
    tags: ['hard query', 'replan-spine', 'bounded safe failure', 'response_document'],
    toolFaults: {
      rules: [
        {
          method: 'GET',
          fault: 'http_error',
          once: false,
          reason: 'Controlled repeated read HTTP error for replan limit proof.',
        },
      ],
    },
    prompt: 'Show status for machine M-CNC-01 only. Do not show other machine details.',
    expected: {
      sessionStatus: 'BLOCKED',
      responseState: 'blocked',
      approvalCount: 0,
      noMutation: true,
      replanSpine: {
        minAttempts: 1,
        attemptCountEqualsMaxAttempts: true,
        limitReached: true,
        requiresMissingEvidenceReason: true,
        missingEvidenceReason: 'tool_error',
        requiresFailedToolMemory: true,
        failedToolReason: 'tool_error',
        requiresStaleAttemptEvidence: true,
        requiresHistoricalEvidence: true,
        forbidActiveFinalEvidence: true,
        forbidStaleFinalEvidence: true,
        forbidResponseEvidenceRefs: true,
      },
      responseDocument: {
        blockTypes: ['diagnostic'],
        hiddenBlockTypes: ['status_result', 'result_table', 'approval_required'],
        blocks: [
          { type: 'diagnostic' },
        ],
      },
      visibleSemanticBlocks: [
        { type: 'diagnostic' },
      ],
      visibleTextIncludes: [
        { label: 'bounded safe terminal diagnostic', pattern: /Request could not start|planner_no_action|blocked before execution|did not produce a safe plan/i },
      ],
      visibleUiTextIncludes: [
        { label: 'safe failure shell status', pattern: /Needs attention/i },
        { label: 'safe failure response title', pattern: /Request could not start|Run needs attention/i },
      ],
      forbiddenVisibleText: [
        { label: 'fake machine status after bounded failure', pattern: /Machine M-CNC-01 is|Status\s+Running|CNC Mill 01/i },
        { label: 'approval required for read failure', pattern: /Approval required/i },
        { label: 'fake success text', pattern: /Run complete/i },
      ],
      forbiddenUiText: [
        { label: 'misleading startup failure banner', pattern: /Factory Agent chat could not start/i },
        { label: 'misleading start retry action', pattern: /Try starting chat again/i },
        { label: 'raw backend error JSON', pattern: /["']errors["']\s*:/i },
      ],
    },
  },
  {
    id: 'HQ-9-TOOL-FAILURE',
    tags: ['hard query', 'phase9', 'tool failure fallback', 'response_document'],
    toolFaults: {
      rules: [
        {
          method: 'GET',
          endpoint: '/machines/{id}',
          fault: 'timeout',
          once: true,
          reason: 'Controlled Phase 9 upstream timeout for the machine status API.',
        },
      ],
    },
    prompt: 'Show machine M-CNC-01 status while the machine status API returns a typed upstream timeout.',
    expected: {
      sessionStatus: 'FAILED',
      responseState: 'failed',
      approvalCount: 0,
      toolFailure: {
        sourceType: 'api_tool',
        reason: 'tool_error',
        finalSuccessForbidden: true,
      },
      responseDocument: {
        blockTypes: ['diagnostic'],
        diagnosticReasonsAllowed: ['tool_timeout', 'tool_http_error', 'unknown_failure'],
      },
      visibleSemanticBlocks: [
        { type: 'diagnostic' },
      ],
      forbiddenVisibleText: [
        { label: 'fake machine status after failure', pattern: /M-CNC-01 is running/i },
        { label: 'fake success text', pattern: /Run complete/i },
      ],
    },
  },
])

export function hardQueryScenarioById(id) {
  return hardQueryScenarios.find((scenario) => scenario.id === id) || null
}
