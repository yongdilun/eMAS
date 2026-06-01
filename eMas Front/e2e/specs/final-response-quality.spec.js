import { expect, test } from '@playwright/test'
import { chatSelectors } from '../fixtures/selectors.js'
import { responseDocumentTrafficPrompt } from '../fixtures/factoryAgentFixtures.js'
import { expectTransitionCheckpoint } from '../support/factoryAgentTransitionOracle.js'
import {
  documentContentRagForbiddenProbeText,
  machineStatusOnlyForbiddenDetailProbeText,
  pendingApprovalGuidanceProbeText,
  readOnlyStatusForbiddenProbeText,
  serializeSemanticProbe,
} from '../support/responseDocumentProbe.js'
import {
  cascadeDefinition,
  forbiddenResponseDocumentText,
  responseDocumentCancelledRunPrompt,
  responseDocumentAllNoOpPrompt,
  responseDocumentCascadePrompt,
  responseDocumentCollapsedResultsPrompt,
  responseDocumentExpandedParentPageOnlyPrompt,
  responseDocumentExpiredApprovalPrompt,
  responseDocumentJobStatusPrompt,
  responseDocumentLotoPrompt,
  responseDocumentLotoNotificationPrompt,
  responseDocumentMachineDetailsPrompt,
  responseDocumentMixedOperationRagPrompt,
  responseDocumentNoResultsPrompt,
  responseDocumentMultiStatusPrompt,
  responseDocumentOshaReenergizingPrompt,
  responseDocumentPartialNoOpPrompt,
  responseDocumentPartialFailurePrompt,
  responseDocumentReadStatusPrompt,
  responseDocumentRejectedApprovalPrompt,
  responseDocumentReverseCascadePrompt,
  responseDocumentSourcePdfPrompt,
  responseDocumentTextSearchPdfPrompt,
  responseDocumentStaleApprovalPrompt,
  responseDocumentTimeoutPrompt,
  responseDocumentZeroMatchApprovalPrompt,
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
  if (probe.activeSidebarStatus === 'Waiting for approval' && probe.headerStatus) {
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
  if (probe.headerStatus) {
    expect(probe.headerStatus).toBe(uiStatusByBackendStatus[sessionStatus])
  }
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

async function elementBox(locator) {
  return locator.evaluate((node) => {
    const rect = node.getBoundingClientRect()
    return {
      left: rect.left,
      top: rect.top,
      right: rect.right,
      bottom: rect.bottom,
      width: rect.width,
      height: rect.height,
    }
  })
}

async function sourceTooltipMetrics(tooltipLocator) {
  return tooltipLocator.evaluate((tooltip) => {
    const roots = Array.from(document.querySelectorAll('[data-response-document-root]'))
    const root = tooltip.closest('[data-response-document-root]') || roots[roots.length - 1]
    if (!root) return null
    const toBox = (node) => {
      const rect = node.getBoundingClientRect()
      return {
        left: rect.left,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height,
      }
    }
    return {
      placement: tooltip.getAttribute('data-source-chip-hover-placement'),
      tooltip: toBox(tooltip),
      container: toBox(root),
      viewport: {
        left: 0,
        top: 0,
        right: window.innerWidth,
        bottom: window.innerHeight,
        width: window.innerWidth,
        height: window.innerHeight,
      },
    }
  })
}

function expectBoxInside(inner, outer, label, tolerance = 1.5) {
  expect(inner.left, `${label} left edge`).toBeGreaterThanOrEqual(outer.left - tolerance)
  expect(inner.top, `${label} top edge`).toBeGreaterThanOrEqual(outer.top - tolerance)
  expect(inner.right, `${label} right edge`).toBeLessThanOrEqual(outer.right + tolerance)
  expect(inner.bottom, `${label} bottom edge`).toBeLessThanOrEqual(outer.bottom + tolerance)
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

async function expectFactoryAgentPdfUrl(page, locator, attr, expectedPathWithFragment) {
  const value = await locator.getAttribute(attr)
  expect(value).toBe(`${mockBaseUrl}${expectedPathWithFragment}`)
  const parsed = new URL(value)
  const frontend = new URL(page.url())
  expect(parsed.origin).toBe(new URL(mockBaseUrl).origin)
  expect(parsed.pathname).toBe(expectedPathWithFragment.split('#')[0])
  expect(parsed.origin === frontend.origin && /^\/documents\//.test(parsed.pathname)).toBe(false)
}

async function expectFactoryAgentPdfResponse(page, action, expectedPathWithFragment) {
  const expectedUrl = `${mockBaseUrl}${expectedPathWithFragment.split('#')[0]}`
  const responsePromise = page.waitForResponse((response) =>
    response.url() === expectedUrl && response.status() === 200,
  )
  await action()
  const response = await responsePromise
  expect(response.headers()['content-type']).toMatch(/application\/pdf/i)
  return response
}

function finalBusinessQualityExpected({
  summary,
  groups = [
    { label: 'Medium -> High', count: 10 },
    { label: 'Original High -> Low', count: 11 },
  ],
  auditExpanded = false,
} = {}) {
  const contractGroups = groups.map((group) => {
    if (group.contract) return group
    if (group.label === 'Not changed') {
      return { ...group, contract: 'entity_agnostic_no_matching_records_v1', entityType: 'job' }
    }
    return {
      ...group,
      contract: 'business_change_v1',
      entityType: 'job',
      changeType: 'update',
      sourceStateBasis: 'original',
      fieldChangeCountMin: 1,
    }
  })
  return {
    finalResultCardCount: 1,
    finalSummaryText: summary,
    businessGroups: contractGroups,
    affectedRecordPreviewMin: 1,
    affectedRecordPreviewMax: 5,
    expandableAuditPresent: true,
    auditExpanded,
    expandedAuditGroups: auditExpanded ? contractGroups : [],
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
      textIncludes: ['Understood request', firstStep],
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
      responseContracts: ['business_change_v1'],
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
        textIncludes: ['Update 10 jobs from medium to high'],
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
        responseContracts: ['business_change_v1'],
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
        responseContracts: ['business_change_v1'],
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
        responseContracts: ['business_change_v1'],
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
        responseContracts: ['entity_agnostic_no_matching_records_v1'],
        approvalActionCount: 0,
        textIncludes: ['No changes were made', 'Not changed', 'no matching jobs'],
        textExcludes: [/Approval required/i],
        finalResponseQuality: {
          finalResultCardCount: 1,
          finalSummaryText: /No changes were made/i,
          businessGroups: [
            {
              label: 'Not changed',
              count: 0,
              contract: 'entity_agnostic_no_matching_records_v1',
              entityType: 'job',
            },
          ],
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

  test('RD-014 zero-match first change shows active medium-to-high approval only', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await openChat(page)
    await sendChatPrompt(page, responseDocumentZeroMatchApprovalPrompt)

    const probe = await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-014 zero-match active approval',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'WAITING_APPROVAL',
        responseState: 'waiting_approval',
        pendingApprovalId: 'pw-rd-zero-match-medium-high',
        visibleBlockTypes: ['completed_step', 'approval_required'],
        backendBlockTypes: ['completed_step', 'approval_required'],
        responseContracts: ['business_change_v1'],
        approvalActionCount: 2,
        textIncludes: [
          'Not changed',
          'no matching jobs for priority = low',
          '2 jobs will be updated from medium to high priority',
        ],
        textExcludes: [/Waiting for approval 2/i, /Approval required before applying staged changes/i],
      },
    })
    const approvalCard = page.locator('[data-response-block-type="approval_required"]').last()
    await expect(approvalCard).toContainText('2 jobs will be updated from medium to high priority')
    await expect(approvalCard).toContainText('JOB-SEED-002')
    await expect(approvalCard).not.toContainText('priority = low')
    await testInfo.attach('rd-014-zero-match-active-approval-probe.json', {
      body: serializeSemanticProbe(probe),
      contentType: 'application/json',
    })
  })

  test('RD-001 orphan/session state invariant forbids IDLE non_terminal_snapshot UI', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, responseDocumentCascadePrompt)

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
    const statusCard = page.locator('[data-response-block-type="status_result"][data-response-contract="entity_status_v1"]').last()
    await expect(statusCard).toBeVisible()
    await expandActivity(page, 'Run complete')
    await expect(page.getByText('Run complete').first()).toBeVisible()
    await expect(page.getByText('Machine ID').first()).toBeVisible()
    await expect(page.getByText('Status').first()).toBeVisible()
    await expect(statusCard).toHaveAttribute('data-read-scope', 'status_only')
    await expect(statusCard).toHaveAttribute('data-requested-fields', 'machine_id,status')
    await expect(statusCard).toHaveAttribute('data-display-mode', 'compact_status_card')
    await expect(statusCard).toHaveAttribute('data-entity-count', '1')
    await expect(statusCard).toHaveAttribute('data-preview-limit', '5')
    await expect(statusCard).toHaveAttribute('data-details-collapsed', 'true')
    await expect(statusCard).toHaveAttribute('data-status-field-count', '2')
    await expect(statusCard).toHaveAttribute('data-secondary-field-count', '0')
    await expect(statusCard.locator('[data-status-field]')).toHaveCount(2)
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
        responseContracts: ['entity_status_v1'],
        approvalActionCount: 0,
        forbiddenText: [...readOnlyStatusForbiddenProbeText, ...machineStatusOnlyForbiddenDetailProbeText],
        textIncludes: [
          'Machine ID',
          'Status',
        ],
        textExcludes: [
          /Approval required/i,
          /Mutation result/i,
          /Machine status \(1\)/i,
          /Machine name/i,
          /Machine type/i,
          /Location/i,
          /Capacity per hour/i,
          /Last maintenance/i,
          /Maintenance interval/i,
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
    const backendStatusBlock = summary.backend.responseDocument.blocks.find((block) => block.type === 'status_result')
    const visibleStatusBlock = summary.visible.visibleBlocks.find((block) => block.type === 'status_result')
    expect(backendStatusBlock).toMatchObject({
      contract: 'entity_status_v1',
      readScope: 'status_only',
      requestedFields: ['machine_id', 'status'],
      displayMode: 'compact_status_card',
      entityCount: 1,
      previewLimit: 5,
      detailsCollapsed: true,
      fieldCount: 2,
      secondaryFieldCount: 0,
    })
    expect(visibleStatusBlock).toMatchObject({
      readScope: 'status_only',
      requestedFields: ['machine_id', 'status'],
      displayMode: 'compact_status_card',
      entityCount: 1,
      previewLimit: 5,
      detailsCollapsed: true,
      fieldCount: 2,
      secondaryFieldCount: 0,
    })
    await expect(page.getByText('Approval required')).toHaveCount(0)
    await expect(page.getByRole('button', { name: exactAction('Approve') })).toHaveCount(0)
    await expect(page.getByRole('button', { name: exactAction('Reject') })).toHaveCount(0)

    await sendChatPrompt(page, responseDocumentLotoPrompt)
    await expect(page.getByText(/Use the M-CNC-01 lockout\/tagout procedure/i).first()).toBeVisible()
    await expandActivity(page, 'Run complete')
    await expect(page.getByText('Knowledge sources').first()).toBeVisible()
    await expect(page.getByText('M-CNC-01 Lockout/Tagout Procedure').first()).toBeVisible()
    await expect(page.getByText('LOTO-M-CNC-01').first()).toBeVisible()
    await expectForbiddenTextAbsent(page)
  })

  test('RD-027 job status entity_status compact display policy carries requested fields', async ({ page }, testInfo) => {
    await openChat(page)
    await sendChatPrompt(page, responseDocumentJobStatusPrompt)

    const statusCard = page.locator('[data-response-block-type="status_result"][data-response-contract="entity_status_v1"]').last()
    await expect(statusCard).toBeVisible()
    await expect(statusCard).toHaveAttribute('data-entity-type', 'job')
    await expect(statusCard).toHaveAttribute('data-read-scope', 'status_only')
    await expect(statusCard).toHaveAttribute('data-requested-fields', 'job_id,status')
    await expect(statusCard).toHaveAttribute('data-display-mode', 'compact_status_card')
    await expect(statusCard).toHaveAttribute('data-entity-count', '1')
    await expect(statusCard).toHaveAttribute('data-status-field-count', '2')
    await expect(statusCard).toContainText('Job ID')
    await expect(statusCard).toContainText('JOB-SEED-001')
    await expect(statusCard).toContainText('Status')
    await expect(statusCard).toContainText('running')

    const summary = await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-027 job status entity_status display policy',
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
        forbiddenText: readOnlyStatusForbiddenProbeText,
        textIncludes: ['Job ID', 'JOB-SEED-001', 'Status', 'running'],
        textExcludes: [/Approval required/i, /Priority/i, /Machine ID/i, /Due date/i],
      },
    })
    await testInfo.attach('rd-027-job-status-display-policy-probe.json', {
      body: serializeSemanticProbe(summary),
      contentType: 'application/json',
    })
    const backendStatusBlock = summary.backend.responseDocument.blocks.find((block) => block.type === 'status_result')
    expect(backendStatusBlock).toMatchObject({
      entityType: 'job',
      readScope: 'status_only',
      requestedFields: ['job_id', 'status'],
      displayMode: 'compact_status_card',
      entityCount: 1,
      fieldCount: 2,
    })
  })

  test('RD-028 multi-status entity_status display policy renders collection table without loops', async ({ page }, testInfo) => {
    await openChat(page)
    await sendChatPrompt(page, responseDocumentMultiStatusPrompt)

    const tableBlock = page.locator('[data-response-block-type="result_table"][data-response-contract="entity_status_v1"]').last()
    await expect(tableBlock).toBeVisible()
    await expect(tableBlock).toHaveAttribute('data-entity-type', 'job')
    await expect(tableBlock).toHaveAttribute('data-read-scope', 'status_only')
    await expect(tableBlock).toHaveAttribute('data-requested-fields', 'job_id,status')
    await expect(tableBlock).toHaveAttribute('data-display-mode', 'collection_table')
    await expect(tableBlock).toHaveAttribute('data-entity-count', '2')
    await expect(tableBlock).toHaveAttribute('data-details-collapsed', 'false')
    await expect(tableBlock).toContainText('JOB-SEED-001')
    await expect(tableBlock).toContainText('JOB-SEED-002')
    await expect(tableBlock).toContainText('running')
    await expect(tableBlock).toContainText('planned')

    const summary = await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-028 multi-status entity_status collection display policy',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['result_table'],
        backendBlockTypes: ['result_table'],
        hiddenBlockTypes: ['approval_required', 'diagnostic', 'mutation_result'],
        hiddenBackendBlockTypes: ['approval_required', 'diagnostic', 'mutation_result'],
        responseContracts: ['entity_status_v1'],
        approvalActionCount: 0,
        textIncludes: ['JOB-SEED-001', 'JOB-SEED-002', 'running', 'planned'],
        textExcludes: [/Priority/i, /planner/i, /guard/i, /loop/i],
      },
    })
    await testInfo.attach('rd-028-multi-status-display-policy-probe.json', {
      body: serializeSemanticProbe(summary),
      contentType: 'application/json',
    })
    const backendTable = summary.backend.responseDocument.blocks.find((block) => block.type === 'result_table')
    const visibleTable = summary.visible.visibleBlocks.find((block) => block.type === 'result_table')
    expect(backendTable).toMatchObject({
      contract: 'entity_status_v1',
      readScope: 'status_only',
      requestedFields: ['job_id', 'status'],
      displayMode: 'collection_table',
      entityCount: 2,
      detailsCollapsed: 'false',
    })
    expect(visibleTable).toMatchObject({
      readScope: 'status_only',
      requestedFields: ['job_id', 'status'],
      displayMode: 'collection_table',
      entityCount: 2,
      detailsCollapsed: 'false',
    })
  })

  test('RD-029 machine status details contrast uses collapsed detail display policy', async ({ page }, testInfo) => {
    await openChat(page)
    await sendChatPrompt(page, responseDocumentMachineDetailsPrompt)

    const statusCard = page.locator('[data-response-block-type="status_result"][data-response-contract="entity_status_v1"]').last()
    await expect(statusCard).toBeVisible()
    await expect(statusCard).toHaveAttribute('data-read-scope', 'details')
    await expect(statusCard).toHaveAttribute('data-requested-fields', 'machine_id,status,details')
    await expect(statusCard).toHaveAttribute('data-display-mode', 'detail_status_card')
    await expect(statusCard).toHaveAttribute('data-details-collapsed', 'true')
    await expect(statusCard).toHaveAttribute('data-status-field-count', '2')
    await expect(statusCard).toHaveAttribute('data-secondary-field-count', '6')
    const details = statusCard.locator('details[data-status-details]').first()
    await expectDetailsClosed(details)
    await details.locator('summary').click()
    await expect(statusCard.getByText('Machine name')).toBeVisible()
    await expect(statusCard.getByText('Machine type')).toBeVisible()
    await expect(statusCard.getByText('Location')).toBeVisible()
    await expect(statusCard.getByText('Capacity per hour')).toBeVisible()

    const summary = await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-029 machine status details display policy contrast',
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
        textIncludes: ['Machine ID', 'Status', 'Technical details'],
      },
    })
    await testInfo.attach('rd-029-machine-details-display-policy-probe.json', {
      body: serializeSemanticProbe(summary),
      contentType: 'application/json',
    })
    const backendStatusBlock = summary.backend.responseDocument.blocks.find((block) => block.type === 'status_result')
    expect(backendStatusBlock).toMatchObject({
      readScope: 'details',
      requestedFields: ['machine_id', 'status', 'details'],
      displayMode: 'detail_status_card',
      entityCount: 1,
      detailsCollapsed: true,
      fieldCount: 2,
      secondaryFieldCount: 6,
    })
  })

  test('RD-029 collapsed results display policy renders one collapsed Results surface', async ({ page }, testInfo) => {
    await openChat(page)
    await sendChatPrompt(page, responseDocumentCollapsedResultsPrompt)

    const previewBlock = page.locator('[data-response-block-type="record_preview"][data-display-mode="collapsed_collection_table"]')
    const tableBlock = page.locator('[data-response-block-type="result_table"][data-display-mode="collapsed_collection_table"]').last()
    await expect(previewBlock).toHaveCount(0)
    await expect(tableBlock).toBeVisible()
    await expect(tableBlock).toHaveAttribute('data-read-scope', 'records')
    await expect(tableBlock).toHaveAttribute('data-entity-count', '6')
    await expect(tableBlock).toHaveAttribute('data-preview-limit', '5')
    await expect(tableBlock).toHaveAttribute('data-details-collapsed', 'true')
    await expect(tableBlock.locator('[data-affected-record-row]')).toHaveCount(5)
    const details = tableBlock.locator('details').filter({ hasText: /Results \(6\)/ }).first()
    await expectDetailsClosed(details)

    const summary = await expectTransitionCheckpoint(page, {
      checkpoint: 'RD-029 collapsed results display policy',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['result_table'],
        backendBlockTypes: ['result_table'],
        hiddenBlockTypes: ['approval_required', 'diagnostic', 'mutation_result'],
        hiddenBackendBlockTypes: ['approval_required', 'diagnostic', 'mutation_result', 'record_preview'],
        approvalActionCount: 0,
        textIncludes: ['Found 6 low-priority jobs.', 'Results'],
        textExcludes: ['Preview'],
      },
    })
    await testInfo.attach('rd-029-collapsed-results-display-policy-probe.json', {
      body: serializeSemanticProbe(summary),
      contentType: 'application/json',
    })
    const backendTable = summary.backend.responseDocument.blocks.find((block) => block.type === 'result_table')
    const visibleTable = summary.visible.visibleBlocks.find((block) => block.type === 'result_table')
    expect(backendTable).toMatchObject({
      readScope: 'records',
      displayMode: 'collapsed_collection_table',
      entityCount: 6,
      previewLimit: 5,
      detailsCollapsed: true,
    })
    expect(visibleTable).toMatchObject({
      readScope: 'records',
      displayMode: 'collapsed_collection_table',
      entityCount: 6,
      previewLimit: 5,
      detailsCollapsed: true,
    })
  })

  test('Phase 33 side evidence drawer opens PDF panel with back navigation and related source identity', async ({ page }, testInfo) => {
    test.setTimeout(45_000)
    await openChat(page)
    await sendChatPrompt(page, responseDocumentOshaReenergizingPrompt)

    await expect(page.getByText(/Before reenergizing, notify affected employees/i).first()).toBeVisible()
    await expandActivity(page, 'Run complete')
    await expect(page.getByText('Safety notice').first()).toBeVisible()
    await expect(page.getByText('Knowledge sources').first()).toBeVisible()
    await expect(page.getByText('Control of Hazardous Energy Lockout/Tagout').first()).toBeVisible()
    await expect(page.getByText('osha_3120_lockout_tagout').first()).toBeVisible()
    await expect(page.getByText('View evidence')).toHaveCount(0)
    await expect(page.locator('[data-cited-answer-text]')).toHaveCount(0)

    const sourceChip = page.locator('[data-source-chip][data-source-id="osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0029"]').first()
    await expect(sourceChip).toBeVisible()
    await expect(sourceChip).toHaveAttribute('data-doc-id', 'osha_3120_lockout_tagout')
    await expect(sourceChip).toHaveAttribute('data-chunk-id', 'osha_3120_lockout_tagout_c0029')
    await expect(sourceChip).toHaveAttribute('data-source-number', '1')
    await expect(sourceChip).toHaveAttribute('data-source-title', 'Control of Hazardous Energy Lockout/Tagout')
    await expect(sourceChip).toHaveAttribute('data-source-open-mode', 'exact')
    await expect(sourceChip).toHaveAttribute('data-source-highlight-kind', 'char_range')
    await sourceChip.hover()
    await expect(page.locator('[data-source-chip-hover]').filter({ hasText: 'Control of Hazardous Energy Lockout/Tagout' }).first()).toBeVisible()
    await expect(page.locator('[data-source-chip-hover]').filter({ hasText: 'OSHA' }).first()).toBeVisible()
    await sourceChip.click()
    const citedAnswerText = page.locator('[data-cited-answer-text][data-source-id="osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0029"]').first()
    await expect(citedAnswerText).toBeVisible()
    await expect(citedAnswerText).toHaveAttribute('data-doc-id', 'osha_3120_lockout_tagout')
    await expect(citedAnswerText).toHaveAttribute('data-chunk-id', 'osha_3120_lockout_tagout_c0029')
    await expect(citedAnswerText).toContainText(/Before reenergizing/i)
    const drawer = page.locator('[data-source-drawer]').first()
    await expect(drawer).toBeVisible()
    await expect(page.getByRole('button', { name: 'Expand sessions' })).toBeVisible()
    await sourceChip.click()
    await expect(page.locator('[data-source-drawer]')).toHaveCount(0)
    await expect(page.locator('[data-cited-answer-text]')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Collapse sessions' })).toBeVisible()
    await sourceChip.click()
    await expect(citedAnswerText).toBeVisible()
    await expect(drawer).toBeVisible()
    await expect(page.getByRole('button', { name: 'Expand sessions' })).toBeVisible()
    await expect(drawer).toHaveAttribute('data-shell-evidence-panel', '')
    await expect(page.locator('[data-response-document-root] [data-source-drawer]')).toHaveCount(0)
    expect(await drawer.evaluate((node) => Boolean(node.closest('[data-chatbot-workspace]')))).toBe(true)
    expect(await drawer.evaluate((node) => Boolean(node.closest('[data-assistant-response-card]')))).toBe(false)
    await expect.poll(async () => {
      const main = await elementBox(page.locator('[data-chatbot-workspace-main]').first())
      const side = await elementBox(drawer)
      return main.right - side.left
    }).toBeLessThanOrEqual(24)
    const workspaceBox = await elementBox(page.locator('[data-chatbot-workspace]').first())
    const mainBox = await elementBox(page.locator('[data-chatbot-workspace-main]').first())
    const drawerBox = await elementBox(drawer)
    expect(mainBox.width).toBeGreaterThan(240)
    expect(drawerBox.width).toBeGreaterThan(260)
    expect(mainBox.right).toBeLessThanOrEqual(drawerBox.left + 24)
    expect(drawerBox.right).toBeLessThanOrEqual(workspaceBox.right + 2)
    await expect(drawer).toHaveAttribute('data-doc-id', 'osha_3120_lockout_tagout')
    await expect(drawer).toHaveAttribute('data-chunk-id', 'osha_3120_lockout_tagout_c0029')
    await expect(drawer).toHaveAttribute('data-source-drawer-view', 'list')
    await expect(drawer.locator('[data-source-drawer-resize-handle]')).toBeVisible()
    const citedEntry = drawer.locator('[data-source-drawer-entry][data-source-role="cited"]').first()
    await expect(citedEntry).toHaveAttribute('data-source-id', 'osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0029')
    await expect(citedEntry).toHaveAttribute('data-doc-id', 'osha_3120_lockout_tagout')
    await expect(citedEntry).toHaveAttribute('data-source-number', '1')
    await expect(citedEntry).toHaveAttribute('data-source-title', 'Control of Hazardous Energy Lockout/Tagout')
    await expect(citedEntry.locator('[data-source-drawer-snippet]')).toContainText(/before reenergizing the machine/i)
    await expect(drawer.getByText('Related supporting sources')).toBeVisible()
    const relatedEntry = drawer.locator('[data-source-drawer-entry][data-source-role="related"]').first()
    await expect(relatedEntry).toHaveAttribute('data-source-id', 'osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0030')
    await expect(relatedEntry).toHaveAttribute('data-source-number', '2')
    await expect(relatedEntry).toHaveAttribute('data-doc-id', 'osha_3120_lockout_tagout')
    const pdfAction = citedEntry.locator('[data-source-pdf-link]').first()
    const citedPdfPath = '/documents/osha_3120_lockout_tagout/pdf#page=15&highlight=char_range&char_start=0&char_end=1017'
    await expectFactoryAgentPdfUrl(page, pdfAction, 'data-source-pdf-href', citedPdfPath)
    await expect(pdfAction).toHaveAttribute('data-source-id', 'osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0029')
    await expect(pdfAction).toHaveAttribute('data-doc-id', 'osha_3120_lockout_tagout')
    await expect(pdfAction).toHaveAttribute('data-source-number', '1')
    await expectFactoryAgentPdfResponse(page, () => pdfAction.click(), citedPdfPath)
    await expect(drawer).toHaveAttribute('data-source-drawer-view', 'pdf')
    await expectFactoryAgentPdfUrl(page, drawer.locator('[data-source-pdf-frame]'), 'data-source-pdf-src', citedPdfPath)
    await expect(drawer.locator('[data-source-pdf-frame]')).toHaveAttribute('data-source-pdf-renderer', 'pdfjs')
    await expect(drawer.locator('[data-source-pdf-frame]')).toHaveAttribute('data-source-id', 'osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0029')
    await expect(drawer.locator('[data-source-pdf-evidence]')).toContainText(/highlight.*page 15/i)
    const highlightLayer = drawer.locator('[data-source-pdf-highlight-layer]').first()
    await expect(highlightLayer).toHaveAttribute('data-source-pdf-highlight-kind', 'char_range')
    await expect.poll(async () => Number(await highlightLayer.getAttribute('data-source-pdf-highlight-count') || 0)).toBeGreaterThan(0)
    await expect(drawer.locator('[data-source-pdf-highlight]').first()).toBeVisible()
    const pdfPage = drawer.locator('[data-source-pdf-page]').first()
    const initialPdfPage = await elementBox(pdfPage)
    await drawer.locator('[data-source-pdf-zoom-in]').click()
    await expect(drawer.locator('[data-source-pdf-fit-width]')).toHaveAttribute('data-source-pdf-zoom-value', '110%')
    await expect.poll(async () => {
      const box = await elementBox(pdfPage)
      return box.width
    }).toBeGreaterThan(initialPdfPage.width + 8)
    await drawer.locator('[data-source-pdf-fit-width]').click()
    await expect(drawer.locator('[data-source-pdf-fit-width]')).toHaveAttribute('data-source-pdf-zoom-value', '100%')
    await drawer.locator('[data-source-pdf-back]').click()
    await expect(drawer).toHaveAttribute('data-source-drawer-view', 'list')
    const relatedPdfAction = drawer.locator('[data-source-drawer-entry][data-source-id="osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0030"] [data-source-pdf-link]').first()
    const relatedPdfPath = '/documents/osha_3120_lockout_tagout/pdf#page=15&search=Before+lockout+or+tagout+devices+are+removed+and+energy+is+restored'
    await expectFactoryAgentPdfUrl(page, relatedPdfAction, 'data-source-pdf-href', relatedPdfPath)
    await expectFactoryAgentPdfResponse(page, () => relatedPdfAction.click(), relatedPdfPath)
    await expect(drawer).toHaveAttribute('data-source-drawer-view', 'pdf')
    await expect(drawer.locator('[data-source-pdf-frame]')).toHaveAttribute('data-source-id', 'osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0030')
    await expectFactoryAgentPdfUrl(page, drawer.locator('[data-source-pdf-frame]'), 'data-source-pdf-src', relatedPdfPath)
    await expect(drawer.locator('[data-source-pdf-evidence]')).toContainText(/page 15/i)
    await drawer.locator('[data-source-pdf-back]').click()
    await expect(drawer).toHaveAttribute('data-source-drawer-view', 'list')

    const visible = await visibleText(page)
    expect(visible).not.toMatch(/loto_notification_requirement/i)
    expect(visible).not.toMatch(/LOTO Notification Requirements/i)
    expect(visible).not.toMatch(/Which machine ID/i)

    const summary = await expectTransitionCheckpoint(page, {
      checkpoint: 'Phase 33 positive OSHA side evidence PDF proof',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['safety_notice', 'knowledge_answer', 'source_list'],
        backendBlockTypes: ['safety_notice', 'knowledge_answer', 'source_list'],
        hiddenBlockTypes: ['approval_required', 'diagnostic', 'status_result', 'mutation_result'],
        hiddenBackendBlockTypes: ['approval_required', 'diagnostic', 'status_result', 'mutation_result'],
        approvalActionCount: 0,
        responseContracts: ['safety_notice_v1', 'knowledge_answer_v1', 'source_list_v1', 'source_locator_v1'],
        forbiddenText: documentContentRagForbiddenProbeText,
        textIncludes: [
          'Before reenergizing, notify affected employees',
          'Control of Hazardous Energy Lockout/Tagout',
          'osha_3120_lockout_tagout',
        ],
        textExcludes: [
          /loto_notification_requirement/i,
          /LOTO Notification Requirements/i,
          /Which machine ID/i,
          /Approval required/i,
        ],
      },
    })
    await testInfo.attach('phase33-positive-osha-side-evidence-semantic-probe.json', {
      body: serializeSemanticProbe(summary),
      contentType: 'application/json',
    })
    expect(summary.visible.latestUserPrompt).toContain(responseDocumentOshaReenergizingPrompt)

    const snapshot = await snapshotForPage(page)
    const knowledgeBlock = snapshot.response_document.blocks.find((block) => block.type === 'knowledge_answer')
    const citation = knowledgeBlock.citations?.[0]
    expect(citation?.doc_id).toBe('osha_3120_lockout_tagout')
    expect(citation?.chunk_id).toBe('osha_3120_lockout_tagout_c0029')
    expect(citation?.page).toBe(15)
    expect(citation?.pdf_url).toBe('/documents/osha_3120_lockout_tagout/pdf')
    expect(citation?.char_range || citation?.text_search).toBeTruthy()
    const sourceBlock = snapshot.response_document.blocks.find((block) => block.type === 'source_list')
    const source = sourceBlock.sources[0]
    expect(source.doc_id).toBe(citation.doc_id)
    expect(source.chunk_id).toBe(citation.chunk_id)
    expect(source.page).toBe(15)
    expect(source.pdf_url).toBe('/documents/osha_3120_lockout_tagout/pdf')
    expect(source.char_range || source.text_search).toBeTruthy()
    expect(source.source_id).toBe(citation.source_id)
    expect(source.source_number).toBe(citation.source_number)
    expect(source.title).toBe(citation.title)
    const relatedSource = sourceBlock.sources.find((item) => item.source_number === 2)
    expect(relatedSource?.source_id).toBe('osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0030')
    expect(relatedSource?.doc_id).toBe('osha_3120_lockout_tagout')
    expect(relatedSource?.title).toBe(citation.title)
    expect(JSON.stringify(snapshot.response_document)).not.toMatch(/loto_notification_requirement|LOTO Notification Requirements/i)
  })

  test('Phase 34 response_document source chip tooltip stays inside chat width at the right edge on small screens', async ({ page }) => {
    test.setTimeout(45_000)
    await page.setViewportSize({ width: 430, height: 760 })
    await openChat(page)
    await sendChatPrompt(page, responseDocumentOshaReenergizingPrompt)

    await expect(page.getByText(/Before reenergizing, notify affected employees/i).first()).toBeVisible()
    const sourceChip = page.locator('[data-source-chip][data-source-id="osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0029"]').first()
    await expect(sourceChip).toBeVisible()
    await sourceChip.evaluate((chip) => {
      const wrapper = chip.parentElement
      if (!wrapper) return
      wrapper.style.display = 'flex'
      wrapper.style.justifyContent = 'flex-end'
      wrapper.style.width = '100%'
    })
    await expect.poll(async () => sourceChip.evaluate((chip) => {
      const root = chip.closest('[data-response-document-root]')
      if (!root) return 999999
      const chipRect = chip.getBoundingClientRect()
      const rootRect = root.getBoundingClientRect()
      const distance = rootRect.right - chipRect.right
      return distance >= 0 ? distance : 999999
    })).toBeLessThan(28)

    await sourceChip.hover()
    const tooltip = page.locator('[data-source-chip-hover]').filter({ hasText: 'Control of Hazardous Energy Lockout/Tagout' }).first()
    await expect(tooltip).toBeVisible()
    await expect(tooltip).toHaveCSS('pointer-events', 'none')
    await expect(tooltip).toHaveAttribute('data-source-chip-hover-placement', /bottom-left|top-left|clamped/)
    const metrics = await sourceTooltipMetrics(tooltip)
    if (!metrics) throw new Error('Source tooltip metrics were not available')
    expectBoxInside(metrics.tooltip, metrics.container, 'source chip tooltip in chat container')
    expectBoxInside(metrics.tooltip, metrics.viewport, 'source chip tooltip in viewport')
  })

  test('Phase 34 response_document responsive chatbot resize increases assistant card width', async ({ page }) => {
    test.setTimeout(45_000)
    await page.setViewportSize({ width: 1500, height: 920 })
    await openChat(page)
    await sendChatPrompt(page, responseDocumentCascadePrompt)

    const modal = page.locator('[data-ai-assistant-modal-window]').first()
    const responseCard = page.locator('[data-response-block-type="approval_required"]').first()
    await expect(responseCard).toBeVisible()
    const sidebarHeader = await elementBox(page.locator('[data-chat-session-sidebar-header]').first())
    const topbar = await elementBox(page.locator('[data-chatbot-topbar]').first())
    expect(Math.abs(topbar.height - sidebarHeader.height)).toBeLessThanOrEqual(1.5)
    const initialModal = await elementBox(modal)
    const initialCard = await elementBox(responseCard)
    const handle = page.locator('[data-resize="e"]').first()
    const handleBox = await handle.boundingBox()
    if (!handleBox) throw new Error('East resize handle was not measurable')

    await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2)
    await page.mouse.down()
    await page.mouse.move(handleBox.x + handleBox.width / 2 + 360, handleBox.y + handleBox.height / 2, { steps: 8 })
    await page.mouse.up()

    await expect.poll(async () => {
      const box = await elementBox(modal)
      return box.width
    }).toBeGreaterThan(initialModal.width + 240)

    const widenedCard = await elementBox(responseCard)
    expect(widenedCard.width).toBeGreaterThan(initialCard.width + 180)
    const prose = await elementBox(page.locator('[data-response-document-prose]').first())
    expect(prose.width).toBeGreaterThan(widenedCard.width - 96)
    expect(prose.left).toBeGreaterThanOrEqual(widenedCard.left - 1)
    expect(prose.right).toBeLessThanOrEqual(widenedCard.right + 1)

    const southeastHandle = page.locator('[data-resize="se"]').first()
    const southeastBox = await southeastHandle.boundingBox()
    if (!southeastBox) throw new Error('Southeast resize handle was not measurable')
    await page.mouse.move(southeastBox.x + southeastBox.width / 2, southeastBox.y + southeastBox.height / 2)
    await page.mouse.down()
    await page.mouse.move(southeastBox.x + 2200, southeastBox.y + 2200, { steps: 10 })
    await page.mouse.up()
    const boundedModal = await elementBox(modal)
    expectBoxInside(boundedModal, { left: 0, top: 0, right: 1500, bottom: 920 }, 'resized assistant modal', 2)

    const fullscreenToggle = page.locator('[data-ai-assistant-fullscreen-toggle]').first()
    const closeToggle = page.getByRole('button', { name: 'Close' }).first()
    const fullscreenBox = await elementBox(fullscreenToggle)
    const closeBox = await elementBox(closeToggle)
    expect(Math.abs(fullscreenBox.width - closeBox.width)).toBeLessThanOrEqual(1.5)
    expect(Math.abs(fullscreenBox.height - closeBox.height)).toBeLessThanOrEqual(1.5)
    expect(Math.abs((fullscreenBox.top + fullscreenBox.height / 2) - (closeBox.top + closeBox.height / 2))).toBeLessThanOrEqual(1.5)
    const fullscreenIcon = fullscreenToggle.locator('[data-ai-assistant-fullscreen-icon]')
    await expect(fullscreenToggle).toHaveAttribute('data-ai-assistant-fullscreen-state', 'windowed')
    await expect(fullscreenIcon).toHaveClass(/material-symbols-outlined/)
    await expect(fullscreenIcon).toHaveAttribute('data-ai-assistant-fullscreen-icon', 'maximize')
    await expect(fullscreenIcon).toHaveText('check_box_outline_blank')
    await fullscreenToggle.click()
    await expect(modal).toHaveAttribute('data-ai-assistant-fullscreen', 'true')
    await expect(fullscreenToggle).toHaveAttribute('data-ai-assistant-fullscreen-state', 'fullscreen')
    await expect(fullscreenIcon).toHaveAttribute('data-ai-assistant-fullscreen-icon', 'restore')
    await expect(fullscreenIcon).toHaveText('filter_none')
    const fullscreenModal = await elementBox(modal)
    expectBoxInside(fullscreenModal, { left: 0, top: 0, right: 1500, bottom: 920 }, 'fullscreen assistant modal', 2)
    await fullscreenToggle.click()
    await expect(modal).toHaveAttribute('data-ai-assistant-fullscreen', 'false')
  })

  test('Phase 32 negative OSHA lockout before-starting notification returns insufficient context without machine ID', async ({ page }, testInfo) => {
    test.setTimeout(45_000)
    await openChat(page)
    await sendChatPrompt(page, responseDocumentLotoNotificationPrompt)
    await expect(page.getByText(/I do not have enough retrieved evidence to answer that safely/i).first()).toBeVisible()
    await expect(page.getByText(/related sources checked/i).first()).toBeVisible()
    await expandActivity(page, 'Run complete')
    await expect(page.getByText('Safety notice').first()).toBeVisible()
    await expect(page.getByText(/site-approved SOP/i).first()).toBeVisible()
    await expect(page.locator('[data-source-chip]')).toHaveCount(0)
    await expect(page.getByText('Knowledge sources').first()).toBeVisible()
    await expect(page.getByText('Control of Hazardous Energy Lockout/Tagout').first()).toBeVisible()
    await expect(page.getByText('osha_3120_lockout_tagout').first()).toBeVisible()
    await expect(page.getByText('Which machine ID')).toHaveCount(0)
    await expect(page.getByText('No results')).toHaveCount(0)
    const visible = await visibleText(page)
    expect(visible).not.toMatch(/affected employees must be notified before lockout\/tagout starts/i)
    expect(visible).not.toMatch(/Tell them the equipment will be locked out/i)
    expect(visible).not.toMatch(/loto_notification_requirement/i)
    expect(visible).not.toMatch(/LOTO Notification Requirements/i)
    expect(visible).not.toMatch(/:::safety/i)
    expect(visible).not.toMatch(/Safety Advisory/i)

    const summary = await expectTransitionCheckpoint(page, {
      checkpoint: 'Phase 32 negative OSHA before-starting-lockout insufficient-context contract',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['safety_notice', 'knowledge_answer', 'source_list'],
        backendBlockTypes: ['safety_notice', 'knowledge_answer', 'source_list'],
        hiddenBlockTypes: ['approval_required', 'diagnostic', 'status_result', 'mutation_result'],
        hiddenBackendBlockTypes: ['approval_required', 'diagnostic', 'status_result', 'mutation_result'],
        approvalActionCount: 0,
        responseContracts: ['safety_notice_v1', 'knowledge_answer_v1', 'source_list_v1'],
        forbiddenText: documentContentRagForbiddenProbeText,
        textIncludes: [
          'I do not have enough retrieved evidence to answer that safely.',
          'related sources checked',
          'Safety notice',
          'Control of Hazardous Energy Lockout/Tagout',
        ],
        textExcludes: [
          /Which machine ID/i,
          /No results/i,
          /completed_answer/i,
          /Approval required/i,
          /loto_notification_requirement/i,
          /LOTO Notification Requirements/i,
          /Tell them the equipment will be locked out/i,
        ],
      },
    })
    await testInfo.attach('phase32-negative-osha-insufficient-context-semantic-probe.json', {
      body: serializeSemanticProbe(summary),
      contentType: 'application/json',
    })
    expect(summary.visible.latestUserPrompt).toContain(responseDocumentLotoNotificationPrompt)
    const snapshot = await snapshotForPage(page)
    const safetyBlock = snapshot.response_document.blocks.find((block) => block.type === 'safety_notice')
    expect(safetyBlock).toBeTruthy()
    expect(safetyBlock.contract).toBe('safety_notice_v1')
    const knowledgeBlock = snapshot.response_document.blocks.find((block) => block.type === 'knowledge_answer')
    expect(knowledgeBlock.contract).toBe('knowledge_answer_v1')
    expect(knowledgeBlock.answer).toMatch(/^I do not have enough retrieved evidence/i)
    expect(knowledgeBlock.citations || []).toHaveLength(0)
    expect(knowledgeBlock.segments?.[0]?.citation_ids || []).toHaveLength(0)
    const sourceBlock = snapshot.response_document.blocks.find((block) => block.type === 'source_list')
    expect(sourceBlock).toBeTruthy()
    expect(sourceBlock.contract).toBe('source_list_v1')
    for (const source of sourceBlock.sources) {
      expect(source.contract).toBe('source_locator_v1')
      for (const key of ['source_id', 'source_number', 'doc_id', 'chunk_id', 'title', 'organization', 'snippet']) {
        expect(source[key]).toBeTruthy()
      }
      expect(source.file_path).toBeUndefined()
      expect(source.doc_id).toBe('osha_3120_lockout_tagout')
      expect(source.policy_only).toBeUndefined()
    }
    expect(snapshot.response_document.message).not.toBe(snapshot.response_document.blocks.find((block) => block.type === 'knowledge_answer')?.answer)
    expect(snapshot.response_document.message).toMatch(/^I do not have enough retrieved evidence/i)
    expect(JSON.stringify(snapshot.response_document)).not.toMatch(/loto_notification_requirement|LOTO Notification Requirements|Tell them the equipment will be locked out/i)
  })

  test('typed RAG mixed operation answer renders separate operation and procedure sections', async ({ page }, testInfo) => {
    test.setTimeout(45_000)
    await openChat(page)
    await sendChatPrompt(page, responseDocumentMixedOperationRagPrompt)

    await expect(page.getByText('Machine status').first()).toBeVisible()
    await expect(page.getByText('Procedure guidance').first()).toBeVisible()
    await expect(page.getByText('Knowledge sources').first()).toBeVisible()
    await expect(page.getByText(/M-CNC-01 is running\./i).first()).toBeVisible()
    await expect(page.getByText(/Before reenergizing after lockout or tagout devices are removed/i).first()).toBeVisible()

    const operationSections = page.locator('[data-response-block-type="status_result"][data-response-contract="entity_status_v1"]')
    const guidanceSections = page.locator('[data-response-block-type="knowledge_answer"][data-response-contract="knowledge_answer_v1"]')
    const operationSection = operationSections.first()
    const guidanceSection = guidanceSections.first()
    await expect(operationSection).toBeVisible()
    await expect(guidanceSection).toBeVisible()
    await expect(operationSections).toHaveCount(1)
    await expect(guidanceSections).toHaveCount(1)
    await expect(guidanceSection.locator('[data-source-chip]')).toHaveCount(1)

    const summary = await expectTransitionCheckpoint(page, {
      checkpoint: 'Phase 28 mixed operation plus RAG sections',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['status_result', 'safety_notice', 'knowledge_answer', 'source_list'],
        backendBlockTypes: ['status_result', 'safety_notice', 'knowledge_answer', 'source_list'],
        hiddenBlockTypes: ['approval_required', 'diagnostic', 'mutation_result'],
        hiddenBackendBlockTypes: ['approval_required', 'diagnostic', 'mutation_result'],
        responseContracts: ['entity_status_v1', 'safety_notice_v1', 'knowledge_answer_v1', 'source_list_v1'],
        forbiddenText: documentContentRagForbiddenProbeText,
        textIncludes: [
          'Machine status',
          'Procedure guidance',
          'M-CNC-01 is running.',
          'Before reenergizing after lockout or tagout devices are removed',
        ],
      },
    })
    await testInfo.attach('phase28-mixed-operation-rag-semantic-probe.json', {
      body: serializeSemanticProbe(summary),
      contentType: 'application/json',
    })
  })

  test('source PDF highlight locator opens cited page before source drawer fallback', async ({ page }, testInfo) => {
    test.setTimeout(45_000)
    await openChat(page)
    await sendChatPrompt(page, responseDocumentSourcePdfPrompt)

    await expect(page.getByText(/PDF-backed LOTO source opens on the cited page/i).first()).toBeVisible()
    const sourceChip = page.locator('[data-source-chip][data-source-id="osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0007"]').first()
    await expect(sourceChip).toBeVisible()
    await expect(sourceChip).toHaveAttribute('data-source-open-mode', 'exact')
    await expect(sourceChip).toHaveAttribute('data-source-highlight-kind', 'char_range')
    await sourceChip.click()

    const drawer = page.locator('[data-source-drawer][data-source-open-mode="exact"][data-source-highlight-kind="char_range"]').first()
    await expect(drawer).toBeVisible()
    await expect(drawer.locator('[data-source-drawer-snippet]')).toContainText(/Affected employees must be notified/i)
    const link = drawer.locator('[data-source-pdf-link]').first()
    await expect(link).toBeVisible()
    const pdfPath = '/documents/osha_3120_lockout_tagout/pdf#page=9&highlight=char_range&char_start=488&char_end=606'
    await expectFactoryAgentPdfUrl(page, link, 'data-source-pdf-href', pdfPath)

    const summary = await expectTransitionCheckpoint(page, {
      checkpoint: 'Phase 29 source PDF highlight locator',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['knowledge_answer', 'source_list'],
        backendBlockTypes: ['knowledge_answer', 'source_list'],
        hiddenBlockTypes: ['approval_required', 'diagnostic', 'mutation_result'],
        hiddenBackendBlockTypes: ['approval_required', 'diagnostic', 'mutation_result'],
        approvalActionCount: 0,
        responseContracts: ['knowledge_answer_v1', 'source_list_v1', 'source_locator_v1'],
        textIncludes: ['Control of Hazardous Energy Lockout/Tagout'],
        textExcludes: [/file_path/i, /C:\\/i, /\/Users\//i],
      },
    })
    await testInfo.attach('phase-29-source-pdf-highlight-semantic-probe.json', {
      body: serializeSemanticProbe(summary),
      contentType: 'application/json',
    })
    expect(summary.visible.latestUserPrompt).toContain(responseDocumentSourcePdfPrompt)
    const snapshot = await snapshotForPage(page)
    const sourceBlock = snapshot.response_document.blocks.find((block) => block.type === 'source_list')
    const source = sourceBlock.sources[0]
    expect(source.pdf_url).toBe('/documents/osha_3120_lockout_tagout/pdf')
    expect(source.page).toBe(9)
    expect(source.char_range).toEqual([488, 606])
    expect(JSON.stringify(snapshot.response_document)).not.toMatch(/file_path|C:\\|\/Users\//i)
  })

  test('source PDF text-search locator opens matching highlight without stale coordinates', async ({ page }, testInfo) => {
    test.setTimeout(45_000)
    await openChat(page)
    await sendChatPrompt(page, responseDocumentTextSearchPdfPrompt)

    await expect(page.getByText(/claim-specific text-search highlight/i).first()).toBeVisible()
    const sourceChip = page.locator('[data-source-chip][data-source-id="osha_3120_lockout_tagout#text-search-claim"]').first()
    await expect(sourceChip).toBeVisible()
    await expect(sourceChip).toHaveAttribute('data-source-open-mode', 'search')
    await expect(sourceChip).toHaveAttribute('data-source-highlight-kind', 'text_search')
    await sourceChip.click()

    const drawer = page.locator('[data-source-drawer][data-source-open-mode="search"][data-source-highlight-kind="text_search"]').first()
    await expect(drawer).toBeVisible()
    await expect(drawer.locator('[data-source-drawer-snippet]')).toContainText(/After removing the lockout/i)
    const link = drawer.locator('[data-source-evidence-item] [data-source-pdf-link]').first()
    await expect(link).toBeVisible()
    await expect(link).toHaveAttribute('data-source-highlight-kind', 'text_search')
    const pdfPath = '/documents/osha_3120_lockout_tagout/pdf#page=15&search=After+removing+the+lockout'
    await expectFactoryAgentPdfUrl(page, link, 'data-source-pdf-href', pdfPath)
    await expectFactoryAgentPdfResponse(page, () => link.click(), pdfPath)
    await expect(drawer).toHaveAttribute('data-source-drawer-view', 'pdf')
    await expectFactoryAgentPdfUrl(page, drawer.locator('[data-source-pdf-frame]'), 'data-source-pdf-src', pdfPath)
    await expect(drawer.locator('[data-source-pdf-frame]')).toHaveAttribute('data-source-pdf-renderer', 'pdfjs')
    await expect(drawer.locator('[data-source-pdf-frame]')).toHaveAttribute('data-source-id', 'osha_3120_lockout_tagout#text-search-claim:evidence-1')
    await expect(drawer.locator('[data-source-pdf-evidence]')).toContainText(/Matching text on page 15/i)
    const highlightLayer = drawer.locator('[data-source-pdf-highlight-layer]').first()
    await expect(highlightLayer).toHaveAttribute('data-source-pdf-highlight-kind', 'text_search')
    await expect.poll(async () => Number(await highlightLayer.getAttribute('data-source-pdf-highlight-count') || 0)).toBeGreaterThan(0)
    await expect(drawer.locator('[data-source-pdf-highlight]').first()).toBeVisible()

    const summary = await expectTransitionCheckpoint(page, {
      checkpoint: 'source PDF text-search highlight locator',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['knowledge_answer', 'source_list'],
        backendBlockTypes: ['knowledge_answer', 'source_list'],
        hiddenBlockTypes: ['approval_required', 'diagnostic', 'mutation_result'],
        hiddenBackendBlockTypes: ['approval_required', 'diagnostic', 'mutation_result'],
        approvalActionCount: 0,
        responseContracts: ['knowledge_answer_v1', 'source_list_v1', 'source_locator_v1'],
        textIncludes: ['Control of Hazardous Energy Lockout/Tagout'],
        textExcludes: [/file_path/i, /C:\\/i, /\/Users\//i],
      },
    })
    await testInfo.attach('source-pdf-text-search-highlight-semantic-probe.json', {
      body: serializeSemanticProbe(summary),
      contentType: 'application/json',
    })
    expect(summary.visible.latestUserPrompt).toContain(responseDocumentTextSearchPdfPrompt)
    const snapshot = await snapshotForPage(page)
    const knowledgeBlock = snapshot.response_document.blocks.find((block) => block.type === 'knowledge_answer')
    const citation = knowledgeBlock.citations?.[0]
    expect(citation?.text_search).toContain('After removing the lockout')
    expect(citation?.char_range).toBeUndefined()
    expect(citation?.bbox).toBeUndefined()
    expect(citation?.evidence?.[0]?.text_search).toContain('After removing the lockout')
    expect(citation?.evidence?.[0]?.char_range).toBeUndefined()
    expect(citation?.evidence?.[0]?.bbox).toBeUndefined()
  })

  test('expanded parent PDF source opens page-only without hidden highlight', async ({ page }, testInfo) => {
    test.setTimeout(45_000)
    await openChat(page)
    await sendChatPrompt(page, responseDocumentExpandedParentPageOnlyPrompt)

    await expect(page.getByText(/parent source reference/i).first()).toBeVisible()
    const sourceChip = page.locator('[data-source-chip][data-source-id="nist_csf_2_0#brse-parent"]').first()
    await expect(sourceChip).toBeVisible()
    await expect(sourceChip).toHaveAttribute('data-source-open-mode', 'page')
    await expect(sourceChip).not.toHaveAttribute('data-source-highlight-kind', /.+/)
    await sourceChip.click()

    const drawer = page.locator('[data-source-drawer][data-source-open-mode="page"]').first()
    await expect(drawer).toBeVisible()
    await expect(drawer).not.toHaveAttribute('data-source-highlight-kind', /.+/)
    await expect(drawer.locator('[data-source-evidence-item]')).toHaveCount(0)
    await expect(drawer.locator('[data-source-drawer-snippet]')).toContainText(/GOVERN Function provides outcomes/i)
    const link = drawer.locator('[data-source-pdf-link]').first()
    await expect(link).toBeVisible()
    await expect(link).not.toHaveAttribute('data-source-highlight-kind', /.+/)
    const pdfPath = '/documents/nist_csf_2_0/pdf#page=8'
    await expectFactoryAgentPdfUrl(page, link, 'data-source-pdf-href', pdfPath)
    await expectFactoryAgentPdfResponse(page, () => link.click(), pdfPath)
    await expect(drawer).toHaveAttribute('data-source-drawer-view', 'pdf')
    const pdfFrame = drawer.locator('[data-source-pdf-frame]').first()
    await expectFactoryAgentPdfUrl(page, pdfFrame, 'data-source-pdf-src', pdfPath)
    await expect(pdfFrame).toHaveAttribute('data-source-pdf-renderer', 'pdfjs')
    await expect(pdfFrame).toHaveAttribute('data-source-id', 'nist_csf_2_0#brse-parent')
    await expect(pdfFrame).not.toHaveAttribute('data-source-highlight-kind', /.+/)
    await expect(drawer.locator('[data-source-pdf-evidence]')).toContainText(/Showing page 8/i)
    const highlightLayer = drawer.locator('[data-source-pdf-highlight-layer]').first()
    await expect(highlightLayer).not.toHaveAttribute('data-source-pdf-highlight-kind', /.+/)
    await expect(highlightLayer).toHaveAttribute('data-source-pdf-highlight-count', '0')
    await expect(drawer.locator('[data-source-pdf-highlight]')).toHaveCount(0)

    const summary = await expectTransitionCheckpoint(page, {
      checkpoint: 'expanded parent PDF source page-only locator',
      snapshotForPage,
      testInfo,
      expected: {
        sessionStatus: 'COMPLETED',
        responseState: 'completed',
        pendingApprovalId: null,
        visibleBlockTypes: ['knowledge_answer', 'source_list'],
        backendBlockTypes: ['knowledge_answer', 'source_list'],
        hiddenBlockTypes: ['approval_required', 'diagnostic', 'mutation_result'],
        hiddenBackendBlockTypes: ['approval_required', 'diagnostic', 'mutation_result'],
        approvalActionCount: 0,
        responseContracts: ['knowledge_answer_v1', 'source_list_v1', 'source_locator_v1'],
        textIncludes: ['The NIST Cybersecurity Framework (CSF) 2.0'],
        textExcludes: [/file_path/i, /C:\\/i, /\/Users\//i],
      },
    })
    await testInfo.attach('expanded-parent-page-only-semantic-probe.json', {
      body: serializeSemanticProbe(summary),
      contentType: 'application/json',
    })
    expect(summary.visible.latestUserPrompt).toContain(responseDocumentExpandedParentPageOnlyPrompt)
    const snapshot = await snapshotForPage(page)
    const knowledgeBlock = snapshot.response_document.blocks.find((block) => block.type === 'knowledge_answer')
    const citation = knowledgeBlock.citations?.[0]
    expect(citation?.text_search).toContain('GOVERN Function provides outcomes')
    expect(citation?.evidence).toBeUndefined()
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
