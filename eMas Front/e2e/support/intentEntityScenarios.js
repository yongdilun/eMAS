import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '..', '..', '..')
export const manualPromptBankPath = path.join(repoRoot, 'tests', 'e2e', 'scenarios', 'manual_prompt_regressions.json')

export function loadManualPromptBank() {
  return JSON.parse(fs.readFileSync(manualPromptBankPath, 'utf8'))
}

export const manualPromptBank = loadManualPromptBank()
export const manualPromptBankEntries = manualPromptBank.prompts || []
export const manualPromptBankPrompts = manualPromptBankEntries.map((entry) => entry.prompt)
export const phase18SeedPrompt = 'What LOTO procedure applies before working on M-CNC-01?'

export const phase18MockRagAnswer =
  'Controlled seeded RAG answer: the LOTO procedure for M-CNC-01 requires isolating hazardous energy, locking and tagging energy-isolating devices, verifying zero energy, and following the site procedure before work begins. [1]'

export const phase18MockRagSource = {
  source_number: 1,
  doc_id: 'seeded-loto-procedure-m-cnc-01',
  title: 'Seeded LOTO Procedure for M-CNC-01',
  organization: 'eMas Safety',
  authority_level: 'controlled_test_fixture',
  license: 'internal-test',
  machine_id: 'M-CNC-01',
  procedure_id: 'LOTO-M-CNC-01',
}

export const phase18MissingMachinePrompt = 'What LOTO procedure applies before working on the CNC machine?'

export const phase18LotoVariantPrompts = [
  'what loto procedure applies before working on m-cnc-01',
  'LOTO for M-CNC-01',
  'Before service: LOTO for "m-cnc-01".',
]

export const phase18SynonymPrompts = {
  machineStatus: 'equipment m-cnc-01 status',
  jobStatus: 'status for work order JOB-SEED-001',
  jobList: 'urgent tasks due soon',
}
