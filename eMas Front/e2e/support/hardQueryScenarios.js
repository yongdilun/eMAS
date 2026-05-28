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
    id: 'HQ-REQUIREMENT-EXPANSION-CONDITION-TRUE',
    tags: ['hard query', 'requirement-expansion', 'conditional branch', 'response_document'],
    prompt: 'Read job JOB-SEED-001. If the job result includes a product id, read that product. Summarize the result.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      minStepCount: 2,
      maxStepCount: 3,
      stepSequence: [
        {
          toolName: 'get__jobs_{id}',
          args: {
            id: 'JOB-SEED-001',
          },
        },
        {
          toolName: 'get__products_{id}',
          args: {
            id: 'P-001',
          },
        },
      ],
      toolNames: ['get__jobs_{id}', 'get__products_{id}'],
      noMutation: true,
      conditionalBranches: [
        {
          status: 'activated',
          conditionType: 'active_parent_evidence_has_any_field',
          fieldAny: ['product_id', 'active_product_id'],
        },
      ],
      requirementExpansion: {
        requireChildLineage: true,
        parentRequirementId: 'req-001',
        childEntity: 'product',
        childConstraintKey: 'product_id',
        childConstraintValue: 'P-001',
        requireFreshChildRetrieval: true,
        childToolNames: ['get__products_{id}'],
        parentToolNames: ['get__jobs_{id}'],
        forbidParentToolExecutableReuse: true,
        requireFinalParentAndChildEvidence: true,
        forbidStaleFinalEvidence: true,
      },
      responseDocument: {
        blockTypes: ['record_preview'],
        hiddenBlockTypes: ['result_table', 'diagnostic', 'approval_required'],
        blocks: [
          {
            type: 'record_preview',
            readScope: 'records',
            entityType: 'job',
            displayMode: 'record_preview',
          },
          {
            type: 'record_preview',
            readScope: 'records',
            entityType: 'product',
            displayMode: 'record_preview',
          },
        ],
      },
      visibleSemanticBlocks: [
        {
          type: 'record_preview',
          readScope: 'records',
          displayMode: 'record_preview',
          entityType: 'job',
        },
        {
          type: 'record_preview',
          readScope: 'records',
          displayMode: 'record_preview',
          entityType: 'product',
          title: /Read product status/i,
          textIncludes: [/P-001/i, /Status\s+active/i],
          forbiddenText: [/Read product status\s+active/i],
        },
      ],
      visibleTextIncludes: [
        { label: 'conditional relationship summary', pattern: /Job\s+JOB-SEED-001\s+included\s+product\s+id\s+P-001/i },
        { label: 'product status summary', pattern: /Product\s+P-001\s+is\s+active/i },
      ],
      forbiddenVisibleText: [
        { label: 'shallow mixed-read counter', pattern: /Found\s+1\s+job\.\s+Found\s+1\s+product/i },
        { label: 'attention state', pattern: /Run needs attention/i },
        { label: 'raw JSON', pattern: /["'](?:error|traceback|requirement_ledger)["']\s*:/i },
      ],
    },
  },
  {
    id: 'HQ-REQUIREMENT-EXPANSION-CONDITION-FALSE',
    tags: ['hard query', 'requirement-expansion', 'conditional branch', 'response_document'],
    prompt: 'Read job JOB-SEED-001. If the job result includes a machine id, read that machine. Summarize the result.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      minStepCount: 1,
      maxStepCount: 2,
      stepSequence: [
        {
          toolName: 'get__jobs_{id}',
          args: {
            id: 'JOB-SEED-001',
          },
        },
      ],
      forbiddenStepSequence: [
        {
          toolName: 'get__machines_{id}',
        },
      ],
      toolNames: ['get__jobs_{id}'],
      noMutation: true,
      conditionalBranches: [
        {
          status: 'skipped',
          skippedReason: 'conditional_branch_not_triggered',
          conditionType: 'active_parent_evidence_has_any_field',
          fieldAny: ['machine_id', 'active_machine_id'],
        },
      ],
      requirementExpansion: {
        expectNoChildLineage: true,
      },
      responseDocument: {
        blockTypes: ['record_preview'],
        hiddenBlockTypes: ['result_table', 'diagnostic', 'approval_required'],
        blocks: [
          {
            type: 'record_preview',
            readScope: 'records',
            entityType: 'job',
            displayMode: 'record_preview',
          },
        ],
      },
      visibleSemanticBlocks: [
        {
          type: 'record_preview',
          readScope: 'records',
          displayMode: 'record_preview',
          entityType: 'job',
        },
      ],
      visibleTextIncludes: [
        { label: 'job answer', pattern: /Job\s+JOB-SEED-001/i },
        { label: 'missing machine id answer', pattern: /No\s+machine\s+id/i },
      ],
      forbiddenVisibleText: [
        { label: 'machine read result', pattern: /Machine\s+M-/i },
        { label: 'attention state', pattern: /Run needs attention/i },
        { label: 'raw JSON', pattern: /["'](?:error|traceback|requirement_ledger)["']\s*:/i },
      ],
    },
  },
  {
    id: 'HQ-REQUIREMENT-EXPANSION-FOR-EACH-PRODUCT',
    tags: ['hard query', 'requirement-expansion', 'conditional branch', 'for-each', 'response_document'],
    prompt: 'Read jobs JOB-SEED-001 and JOB-SEED-002. For each job that includes a product id, read that product. Summarize each job with its product.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      minStepCount: 3,
      maxStepCount: 5,
      stepSequence: [
        {
          toolName: 'get__jobs_{id}',
          args: {
            id: 'JOB-SEED-001',
          },
        },
        {
          toolName: 'get__jobs_{id}',
          args: {
            id: 'JOB-SEED-002',
          },
        },
        {
          toolName: 'get__products_{id}',
          args: {
            id: 'P-001',
          },
        },
        {
          toolName: 'get__products_{id}',
          args: {
            id: 'P-002',
          },
        },
      ],
      forbiddenStepSequence: [
        {
          toolName: 'get__jobs',
          emptyArgs: true,
        },
        {
          toolName: 'get__products',
          emptyArgs: true,
        },
      ],
      toolNames: ['get__jobs_{id}', 'get__products_{id}'],
      noMutation: true,
      conditionalBranches: [
        {
          status: 'activated',
          conditionType: 'active_parent_evidence_has_any_field',
          fieldAny: ['product_id', 'active_product_id'],
          activatedChildCount: 2,
          triggerValues: ['P-001', 'P-002'],
        },
      ],
      requirementExpansion: {
        requireChildLineage: true,
        requireChildCount: 2,
        parentRequirementId: 'req-001',
        childEntity: 'product',
        childConstraintKey: 'product_id',
        childConstraintValues: ['P-001', 'P-002'],
        requireFreshChildRetrieval: true,
        childToolNames: ['get__products_{id}'],
        parentToolNames: ['get__jobs_{id}'],
        forbidParentToolExecutableReuse: true,
        requireFinalParentAndChildEvidence: true,
        forbidStaleFinalEvidence: true,
      },
      responseDocument: {
        blockTypes: ['record_preview'],
        hiddenBlockTypes: ['diagnostic', 'approval_required'],
        minReadRunSteps: 3,
      },
      visibleSemanticBlocks: [
        {
          type: 'record_preview',
          readScope: 'records',
          displayMode: 'record_preview',
          entityType: 'job',
          textIncludes: [/JOB-SEED-001/i, /P-001/i],
        },
        {
          type: 'record_preview',
          readScope: 'records',
          displayMode: 'record_preview',
          entityType: 'job',
          textIncludes: [/JOB-SEED-002/i, /P-002/i],
        },
        {
          type: 'record_preview',
          readScope: 'records',
          displayMode: 'record_preview',
          entityType: 'product',
          textIncludes: [/P-001/i, /Status\s+active/i],
        },
        {
          type: 'record_preview',
          readScope: 'records',
          displayMode: 'record_preview',
          entityType: 'product',
          textIncludes: [/P-002/i, /Status\s+active/i],
        },
      ],
      visibleTextIncludes: [
        { label: 'first job product summary', pattern: /Job\s+JOB-SEED-001\s+included\s+product\s+id\s+P-001/i },
        { label: 'second job product summary', pattern: /Job\s+JOB-SEED-002\s+included\s+product\s+id\s+P-002/i },
        { label: 'first product status summary', pattern: /Product\s+P-001\s+is\s+active/i },
        { label: 'second product status summary', pattern: /Product\s+P-002\s+is\s+active/i },
      ],
      forbiddenVisibleText: [
        { label: 'attention state', pattern: /Run needs attention/i },
        { label: 'fake id constraint', pattern: /\bproduct\s+id\s+ID\b/i },
        { label: 'raw JSON', pattern: /["'](?:error|traceback|requirement_ledger)["']\s*:/i },
      ],
    },
  },
  {
    id: 'HQ-SEMANTIC-INTAKE-CONDITIONAL-FALSE',
    tags: ['hard query', 'semantic-intake', 'conditional branch', 'response_document'],
    prompt: 'Check machine M-CNC-01 status. If the machine result includes a job id, read that job and explain the cause.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      minStepCount: 1,
      maxStepCount: 2,
      stepSequence: [
        {
          toolName: 'get__machines_{id}',
          args: {
            id: 'M-CNC-01',
            fields: ['status', 'job_id', 'active_job_id'],
          },
        },
      ],
      forbiddenStepSequence: [
        {
          toolName: 'get__jobs',
          emptyArgs: true,
        },
        {
          toolName: 'get__jobs_{id}',
        },
        {
          toolName: 'get__settings_get',
        },
      ],
      toolNames: ['get__machines_{id}'],
      noMutation: true,
      conditionalBranches: [
        {
          status: 'skipped',
          skippedReason: 'conditional_branch_not_triggered',
          conditionType: 'active_parent_evidence_has_any_field',
          fieldAny: ['job_id', 'active_job_id'],
        },
      ],
      requirementExpansion: {
        expectNoChildLineage: true,
      },
      responseDocument: {
        contracts: ['entity_status_v1'],
        blockTypes: ['status_result'],
        hiddenBlockTypes: ['result_table', 'diagnostic', 'approval_required'],
        blocks: [
          {
            type: 'status_result',
            contract: 'entity_status_v1',
            entityType: 'machine',
            displayMode: 'compact_status_card',
          },
        ],
      },
      visibleSemanticBlocks: [
        {
          type: 'status_result',
          contract: 'entity_status_v1',
          entityType: 'machine',
          displayMode: 'compact_status_card',
          statusFieldKeys: ['machine_id', 'status'],
        },
      ],
      visibleTextIncludes: [
        { label: 'machine running answer', pattern: /Machine\s+M-CNC-01\s+is\s+running/i },
        { label: 'conditional no job explanation', pattern: /No\s+job\s+id/i },
      ],
      forbiddenVisibleText: [
        { label: 'broad jobs result', pattern: /Found\s+\d+\s+jobs/i },
        { label: 'settings lookup failure', pattern: /settings|404/i },
        { label: 'raw planner no action', pattern: /planner_no_action/i },
        { label: 'request start failure', pattern: /Request could not start/i },
      ],
    },
  },
  {
    id: 'HQ-SEMANTIC-INTAKE-CONDITIONAL-TRUE',
    tags: ['hard query', 'semantic-intake', 'conditional branch', 'response_document'],
    prompt: 'Read job JOB-SEED-001. If it has a product, read that product too and summarize both.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      minStepCount: 2,
      maxStepCount: 3,
      stepSequence: [
        {
          toolName: 'get__jobs_{id}',
          args: {
            id: 'JOB-SEED-001',
          },
        },
        {
          toolName: 'get__products_{id}',
          args: {
            id: 'P-001',
          },
        },
      ],
      forbiddenStepSequence: [
        {
          toolName: 'get__products',
          emptyArgs: true,
        },
      ],
      toolNames: ['get__jobs_{id}', 'get__products_{id}'],
      noMutation: true,
      conditionalBranches: [
        {
          status: 'activated',
          conditionType: 'active_parent_evidence_has_any_field',
          fieldAny: ['product_id', 'active_product_id'],
          activatedChildCount: 1,
          triggerValues: ['P-001'],
        },
      ],
      requirementExpansion: {
        requireChildLineage: true,
        parentRequirementId: 'req-001',
        childEntity: 'product',
        childConstraintKey: 'product_id',
        childConstraintValue: 'P-001',
        requireFreshChildRetrieval: true,
        childToolNames: ['get__products_{id}'],
        parentToolNames: ['get__jobs_{id}'],
        forbidParentToolExecutableReuse: true,
        requireFinalParentAndChildEvidence: true,
        forbidStaleFinalEvidence: true,
      },
      responseDocument: {
        blockTypes: ['record_preview'],
        hiddenBlockTypes: ['result_table', 'diagnostic', 'approval_required'],
        blocks: [
          {
            type: 'record_preview',
            readScope: 'records',
            entityType: 'job',
            displayMode: 'record_preview',
          },
          {
            type: 'record_preview',
            readScope: 'records',
            entityType: 'product',
            displayMode: 'record_preview',
          },
        ],
      },
      visibleSemanticBlocks: [
        {
          type: 'record_preview',
          readScope: 'records',
          displayMode: 'record_preview',
          entityType: 'job',
        },
        {
          type: 'record_preview',
          readScope: 'records',
          displayMode: 'record_preview',
          entityType: 'product',
          title: /Read product status/i,
          textIncludes: [/P-001/i, /Status\s+active/i],
        },
      ],
      visibleTextIncludes: [
        { label: 'job product referent summary', pattern: /Job\s+JOB-SEED-001\s+included\s+product\s+id\s+P-001/i },
        { label: 'product answer', pattern: /Product\s+P-001\s+is\s+active/i },
      ],
      forbiddenVisibleText: [
        { label: 'attention state', pattern: /Run needs attention/i },
        { label: 'raw JSON', pattern: /["'](?:error|traceback|requirement_ledger)["']\s*:/i },
      ],
    },
  },
  {
    id: 'HQ-SEMANTIC-INTAKE-ANSWER-INSTRUCTION',
    tags: ['hard query', 'semantic-intake', 'answer instruction', 'response_document'],
    prompt: 'Show machine M-CNC-01 status and explain what it means.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      minStepCount: 1,
      maxStepCount: 2,
      stepSequence: [
        {
          toolName: 'get__machines_{id}',
          args: {
            id: 'M-CNC-01',
            fields: ['status'],
          },
        },
      ],
      forbiddenStepSequence: [
        {
          toolName: 'get__settings_get',
        },
      ],
      toolNames: ['get__machines_{id}'],
      noMutation: true,
      responseDocument: {
        contracts: ['entity_status_v1'],
        blockTypes: ['status_result'],
        hiddenBlockTypes: ['result_table', 'diagnostic', 'approval_required'],
        blocks: [
          {
            type: 'status_result',
            contract: 'entity_status_v1',
            entityType: 'machine',
            displayMode: 'compact_status_card',
          },
        ],
      },
      visibleSemanticBlocks: [
        {
          type: 'status_result',
          contract: 'entity_status_v1',
          entityType: 'machine',
          displayMode: 'compact_status_card',
          statusFieldKeys: ['machine_id', 'status'],
        },
      ],
      visibleTextIncludes: [
        { label: 'machine status answer', pattern: /Machine\s+M-CNC-01\s+is\s+running/i },
      ],
      forbiddenVisibleText: [
        { label: 'settings lookup failure', pattern: /settings|404/i },
        { label: 'request start failure', pattern: /Request could not start/i },
      ],
    },
  },
  {
    id: 'HQ-SEMANTIC-INTAKE-DEPENDENT-IF-PRESENT',
    tags: ['hard query', 'semantic-intake', 'conditional branch', 'dependent referent', 'response_document'],
    prompt: 'Check job JOB-SEED-001 then explain its product if present.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      minStepCount: 2,
      maxStepCount: 3,
      stepSequence: [
        {
          toolName: 'get__jobs_{id}',
          args: {
            id: 'JOB-SEED-001',
          },
        },
        {
          toolName: 'get__products_{id}',
          args: {
            id: 'P-001',
          },
        },
      ],
      forbiddenStepSequence: [
        {
          toolName: 'get__products',
          emptyArgs: true,
        },
      ],
      toolNames: ['get__jobs_{id}', 'get__products_{id}'],
      noMutation: true,
      conditionalBranches: [
        {
          status: 'activated',
          conditionType: 'active_parent_evidence_has_any_field',
          fieldAny: ['product_id', 'active_product_id'],
          activatedChildCount: 1,
          triggerValues: ['P-001'],
        },
      ],
      requirementExpansion: {
        requireChildLineage: true,
        parentRequirementId: 'req-001',
        childEntity: 'product',
        childConstraintKey: 'product_id',
        childConstraintValue: 'P-001',
        requireFreshChildRetrieval: true,
        childToolNames: ['get__products_{id}'],
        parentToolNames: ['get__jobs_{id}'],
        forbidParentToolExecutableReuse: true,
        requireFinalParentAndChildEvidence: true,
        forbidStaleFinalEvidence: true,
      },
      responseDocument: {
        blockTypes: ['record_preview'],
        hiddenBlockTypes: ['result_table', 'diagnostic', 'approval_required'],
        blocks: [
          {
            type: 'record_preview',
            readScope: 'records',
            entityType: 'job',
            displayMode: 'record_preview',
          },
          {
            type: 'record_preview',
            readScope: 'records',
            entityType: 'product',
            displayMode: 'record_preview',
          },
        ],
      },
      visibleSemanticBlocks: [
        {
          type: 'record_preview',
          readScope: 'records',
          displayMode: 'record_preview',
          entityType: 'job',
        },
        {
          type: 'record_preview',
          readScope: 'records',
          displayMode: 'record_preview',
          entityType: 'product',
          title: /Read product status/i,
          textIncludes: [/P-001/i, /Status\s+active/i],
        },
      ],
      visibleTextIncludes: [
        { label: 'job product referent summary', pattern: /Job\s+JOB-SEED-001\s+included\s+product\s+id\s+P-001/i },
        { label: 'product answer', pattern: /Product\s+P-001\s+is\s+active/i },
      ],
      forbiddenVisibleText: [
        { label: 'attention state', pattern: /Run needs attention/i },
        { label: 'fake product id if', pattern: /\bproduct\s+id\s+IF\b/i },
        { label: 'broad product result', pattern: /Found\s+\d+\s+products/i },
        { label: 'raw JSON', pattern: /["'](?:error|traceback|requirement_ledger)["']\s*:/i },
      ],
      forbiddenBackendText: [
        { label: 'fake product id if', pattern: /\bproduct_id["']?\s*[:=]\s*["']?IF\b/i },
      ],
    },
  },
  {
    id: 'HQ-DEPENDENCY-INDEPENDENT-READ-BATCH',
    tags: ['hard query', 'dependency execution', 'parallel read batch', 'response_document'],
    prompt: 'Show status for machine M-CNC-01 and job JOB-SEED-001.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      minStepCount: 2,
      maxStepCount: 3,
      stepSequence: [
        { toolName: 'get__machines_{id}', args: { id: 'M-CNC-01', fields: ['status'] } },
        { toolName: 'get__jobs_{id}', args: { id: 'JOB-SEED-001', fields: ['status'] } },
      ],
      toolNames: ['get__machines_{id}', 'get__jobs_{id}'],
      dependencyPlan: {
        historyLabels: [
          { label: 'independent_read', minSnapshots: 1 },
        ],
        finalLabels: [
          { label: 'satisfied_or_terminal', minCount: 2 },
        ],
        readyGroup: {
          mode: 'parallel_read_batch',
          batchKey: 'read:operational_state:bounded_single_entity_api',
          minRequirementCount: 2,
          maxBatchSize: 3,
        },
        parallelBatch: {
          minCalls: 2,
          maxCalls: 3,
          readOnlyApiOnly: true,
          sameSourceOfTruth: 'operational_state',
        },
      },
      responseDocument: {
        hiddenBlockTypes: ['approval_required', 'mutation_result', 'diagnostic'],
      },
      visibleSemanticBlocks: [
        { type: 'status_result', contract: 'entity_status_v1', entityType: 'machine' },
        { type: 'status_result', contract: 'entity_status_v1', entityType: 'job' },
      ],
      noMutation: true,
      forbiddenVisibleText: [
        { label: 'approval card on read batch', pattern: /Approval required/i },
        { label: 'fake sequential warning', pattern: /dependency.*not.*ready/i },
      ],
    },
  },
  {
    id: 'HQ-DEPENDENCY-CONDITIONAL-CHILD-WAITS',
    tags: ['hard query', 'dependency execution', 'conditional branch', 'response_document'],
    prompt: 'Read job JOB-SEED-001. If it has a product id, read that product. Summarize both.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      minStepCount: 2,
      maxStepCount: 3,
      stepSequence: [
        { toolName: 'get__jobs_{id}', args: { id: 'JOB-SEED-001' } },
        { toolName: 'get__products_{id}', args: { id: 'P-001' } },
      ],
      forbiddenStepSequence: [
        { toolName: 'get__products', emptyArgs: true },
      ],
      toolNames: ['get__jobs_{id}', 'get__products_{id}'],
      conditionalBranches: [
        {
          status: 'activated',
          conditionType: 'active_parent_evidence_has_any_field',
          fieldAny: ['product_id', 'active_product_id'],
          activatedChildCount: 1,
          triggerValues: ['P-001'],
        },
      ],
      requirementExpansion: {
        requireChildLineage: true,
        childEntity: 'product',
        childConstraintKey: 'product_id',
        childConstraintValue: 'P-001',
        requireFreshChildRetrieval: true,
        childToolNames: ['get__products_{id}'],
        parentToolNames: ['get__jobs_{id}'],
        forbidParentToolExecutableReuse: true,
        requireFinalParentAndChildEvidence: true,
        forbidStaleFinalEvidence: true,
      },
      dependencyPlan: {
        historyLabels: [
          { label: 'independent_read', minSnapshots: 1 },
        ],
        childWaitsForParent: true,
      },
      responseDocument: {
        blockTypes: ['record_preview'],
        hiddenBlockTypes: ['result_table', 'diagnostic', 'approval_required'],
      },
      visibleSemanticBlocks: [
        { type: 'record_preview', entityType: 'job', textIncludes: [/JOB-SEED-001/i, /P-001/i] },
        { type: 'record_preview', entityType: 'product', textIncludes: [/P-001/i, /Status\s+active/i] },
      ],
      visibleTextIncludes: [
        { label: 'job product summary', pattern: /Job\s+JOB-SEED-001\s+included\s+product\s+id\s+P-001/i },
        { label: 'product status summary', pattern: /Product\s+P-001\s+is\s+active/i },
      ],
      noMutation: true,
      forbiddenVisibleText: [
        { label: 'broad product result', pattern: /Found\s+\d+\s+products/i },
        { label: 'fake product id', pattern: /\bproduct\s+id\s+ID\b/i },
      ],
    },
  },
  {
    id: 'HQ-DEPENDENCY-APPROVAL-WAITS-FOR-READ',
    tags: ['hard query', 'dependency execution', 'approval branch', 'response_document'],
    prompt: 'List medium priority jobs, then change those jobs to high priority. Show what would change and ask approval before applying.',
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
      dependencyPlan: {
        historyLabels: [
          { label: 'sequential_read', minSnapshots: 1 },
          { label: 'approval_required', minSnapshots: 1 },
        ],
        approvalWaitsForRead: true,
      },
      lockedConstraints: {
        priority: 'medium',
        new_priority: 'high',
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
        hiddenBlockTypes: ['mutation_result'],
      },
      visibleSemanticBlocks: [
        {
          type: 'approval_required',
          contract: 'business_change_v1',
          detailsCollapsed: true,
          forbiddenTableColumnKeys: ['operation_id', 'step_id', 'row_id'],
        },
      ],
      forbiddenVisibleText: [
        { label: 'mutation success before approval', pattern: /Run complete|updated successfully|applied/i },
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
    id: 'HQ-REPLAN-SPINE-RECOVERY',
    tags: ['hard query', 'replan-spine', 'bounded recovery', 'response_document'],
    toolFaults: {
      rules: [
        {
          method: 'GET',
          endpoint: '/jobs',
          fault: 'timeout',
          once: true,
          reason: 'Controlled one-time job list timeout for replan recovery proof.',
        },
      ],
    },
    prompt: 'List low priority jobs, only job id and deadline, sorted by deadline ascending, limit 3.',
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      approvalCount: 0,
      noMutation: true,
      replanSpine: {
        minAttempts: 1,
        limitReached: false,
        requiresMissingEvidenceReason: true,
        missingEvidenceReason: 'tool_error',
        requiresFailedToolMemory: true,
        failedToolReason: 'tool_error',
        requiresStaleAttemptEvidence: true,
        requiresHistoricalEvidence: true,
        requiresActiveFinalEvidence: true,
        activeFinalEvidenceInResponse: true,
        forbidStaleFinalEvidence: true,
      },
      responseDocument: {
        blockTypes: ['result_table'],
        hiddenBlockTypes: ['diagnostic', 'status_result', 'approval_required'],
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
      visibleRunSteps: [
        { title: /Running selected tool/i },
        { title: /Checking evidence/i },
        { title: /Replanning after timeout/i },
        { title: /Retrying .+ read/i },
        { title: /Checking new evidence/i },
        { title: /Run complete/i },
      ],
      visibleUiTextIncludes: [
        { label: 'first visible retry attempt number', pattern: /Attempt\s+1\s+of\s+\d+/i },
        { label: 'second visible retry attempt number', pattern: /Attempt\s+2\s+of\s+\d+/i },
        { label: 'visible timeout retry reason', pattern: /Previous read timed out/i },
      ],
      forbiddenVisibleText: [
        { label: 'safe failure text after recovery', pattern: /could not verify the requested evidence after bounded retries/i },
        { label: 'approval required for read recovery', pattern: /Approval required/i },
        { label: 'unrequested status column after retry', pattern: /\bStatus\b/i },
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
        { label: 'bounded timeout safe terminal diagnostic', pattern: /could not verify the requested evidence after bounded retries/i },
      ],
      visibleUiTextIncludes: [
        { label: 'safe failure shell status', pattern: /Needs attention/i },
        { label: 'safe failure response title', pattern: /Run needs attention/i },
        { label: 'safe failure evidence explanation', pattern: /could not verify the requested evidence after bounded retries/i },
        { label: 'safe failure final attempt count', pattern: /Attempt\s+\d+\s+of\s+\d+/i },
        { label: 'safe failure timeout retry reason', pattern: /Previous read timed out/i },
        { label: 'safe failure collapsed retry summary', pattern: /earlier attempts collapsed/i },
      ],
      forbiddenVisibleText: [
        { label: 'misleading request start failure', pattern: /Request could not start/i },
        { label: 'technical planner code as primary text', pattern: /planner_no_action/i },
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
        { label: 'misleading request start failure', pattern: /Request could not start/i },
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
        { label: 'bounded safe terminal diagnostic', pattern: /could not verify the requested evidence after bounded retries/i },
      ],
      visibleUiTextIncludes: [
        { label: 'safe failure shell status', pattern: /Needs attention/i },
        { label: 'safe failure response title', pattern: /Run needs attention/i },
        { label: 'safe failure evidence explanation', pattern: /could not verify the requested evidence after bounded retries/i },
        { label: 'safe failure final attempt count', pattern: /Attempt\s+\d+\s+of\s+\d+/i },
        { label: 'safe failure collapsed retry summary', pattern: /earlier attempts collapsed/i },
      ],
      forbiddenVisibleText: [
        { label: 'misleading request start failure', pattern: /Request could not start/i },
        { label: 'technical planner code as primary text', pattern: /planner_no_action/i },
        { label: 'fake machine status after bounded failure', pattern: /Machine M-CNC-01 is|Status\s+Running|CNC Mill 01/i },
        { label: 'approval required for read failure', pattern: /Approval required/i },
        { label: 'fake success text', pattern: /Run complete/i },
      ],
      forbiddenUiText: [
        { label: 'misleading startup failure banner', pattern: /Factory Agent chat could not start/i },
        { label: 'misleading start retry action', pattern: /Try starting chat again/i },
        { label: 'misleading request start failure', pattern: /Request could not start/i },
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
