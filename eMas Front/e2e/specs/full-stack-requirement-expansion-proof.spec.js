import fs from 'node:fs'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const repoRoot = path.resolve(__dirname, '..', '..', '..')
const factoryAgentRoot = path.join(repoRoot, 'factory-agent')
const canonicalProofPath = path.join(repoRoot, 'test-artifacts', 'planner-owned-requirement-expansion', 'browser-proof.json')

function pythonExe() {
  const candidate = path.join(factoryAgentRoot, '.venv', 'Scripts', 'python.exe')
  return fs.existsSync(candidate) ? candidate : 'python'
}

test('HQ-REQUIREMENT-EXPANSION repo-owned proof generator reproduces child expansion audit', async ({}, testInfo) => {
  const generatedPath = testInfo.outputPath('hq-requirement-expansion-browser-proof.json')
  execFileSync(
    pythonExe(),
    ['scripts/generate_requirement_expansion_proof.py', '--output', generatedPath],
    {
      cwd: factoryAgentRoot,
      encoding: 'utf8',
      stdio: 'pipe',
    },
  )

  const proof = JSON.parse(fs.readFileSync(generatedPath, 'utf8'))
  fs.mkdirSync(path.dirname(canonicalProofPath), { recursive: true })
  fs.copyFileSync(generatedPath, canonicalProofPath)
  await testInfo.attach('hq-requirement-expansion-browser-proof.json', {
    path: generatedPath,
    contentType: 'application/json',
  })

  expect(proof.browser_validation).toBe('planner_owned_requirement_expansion')
  expect(proof.seeded_fixture_feasibility).toMatchObject({ feasible: false })
  expect(proof.executor_tool_sequence).toEqual(['get__machines_{id}', 'get__jobs_{id}'])
  expect(proof.selector_requirement_ids).toEqual(['req-001', 'req-001.a'])
  expect(proof.child_choose_tool_call).toMatchObject({
    tool_name: 'get__jobs_{id}',
    requirement_id: 'req-001.a',
    candidate_window_id: 'window-002',
  })
  expect(proof.active_final_evidence_refs).toEqual(['ev-api-req-001', 'ev-api-req-001.a'])
  expect(proof.response_evidence_refs).toEqual(proof.active_final_evidence_refs)
  expect(proof.stale_or_failed_final_evidence_refs).toEqual([])
  expect(Object.values(proof.checks)).toEqual(Object.keys(proof.checks).map(() => true))
})
