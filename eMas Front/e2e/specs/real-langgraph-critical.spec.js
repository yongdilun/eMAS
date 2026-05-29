import { test, expect } from '../support/realLangGraphArtifacts.js'
import { expectTransitionCheckpoint } from '../support/factoryAgentTransitionOracle.js'
import {
  activeSessionId,
  activityText,
  approvalById,
  approvalIdsFromTimeline,
  bundleJobIds,
  currentPriorityMap,
  currentSeededJobRowsById,
  expectedPriorityMapForCascade,
  expectGraphPriorityApproval,
  expectSnapshotApprovalState,
  expectTimelineEvidenceInOrder,
  factoryAgentJson,
  finalAssistantText,
  openChat,
  originalHighJobIds,
  originalLowJobIds,
  originalMediumJobIds,
  pendingApprovalsForPage,
  resetFactoryAgentSessions,
  resetSeededJobPriorities,
  sendPrompt,
  snapshotForPage,
  timelineText,
} from '../support/realLangGraphScenarios.js'

const so001Prompt = 'change all medium priority job to high then change all high priority job to medium'
const so001Changes = [
  { source: 'medium', target: 'high' },
  { source: 'high', target: 'medium' },
]
const so041Prompt = 'change all medium priority job to high then change all high priority job to low'
const so041Changes = [
  { source: 'medium', target: 'high' },
  { source: 'high', target: 'low' },
]

async function pendingApprovalWithRows(page, expectedJobIds) {
  await expect
    .poll(async () => {
      const pending = await pendingApprovalsForPage(page)
      return pending.find((approval) => {
        const rows = approval?.args?.bundle_ui?.rows
        if (!Array.isArray(rows)) return false
        return rows.map((row) => row.job_id).filter(Boolean).sort().join('|') === [...expectedJobIds].sort().join('|')
      })?.approval_id || null
    }, { timeout: 90_000 })
    .not.toBeNull()
  const pending = await pendingApprovalsForPage(page)
  return pending.find((approval) => bundleJobIds(approval).join('|') === [...expectedJobIds].sort().join('|'))
}

async function expectJobsAtPriority(jobIds, priority) {
  await expect
    .poll(async () => {
      const current = await currentPriorityMap()
      return jobIds.every((jobId) => current[jobId] === priority)
    }, { timeout: 30_000 })
    .toBe(true)
}

async function visibleText(page) {
  return page.locator('body').evaluate((body) => body.innerText)
}

function planRows(snapshot) {
  return Array.isArray(snapshot?.steps) ? snapshot.steps : []
}

function expectPlanAuditMatchesRows(snapshot, { jobIds, requestedPriority }) {
  const rows = planRows(snapshot).filter((step) => step.tool_name === 'put__jobs_{id}')
  const matching = rows.filter((step) => jobIds.includes(step.args?.id) && step.args?.priority === requestedPriority)
  expect(matching.map((step) => step.args.id).sort()).toEqual([...jobIds].sort())
  for (const row of matching) {
    expect(row.status).toBe('DONE')
  }
}

test.describe('Phase 7 real LangGraph critical browser proof @critical', () => {
  test.describe.configure({ timeout: 150_000 })

  test.beforeEach(async () => {
    await resetFactoryAgentSessions()
    await resetSeededJobPriorities()
  })

  test('SO-001/SO-035 uses real LangGraph approvals, original-state rows, and terminal evidence', async ({ page }) => {
    const initialRows = await currentSeededJobRowsById()
    await openChat(page)
    await sendPrompt(page, so001Prompt)
    const sessionId = await activeSessionId(page)

    const first = await pendingApprovalWithRows(page, originalMediumJobIds)
    await expectGraphPriorityApproval(first, {
      status: 'PENDING',
      jobIds: originalMediumJobIds,
      requestedPriority: 'high',
      originalPriority: 'medium',
    })
    await expect(page.getByText(`${originalMediumJobIds.length} jobs will be updated from medium to high priority.`).first()).toBeVisible()
    await expect(page.getByText(/Run complete/i)).toHaveCount(0)
    await page.getByRole('button', { name: 'Approve' }).click()

    await expectJobsAtPriority(originalMediumJobIds, 'high')
    await expect
      .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
      .toBe('WAITING_APPROVAL')
    await expect(page.getByText(/Run complete/i)).toHaveCount(0)

    const second = await pendingApprovalWithRows(page, originalHighJobIds)
    expect(second.approval_id).not.toBe(first.approval_id)
    await expectGraphPriorityApproval(first.approval_id, {
      status: 'APPROVED',
      jobIds: originalMediumJobIds,
      requestedPriority: 'high',
      originalPriority: 'medium',
    })
    await expectGraphPriorityApproval(second, {
      status: 'PENDING',
      jobIds: originalHighJobIds,
      requestedPriority: 'medium',
      originalPriority: 'high',
    })
    expect(bundleJobIds(second)).toEqual([...originalHighJobIds].sort())
    expect(bundleJobIds(second)).not.toEqual([...originalMediumJobIds].sort())
    for (const newlyMutatedId of originalMediumJobIds) {
      expect(bundleJobIds(second)).not.toContain(newlyMutatedId)
    }
    await expectSnapshotApprovalState(page, { status: 'WAITING_APPROVAL', pendingApprovalId: second.approval_id })
    await expect(page.getByText(`${originalHighJobIds.length} jobs will be updated from high to medium priority.`).first()).toBeVisible()
    await expect(page.getByText(/Run complete/i)).toHaveCount(0)
    await page.getByRole('button', { name: 'Approve' }).click()

    await expectJobsAtPriority(originalHighJobIds, 'medium')
    await expect
      .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
      .toBe('COMPLETED')
    await expect(page.getByText(/Run complete/i).first()).toBeVisible()
    await expectSnapshotApprovalState(page, { status: 'COMPLETED', pendingApprovalId: null })

    const firstApproval = await approvalById(first.approval_id)
    const secondApproval = await approvalById(second.approval_id)
    expect(firstApproval.status).toBe('APPROVED')
    expect(secondApproval.status).toBe('APPROVED')
    expect(new Date(firstApproval.created_at).getTime()).toBeLessThan(new Date(secondApproval.created_at).getTime())

    expect(await currentPriorityMap()).toEqual(expectedPriorityMapForCascade(so001Changes))
    const finalRows = await currentSeededJobRowsById()
    for (const jobId of originalLowJobIds) {
      expect(finalRows[jobId]).toEqual(initialRows[jobId])
    }
    for (const jobId of originalMediumJobIds) {
      expect(finalRows[jobId].priority).toBe('high')
    }
    for (const jobId of originalHighJobIds) {
      expect(finalRows[jobId].priority).toBe('medium')
    }

    const snapshot = await snapshotForPage(page)
    const timelineApprovalIds = approvalIdsFromTimeline(snapshot)
    expect(timelineApprovalIds.has(first.approval_id)).toBe(true)
    expect(timelineApprovalIds.has(second.approval_id)).toBe(true)
    expect(timelineText(snapshot)).toContain(`${originalMediumJobIds.length} medium-priority jobs`)
    expect(timelineText(snapshot)).toContain(`${originalHighJobIds.length} high-priority jobs`)
    expect(activityText(snapshot)).toContain('Run complete')
    expectPlanAuditMatchesRows(snapshot, { jobIds: originalMediumJobIds, requestedPriority: 'high' })
    expectPlanAuditMatchesRows(snapshot, { jobIds: originalHighJobIds, requestedPriority: 'medium' })
    expectTimelineEvidenceInOrder(snapshot, [
      {
        label: `approval requested ${first.approval_id}`,
        predicate: (event) => event.event_type === 'approval_required' && event.approval_id === first.approval_id,
      },
      {
        label: `approval decided ${first.approval_id}`,
        predicate: (event) => event.event_type === 'approval_decided' && event.approval_id === first.approval_id && event.status === 'APPROVED',
      },
      {
        label: `approval requested ${second.approval_id}`,
        predicate: (event) => event.event_type === 'approval_required' && event.approval_id === second.approval_id,
      },
      {
        label: `approval decided ${second.approval_id}`,
        predicate: (event) => event.event_type === 'approval_decided' && event.approval_id === second.approval_id && event.status === 'APPROVED',
      },
      {
        label: 'terminal session completion',
        predicate: (event) => event.event_type === 'session_completed' && event.status === 'COMPLETED',
      },
    ])

    const finalText = await finalAssistantText(sessionId)
    expect(finalText).toContain('Updated')
    expect(finalText).toContain(`${originalHighJobIds.length}`)
    expect(finalText).not.toMatch(/Factory Agent needs attention/i)
    const finalVisible = await visibleText(page)
    expect(finalVisible).toContain('Run complete')
    expect(finalVisible).not.toMatch(/seeded adapter|Run complete before approval|Factory Agent needs attention/i)
    expect(await factoryAgentJson('/ready')).toMatchObject({
      status: 'ready',
      checks: {
        tool_registry: { ok: true },
      },
    })
  })

  test('RD-001 state transition oracle: SO-041 aggregates both real LangGraph write sets in the final response', async ({ page }, testInfo) => {
    await openChat(page)
    await sendPrompt(page, so041Prompt)
    const sessionId = await activeSessionId(page)

    const first = await pendingApprovalWithRows(page, originalMediumJobIds)
    await expectGraphPriorityApproval(first, {
      status: 'PENDING',
      jobIds: originalMediumJobIds,
      requestedPriority: 'high',
      originalPriority: 'medium',
    })
    const afterSend = await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-001 real LangGraph after send shows approval 1',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'WAITING_APPROVAL',
        responseState: 'waiting_approval',
        pendingApprovalId: first.approval_id,
        visibleBlockTypes: ['approval_required'],
        visibleBlockIds: [`approval:${first.approval_id}`],
        backendBlockTypes: ['approval_required'],
        approvalActionCount: 2,
        textIncludes: [
          new RegExp(`${originalMediumJobIds.length} (?:jobs .*medium.*high|original medium-priority jobs)`, 'i'),
        ],
        textExcludes: [/Run complete/i],
      },
    })
    await page.getByRole('button', { name: 'Approve' }).click()

    await expectJobsAtPriority(originalMediumJobIds, 'high')
    await expect
      .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
      .toBe('WAITING_APPROVAL')
    await expect(page.getByText(/Run complete/i)).toHaveCount(0)

    const second = await pendingApprovalWithRows(page, originalHighJobIds)
    expect(second.approval_id).not.toBe(first.approval_id)
    await expectGraphPriorityApproval(second, {
      status: 'PENDING',
      jobIds: originalHighJobIds,
      requestedPriority: 'low',
      originalPriority: 'high',
    })
    expect(bundleJobIds(second)).toEqual([...originalHighJobIds].sort())
    for (const newlyMutatedId of originalMediumJobIds) {
      expect(bundleJobIds(second)).not.toContain(newlyMutatedId)
    }
    await expect(page.getByText(`${originalHighJobIds.length} jobs will be updated from high to low priority.`).first()).toBeVisible()
    const afterApproval1 = await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-001 real LangGraph after approval 1 shows distinct approval 2',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'WAITING_APPROVAL',
        responseState: 'waiting_approval',
        pendingApprovalId: second.approval_id,
        pendingApprovalMustDifferFrom: first.approval_id,
        revisionGreaterThan: afterSend.backend.responseDocumentRevision,
        visibleBlockTypes: ['approval_required'],
        visibleBlockIds: [`approval:${second.approval_id}`],
        hiddenBlockIds: [`approval:${first.approval_id}`],
        backendBlockTypes: ['approval_required'],
        approvalActionCount: 2,
        forbidWaitingApproval1: true,
        textIncludes: [
          new RegExp(`${originalHighJobIds.length} (?:jobs .*high.*low|original high-priority jobs)`, 'i'),
        ],
        textExcludes: [/Run complete/i],
      },
    })
    const secondApprovalVisible = await visibleText(page)
    expect(secondApprovalVisible).not.toMatch(/Improving the response\s+Current|Current\s+Improving the response/i)
    expect(secondApprovalVisible).not.toContain(`${originalMediumJobIds.length} jobs will be updated from medium to high priority.`)
    await page.getByRole('button', { name: 'Approve' }).click()

    await expectJobsAtPriority(originalHighJobIds, 'low')
    await expect
      .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
      .toBe('COMPLETED')
    await expectSnapshotApprovalState(page, { status: 'COMPLETED', pendingApprovalId: null })
    expect(await currentPriorityMap()).toEqual(expectedPriorityMapForCascade(so041Changes))
    const mediumBusinessGroupText = new RegExp(`(?:Original )?Medium -> High: ${originalMediumJobIds.length} jobs`, 'i')
    const highBusinessGroupText = new RegExp(`(?:Original )?High -> Low: ${originalHighJobIds.length} jobs`, 'i')
    await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-001 real LangGraph after final approval shows aggregate completion',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        revisionGreaterThan: afterApproval1.backend.responseDocumentRevision,
        visibleBlockTypes: ['result_summary'],
        hiddenBlockTypes: ['approval_required'],
        hiddenBlockIds: [`approval:${first.approval_id}`, `approval:${second.approval_id}`],
        hiddenBackendBlockTypes: ['approval_required'],
        responseContracts: ['business_change_v1'],
        approvalActionCount: 0,
        textIncludes: [
          /Run complete/i,
          mediumBusinessGroupText,
          highBusinessGroupText,
        ],
        textExcludes: [/Waiting for approval/i, /Approval required/i],
        finalResponseQuality: {
          finalResultCardCount: 1,
          finalSummaryText: /21 jobs across 2 approved business changes/i,
          businessGroups: [
            {
              labelPattern: /^(?:Original )?Medium -> High$/,
              count: originalMediumJobIds.length,
              contract: 'business_change_v1',
              entityType: 'job',
              fieldChangeCountMin: 1,
            },
            {
              labelPattern: /^(?:Original )?High -> Low$/,
              count: originalHighJobIds.length,
              contract: 'business_change_v1',
              entityType: 'job',
              fieldChangeCountMin: 1,
            },
          ],
          affectedRecordPreviewMin: 1,
          affectedRecordPreviewMax: 5,
          expandableAuditPresent: true,
          forbidDuplicateAffectedRecords: true,
        },
      },
    })
    const finalVisible = await visibleText(page)
    expect(finalVisible).not.toMatch(/Approved request to change record/i)
    expect(finalVisible).not.toMatch(/Waiting for your approval|Please approve to continue/i)
    expect(finalVisible).not.toMatch(/Affected records \(11\)/i)

    const snapshot = await snapshotForPage(page)
    const timelineApprovalIds = approvalIdsFromTimeline(snapshot)
    expect(timelineApprovalIds.has(first.approval_id)).toBe(true)
    expect(timelineApprovalIds.has(second.approval_id)).toBe(true)
    expectPlanAuditMatchesRows(snapshot, { jobIds: originalMediumJobIds, requestedPriority: 'high' })
    expectPlanAuditMatchesRows(snapshot, { jobIds: originalHighJobIds, requestedPriority: 'low' })

    const finalText = await finalAssistantText(sessionId)
    expect(finalText).not.toContain(`Updated **${originalMediumJobIds.length}** job(s).`)
    expect(finalText).not.toMatch(/Factory Agent needs attention/i)
  })

  test('SO-026 resolves a LOTO follow-up pronoun before the real LangGraph route gate', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'What is the status of M-CNC-01?')
    const sessionId = await activeSessionId(page)

    await expect(page.getByText(/M-CNC-01/i).first()).toBeVisible({ timeout: 30_000 })
    await expect
      .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
      .toBe('COMPLETED')
    const firstFinal = await finalAssistantText(sessionId)
    expect(firstFinal).toMatch(/M-CNC-01/i)

    const followupPrompt = 'What LOTO procedure applies before working on it?'
    await sendPrompt(page, followupPrompt)
    await expect
      .poll(async () => {
        const latest = await snapshotForPage(page)
        const resolution = latest.session.replan_context?.contextual_resolution
        return {
          intent: latest.session.current_intent,
          machineId: resolution?.machine_id || null,
          source: resolution?.source || null,
          status: latest.session.status,
        }
      }, { timeout: 45_000 })
      .toMatchObject({
        intent: followupPrompt,
        machineId: 'M-CNC-01',
        source: 'previous_turn',
      })

    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).not.toBe('FAILED')
    expect(snapshot.session.status).not.toBe('BLOCKED')
    expect(snapshot.session.current_intent).toBe(followupPrompt)
    expect(snapshot.session.replan_context?.contextual_resolution?.machine_id).toBe('M-CNC-01')
    expect(snapshot.session.replan_context?.contextual_resolution?.source).toBe('previous_turn')
    const finalVisible = await visibleText(page)
    expect(finalVisible).not.toMatch(/Which machine ID should I use|Factory Agent needs attention/i)
  })
})
