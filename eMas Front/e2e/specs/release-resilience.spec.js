import { expect, test } from '../support/releaseArtifacts.js'
import {
  activeSessionId,
  factoryAgentJson,
  openChat,
  pendingApprovalsForPage,
  releaseEnv,
  releaseLogSizeBytes,
  resetReleaseFaults,
  sendPrompt,
  setReleaseFaults,
  snapshotForPage,
} from '../support/releaseScenarios.js'

test.setTimeout(90_000)

function approvalRowsFromPayload(approval) {
  const args = approval?.args && typeof approval.args === 'object' ? approval.args : {}
  const bundle = args.bundle_ui && typeof args.bundle_ui === 'object' ? args.bundle_ui : {}
  const rows = Array.isArray(bundle.rows) && bundle.rows.length
    ? bundle.rows
    : Array.isArray(args.preview)
      ? args.preview.map((item) => (item?.args && typeof item.args === 'object' ? item.args : item)).filter(Boolean)
      : []
  return rows.filter((row) => row && typeof row === 'object')
}

function visibleSeededRecordIds(text) {
  return Array.from(new Set(String(text || '').match(/\b[A-Z]+-SEED-\d+\b/g) || []))
}

test.describe('L4 release resilience and accessibility @l4-release', () => {
  test.beforeEach(async () => {
    await resetReleaseFaults()
  })

  test('scenario 60: Go API outage during chatbot job shows degraded state and no fake completion', async ({ page }) => {
    await openChat(page)
    await setReleaseFaults({ goApiUnavailable: true })
    await sendPrompt(page, 'Run Phase 10 Go API outage machine lookup')

    await expect(page.getByText('Factory Agent needs attention').or(page.getByText(/503|goApiUnavailable|controlled release fault/i).first())).toBeVisible({
      timeout: 20_000,
    })
    await expect(page.getByText('Run complete')).toHaveCount(0)
    await expect(page.getByText(/Machine M-CNC-01 .* seeded Go API data/i)).toHaveCount(0)
  })

  test('scenario 61: Factory Agent unavailable at page load keeps chat open enough to show diagnostics', async ({ page }) => {
    await setReleaseFaults({ factoryAgentUnavailable: true })
    await openChat(page)

    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByText(/Factory Agent (?:backend unavailable|is disconnected)/i)).toBeVisible()
    await expect(page.getByText(/Cannot reach Factory Agent|service is unavailable|503|factoryAgentUnavailable|controlled release fault/i).first()).toBeVisible()
    await expect(page.getByPlaceholder('Ask factory agent...')).toBeVisible()
  })

  test('scenario 64: refresh during an active job restores or safely abandons without duplicate execution', async ({ page }) => {
    await openChat(page)
    const prompt = 'Run Phase 10 refresh during active job without duplicate execution'
    await sendPrompt(page, prompt)
    await expect.poll(() => activeSessionId(page)).not.toBeNull()
    const sessionId = await activeSessionId(page)
    await expect.poll(async () => {
      const messages = await factoryAgentJson(`/sessions/${sessionId}/messages`)
      return messages.filter((message) => message.role === 'user' && message.content === prompt).length
    }, { timeout: releaseEnv.latencyBudgetsMs.firstProgress }).toBe(1)

    await page.reload()
    await page.getByRole('button', { name: /AI Assistant/i }).click()
    await expect(page.getByRole('dialog')).toBeVisible()

    const messages = await factoryAgentJson(`/sessions/${sessionId}/messages`)
    expect(messages.filter((message) => message.role === 'user' && message.content === prompt)).toHaveLength(1)
    const restoredPromptCount = await page.getByText(prompt).count()
    const snapshot = restoredPromptCount > 0
      ? await snapshotForPage(page)
      : await factoryAgentJson(`/sessions/${sessionId}/snapshot`)
    if (restoredPromptCount > 0 && snapshot.session.status === 'COMPLETED') {
      await expect(page.getByText(/Phase 10 refresh recovery completed once/i).last()).toBeVisible({
        timeout: releaseEnv.latencyBudgetsMs.finalAnswer,
      })
    } else {
      expect(['IDLE', 'PLANNING', 'EXECUTING', 'FAILED', 'BLOCKED', 'COMPLETED']).toContain(snapshot.session.status)
      await expect(page.getByText('Run complete')).toHaveCount(0)
    }
  })

  test('scenario 65: slow network still shows first progress before the release threshold', async ({ page }) => {
    await page.route('**/agent/**', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 175))
      await route.continue()
    })

    await openChat(page)
    const started = Date.now()
    await sendPrompt(page, 'Run Phase 10 slow network machine status')
    await expect(page.getByText(/Understanding your request|Gathering information|Run complete/i).first()).toBeVisible({
      timeout: releaseEnv.latencyBudgetsMs.firstProgress,
    })
    expect(Date.now() - started).toBeLessThan(releaseEnv.latencyBudgetsMs.firstProgress)
    await expect(page.getByText(/Machine M-CNC-01/i).first()).toBeVisible({
      timeout: releaseEnv.latencyBudgetsMs.finalAnswer,
    })
  })

  test('scenario 66: mobile viewport opens chat, submits prompt, handles approval card, and avoids overlap', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await openChat(page)
    await sendPrompt(page, 'Release mobile approval: change low priority jobs to high priority')

    await expect(page.getByText('Approval required').first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible()
    const dialogOverflows = await page.getByRole('dialog').evaluate((dialog) => dialog.scrollWidth > dialog.clientWidth + 1)
    expect(dialogOverflows).toBe(false)

    const pending = await pendingApprovalsForPage(page)
    expect(pending.length).toBeGreaterThan(0)
    const payloadRows = approvalRowsFromPayload(pending[0])
    const stagedIds = payloadRows
      .map((row) => String(row.job_id || row.id || '').trim())
      .filter(Boolean)
    const approvalPreviewRows = page.locator('[data-response-block-type="approval_required"] [data-affected-record-row]')
    await expect(approvalPreviewRows.first()).toBeVisible()
    const visibleApprovalIds = visibleSeededRecordIds((await approvalPreviewRows.allTextContents()).join(' '))
    const expectedCount = payloadRows.length || visibleApprovalIds.length
    expect(expectedCount).toBeGreaterThan(0)
    await page.getByRole('button', { name: 'Approve' }).click()
    await expect.poll(async () => (await snapshotForPage(page)).session.status, {
      timeout: releaseEnv.latencyBudgetsMs.finalAnswer,
    }).toBe('COMPLETED')
    await expect.poll(async () => page.getByRole('dialog').textContent(), {
      timeout: releaseEnv.latencyBudgetsMs.finalAnswer,
    }).toContain('Run complete')
    const dialogText = await page.getByRole('dialog').textContent()
    expect(dialogText).toContain('Run complete')
    expect(dialogText).not.toMatch(/Applied\s*0\s+approved/i)
    expect(dialogText).toMatch(new RegExp(`(?:Updated|Applied)\\s*${expectedCount}\\b`, 'i'))
    const idsToCheck = stagedIds.length ? stagedIds : visibleApprovalIds
    if (idsToCheck.length) {
      expect(idsToCheck.some((id) => dialogText.includes(id))).toBe(true)
    }
    expect(dialogText).not.toContain('Approved request to change record')
    const finalDialogOverflows = await page.getByRole('dialog').evaluate((dialog) => dialog.scrollWidth > dialog.clientWidth + 1)
    expect(finalDialogOverflows).toBe(false)
  })

  test('scenario 67: keyboard-only flow opens chat, submits, rejects approval, and closes modal', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /AI Assistant/i }).focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('dialog')).toBeVisible()

    const keyboardPrompt = 'Release keyboard approval: change medium priority jobs to high priority'
    const composer = page.getByPlaceholder('Ask factory agent...')
    await expect(composer).toBeEnabled()
    await composer.focus()
    await page.keyboard.type(keyboardPrompt)
    await expect(composer).toHaveValue(keyboardPrompt)
    const sendButton = page.getByRole('button', { name: 'Send' })
    await expect(sendButton).toBeEnabled()
    await sendButton.focus()
    await page.keyboard.press('Enter')
    await expect(page.getByText(keyboardPrompt)).toBeVisible()

    await expect(page.getByText('Approval required').first()).toBeVisible({
      timeout: releaseEnv.latencyBudgetsMs.finalAnswer,
    })
    await page.getByPlaceholder('Optional rejection reason').focus()
    await page.keyboard.insertText('Keyboard-only release validation rejection.')
    await page.getByRole('button', { name: 'Reject' }).focus()
    await page.keyboard.press('Enter')

    const pending = await pendingApprovalsForPage(page)
    expect(pending).toHaveLength(0)
    await page.getByRole('button', { name: 'Close' }).focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })

  test('scenario 70: long-running stream stays within log limits and reaches terminal state or timeout', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Run Phase 10 long-running stream with bounded logs')

    await expect(page.getByRole('dialog')).toContainText(/terminal state within release limits/i, {
      timeout: releaseEnv.latencyBudgetsMs.longStream,
    })
    await expect(page.getByText('Run complete')).toBeVisible()
    const snapshot = await snapshotForPage(page)
    expect(['COMPLETED', 'FAILED']).toContain(snapshot.session.status)
    expect(releaseLogSizeBytes('release-proxy.log')).toBeLessThan(2_000_000)
    expect(releaseLogSizeBytes('factory-agent.log')).toBeLessThan(2_000_000)
  })
})
