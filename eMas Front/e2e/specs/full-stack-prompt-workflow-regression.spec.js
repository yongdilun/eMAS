import { expect, test } from '../support/seededArtifacts.js'
import {
  activeSessionId,
  factoryAgentJson,
  openChat,
  pendingApprovalsForPage,
  sendPrompt,
  snapshotForPage,
  waitForSessionStatus,
} from '../support/fullStackScenarios.js'
import {
  activityText,
  approvalIdsFromTimeline,
  currentPriorityMap,
  dataIntegrityAudit,
  expectedPriorityMapForCascade,
  expectAuditForJobs,
  factoryAgentRaw,
  jobIdsByPriority,
  priorityForJob,
  resetSeededJobPriorities,
  timelineText,
} from '../support/dataIntegrityScenarios.js'
import {
  phase19CascadeMatrix,
  phase19LotoRegressionEntries,
} from '../support/promptRegressionScenarios.js'

async function approveApproval(approvalId, decidedBy = 'phase19-playwright') {
  return factoryAgentRaw(`/approvals/${approvalId}/approve`, {
    method: 'POST',
    body: { decided_by: decidedBy },
  })
}

async function pendingApprovalMatching(page, writeSet) {
  await expect
    .poll(async () => {
      const pending = await pendingApprovalsForPage(page)
      return pending.find((approval) => approval?.args?.bundle_ui?.write_set === writeSet)?.approval_id || null
    }, { timeout: 30_000 })
    .not.toBeNull()
  const pending = await pendingApprovalsForPage(page)
  return pending.find((approval) => approval?.args?.bundle_ui?.write_set === writeSet)
}

function sourcesFromSnapshot(snapshot) {
  const planSources = snapshot.plan?.sources || []
  if (planSources.length) return planSources
  return (snapshot.timeline || []).flatMap((event) => event.details?.sources || [])
}

async function expectJobsAtPriority(jobIds, priority) {
  await expect
    .poll(async () => {
      const current = await currentPriorityMap()
      return jobIds.every((jobId) => current[jobId] === priority)
    }, { timeout: 30_000 })
    .toBe(true)
}

function approvalHeadlinePattern(number, source, target) {
  return new RegExp(`Approval ${number} required: original ${source.toUpperCase()}-priority jobs will become ${target.toUpperCase()}`, 'i')
}

async function runCascadeInvariant(page, scenario) {
  const [firstChange, secondChange] = scenario.changes
  const firstWriteSet = `original_${firstChange.source}_to_${firstChange.target}`
  const secondWriteSet = `original_${secondChange.source}_to_${secondChange.target}`
  const firstJobIds = jobIdsByPriority(firstChange.source)
  const secondJobIds = jobIdsByPriority(secondChange.source)

  await openChat(page)
  await sendPrompt(page, scenario.prompt)

  const first = await pendingApprovalMatching(page, firstWriteSet)
  expect(first.args.bundle_ui.rows.map((row) => row.job_id).sort()).toEqual([...firstJobIds].sort())
  expect(first.args.bundle_ui.original_state_semantics.toLowerCase()).toContain(
    `original ${secondChange.source}-priority jobs become ${secondChange.target}`,
  )
  await expect(page.getByText(approvalHeadlinePattern(1, firstChange.source, firstChange.target)).first()).toBeVisible()
  await expect(page.getByText(/Phase 19 cascade matrix complete|Phase 14 cascading priority update complete/i)).toHaveCount(0)
  await page.getByRole('button', { name: 'Approve' }).click()

  await expectJobsAtPriority(firstJobIds, firstChange.target)
  await expect
    .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
    .toBe('WAITING_APPROVAL')
  await expect(page.getByText(/Run complete/i)).toHaveCount(0)

  const second = await pendingApprovalMatching(page, secondWriteSet)
  expect(second.approval_id).not.toBe(first.approval_id)
  expect(second.args.bundle_ui.rows.map((row) => row.job_id).sort()).toEqual([...secondJobIds].sort())
  expect(second.args.bundle_ui.previous_approval_id).toBe(first.approval_id)
  await expect(page.getByText(approvalHeadlinePattern(2, secondChange.source, secondChange.target)).first()).toBeVisible()
  await page.getByRole('button', { name: 'Approve' }).click()

  await expectJobsAtPriority(secondJobIds, secondChange.target)
  await waitForSessionStatus(page, 'COMPLETED')
  await expect(page.getByText(/Run complete/i)).toBeVisible()

  const sessionId = await activeSessionId(page)
  expect(await currentPriorityMap()).toEqual(expectedPriorityMapForCascade(scenario.changes))
  for (const unchangedPriority of scenario.unchanged) {
    for (const jobId of jobIdsByPriority(unchangedPriority)) {
      expect(await priorityForJob(jobId), `${jobId} should keep original ${unchangedPriority} priority`).toBe(unchangedPriority)
    }
  }

  const audit = await dataIntegrityAudit(sessionId)
  expectAuditForJobs(audit, {
    scenario: '119',
    writeSet: firstWriteSet,
    approvalId: first.approval_id,
    jobIds: firstJobIds,
    requestedPriority: firstChange.target,
  })
  expectAuditForJobs(audit, {
    scenario: '119',
    writeSet: secondWriteSet,
    approvalId: second.approval_id,
    jobIds: secondJobIds,
    requestedPriority: secondChange.target,
  })

  const firstApproval = await factoryAgentJson(`/approvals/${first.approval_id}`)
  const secondApproval = await factoryAgentJson(`/approvals/${second.approval_id}`)
  expect(firstApproval.status).toBe('APPROVED')
  expect(secondApproval.status).toBe('APPROVED')

  const snapshot = await snapshotForPage(page)
  const timelineApprovalIds = approvalIdsFromTimeline(snapshot)
  expect(timelineApprovalIds.has(first.approval_id)).toBe(true)
  expect(timelineApprovalIds.has(second.approval_id)).toBe(true)
  expect(timelineText(snapshot)).toContain(`${firstChange.source}->${firstChange.target} ${firstJobIds.length}`)
  expect(timelineText(snapshot)).toContain(`${secondChange.source}->${secondChange.target} ${secondJobIds.length}`)
  expect(activityText(snapshot)).toContain('Run complete')
}

test.describe('Phase 19 seeded prompt/workflow regression gate @prompt-regression @data-integrity', () => {
  test.describe.configure({ timeout: 150_000 })

  test('scenario 116/124/125: LOTO regression bank routes through seeded RAG without generic diagnostics', async ({ page }) => {
    expect(phase19LotoRegressionEntries.length).toBeGreaterThanOrEqual(5)

    for (const [index, entry] of phase19LotoRegressionEntries.entries()) {
      if (index === 0) {
        await openChat(page)
      } else {
        await page.getByRole('button', { name: 'New Session' }).click()
      }
      await sendPrompt(page, entry.source_prompt)

      await expect(page.getByText(/Controlled seeded RAG answer/i).first()).toBeVisible()
      await expect(page.getByText(/M-CNC-01/i).first()).toBeVisible()
      await expect(page.getByText('Knowledge sources')).toBeVisible()
      await expect(page.getByText(/Seeded LOTO Procedure for M-CNC-01/i).first()).toBeVisible()
      await expect(page.getByText(/Which machine ID/i)).toHaveCount(0)
      await expect(page.getByText('Factory Agent needs attention')).toHaveCount(0)
      await expect(page.getByText('Run complete')).toBeVisible()

      const snapshot = await snapshotForPage(page)
      const sources = sourcesFromSnapshot(snapshot)
      expect(snapshot.session.status).toBe(entry.expected.required_final_state)
      expect(snapshot.steps).toHaveLength(0)
      expect(sources[0].machine_id).toBe(entry.expected.required_source.machine_id)
      expect(sources[0].procedure_id).toBe(entry.expected.required_source.procedure_id)
    }
  })

  for (const scenario of phase19CascadeMatrix) {
    test(`scenario 119/120/121/125: ${scenario.name} uses two approvals and original-state semantics`, async ({ page }) => {
      await resetSeededJobPriorities()
      await runCascadeInvariant(page, scenario)
    })
  }
})
