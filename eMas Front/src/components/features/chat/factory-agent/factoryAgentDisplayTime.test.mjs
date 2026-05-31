import assert from 'node:assert/strict'
import test from 'node:test'

import { parseFactoryAgentTime } from './factoryAgentDisplayTime.js'

test('parseFactoryAgentTime treats backend numeric timestamps as seconds', () => {
  assert.equal(parseFactoryAgentTime(1_780_000_000).toISOString(), '2026-05-28T20:26:40.000Z')
  assert.equal(parseFactoryAgentTime('1780000000').toISOString(), '2026-05-28T20:26:40.000Z')
})

test('parseFactoryAgentTime treats timezone-less backend ISO timestamps as UTC', () => {
  assert.equal(parseFactoryAgentTime('2026-06-01T13:21:00').toISOString(), '2026-06-01T13:21:00.000Z')
  assert.equal(parseFactoryAgentTime('2026-06-01T13:21:00Z').toISOString(), '2026-06-01T13:21:00.000Z')
})
