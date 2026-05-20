export const normalUseTurns = [
  {
    key: 'machine-status',
    prompt: 'Phase 13 normal use turn 01: show current status for M-CNC-01',
    answer: 'Phase 13 turn 01: M-CNC-01 is running normally at 87% utilization with no active alarms.',
    plan: 'Checking the current operating state for M-CNC-01.',
    toolName: 'get_machine_status',
    args: { machine_id: 'M-CNC-01' },
    result: {
      machine_id: 'M-CNC-01',
      status: 'RUNNING',
      utilization: 87,
      alarms: [],
    },
  },
  {
    key: 'low-priority-jobs',
    prompt: 'Phase 13 normal use turn 02: list low priority jobs due soon',
    answer: 'Phase 13 turn 02: Found 3 low-priority jobs due soon: JOB-SEED-001, JOB-SEED-002, JOB-SEED-003.',
    plan: 'Listing low-priority jobs sorted by nearest due date.',
    toolName: 'list_jobs',
    args: { priority: 'low', sort_by: 'deadline', limit: 3 },
    result: {
      data: [
        { job_id: 'JOB-SEED-001', priority: 'low', status: 'planned', deadline: '2026-05-18' },
        { job_id: 'JOB-SEED-002', priority: 'low', status: 'delayed', deadline: '2026-05-19' },
        { job_id: 'JOB-SEED-003', priority: 'low', status: 'queued', deadline: '2026-05-20' },
      ],
    },
    presentation: {
      render_hint: 'table',
      table: {
        columns: [
          { key: 'job_id', label: 'Job' },
          { key: 'priority', label: 'Priority' },
          { key: 'status', label: 'Status' },
          { key: 'deadline', label: 'Deadline' },
        ],
        rows: [
          { job_id: 'JOB-SEED-001', priority: 'low', status: 'planned', deadline: '2026-05-18' },
          { job_id: 'JOB-SEED-002', priority: 'low', status: 'delayed', deadline: '2026-05-19' },
          { job_id: 'JOB-SEED-003', priority: 'low', status: 'queued', deadline: '2026-05-20' },
        ],
        displayed_rows: 3,
        total_rows: 3,
      },
    },
  },
  {
    key: 'loto-guidance',
    prompt: 'Phase 13 normal use turn 03: explain LOTO notification before lockout',
    answer:
      'Phase 13 turn 03: Notify affected operators, isolate hazardous energy, attach locks and tags, and verify zero energy before work begins. [^1]',
    plan: 'Answering a read-only LOTO procedure question with controlled source metadata.',
    toolName: 'rag_loto_lookup',
    args: { topic: 'loto-notification' },
    result: {
      doc_id: 'normal-use-loto-procedure',
      status: 'controlled_fixture',
    },
    sources: [
      {
        source_number: 1,
        doc_id: 'normal-use-loto-procedure',
        title: 'Normal Use LOTO Procedure',
        organization: 'eMas Safety',
        authority_level: 'controlled_test_fixture',
      },
    ],
    safetyContent: {
      title: 'Safety Advisory',
      content: 'Controlled Phase 13 fixture. Verify the site procedure before acting.',
    },
  },
  {
    key: 'highest-risk-job',
    prompt: 'Phase 13 normal use turn 04: follow up with the highest risk job from that list',
    answer:
      'Phase 13 turn 04: JOB-SEED-002 carries the highest schedule risk because it is delayed and depends on M-CNC-01.',
    plan: 'Reviewing the previous job list shape without relying on long-term memory features.',
    toolName: 'rank_job_risk',
    args: { candidates: ['JOB-SEED-001', 'JOB-SEED-002', 'JOB-SEED-003'] },
    result: {
      job_id: 'JOB-SEED-002',
      risk: 'highest',
      reason: 'delayed and machine-dependent',
    },
  },
  {
    key: 'maintenance-window',
    prompt: 'Phase 13 normal use turn 05: when is the next maintenance window for M-CNC-01',
    answer: 'Phase 13 turn 05: The next preventive maintenance window for M-CNC-01 is Friday at 14:00.',
    plan: 'Checking the next preventive maintenance window.',
    toolName: 'get_machine_status',
    args: { machine_id: 'M-CNC-01', field: 'next_maintenance' },
    result: {
      machine_id: 'M-CNC-01',
      next_maintenance: 'Friday 14:00',
    },
  },
  {
    key: 'alarm-follow-up',
    prompt: 'Phase 13 normal use turn 06: any alarms after that status check',
    answer: 'Phase 13 turn 06: No active alarms are reported for M-CNC-01 in this fixture.',
    plan: 'Checking alarm state after the machine status request.',
    toolName: 'get_machine_alarms',
    args: { machine_id: 'M-CNC-01' },
    result: {
      machine_id: 'M-CNC-01',
      alarms: [],
    },
  },
  {
    key: 'operator-handoff',
    prompt: 'Phase 13 normal use turn 07: summarize what I should tell the next operator',
    answer:
      'Phase 13 turn 07: Handoff summary: M-CNC-01 is running, JOB-SEED-002 needs attention, and LOTO steps require affected-operator notification.',
    plan: 'Producing a concise handoff summary from the visible conversation state.',
    toolName: 'summarize_operator_handoff',
    args: { scope: 'visible-thread' },
    result: {
      machine: 'M-CNC-01',
      watch_job: 'JOB-SEED-002',
      safety_note: 'notify affected operators before lockout',
    },
  },
  {
    key: 'job-owner',
    prompt: 'Phase 13 normal use turn 08: who owns JOB-SEED-002',
    answer: 'Phase 13 turn 08: JOB-SEED-002 is assigned to frontend-operator for this deterministic fixture.',
    plan: 'Looking up the owner for JOB-SEED-002.',
    toolName: 'get_job_owner',
    args: { job_id: 'JOB-SEED-002' },
    result: {
      job_id: 'JOB-SEED-002',
      owner: 'frontend-operator',
    },
  },
  {
    key: 'safe-next-step',
    prompt: 'Phase 13 normal use turn 09: what is the safe next step before touching the machine',
    answer:
      'Phase 13 turn 09: Safe next step: confirm the work order, notify affected operators, and verify the machine is isolated before contact.',
    plan: 'Answering a read-only safety next-step question.',
    toolName: 'rag_loto_lookup',
    args: { topic: 'safe-next-step' },
    result: {
      recommendation: 'confirm, notify, isolate, verify',
    },
  },
  {
    key: 'final-check',
    prompt: 'Phase 13 normal use turn 10: final check, did we lose any state',
    answer:
      'Phase 13 turn 10: State check passed: prior machine status, job list, LOTO source, and follow-up context remain visible.',
    plan: 'Verifying the visible transcript still has the normal-use thread state.',
    toolName: 'summarize_visible_state',
    args: { expected_turns: 10 },
    result: {
      expected_turns: 10,
      state: 'visible',
    },
  },
]

export const normalUsePromptSet = normalUseTurns.map((turn) => turn.prompt)

export const normalUseLifecycleCompletedPrompt =
  'Phase 13 normal use lifecycle: complete a machine check before closing chat'

export const normalUsePlanModeDraftPrompt =
  'Phase 13 draft text that should never be sent'

export const normalUsePlanModeFinalPrompt =
  'Phase 13 final edited plan-mode prompt for M-CNC-01'

export const normalUsePlanModeAnswer =
  'Phase 13 plan-mode final answer: submitted once with the edited text and Plan mode.'

export function normalUseTurnForPrompt(prompt) {
  const normalized = String(prompt || '').trim().toLowerCase()
  if (normalized === normalUseLifecycleCompletedPrompt.toLowerCase()) {
    return {
      ...normalUseTurns[0],
      key: 'lifecycle-completed',
      prompt: normalUseLifecycleCompletedPrompt,
      answer: 'Phase 13 lifecycle completed session: M-CNC-01 finished normally before the chat was closed.',
      plan: 'Completing a normal lifecycle check before modal close.',
    }
  }
  if (normalized === normalUsePlanModeFinalPrompt.toLowerCase()) {
    return {
      ...normalUseTurns[0],
      key: 'plan-mode-final',
      prompt: normalUsePlanModeFinalPrompt,
      answer: normalUsePlanModeAnswer,
      plan: 'Planning the final edited operator request.',
      toolName: 'plan_machine_status_review',
      args: { machine_id: 'M-CNC-01', mode: 'plan' },
      result: {
        machine_id: 'M-CNC-01',
        mode: 'plan',
        submitted_text: normalUsePlanModeFinalPrompt,
      },
    }
  }
  return normalUseTurns.find((turn) => turn.prompt.toLowerCase() === normalized) || normalUseTurns[0]
}

export function normalUseHistoryFixtures(runId = 'default') {
  const prefix = `Phase 13 history ${runId}`
  const sessions = Array.from({ length: 18 }, (_, index) => {
    const ordinal = String(index + 1).padStart(2, '0')
    return {
      key: `history-${ordinal}`,
      name: `${prefix} archived ${ordinal}`,
      prompt: `${prefix} decoy prompt ${ordinal}`,
      answer: `${prefix} decoy transcript ${ordinal} should not appear when the target session is selected.`,
      status: 'COMPLETED',
      updatedOffsetSeconds: index,
    }
  })

  const target = {
    key: 'target',
    name: `${prefix} target transcript`,
    prompt: `${prefix} target prompt for M-CNC-01`,
    answer: `${prefix} target transcript restored for M-CNC-01 without mixing historical sessions.`,
    status: 'COMPLETED',
    updatedOffsetSeconds: 100,
    sources: [
      {
        source_number: 1,
        doc_id: 'normal-use-history-target',
        title: 'Normal Use History Target',
        organization: 'eMas Playwright',
      },
    ],
  }

  sessions.splice(8, 0, target)
  return { sessions, target }
}
