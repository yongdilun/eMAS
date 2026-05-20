import { expect, test } from '../support/seededArtifacts.js'
import {
  manualPromptBankEntries,
  phase18LotoVariantPrompts,
  phase18MissingMachinePrompt,
  phase18SynonymPrompts,
} from '../support/intentEntityScenarios.js'
import { openChat, sendPrompt, snapshotForPage } from '../support/fullStackScenarios.js'
import { expectTransitionCheckpoint } from '../support/factoryAgentTransitionOracle.js'

function textFromSnapshot(snapshot) {
  return JSON.stringify(snapshot).toLowerCase()
}

function sourcesFromSnapshot(snapshot) {
  const planSources = snapshot.plan?.sources || []
  if (planSources.length) return planSources
  return (snapshot.timeline || []).flatMap((event) => event.details?.sources || [])
}

async function expectNoMachineClarification(page) {
  await expect(page.getByText(/Which machine ID/i)).toHaveCount(0)
  await expect(page.getByText(/provide the exact machine/i)).toHaveCount(0)
}

test.describe('Phase 18 seeded intent/entity and RAG routing @intent-entity @rag-route', () => {
  test('scenario 106/112/115: query bank LOTO prompt routes to RAG and keeps source metadata tied to M-CNC-01', async ({ page }) => {
    const entry = manualPromptBankEntries.find((item) => item.id === 'phase18-loto-m-cnc-01')
    expect(entry).toBeTruthy()

    await openChat(page)
    await sendPrompt(page, entry.prompt)

    await expect(page.getByText(/Controlled seeded RAG answer/i).first()).toBeVisible()
    await expect(page.getByText(/M-CNC-01/i).first()).toBeVisible()
    await expect(page.getByText('Knowledge sources')).toBeVisible()
    await expect(page.getByText(/Seeded LOTO Procedure for M-CNC-01/i).first()).toBeVisible()
    await expectNoMachineClarification(page)
    await expect(page.getByText('Run complete')).toBeVisible()

    const snapshot = await snapshotForPage(page)
    const sources = sourcesFromSnapshot(snapshot)
    expect(snapshot.session.status).toBe(entry.expected.required_final_state)
    expect(snapshot.steps).toHaveLength(0)
    expect(sources[0].machine_id).toBe(entry.expected.required_source.machine_id)
    expect(sources[0].procedure_id).toBe(entry.expected.required_source.procedure_id)
    expect(textFromSnapshot(snapshot)).not.toContain('which machine id')
  })

  for (const [index, prompt] of phase18LotoVariantPrompts.entries()) {
    test(`scenario 107 variant ${index + 1}: LOTO wording extracts M-CNC-01 before RAG routing`, async ({ page }) => {
      await openChat(page)
      await sendPrompt(page, prompt)

      await expect(page.getByText(/Controlled seeded RAG answer/i).first()).toBeVisible()
      await expect(page.getByText(/M-CNC-01/i).first()).toBeVisible()
      await expectNoMachineClarification(page)
      const snapshot = await snapshotForPage(page)
      const sources = sourcesFromSnapshot(snapshot)
      expect(snapshot.session.status).toBe('COMPLETED')
      expect(sources[0].machine_id).toBe('M-CNC-01')
    })
  }

  test('scenario 108: machine status synonyms route to the machine lookup tool', async ({ page }, testInfo) => {
    await openChat(page)
    await sendPrompt(page, phase18SynonymPrompts.machineStatus)

    await expectTransitionCheckpoint(page, {
      checkpoint: 'scenario 108 seeded machine status response-document contract',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['status_result'],
        backendBlockTypes: ['status_result'],
        hiddenBlockTypes: ['approval_required', 'mutation_result', 'result_table'],
        hiddenBackendBlockTypes: ['approval_required', 'mutation_result', 'result_table', 'record_preview'],
        responseContracts: ['entity_status_v1'],
        approvalActionCount: 0,
        textIncludes: ['Machine M-CNC-01', 'Machine ID', 'Machine name', 'CNC Mill 01', 'Status'],
        textExcludes: [/Approval required/i, /Which machine ID/i],
      },
    })
    const snapshot = await snapshotForPage(page)
    expect(snapshot.steps[0].tool_name).toBe('get__machines_{id}')
    expect(snapshot.steps[0].args.id).toBe('M-CNC-01')
  })

  test('scenario 108: work-order status synonyms route to the job lookup tool', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, phase18SynonymPrompts.jobStatus)

    await expect(page.getByText(/Job JOB-SEED-001/i).first()).toBeVisible()
    const snapshot = await snapshotForPage(page)
    expect(snapshot.steps[0].tool_name).toBe('get__jobs_{id}')
    expect(snapshot.steps[0].args.id).toBe('JOB-SEED-001')
  })

  test('scenario 108: urgent task wording routes to the job collection tool with high priority', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, phase18SynonymPrompts.jobList)

    await expect(page.getByText(/Found .* seeded jobs for priority=high/i).first()).toBeVisible()
    const snapshot = await snapshotForPage(page)
    expect(snapshot.steps[0].tool_name).toBe('get__jobs')
    expect(snapshot.steps[0].args.priority).toBe('high')
  })

  test('SO-022 scenario 109 @prompt-regression: missing LOTO machine ID asks for a specific id without inventing one', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, phase18MissingMachinePrompt)

    await expect(page.getByText(/Which machine ID should I use for the LOTO procedure/i).first()).toBeVisible()
    await expect(page.getByText(/exact machine ID/i).first()).toBeVisible()
    await expect(page.getByText(/M-CNC-01/i)).toHaveCount(0)
    await expect(page.getByText(/Controlled seeded RAG answer/i)).toHaveCount(0)
    await expect(page.getByText('Knowledge sources')).toHaveCount(0)
    await expect(page.getByText('Factory Agent needs attention')).toHaveCount(0)
    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('COMPLETED')
    expect(snapshot.steps).toHaveLength(0)
    expect(sourcesFromSnapshot(snapshot)).toEqual([])
    expect(textFromSnapshot(snapshot)).toContain('which machine id')
    expect(textFromSnapshot(snapshot)).not.toContain('m-cnc-01')
  })

  test('scenario 110: multi-entity LOTO prompt preserves machine and job IDs on the RAG route', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'What LOTO procedure applies before working on M-CNC-01 for job JOB-SEED-001?')

    await expect(page.getByText(/Controlled seeded RAG answer/i).first()).toBeVisible()
    await expect(page.getByText(/JOB-SEED-001/i).first()).toBeVisible()
    await expectNoMachineClarification(page)
    const snapshot = await snapshotForPage(page)
    const sources = sourcesFromSnapshot(snapshot)
    expect(snapshot.steps).toHaveLength(0)
    expect(sources[0].machine_id).toBe('M-CNC-01')
    expect(sources[0].job_id).toBe('JOB-SEED-001')
  })

  test('scenario 111: existing machine with no LOTO source returns honest not-found response', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'What LOTO procedure applies before working on M-CNC-02?')

    await expect(page.getByText(/machine M-CNC-02 exists/i).first()).toBeVisible()
    await expect(page.getByText(/do not have an available cited LOTO source/i).first()).toBeVisible()
    await expect(page.getByText('Knowledge sources')).toHaveCount(0)
    await expect(page.getByText('Run complete')).toBeVisible()

    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('COMPLETED')
    expect(sourcesFromSnapshot(snapshot)).toEqual([])
  })
})
