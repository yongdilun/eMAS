import { expect, test } from '../support/seededArtifacts.js'
import {
  factoryAgentJson,
  openChat,
  sendPrompt,
  snapshotForPage,
} from '../support/fullStackScenarios.js'

test.describe('Phase 15 seeded reliability cross-checks @reliability', () => {
  test('scenario 92 seeded cross-check: real seeded stream reaches terminal state and idle UI', async ({ page }) => {
    await openChat(page)
    await sendPrompt(page, 'Run seeded SSE activity stream for machine M-CNC-01')

    await expect(page.getByText(/Machine M-CNC-01/i).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)

    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('COMPLETED')
    expect(snapshot.activity_steps.some((step) => step.label === 'Run complete')).toBe(true)
  })

  test('scenario 93 seeded cross-check: real seeded large result keeps layout stable and controls usable', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 820 })
    await openChat(page)
    await sendPrompt(page, 'List jobs for Phase 9 large structured result')

    await expect(page.getByText(/Phase 9 large structured result rendered 80 seeded rows/i).first()).toBeVisible()
    await expect(page.getByRole('table').first()).toBeVisible()
    await expect(page.getByText('Showing 20 of 80 rows.')).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)

    const dialogOverflows = await page.getByRole('dialog').evaluate((dialog) => dialog.scrollWidth > dialog.clientWidth + 1)
    expect(dialogOverflows).toBe(false)
    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('COMPLETED')
    expect(snapshot.steps[0].result.data).toHaveLength(80)

    const connections = await factoryAgentJson('/_playwright/sse-connections')
    expect(Array.isArray(connections.connections)).toBe(true)
  })
})
