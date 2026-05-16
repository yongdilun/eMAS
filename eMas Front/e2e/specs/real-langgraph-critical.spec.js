import { test, expect } from '../support/realLangGraphArtifacts.js'
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

async function pendingApprovalWithRows(page, expectedJobIds) {
  await expect
    .poll(async () => {
      const pending = await pendingApprovalsForPage(page)
      return pending.find((approval) => {
        const rows = approval?.args?.bundle_ui?.rows
        if (!Array.isArray(rows)) return false
        return rows.map((row) => row.job_id).filter(Boolean).sort().join('|') === [...expectedJobIds].sort().join('|')
      })?.approval_id || null
    }, { timeout: 30_000 })
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
    await resetSeededJobPriorities()
  })

  test('SO-001 uses real LangGraph approvals, original-state rows, and terminal evidence', async ({ page }) => {
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
    expect(await visibleText(page)).toContain('Run complete')
    expect(await factoryAgentJson('/ready')).toMatchObject({
      status: 'ready',
      checks: {
        tool_registry: { ok: true },
      },
    })
  })
})
