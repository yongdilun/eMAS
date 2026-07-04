import { expect, test } from '@playwright/test'
import { chatSelectors } from '../fixtures/selectors.js'
import {
  activityActiveRetryStoryPrompt,
  activityRetryCollapseHandoffPrompt,
  activitySseAnswer,
  activitySseApprovalNoPendingPrompt,
  activitySseApprovalResumePrompt,
  activitySseDelayedFallbackPrompt,
  activitySseGraphDuplicatePrompt,
  activitySsePrompt,
  activitySseResponseDocumentPrompt,
  activitySharedTimestampOrderPrompt,
} from '../fixtures/factoryAgentFixtures.js'

const mockBaseUrl = `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_FACTORY_AGENT_PORT || 8015)}`

async function getMockJson(path) {
  const response = await fetch(`${mockBaseUrl}${path}`)
  if (!response.ok) throw new Error(`Could not read mock ${path}: ${response.status}`)
  return response.json()
}

async function connectionsFor(query) {
  const params = new URLSearchParams(query)
  const body = await getMockJson(`/__test/sse-connections?${params}`)
  return body.connections || []
}

async function requestsFor(query) {
  const params = new URLSearchParams(query)
  const body = await getMockJson(`/__test/requests?${params}`)
  return body.requests || []
}

async function sseEventsFor(query) {
  const params = new URLSearchParams(query)
  const body = await getMockJson(`/__test/sse-events?${params}`)
  return body.events || []
}

async function activityRowLabels(page) {
  return page.locator('.activity-timeline-row').evaluateAll((rows) =>
    rows.map((row) => {
      const firstLine = String(row.innerText || '').split('\n')[0] || ''
      return firstLine.replace(/\s+Current\s*$/, '').trim()
    }),
  )
}

async function activeSessionId(page) {
  return page.evaluate(() => window.localStorage.getItem('factory_agent_active_session_id'))
}

async function snapshotForPage(page) {
  const sessionId = await activeSessionId(page)
  if (!sessionId) throw new Error('No active Factory Agent session id')
  const response = await fetch(`${mockBaseUrl}/sessions/${sessionId}/snapshot`, {
    headers: { 'X-User-Id': 'frontend-operator' },
  })
  if (!response.ok) throw new Error(`Could not read snapshot: ${response.status}`)
  return response.json()
}

function assertMonotonicUniqueFrameIds(events) {
  const ids = events.map((entry) => Number(entry.id))
  expect(ids.every(Number.isFinite)).toBe(true)
  expect(ids).toEqual([...ids].sort((a, b) => a - b))
  expect(new Set(ids).size).toBe(ids.length)
}

function activitySnapshotSteps(entry) {
  return entry?.data?.activity_steps || entry?.data?.activitySteps || []
}

function latestSnapshotSteps(events) {
  return activitySnapshotSteps(events.at(-1))
}

function latestSnapshotLabels(events) {
  return latestSnapshotSteps(events).map((step) => step.label)
}

function allSnapshotLabels(events) {
  return events.flatMap((entry) => activitySnapshotSteps(entry).map((step) => step.label))
}

function allSnapshotStepIds(events) {
  return events.flatMap((entry) => activitySnapshotSteps(entry).map((step) => step.id))
}

function assertLatestFrameLabels(events, expectedLabels) {
  expect(latestSnapshotLabels(events)).toEqual(expectedLabels)
}

function assertSnapshotLengthsNeverShrink(events) {
  const lengths = events.map((entry) => activitySnapshotSteps(entry).length)
  for (let index = 1; index < lengths.length; index += 1) {
    expect(lengths[index]).toBeGreaterThanOrEqual(lengths[index - 1])
  }
}

async function activitySnapshotEventsFor(scenario) {
  return sseEventsFor({
    scenario,
    stream: 'activity',
    event: 'activity_snapshot',
  })
}

function assertTimelineOrder(snapshot, expectedTypes) {
  const types = snapshot.timeline.map((event) => event.event_type)
  for (const type of expectedTypes) {
    expect(types).toContain(type)
  }
  for (let index = 1; index < expectedTypes.length; index += 1) {
    expect(types.indexOf(expectedTypes[index - 1])).toBeLessThan(types.indexOf(expectedTypes[index]))
  }
}

async function openChat(page) {
  await page.goto('/')
  await page.getByRole('button', { name: chatSelectors.openAssistantButtonName }).click()
  await expect(page.getByRole('dialog', { name: chatSelectors.dialogName })).toBeVisible()
}

async function sendChatPrompt(page, prompt) {
  const composer = page.getByPlaceholder(chatSelectors.composerPlaceholder)
  await expect(composer).toBeEnabled()
  await composer.fill(prompt)
  await page.getByRole('button', { name: chatSelectors.sendButtonName }).click()
  await expect(page.getByText(prompt)).toBeVisible()
}

test.describe('Factory Agent chat SSE activity stream @sse', () => {
  test.describe.configure({ mode: 'serial' })

  test('activity stream shows ordered steps and gates the final answer until completed snapshot state', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, activitySsePrompt)

    await expect
      .poll(async () => {
        const connections = await connectionsFor({
          scenario: 'activitySseOrdered',
          stream: 'activity',
          event: 'open',
        })
        return connections.length
      })
      .toBeGreaterThan(0)

    await page.getByRole('button', { name: /Run complete[\s\S]*4 updates/i }).click()
    await expect(page.getByText('SSE understanding request')).toBeVisible()
    await expect(page.getByText('SSE checking machine telemetry')).toBeVisible()
    await expect(page.getByText('SSE validating result')).toBeVisible()

    const activityList = page.locator('ol').filter({ hasText: 'SSE understanding request' }).first()
    const activityText = await activityList.innerText()
    expect(activityText.indexOf('SSE understanding request')).toBeLessThan(
      activityText.indexOf('SSE checking machine telemetry'),
    )
    expect(activityText.indexOf('SSE checking machine telemetry')).toBeLessThan(
      activityText.indexOf('SSE validating result'),
    )

    await expect(page.getByText(/heartbeat/i)).toHaveCount(0)

    await expect(page.getByText(activitySseAnswer).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.locator('[role="status"][aria-busy="true"]')).toHaveCount(0)

    const activityFrames = await activitySnapshotEventsFor('activitySseOrdered')
    assertMonotonicUniqueFrameIds(activityFrames)
    assertLatestFrameLabels(activityFrames, [
      'SSE understanding request',
      'SSE checking machine telemetry',
      'SSE validating result',
    ])

    const snapshot = await snapshotForPage(page)
    expect(snapshot.session.status).toBe('COMPLETED')
    expect(snapshot.activity_steps.map((step) => step.label)).toEqual([
      'SSE understanding request',
      'SSE checking machine telemetry',
      'SSE validating result',
      'Run complete',
    ])
    assertTimelineOrder(snapshot, ['plan_created', 'execution_started', 'tool_result', 'session_completed'])

    const notificationConnections = await connectionsFor({
      scenario: 'activitySseOrdered',
      stream: 'notification',
      event: 'open',
    })
    expect(notificationConnections.length).toBeGreaterThan(0)

    const requests = await requestsFor({ scenario: 'activitySseOrdered' })
    expect(requests.some((entry) => entry.path.endsWith('/events/activity'))).toBe(true)
    expect(requests.some((entry) => entry.path.endsWith('/snapshot'))).toBe(true)

    expect(() => assertMonotonicUniqueFrameIds([{ id: 2 }, { id: 2 }])).toThrow()
    expect(() => assertLatestFrameLabels(activityFrames.slice(0, 1), [
      'SSE understanding request',
      'SSE checking machine telemetry',
      'SSE validating result',
    ])).toThrow()
  })

  test('response_document turns render live activity before final snapshot completion', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, activitySseResponseDocumentPrompt)

    await expect
      .poll(async () => {
        const activityFrames = await activitySnapshotEventsFor('activitySseResponseDocument')
        return allSnapshotLabels(activityFrames)
      })
      .toContain('SSE checking machine telemetry')

    await expect(page.getByText('Session activity')).toBeVisible()
    const rdActivityList = page.locator('ol').filter({ hasText: 'SSE checking machine telemetry' }).first()
    await expect(rdActivityList.getByText('SSE checking machine telemetry', { exact: true })).toBeVisible()
    await expect(rdActivityList.getByText('Reading M-CNC-01 status and alarm records', { exact: true })).toBeVisible()
    await expect(page.getByText('Working on response-document activity stream.')).toBeVisible()
    await expect(page.getByText(activitySseAnswer).first()).not.toBeVisible()
    await expect(page.getByText('Run complete')).not.toBeVisible({ timeout: 250 })

    await expect
      .poll(async () => {
        const requests = await requestsFor({ scenario: 'activitySseResponseDocument' })
        return requests.filter((entry) => String(entry.path || '').endsWith('/snapshot')).length
      })
      .toBeGreaterThanOrEqual(3)

    await expect(rdActivityList.getByText('SSE checking machine telemetry', { exact: true })).toBeVisible()
    await expect(rdActivityList.getByText('Reading M-CNC-01 status and alarm records', { exact: true })).toBeVisible()
    await expect(page.getByText(activitySseAnswer).first()).not.toBeVisible()

    await expect
      .poll(async () => {
        const activityFrames = await activitySnapshotEventsFor('activitySseResponseDocument')
        return allSnapshotLabels(activityFrames)
      })
      .toContain('SSE validating result')

    await expect
      .poll(async () => {
        const activityFrames = await activitySnapshotEventsFor('activitySseResponseDocument')
        return allSnapshotLabels(activityFrames)
      })
      .toContain('Run complete')

    if (!(await page.getByText(activitySseAnswer).first().isVisible().catch(() => false))) {
      await expect(page.getByText('Working on response-document activity stream.')).toBeVisible()
      await expect(page.getByText('Run complete')).not.toBeVisible({ timeout: 250 })
    }

    await expect(page.getByText(activitySseAnswer).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.getByText('Working on response-document activity stream.')).not.toBeVisible()
  })

  test('delayed server activity replaces one neutral client fallback without generic status spam', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, activitySseDelayedFallbackPrompt)

    await expect(page.getByText('This updates as the session progresses')).toHaveCount(0)
    await expect(page.getByText('Understanding...')).toHaveCount(0)
    await expect(page.getByText('Checking information...')).toHaveCount(0)
    await expect(page.getByText('Wrapping up…')).toHaveCount(0)
    await expect(page.getByText('Reviewing results...')).toHaveCount(0)
    await expect
      .poll(async () => page.getByText('Starting request...').count())
      .toBeLessThanOrEqual(1)

    await expect
      .poll(async () => {
        const activityFrames = await activitySnapshotEventsFor('activitySseDelayedFallback')
        return allSnapshotLabels(activityFrames)
      })
      .toContain('SSE understanding request')

    const delayedActivityList = page.locator('ol').filter({ hasText: 'SSE understanding request' }).first()
    await expect(delayedActivityList.getByText('SSE understanding request', { exact: true })).toBeVisible()
    await expect(page.getByText('Starting request...')).toHaveCount(0)
    await expect(page.getByText('This updates as the session progresses')).toHaveCount(0)
    await expect(page.getByText('Understanding...')).toHaveCount(0)
    await expect(page.getByText('Checking information...')).toHaveCount(0)
    await expect(page.getByText('Wrapping up…')).toHaveCount(0)
    await expect(page.getByText('Reviewing results...')).toHaveCount(0)

    await expect
      .poll(async () => {
        const requests = await requestsFor({ scenario: 'activitySseDelayedFallback' })
        return requests.filter((entry) => String(entry.path || '').endsWith('/snapshot')).length
      })
      .toBeGreaterThanOrEqual(2)

    await expect(delayedActivityList.getByText('SSE understanding request', { exact: true })).toBeVisible()
    await expect(delayedActivityList.getByText('SSE checking machine telemetry', { exact: true })).toBeVisible()
    await expect(page.getByText(activitySseAnswer).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
  })

  test('graph activity does not duplicate understood rows and completed answer appears', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, activitySseGraphDuplicatePrompt)

    await expect
      .poll(async () => {
        const activityFrames = await activitySnapshotEventsFor('activitySseGraphDuplicate')
        return allSnapshotLabels(activityFrames)
      })
      .toContain('Searching knowledge sources')

    await expect(page.getByText('Session activity')).toBeVisible()
    const activityList = page.locator('ol').filter({ hasText: 'Searching knowledge sources' }).first()
    await expect(activityList.getByText('Searching knowledge sources', { exact: true })).toBeVisible()
    await expect
      .poll(async () => activityList.getByText('Understood request', { exact: true }).count())
      .toBeLessThanOrEqual(1)
    await expect(activityList.getByText('Understanding your request', { exact: true })).toHaveCount(0)

    await expect(page.getByText(activitySseAnswer).first()).toBeVisible()
    await expect(page.getByText('Run complete')).toBeVisible()
    await expect(page.getByText("I'm working on the request and waiting for the next backend update.")).toHaveCount(0)
    await expect(page.getByText('Working on response-document activity stream.')).toHaveCount(0)
  })

  test('approval resume SSE renders one clean timeline without raw graph rows', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, activitySseApprovalResumePrompt)

    await expect(page.getByText('Approval required')).toBeVisible()
    await expect(page.getByText('5 jobs will be updated from low to medium priority.').first()).toBeVisible()

    await expect
      .poll(async () => {
        const activityFrames = await activitySnapshotEventsFor('activitySseApprovalResume')
        return latestSnapshotLabels(activityFrames)
      })
      .toEqual([
        'Understood request',
        'Structuring request',
        'Finding information path',
        'Selecting safe action',
        'Found 5 low-priority jobs',
        'Prepared change preview',
        'Waiting for your approval',
      ])

    await expect
      .poll(async () => {
        const requests = await requestsFor({ scenario: 'activitySseApprovalResume' })
        return requests.filter((entry) => String(entry.path || '').endsWith('/snapshot')).length
      })
      .toBeGreaterThanOrEqual(2)

    await page.waitForTimeout(750)
    const preApprovalFrames = await activitySnapshotEventsFor('activitySseApprovalResume')
    assertMonotonicUniqueFrameIds(preApprovalFrames)
    assertSnapshotLengthsNeverShrink(preApprovalFrames)
    expect(latestSnapshotLabels(preApprovalFrames)).toEqual([
      'Understood request',
      'Structuring request',
      'Finding information path',
      'Selecting safe action',
      'Found 5 low-priority jobs',
      'Prepared change preview',
      'Waiting for your approval',
    ])
    expect(allSnapshotStepIds(preApprovalFrames).every((id) => String(id || '').startsWith('act:display:'))).toBe(true)
    for (const leakedRawApprovalLabel of [
      'Waiting for parent evidence',
      'Preparing backend action',
      'Preparing write approval',
      'Checking result',
      'Verifying result',
      'Reading 3 job records',
    ]) {
      expect(allSnapshotLabels(preApprovalFrames)).not.toContain(leakedRawApprovalLabel)
    }

    const midLabels = await activityRowLabels(page)
    expect(midLabels).toEqual([
      'Understood request',
      'Structuring request',
      'Finding information path',
      'Selecting safe action',
      'Found 5 low-priority jobs',
      'Prepared change preview',
      'Waiting for your approval',
    ])
    expect(midLabels).not.toContain('Waiting for parent evidence')

    const preApprovalActivityList = page.locator('ol').filter({ hasText: 'Found 5 low-priority jobs' }).first()
    await expect(preApprovalActivityList.getByText('Found 5 low-priority jobs', { exact: true })).toBeVisible()
    for (const leakedPreApprovalLabel of [
      'Waiting for parent evidence',
      'Preparing backend action',
      'Preparing write approval',
      'Checking result',
      'Verifying result',
    ]) {
      await expect(preApprovalActivityList.getByText(leakedPreApprovalLabel, { exact: true })).toHaveCount(0)
    }

    await page.getByRole('button', { name: 'Approve' }).click()

    await expect
      .poll(async () => {
        const activityFrames = await activitySnapshotEventsFor('activitySseApprovalResume')
        return latestSnapshotLabels(activityFrames)
      })
      .toEqual([
        'Understood request',
        'Structuring request',
        'Finding information path',
        'Selecting safe action',
        'Found 5 low-priority jobs',
        'Prepared change preview',
        'Waiting for your approval',
        'Approval received',
        'Applied approved change',
        'Read updated jobs',
        'Verified updated result',
      ])

    const emittedFrames = await activitySnapshotEventsFor('activitySseApprovalResume')
    assertMonotonicUniqueFrameIds(emittedFrames)
    assertSnapshotLengthsNeverShrink(emittedFrames)
    expect(allSnapshotStepIds(emittedFrames).every((id) => String(id || '').startsWith('act:display:'))).toBe(true)

    const activityList = page.locator('ol').filter({ hasText: 'Found 5 low-priority jobs' }).first()
    await expect
      .poll(async () => {
        try {
          return await activityList.innerText()
        } catch {
          return ''
        }
      }, { timeout: 3000 })
      .toContain('Verified updated result')
    const activityText = await activityList.innerText()
    const expectedOrder = [
      'Understood request',
      'Structuring request',
      'Finding information path',
      'Selecting safe action',
      'Found 5 low-priority jobs',
      'Prepared change preview',
      'Waiting for your approval',
      'Approval received',
      'Applied approved change',
      'Verified updated result',
    ]
    for (const expectedLabel of expectedOrder) {
      expect(activityText).toContain(expectedLabel)
    }
    expect((activityText.match(/Waiting for your approval/g) || []).length).toBe(1)
    for (let idx = 1; idx < expectedOrder.length; idx += 1) {
      expect(activityText.indexOf(expectedOrder[idx - 1])).toBeLessThan(activityText.indexOf(expectedOrder[idx]))
    }
    for (const leakedLabel of [
      'Waiting for parent evidence',
      'Reading 3 job records',
      'Preparing backend action',
      'Preparing write approval',
      'Checking result',
      'Verifying result',
    ]) {
      expect(activityText).not.toContain(leakedLabel)
      expect(allSnapshotLabels(emittedFrames)).not.toContain(leakedLabel)
    }

    await expect(page.getByText('Approval activity SSE rendered one clean timeline after approval.').first()).toBeVisible()
  })

  test('planned approval SSE stays clean before pending approval object exists', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, activitySseApprovalNoPendingPrompt)

    const expectedLabels = [
      'Understood request',
      'Structuring request',
      'Finding information path',
      'Selecting safe action',
      'Prepared change preview',
      'Waiting for your approval',
    ]

    await expect
      .poll(async () => latestSnapshotLabels(await activitySnapshotEventsFor('activitySseApprovalNoPending')))
      .toEqual(expectedLabels)

    await page.waitForTimeout(900)
    const emittedFrames = await activitySnapshotEventsFor('activitySseApprovalNoPending')
    assertMonotonicUniqueFrameIds(emittedFrames)
    assertSnapshotLengthsNeverShrink(emittedFrames)
    expect(latestSnapshotLabels(emittedFrames)).toEqual(expectedLabels)
    expect(allSnapshotStepIds(emittedFrames).every((id) => String(id || '').startsWith('act:display:'))).toBe(true)

    const leakedRawLabels = [
      'Waiting for parent evidence',
      'Preparing backend action',
      'Preparing write approval',
      'Checking result',
      'Verifying result',
    ]
    for (const leakedLabel of leakedRawLabels) {
      expect(allSnapshotLabels(emittedFrames)).not.toContain(leakedLabel)
    }

    await expect
      .poll(async () => activityRowLabels(page))
      .toEqual(expectedLabels)
    const activityList = page.locator('ol').filter({ hasText: 'Prepared change preview' }).first()
    for (const leakedLabel of leakedRawLabels) {
      await expect(activityList.getByText(leakedLabel, { exact: true })).toHaveCount(0)
    }
  })

  test('active activity rows keep graph order when backend timestamps collide', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, activitySharedTimestampOrderPrompt)

    await expect(page.getByText('Session activity')).toBeVisible()
    const activityList = page.locator('ol').filter({ hasText: 'Checking tool evidence' }).first()
    await expect(activityList.getByText('Structuring request', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Choosing next action', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Structuring the request', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Choosing the next backend action', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Checking relevant records', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Checking tool evidence', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Preparing next action', { exact: true })).toHaveCount(0)

    const activityText = await activityList.innerText()
    expect(activityText.indexOf('Structuring the request')).toBeLessThan(
      activityText.indexOf('Choosing the next backend action'),
    )
    expect(activityText.indexOf('Choosing the next backend action')).toBeLessThan(
      activityText.indexOf('Checking relevant records'),
    )
    expect(activityText.indexOf('Checking relevant records')).toBeLessThan(
      activityText.indexOf('Checking tool evidence'),
    )
    await expect(page.getByText(/Factory Agent chat could not start/i)).toHaveCount(0)
    await expect(page.getByRole('button', { name: /Try starting chat again/i })).toHaveCount(0)
  })

  test('active retry story keeps graph prelude and appends attempts below the failed check', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, activityActiveRetryStoryPrompt)

    await expect(page.getByText('Session activity')).toBeVisible()
    const activityList = page.locator('ol').filter({ hasText: 'Attempt 3 of 6' }).first()
    await expect(activityList.getByText('Structuring request', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Choosing next action', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Finding information path', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Selecting safe action', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Attempt 1 of 6 - Running the selected read', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Attempt 1 of 6 - Previous read timed out', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Attempt 2 of 6 - Running the next selected read', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Attempt 3 of 6 - Running the next selected read', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Replanning after timeout', { exact: true })).toHaveCount(2)

    const initialText = await activityList.innerText()
    expect(initialText.indexOf('Structuring request')).toBeLessThan(
      initialText.indexOf('Choosing next action'),
    )
    expect(initialText.indexOf('Choosing next action')).toBeLessThan(
      initialText.indexOf('Finding information path'),
    )
    expect(initialText.indexOf('Finding information path')).toBeLessThan(
      initialText.indexOf('Selecting safe action'),
    )
    expect(initialText.indexOf('Selecting safe action')).toBeLessThan(
      initialText.indexOf('Attempt 1 of 6 - Running the selected read'),
    )
    expect(initialText.indexOf('Attempt 1 of 6 - Running the selected read')).toBeLessThan(
      initialText.indexOf('Attempt 1 of 6 - Previous read timed out'),
    )
    expect(initialText.indexOf('Attempt 1 of 6 - Previous read timed out')).toBeLessThan(
      initialText.indexOf('Attempt 2 of 6 - Running the next selected read'),
    )
    expect(initialText.indexOf('Attempt 2 of 6 - Running the next selected read')).toBeLessThan(
      initialText.indexOf('Attempt 3 of 6 - Running the next selected read'),
    )

    await expect
      .poll(async () => {
        const activityFrames = await activitySnapshotEventsFor('activityActiveRetryStory')
        return latestSnapshotLabels(activityFrames)
      })
      .toEqual(['Selecting safe action', 'Finding information path', 'Choosing next action'])

    await expect(activityList.getByText('Finding information path', { exact: true })).toHaveCount(1)
    await expect(activityList.getByText('Selecting safe action', { exact: true })).toHaveCount(1)
    await expect(activityList.getByText('Choosing next action', { exact: true })).toHaveCount(1)
    const currentCount = await activityList.getByText('Current', { exact: true }).count()
    expect(currentCount).toBe(1)
  })

  test('active retry snapshots keep the full story stable until terminal', async ({ page }) => {
    await openChat(page)
    await sendChatPrompt(page, activityRetryCollapseHandoffPrompt)

    await expect(page.getByText('Session activity')).toBeVisible()
    const activityList = page.locator('ol').filter({ hasText: 'Attempt 1 of 6' }).first()
    await expect(activityList.getByText('Attempt 5 of 6 - Running the next selected read', { exact: true })).toBeVisible()

    await expect(activityList.getByText('Attempt 6 of 6 - Running the next selected read', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Earlier retry attempts', { exact: true })).toHaveCount(0)
    await expect(activityList.getByText('4 earlier attempts collapsed', { exact: true })).toHaveCount(0)
    await expect(activityList.getByText('Attempt 3 of 6 - Running the next selected read', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Attempt 4 of 6 - Running the next selected read', { exact: true })).toBeVisible()
    await expect(activityList.getByText('Attempt 5 of 6 - Running the next selected read', { exact: true })).toBeVisible()
    const progressIcons = await activityList.locator('[data-icon="progress_activity"]').count()
    expect(progressIcons).toBe(1)
  })
})
