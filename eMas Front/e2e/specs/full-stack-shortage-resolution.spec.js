import { seededRuntimeEnv } from '../support/fullStackEnv.js'
import { expect, test } from '../support/seededArtifacts.js'

const seededEnv = seededRuntimeEnv()
const TARGET_SHORTAGE_JOB_IDS = new Set(['JOB-SEED-019', 'JOB-SEED-021', 'JOB-SEED-026'])
const DIRECT_MATERIAL_FIXTURE = {
  productId: 'P-E2E-MAT',
  processId: 'PRC-E2E-MAT',
  stepId: 'STEP-E2E-MAT',
  machineId: 'M-E2E-MAT',
  materialId: 'MAT-E2E-LIMIT',
}
const CHILD_MATERIAL_FIXTURE = {
  parentProductId: 'P-E2E-PARENT-CHILD',
  childProductId: 'P-E2E-CHILD-RAW',
  parentProcessId: 'PRC-E2E-PARENT-CHILD',
  childProcessId: 'PRC-E2E-CHILD-RAW',
  parentStepId: 'STEP-E2E-PARENT-USES-CHILD',
  childStepId: 'STEP-E2E-CHILD-USES-RAW',
  parentMachineId: 'M-E2E-PARENT-CHILD',
  childMachineId: 'M-E2E-CHILD-RAW',
  materialId: 'MAT-E2E-CHILD-RAW',
}

test.setTimeout(360_000)

async function goApiJson(path, options = {}) {
  const response = await fetch(`${seededEnv.goApiBaseUrl}${path}`, {
    method: options.method || 'GET',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': 'shortage-resolution-e2e',
      'X-User-Role': 'planner',
      ...(options.headers || {}),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  const text = await response.text()
  let body = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      throw new Error(`Go API ${options.method || 'GET'} ${path} returned non-JSON: ${response.status} ${text.slice(0, 300)}`)
    }
  }
  if (!response.ok) {
    throw new Error(`Go API ${options.method || 'GET'} ${path} failed: ${response.status} ${text}`)
  }
  return body
}

async function resetSeededGoApi() {
  await goApiJson('/__e2e/reset', { method: 'POST' })
}

async function keepOnlyTargetShortageJobsActive() {
  const response = await goApiJson('/jobs?fields=job_id,status&limit=200')
  const jobs = Array.isArray(response?.data) ? response.data : []
  const updates = jobs
    .filter((job) => job?.job_id && !TARGET_SHORTAGE_JOB_IDS.has(job.job_id))
    .filter((job) => ['planned', 'scheduled', 'blocked', 'paused', 'running'].includes(job.status))
  for (const job of updates) {
    await goApiJson(`/jobs/${encodeURIComponent(job.job_id)}`, {
      method: 'PUT',
      body: { status: 'completed' },
    })
  }
}

async function createDirectMaterialShortageFixture() {
  await goApiJson('/products', {
    method: 'POST',
    body: {
      product_id: DIRECT_MATERIAL_FIXTURE.productId,
      product_name: 'E2E Material Shortage Product',
    },
  })
  await goApiJson('/processes', {
    method: 'POST',
    body: {
      process_id: DIRECT_MATERIAL_FIXTURE.processId,
      product_id: DIRECT_MATERIAL_FIXTURE.productId,
      process_name: 'E2E Material Shortage Process',
    },
  })
  await goApiJson(`/processes/${DIRECT_MATERIAL_FIXTURE.processId}/steps`, {
    method: 'POST',
    body: {
      step_id: DIRECT_MATERIAL_FIXTURE.stepId,
      step_sequence: 1,
      step_name: 'E2E material constrained step',
      machine_type_required: 'E2EMAT',
      default_processing_time: 30,
    },
  })
  await goApiJson('/machines', {
    method: 'POST',
    body: {
      machine_id: DIRECT_MATERIAL_FIXTURE.machineId,
      machine_name: 'E2E Material Machine',
      machine_type: 'E2EMAT',
      capacity_per_hour: 60,
    },
  })
  await goApiJson('/inventory/materials', {
    method: 'POST',
    body: {
      material_id: DIRECT_MATERIAL_FIXTURE.materialId,
      material_name: 'E2E Limited Material',
      current_stock: 0,
      unit: 'kg',
    },
  })
  await goApiJson(`/process-steps/${DIRECT_MATERIAL_FIXTURE.stepId}/materials`, {
    method: 'POST',
    body: {
      material_id: DIRECT_MATERIAL_FIXTURE.materialId,
      role: 'input',
      quantity_per_unit: 5,
      unit: 'kg',
    },
  })
  await goApiJson('/jobs', {
    method: 'POST',
    body: {
      product_id: DIRECT_MATERIAL_FIXTURE.productId,
      quantity_total: 3,
      deadline: new Date(Date.now() + 72 * 60 * 60 * 1000).toISOString(),
      priority: 'high',
      allow_auto_plan: true,
    },
  })
}

async function createSubproductRawMaterialShortageFixture() {
  await goApiJson('/products', {
    method: 'POST',
    body: {
      product_id: CHILD_MATERIAL_FIXTURE.childProductId,
      product_name: 'E2E Child Raw Material Product',
    },
  })
  await goApiJson('/products', {
    method: 'POST',
    body: {
      product_id: CHILD_MATERIAL_FIXTURE.parentProductId,
      product_name: 'E2E Parent Needs Child Product',
    },
  })
  await goApiJson('/processes', {
    method: 'POST',
    body: {
      process_id: CHILD_MATERIAL_FIXTURE.childProcessId,
      product_id: CHILD_MATERIAL_FIXTURE.childProductId,
      process_name: 'E2E Child Raw Process',
    },
  })
  await goApiJson(`/processes/${CHILD_MATERIAL_FIXTURE.childProcessId}/steps`, {
    method: 'POST',
    body: {
      step_id: CHILD_MATERIAL_FIXTURE.childStepId,
      step_sequence: 1,
      step_name: 'E2E child raw constrained step',
      machine_type_required: 'E2ECHILDRAW',
      default_processing_time: 30,
    },
  })
  await goApiJson('/processes', {
    method: 'POST',
    body: {
      process_id: CHILD_MATERIAL_FIXTURE.parentProcessId,
      product_id: CHILD_MATERIAL_FIXTURE.parentProductId,
      process_name: 'E2E Parent Child Process',
    },
  })
  await goApiJson(`/processes/${CHILD_MATERIAL_FIXTURE.parentProcessId}/steps`, {
    method: 'POST',
    body: {
      step_id: CHILD_MATERIAL_FIXTURE.parentStepId,
      step_sequence: 1,
      step_name: 'E2E parent consumes child step',
      machine_type_required: 'E2EPARENTCHILD',
      default_processing_time: 30,
    },
  })
  await goApiJson('/machines', {
    method: 'POST',
    body: {
      machine_id: CHILD_MATERIAL_FIXTURE.childMachineId,
      machine_name: 'E2E Child Raw Machine',
      machine_type: 'E2ECHILDRAW',
      capacity_per_hour: 60,
    },
  })
  await goApiJson('/machines', {
    method: 'POST',
    body: {
      machine_id: CHILD_MATERIAL_FIXTURE.parentMachineId,
      machine_name: 'E2E Parent Child Machine',
      machine_type: 'E2EPARENTCHILD',
      capacity_per_hour: 60,
    },
  })
  await goApiJson('/inventory/materials', {
    method: 'POST',
    body: {
      material_id: CHILD_MATERIAL_FIXTURE.materialId,
      material_name: 'E2E Child Raw Material',
      current_stock: 0,
      unit: 'kg',
    },
  })
  await goApiJson(`/process-steps/${CHILD_MATERIAL_FIXTURE.childStepId}/materials`, {
    method: 'POST',
    body: {
      material_id: CHILD_MATERIAL_FIXTURE.materialId,
      role: 'input',
      quantity_per_unit: 2,
      unit: 'kg',
    },
  })
  await goApiJson(`/process-steps/${CHILD_MATERIAL_FIXTURE.parentStepId}/materials`, {
    method: 'POST',
    body: {
      product_id: CHILD_MATERIAL_FIXTURE.childProductId,
      role: 'input',
      quantity_per_unit: 1,
      unit: 'pcs',
    },
  })
  await goApiJson(`/products/${CHILD_MATERIAL_FIXTURE.childProductId}/bom`, {
    method: 'PUT',
    body: {
      process_id: CHILD_MATERIAL_FIXTURE.childProcessId,
      bom_items: [
        {
          material_id: CHILD_MATERIAL_FIXTURE.materialId,
          quantity_per_unit: 2,
          unit: 'kg',
        },
      ],
    },
  })
  await goApiJson(`/products/${CHILD_MATERIAL_FIXTURE.parentProductId}/bom`, {
    method: 'PUT',
    body: {
      process_id: CHILD_MATERIAL_FIXTURE.parentProcessId,
      bom_items: [
        {
          product_id: CHILD_MATERIAL_FIXTURE.childProductId,
          quantity_per_unit: 1,
          unit: 'pcs',
        },
      ],
    },
  })
  await goApiJson('/jobs', {
    method: 'POST',
    body: {
      product_id: CHILD_MATERIAL_FIXTURE.parentProductId,
      quantity_total: 4,
      deadline: new Date(Date.now() + 72 * 60 * 60 * 1000).toISOString(),
      priority: 'urgent',
    },
  })
}

async function openShortageResolution(page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('theme', JSON.stringify('dark'))
  })
  const batchResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      response.url().includes('/ai/scheduling/batch-proposals'),
    { timeout: 120_000 },
  )
  await page.goto('/scheduling/shortage-resolution')
  const batchResponse = await batchResponsePromise
  expect(batchResponse.ok()).toBe(true)
  const batchBody = await batchResponse.json()

  await expect(page.locator('html')).toHaveClass(/dark/)
  await expect(page.getByRole('heading', { name: 'Shortage Resolution Center' })).toBeVisible()
  await expect(page.getByText('Unified Material Shortage Resolution')).toBeVisible({ timeout: 90_000 })
  await expect(page.locator('[data-shortage-line-kind="material"]').first()).toBeVisible()
  await expect(page.locator('[data-shortage-line-kind="schedule_production"]')).toHaveCount(0)

  return batchBody?.data || batchBody
}

async function openSchedulingPreview(page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('theme', JSON.stringify('dark'))
  })
  await page.goto('/scheduling')
  await expect(page.locator('html')).toHaveClass(/dark/)
  await expect(page.getByRole('button', { name: 'Reschedule All' }).first()).toBeVisible({ timeout: 60_000 })
  await page.getByRole('button', { name: 'Reschedule All' }).first().click()

  const rescheduleResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      response.url().includes('/ai/scheduling/reschedule-all'),
    { timeout: 240_000 },
  )
  await page.getByRole('button', { name: 'Continue' }).click()
  const response = await rescheduleResponsePromise
  expect(response.ok()).toBe(true)
  const body = await response.json()
  await expect(page.getByRole('heading', { name: 'Schedule Preview' })).toBeVisible({ timeout: 60_000 })
  return body?.data || body
}

async function applyAndCapture(page) {
  const rescheduleBodies = []
  const captureResponse = async (response) => {
    if (
      response.request().method() === 'POST' &&
      response.url().includes('/ai/scheduling/reschedule-all')
    ) {
      try {
        const body = await response.json()
        rescheduleBodies.push(body?.data || body)
      } catch {
        // The explicit response assertions below will surface bad JSON/status.
      }
    }
  }
  page.on('response', captureResponse)
  const applyRequestPromise = page.waitForRequest(
    (request) =>
      request.method() === 'POST' &&
      request.url().includes('/ai/scheduling/apply-replenishment-batch'),
    { timeout: 30_000 },
  )
  const applyResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      response.url().includes('/ai/scheduling/apply-replenishment-batch'),
    { timeout: 60_000 },
  )
  const rescheduleResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      response.url().includes('/ai/scheduling/reschedule-all'),
    { timeout: 240_000 },
  )

  await page.getByRole('button', { name: 'Apply and Replan' }).click()
  const applyRequest = await applyRequestPromise
  const payload = applyRequest.postDataJSON()
  const applyResponse = await applyResponsePromise
  expect(applyResponse.ok()).toBe(true)
  const rescheduleResponse = await rescheduleResponsePromise
  expect(rescheduleResponse.ok()).toBe(true)
  await expect(page.getByText('Running')).toHaveCount(0, { timeout: 240_000 })
  await expect.poll(() => rescheduleBodies.length, { timeout: 10_000 }).toBeGreaterThan(0)
  page.off('response', captureResponse)
  return { payload, rescheduleData: rescheduleBodies.at(-1) }
}

async function applyAndCaptureFromEmbeddedResolution(page) {
  const applyPayloads = []
  const rescheduleBodies = []
  const captureResponse = async (response) => {
    if (
      response.request().method() === 'POST' &&
      response.url().includes('/ai/scheduling/reschedule-all')
    ) {
      try {
        const body = await response.json()
        rescheduleBodies.push(body?.data || body)
      } catch {
        // The explicit response assertions below will surface bad JSON/status.
      }
    }
  }
  page.on('response', captureResponse)

  const captureRequest = (request) => {
    if (
      request.method() === 'POST' &&
      request.url().includes('/ai/scheduling/apply-replenishment-batch')
    ) {
      applyPayloads.push(request.postDataJSON())
    }
  }
  page.on('request', captureRequest)

  const applyResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      response.url().includes('/ai/scheduling/apply-replenishment-batch'),
    { timeout: 60_000 },
  )
  const rescheduleResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      response.url().includes('/ai/scheduling/reschedule-all'),
    { timeout: 240_000 },
  )

  await page.getByRole('button', { name: 'Apply and Replan' }).click()
  const applyResponse = await applyResponsePromise
  expect(applyResponse.ok()).toBe(true)
  const firstReschedule = await rescheduleResponsePromise
  expect(firstReschedule.ok()).toBe(true)
  await expect(page.getByRole('heading', { name: 'Schedule Preview' })).toBeVisible({ timeout: 240_000 })
  await expect(page.getByRole('heading', { name: 'Shortage Resolution Center' })).toHaveCount(0)
  await expect.poll(() => rescheduleBodies.length, { timeout: 10_000 }).toBeGreaterThan(0)
  page.off('response', captureResponse)
  page.off('request', captureRequest)

  return { applyPayloads, rescheduleData: rescheduleBodies.at(-1) }
}

function buildShortageDiagnostics(batchPayload) {
  const summary = batchPayload?.summary || {}
  const proposals = Array.isArray(batchPayload?.proposals) ? batchPayload.proposals : []
  const aggregateRows = (summary.material_replenishment_aggregate || []).map((row) => ({ ...row, kind: 'material' }))
  const aggregateByJob = new Map()
  for (const row of aggregateRows) {
    for (const jobId of row.affected_job_ids || []) {
      const rows = aggregateByJob.get(jobId) || []
      rows.push({
        kind: row.kind,
        id: row.material_id || row.product_id,
        qty: row.recommended_qty,
      })
      aggregateByJob.set(jobId, rows)
    }
  }
  const rows = proposals.map((proposal) => {
    const directShortage =
      (proposal.material_shortages || []).length > 0 ||
      (proposal.shortage_resolutions || []).length > 0
    const aggregateCauses = aggregateByJob.get(proposal.job_id) || []
    return {
      job_id: proposal.job_id,
      feasible: proposal.feasible !== false,
      blocked_reasons: proposal.blocked_reasons || [],
      direct_shortage: directShortage,
      aggregate_causes: aggregateCauses,
    }
  })
  return {
    summary: {
      generated: summary.generated,
      blocked: summary.blocked,
      material_rows: summary.material_replenishment_aggregate?.length || 0,
      planned_product_rows: summary.schedule_production_aggregate?.length || 0,
    },
    rows,
    black_box_infeasible: rows.filter((row) => !row.feasible && !row.direct_shortage && row.aggregate_causes.length === 0),
    aggregate_only_infeasible: rows.filter((row) => !row.feasible && !row.direct_shortage && row.aggregate_causes.length > 0),
  }
}

function materialShortageInfeasible(proposals) {
  return (Array.isArray(proposals) ? proposals : []).filter((proposal) => {
    if (proposal?.feasible !== false) return false
    const reasons = [
      ...(Array.isArray(proposal.blocked_reasons) ? proposal.blocked_reasons : []),
      proposal.blocked_reason,
      proposal.reason,
    ]
      .filter(Boolean)
      .join(' ')
    return /material[_\s-]*shortage/i.test(reasons) ||
      (Array.isArray(proposal.material_shortages) && proposal.material_shortages.length > 0) ||
      (Array.isArray(proposal.shortage_resolutions) && proposal.shortage_resolutions.length > 0)
  })
}

test.describe('canonical seeded shortage resolution @shortage-resolution-direct @canonical-seed', () => {
  test.beforeEach(async () => {
    await resetSeededGoApi()
  })

  test('one Apply and Replan clears canonical seed material shortages without Factory Agent', async ({ page }, testInfo) => {
    const initialPayload = await openShortageResolution(page)
    const initialSummary = initialPayload?.summary || {}
    const initialRows = initialSummary.material_replenishment_aggregate || []
    const initialMaterialIds = initialRows.map((row) => row.material_id)

    await testInfo.attach('canonical-initial-shortage-summary.json', {
      body: JSON.stringify(initialSummary, null, 2),
      contentType: 'application/json',
    })

    expect(initialRows.length).toBeGreaterThan(0)
    expect(initialMaterialIds).toContain('MAT-010')
    expect(initialSummary.schedule_production_aggregate || []).toEqual([])
    await expect(page.locator('[data-shortage-line-kind="schedule_production"]')).toHaveCount(0)
    await expect(page.getByText(/^Proposals \(/)).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('canonical-shortage-resolution-dark.png'), fullPage: true })

    const { payload, rescheduleData } = await applyAndCapture(page)
    const submittedRows = payload?.suggestions || []
    const finalSummary = rescheduleData?.summary || {}
    const finalProposals = Array.isArray(rescheduleData?.proposals) ? rescheduleData.proposals : []

    await testInfo.attach('canonical-one-shot-apply-and-replan.json', {
      body: JSON.stringify({ submittedRows, finalSummary }, null, 2),
      contentType: 'application/json',
    })

    expect(submittedRows.length).toBeGreaterThan(0)
    expect(submittedRows.every((row) => String(row.material_id || '').startsWith('MAT-'))).toBe(true)
    expect(submittedRows.some((row) => row.option_type === 'schedule_production')).toBe(false)
    expect(finalProposals.length).toBeGreaterThan(0)
    expect(materialShortageInfeasible(finalProposals)).toEqual([])
    expect(finalProposals.filter((proposal) => proposal.feasible === false)).toEqual([])
    expect(finalProposals.every((proposal) => Array.isArray(proposal.proposed_slots) && proposal.proposed_slots.length > 0)).toBe(true)
    expect(finalSummary.blocked || 0).toBe(0)
    expect(finalSummary.material_replenishment_aggregate || []).toEqual([])
    expect(finalSummary.schedule_production_aggregate || []).toEqual([])
  })

  test('modal first aggregate includes deep child material and clears in one Apply/Replan', async ({ page }, testInfo) => {
    const initialPayload = await openSchedulingPreview(page)
    const initialSummary = initialPayload?.summary || {}
    const initialRows = initialSummary.material_replenishment_aggregate || []
    const initialMaterialIds = initialRows.map((row) => row.material_id)

    await testInfo.attach('canonical-modal-initial-reschedule-summary.json', {
      body: JSON.stringify(initialSummary, null, 2),
      contentType: 'application/json',
    })

    expect(initialRows.length).toBeGreaterThan(0)
    expect(initialMaterialIds).toContain('MAT-010')
    expect(initialSummary.schedule_production_aggregate || []).toEqual([])

    await page.getByRole('button', { name: 'Resolve in Resolution Center' }).click()
    await expect(page.getByRole('heading', { name: 'Shortage Resolution Center' }).first()).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('Unified Material Shortage Resolution')).toBeVisible()
    await expect(page.locator('[data-shortage-line-kind="material"]').filter({ hasText: 'MAT-010' })).toBeVisible()
    await expect(page.locator('[data-shortage-line-kind="schedule_production"]')).toHaveCount(0)
    await expect(page.getByText(/^Proposals \(/)).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('canonical-modal-shortage-resolution-dark.png'), fullPage: true })

    const { applyPayloads, rescheduleData } = await applyAndCaptureFromEmbeddedResolution(page)
    const submittedRows = applyPayloads.flatMap((payload) => payload?.suggestions || [])
    const finalSummary = rescheduleData?.summary || {}
    const finalProposals = Array.isArray(rescheduleData?.proposals) ? rescheduleData.proposals : []

    await testInfo.attach('canonical-modal-one-shot-apply-and-replan.json', {
      body: JSON.stringify({ submittedRows, finalSummary }, null, 2),
      contentType: 'application/json',
    })

    expect(submittedRows.length).toBeGreaterThan(0)
    expect(submittedRows.some((row) => row.material_id === 'MAT-010')).toBe(true)
    expect(submittedRows.every((row) => String(row.material_id || '').startsWith('MAT-'))).toBe(true)
    expect(submittedRows.some((row) => row.option_type === 'schedule_production')).toBe(false)
    expect(finalProposals.length).toBeGreaterThan(0)
    expect(materialShortageInfeasible(finalProposals)).toEqual([])
    expect(finalProposals.filter((proposal) => proposal.feasible === false)).toEqual([])
    expect(finalProposals.every((proposal) => Array.isArray(proposal.proposed_slots) && proposal.proposed_slots.length > 0)).toBe(true)
    expect(finalSummary.blocked || 0).toBe(0)
    expect(finalSummary.material_replenishment_aggregate || []).toEqual([])
    expect(finalSummary.schedule_production_aggregate || []).toEqual([])
  })
})

test.describe('direct seeded shortage resolution @shortage-resolution-direct', () => {
  test.beforeEach(async () => {
    await resetSeededGoApi()
    await keepOnlyTargetShortageJobsActive()
    await createDirectMaterialShortageFixture()
  })

  test('captures shortage root causes without aggregate-only infeasible noise', async ({ page }, testInfo) => {
    const batchPayload = await openShortageResolution(page)
    const diagnostics = buildShortageDiagnostics(batchPayload)
    await testInfo.attach('shortage-root-cause-diagnostics.json', {
      body: JSON.stringify(diagnostics, null, 2),
      contentType: 'application/json',
    })

    expect(diagnostics.summary.material_rows).toBeGreaterThan(0)
    expect(diagnostics.summary.planned_product_rows).toBe(0)
    expect(diagnostics.black_box_infeasible).toEqual([])
    expect(diagnostics.aggregate_only_infeasible).toEqual([])
  })

  test('applies recommended material rows and reschedules all shortage jobs as feasible', async ({ page }, testInfo) => {
    await openShortageResolution(page)

    const materialRow = page.locator('[data-shortage-line-kind="material"]').first()

    await expect(materialRow.getByRole('checkbox', { name: /Include / })).toBeChecked()
    await expect(page.locator('[data-shortage-line-kind="schedule_production"]')).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('shortage-resolution-dark-material-only.png'), fullPage: true })

    const { payload, rescheduleData } = await applyAndCapture(page)
    const suggestions = payload?.suggestions || []
    expect(suggestions.length).toBeGreaterThan(0)
    expect(suggestions.every((row) => String(row.material_id || '').startsWith('MAT-'))).toBe(true)
    expect(suggestions.some((row) => row.option_type === 'schedule_production')).toBe(false)

    await testInfo.attach('material-apply-reschedule.json', {
      body: JSON.stringify({ payload, rescheduleSummary: rescheduleData?.summary }, null, 2),
      contentType: 'application/json',
    })

    const proposals = Array.isArray(rescheduleData?.proposals) ? rescheduleData.proposals : []
    expect(proposals.length).toBeGreaterThan(0)
    expect(proposals.filter((proposal) => proposal.feasible === false)).toEqual([])
    expect(proposals.every((proposal) => Array.isArray(proposal.proposed_slots) && proposal.proposed_slots.length > 0)).toBe(true)
    expect(rescheduleData?.summary?.blocked || 0).toBe(0)
    expect(rescheduleData?.summary?.schedule_production_aggregate || []).toEqual([])
  })

  test('applying child-product raw material recommendations does not repeat the same shortage rows', async ({ page }, testInfo) => {
    await createSubproductRawMaterialShortageFixture()
    await openShortageResolution(page)

    const childMaterialRow = page
      .locator('[data-shortage-line-kind="material"]')
      .filter({ hasText: CHILD_MATERIAL_FIXTURE.materialId })
    await expect(childMaterialRow).toBeVisible({ timeout: 90_000 })
    await expect(childMaterialRow.getByRole('checkbox', { name: /Include / })).toBeChecked()
    await expect(page.locator('[data-shortage-line-kind="schedule_production"]')).toHaveCount(0)

    const { payload, rescheduleData } = await applyAndCapture(page)
    const submittedRows = payload?.suggestions || []
    expect(submittedRows.some((row) => row.material_id === CHILD_MATERIAL_FIXTURE.materialId)).toBe(true)
    expect(submittedRows.some((row) => row.option_type === 'schedule_production')).toBe(false)

    const finalMaterialRows = rescheduleData?.summary?.material_replenishment_aggregate || []
    await testInfo.attach('child-raw-material-apply-final.json', {
      body: JSON.stringify({ submittedRows, finalSummary: rescheduleData?.summary }, null, 2),
      contentType: 'application/json',
    })

    expect(finalMaterialRows.map((row) => row.material_id)).not.toContain(CHILD_MATERIAL_FIXTURE.materialId)
    expect(rescheduleData?.summary?.schedule_production_aggregate || []).toEqual([])
    expect(materialShortageInfeasible(rescheduleData?.proposals)).toEqual([])
    expect((rescheduleData?.proposals || []).filter((proposal) => proposal.feasible === false)).toEqual([])
    expect(rescheduleData?.summary?.blocked || 0).toBe(0)
  })

  test('modal Apply and Replan clears material-shortage infeasible jobs in the schedule preview', async ({ page }, testInfo) => {
    const initialPayload = await openSchedulingPreview(page)
    const initialDiagnostics = buildShortageDiagnostics(initialPayload)
    await testInfo.attach('modal-initial-shortage-diagnostics.json', {
      body: JSON.stringify(initialDiagnostics, null, 2),
      contentType: 'application/json',
    })
    expect(initialDiagnostics.summary.material_rows).toBeGreaterThan(0)
    expect(materialShortageInfeasible(initialPayload.proposals).length).toBeGreaterThan(0)

    await page.getByRole('button', { name: 'Resolve in Resolution Center' }).click()
    await expect(page.getByRole('heading', { name: 'Shortage Resolution Center' }).first()).toBeVisible({ timeout: 60_000 })
    await expect(page.locator('[data-shortage-line-kind="material"]').first()).toBeVisible()
    await expect(page.locator('[data-shortage-line-kind="schedule_production"]')).toHaveCount(0)

    const { applyPayloads, rescheduleData } = await applyAndCaptureFromEmbeddedResolution(page)
    const submittedRows = applyPayloads.flatMap((payload) => payload?.suggestions || [])
    expect(submittedRows.length).toBeGreaterThan(0)
    expect(submittedRows.every((row) => String(row.material_id || '').startsWith('MAT-'))).toBe(true)
    expect(submittedRows.some((row) => row.option_type === 'schedule_production')).toBe(false)

    await testInfo.attach('modal-apply-final-reschedule.json', {
      body: JSON.stringify({ applyPayloads, finalSummary: rescheduleData?.summary }, null, 2),
      contentType: 'application/json',
    })

    const finalProposals = Array.isArray(rescheduleData?.proposals) ? rescheduleData.proposals : []
    expect(finalProposals.length).toBeGreaterThan(0)
    expect(materialShortageInfeasible(finalProposals)).toEqual([])
    expect(finalProposals.filter((proposal) => proposal.feasible === false)).toEqual([])
    expect(finalProposals.every((proposal) => Array.isArray(proposal.proposed_slots) && proposal.proposed_slots.length > 0)).toBe(true)
    expect(rescheduleData?.summary?.blocked || 0).toBe(0)
    expect(rescheduleData?.summary?.material_replenishment_aggregate || []).toEqual([])
    expect(rescheduleData?.summary?.schedule_production_aggregate || []).toEqual([])
  })
})
