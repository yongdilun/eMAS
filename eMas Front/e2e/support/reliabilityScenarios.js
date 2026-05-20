import { fixtureTime } from '../fixtures/factoryAgentFixtures.js'

export const reliabilityConcurrentTurns = Array.from({ length: 10 }, (_, index) => {
  const sequence = String(index + 1).padStart(2, '0')
  return {
    key: `session-${sequence}`,
    label: `Reliability Session ${sequence}`,
    prompt: `Phase 15 reliability concurrent session ${sequence} read-only machine status`,
    answer: `Phase 15 reliability session ${sequence} completed read-only status without cross-session leakage.`,
    machineId: `M-CNC-${sequence}`,
  }
})

export const reliabilityLongStreamPrompt = 'Phase 15 reliability long activity stream for M-CNC-01'
export const reliabilityLongStreamAnswer =
  'Phase 15 reliability long stream reached a terminal state after many ordered activity events.'
export const reliabilityLongStreamStepCount = 48

export const reliabilityLargeResultPrompt = 'Phase 15 reliability large structured result with many sources'
export const reliabilityLargeResultAnswer =
  'Phase 15 reliability large result rendered 120 rows and 24 knowledge sources without losing usable controls. [^1] [^24]'

export const reliabilitySlowTimeoutPrompt = 'Phase 15 reliability slow tool response should timeout safely'

export function reliabilityTurnForPrompt(prompt) {
  const normalized = String(prompt || '').trim().toLowerCase()
  return (
    reliabilityConcurrentTurns.find((turn) => turn.prompt.toLowerCase() === normalized) ||
    reliabilityConcurrentTurns[0]
  )
}

export function reliabilityLongActivitySteps({ terminal = false } = {}) {
  const rows = Array.from({ length: reliabilityLongStreamStepCount }, (_, index) => {
    const sequence = String(index + 1).padStart(2, '0')
    return {
      id: `pw-reliability-long-step-${sequence}`,
      timestamp: Date.parse(fixtureTime(index + 1)) / 1000,
      group: index < 8 ? 'planning' : index < 36 ? 'research' : 'response',
      label: `Reliability stream step ${sequence}`,
      detail: `Phase 15 long-stream activity event ${sequence} of ${reliabilityLongStreamStepCount}.`,
      state: terminal || index < reliabilityLongStreamStepCount - 1 ? 'success' : 'running',
    }
  })

  if (terminal) {
    rows.push({
      id: 'pw-reliability-long-complete',
      timestamp: Date.parse(fixtureTime(reliabilityLongStreamStepCount + 1)) / 1000,
      group: 'response',
      label: 'Run complete',
      detail: 'All reliability stream activity events reached a terminal state.',
      state: 'complete',
    })
  }

  return rows
}

export function reliabilityLargeResultRows(total = 120) {
  return Array.from({ length: total }, (_, index) => {
    const sequence = String(index + 1).padStart(3, '0')
    const priorities = ['low', 'medium', 'high']
    return {
      job_id: `JOB-REL-${sequence}`,
      machine_id: `M-CNC-${String((index % 10) + 1).padStart(2, '0')}`,
      priority: priorities[index % priorities.length],
      status: index % 4 === 0 ? 'delayed' : 'planned',
      source_ref: `SRC-${String((index % 24) + 1).padStart(2, '0')}`,
    }
  })
}

export function reliabilityLargeResultSources(total = 24) {
  return Array.from({ length: total }, (_, index) => {
    const sourceNumber = index + 1
    const sequence = String(sourceNumber).padStart(2, '0')
    return {
      source_number: sourceNumber,
      title: `Reliability Source ${sequence}`,
      doc_id: `REL-SRC-${sequence}`,
      organization: 'eMAS Reliability Lab',
      uri: `seeded://reliability/source-${sequence}`,
    }
  })
}

export function reliabilityLargeResultPresentation() {
  const rows = reliabilityLargeResultRows()
  return {
    render_hint: 'table',
    table: {
      columns: [
        { key: 'job_id', label: 'Job' },
        { key: 'machine_id', label: 'Machine' },
        { key: 'priority', label: 'Priority' },
        { key: 'status', label: 'Status' },
        { key: 'source_ref', label: 'Source' },
      ],
      rows: rows.slice(0, 20),
      displayed_rows: 20,
      total_rows: rows.length,
    },
    analysis: {
      facts: [
        'Phase 15 large-result fixture keeps only the first 20 rows visible while preserving total-row evidence.',
        'Source chips remain available after answer streaming completes.',
      ],
    },
  }
}

export function reliabilitySlowActivitySteps() {
  return [
    {
      id: 'pw-reliability-slow-planning',
      timestamp: Date.parse(fixtureTime(1)) / 1000,
      group: 'planning',
      label: 'Understanding your request',
      detail: 'The slow-response fixture accepted the request and is waiting on a tool response.',
      state: 'running',
    },
  ]
}
