import { seededRuntimeEnv } from '../support/fullStackEnv.js'
import { expect, test } from '../support/seededArtifacts.js'
import { chatSelectors } from '../fixtures/selectors.js'

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

  test('scenario 32: machine status prompt completes against seeded Go API data', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Show status for machine M-CNC-01 from the seeded Go API')

    await expect(page.getByText(/Machine M-CNC-01/i).first()).toBeVisible()
    await expect(page.getByText(/CNC Mill 01/i).first()).toBeVisible()
    await expect(page.getByText(/seeded Go API data/i).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)
  })

  test('scenario 33: low-priority jobs prompt renders structured seeded results', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'List low priority seeded jobs sorted by deadline')

    await expect(page.getByText(/low-priority seeded jobs/i).first()).toBeVisible()
    await expect(page.getByText(/JOB-SEED-/).first()).toBeVisible()
    await expect(page.getByRole('table').first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
  })

  test('scenario 34: RAG/LOTO prompt renders controlled answer and sources', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Use seeded LOTO guidance to explain hazardous energy lockout')

    await expect(page.getByText(/Controlled seeded RAG answer/i).first()).toBeVisible()
    await expect(page.getByText('Knowledge sources')).toBeVisible()
    await expect(page.getByText('Seeded LOTO Procedure').first()).toBeVisible()
    await expect(page.getByText(/Controlled fake RAG output/i)).toBeVisible()
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
    await sendPrompt(page, 'Seeded approval approve flow: change low priority jobs to high priority')

    const approve = page.getByRole('button', { name: 'Approve' })
    await expect(approve).toBeVisible()
    await approve.click()

    const sessionId = await activeSessionId(page)
    await expect.poll(async () => {
      const snapshot = await factoryAgentJson(`/sessions/${sessionId}/snapshot`)
      return snapshot.session.status
    }).toBe('COMPLETED')

    await expect(page.getByText('Run complete')).toBeVisible()
    await page.getByText('Show details').click()
    await expect(page.getByText(/Approved seeded change completed/i).last()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  })

  test('scenario 37: cancel during execution returns to idle cancelled state', async ({ page }) => {
    await openChat(page)
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
