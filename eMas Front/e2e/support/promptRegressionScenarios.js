import { manualPromptBankEntries } from './intentEntityScenarios.js'

export const phase19LotoRegressionEntries = manualPromptBankEntries.filter(
  (entry) =>
    (
      entry.id === 'phase18-loto-m-cnc-01' ||
      String(entry.id || '').startsWith('phase19-loto-') ||
      entry.selected_oracle === 'SO-023'
    ) &&
    entry.expected?.primary_route === 'rag_loto',
)

export const phase19UnknownPrompt = 'Phase 19 unsupported prompt: calibrate the moonlight queue'
export const phase19UnknownDiagnostic = 'Unsupported Phase 19 prompt regression fixture: no safe route matched.'

export const phase19CascadeMatrix = Object.freeze([
  {
    oracleId: 'SO-002',
    name: 'high-to-low then original-low-to-medium',
    prompt: 'Phase 19 prompt regression: change all high priority job to low then change all low priority job to medium',
    changes: [
      { source: 'high', target: 'low' },
      { source: 'low', target: 'medium' },
    ],
    unchanged: ['medium'],
  },
  {
    oracleId: 'SO-001',
    name: 'medium-to-high then original-high-to-medium',
    prompt: 'Phase 19 prompt regression: change all medium priority job to high then change all high priority job to medium',
    changes: [
      { source: 'medium', target: 'high' },
      { source: 'high', target: 'medium' },
    ],
    unchanged: ['low'],
  },
  {
    oracleId: 'SO-041',
    name: 'medium-to-high then original-high-to-low',
    prompt: 'Phase 11 prompt regression: change all medium priority job to high then change all high priority job to low',
    changes: [
      { source: 'medium', target: 'high' },
      { source: 'high', target: 'low' },
    ],
    unchanged: ['low'],
  },
  {
    oracleId: 'SO-003',
    name: 'low-to-high then original-high-to-low',
    prompt: 'Phase 19 prompt regression: change all low priority job to high then change all high priority job to low',
    changes: [
      { source: 'low', target: 'high' },
      { source: 'high', target: 'low' },
    ],
    unchanged: ['medium'],
  },
  {
    oracleId: 'SO-004',
    name: 'high-to-medium then original-medium-to-low',
    prompt: 'Phase 19 prompt regression: change all high priority job to medium then change all medium priority job to low',
    changes: [
      { source: 'high', target: 'medium' },
      { source: 'medium', target: 'low' },
    ],
    unchanged: ['low'],
  },
])
