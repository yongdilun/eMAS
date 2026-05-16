import { manualPromptBankEntries } from './intentEntityScenarios.js'

export const phase19LotoRegressionEntries = manualPromptBankEntries.filter(
  (entry) => entry.id === 'phase18-loto-m-cnc-01' || String(entry.id || '').startsWith('phase19-loto-'),
)

export const phase19UnknownPrompt = 'Phase 19 unsupported prompt: calibrate the moonlight queue'
export const phase19UnknownDiagnostic = 'Unsupported Phase 19 prompt regression fixture: no safe route matched.'

export const phase19CascadeMatrix = Object.freeze([
  {
    name: 'high-to-low then original-low-to-medium',
    prompt: 'Phase 19 prompt regression: change all high priority job to low then change all low priority job to medium',
    changes: [
      { source: 'high', target: 'low' },
      { source: 'low', target: 'medium' },
    ],
    unchanged: ['medium'],
  },
  {
    name: 'medium-to-high then original-high-to-medium',
    prompt: 'Phase 19 prompt regression: change all medium priority job to high then change all high priority job to medium',
    changes: [
      { source: 'medium', target: 'high' },
      { source: 'high', target: 'medium' },
    ],
    unchanged: ['low'],
  },
  {
    name: 'low-to-high then original-high-to-low',
    prompt: 'Phase 19 prompt regression: change all low priority job to high then change all high priority job to low',
    changes: [
      { source: 'low', target: 'high' },
      { source: 'high', target: 'low' },
    ],
    unchanged: ['medium'],
  },
  {
    name: 'high-to-medium then original-medium-to-low',
    prompt: 'Phase 19 prompt regression: change all high priority job to medium then change all medium priority job to low',
    changes: [
      { source: 'high', target: 'medium' },
      { source: 'medium', target: 'low' },
    ],
    unchanged: ['low'],
  },
])
