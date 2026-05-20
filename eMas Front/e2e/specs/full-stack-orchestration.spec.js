import { expect, test } from '../support/seededArtifacts.js'
import {
  activeSessionId,
  factoryAgentJson,
  openChat,
  pendingApprovalsForPage,
  sendPrompt,
  snapshotForPage,
  textIndex,
  waitForSessionStatus,
} from '../support/fullStackScenarios.js'

test.describe('L3 seeded hard orchestration @l3-hard', () => {
  test('scenario 39 @multi-step: ordered multi-step job plans, reads seeded data, applies a rule, and summarizes', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 9 multi-step ordered seeded jobs workflow: list jobs, apply business rule, summarize jobs')

    await expect(page.getByText(/Phase 9 step 2 read seeded data/i).first()).toBeVisible()
    await expect(page.getByText(/Phase 9 step 3 apply business rule/i).first()).toBeVisible()
    await expect(page.getByText(/Phase 9 step 4 summarize/i).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()

    const snapshot = await snapshotForPage(page)
    expect(snapshot.plan.plan_explanation).toContain('Phase 9 plan: plan, read seeded data, apply business rule, summarize.')
    const timelineText = snapshot.timeline.map((event) => event.content || '').join('\n')
    const readIdx = textIndex(timelineText, 'Phase 9 step 2 read seeded data')
    const ruleIdx = textIndex(timelineText, 'Phase 9 step 3 apply business rule')
    const summaryIdx = textIndex(timelineText, 'Phase 9 step 4 summarize')
    expect(readIdx).toBeLessThan(ruleIdx)
    expect(ruleIdx).toBeLessThan(summaryIdx)
    expect(snapshot.steps.map((step) => step.status)).toEqual(['DONE', 'DONE', 'DONE'])
  })

  test('scenario 40 @approval-chain: two approvals are required before final execution completes', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 9 multi approval chain for seeded job priority update')

    await expect(page.getByText(/First approval required/i).first()).toBeVisible()
    let pending = await pendingApprovalsForPage(page)
    expect(pending).toHaveLength(1)
    const firstApprovalId = pending[0].approval_id

    await page.getByRole('button', { name: 'Approve' }).click()
    await expect(page.getByText(/Second approval required before final execution/i).first()).toBeVisible()
    pending = await pendingApprovalsForPage(page)
    expect(pending).toHaveLength(1)
    const secondApprovalId = pending[0].approval_id
    expect(secondApprovalId).not.toBe(firstApprovalId)

    await page.getByRole('button', { name: 'Approve' }).click()
    await waitForSessionStatus(page, 'COMPLETED')
    await expect(page.getByText(/Phase 9 multi-approval final execution completed after two approvals/i).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)

    const first = await factoryAgentJson(`/approvals/${firstApprovalId}`)
    const second = await factoryAgentJson(`/approvals/${secondApprovalId}`)
    expect(first.status).toBe('APPROVED')
    expect(second.status).toBe('APPROVED')
  })

  test('scenario 41 @approval-chain: rejecting the second approval stops without later execution', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 9 multi approval chain for seeded job priority update')

    await expect(page.getByText(/First approval required/i).first()).toBeVisible()
    await page.getByRole('button', { name: 'Approve' }).click()
    await expect(page.getByText(/Second approval required before final execution/i).first()).toBeVisible()
    const pending = await pendingApprovalsForPage(page)
    expect(pending).toHaveLength(1)
    const secondApprovalId = pending[0].approval_id

    await page.getByPlaceholder('Optional rejection reason').fill('Phase 9 rejected second approval.')
    await page.getByRole('button', { name: 'Reject' }).click()

    await expect(page.getByText(/Phase 9 multi-approval final execution completed/i)).toHaveCount(0, { timeout: 1000 })
    await expect(page.getByText('Run complete')).toHaveCount(0)
    const second = await factoryAgentJson(`/approvals/${secondApprovalId}`)
    expect(second.status).toBe('REJECTED')
    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('IDLE')
    expect(snapshot.steps).toHaveLength(0)
  })

  test('scenario 42 @approval-chain: approval timeout remains visible, safe, and non-terminal', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 9 approval timeout seeded job update')

    await expect(page.getByText(/Approval timed out; execution remains paused and visible/i).first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible()

    const pending = await pendingApprovalsForPage(page)
    expect(pending).toHaveLength(1)
    expect(new Date(pending[0].expires_at).getTime()).toBeLessThan(Date.now())

    const before = await snapshotForPage(page)
    expect(before.session.status).toBe('WAITING_APPROVAL')
    await page.waitForTimeout(1200)
    const after = await snapshotForPage(page)
    expect(after.session.status).toBe('WAITING_APPROVAL')
    expect(after.session.completed_at).toBeFalsy()
    await expect(page.getByText('Run complete')).toHaveCount(0)
  })

  test('scenario 43 @multi-step: partial failure stops after step 2 and never runs step 3', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 9 partial failure seeded jobs workflow')

    await waitForSessionStatus(page, 'FAILED')
    await expect(page.getByText(/Phase 9 forced failure at step 2/i).first()).toBeVisible()
    await expect(page.getByText(/must-not-run/i)).toHaveCount(0)
    await expect(page.getByText('Run complete')).toHaveCount(0)

    const snapshot = await snapshotForPage(page)
    expect(snapshot.steps.map((step) => step.status)).toEqual(['DONE', 'FAILED', 'NOT_STARTED'])
    expect(snapshot.steps[0].result_summary).toMatch(/step 1 succeeded/i)
    expect(snapshot.steps[1].result_summary).toMatch(/step 2 failed safely/i)
    expect(snapshot.steps[1].last_error).toMatch(/step 2/i)
    expect(snapshot.steps[2].result).toBeFalsy()
  })

  test('scenario 44: malformed tool payload returns a safe visible error without crashing the chat panel', async ({ page }) => {
    const pageErrors = []
    page.on('pageerror', (error) => pageErrors.push(error.message))

    await openChat(page)
    await sendPrompt(page, 'Run Phase 9 schema mismatch for machine M-CNC-01 payload')

    await expect(page.getByText('Factory Agent needs attention')).toBeVisible()
    await expect(page.getByText(/Invalid args|validation|schema|malformed/i).first()).toBeVisible()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByPlaceholder('Ask factory agent...')).toBeEnabled()
    expect(pageErrors).toEqual([])
  })

  test('scenario 45: duplicate submit sends one user turn and one execute request', async ({ page }) => {
    const requests = []
    page.on('request', (request) => {
      const url = request.url()
      if (request.method() === 'POST' && /\/sessions\/[^/]+\/(?:messages|execute)(?:\?|$)/.test(url)) {
        requests.push(url)
      }
    })

    await openChat(page)
    const prompt = 'Run Phase 9 duplicate submit seeded machine job'
    const composer = page.getByPlaceholder('Ask factory agent...')
    await composer.fill(prompt)
    await page.getByRole('button', { name: 'Send' }).dblclick()

    await expect(page.getByText(prompt)).toBeVisible()
    await expect(page.getByText(/Machine M-CNC-01/i).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()

    const messageRequests = requests.filter((url) => /\/messages$/.test(new URL(url).pathname))
    const executeRequests = requests.filter((url) => /\/execute$/.test(new URL(url).pathname))
    expect(messageRequests).toHaveLength(1)
    expect(executeRequests).toHaveLength(1)

    const sessionId = await activeSessionId(page)
    const messages = await factoryAgentJson(`/sessions/${sessionId}/messages`)
    expect(messages.filter((message) => message.role === 'user' && message.content === prompt)).toHaveLength(1)
  })
})
