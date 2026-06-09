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
  resetCanonicalGoApiSeed,
  resetFactoryAgentSessions,
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
const starterReadJobProductPrompt = 'Read JOB-SEED-005. If it has a product, read the product too.'
const starterPriorityUpdatePrompt = 'Change planned low-priority jobs to medium priority, then show the id and status of the updated jobs.'
const starterLotoProcedurePrompt = 'According to the LOTO procedure, what steps must workers complete before beginning service or maintenance?'

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

async function pendingApprovalByTool(page, toolName) {
  const pending = await pendingApprovalsForPage(page)
  return pending.find((approval) => (
    approval?.tool_name === toolName
    || approval?.args?.selected_graph_tool_call?.tool_name === toolName
    || (Array.isArray(approval?.args?.staged_graph_tool_calls) && approval.args.staged_graph_tool_calls.some((call) => call?.tool_name === toolName))
    || (Array.isArray(approval?.args?.preview) && approval.args.preview.some((call) => call?.tool_name === toolName))
  )) || null
}

async function pendingRescheduleInteraction(page) {
  const snapshot = await snapshotForPage(page)
  const interaction = snapshot?.pending_interaction || snapshot?.pendingInteraction || null
  return interaction?.kind === 'reschedule_all_review' ? interaction : null
}

async function expectEmbeddedRescheduleReview(page) {
  const dialog = page.getByRole('dialog', { name: /Review (?:generated )?(?:reschedule|schedule)/i })
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText(/Proposals\s*\d+/i)
  await expect(dialog).toContainText(/Feasible\s*\d+/i)
  await expect(dialog).toContainText(/Conflicts\s*\d+/i)
  await expect(dialog).toContainText(/Late\s*\d+/i)
  await expect(dialog.getByRole('button', { name: /Resolve in Resolution Center/i })).toBeVisible()
  await expect(dialog.getByRole('button', { name: /Apply all/i })).toBeEnabled()
  return dialog
}

function planRows(snapshot) {
  return Array.isArray(snapshot?.steps) ? snapshot.steps : []
}

function plannedLowJobIdsFromRows(rowsById) {
  return Object.values(rowsById)
    .filter((row) => row?.job_id && row.priority === 'low' && row.status === 'planned')
    .map((row) => row.job_id)
    .sort()
}

function expectPlanAuditMatchesRows(snapshot, { jobIds, requestedPriority }) {
  const rows = planRows(snapshot).filter((step) => step.tool_name === 'put__jobs_{id}')
  const matching = rows.filter((step) => jobIds.includes(step.args?.id) && step.args?.priority === requestedPriority)
  expect(matching.map((step) => step.args.id).sort()).toEqual([...jobIds].sort())
  for (const row of matching) {
    expect(row.status).toBe('DONE')
  }
}

function responseDocumentText(snapshot) {
  return JSON.stringify(snapshot?.response_document || {})
}

test.describe('Phase 7 real LangGraph critical browser proof @critical', () => {
  test.describe.configure({ timeout: 150_000 })

  test.beforeEach(async () => {
    await resetCanonicalGoApiSeed()
    await resetFactoryAgentSessions()
  })

  test('CJ-001 create-job prompt opens real LangGraph manual-input form @critical', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'help me to create a job')

    await expect
      .poll(async () => (await pendingApprovalByTool(page, 'post__jobs'))?.approval_id || null, { timeout: 90_000 })
      .not.toBeNull()

    const approval = await pendingApprovalByTool(page, 'post__jobs')
    expect(approval?.args?.preview_details).toMatchObject({
      manual_input_required: true,
      missing_required_args: ['product_id', 'quantity_total'],
    })
    expect(approval?.args?.selected_graph_tool_call).toMatchObject({
      tool_name: 'post__jobs',
      args: {},
    })

    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('WAITING_APPROVAL')
    expect(snapshot.pending_approval?.approval_id).toBe(approval.approval_id)

    const productSelect = page
      .locator('label')
      .filter({ hasText: /Product \*/i })
      .locator('select')
      .last()
    const quantityInput = page
      .locator('label')
      .filter({ hasText: /quantity total \*/i })
      .locator('input')
      .last()

    await expect(page.getByText('Review and edit request').last()).toBeVisible()
    await expect(productSelect).toBeVisible()
    await expect(quantityInput).toBeVisible()
    await expect
      .poll(
        async () => productSelect.evaluate((select) => Array.from(select.options).map((option) => option.textContent || '').join('|')),
        { timeout: 30_000 },
      )
      .toMatch(/P-00[12]|Precision|Valve|Gear/i)

    await productSelect.selectOption({ index: 1 })
    const selectedProduct = await productSelect.inputValue()
    await quantityInput.fill('12')
    await expect(productSelect).toHaveValue(selectedProduct)
    await expect(quantityInput).toHaveValue('12')

    const text = await visibleText(page)
    expect(text).toMatch(/Approval required/i)
    expect(text).toMatch(/Review and edit request/i)
    expect(text).not.toMatch(/Please provide the missing required field/i)
    expect(text).not.toMatch(/\bslots\b/i)
    expect(text).not.toMatch(/Enter JSON/i)
  })

  test('RS-001 reschedule-all prompt opens embedded review and applies in the same chat @critical', async ({ page }) => {
    test.setTimeout(240_000)
    await openChat(page)
    const initialUrl = page.url()
    const initialPageCount = page.context().pages().length
    let openedNewPage = false
    const onPage = () => {
      openedNewPage = true
    }
    page.context().on('page', onPage)
    await sendPrompt(page, 'help me to reschedule all job')

    try {
      await expect
        .poll(
          async () => (await pendingApprovalByTool(page, 'post__ai_scheduling_reschedule-all'))?.approval_id || null,
          { timeout: 90_000 },
        )
        .not.toBeNull()

      const approval = await pendingApprovalByTool(page, 'post__ai_scheduling_reschedule-all')
      expect(approval?.args?.selected_graph_tool_call).toMatchObject({
        tool_name: 'post__ai_scheduling_reschedule-all',
      })

      const snapshot = await snapshotForPage(page)
      expect(snapshot.session.status).toBe('WAITING_APPROVAL')
      expect(snapshot.pending_approval?.approval_id).toBe(approval.approval_id)

      const text = await visibleText(page)
      expect(text).toMatch(/Approval required/i)
      expect(text).toMatch(/reschedule/i)
      expect(text).not.toMatch(/Please provide the missing required field/i)
      expect(text).not.toMatch(/Rendering response\s+Current|Current\s+Rendering response/i)
      expect(text).not.toMatch(/Preparing response\s+Current|Current\s+Preparing response/i)
      await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible()
      await expect(page.getByText(/Waiting for (your )?approval/i).first()).toBeVisible()

      await page.getByRole('button', { name: 'Approve' }).click()
      await expect
        .poll(async () => (await pendingRescheduleInteraction(page))?.interaction_id || null, { timeout: 120_000 })
        .not.toBeNull()
      await expect(page.getByText(/missing authenticated user or role/i)).toHaveCount(0)
      await expect(page.getByText(/Data too long/i)).toHaveCount(0)
      await expect(page.getByText(/Rendering response\s+Current|Current\s+Rendering response/i)).toHaveCount(0)
      await expect(page.getByText(/Preparing response\s+Current|Current\s+Preparing response/i)).toHaveCount(0)
      await expect(page.getByText(/Waiting for your action/i).first()).toBeVisible()

      expect(openedNewPage).toBe(false)
      expect(page.context().pages().length).toBe(initialPageCount)
      expect(page.url()).toBe(initialUrl)
      await expectEmbeddedRescheduleReview(page)

      await page.getByRole('button', { name: /Apply all/i }).click()
      await expect
        .poll(async () => (await snapshotForPage(page))?.session?.status || null, { timeout: 120_000 })
        .toBe('COMPLETED')
      await expect(page.getByText(/Reschedule (?:partially )?applied/i).first()).toBeVisible({ timeout: 30_000 })
      await expect(page.getByText(/missing authenticated user or role|Data too long/i)).toHaveCount(0)
      expect(page.context().pages().length).toBe(initialPageCount)
      expect(page.url()).toBe(initialUrl)
    } finally {
      page.context().off('page', onPage)
    }
  })

  test('RS-002 reschedule-all embedded review cancels in the same chat @critical', async ({ page }) => {
    test.setTimeout(240_000)
    await openChat(page)
    const initialUrl = page.url()
    const initialPageCount = page.context().pages().length
    let openedNewPage = false
    const onPage = () => {
      openedNewPage = true
    }
    page.context().on('page', onPage)
    await sendPrompt(page, 'help me to reschedule all job')

    try {
      await expect
        .poll(
          async () => (await pendingApprovalByTool(page, 'post__ai_scheduling_reschedule-all'))?.approval_id || null,
          { timeout: 90_000 },
        )
        .not.toBeNull()
      await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible()
      await expect(page.getByText(/Rendering response\s+Current|Current\s+Rendering response/i)).toHaveCount(0)
      await expect(page.getByText(/Preparing response\s+Current|Current\s+Preparing response/i)).toHaveCount(0)

      await page.getByRole('button', { name: 'Approve' }).click()
      await expect
        .poll(async () => (await pendingRescheduleInteraction(page))?.interaction_id || null, { timeout: 120_000 })
        .not.toBeNull()
      await expect(page.getByText(/missing authenticated user or role/i)).toHaveCount(0)
      await expect(page.getByText(/Data too long/i)).toHaveCount(0)
      await expect(page.getByText(/Rendering response\s+Current|Current\s+Rendering response/i)).toHaveCount(0)
      await expect(page.getByText(/Preparing response\s+Current|Current\s+Preparing response/i)).toHaveCount(0)
      await expectEmbeddedRescheduleReview(page)

      expect(openedNewPage).toBe(false)
      expect(page.context().pages().length).toBe(initialPageCount)
      expect(page.url()).toBe(initialUrl)

      await page.getByRole('button', { name: /Resolve in Resolution Center/i }).click()
      await expect(page.getByRole('heading', { name: /Shortage Resolution Center/i })).toBeVisible()
      expect(openedNewPage).toBe(false)
      expect(page.context().pages().length).toBe(initialPageCount)
      expect(page.url()).toBe(initialUrl)
      await page.getByText('Close', { exact: true }).click()
      await expect(page.getByRole('dialog', { name: /Review (?:generated )?(?:reschedule|schedule)/i })).toBeVisible()

      await page.getByRole('button', { name: 'Cancel', exact: true }).click()
      await expect
        .poll(async () => {
          const snapshot = await snapshotForPage(page)
          return `${snapshot?.session?.status || ''}:${snapshot?.response_document?.state || ''}`
        }, { timeout: 120_000 })
        .toMatch(/^(IDLE|COMPLETED):cancelled$/)
      await expect(page.getByText(/Reschedule cancelled/i).first()).toBeVisible({ timeout: 30_000 })
      expect(page.context().pages().length).toBe(initialPageCount)
      expect(page.url()).toBe(initialUrl)
    } finally {
      page.context().off('page', onPage)
    }
  })

  test('SP-001 starter read job and conditional product path exposes middle-step evidence @critical', async ({ page }, testInfo) => {
    const initialRows = await currentSeededJobRowsById(['JOB-SEED-005'])
    const job = initialRows['JOB-SEED-005']
    expect(job?.product_id, 'JOB-SEED-005 should have a product_id for this conditional-read proof').toBeTruthy()

    await openChat(page)
    await sendPrompt(page, starterReadJobProductPrompt)

    await expectTransitionCheckpoint(page, {
      checkpoint: 'SP-001 real LangGraph starter read job then product',
      snapshotForPage,
      testInfo,
      timeout: 120_000,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['record_preview'],
        backendBlockTypes: ['record_preview'],
        hiddenBlockTypes: ['approval_required', 'mutation_result', 'diagnostic'],
        hiddenBackendBlockTypes: ['approval_required', 'mutation_result', 'diagnostic'],
        responseRunStepKinds: ['read', 'completed'],
        responseRunStepTitles: [/Read 1/i, /Read product status/i, /Run complete/i],
        activityLabelsInclude: [/Run complete/i],
        textIncludes: [/JOB-SEED-005/i, new RegExp(job.product_id, 'i')],
        textExcludes: [/Approval required/i, /Which job ID/i, /Which product/i, /Factory Agent needs attention/i],
      },
    })
  })

  test('SP-002 starter priority update waits for approval and proves read-after-write evidence @critical', async ({ page }, testInfo) => {
    const initialRows = await currentSeededJobRowsById()
    const plannedLowJobIds = plannedLowJobIdsFromRows(initialRows)
    expect(plannedLowJobIds.length, 'seed should include planned low-priority jobs').toBeGreaterThan(0)

    await openChat(page)
    await sendPrompt(page, starterPriorityUpdatePrompt)

    const approval = await pendingApprovalWithRows(page, plannedLowJobIds)
    await expectGraphPriorityApproval(approval, {
      status: 'PENDING',
      jobIds: plannedLowJobIds,
      requestedPriority: 'medium',
      originalPriority: 'low',
    })
    await expectTransitionCheckpoint(page, {
      checkpoint: 'SP-002 real LangGraph starter update waits for approval',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'WAITING_APPROVAL',
        responseState: 'waiting_approval',
        pendingApprovalId: approval.approval_id,
        visibleBlockTypes: ['approval_required'],
        backendBlockTypes: ['approval_required'],
        approvalActionCount: 2,
        responseRunStepKinds: ['read', 'approval'],
        responseRunStepTitles: [/Found \d+ records/i, /Waiting for approval/i],
        timelineEventsInOrder: [
          { eventType: 'approval_required', approvalId: approval.approval_id },
        ],
        textIncludes: [/low/i, /medium/i],
        textExcludes: [/Run complete/i, /Changes completed/i],
      },
    })

    await page.getByRole('button', { name: 'Approve' }).click()
    await expectJobsAtPriority(plannedLowJobIds, 'medium')
    await expectTransitionCheckpoint(page, {
      checkpoint: 'SP-002 real LangGraph starter update completes after approved write',
      snapshotForPage,
      testInfo,
      timeout: 120_000,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['result_summary', 'mutation_result'],
        backendBlockTypes: ['result_summary', 'mutation_result'],
        hiddenBlockTypes: ['approval_required'],
        hiddenBackendBlockTypes: ['approval_required'],
        responseContracts: ['business_change_v1'],
        approvalActionCount: 0,
        responseRunStepKinds: ['mutation', 'completed'],
        timelineEventsInOrder: [
          { eventType: 'approval_required', approvalId: approval.approval_id },
          { eventType: 'approval_decided', approvalId: approval.approval_id, status: 'APPROVED' },
          'tool_result',
          'session_completed',
        ],
        activityLabelsInclude: [/Run complete/i],
        textIncludes: [/Run complete/i, /medium/i, new RegExp(plannedLowJobIds[0], 'i')],
        textExcludes: [/Waiting for approval/i, /Approval required/i, /Which updated jobs/i],
      },
    })

    const snapshot = await snapshotForPage(page)
    expectPlanAuditMatchesRows(snapshot, { jobIds: plannedLowJobIds, requestedPriority: 'medium' })
    const documentText = responseDocumentText(snapshot)
    for (const jobId of plannedLowJobIds) expect(documentText).toContain(jobId)
    expect(documentText).toMatch(/status/i)
  })

  test('SP-003 starter LOTO procedure returns source-backed RAG structure, not just final prose @critical', async ({ page }, testInfo) => {
    await openChat(page)
    await sendPrompt(page, starterLotoProcedurePrompt)

    await expectTransitionCheckpoint(page, {
      checkpoint: 'SP-003 real LangGraph starter LOTO source-backed answer',
      snapshotForPage,
      testInfo,
      timeout: 120_000,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['knowledge_answer', 'source_list'],
        backendBlockTypes: ['knowledge_answer', 'source_list'],
        hiddenBlockTypes: ['approval_required', 'diagnostic', 'mutation_result'],
        hiddenBackendBlockTypes: ['approval_required', 'diagnostic', 'mutation_result'],
        responseContracts: ['knowledge_answer_v1', 'source_list_v1'],
        approvalActionCount: 0,
        activityLabelsInclude: [/Run complete/i],
        textIncludes: [/LOTO|lockout|tagout|service|maintenance/i],
        textExcludes: [/Which machine ID/i, /Approval required/i, /\bNo results\b/i, /Factory Agent needs attention/i],
      },
    })

    const snapshot = await snapshotForPage(page)
    const knowledgeBlock = snapshot.response_document?.blocks?.find((block) => block.type === 'knowledge_answer')
    const sourceBlock = snapshot.response_document?.blocks?.find((block) => block.type === 'source_list')
    expect(knowledgeBlock?.contract).toBe('knowledge_answer_v1')
    expect(sourceBlock?.contract).toBe('source_list_v1')
    expect(Array.isArray(sourceBlock?.sources) && sourceBlock.sources.length > 0).toBe(true)
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
