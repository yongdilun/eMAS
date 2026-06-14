import assert from 'node:assert/strict'
import test from 'node:test'

import { createViteSsrServer } from '../test/reactComponentTestUtils.mjs'

let server
let normalizers

test.before(async () => {
  server = await createViteSsrServer()
  normalizers = await server.ssrLoadModule('/src/services/normalizers.js')
})

test.after(async () => {
  await server?.close()
})

test('normalizeBatchAggregateLines returns only material rows', () => {
  const lines = normalizers.normalizeBatchAggregateLines(
    [
      {
        material_id: 'MAT-010',
        material_name: 'M8 Hex Bolt',
        recommended_qty: 25,
        suggested_arrive_at: '2026-06-20T08:00:00.000Z',
      },
    ],
    [
      {
        product_id: 'P-007',
        product_name: 'Seal Kit',
        recommended_qty: 3,
        suggested_arrive_at: '2026-06-21T08:00:00.000Z',
      },
    ],
  )

  assert.equal(lines.length, 1)
  assert.equal(lines[0].kind, 'material')
  assert.equal(lines[0].id, 'MAT-010')
  assert.equal(lines[0].label, 'M8 Hex Bolt')
  assert.equal(lines[0].selected, true)
})

test('buildAggregateApplySuggestions emits only material arrivals', () => {
  const lines = normalizers.normalizeBatchAggregateLines(
    [
      {
        material_id: 'MAT-010',
        recommended_qty: 25,
        suggested_arrive_at: '2026-06-20T08:00:00.000Z',
      },
    ],
    [
      {
        product_id: 'P-007',
        recommended_qty: 3,
        suggested_arrive_at: '2026-06-21T08:00:00.000Z',
      },
    ],
  )

  const payload = normalizers.buildAggregateApplySuggestions(lines)

  assert.deepEqual(payload, [
    {
      material_id: 'MAT-010',
      quantity: 25,
      arrive_at: '2026-06-20T08:00:00.000Z',
    },
  ])
})

test('aggregateMaterialShortageRowsFromProposals dedupes proposal alternatives', () => {
  const rows = normalizers.aggregateMaterialShortageRowsFromProposals([
    {
      proposal_id: 'AIPROP-1',
      job_id: 'JOB-SEED-022',
      feasible: false,
      shortage_resolutions: [
        {
          material_id: 'MAT-010',
          option_type: 'replenish',
          replenishment: {
            material_id: 'MAT-010',
            material_name: 'M8 Hex Bolt',
            suggested_qty: 154600,
            suggested_arrive_at: '2026-07-08T03:00:00.000Z',
          },
          affected_job_ids: ['JOB-SEED-022'],
        },
        {
          material_id: 'MAT-010',
          option_type: 'replenish',
          dependency_product_id: 'P-007',
          replenishment: {
            material_id: 'MAT-010',
            material_name: 'M8 Hex Bolt',
            suggested_qty: 154600,
            suggested_arrive_at: '2026-07-13T05:30:00.000Z',
          },
          affected_job_ids: ['JOB-SEED-022'],
        },
        {
          product_id: 'P-007',
          option_type: 'schedule_production',
          replenishment: {
            suggested_qty: 1,
            suggested_arrive_at: '2026-06-20T08:00:00.000Z',
          },
        },
      ],
    },
  ])

  assert.equal(rows.length, 1)
  assert.equal(rows[0].material_id, 'MAT-010')
  assert.equal(rows[0].recommended_qty, 154600)
  assert.equal(rows[0].suggested_arrive_at, '2026-07-08T03:00:00.000Z')
  assert.deepEqual(rows[0].affected_job_ids, ['JOB-SEED-022'])
})
