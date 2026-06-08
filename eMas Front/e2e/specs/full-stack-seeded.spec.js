import { seededRuntimeEnv } from '../support/fullStackEnv.js'
import { expect, test } from '../support/seededArtifacts.js'
import { chatSelectors } from '../fixtures/selectors.js'
import {
  activityText,
  currentPriorityMap,
  dataIntegrityAudit,
  expectNoSuccessfulAudit,
  sessionMessages,
  timelineText,
} from '../support/dataIntegrityScenarios.js'
import { expectTransitionCheckpoint } from '../support/factoryAgentTransitionOracle.js'

const seededEnv = seededRuntimeEnv()

async function factoryAgentJson(path) {
  const response = await fetch(`${seededEnv.factoryAgentBaseUrl}${path}`)
  if (!response.ok) throw new Error(`Factory Agent ${path} failed: ${response.status} ${await response.text()}`)
  return response.json()
}

async function openChat(page) {
  await page.goto('/')
  await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
  await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()
}

async function sendPrompt(page, prompt) {
  const composer = page.getByPlaceholder(chatSelectors.composerPlaceholder)
  await expect(composer).toBeEnabled()
  await composer.fill(prompt)
  await page.getByRole('button', { name: chatSelectors.sendButtonName }).click()
  await expect(page.getByText(prompt)).toBeVisible()
}

async function activeSessionId(page) {
  return page.evaluate(() => window.localStorage.getItem('factory_agent_active_session_id'))
}

async function startNewChatSession(page) {
  const previous = await activeSessionId(page)
  await page.getByRole('button', { name: 'New Session' }).click()
  await expect
    .poll(async () => {
      const current = await activeSessionId(page)
      return Boolean(current && current !== previous)
    }, { timeout: 10_000 })
    .toBe(true)
  await expect(page.getByPlaceholder(chatSelectors.composerPlaceholder)).toBeEnabled()
}

async function snapshotForPage(page) {
  let sessionId = await activeSessionId(page)
  if (!sessionId) {
    await page.waitForFunction(() => window.localStorage.getItem('factory_agent_active_session_id'), null, { timeout: 5000 })
    sessionId = await activeSessionId(page)
  }
  if (!sessionId) throw new Error('No active Factory Agent session id in localStorage')
  return factoryAgentJson(`/sessions/${sessionId}/snapshot`)
}

async function approveCurrentResponseDocument(page) {
  const dialog = page.getByRole('dialog', { name: chatSelectors.dialogName })
  const approvalBlock = dialog.locator('[data-response-block-type="approval_required"]').last()
  const approve = approvalBlock.getByRole('button', { name: 'Approve' })
  await expect(approve).toBeVisible()
  const [approveResponse] = await Promise.all([
    page.waitForResponse((response) =>
      response.request().method() === 'POST' &&
      /\/approvals\/[^/]+\/approve$/.test(new URL(response.url()).pathname),
    ),
    approve.click(),
  ])
  expect(approveResponse.ok()).toBe(true)
  return approveResponse
}

test.describe('L3 seeded full-stack foundation @l3-foundation', () => {
  test('scenario 31: opens chat through Vite and creates a real Factory Agent session', async ({ page }) => {
    await openChat(page)
    await page.getByRole('button', { name: 'New Session' }).click()

    await expect(page.getByPlaceholder(chatSelectors.composerPlaceholder)).toBeEnabled()
    await expect
      .poll(async () => {
        const sessions = await factoryAgentJson('/sessions?user_id=frontend-operator')
        return sessions.length
      })
      .toBeGreaterThan(0)
  })

  test('scenario 32: machine status prompt completes against seeded Go API data', async ({ page }, testInfo) => {
    await openChat(page)
    await sendPrompt(page, 'Show status for machine M-CNC-01 from the seeded Go API')

    await expectTransitionCheckpoint(page, {
      checkpoint: 'scenario 32 seeded machine status response-document contract',
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
        textIncludes: ['Run complete', 'Machine M-CNC-01', 'Machine ID', 'Status'],
        textExcludes: [/Approval required/i, /Which machine ID/i],
      },
    })
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)
  })

  test('scenario 33: low-priority jobs prompt renders structured seeded results', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'List low priority seeded jobs sorted by deadline')

    await expect(page.getByText(/Found \d+ low-priority jobs sorted by deadline/i).first()).toBeVisible()
    await expect(page.getByText(/JOB-SEED-/).first()).toBeVisible()
    await expect(page.getByRole('table').first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
  })

  test('scenario 34: RAG/LOTO prompt renders controlled answer and sources', async ({ page }, testInfo) => {
    await openChat(page)
    await sendPrompt(page, 'Use seeded LOTO guidance to explain hazardous energy lockout')

    await expectTransitionCheckpoint(page, {
      checkpoint: 'scenario 34 seeded LOTO source-list response-document contract',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['source_list'],
        backendBlockTypes: ['knowledge_answer', 'source_list'],
        hiddenBlockTypes: ['approval_required', 'diagnostic', 'status_result', 'mutation_result'],
        hiddenBackendBlockTypes: ['approval_required', 'diagnostic', 'status_result', 'mutation_result'],
        approvalActionCount: 0,
        textIncludes: [
          'Controlled seeded RAG answer',
          'Knowledge sources',
          'Seeded General LOTO Guidance',
          'Control of Hazardous Energy Lockout/Tagout',
          '29 CFR 1910.147',
        ],
        textExcludes: [/Which machine ID/i, /Approval required/i],
      },
    })
  })

  test('scenario 34b @prompt-regression: OSHA lockout RAG proves positive source and insufficient context', async ({ page }, testInfo) => {
    await openChat(page)
    const positivePrompt = 'According to the OSHA lockout/tagout guide, what notification is required before reenergizing a machine after removing lockout or tagout devices?'
    await sendPrompt(page, positivePrompt)

    await expectTransitionCheckpoint(page, {
      checkpoint: 'scenario 34b Phase 32 positive OSHA source-backed RAG proof',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['knowledge_answer', 'source_list'],
        backendBlockTypes: ['knowledge_answer', 'source_list'],
        hiddenBlockTypes: ['approval_required', 'diagnostic', 'status_result', 'mutation_result'],
        hiddenBackendBlockTypes: ['approval_required', 'diagnostic', 'status_result', 'mutation_result'],
        approvalActionCount: 0,
        textIncludes: [
          'Before reenergizing, notify affected employees',
          'Control of Hazardous Energy Lockout/Tagout',
          'osha_3120_lockout_tagout',
        ],
        textExcludes: [/Which machine ID/i, /loto_notification_requirement/i, /LOTO Notification Requirements/i],
      },
    })

    const positiveSnapshot = await snapshotForPage(page)
    const positiveKnowledge = positiveSnapshot.response_document.blocks.find((block) => block.type === 'knowledge_answer')
    const positiveSource = positiveSnapshot.response_document.blocks.find((block) => block.type === 'source_list')?.sources?.[0]
    expect(positiveKnowledge?.citations?.[0]?.doc_id).toBe('osha_3120_lockout_tagout')
    expect(positiveKnowledge?.citations?.[0]?.chunk_id).toBe('osha_3120_lockout_tagout_c0029')
    expect(positiveSource?.pdf_url).toBe('/documents/osha_3120_lockout_tagout/pdf')
    expect(positiveSource?.page).toBe(15)
    expect(positiveSource?.char_range || positiveSource?.text_search).toBeTruthy()

    const negativePrompt = 'According to the OSHA lockout/tagout guide, what notification is required before starting lockout?'
    await sendPrompt(page, negativePrompt)

    await expectTransitionCheckpoint(page, {
      checkpoint: 'scenario 34b Phase 32 negative OSHA insufficient context RAG proof',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['knowledge_answer', 'source_list'],
        backendBlockTypes: ['knowledge_answer', 'source_list'],
        hiddenBlockTypes: ['approval_required', 'diagnostic', 'status_result', 'mutation_result'],
        hiddenBackendBlockTypes: ['approval_required', 'diagnostic', 'status_result', 'mutation_result'],
        approvalActionCount: 0,
        textIncludes: [
          'I do not have enough retrieved evidence to answer that safely.',
          'related sources checked',
          'Control of Hazardous Energy Lockout/Tagout',
        ],
        textExcludes: [
          /Which machine ID/i,
          /affected employees must be notified before lockout\/tagout starts/i,
          /Tell them the equipment will be locked out/i,
          /loto_notification_requirement/i,
          /LOTO Notification Requirements/i,
        ],
      },
    })

    const negativeSnapshot = await snapshotForPage(page)
    const negativeKnowledge = negativeSnapshot.response_document.blocks.find((block) => block.type === 'knowledge_answer')
    const negativeSource = negativeSnapshot.response_document.blocks.find((block) => block.type === 'source_list')?.sources?.[0]
    expect(negativeKnowledge?.answer).toMatch(/^I do not have enough retrieved evidence/i)
    expect(negativeKnowledge?.citations || []).toHaveLength(0)
    expect(negativeSource?.doc_id).toBe('osha_3120_lockout_tagout')
    expect(negativeSource?.policy_only).toBeUndefined()
    expect(JSON.stringify(negativeSnapshot.response_document)).not.toMatch(/loto_notification_requirement|LOTO Notification Requirements/i)
  })

  test('scenario 35: approval-required flow renders pending approval from real Factory Agent snapshot', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Seeded approval: change low priority jobs to high priority')

    await expect(page.getByText('Approval required').first()).toBeVisible()
    await expect(page.getByText(/will be updated from LOW to HIGH priority/i).first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible()

    const pending = await factoryAgentJson('/approvals/pending')
    expect(pending.some((approval) => approval.subject_type === 'graph' && approval.status === 'PENDING')).toBe(true)
  })

  test('scenario 36: approval approve resumes and reaches completed state with controlled provider', async ({ page }) => {
    await openChat(page)
    await startNewChatSession(page)
    await sendPrompt(page, 'Seeded approval approve flow: change low priority jobs to high priority')

    await approveCurrentResponseDocument(page)

    const sessionId = await activeSessionId(page)
    await expect.poll(async () => {
      const snapshot = await factoryAgentJson(`/sessions/${sessionId}/snapshot`)
      return snapshot.session.status
    }).toBe('COMPLETED')

    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Changes completed' })).toBeVisible()
    await expect(page.getByText(/Done\. I updated 5 jobs across 1 approved business change/i).last()).toBeVisible()
    await expect(page.getByText(/Low -> High: 5 jobs/i).first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  })

  test('SO-028 scenario 37 @sse: cancel during execution returns to idle without hidden continuation', async ({ page }) => {
    test.setTimeout(75_000)
    const initialPriorities = await currentPriorityMap()
    await openChat(page)
    await startNewChatSession(page)
    await sendPrompt(page, 'Start a seeded cancel jobs run and keep it executing')

    const cancel = page.getByRole('button', { name: 'Cancel current run' })
    await expect(cancel).toBeVisible()
    await cancel.click()

    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Cancel current run' })).toHaveCount(0)
    const sessionId = await activeSessionId(page)
    const snapshot = await factoryAgentJson(`/sessions/${sessionId}/snapshot`)
    expect(snapshot.session.status).toBe('IDLE')
    expect(snapshot.session.error).toMatch(/Cancelled/i)
    expect(activityText(snapshot)).not.toContain('Run complete')
    expect(timelineText(snapshot)).not.toMatch(/low-priority seeded jobs|Run complete/i)
    await expect(page.getByRole('heading', { name: 'Run cancelled' })).toBeVisible()
    await expect(page.getByText(/The run was cancelled\. I stopped work and did not continue pending actions\./i).first()).toBeVisible()
    await expect(page.getByText(/low-priority seeded jobs|Seeded cancellable run completed/i)).toHaveCount(0)
    await expect(page.getByText('Run complete')).toHaveCount(0)
    expectNoSuccessfulAudit(await dataIntegrityAudit(sessionId))

    await page.waitForTimeout(32_500)
    const laterSnapshot = await factoryAgentJson(`/sessions/${sessionId}/snapshot`)
    expect(laterSnapshot.session.status).toBe('IDLE')
    expect(laterSnapshot.session.error).toMatch(/Cancelled/i)
    expect(activityText(laterSnapshot)).not.toContain('Run complete')
    expect(timelineText(laterSnapshot)).not.toMatch(/low-priority seeded jobs|Run complete/i)
    expect(await currentPriorityMap()).toEqual(initialPriorities)
    expectNoSuccessfulAudit(await dataIntegrityAudit(sessionId))
    const messages = await sessionMessages(sessionId)
    const assistantText = messages
      .filter((message) => message.role === 'assistant')
      .map((message) => message.content)
      .join('\n')
    expect(assistantText).not.toMatch(/Run complete|low-priority seeded jobs|all requested changes completed/i)
  })

  test('scenario 38: notification and activity SSE open and reach final snapshot', async ({ page }) => {
    const sseRequests = []
    page.on('request', (request) => {
      const url = request.url()
      if (url.includes('/events')) sseRequests.push(url)
    })

    await openChat(page)
    await sendPrompt(page, 'Run seeded SSE activity stream for machine M-CNC-01')

    await expect
      .poll(() => sseRequests.some((url) => /\/events(?:\?|$)/.test(url)))
      .toBe(true)
    await expect
      .poll(() => sseRequests.some((url) => url.includes('/events/activity')))
      .toBe(true)

    await expect(page.getByText(/Machine M-CNC-01/i).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
  })
})
