import test from 'node:test'
import assert from 'node:assert/strict'

import { castApprovalFieldValue } from './approvalFieldUtils.js'

test('castApprovalFieldValue rejects partial integers', () => {
  assert.equal(Number.isNaN(castApprovalFieldValue('12abc', { type: 'integer' })), true)
  assert.equal(Number.isNaN(castApprovalFieldValue('1.5', { type: 'integer' })), true)
  assert.equal(castApprovalFieldValue('12', { type: 'integer' }), 12)
})

test('castApprovalFieldValue rejects partial numbers and accepts finite numeric strings', () => {
  assert.equal(Number.isNaN(castApprovalFieldValue('3.14kg', { type: 'number' })), true)
  assert.equal(Number.isNaN(castApprovalFieldValue('Infinity', { type: 'number' })), true)
  assert.equal(castApprovalFieldValue('3.14', { type: 'number' }), 3.14)
  assert.equal(castApprovalFieldValue('1e3', { type: 'number' }), 1000)
})
