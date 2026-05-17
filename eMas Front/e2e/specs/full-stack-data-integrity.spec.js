import { expect, test } from '../support/seededArtifacts.js'
import { chatSelectors } from '../fixtures/selectors.js'
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
  captureFinalSeededState,
  captureInitialSeededState,
  approvalIdsFromTimeline,
  canonicalJobPriorities,
  currentPriorityMap,
  dataIntegrityAudit,
  expectedCascadePriorities,
  expectedPriorityMapForCascade,
  expectApprovalRowMatches,
  expectAuditCommit,
  expectAuditForJobs,
  expectCascadeTimelineEvidence,
  expectFinalSummaryClaimsOnly,
  expectNoSuccessfulAudit,
  expectRowsUnchangedFromInitial,
  expectSnapshotApprovalState,
  expectTimelineEvidenceInOrder,
  expectUnchangedRowsMatch,
  factoryAgentRaw,
  jobIdsByPriority,
  originalHighJobIds,
  originalLowJobIds,
  originalMediumJobIds,
  priorityForJob,
  recordOracleCheckpoint,
  resetSeededJobPriorities,
  sessionMessages,
  sseConnections,
  timelineText,
  withSeededOracleArtifact,
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

async function finalAssistantText(sessionId) {
  const messages = await sessionMessages(sessionId)
  return [...messages].reverse().find((message) => message.role === 'assistant')?.content || ''
}

async function visibleText(page) {
  return page.locator('body').evaluate((body) => body.innerText)
}

async function runPhase6Oracle(testInfo, name, page, body) {
  return withSeededOracleArtifact(testInfo, name, async (artifact) => {
    const initial = await captureInitialSeededState(artifact)
    let sessionId = null
    try {
      return await body({
        artifact,
        initial,
        setSessionId(value) {
          sessionId = value
        },
      })
    } finally {
      await captureFinalSeededState(artifact, { page, sessionId }).catch(() => null)
    }
  })
}

test.describe('Phase 14 data integrity and side-effect safety @data-integrity', () => {
  test.describe.configure({ timeout: 90_000 })

  test.beforeEach(async () => {
    await resetSeededJobPriorities()
  })

  test('SO-002 scenario 86 @data-integrity: cascading priority update uses original-state semantics and two approvals', async ({ page }, testInfo) => runPhase6Oracle(testInfo, 'SO-002 scenario 86 high-to-low original-low-to-medium', page, async ({ artifact, initial, setSessionId }) => {
    const prompt = 'change all high priority job to low then change all low priority job to medium'
    await openChat(page)
    await sendPrompt(page, prompt)
    const sessionId = await activeSessionId(page)
    setSessionId(sessionId)

    const first = await pendingApprovalMatching(page, 'original_high_to_low')
    await expectApprovalRowMatches(first, {
      status: 'PENDING',
      writeSet: 'original_high_to_low',
      kind: 'phase14_cascade_priority',
      jobIds: originalHighJobIds,
      requestedPriority: 'low',
      originalPriority: 'high',
      count: originalHighJobIds.length,
    })
    expect(first.args.bundle_ui.rows.map((row) => row.job_id).sort()).toEqual([...originalHighJobIds].sort())
    expect(first.args.bundle_ui.original_state_semantics).toContain('original low-priority jobs become medium')
    await expect(page.getByText(/Approval 1 required: original HIGH-priority jobs will become LOW/i).first()).toBeVisible()
    await page.getByRole('button', { name: 'Approve' }).click()

    await expect
      .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
      .toBe('WAITING_APPROVAL')
    const second = await pendingApprovalMatching(page, 'original_low_to_medium')
    await expectApprovalRowMatches(first.approval_id, {
      status: 'APPROVED',
      writeSet: 'original_high_to_low',
      kind: 'phase14_cascade_priority',
      jobIds: originalHighJobIds,
      requestedPriority: 'low',
      originalPriority: 'high',
      count: originalHighJobIds.length,
    })
    expectAuditCommit(await dataIntegrityAudit(sessionId), {
      scenario: '86',
      writeSet: 'original_high_to_low',
      approvalId: first.approval_id,
      succeededJobIds: originalHighJobIds,
      requestedPriority: 'low',
    })
    await expectRowsUnchangedFromInitial(initial.rowsById, [...originalLowJobIds, ...originalMediumJobIds])
    await expectSnapshotApprovalState(page, { status: 'WAITING_APPROVAL', pendingApprovalId: second.approval_id })
    recordOracleCheckpoint(artifact, 'after first approval commit', {
      approval: await factoryAgentJson(`/approvals/${first.approval_id}`),
      audit: await dataIntegrityAudit(sessionId),
      priorities: await currentPriorityMap(),
      snapshot: await snapshotForPage(page),
    })
    expect(second.approval_id).not.toBe(first.approval_id)
    await expectApprovalRowMatches(second, {
      status: 'PENDING',
      writeSet: 'original_low_to_medium',
      kind: 'phase14_cascade_priority',
      jobIds: originalLowJobIds,
      requestedPriority: 'medium',
      originalPriority: 'low',
      previousApprovalId: first.approval_id,
      count: originalLowJobIds.length,
    })
    expect(second.args.bundle_ui.rows.map((row) => row.job_id).sort()).toEqual([...originalLowJobIds].sort())
    await expect(page.getByText(/Approval 2 required: original LOW-priority jobs will become MEDIUM/i).first()).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText(/Phase 14 cascading priority update complete/i)).toHaveCount(0)
    await page.getByRole('button', { name: 'Approve' }).click()

    await expect
      .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
      .toBe('COMPLETED')
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

    await expectApprovalRowMatches(second.approval_id, {
      status: 'APPROVED',
      writeSet: 'original_low_to_medium',
      kind: 'phase14_cascade_priority',
      jobIds: originalLowJobIds,
      requestedPriority: 'medium',
      originalPriority: 'low',
      previousApprovalId: first.approval_id,
      count: originalLowJobIds.length,
    })
    await expectSnapshotApprovalState(page, { status: 'COMPLETED', pendingApprovalId: null })
    expect(await currentPriorityMap()).toEqual(expectedCascadePriorities())
    await expectRowsUnchangedFromInitial(initial.rowsById, originalMediumJobIds)

    const audit = await dataIntegrityAudit(sessionId)
    expectAuditCommit(audit, {
      scenario: '86',
      writeSet: 'original_high_to_low',
      approvalId: first.approval_id,
      succeededJobIds: originalHighJobIds,
      requestedPriority: 'low',
    })
    expectAuditCommit(audit, {
      scenario: '86',
      writeSet: 'original_low_to_medium',
      approvalId: second.approval_id,
      succeededJobIds: originalLowJobIds,
      requestedPriority: 'medium',
    })
    expectAuditForJobs(audit, {
      scenario: '86',
      writeSet: 'original_high_to_low',
      approvalId: first.approval_id,
      jobIds: originalHighJobIds,
      requestedPriority: 'low',
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
    expectCascadeTimelineEvidence(snapshot, {
      firstApprovalId: first.approval_id,
      secondApprovalId: second.approval_id,
      firstSummary: 'changed original HIGH jobs to LOW',
      secondSummary: 'high->low 11',
    })
    expectFinalSummaryClaimsOnly(await finalAssistantText(sessionId), {
      mustInclude: ['Phase 14 cascading priority update complete', 'high->low 11', 'low->medium 5', 'medium unchanged 10'],
      mustExclude: [/Factory Agent needs attention/i, /3 succeeded, 0 failed/i],
    })
    expectFinalSummaryClaimsOnly(await visibleText(page), {
      mustInclude: ['Phase 14 cascading priority update complete', 'Run complete'],
      mustExclude: [/Factory Agent needs attention/i],
    })
  }))

  test('SO-001 scenario 86 @data-integrity: medium-to-high then high-to-medium still requires two approvals', async ({ page }, testInfo) => runPhase6Oracle(testInfo, 'SO-001 scenario 86 medium-to-high original-high-to-medium', page, async ({ artifact, initial, setSessionId }) => {
    const prompt = 'change all medium priority job to high then change all high priority job to medium'
    await openChat(page)
    await sendPrompt(page, prompt)
    const sessionId = await activeSessionId(page)
    setSessionId(sessionId)

    const first = await pendingApprovalMatching(page, 'original_medium_to_high')
    await expectApprovalRowMatches(first, {
      status: 'PENDING',
      writeSet: 'original_medium_to_high',
      kind: 'phase14_cascade_priority',
      jobIds: originalMediumJobIds,
      requestedPriority: 'high',
      originalPriority: 'medium',
      count: originalMediumJobIds.length,
    })
    expect(first.args.bundle_ui.rows.map((row) => row.job_id).sort()).toEqual([...originalMediumJobIds].sort())
    expect(first.args.bundle_ui.original_state_semantics.toLowerCase()).toContain('original high-priority jobs become medium')
    await expect(page.getByText(/Approval 1 required: original MEDIUM-priority jobs will become HIGH/i).first()).toBeVisible()
    await page.getByRole('button', { name: 'Approve' }).click()

    await expect
      .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
      .toBe('WAITING_APPROVAL')
    const second = await pendingApprovalMatching(page, 'original_high_to_medium')
    await expectApprovalRowMatches(first.approval_id, {
      status: 'APPROVED',
      writeSet: 'original_medium_to_high',
      kind: 'phase14_cascade_priority',
      jobIds: originalMediumJobIds,
      requestedPriority: 'high',
      originalPriority: 'medium',
      count: originalMediumJobIds.length,
    })
    expectAuditCommit(await dataIntegrityAudit(sessionId), {
      scenario: '86',
      writeSet: 'original_medium_to_high',
      approvalId: first.approval_id,
      succeededJobIds: originalMediumJobIds,
      requestedPriority: 'high',
    })
    await expectRowsUnchangedFromInitial(initial.rowsById, [...originalHighJobIds, ...originalLowJobIds])
    await expectSnapshotApprovalState(page, { status: 'WAITING_APPROVAL', pendingApprovalId: second.approval_id })
    recordOracleCheckpoint(artifact, 'after first approval commit', {
      approval: await factoryAgentJson(`/approvals/${first.approval_id}`),
      audit: await dataIntegrityAudit(sessionId),
      priorities: await currentPriorityMap(),
      snapshot: await snapshotForPage(page),
    })
    expect(second.approval_id).not.toBe(first.approval_id)
    await expectApprovalRowMatches(second, {
      status: 'PENDING',
      writeSet: 'original_high_to_medium',
      kind: 'phase14_cascade_priority',
      jobIds: originalHighJobIds,
      requestedPriority: 'medium',
      originalPriority: 'high',
      previousApprovalId: first.approval_id,
      count: originalHighJobIds.length,
    })
    expect(second.args.bundle_ui.rows.map((row) => row.job_id).sort()).toEqual([...originalHighJobIds].sort())
    await expect(page.getByText(/Approval 2 required: original HIGH-priority jobs will become MEDIUM/i).first()).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText(/Phase 14 cascading priority update complete/i)).toHaveCount(0)
    await page.getByRole('button', { name: 'Approve' }).click()

    await expect
      .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
      .toBe('COMPLETED')
    await expectApprovalRowMatches(second.approval_id, {
      status: 'APPROVED',
      writeSet: 'original_high_to_medium',
      kind: 'phase14_cascade_priority',
      jobIds: originalHighJobIds,
      requestedPriority: 'medium',
      originalPriority: 'high',
      previousApprovalId: first.approval_id,
      count: originalHighJobIds.length,
    })
    await expectSnapshotApprovalState(page, { status: 'COMPLETED', pendingApprovalId: null })
    expect(await currentPriorityMap()).toEqual(expectedPriorityMapForCascade([
      { source: 'medium', target: 'high' },
      { source: 'high', target: 'medium' },
    ]))
    await expectRowsUnchangedFromInitial(initial.rowsById, jobIdsByPriority('low'))

    const audit = await dataIntegrityAudit(sessionId)
    expectAuditCommit(audit, {
      scenario: '86',
      writeSet: 'original_medium_to_high',
      approvalId: first.approval_id,
      succeededJobIds: originalMediumJobIds,
      requestedPriority: 'high',
    })
    expectAuditCommit(audit, {
      scenario: '86',
      writeSet: 'original_high_to_medium',
      approvalId: second.approval_id,
      succeededJobIds: originalHighJobIds,
      requestedPriority: 'medium',
    })

    const snapshot = await snapshotForPage(page)
    expect(approvalIdsFromTimeline(snapshot).has(first.approval_id)).toBe(true)
    expect(approvalIdsFromTimeline(snapshot).has(second.approval_id)).toBe(true)
    expect(timelineText(snapshot)).toContain('medium->high 10')
    expect(timelineText(snapshot)).toContain('high->medium 11')
    expect(activityText(snapshot)).toContain('Run complete')
    expectCascadeTimelineEvidence(snapshot, {
      firstApprovalId: first.approval_id,
      secondApprovalId: second.approval_id,
      firstSummary: 'changed original MEDIUM jobs to HIGH',
      secondSummary: 'medium->high 10',
    })
    expectFinalSummaryClaimsOnly(await finalAssistantText(sessionId), {
      mustInclude: ['Phase 14 cascading priority update complete', 'medium->high 10', 'high->medium 11', 'low unchanged 5'],
      mustExclude: [/all high priority jobs changed to medium/i, /Factory Agent needs attention/i],
    })
    await expect
      .poll(async () => visibleText(page), { timeout: 30_000 })
      .toContain('Phase 14 cascading priority update complete')
    await expect
      .poll(async () => visibleText(page), { timeout: 30_000 })
      .toContain('Run complete')
    expectFinalSummaryClaimsOnly(await visibleText(page), {
      mustInclude: ['Phase 14 cascading priority update complete', 'Run complete'],
      mustExclude: [/Factory Agent needs attention/i],
    })
  }))

  test('SO-005 scenario 86 @data-integrity: rejecting approval 2 stops cascade without hidden second commit', async ({ page }, testInfo) => runPhase6Oracle(testInfo, 'SO-005 scenario 86 approval 2 rejected no hidden commit', page, async ({ artifact, initial, setSessionId }) => {
    const prompt = 'change all medium priority job to high then change all high priority job to low'
    await openChat(page)
    await sendPrompt(page, prompt)
    const sessionId = await activeSessionId(page)
    setSessionId(sessionId)

    const first = await pendingApprovalMatching(page, 'original_medium_to_high')
    await expectApprovalRowMatches(first, {
      status: 'PENDING',
      writeSet: 'original_medium_to_high',
      kind: 'phase14_cascade_priority',
      jobIds: originalMediumJobIds,
      requestedPriority: 'high',
      originalPriority: 'medium',
      count: originalMediumJobIds.length,
    })
    expect(first.args.bundle_ui.rows.map((row) => row.job_id).sort()).toEqual([...originalMediumJobIds].sort())
    await expect(page.getByText(/Approval 1 required: original MEDIUM-priority jobs will become HIGH/i).first()).toBeVisible()
    await page.getByRole('button', { name: 'Approve' }).click()

    await expect
      .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 30_000 })
      .toBe('WAITING_APPROVAL')
    const second = await pendingApprovalMatching(page, 'original_high_to_low')
    expect(second.approval_id).not.toBe(first.approval_id)
    await expectApprovalRowMatches(first.approval_id, {
      status: 'APPROVED',
      writeSet: 'original_medium_to_high',
      kind: 'phase14_cascade_priority',
      jobIds: originalMediumJobIds,
      requestedPriority: 'high',
      originalPriority: 'medium',
      count: originalMediumJobIds.length,
    })
    await expectSnapshotApprovalState(page, { status: 'WAITING_APPROVAL', pendingApprovalId: second.approval_id })
    expect(await currentPriorityMap()).toEqual(expectedPriorityMapForCascade([{ source: 'medium', target: 'high' }]))
    await expectRowsUnchangedFromInitial(initial.rowsById, [...originalHighJobIds, ...originalLowJobIds])
    expectAuditCommit(await dataIntegrityAudit(sessionId), {
      scenario: '86',
      writeSet: 'original_medium_to_high',
      approvalId: first.approval_id,
      succeededJobIds: originalMediumJobIds,
      requestedPriority: 'high',
    })
    recordOracleCheckpoint(artifact, 'after first approval before rejecting approval 2', {
      firstApproval: await factoryAgentJson(`/approvals/${first.approval_id}`),
      secondApproval: await factoryAgentJson(`/approvals/${second.approval_id}`),
      audit: await dataIntegrityAudit(sessionId),
      priorities: await currentPriorityMap(),
      snapshot: await snapshotForPage(page),
    })

    await expectApprovalRowMatches(second, {
      status: 'PENDING',
      writeSet: 'original_high_to_low',
      kind: 'phase14_cascade_priority',
      jobIds: originalHighJobIds,
      requestedPriority: 'low',
      originalPriority: 'high',
      previousApprovalId: first.approval_id,
      count: originalHighJobIds.length,
    })
    expect(second.args.bundle_ui.rows.map((row) => row.job_id).sort()).toEqual([...originalHighJobIds].sort())
    for (const newlyHighId of originalMediumJobIds) {
      expect(second.args.bundle_ui.rows.map((row) => row.job_id)).not.toContain(newlyHighId)
    }
    await expect(page.getByText(/Approval 2 required: original HIGH-priority jobs will become LOW/i).first()).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText(/Run complete/i)).toHaveCount(0)
    await expect(page.getByText(/Phase 14 cascading priority update complete/i)).toHaveCount(0)

    const rejectionReason = 'SO-005 second approval rejected; stop before second write.'
    await page.getByPlaceholder('Optional rejection reason').fill(rejectionReason)
    await page.getByRole('button', { name: 'Reject' }).click()

    await expect
      .poll(async () => (await factoryAgentJson(`/approvals/${second.approval_id}`)).status, { timeout: 30_000 })
      .toBe('REJECTED')
    await expectApprovalRowMatches(second.approval_id, {
      status: 'REJECTED',
      writeSet: 'original_high_to_low',
      kind: 'phase14_cascade_priority',
      jobIds: originalHighJobIds,
      requestedPriority: 'low',
      originalPriority: 'high',
      previousApprovalId: first.approval_id,
      count: originalHighJobIds.length,
    })
    await expectSnapshotApprovalState(page, { status: 'IDLE', pendingApprovalId: null })

    const afterRejectPriorities = await currentPriorityMap()
    expect(afterRejectPriorities).toEqual(expectedPriorityMapForCascade([{ source: 'medium', target: 'high' }]))
    for (const jobId of originalMediumJobIds) expect(afterRejectPriorities[jobId]).toBe('high')
    for (const jobId of originalHighJobIds) expect(afterRejectPriorities[jobId]).toBe('high')
    await expectRowsUnchangedFromInitial(initial.rowsById, [...originalHighJobIds, ...originalLowJobIds])

    const audit = await dataIntegrityAudit(sessionId)
    expectAuditCommit(audit, {
      scenario: '86',
      writeSet: 'original_medium_to_high',
      approvalId: first.approval_id,
      succeededJobIds: originalMediumJobIds,
      requestedPriority: 'high',
    })
    expectAuditForJobs(audit, {
      scenario: '86',
      writeSet: 'original_medium_to_high',
      approvalId: first.approval_id,
      jobIds: originalMediumJobIds,
      requestedPriority: 'high',
    })
    expect(audit.filter((entry) => entry.approval_id === second.approval_id)).toEqual([])

    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('IDLE')
    expect(approvalIdsFromTimeline(snapshot).has(first.approval_id)).toBe(true)
    expect(approvalIdsFromTimeline(snapshot).has(second.approval_id)).toBe(true)
    expect(timelineText(snapshot)).toMatch(/rejected/i)
    expect(timelineText(snapshot)).not.toMatch(/high->low 11|original high priority jobs changed to low|all changes succeeded/i)
    expect(activityText(snapshot)).not.toContain('Run complete')
    expectTimelineEvidenceInOrder(snapshot, [
      {
        label: `approval 1 requested ${first.approval_id}`,
        predicate: (event) => event.event_type === 'approval_required' && event.approval_id === first.approval_id,
      },
      {
        label: `approval 1 accepted ${first.approval_id}`,
        predicate: (event) => event.event_type === 'approval_decided' && event.approval_id === first.approval_id && event.status === 'APPROVED',
      },
      {
        label: `approval 2 requested ${second.approval_id}`,
        predicate: (event) => event.event_type === 'approval_required' && event.approval_id === second.approval_id,
      },
      {
        label: `approval 2 rejected ${second.approval_id}`,
        predicate: (event) => event.event_type === 'approval_decided' && event.approval_id === second.approval_id && event.status === 'REJECTED',
      },
    ])

    await expect
      .poll(async () => visibleText(page), { timeout: 30_000 })
      .toMatch(/SO-005 second approval rejected|approval .*rejected|rejected .*approval|stopped/i)
    expectFinalSummaryClaimsOnly(await visibleText(page), {
      mustInclude: [/SO-005 second approval rejected|approval .*rejected|rejected .*approval|stopped/i],
      mustExclude: [
        /Run complete/i,
        /all changes succeeded/i,
        /all requested changes completed/i,
        /Phase 14 cascading priority update complete/i,
        /high->low 11/i,
        /original high priority jobs changed to low/i,
      ],
    })
    expectFinalSummaryClaimsOnly(await finalAssistantText(sessionId), {
      mustInclude: [],
      mustExclude: [/Run complete/i, /all changes succeeded/i, /high->low 11/i, /original high priority jobs changed to low/i],
    })
  }))

  test('SO-009 scenario 87 @data-integrity: bulk partial failure records exact per-row outcomes without false success', async ({ page }, testInfo) => runPhase6Oracle(testInfo, 'SO-009 scenario 87 partial bulk failure no overclaim', page, async ({ initial, setSessionId }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 14 bulk partial failure priority update with exact row outcomes')
    const sessionId = await activeSessionId(page)
    setSessionId(sessionId)

    const approval = await pendingApprovalMatching(page, 'bulk_partial_failure')
    await expectApprovalRowMatches(approval, {
      status: 'PENDING',
      writeSet: 'bulk_partial_failure',
      kind: 'phase14_partial_failure',
      jobIds: ['JOB-SEED-005', 'JOB-SEED-009', 'JOB-SEED-MISSING-014'],
      requestedPriority: 'high',
      count: 3,
    })
    await page.getByRole('button', { name: 'Approve' }).click()

    await waitForSessionStatus(page, 'FAILED')
    await expectApprovalRowMatches(approval.approval_id, {
      status: 'APPROVED',
      writeSet: 'bulk_partial_failure',
      kind: 'phase14_partial_failure',
      jobIds: ['JOB-SEED-005', 'JOB-SEED-009', 'JOB-SEED-MISSING-014'],
      requestedPriority: 'high',
      count: 3,
    })
    await expectSnapshotApprovalState(page, { status: 'FAILED', pendingApprovalId: null })
    await expect(page.getByText(/2 succeeded, 1 failed[\s\S]*not all jobs succeeded/i).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toHaveCount(0)

    expect(await priorityForJob('JOB-SEED-005')).toBe('high')
    expect(await priorityForJob('JOB-SEED-009')).toBe('high')
    expect(await priorityForJob('JOB-SEED-012')).toBe(canonicalJobPriorities['JOB-SEED-012'])
    await expectRowsUnchangedFromInitial(
      initial.rowsById,
      Object.keys(canonicalJobPriorities).filter((jobId) => !['JOB-SEED-005', 'JOB-SEED-009'].includes(jobId)),
    )

    const audit = await dataIntegrityAudit(sessionId)
    expectAuditCommit(audit, {
      scenario: '87',
      writeSet: 'bulk_partial_failure',
      approvalId: approval.approval_id,
      succeededJobIds: ['JOB-SEED-005', 'JOB-SEED-009'],
      failedJobIds: ['JOB-SEED-MISSING-014'],
      requestedPriority: 'high',
    })
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
    expectTimelineEvidenceInOrder(snapshot, [
      {
        label: `approval requested ${approval.approval_id}`,
        predicate: (event) => event.event_type === 'approval_required' && event.approval_id === approval.approval_id,
      },
      {
        label: `approval decided ${approval.approval_id}`,
        predicate: (event) => event.event_type === 'approval_decided' && event.approval_id === approval.approval_id && event.status === 'APPROVED',
      },
      {
        label: 'partial failure commit evidence',
        predicate: (event) => event.event_type === 'tool_result' && event.status === 'FAILED' && String(event.content || '').includes('2 succeeded, 1 failed'),
      },
      {
        label: 'terminal failed session evidence',
        predicate: (event) => event.event_type === 'session_failed' && event.status === 'FAILED',
      },
    ])
    expectFinalSummaryClaimsOnly(await visibleText(page), {
      mustInclude: [/2 succeeded, 1 failed[\s\S]*not all jobs succeeded/i, 'JOB-SEED-MISSING-014'],
      mustExclude: [/Run complete/i, /3 succeeded, 0 failed/i, /all 3 jobs succeeded/i],
    })
    expectFinalSummaryClaimsOnly(await finalAssistantText(sessionId), {
      mustInclude: ['2 succeeded, 1 failed', 'not all jobs succeeded', approval.approval_id],
      mustExclude: [/3 low priority jobs changed to high/i, /all requested changes completed/i],
    })
  }))

  test('SO-007/SO-018 scenario 88 @data-integrity: approval replay after refresh does not apply the same mutation twice', async ({ page }, testInfo) => runPhase6Oracle(testInfo, 'SO-007 SO-018 scenario 88 duplicate approval replay suppressed', page, async ({ initial, setSessionId }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 14 idempotent approval replay for one seeded job priority update')
    const sessionId = await activeSessionId(page)
    setSessionId(sessionId)

    const approval = await pendingApprovalMatching(page, 'single_idempotent_update')
    await expectApprovalRowMatches(approval, {
      status: 'PENDING',
      writeSet: 'single_idempotent_update',
      kind: 'phase14_idempotent_replay',
      jobIds: ['JOB-SEED-005'],
      requestedPriority: 'high',
      count: 1,
    })
    await page.getByRole('button', { name: 'Approve' }).dblclick()
    await waitForSessionStatus(page, 'COMPLETED')
    await expectApprovalRowMatches(approval.approval_id, {
      status: 'APPROVED',
      writeSet: 'single_idempotent_update',
      kind: 'phase14_idempotent_replay',
      jobIds: ['JOB-SEED-005'],
      requestedPriority: 'high',
      count: 1,
    })
    await expectSnapshotApprovalState(page, { status: 'COMPLETED', pendingApprovalId: null })

    await page.reload()
    await openChat(page)
    const replay = await approveApproval(approval.approval_id, 'phase14-replay-after-refresh')
    expect(replay.status).toBe(200)
    await page.waitForTimeout(500)

    expect(await priorityForJob('JOB-SEED-005')).toBe('high')
    await expectRowsUnchangedFromInitial(
      initial.rowsById,
      Object.keys(canonicalJobPriorities).filter((jobId) => jobId !== 'JOB-SEED-005'),
    )
    const audit = await dataIntegrityAudit(sessionId)
    expectAuditCommit(audit, {
      scenario: '88',
      writeSet: 'single_idempotent_update',
      approvalId: approval.approval_id,
      succeededJobIds: ['JOB-SEED-005'],
      requestedPriority: 'high',
    })
    const successful = audit.filter((entry) => entry.scenario === '88' && entry.status === 'succeeded')
    expect(successful).toHaveLength(1)
    expect(successful[0].job_id).toBe('JOB-SEED-005')
    expect(successful[0].approval_id).toBe(approval.approval_id)

    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('COMPLETED')
    expect(timelineText(snapshot)).toContain('applied JOB-SEED-005 exactly once')
    expectTimelineEvidenceInOrder(snapshot, [
      {
        label: `approval requested ${approval.approval_id}`,
        predicate: (event) => event.event_type === 'approval_required' && event.approval_id === approval.approval_id,
      },
      {
        label: `approval decided ${approval.approval_id}`,
        predicate: (event) => event.event_type === 'approval_decided' && event.approval_id === approval.approval_id && event.status === 'APPROVED',
      },
      {
        label: 'single commit evidence',
        predicate: (event) => event.event_type === 'tool_result' && String(event.content || '').includes('exactly once'),
      },
      {
        label: 'terminal completion evidence',
        predicate: (event) => event.event_type === 'session_completed' && event.status === 'COMPLETED',
      },
    ])
    expectFinalSummaryClaimsOnly(await finalAssistantText(sessionId), {
      mustInclude: ['JOB-SEED-005 exactly once', approval.approval_id],
      mustExclude: [/twice/i, /duplicate mutation/i],
    })
  }))

  test('SO-018 @data-integrity: active approval survives refresh with the same staged bundle', async ({ page }, testInfo) => runPhase6Oracle(testInfo, 'SO-018 active approval refresh restores pending approval', page, async ({ artifact, initial, setSessionId }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 14 refresh during active approval for original high jobs to medium')
    const sessionId = await activeSessionId(page)
    setSessionId(sessionId)

    const approval = await pendingApprovalMatching(page, 'original_high_to_medium_refresh')
    await expectApprovalRowMatches(approval, {
      status: 'PENDING',
      writeSet: 'original_high_to_medium_refresh',
      kind: 'phase14_refresh_active_approval',
      jobIds: originalHighJobIds,
      requestedPriority: 'medium',
      originalPriority: 'high',
      count: originalHighJobIds.length,
    })
    await expectSnapshotApprovalState(page, { status: 'WAITING_APPROVAL', pendingApprovalId: approval.approval_id })
    await expect(page.getByRole('heading', { name: 'Approval required' })).toHaveCount(1)
    await expect(page.getByText(/Approval required: original HIGH-priority jobs will become MEDIUM after refresh/i).first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(1)
    expect(await currentPriorityMap()).toEqual(initial.priorities)
    expectNoSuccessfulAudit(await dataIntegrityAudit(sessionId))
    recordOracleCheckpoint(artifact, 'before browser refresh with approval pending', {
      approval: await factoryAgentJson(`/approvals/${approval.approval_id}`),
      priorities: await currentPriorityMap(),
      audit: await dataIntegrityAudit(sessionId),
      snapshot: await snapshotForPage(page),
    })

    await page.reload()
    await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
    await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()

    await expect(page.getByRole('heading', { name: 'Approval required' })).toHaveCount(1)
    await expect(page.getByText(/Approval required: original HIGH-priority jobs will become MEDIUM after refresh/i).first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(1)
    await expect(page.getByText(/Run complete/i)).toHaveCount(0)
    await expectSnapshotApprovalState(page, { status: 'WAITING_APPROVAL', pendingApprovalId: approval.approval_id })
    const pendingAfterRefresh = await pendingApprovalsForPage(page)
    expect(pendingAfterRefresh.map((row) => row.approval_id)).toEqual([approval.approval_id])
    await expectApprovalRowMatches(pendingAfterRefresh[0], {
      status: 'PENDING',
      writeSet: 'original_high_to_medium_refresh',
      kind: 'phase14_refresh_active_approval',
      jobIds: originalHighJobIds,
      requestedPriority: 'medium',
      originalPriority: 'high',
      count: originalHighJobIds.length,
    })
    expect(await currentPriorityMap()).toEqual(initial.priorities)
    expectNoSuccessfulAudit(await dataIntegrityAudit(sessionId))
    recordOracleCheckpoint(artifact, 'after browser refresh before approval', {
      approval: await factoryAgentJson(`/approvals/${approval.approval_id}`),
      pending: pendingAfterRefresh,
      priorities: await currentPriorityMap(),
      audit: await dataIntegrityAudit(sessionId),
      snapshot: await snapshotForPage(page),
    })

    await page.getByRole('button', { name: 'Approve' }).click()
    await waitForSessionStatus(page, 'COMPLETED')
    await expectApprovalRowMatches(approval.approval_id, {
      status: 'APPROVED',
      writeSet: 'original_high_to_medium_refresh',
      kind: 'phase14_refresh_active_approval',
      jobIds: originalHighJobIds,
      requestedPriority: 'medium',
      originalPriority: 'high',
      count: originalHighJobIds.length,
    })
    await expectSnapshotApprovalState(page, { status: 'COMPLETED', pendingApprovalId: null })
    expect(await currentPriorityMap()).toEqual(expectedPriorityMapForCascade([{ source: 'high', target: 'medium' }]))
    await expectRowsUnchangedFromInitial(initial.rowsById, [...originalLowJobIds, ...originalMediumJobIds])

    const audit = await dataIntegrityAudit(sessionId)
    expectAuditCommit(audit, {
      scenario: 'SO-018',
      writeSet: 'original_high_to_medium_refresh',
      approvalId: approval.approval_id,
      succeededJobIds: originalHighJobIds,
      requestedPriority: 'medium',
    })
    expect(audit.filter((entry) => entry.scenario === 'SO-018' && entry.status === 'succeeded')).toHaveLength(originalHighJobIds.length)

    const snapshot = await snapshotForPage(page)
    expect(approvalIdsFromTimeline(snapshot).has(approval.approval_id)).toBe(true)
    expect(timelineText(snapshot)).toContain('exactly once')
    expectTimelineEvidenceInOrder(snapshot, [
      {
        label: `approval requested ${approval.approval_id}`,
        predicate: (event) => event.event_type === 'approval_required' && event.approval_id === approval.approval_id,
      },
      {
        label: `approval decided ${approval.approval_id}`,
        predicate: (event) => event.event_type === 'approval_decided' && event.approval_id === approval.approval_id && event.status === 'APPROVED',
      },
      {
        label: 'single restored bundle commit evidence',
        predicate: (event) =>
          event.event_type === 'tool_result' &&
          (event.approval_id === approval.approval_id || event.details?.result?.approval_id === approval.approval_id) &&
          String(event.content || '').includes('exactly once'),
      },
      {
        label: 'terminal completion evidence',
        predicate: (event) => event.event_type === 'session_completed' && event.status === 'COMPLETED',
      },
    ])
    expectFinalSummaryClaimsOnly(await finalAssistantText(sessionId), {
      mustInclude: ['high priority jobs changed to medium exactly once', approval.approval_id],
      mustExclude: [/duplicate approval/i, /fake completion/i, /Factory Agent needs attention/i],
    })
    await expect
      .poll(async () => visibleText(page), { timeout: 30_000 })
      .toContain('Run complete')
    await expect
      .poll(async () => visibleText(page), { timeout: 30_000 })
      .toContain('high priority jobs changed to medium exactly once')
    expectFinalSummaryClaimsOnly(await visibleText(page), {
      mustInclude: ['Run complete', 'high priority jobs changed to medium exactly once'],
      mustExclude: [/duplicate approval/i, /fake completion/i, /Factory Agent needs attention/i],
    })
  }))

  test('SO-006/SO-008/SO-027 scenario 89 @data-integrity: stale or expired approvals cannot mutate after session state changes', async ({ page }, testInfo) => runPhase6Oracle(testInfo, 'SO-006 SO-008 SO-027 scenario 89 stale and expired approvals cannot mutate', page, async ({ initial, setSessionId }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 14 stale approval seeded job update')

    const stale = await pendingApprovalMatching(page, 'stale_or_expired_update')
    const staleSessionId = await activeSessionId(page)
    setSessionId(staleSessionId)
    await expectApprovalRowMatches(stale, {
      status: 'PENDING',
      writeSet: 'stale_or_expired_update',
      kind: 'phase14_stale_approval',
      jobIds: ['JOB-SEED-005'],
      requestedPriority: 'high',
      count: 1,
    })
    await expectSnapshotApprovalState(page, { status: 'WAITING_APPROVAL', pendingApprovalId: stale.approval_id })
    await factoryAgentJson(`/sessions/${staleSessionId}/messages`, {
      method: 'POST',
      body: {
        role: 'user',
        mode: 'normal',
        content: 'Show status for machine M-CNC-01 after superseding the stale Phase 14 approval',
      },
    })
    await expect.poll(async () => (await factoryAgentJson(`/approvals/${stale.approval_id}`)).status).toBe('REJECTED')
    await expectApprovalRowMatches(stale.approval_id, {
      status: 'REJECTED',
      writeSet: 'stale_or_expired_update',
      kind: 'phase14_stale_approval',
      jobIds: ['JOB-SEED-005'],
      requestedPriority: 'high',
      count: 1,
    })

    const staleReplay = await approveApproval(stale.approval_id, 'phase14-stale-replay')
    expect(staleReplay.status).toBe(409)
    expect(await priorityForJob('JOB-SEED-005')).toBe('low')
    await expectRowsUnchangedFromInitial(initial.rowsById, Object.keys(canonicalJobPriorities))
    expectNoSuccessfulAudit(await dataIntegrityAudit(staleSessionId))

    await page.getByRole('button', { name: 'New Session' }).click()
    await sendPrompt(page, 'Run Phase 14 expired approval seeded job update')
    const expired = await pendingApprovalMatching(page, 'stale_or_expired_update')
    const expiredSessionId = await activeSessionId(page)
    setSessionId(expiredSessionId)
    await expectApprovalRowMatches(expired, {
      status: 'PENDING',
      writeSet: 'stale_or_expired_update',
      kind: 'phase14_expired_approval',
      jobIds: ['JOB-SEED-005'],
      requestedPriority: 'high',
      count: 1,
    })
    await expect(page.getByText(/Expired approval fixture/i).first()).toBeVisible()
    const expiredApprove = await approveApproval(expired.approval_id, 'phase14-expired-replay')
    expect(expiredApprove.status).toBe(409)
    await expect.poll(async () => (await factoryAgentJson(`/approvals/${expired.approval_id}`)).status).toBe('EXPIRED')
    await expectApprovalRowMatches(expired.approval_id, {
      status: 'EXPIRED',
      writeSet: 'stale_or_expired_update',
      kind: 'phase14_expired_approval',
      jobIds: ['JOB-SEED-005'],
      requestedPriority: 'high',
      count: 1,
    })
    await expectSnapshotApprovalState(page, { status: 'IDLE', pendingApprovalId: null })
    expect(await priorityForJob('JOB-SEED-005')).toBe('low')
    await expectRowsUnchangedFromInitial(initial.rowsById, Object.keys(canonicalJobPriorities))
    expectNoSuccessfulAudit(await dataIntegrityAudit(expiredSessionId))

    const snapshot = await snapshotForPage(page)
    expectTimelineEvidenceInOrder(snapshot, [
      {
        label: `expired approval requested ${expired.approval_id}`,
        predicate: (event) => event.event_type === 'approval_required' && event.approval_id === expired.approval_id,
      },
      {
        label: `expired approval decision ${expired.approval_id}`,
        predicate: (event) => event.event_type === 'approval_decided' && event.approval_id === expired.approval_id && event.status === 'EXPIRED',
      },
    ])
    await expect
      .poll(async () => visibleText(page), { timeout: 30_000 })
      .toContain('Expired approval fixture')
    expectFinalSummaryClaimsOnly(await visibleText(page), {
      mustInclude: ['Expired approval fixture'],
      mustExclude: [/Run complete/i, /unexpectedly applied/i, /Factory Agent needs attention/i],
    })
  }))

  test('SO-010 scenario 90 @data-integrity: audit, DB, SSE timeline, approval id, and final summary agree', async ({ page }, testInfo) => runPhase6Oracle(testInfo, 'SO-010 scenario 90 cross surface agreement', page, async ({ initial, setSessionId }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 14 agreement audit timeline summary for seeded job priority updates')
    const sessionId = await activeSessionId(page)
    setSessionId(sessionId)

    const approval = await pendingApprovalMatching(page, 'agreement_update')
    await expectApprovalRowMatches(approval, {
      status: 'PENDING',
      writeSet: 'agreement_update',
      kind: 'phase14_agreement',
      jobIds: ['JOB-SEED-005', 'JOB-SEED-009'],
      requestedPriority: 'high',
      count: 2,
    })
    await page.getByRole('button', { name: 'Approve' }).click()
    await waitForSessionStatus(page, 'COMPLETED')
    await expectApprovalRowMatches(approval.approval_id, {
      status: 'APPROVED',
      writeSet: 'agreement_update',
      kind: 'phase14_agreement',
      jobIds: ['JOB-SEED-005', 'JOB-SEED-009'],
      requestedPriority: 'high',
      count: 2,
    })
    await expectSnapshotApprovalState(page, { status: 'COMPLETED', pendingApprovalId: null })

    await expect(page.getByText(/Phase 14 agreement complete/i).first()).toBeVisible()
    await expect(page.getByText(/JOB-SEED-005 and JOB-SEED-009 are high priority/i).first()).toBeVisible()
    expect(await priorityForJob('JOB-SEED-005')).toBe('high')
    expect(await priorityForJob('JOB-SEED-009')).toBe('high')
    await expectRowsUnchangedFromInitial(
      initial.rowsById,
      Object.keys(canonicalJobPriorities).filter((jobId) => !['JOB-SEED-005', 'JOB-SEED-009'].includes(jobId)),
    )

    const audit = await dataIntegrityAudit(sessionId)
    expectAuditCommit(audit, {
      scenario: '90',
      writeSet: 'agreement_update',
      approvalId: approval.approval_id,
      succeededJobIds: ['JOB-SEED-005', 'JOB-SEED-009'],
      requestedPriority: 'high',
    })

    const snapshot = await snapshotForPage(page)
    const text = timelineText(snapshot)
    expect(text).toContain('JOB-SEED-005 and JOB-SEED-009 are high priority')
    expect(text).toContain(approval.approval_id)
    expect(approvalIdsFromTimeline(snapshot).has(approval.approval_id)).toBe(true)
    expect(activityText(snapshot)).toContain('Run complete')
    expectTimelineEvidenceInOrder(snapshot, [
      {
        label: `approval requested ${approval.approval_id}`,
        predicate: (event) => event.event_type === 'approval_required' && event.approval_id === approval.approval_id,
      },
      {
        label: `approval decided ${approval.approval_id}`,
        predicate: (event) => event.event_type === 'approval_decided' && event.approval_id === approval.approval_id && event.status === 'APPROVED',
      },
      {
        label: 'agreement commit evidence',
        predicate: (event) =>
          event.event_type === 'tool_result' &&
          (event.approval_id === approval.approval_id || event.details?.result?.approval_id === approval.approval_id) &&
          String(event.content || '').includes('JOB-SEED-005 and JOB-SEED-009 are high priority'),
      },
      {
        label: 'terminal completion evidence',
        predicate: (event) => event.event_type === 'session_completed' && event.status === 'COMPLETED',
      },
    ])

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
    expectFinalSummaryClaimsOnly(finalAssistant, {
      mustInclude: ['JOB-SEED-005 and JOB-SEED-009 are high priority', approval.approval_id],
      mustExclude: [/JOB-SEED-012/i, /all low priority jobs/i, /Factory Agent needs attention/i],
    })
  }))

  test('SO-029 @data-integrity: Go API 500 mid-run fails safely without mutation or audit rows', async ({ page }, testInfo) => runPhase6Oracle(testInfo, 'SO-029 Go API 500 mid-run safe failure', page, async ({ initial, setSessionId }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 14 Go API 500 commit failure for JOB-SEED-001')
    const sessionId = await activeSessionId(page)
    setSessionId(sessionId)

    const approval = await pendingApprovalMatching(page, 'go_api_500_high_to_medium')
    await expectApprovalRowMatches(approval, {
      status: 'PENDING',
      writeSet: 'go_api_500_high_to_medium',
      kind: 'phase14_go_api_500',
      jobIds: ['JOB-SEED-001'],
      requestedPriority: 'medium',
      originalPriority: 'high',
      count: 1,
    })
    await expectSnapshotApprovalState(page, { status: 'WAITING_APPROVAL', pendingApprovalId: approval.approval_id })
    expect(await priorityForJob('JOB-SEED-001')).toBe('high')
    await expectRowsUnchangedFromInitial(initial.rowsById, Object.keys(canonicalJobPriorities))
    expect(await dataIntegrityAudit(sessionId)).toEqual([])
    await expect(page.getByText(/Run complete/i)).toHaveCount(0)

    await page.getByRole('button', { name: 'Approve' }).click()
    await waitForSessionStatus(page, 'FAILED')
    await expectApprovalRowMatches(approval.approval_id, {
      status: 'APPROVED',
      writeSet: 'go_api_500_high_to_medium',
      kind: 'phase14_go_api_500',
      jobIds: ['JOB-SEED-001'],
      requestedPriority: 'medium',
      originalPriority: 'high',
      count: 1,
    })
    await expectSnapshotApprovalState(page, { status: 'FAILED', pendingApprovalId: null })
    expect(await priorityForJob('JOB-SEED-001')).toBe('high')
    await expectRowsUnchangedFromInitial(initial.rowsById, Object.keys(canonicalJobPriorities))
    expect(await dataIntegrityAudit(sessionId)).toEqual([])

    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('FAILED')
    expect(timelineText(snapshot)).toContain('database unavailable')
    expect(timelineText(snapshot)).not.toContain('Updated **1** job')
    expect(timelineText(snapshot)).not.toContain('Priority: **medium**')
    expectTimelineEvidenceInOrder(snapshot, [
      {
        label: `approval requested ${approval.approval_id}`,
        predicate: (event) => event.event_type === 'approval_required' && event.approval_id === approval.approval_id,
      },
      {
        label: `approval decided ${approval.approval_id}`,
        predicate: (event) => event.event_type === 'approval_decided' && event.approval_id === approval.approval_id && event.status === 'APPROVED',
      },
      {
        label: 'Go API 500 failure evidence',
        predicate: (event) =>
          event.event_type === 'tool_result' &&
          event.status === 'FAILED' &&
          String(event.content || '').includes('database unavailable'),
      },
      {
        label: 'terminal failed session evidence',
        predicate: (event) => event.event_type === 'session_failed' && event.status === 'FAILED',
      },
    ])
    await expect
      .poll(async () => visibleText(page), { timeout: 30_000 })
      .toContain('Please retry')
    expectFinalSummaryClaimsOnly(await visibleText(page), {
      mustInclude: ['Could not complete', 'database unavailable', 'Please retry'],
      mustExclude: [/Run complete/i, /JOB-SEED-001 is now medium/i, /1 high priority job changed/i, /all requested changes completed/i],
    })
  }))

  test('SO-030 @data-integrity: stream drop recovers by polling without stale final success', async ({ page }, testInfo) => runPhase6Oracle(testInfo, 'SO-030 stream drop polling recovery', page, async ({ initial, setSessionId }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 14 stream drop commit recovery for original high jobs to medium')
    const sessionId = await activeSessionId(page)
    setSessionId(sessionId)

    const approval = await pendingApprovalMatching(page, 'stream_drop_high_to_medium')
    await expectApprovalRowMatches(approval, {
      status: 'PENDING',
      writeSet: 'stream_drop_high_to_medium',
      kind: 'phase14_stream_drop_commit',
      jobIds: originalHighJobIds,
      requestedPriority: 'medium',
      originalPriority: 'high',
      count: originalHighJobIds.length,
    })
    await expectSnapshotApprovalState(page, { status: 'WAITING_APPROVAL', pendingApprovalId: approval.approval_id })
    await expect
      .poll(async () => (await sseConnections(sessionId)).some((entry) => entry.stream === 'notification' && entry.event === 'seeded_drop'), { timeout: 10_000 })
      .toBe(true)
    await expect(page.getByText(/Run complete/i)).toHaveCount(0)
    expect(await currentPriorityMap()).toEqual(initial.priorities)
    expectNoSuccessfulAudit(await dataIntegrityAudit(sessionId))

    await page.getByRole('button', { name: 'Approve' }).click()
    await expect
      .poll(async () => (await snapshotForPage(page)).session.status, { timeout: 5_000 })
      .toBe('EXECUTING')
    await expect(page.getByText(/Run complete/i)).toHaveCount(0)

    await waitForSessionStatus(page, 'COMPLETED')
    await expect(page.getByText('Run complete').first()).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText(/Phase 14 stream drop commit recovered from polling after terminal snapshot/i).first()).toBeVisible()
    await expectApprovalRowMatches(approval.approval_id, {
      status: 'APPROVED',
      writeSet: 'stream_drop_high_to_medium',
      kind: 'phase14_stream_drop_commit',
      jobIds: originalHighJobIds,
      requestedPriority: 'medium',
      originalPriority: 'high',
      count: originalHighJobIds.length,
    })
    await expectSnapshotApprovalState(page, { status: 'COMPLETED', pendingApprovalId: null })
    expect(await currentPriorityMap()).toEqual(expectedPriorityMapForCascade([{ source: 'high', target: 'medium' }]))
    await expectRowsUnchangedFromInitial(initial.rowsById, [...originalLowJobIds, ...originalMediumJobIds])

    const audit = await dataIntegrityAudit(sessionId)
    expectAuditCommit(audit, {
      scenario: 'SO-030',
      writeSet: 'stream_drop_high_to_medium',
      approvalId: approval.approval_id,
      succeededJobIds: originalHighJobIds,
      requestedPriority: 'medium',
    })

    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('COMPLETED')
    expect(activityText(snapshot)).toContain('Run complete')
    expect(timelineText(snapshot)).toContain('Phase 14 stream drop commit recovered from polling after terminal snapshot')
    expect(approvalIdsFromTimeline(snapshot).has(approval.approval_id)).toBe(true)
    expectTimelineEvidenceInOrder(snapshot, [
      {
        label: `approval requested ${approval.approval_id}`,
        predicate: (event) => event.event_type === 'approval_required' && event.approval_id === approval.approval_id,
      },
      {
        label: `approval decided ${approval.approval_id}`,
        predicate: (event) => event.event_type === 'approval_decided' && event.approval_id === approval.approval_id && event.status === 'APPROVED',
      },
      {
        label: 'stream-drop commit evidence',
        predicate: (event) =>
          event.event_type === 'tool_result' &&
          (event.approval_id === approval.approval_id || event.details?.result?.approval_id === approval.approval_id) &&
          String(event.content || '').includes('after terminal snapshot'),
      },
      {
        label: 'terminal completion evidence',
        predicate: (event) => event.event_type === 'session_completed' && event.status === 'COMPLETED',
      },
    ])
    await expect
      .poll(async () => {
        const streams = new Set((await sseConnections(sessionId)).map((entry) => entry.stream))
        return streams.has('notification')
      })
      .toBe(true)
    expectFinalSummaryClaimsOnly(await finalAssistantText(sessionId), {
      mustInclude: ['Phase 14 stream drop commit recovered from polling after terminal snapshot', approval.approval_id],
      mustExclude: [/fake completion/i, /stream lost/i, /Factory Agent needs attention/i],
    })
    expectFinalSummaryClaimsOnly(await visibleText(page), {
      mustInclude: ['Run complete', 'Phase 14 stream drop commit recovered from polling after terminal snapshot'],
      mustExclude: [/stream lost/i, /fake completion/i, /Factory Agent needs attention/i],
    })
  }))

  test('phase 6 oracle validity checks reject bad seeded evidence @data-integrity', async () => {
    const audit = [
      {
        scenario: 'oracle-negative',
        write_set: 'agreement_update',
        approval_id: 'approval-negative-1',
        job_id: 'JOB-SEED-005',
        requested_priority: 'high',
        after_priority: 'high',
        status: 'succeeded',
        reason: null,
      },
    ]

    expect(() =>
      expectAuditCommit(audit, {
        scenario: 'oracle-negative',
        writeSet: 'agreement_update',
        approvalId: 'approval-negative-1',
        succeededJobIds: ['JOB-SEED-009'],
        requestedPriority: 'high',
      }),
    ).toThrow()
    expect(() =>
      expectAuditCommit([], {
        scenario: 'oracle-negative',
        writeSet: 'agreement_update',
        approvalId: 'approval-negative-1',
        succeededJobIds: ['JOB-SEED-005'],
        requestedPriority: 'high',
      }),
    ).toThrow()

    const outOfOrderSnapshot = {
      timeline: [
        { event_type: 'tool_result', approval_id: 'approval-negative-1', content: 'commit evidence', status: 'DONE' },
        { event_type: 'approval_required', approval_id: 'approval-negative-1', content: 'approval required' },
        { event_type: 'approval_decided', approval_id: 'approval-negative-1', content: 'approved', status: 'APPROVED' },
        { event_type: 'session_completed', content: 'Run complete', status: 'COMPLETED' },
      ],
    }
    expect(() =>
      expectTimelineEvidenceInOrder(outOfOrderSnapshot, [
        {
          label: 'approval required',
          predicate: (event) => event.event_type === 'approval_required',
        },
        {
          label: 'commit after approval',
          predicate: (event) => event.event_type === 'tool_result',
        },
      ]),
    ).toThrow()

    const initial = {
      'JOB-SEED-012': { job_id: 'JOB-SEED-012', priority: 'low', product_id: 'P-012', status: 'planned', deadline: '2026-05-12' },
    }
    const mutated = {
      'JOB-SEED-012': { job_id: 'JOB-SEED-012', priority: 'high', product_id: 'P-012', status: 'planned', deadline: '2026-05-12' },
    }
    expect(() => expectUnchangedRowsMatch(initial, mutated, ['JOB-SEED-012'])).toThrow()
    expect(() =>
      expectFinalSummaryClaimsOnly('All 3 low priority jobs changed to high after stale approval approval-old.', {
        mustExclude: [/all 3 low priority jobs changed/i, /stale approval/i],
      }),
    ).toThrow()
  })
})
