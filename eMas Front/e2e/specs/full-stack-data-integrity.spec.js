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
  canonicalJobPriorities,
  currentPriorityMap,
  dataIntegrityAudit,
  expectedCascadePriorities,
  expectedPriorityMapForCascade,
  expectAuditForJobs,
  expectNoSuccessfulAudit,
  factoryAgentRaw,
  jobIdsByPriority,
  originalHighJobIds,
  originalLowJobIds,
  originalMediumJobIds,
  priorityForJob,
  resetSeededJobPriorities,
  sessionMessages,
  sseConnections,
  timelineText,
} from '../support/dataIntegrityScenarios.js'

async function approveApproval(approvalId, decidedBy = 'phase14-playwright') {
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
    })
    .not.toBeNull()
  const pending = await pendingApprovalsForPage(page)
  return pending.find((approval) => approval?.args?.bundle_ui?.write_set === writeSet)
}

test.describe('Phase 14 data integrity and side-effect safety @data-integrity', () => {
  test.describe.configure({ timeout: 90_000 })

  test.beforeEach(async () => {
    await resetSeededJobPriorities()
  })

  test('scenario 86 @data-integrity: cascading priority update uses original-state semantics and two approvals', async ({ page }) => {
    const prompt = 'change all high priority job to low then change all low priority job to medium'
    await openChat(page)
    await sendPrompt(page, prompt)

    const first = await pendingApprovalMatching(page, 'original_high_to_low')
    expect(first.args.bundle_ui.rows.map((row) => row.job_id).sort()).toEqual([...originalHighJobIds].sort())
    expect(first.args.bundle_ui.original_state_semantics).toContain('original low-priority jobs become medium')
    await expect(page.getByText(/Approval 1 required: original HIGH-priority jobs will become LOW/i).first()).toBeVisible()
    await page.getByRole('button', { name: 'Approve' }).click()

    await expect
      .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
      .toBe('WAITING_APPROVAL')
    const second = await pendingApprovalMatching(page, 'original_low_to_medium')
    expect(second.approval_id).not.toBe(first.approval_id)
    expect(second.args.bundle_ui.rows.map((row) => row.job_id).sort()).toEqual([...originalLowJobIds].sort())
    await expect(page.getByText(/Approval 2 required: original LOW-priority jobs will become MEDIUM/i).first()).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText(/Phase 14 cascading priority update complete/i)).toHaveCount(0)
    await page.getByRole('button', { name: 'Approve' }).click()

    await expect
      .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
      .toBe('COMPLETED')
    const sessionId = await activeSessionId(page)
    await page.reload()
    await openChat(page)
    await expect(page.getByText(prompt)).toBeVisible()
    await expect
      .poll(async () => page.locator('body').evaluate((body) => body.innerText), { timeout: 30_000 })
      .toContain('Run complete')
    await expect
      .poll(async () => page.locator('body').evaluate((body) => body.innerText), { timeout: 30_000 })
      .toContain('Phase 14 cascading priority update complete')
    await expect(page.getByText('Run complete')).toBeVisible()

    expect(await currentPriorityMap()).toEqual(expectedCascadePriorities())
    for (const jobId of originalMediumJobIds) {
      expect(await priorityForJob(jobId), `${jobId} should remain medium`).toBe('medium')
    }

    const audit = await dataIntegrityAudit(sessionId)
    expectAuditForJobs(audit, {
      scenario: '86',
      writeSet: 'original_high_to_low',
      approvalId: first.approval_id,
      jobIds: originalHighJobIds,
      requestedPriority: 'low',
    })
    expectAuditForJobs(audit, {
      scenario: '86',
      writeSet: 'original_low_to_medium',
      approvalId: second.approval_id,
      jobIds: originalLowJobIds,
      requestedPriority: 'medium',
    })

    const firstApproval = await factoryAgentJson(`/approvals/${first.approval_id}`)
    const secondApproval = await factoryAgentJson(`/approvals/${second.approval_id}`)
    expect(firstApproval.status).toBe('APPROVED')
    expect(secondApproval.status).toBe('APPROVED')

    const snapshot = await snapshotForPage(page)
    const timelineApprovalIds = approvalIdsFromTimeline(snapshot)
    expect(timelineApprovalIds.has(first.approval_id)).toBe(true)
    expect(timelineApprovalIds.has(second.approval_id)).toBe(true)
    expect(timelineText(snapshot)).toContain('high->low 11')
    expect(timelineText(snapshot)).toContain('low->medium 5')
    expect(activityText(snapshot)).toContain('Run complete')
  })

  test('scenario 86 @data-integrity: medium-to-high then high-to-medium still requires two approvals', async ({ page }) => {
    const prompt = 'change all medium priority job to high then change all high priority job to medium'
    await openChat(page)
    await sendPrompt(page, prompt)

    const first = await pendingApprovalMatching(page, 'original_medium_to_high')
    expect(first.args.bundle_ui.rows.map((row) => row.job_id).sort()).toEqual([...originalMediumJobIds].sort())
    expect(first.args.bundle_ui.original_state_semantics.toLowerCase()).toContain('original high-priority jobs become medium')
    await expect(page.getByText(/Approval 1 required: original MEDIUM-priority jobs will become HIGH/i).first()).toBeVisible()
    await page.getByRole('button', { name: 'Approve' }).click()

    await expect
      .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
      .toBe('WAITING_APPROVAL')
    const second = await pendingApprovalMatching(page, 'original_high_to_medium')
    expect(second.approval_id).not.toBe(first.approval_id)
    expect(second.args.bundle_ui.rows.map((row) => row.job_id).sort()).toEqual([...originalHighJobIds].sort())
    await expect(page.getByText(/Approval 2 required: original HIGH-priority jobs will become MEDIUM/i).first()).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText(/Phase 14 cascading priority update complete/i)).toHaveCount(0)
    await page.getByRole('button', { name: 'Approve' }).click()

    await expect
      .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
      .toBe('COMPLETED')
    const sessionId = await activeSessionId(page)
    expect(await currentPriorityMap()).toEqual(expectedPriorityMapForCascade([
      { source: 'medium', target: 'high' },
      { source: 'high', target: 'medium' },
    ]))
    for (const jobId of jobIdsByPriority('low')) {
      expect(await priorityForJob(jobId), `${jobId} should remain low`).toBe('low')
    }

    const audit = await dataIntegrityAudit(sessionId)
    expectAuditForJobs(audit, {
      scenario: '86',
      writeSet: 'original_medium_to_high',
      approvalId: first.approval_id,
      jobIds: originalMediumJobIds,
      requestedPriority: 'high',
    })
    expectAuditForJobs(audit, {
      scenario: '86',
      writeSet: 'original_high_to_medium',
      approvalId: second.approval_id,
      jobIds: originalHighJobIds,
      requestedPriority: 'medium',
    })

    const snapshot = await snapshotForPage(page)
    expect(approvalIdsFromTimeline(snapshot).has(first.approval_id)).toBe(true)
    expect(approvalIdsFromTimeline(snapshot).has(second.approval_id)).toBe(true)
    expect(timelineText(snapshot)).toContain('medium->high 10')
    expect(timelineText(snapshot)).toContain('high->medium 11')
    expect(activityText(snapshot)).toContain('Run complete')
  })

  test('scenario 87 @data-integrity: bulk partial failure records exact per-row outcomes without false success', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 14 bulk partial failure priority update with exact row outcomes')

    const approval = await pendingApprovalMatching(page, 'bulk_partial_failure')
    await page.getByRole('button', { name: 'Approve' }).click()

    await waitForSessionStatus(page, 'FAILED')
    await expect(page.getByText(/2 succeeded, 1 failed; not all jobs succeeded/i).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toHaveCount(0)

    expect(await priorityForJob('JOB-SEED-005')).toBe('high')
    expect(await priorityForJob('JOB-SEED-009')).toBe('high')
    expect(await priorityForJob('JOB-SEED-012')).toBe(canonicalJobPriorities['JOB-SEED-012'])

    const sessionId = await activeSessionId(page)
    const audit = await dataIntegrityAudit(sessionId)
    expectAuditForJobs(audit, {
      scenario: '87',
      writeSet: 'bulk_partial_failure',
      approvalId: approval.approval_id,
      jobIds: ['JOB-SEED-005', 'JOB-SEED-009'],
      requestedPriority: 'high',
    })
    const failed = audit.filter((entry) => entry.scenario === '87' && entry.status === 'failed')
    expect(failed).toHaveLength(1)
    expect(failed[0].job_id).toBe('JOB-SEED-MISSING-014')
    expect(failed[0].reason).toMatch(/HTTP 404/i)

    const snapshot = await snapshotForPage(page)
    expect(snapshot.steps[0].status).toBe('FAILED')
    expect(timelineText(snapshot)).toContain('not all jobs succeeded')
    expect(timelineText(snapshot)).not.toMatch(/3 succeeded, 0 failed|all 3 jobs succeeded/i)
  })

  test('scenario 88 @data-integrity: approval replay after refresh does not apply the same mutation twice', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 14 idempotent approval replay for one seeded job priority update')

    const approval = await pendingApprovalMatching(page, 'single_idempotent_update')
    await page.getByRole('button', { name: 'Approve' }).dblclick()
    await waitForSessionStatus(page, 'COMPLETED')

    await page.reload()
    await openChat(page)
    const replay = await approveApproval(approval.approval_id, 'phase14-replay-after-refresh')
    expect(replay.status).toBe(200)
    await page.waitForTimeout(500)

    expect(await priorityForJob('JOB-SEED-005')).toBe('high')
    const sessionId = await activeSessionId(page)
    const audit = await dataIntegrityAudit(sessionId)
    const successful = audit.filter((entry) => entry.scenario === '88' && entry.status === 'succeeded')
    expect(successful).toHaveLength(1)
    expect(successful[0].job_id).toBe('JOB-SEED-005')
    expect(successful[0].approval_id).toBe(approval.approval_id)

    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('COMPLETED')
    expect(timelineText(snapshot)).toContain('applied JOB-SEED-005 exactly once')
  })

  test('scenario 89 @data-integrity: stale or expired approvals cannot mutate after session state changes', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 14 stale approval seeded job update')

    const stale = await pendingApprovalMatching(page, 'stale_or_expired_update')
    const staleSessionId = await activeSessionId(page)
    await factoryAgentJson(`/sessions/${staleSessionId}/messages`, {
      method: 'POST',
      body: {
        role: 'user',
        mode: 'normal',
        content: 'Show status for machine M-CNC-01 after superseding the stale Phase 14 approval',
      },
    })
    await expect.poll(async () => (await factoryAgentJson(`/approvals/${stale.approval_id}`)).status).toBe('REJECTED')

    const staleReplay = await approveApproval(stale.approval_id, 'phase14-stale-replay')
    expect(staleReplay.status).toBe(409)
    expect(await priorityForJob('JOB-SEED-005')).toBe('low')
    expectNoSuccessfulAudit(await dataIntegrityAudit(staleSessionId))

    await page.getByRole('button', { name: 'New Session' }).click()
    await sendPrompt(page, 'Run Phase 14 expired approval seeded job update')
    const expired = await pendingApprovalMatching(page, 'stale_or_expired_update')
    const expiredApprove = await approveApproval(expired.approval_id, 'phase14-expired-replay')
    expect(expiredApprove.status).toBe(409)
    await expect.poll(async () => (await factoryAgentJson(`/approvals/${expired.approval_id}`)).status).toBe('EXPIRED')
    expect(await priorityForJob('JOB-SEED-005')).toBe('low')
    expectNoSuccessfulAudit(await dataIntegrityAudit(await activeSessionId(page)))
  })

  test('scenario 90 @data-integrity: audit, DB, SSE timeline, approval id, and final summary agree', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 14 agreement audit timeline summary for seeded job priority updates')

    const approval = await pendingApprovalMatching(page, 'agreement_update')
    await page.getByRole('button', { name: 'Approve' }).click()
    await waitForSessionStatus(page, 'COMPLETED')

    const sessionId = await activeSessionId(page)
    await expect(page.getByText(/Phase 14 agreement complete/i).first()).toBeVisible()
    await expect(page.getByText(/JOB-SEED-005 and JOB-SEED-009 are high priority/i).first()).toBeVisible()
    expect(await priorityForJob('JOB-SEED-005')).toBe('high')
    expect(await priorityForJob('JOB-SEED-009')).toBe('high')

    const audit = await dataIntegrityAudit(sessionId)
    expectAuditForJobs(audit, {
      scenario: '90',
      writeSet: 'agreement_update',
      approvalId: approval.approval_id,
      jobIds: ['JOB-SEED-005', 'JOB-SEED-009'],
      requestedPriority: 'high',
    })

    const snapshot = await snapshotForPage(page)
    const text = timelineText(snapshot)
    expect(text).toContain('JOB-SEED-005 and JOB-SEED-009 are high priority')
    expect(text).toContain(approval.approval_id)
    expect(approvalIdsFromTimeline(snapshot).has(approval.approval_id)).toBe(true)
    expect(activityText(snapshot)).toContain('Run complete')

    await expect
      .poll(async () => {
        const streams = new Set((await sseConnections(sessionId)).map((entry) => entry.stream))
        return streams.has('notification') && streams.has('activity')
      })
      .toBe(true)

    const messages = await sessionMessages(sessionId)
    const finalAssistant = [...messages].reverse().find((message) => message.role === 'assistant')?.content || ''
    expect(finalAssistant).toContain('Phase 14 agreement complete')
    expect(finalAssistant).toContain(approval.approval_id)
  })
})
