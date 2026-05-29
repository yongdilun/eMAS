import { expect, test } from '../support/seededArtifacts.js'
import {
  activeSessionId,
  factoryAgentJson,
  openChat,
  pendingApprovalsForPage,
  sendPrompt,
  snapshotForPage,
  startNewChatSession,
  waitForSessionStatus,
} from '../support/fullStackScenarios.js'
import {
  activityText,
  approvalIdsFromTimeline,
  captureFinalSeededState,
  captureInitialSeededState,
  currentPriorityMap,
  dataIntegrityAudit,
  expectedPriorityMapForCascade,
  expectApprovalRowMatches,
  expectAuditCommit,
  expectAuditForJobs,
  expectCascadeTimelineEvidence,
  expectFinalSummaryClaimsOnly,
  expectRowsUnchangedFromInitial,
  expectSnapshotApprovalState,
  jobIdsByPriority,
  priorityForJob,
  recordOracleCheckpoint,
  resetSeededJobPriorities,
  sessionMessages,
  timelineText,
  withSeededOracleArtifact,
} from '../support/dataIntegrityScenarios.js'
import {
  phase19CascadeMatrix,
  phase19LotoRegressionEntries,
} from '../support/promptRegressionScenarios.js'

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

function capitalizedPriority(value) {
  return String(value || '').replace(/^\w/, (letter) => letter.toUpperCase())
}

function cascadeCompletePattern(totalJobs) {
  return new RegExp(`Done\\. I updated ${totalJobs} jobs across 2 approved business changes\\.`, 'i')
}

function businessGroupPattern(source, target, count) {
  return new RegExp(`(?:Original\\s+)?${capitalizedPriority(source)}\\s*->\\s*${capitalizedPriority(target)}:\\s*${count} jobs`, 'i')
}

async function finalAssistantText(sessionId) {
  const messages = await sessionMessages(sessionId)
  return [...messages].reverse().find((message) => message.role === 'assistant')?.content || ''
}

async function visibleText(page) {
  return page.locator('body').evaluate((body) => body.innerText)
}

async function runCascadeInvariant(page, scenario, testInfo) {
  return withSeededOracleArtifact(testInfo, `${scenario.oracleId} prompt regression cascade ${scenario.name}`, async (artifact) => {
    const initial = await captureInitialSeededState(artifact)
    let sessionId = null
    try {
  const [firstChange, secondChange] = scenario.changes
  const firstWriteSet = `original_${firstChange.source}_to_${firstChange.target}`
  const secondWriteSet = `original_${secondChange.source}_to_${secondChange.target}`
  const firstJobIds = jobIdsByPriority(firstChange.source)
  const secondJobIds = jobIdsByPriority(secondChange.source)
  const finalCompletePattern = cascadeCompletePattern(firstJobIds.length + secondJobIds.length)
  const firstBusinessGroupPattern = businessGroupPattern(firstChange.source, firstChange.target, firstJobIds.length)
  const secondBusinessGroupPattern = businessGroupPattern(secondChange.source, secondChange.target, secondJobIds.length)

  await openChat(page)
  await sendPrompt(page, scenario.prompt)
  sessionId = await activeSessionId(page)

  const first = await pendingApprovalMatching(page, firstWriteSet)
  await expectApprovalRowMatches(first, {
    status: 'PENDING',
    writeSet: firstWriteSet,
    kind: 'phase14_cascade_priority',
    jobIds: firstJobIds,
    requestedPriority: firstChange.target,
    originalPriority: firstChange.source,
    count: firstJobIds.length,
  })
  expect(first.args.bundle_ui.rows.map((row) => row.job_id).sort()).toEqual([...firstJobIds].sort())
  expect(first.args.bundle_ui.original_state_semantics.toLowerCase()).toContain(
    `original ${secondChange.source}-priority jobs become ${secondChange.target}`,
  )
  await expect(page.getByText(approvalHeadlinePattern(1, firstChange.source, firstChange.target)).first()).toBeVisible()
  await expect(page.getByText(finalCompletePattern)).toHaveCount(0)
  await page.getByRole('button', { name: 'Approve' }).click()

  await expectJobsAtPriority(firstJobIds, firstChange.target)
  await expect
    .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
    .toBe('WAITING_APPROVAL')
  await expect(page.getByText(/Run complete/i)).toHaveCount(0)

  const second = await pendingApprovalMatching(page, secondWriteSet)
  await expectApprovalRowMatches(first.approval_id, {
    status: 'APPROVED',
    writeSet: firstWriteSet,
    kind: 'phase14_cascade_priority',
    jobIds: firstJobIds,
    requestedPriority: firstChange.target,
    originalPriority: firstChange.source,
    count: firstJobIds.length,
  })
  expectAuditCommit(await dataIntegrityAudit(sessionId), {
    scenario: '119',
    writeSet: firstWriteSet,
    approvalId: first.approval_id,
    succeededJobIds: firstJobIds,
    requestedPriority: firstChange.target,
  })
  for (const unchangedPriority of scenario.unchanged) {
    for (const jobId of jobIdsByPriority(unchangedPriority)) {
      expect(await priorityForJob(jobId), `${jobId} should keep original ${unchangedPriority} priority after approval 1`).toBe(unchangedPriority)
    }
  }
  recordOracleCheckpoint(artifact, 'after first prompt-regression cascade commit', {
    approval: await factoryAgentJson(`/approvals/${first.approval_id}`),
    audit: await dataIntegrityAudit(sessionId),
    priorities: await currentPriorityMap(),
    snapshot: await snapshotForPage(page),
  })
  expect(second.approval_id).not.toBe(first.approval_id)
  expect(second.args.bundle_ui.rows.map((row) => row.job_id).sort()).toEqual([...secondJobIds].sort())
  expect(second.args.bundle_ui.previous_approval_id).toBe(first.approval_id)
  await expectApprovalRowMatches(second, {
    status: 'PENDING',
    writeSet: secondWriteSet,
    kind: 'phase14_cascade_priority',
    jobIds: secondJobIds,
    requestedPriority: secondChange.target,
    originalPriority: secondChange.source,
    previousApprovalId: first.approval_id,
    count: secondJobIds.length,
  })
  await expectSnapshotApprovalState(page, { status: 'WAITING_APPROVAL', pendingApprovalId: second.approval_id })
  await expect(page.getByText(approvalHeadlinePattern(2, secondChange.source, secondChange.target)).first()).toBeVisible()
  await page.getByRole('button', { name: 'Approve' }).click()

  await expectJobsAtPriority(secondJobIds, secondChange.target)
  await waitForSessionStatus(page, 'COMPLETED')
  await expect(page.getByText(/Run complete/i).first()).toBeVisible()
  await expectApprovalRowMatches(second.approval_id, {
    status: 'APPROVED',
    writeSet: secondWriteSet,
    kind: 'phase14_cascade_priority',
    jobIds: secondJobIds,
    requestedPriority: secondChange.target,
    originalPriority: secondChange.source,
    previousApprovalId: first.approval_id,
    count: secondJobIds.length,
  })
  await expectSnapshotApprovalState(page, { status: 'COMPLETED', pendingApprovalId: null })

  expect(await currentPriorityMap()).toEqual(expectedPriorityMapForCascade(scenario.changes))
  for (const unchangedPriority of scenario.unchanged) {
    for (const jobId of jobIdsByPriority(unchangedPriority)) {
      expect(await priorityForJob(jobId), `${jobId} should keep original ${unchangedPriority} priority`).toBe(unchangedPriority)
      expect(await priorityForJob(jobId), `${jobId} should match captured initial state`).toBe(initial.priorities[jobId])
    }
    await expectRowsUnchangedFromInitial(initial.rowsById, jobIdsByPriority(unchangedPriority))
  }

  const audit = await dataIntegrityAudit(sessionId)
  expectAuditCommit(audit, {
    scenario: '119',
    writeSet: firstWriteSet,
    approvalId: first.approval_id,
    succeededJobIds: firstJobIds,
    requestedPriority: firstChange.target,
  })
  expectAuditCommit(audit, {
    scenario: '119',
    writeSet: secondWriteSet,
    approvalId: second.approval_id,
    succeededJobIds: secondJobIds,
    requestedPriority: secondChange.target,
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
  expectCascadeTimelineEvidence(snapshot, {
    firstApprovalId: first.approval_id,
    secondApprovalId: second.approval_id,
    firstSummary: `changed original ${firstChange.source.toUpperCase()} jobs to ${firstChange.target.toUpperCase()}`,
    secondSummary: `${firstChange.source}->${firstChange.target} ${firstJobIds.length}`,
  })
  expectFinalSummaryClaimsOnly(await finalAssistantText(sessionId), {
    mustInclude: [
      'Phase 19 cascade matrix complete',
      `${firstChange.source}->${firstChange.target} ${firstJobIds.length}`,
      `${secondChange.source}->${secondChange.target} ${secondJobIds.length}`,
    ],
    mustExclude: [/Factory Agent needs attention/i, /Run complete before approval/i],
  })
  await expect
    .poll(
      async () => {
        const text = await visibleText(page)
        return (
          finalCompletePattern.test(text) &&
          firstBusinessGroupPattern.test(text) &&
          secondBusinessGroupPattern.test(text)
        )
      },
      { timeout: 30_000 },
    )
    .toBe(true)
  expectFinalSummaryClaimsOnly(await visibleText(page), {
    mustInclude: [
      'Run complete',
      finalCompletePattern,
      firstBusinessGroupPattern,
      secondBusinessGroupPattern,
    ],
    mustExclude: [
      /Factory Agent needs attention/i,
      /Waiting for your approval/i,
      /Please approve to continue/i,
      /Run complete before approval/i,
    ],
  })
    } finally {
      await captureFinalSeededState(artifact, { page, sessionId }).catch(() => null)
    }
  })
}

test.describe('Phase 19 seeded prompt/workflow regression gate @prompt-regression @data-integrity', () => {
  test.describe.configure({ timeout: 150_000 })

  test('SO-021/SO-023 scenario 116/124/125: LOTO regression bank routes through seeded RAG without generic diagnostics', async ({ page }) => {
    expect(phase19LotoRegressionEntries.length).toBeGreaterThanOrEqual(5)

    for (const [index, entry] of phase19LotoRegressionEntries.entries()) {
      if (index === 0) {
        await openChat(page)
      } else {
        await startNewChatSession(page)
      }
      await sendPrompt(page, entry.source_prompt)
      await waitForSessionStatus(page, entry.expected.required_final_state)

      await expect(page.getByText(/Controlled seeded RAG answer/i).first()).toBeVisible()
      await expect(page.getByText(/M-CNC-01/i).first()).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Knowledge sources' }).first()).toBeVisible()
      await expect(page.getByText(/Seeded LOTO Procedure for M-CNC-01/i).first()).toBeVisible()
      await expect(page.getByText(/Which machine ID/i)).toHaveCount(0)
      await expect(page.getByText(/currently running|machine status only/i)).toHaveCount(0)
      await expect(page.getByText('Factory Agent needs attention')).toHaveCount(0)
      await expect(page.getByText('Run complete').first()).toBeVisible()

      const snapshot = await snapshotForPage(page)
      const sources = sourcesFromSnapshot(snapshot)
      expect(snapshot.session.status).toBe(entry.expected.required_final_state)
      expect(snapshot.steps).toHaveLength(0)
      expect(sources[0].machine_id).toBe(entry.expected.required_source.machine_id)
      expect(sources[0].procedure_id).toBe(entry.expected.required_source.procedure_id)
    }
  })

  test('SO-025 route confusion prompt renders LOTO source text instead of status-only copy', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'For M-CNC-01, tell me the lockout tagout steps, not the current machine status.')

    await expect(page.getByText(/Controlled seeded RAG answer/i).first()).toBeVisible()
    await expect(page.getByText(/lockout|tagout/i).first()).toBeVisible()
    await expect(page.getByText(/M-CNC-01/i).first()).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Knowledge sources' }).first()).toBeVisible()
    await expect(page.getByText(/Seeded LOTO Procedure for M-CNC-01/i).first()).toBeVisible()
    await expect(page.getByText(/Status:\s*running|machine status only|Which machine/i)).toHaveCount(0)
    await expect(page.getByText('Factory Agent needs attention')).toHaveCount(0)
    await expect(page.getByText('Run complete').first()).toBeVisible()
  })

  test('SO-026 multi-turn LOTO follow-up resolves it to the previous machine before routing to RAG', async ({ page }) => {
    await openChat(page)
    await startNewChatSession(page)
    await sendPrompt(page, 'What is the status of M-CNC-01?')
    await waitForSessionStatus(page, 'COMPLETED')

    await expect(page.getByText(/Machine M-CNC-01/i).first()).toBeVisible()
    await expect(page.getByText('Run complete').first()).toBeVisible()
    const sessionId = await activeSessionId(page)
    expect(sessionId).toBeTruthy()

    await sendPrompt(page, 'What LOTO procedure applies before working on it?')

    await expect(page.getByText(/Controlled seeded RAG answer/i).first()).toBeVisible()
    await expect(page.getByText(/M-CNC-01/i).first()).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Knowledge sources' }).first()).toBeVisible()
    await expect(page.getByText(/Seeded LOTO Procedure for M-CNC-01/i).first()).toBeVisible()
    await expect(page.getByText(/Which machine ID/i)).toHaveCount(0)
    await expect(page.getByText('Factory Agent needs attention')).toHaveCount(0)
    await waitForSessionStatus(page, 'COMPLETED')

    const snapshot = await snapshotForPage(page)
    const sources = sourcesFromSnapshot(snapshot)
    expect(snapshot.session.status).toBe('COMPLETED')
    expect(snapshot.session.current_intent).toBe('What LOTO procedure applies before working on it?')
    expect(snapshot.session.replan_context?.contextual_resolution?.machine_id).toBe('M-CNC-01')
    expect(snapshot.session.replan_context?.contextual_resolution?.source).toBe('previous_turn')
    expect(snapshot.steps).toHaveLength(0)
    expect(sources[0].machine_id).toBe('M-CNC-01')
    expect(sources[0].procedure_id).toBe('LOTO-M-CNC-01')

    const finalText = await finalAssistantText(sessionId)
    expectFinalSummaryClaimsOnly(finalText, {
      mustInclude: ['Controlled seeded RAG answer', 'M-CNC-01'],
      mustExclude: [/Which machine/i, /seeded Go API data/i, /Machine M-CNC-01 is RUNNING/i, /Factory Agent needs attention/i],
    })
  })

  test('SO-031 large structured result keeps terminal state visible and details controls usable', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 820 })
    await openChat(page)
    await sendPrompt(page, 'List jobs for Phase 9 large structured result')

    await expect(page.getByText(/Phase 9 large structured result rendered 80 seeded rows/i).first()).toBeVisible()
    await page.getByText('Results (80)').click()
    await expect(page.getByRole('table').first()).toBeVisible()
    await expect(page.getByText('Showing 20 of 80 rows.')).toBeVisible()
    await expect(page.getByText(/JOB-SEED-LARGE-001/i).first()).toBeVisible()
    await expect(page.getByText('Run complete').first()).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)
    await expect(page.getByText(/Gathering information\.\.\.|Working\.\.\.|Understanding your request\.\.\./i)).toHaveCount(0)
    await expect(page.getByText('Factory Agent needs attention')).toHaveCount(0)

    const activityToggle = page.getByRole('button', { name: /Run complete/i }).first()
    await expect(activityToggle).toBeVisible()
    await activityToggle.click()
    await expect(page.getByText(/Phase 9 large structured result rendered 80 seeded rows/i).first()).toBeVisible()
    await page.getByRole('button', { name: /Session activity/i }).first().click()
    await expect(page.getByText(/Phase 9 large structured result rendered 80 seeded rows/i).first()).toBeVisible()

    const dialogOverflows = await page.getByRole('dialog').evaluate((dialog) => dialog.scrollWidth > dialog.clientWidth + 1)
    expect(dialogOverflows).toBe(false)
    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('COMPLETED')
    expect(snapshot.steps[0].result.data).toHaveLength(80)
    expect(snapshot.steps[0].result.data.at(-1).job_id).toBe('JOB-SEED-LARGE-080')
    expect(activityText(snapshot)).toContain('Run complete')
    expect(timelineText(snapshot)).toContain('Phase 9 large structured result rendered 80 seeded rows')
  })

  for (const scenario of phase19CascadeMatrix) {
    test(`${scenario.oracleId} scenario 119/120/121/125: ${scenario.name} uses two approvals and original-state semantics`, async ({ page }) => {
      await resetSeededJobPriorities()
      await runCascadeInvariant(page, scenario, test.info())
    })
  }
})
