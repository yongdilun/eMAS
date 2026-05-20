import { expect, test } from '../support/seededArtifacts.js'
import {
  factoryAgentJson,
  openChat,
  pendingApprovalsForPage,
  sendPrompt,
  snapshotForPage,
} from '../support/fullStackScenarios.js'
import { hardQueryScenarios } from '../support/hardQueryScenarios.js'
import { expectHardQueryScenario } from '../support/hardQueryOracle.js'

async function resetToolFaults() {
  await factoryAgentJson('/_playwright/tool-faults', { method: 'DELETE' })
}

async function applyScenarioSetup(page, scenario) {
  if (scenario.toolFaults) {
    await factoryAgentJson('/_playwright/tool-faults', {
      method: 'POST',
      body: scenario.toolFaults,
    })
  }
  if (!scenario.setup?.prompt) return
  await sendPrompt(page, scenario.setup.prompt)
  const waitFor = scenario.setup.waitFor || {}
  if (waitFor.sessionStatus) {
    await expect
      .poll(async () => (await snapshotForPage(page))?.session?.status, { timeout: 30_000 })
      .toBe(waitFor.sessionStatus)
  }
  if (Object.hasOwn(waitFor, 'approvalCount')) {
    await expect
      .poll(async () => (await pendingApprovalsForPage(page)).length, { timeout: 30_000 })
      .toBe(waitFor.approvalCount)
  }
}

test.describe('Hard query oracle harness @prompt-regression @hard-query', () => {
  for (const scenario of hardQueryScenarios) {
    test(`${scenario.id} hard query proves typed oracle contract`, async ({ page }, testInfo) => {
      await resetToolFaults()
      try {
        await openChat(page)
        await applyScenarioSetup(page, scenario)
        await sendPrompt(page, scenario.prompt)
        await expectHardQueryScenario(page, scenario, {
          snapshotForPage,
          pendingApprovalsForPage,
          testInfo,
        })
      } finally {
        await resetToolFaults()
      }
    })
  }
})
