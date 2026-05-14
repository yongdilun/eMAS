import assert from 'node:assert/strict'
import test from 'node:test'

import {
  compactInterruptApprovalHeadline,
  extractApprovalInterruptBody,
  isInterruptBundleApprovalText,
  presentationFromBundleUi,
  resolveApprovalTablePresentation,
  shortenApprovalRiskSummary,
} from './approvalInterruptDisplay.js'

test('presentationFromBundleUi maps backend bundle_ui to table presentation', () => {
  const pres = presentationFromBundleUi({
    kind: 'job_priority_bundle',
    headline: '1 job will be updated from low to urgent priority.',
    rows: [{ job_id: 'JOB-A', previous_priority: 'low', new_priority: 'urgent' }],
  })
  assert.equal(pres.render_hint, 'table')
  assert.equal(pres.table.columns.length, 3)
  assert.deepEqual(pres.table.rows[0], {
    job_id: 'JOB-A',
    previous_priority: 'low',
    new_priority: 'urgent',
  })
})

test('detects interrupt bundle copy by markers', () => {
  assert.equal(isInterruptBundleApprovalText('Hello'), false)
  assert.equal(isInterruptBundleApprovalText('Jobs affected:\n1. x'), true)
  assert.equal(isInterruptBundleApprovalText('Current vs requested priority:\n- a'), true)
})

test('shortens risk summary to lead-in before job enumeration', () => {
  const risk =
    'Please approve to continue. Jobs affected:\n1. JOB-SEED-002 (priority set to high)\n2. JOB-SEED-004 (priority set to high)'
  assert.equal(shortenApprovalRiskSummary(risk), 'Please approve to continue.')
})

test('extractApprovalInterruptBody strips timeline approval prefix', () => {
  const body = extractApprovalInterruptBody(
    'Waiting for your approval: Jobs affected:\n1. JOB-1 (priority set to high)',
  )
  assert.ok(body.startsWith('Jobs affected'))
})

test('resolveApprovalTablePresentation falls back to parsed risk_summary when bundle_ui absent', () => {
  const risk = `Please approve. Jobs affected:
1. JOB-SEED-002 (priority set to high)
2. JOB-SEED-004 (priority set to high)

Current vs requested priority:
- JOB-SEED-002: priority set to high (from medium)
- JOB-SEED-004: priority set to high (from medium)
`
  const pres = resolveApprovalTablePresentation({
    event_type: 'approval_required',
    content: `Waiting for your approval: ${risk}`,
    details: { args: {} },
  })
  assert.equal(pres?.render_hint, 'table')
  assert.equal(pres?.table?.rows?.length, 2)
})

test('resolveApprovalTablePresentation uses structured bundle_ui when present', () => {
  const pres = resolveApprovalTablePresentation({
    event_type: 'approval_required',
    details: {
      args: {
        bundle_ui: {
          kind: 'job_priority_bundle',
          headline: '2 jobs will be updated from medium to high priority.',
          rows: [
            { job_id: 'JOB-A', previous_priority: 'medium', new_priority: 'high' },
            { job_id: 'JOB-B', previous_priority: 'medium', new_priority: 'high' },
          ],
        },
      },
    },
  })
  assert.equal(pres.table.rows.length, 2)
})

test('compact headline summarizes job count and priority delta (legacy markdown body)', () => {
  const body = `Jobs affected:
1. JOB-SEED-002 (priority set to high)
2. JOB-SEED-004 (priority set to high)

Current vs requested priority:
- JOB-SEED-002: priority set to high (from medium)
- JOB-SEED-004: priority set to high (from medium)
`
  const h = compactInterruptApprovalHeadline(body)
  assert.match(h, /2 jobs/)
  assert.match(h, /will be updated/)
  assert.match(h, /medium/)
  assert.match(h, /high/)
})
