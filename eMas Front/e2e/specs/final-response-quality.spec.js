import { expect, test } from '@playwright/test'
import { chatSelectors } from '../fixtures/selectors.js'
import { responseDocumentTrafficPrompt } from '../fixtures/factoryAgentFixtures.js'
import { expectTransitionCheckpoint } from '../support/factoryAgentTransitionOracle.js'
import { pendingApprovalGuidanceProbeText, readOnlyStatusForbiddenProbeText, serializeSemanticProbe } from '../support/responseDocumentProbe.js'
import {
  cascadeDefinition,
  forbiddenResponseDocumentText,
  responseDocumentCancelledRunPrompt,
  responseDocumentAllNoOpPrompt,
  responseDocumentCascadePrompt,
  responseDocumentExpiredApprovalPrompt,
  responseDocumentLotoPrompt,
  responseDocumentNoResultsPrompt,
  responseDocumentPartialNoOpPrompt,
  responseDocumentPartialFailurePrompt,
  responseDocumentReadStatusPrompt,
  responseDocumentRejectedApprovalPrompt,
  responseDocumentReverseCascadePrompt,
  responseDocumentStaleApprovalPrompt,
  responseDocumentTimeoutPrompt,
} from '../support/responseDocumentScenarios.js'

const mockBaseUrl = `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_FACTORY_AGENT_PORT || 8015)}`
const activeSessionStorageKey = 'factory_agent_active_session_id'

async function openChat(page) {
  await page.goto('/')
  await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
  await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()
}

async function sendChatPrompt(page, prompt) {
  const composer = page.getByPlaceholder(chatSelectors.composerPlaceholder)
  const sendButton = page.getByRole('button', { name: chatSelectors.sendButtonName })
  await expect(composer).toBeEnabled()
  await composer.fill(prompt)
  await expect(sendButton).toBeEnabled()
  await sendButton.scrollIntoViewIfNeeded()
  await sendButton.click()
  await expect(page.getByText(prompt)).toBeVisible()
}

async function visibleText(page) {
  return page.locator('body').evaluate((body) => body.innerText)
}

async function expectForbiddenTextAbsent(page, patterns = forbiddenResponseDocumentText) {
  const text = await visibleText(page)
  for (const pattern of patterns) {
    expect(text).not.toMatch(pattern)
  }
}

async function activeSessionId(page) {
  let sessionId = await page.evaluate((key) => window.localStorage.getItem(key), activeSessionStorageKey)
  if (!sessionId) {
    await page.waitForFunction((key) => window.localStorage.getItem(key), activeSessionStorageKey, { timeout: 5000 })
    sessionId = await page.evaluate((key) => window.localStorage.getItem(key), activeSessionStorageKey)
  }
  if (!sessionId) throw new Error('No active Factory Agent session id in localStorage')
  return sessionId
}

async function snapshotForPage(page) {
  const sessionId = await activeSessionId(page)
  const response = await fetch(`${mockBaseUrl}/sessions/${sessionId}/snapshot`, {
    headers: { 'X-User-Id': 'frontend-operator' },
  })
  const body = await response.json()
  if (!response.ok) throw new Error(`Snapshot fetch failed: ${response.status} ${JSON.stringify(body)}`)
  return body
}

const uiStatusByBackendStatus = {
  PLANNING: 'Understanding',
  EXECUTING: 'Checking',
  WAITING_APPROVAL: 'Waiting for approval',
  WAITING_CONFIRMATION: 'Waiting for confirmation',
  BLOCKED: 'Needs attention',
  FAILED: 'Needs attention',
  COMPLETED: 'Complete',
  IDLE: 'Ready',
}

async function collectStateProbe(page) {
  return page.evaluate(() => {
    const statusLabels = new Set([
      'Ready',
      'Understanding',
      'Checking',
      'Waiting for approval',
      'Waiting for confirmation',
      'Needs attention',
      'Complete',
      'Working',
    ])
    const dialog = document.querySelector('[role="dialog"]') || document.body
    const text = document.body.innerText || ''
    const heading = dialog.querySelector('h2')
    const headerRegion = heading?.parentElement || dialog
    const headerStatus = Array.from(headerRegion.querySelectorAll('span'))
      .map((node) => (node.textContent || '').trim())
      .find((value) => statusLabels.has(value)) || null
    const activeSessionButton = dialog.querySelector('aside [aria-current="page"]')
    const activeSidebarStatus = activeSessionButton
      ? Array.from(activeSessionButton.querySelectorAll('span'))
        .map((node) => (node.textContent || '').trim())
        .find((value) => statusLabels.has(value)) || null
      : null
    const blockTypes = Array.from(document.querySelectorAll('[data-response-block-type]'))
      .map((node) => node.getAttribute('data-response-block-type'))
      .filter(Boolean)
    return { headerStatus, activeSidebarStatus, blockTypes, text }
  })
}

async function expectNoOrphanTurnVisible(page) {
  const probe = await collectStateProbe(page)
  expect(probe.text).not.toMatch(/non_terminal_snapshot/i)
  expect(probe.text).not.toMatch(/Session status:\s*IDLE/i)
  expect(probe.text).not.toMatch(/Needs attention\s+The request needs attention before it can continue/i)
  expect(probe.text).not.toMatch(/The request needs attention before it can continue\./i)
  if (probe.activeSidebarStatus === 'Waiting for approval') {
    expect(probe.headerStatus).toBe('Waiting for approval')
  }
}

async function expectActiveStateAgreement(page, {
  sessionStatus,
  responseState,
  pendingApproval,
  visibleBlockType,
}) {
  const snapshot = await snapshotForPage(page)
  const probe = await collectStateProbe(page)
  expect(snapshot.session.status).toBe(sessionStatus)
  expect(Boolean(snapshot.pending_approval)).toBe(pendingApproval)
  expect(snapshot.response_document?.state).toBe(responseState)
  expect(probe.headerStatus).toBe(uiStatusByBackendStatus[sessionStatus])
  expect(probe.activeSidebarStatus).toBe(uiStatusByBackendStatus[sessionStatus])
  expect(probe.blockTypes).toContain(visibleBlockType)
  await expectNoOrphanTurnVisible(page)
  return { snapshot, probe }
}

async function expectDetailsClosed(locator) {
  await expect(locator).toBeVisible()
  expect(await locator.evaluate((node) => node.open)).toBe(false)
}

async function expectNoResponseDocumentOverflow(page) {
  const offenders = await page.locator('[data-response-document-root]').evaluateAll((roots) =>
    roots.flatMap((root) =>
      Array.from(root.querySelectorAll('[data-response-block-type], [data-response-document-root]'))
        .filter((node) => node.scrollWidth > node.clientWidth + 2)
        .map((node) => ({
          type: node.getAttribute('data-response-block-type') || 'root',
          text: (node.textContent || '').slice(0, 120),
          scrollWidth: node.scrollWidth,
          clientWidth: node.clientWidth,
        })),
    ),
  )
  expect(offenders).toEqual([])
}

async function expandActivity(page, label) {
  const activity = page.getByRole('button', { name: new RegExp(label, 'i') }).last()
  await expect(activity).toBeVisible()
  const expanded = await activity.getAttribute('aria-expanded')
  if (expanded !== 'true') await activity.click()
}

const exactAction = (name) => new RegExp(`^${name}$`)

async function decideApproval(page, action) {
  const label = action === 'approve' ? 'Approve' : 'Reject'
  const responsePromise = page.waitForResponse((response) =>
    response.url().includes('/approvals/') && response.url().endsWith(`/${action}`),
  )
  await page.getByRole('button', { name: exactAction(label) }).click()
  const response = await responsePromise
  expect(response.status()).toBe(200)
}

async function runCascade(page, { prompt, finalMessage, firstStep, secondStep, firstRowsLabel, secondRowsLabel }) {
  await page.setViewportSize({ width: 390, height: 760 })
  await openChat(page)
  await sendChatPrompt(page, prompt)

  await expect(page.getByText('Understood request').first()).toBeVisible()
  await expect(page.getByText(firstRowsLabel).first()).toBeVisible()
  await expect(page.getByText('Waiting for approval 1').first()).toBeVisible()
  const firstApprovalCard = page.locator('[data-response-block-type="approval_required"]').filter({ hasText: firstStep }).last()
  await expect(firstApprovalCard).toBeVisible()
  await expect(firstApprovalCard).toContainText(firstStep)
  await expect(firstApprovalCard).toContainText(/JOB-SEED-00[12]/)
  await expect(firstApprovalCard).toContainText(/\+\d+ more/)
  await expect(page.getByText('Run complete')).toHaveCount(0)
  await expect(page.getByText(finalMessage)).toHaveCount(0)
  await expectNoResponseDocumentOverflow(page)

  const firstDetails = page.locator('details').filter({ hasText: /Affected records \(\d+\)/ }).first()
  await expectDetailsClosed(firstDetails)
  await firstDetails.locator('summary').click()
  expect(await firstDetails.evaluate((node) => node.open)).toBe(true)
  await firstDetails.locator('summary').click()
  expect(await firstDetails.evaluate((node) => node.open)).toBe(false)
  await page.waitForTimeout(3300)
  await expectDetailsClosed(firstDetails)

  await page.setViewportSize({ width: 1280, height: 900 })
  await decideApproval(page, 'approve')
  await expect(page.getByText('Waiting for approval 2').first()).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText(secondRowsLabel).first()).toBeVisible()
  await expect(page.getByText(new RegExp(firstStep.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/^Update/, 'Updated'))).first()).toBeVisible()
  const secondApprovalCard = page.locator('[data-response-block-type="approval_required"]').filter({ hasText: secondStep }).last()
  await expect(secondApprovalCard).toBeVisible()
  await expect(secondApprovalCard).toContainText(secondStep)
  await expect(page.getByText('Run complete')).toHaveCount(0)
  await expect(page.getByText(finalMessage)).toHaveCount(0)

  await decideApproval(page, 'approve')
  await expect(page.getByText(finalMessage).first()).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText('Run complete').first()).toBeVisible()
  await expect(page.getByText(/->/).first()).toBeVisible()
  await expect(page.getByText('Approval required')).toHaveCount(0)
  await expect(page.getByText(/Waiting for approval \d/)).toHaveCount(0)
  await expectForbiddenTextAbsent(page, [
    /All requested changes completed/i,
    /Approved request to change record/i,
    /Response document invalid/i,
    /Traceback/i,
    /super-secret/i,
  ])
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function finalBusinessQualityExpected({
  summary,
  groups = [
    { label: 'Medium -> High', count: 10 },
    { label: 'Original High -> Low', count: 11 },
  ],
  auditExpanded = false,
} = {}) {
  return {
    finalResultCardCount: 1,
    finalSummaryText: summary,
    businessGroups: groups,
    affectedRecordPreviewMin: 1,
    affectedRecordPreviewMax: 5,
    expandableAuditPresent: true,
    auditExpanded,
    expandedAuditGroups: auditExpanded ? groups : [],
    forbidDuplicateAffectedRecords: true,
  }
}

async function runCascadeStateTransitionOracle(page, testInfo, {
  kind,
  label,
  firstStep,
  secondStep,
  firstRowsLabel,
  secondRowsLabel,
}) {
  const definition = cascadeDefinition(kind)
  const firstApprovalId = definition.first.approvalId
  const secondApprovalId = definition.second.approvalId
  const finalGroups = kind === 'reverse'
    ? [
        { label: 'High -> Low', count: 11 },
        { label: 'Original Low -> Medium', count: 5 },
      ]
    : [
        { label: 'Medium -> High', count: 10 },
        { label: 'Original High -> Low', count: 11 },
      ]
  expect(secondApprovalId).not.toBe(firstApprovalId)

  await page.setViewportSize({ width: 1280, height: 900 })
  await openChat(page)
  await sendChatPrompt(page, definition.prompt)

  const afterSend = await expectTransitionCheckpoint(page, {
    checkpoint: `${label} after send shows approval 1`,
    snapshotForPage,
    testInfo,
    expected: {
      sessionStatus: 'WAITING_APPROVAL',
      responseState: 'waiting_approval',
      pendingApprovalId: firstApprovalId,
      visibleBlockTypes: ['approval_required'],
      visibleBlockIds: [`approval:${firstApprovalId}`],
      backendBlockTypes: ['approval_required'],
      approvalActionCount: 2,
      forbiddenText: pendingApprovalGuidanceProbeText,
      textIncludes: ['Understood request', firstRowsLabel, 'Waiting for approval 1', firstStep],
      textExcludes: [/Run complete/i, definition.finalMessage],
    },
  })

  await decideApproval(page, 'approve')
  const afterApproval1 = await expectTransitionCheckpoint(page, {
    checkpoint: `${label} after approval 1 shows distinct approval 2`,
    snapshotForPage,
    testInfo,
    expected: {
      sessionStatus: 'WAITING_APPROVAL',
      responseState: 'waiting_approval',
      pendingApprovalId: secondApprovalId,
      pendingApprovalMustDifferFrom: firstApprovalId,
      revisionGreaterThan: afterSend.backend.responseDocumentRevision,
      visibleBlockTypes: ['completed_step', 'approval_required'],
      visibleBlockIds: [`approval:${secondApprovalId}`],
      hiddenBlockIds: [`approval:${firstApprovalId}`],
      backendBlockTypes: ['completed_step', 'approval_required'],
      approvalActionCount: 2,
      forbidWaitingApproval1: true,
      forbiddenText: pendingApprovalGuidanceProbeText,
      textIncludes: [
        'Approval 1 received',
        secondRowsLabel,
        'Waiting for approval 2',
        secondStep,
        new RegExp(escapeRegExp(firstStep).replace(/^Update/, 'Updated')),
      ],
      textExcludes: [/Run complete/i, firstStep],
    },
  })

  await decideApproval(page, 'approve')
  await expectTransitionCheckpoint(page, {
    checkpoint: `${label} after final approval shows aggregate completion`,
    snapshotForPage,
    testInfo,
    expected: {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      pendingApprovalId: null,
      revisionGreaterThan: afterApproval1.backend.responseDocumentRevision,
      visibleBlockTypes: ['result_summary', 'mutation_result'],
      hiddenBlockTypes: ['approval_required'],
      hiddenBlockIds: [`approval:${firstApprovalId}`, `approval:${secondApprovalId}`],
      hiddenBackendBlockTypes: ['approval_required'],
      approvalActionCount: 0,
      textIncludes: [definition.finalMessage, 'Run complete', finalGroups[0].label, finalGroups[1].label],
      textExcludes: [/Waiting for approval \d/i, /Approval required/i],
      finalResponseQuality: finalBusinessQualityExpected({ summary: definition.finalMessage, groups: finalGroups }),
    },
  })
}

test.describe('Final response quality response_document gate', () => {
  test.describe.configure({ mode: 'default' })

  test('RD-001 state transition oracle catches stale visible approval after backend advances', async ({ page }, testInfo) => {
    await runCascadeStateTransitionOracle(page, testInfo, {
      kind: 'forward',
      label: 'RD-001',
      firstStep: 'Update 10 jobs from medium to high',
      secondStep: 'Update 11 jobs from high to low',
      firstRowsLabel: 'Found 10 original medium-priority jobs',
      secondRowsLabel: 'Found 11 original high-priority jobs',
    })
  })

  test('RD-001 approval copy pending guidance stays absent from normal approval display', async ({ page }, testInfo) => {
    const definition = cascadeDefinition('forward')
    await page.setViewportSize({ width: 1280, height: 900 })
    await openChat(page)
    await sendChatPrompt(page, definition.prompt)

    const summary = await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-001 phase 16 approval copy proof after send',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'WAITING_APPROVAL',
        responseState: 'waiting_approval',
        pendingApprovalId: definition.first.approvalId,
        visibleBlockTypes: ['approval_required'],
        visibleBlockIds: [`approval:${definition.first.approvalId}`],
        backendBlockTypes: ['approval_required'],
        approvalActionCount: 2,
        forbiddenText: pendingApprovalGuidanceProbeText,
        textIncludes: ['Waiting for approval 1', 'Update 10 jobs from medium to high'],
        textExcludes: [/Run complete/i],
      },
    })
    const body = serializeSemanticProbe(summary)
    await testInfo.attach('phase16-approval-copy-semantic-probe.json', {
      body,
      contentType: 'application/json',
    })

    expect(summary.visible.latestUserPrompt).toContain(definition.prompt)
    expect(summary.backend.pendingApprovalId).toBe(definition.first.approvalId)
    expect(summary.visible.visibleBlockTypes).toContain('approval_required')
    expect(body.split(/\r?\n/).length).toBeLessThan(200)
  })

  test('RD-001 final response visual quality oracle proves compact grouped business result', async ({ page }, testInfo) => {
    const definition = cascadeDefinition('forward')
    await page.setViewportSize({ width: 1280, height: 900 })
    await openChat(page)
    await sendChatPrompt(page, definition.prompt)

    await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-001 visual quality after send shows approval 1',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'WAITING_APPROVAL',
        responseState: 'waiting_approval',
        pendingApprovalId: definition.first.approvalId,
        visibleBlockTypes: ['approval_required'],
        visibleBlockIds: [`approval:${definition.first.approvalId}`],
        approvalActionCount: 2,
        forbiddenText: pendingApprovalGuidanceProbeText,
      },
    })

    await decideApproval(page, 'approve')
    await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-001 visual quality after approval 1 shows approval 2',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'WAITING_APPROVAL',
        responseState: 'waiting_approval',
        pendingApprovalId: definition.second.approvalId,
        visibleBlockTypes: ['completed_step', 'approval_required'],
        visibleBlockIds: [`approval:${definition.second.approvalId}`],
        hiddenBlockIds: [`approval:${definition.first.approvalId}`],
        approvalActionCount: 2,
        forbidWaitingApproval1: true,
        forbiddenText: pendingApprovalGuidanceProbeText,
      },
    })

    await decideApproval(page, 'approve')
    const collapsedSummary = await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-001 final response visual quality collapsed',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['result_summary', 'mutation_result'],
        hiddenBlockTypes: ['approval_required', 'completed_step'],
        hiddenBackendBlockTypes: ['approval_required', 'completed_step', 'result_table'],
        approvalActionCount: 0,
        textIncludes: [
          definition.finalMessage,
          'Changes completed',
          'Medium -> High: 10 jobs',
          'Original High -> Low: 11 jobs',
          'Full clean audit',
        ],
        textExcludes: [
          /Updated 63 jobs across 22 approved steps/i,
          /Operation ID/i,
          /Step ID/i,
          /Row ID/i,
          /\*\*Success\*\*/i,
          /Approval required/i,
        ],
        finalResponseQuality: finalBusinessQualityExpected({ summary: definition.finalMessage }),
      },
    })
    await testInfo.attach('rd-001-final-visual-quality-collapsed-probe.json', {
      body: serializeSemanticProbe(collapsedSummary),
      contentType: 'application/json',
    })

    const audit = page.locator('[data-final-result-card] details[data-clean-audit]').last()
    await expect(audit).toBeVisible()
    expect(await audit.evaluate((node) => node.open)).toBe(false)
    await audit.locator('summary').click()

    const expandedSummary = await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-001 final response visual quality expanded audit',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['result_summary', 'mutation_result'],
        hiddenBlockTypes: ['approval_required', 'completed_step'],
        approvalActionCount: 0,
        finalResponseQuality: finalBusinessQualityExpected({
          summary: definition.finalMessage,
          auditExpanded: true,
        }),
      },
    })
    await testInfo.attach('rd-001-final-visual-quality-expanded-probe.json', {
      body: serializeSemanticProbe(expandedSummary),
      contentType: 'application/json',
    })
    await expect(page.locator('[data-clean-audit-group]')).toHaveCount(2)
    await expect(page.locator('[data-clean-audit-group][data-business-change-label="Medium -> High"] [data-affected-record-row]')).toHaveCount(10)
    await expect(page.locator('[data-clean-audit-group][data-business-change-label="Original High -> Low"] [data-affected-record-row]')).toHaveCount(11)
  })

  test('RD-002 state transition oracle covers reverse cascade without overfitting RD-001', async ({ page }, testInfo) => {
    await runCascadeStateTransitionOracle(page, testInfo, {
      kind: 'reverse',
      label: 'RD-002',
      firstStep: 'Update 11 jobs from high to low',
      secondStep: 'Update 5 jobs from low to medium',
      firstRowsLabel: 'Found 11 original high-priority jobs',
      secondRowsLabel: 'Found 5 original low-priority jobs',
    })
  })

  test('RD-006 no-op mutation contract shows Not changed, no matching records, and no fake approval', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await openChat(page)
    await sendChatPrompt(page, responseDocumentPartialNoOpPrompt)

    const afterSend = await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-006 partial no-op after send',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'WAITING_APPROVAL',
        responseState: 'waiting_approval',
        pendingApprovalId: 'pw-rd-partial-noop-approval',
        visibleBlockTypes: ['completed_step', 'approval_required'],
        backendBlockTypes: ['completed_step', 'approval_required'],
        approvalActionCount: 2,
        textIncludes: ['Not changed', 'no matching jobs', 'Update 3 jobs from high to low'],
        textExcludes: [/No changes were made/i],
      },
    })
    const approvalCard = page.locator('[data-response-block-type="approval_required"]').last()
    await expect(approvalCard).toContainText('Update 3 jobs from high to low')
    await expect(approvalCard).toContainText('JOB-SEED-001')
    await expect(approvalCard).not.toContainText('archived')

    await decideApproval(page, 'approve')
    await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-006 partial no-op final',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        revisionGreaterThan: afterSend.backend.responseDocumentRevision,
        visibleBlockTypes: ['result_summary', 'mutation_result'],
        hiddenBlockTypes: ['approval_required'],
        approvalActionCount: 0,
        textIncludes: [
          'Run complete',
          'Not changed',
          'no matching jobs',
          'Done. I updated 3 jobs across 1 approved business change',
          'High -> Low: 3 jobs',
        ],
        textExcludes: [/Approval required/i],
        finalResponseQuality: finalBusinessQualityExpected({
          summary: /Done\. I updated 3 jobs across 1 approved business change/i,
          groups: [
            { label: 'Not changed', count: 0 },
            { label: 'High -> Low', count: 3 },
          ],
        }),
      },
    })

    await sendChatPrompt(page, responseDocumentAllNoOpPrompt)
    const allNoop = await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-007 all no-op final',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['result_summary', 'mutation_result'],
        hiddenBlockTypes: ['approval_required'],
        approvalActionCount: 0,
        textIncludes: ['No changes were made', 'Not changed', 'no matching jobs'],
        textExcludes: [/Approval required/i],
        finalResponseQuality: {
          finalResultCardCount: 1,
          finalSummaryText: /No changes were made/i,
          businessGroups: [{ label: 'Not changed', count: 0 }],
          affectedRecordPreviewMax: 0,
          expandableAuditPresent: true,
          forbidDuplicateAffectedRecords: true,
        },
      },
    })
    await testInfo.attach('rd-006-no-op-semantic-probe.json', {
      body: serializeSemanticProbe(allNoop),
      contentType: 'application/json',
    })
  })

  test('RD-001 orphan/session state invariant forbids IDLE non_terminal_snapshot UI', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, responseDocumentCascadePrompt)

    await expect(page.getByText('Waiting for approval 1').first()).toBeVisible()
    const firstApprovalCard = page.locator('[data-response-block-type="approval_required"]')
      .filter({ hasText: 'Update 10 jobs from medium to high' })
      .last()
    await expect(firstApprovalCard).toBeVisible()
    await expectActiveStateAgreement(page, {
      sessionStatus: 'WAITING_APPROVAL',
      responseState: 'waiting_approval',
      pendingApproval: true,
      visibleBlockType: 'approval_required',
    })

    await decideApproval(page, 'approve')
    await expect(page.getByText('Waiting for approval 2').first()).toBeVisible({ timeout: 10_000 })
    const secondApprovalCard = page.locator('[data-response-block-type="approval_required"]')
      .filter({ hasText: 'Update 11 jobs from high to low' })
      .last()
    await expect(secondApprovalCard).toBeVisible()
    await expectActiveStateAgreement(page, {
      sessionStatus: 'WAITING_APPROVAL',
      responseState: 'waiting_approval',
      pendingApproval: true,
      visibleBlockType: 'approval_required',
    })

    await decideApproval(page, 'approve')
    await expect(page.getByText('Done. I updated 21 jobs across 2 approved business changes.').first()).toBeVisible({ timeout: 10_000 })
    await expectActiveStateAgreement(page, {
      sessionStatus: 'COMPLETED',
      responseState: 'completed',
      pendingApproval: false,
      visibleBlockType: 'result_summary',
    })
  })

  test('two-approval cascade keeps compact pending state and final aggregate truth', async ({ page }) => {
    await runCascade(page, {
      prompt: responseDocumentCascadePrompt,
      finalMessage: 'Done. I updated 21 jobs across 2 approved business changes.',
      firstStep: 'Update 10 jobs from medium to high',
      secondStep: 'Update 11 jobs from high to low',
      firstRowsLabel: 'Found 10 original medium-priority jobs',
      secondRowsLabel: 'Found 11 original high-priority jobs',
    })
  })

  test('reverse two-approval cascade converges to final aggregate truth', async ({ page }) => {
    await runCascade(page, {
      prompt: responseDocumentReverseCascadePrompt,
      finalMessage: 'Done. I updated 16 jobs across 2 approved business changes.',
      firstStep: 'Update 11 jobs from high to low',
      secondStep: 'Update 5 jobs from low to medium',
      firstRowsLabel: 'Found 11 original high-priority jobs',
      secondRowsLabel: 'Found 5 original low-priority jobs',
    })
  })

  test('RD-008 read-only status response renders one clean machine status contract', async ({ page }, testInfo) => {
    await openChat(page)
    await sendChatPrompt(page, responseDocumentReadStatusPrompt)
    const statusSummary = page.getByText('Machine M-CNC-01 is running.')
    await expect(statusSummary).toHaveCount(1)
    await expandActivity(page, 'Run complete')
    await expect(page.getByText('Read machine status').first()).toBeVisible()
    await expect(page.getByText('Run complete').first()).toBeVisible()
    await expect(page.locator('[data-response-block-type="status_result"]').last()).toBeVisible()
    await expect(page.getByText('Machine ID').first()).toBeVisible()
    await expect(page.getByText('Machine name').first()).toBeVisible()
    await expect(page.getByText('Machine type').first()).toBeVisible()
    await expect(page.getByText('Location').first()).toBeVisible()
    await expect(page.getByText('Status').first()).toBeVisible()
    await expect(page.getByText('Capacity per hour').first()).toBeVisible()
    await expect(page.getByText('Last maintenance').first()).toBeVisible()
    await expect(page.getByText('Maintenance interval').first()).toBeVisible()
    const summary = await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-008 read-only status response contract',
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
        approvalActionCount: 0,
        forbiddenText: readOnlyStatusForbiddenProbeText,
        textIncludes: [
          responseDocumentReadStatusPrompt,
          'Machine M-CNC-01 is running.',
          'Machine ID',
          'Machine name',
          'Machine type',
          'Location',
          'Status',
          'Capacity per hour',
          'Last maintenance',
          'Maintenance interval',
        ],
        textExcludes: [
          /Approval required/i,
          /Mutation result/i,
          /Machine status \(1\)/i,
          /Default setup/i,
          /Default cleaning/i,
          /Default changeover/i,
          /Utilization rate/i,
        ],
      },
    })
    await testInfo.attach('rd-008-read-only-status-semantic-probe.json', {
      body: serializeSemanticProbe(summary),
      contentType: 'application/json',
    })
    await expect(page.getByText('Approval required')).toHaveCount(0)
    await expect(page.getByRole('button', { name: exactAction('Approve') })).toHaveCount(0)
    await expect(page.getByRole('button', { name: exactAction('Reject') })).toHaveCount(0)

    await sendChatPrompt(page, responseDocumentLotoPrompt)
    await expect(page.getByText(/Use the M-CNC-01 lockout\/tagout procedure/i).first()).toBeVisible()
    await expandActivity(page, 'Run complete')
    await expect(page.getByText('Prepared sourced answer').first()).toBeVisible()
    await expect(page.getByText('Knowledge sources').first()).toBeVisible()
    await expect(page.getByText('M-CNC-01 Lockout/Tagout Procedure').first()).toBeVisible()
    await expect(page.getByText('LOTO-M-CNC-01').first()).toBeVisible()
    await expectForbiddenTextAbsent(page)
  })

  test('diagnostic documents cover no-result, partial failure, timeout, expired, and stale approvals', async ({ page }) => {
    await openChat(page)
    const cases = [
      [responseDocumentNoResultsPrompt, /No matching jobs were found/i, 'No results'],
      [responseDocumentPartialFailurePrompt, /Some rows were updated, but other rows failed/i, 'Partial failure'],
      [responseDocumentTimeoutPrompt, /planner timed out while preparing the next step/i, 'Run interrupted'],
      [responseDocumentExpiredApprovalPrompt, /approval expired/i, 'Approval expired'],
      [responseDocumentStaleApprovalPrompt, /approval is stale/i, 'Approval is stale'],
    ]

    for (const [prompt, messagePattern, title] of cases) {
      await sendChatPrompt(page, prompt)
      await expect(page.getByText(messagePattern).first()).toBeVisible()
      await expect(page.getByText(title).first()).toBeVisible()
      await expect(page.getByText('Technical details').last()).toBeVisible()
      const technical = page.locator('details').filter({ hasText: 'Technical details' }).last()
      await expectDetailsClosed(technical)
      await expect(page.getByText('Approval required')).toHaveCount(0)
      await expect(page.getByRole('button', { name: exactAction('Approve') })).toHaveCount(0)
      await expectForbiddenTextAbsent(page)
    }
  })

  test('rejected approval closes actions while preserving completed prior step', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, responseDocumentRejectedApprovalPrompt)
    await expect(page.getByText('Completed step').first()).toBeVisible()
    await expect(page.getByText('Update 11 jobs from high to low').first()).toBeVisible()
    await expect(page.getByRole('button', { name: exactAction('Reject') })).toBeVisible()

    await page.getByRole('button', { name: exactAction('Reject') }).click()
    await expect(page.getByText('Approval rejected').first()).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('The approval was rejected, so I did not apply that pending change.').first()).toBeVisible()
    await expect(page.getByText('Updated 10 jobs from medium to high.').first()).toBeVisible()
    await expect(page.getByRole('button', { name: exactAction('Approve') })).toHaveCount(0)
    await expect(page.getByRole('button', { name: exactAction('Reject') })).toHaveCount(0)
    await expect(page.getByText('Run complete')).toHaveCount(0)
    await expectForbiddenTextAbsent(page)
  })

  test('cancelled run renders typed cancelled diagnostic with no stale pending state', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, responseDocumentCancelledRunPrompt)
    await expect(page.getByText('I am checking records and can still be cancelled.').first()).toBeVisible()
    await expect(page.getByText('Checking records').first()).toBeVisible()
    await page.getByRole('button', { name: 'Cancel current run' }).click()

    await expect(page.getByText('Run cancelled').first()).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('The run was cancelled. I stopped work and did not continue pending actions.').first()).toBeVisible()
    await expect(page.getByText('Approval required')).toHaveCount(0)
    await expect(page.getByText('Run complete')).toHaveCount(0)
    await expectForbiddenTextAbsent(page)
  })

  test('busy traffic event storm converges on final response without stale blocks', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, responseDocumentTrafficPrompt)

    await expect(page.getByText('Done. I updated 21 jobs across 2 approved business changes.').first()).toBeVisible({ timeout: 10_000 })
    await page.waitForTimeout(900)
    await expect(page.getByText('Done. I updated 21 jobs across 2 approved business changes.').first()).toBeVisible()
    await expect(page.getByText('Stale failure: database unavailable.')).toHaveCount(0)
    await expect(page.getByText('Response document invalid')).toHaveCount(0)
    await expect(page.getByText('Approval required')).toHaveCount(0)
    await expect(page.getByText('Waiting for approval 2')).toHaveCount(0)
  })
})
