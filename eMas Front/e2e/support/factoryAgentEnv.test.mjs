import assert from 'node:assert/strict'
import test from 'node:test'

import { blankOpenAICompatibleEnv, OPENAI_COMPATIBLE_ENV_KEYS } from './factoryAgentEnv.js'

test('blankOpenAICompatibleEnv clears every LLM role URL used by seeded deterministic stacks', () => {
  const env = blankOpenAICompatibleEnv()
  const requiredKeys = [
    'PLANNER_OPENAI_BASE_URL',
    'SEMANTIC_INTAKE_OPENAI_BASE_URL',
    'SUMMARY_OPENAI_BASE_URL',
    'TOOL_RESULT_SUMMARY_OPENAI_BASE_URL',
    'TOOL_SELECTOR_OPENAI_BASE_URL',
    'RAG_RERANKER_OPENAI_BASE_URL',
    'RAG_ANSWER_OPENAI_BASE_URL',
    'OPENAI_BASE_URL',
    'LLM_BASE_URL',
    'OPENAI_API_BASE',
    'OPENAI_API_KEY',
    'DEVELOPMENT_SEMANTIC_INTAKE_OPENAI_BASE_URL',
    'PRODUCTION_SEMANTIC_INTAKE_OPENAI_BASE_URL',
  ]

  for (const key of requiredKeys) {
    assert.equal(env[key], '', `${key} must be blanked so factory-agent/.env cannot leak into seeded runs`)
  }
  assert.equal(Object.keys(env).length, OPENAI_COMPATIBLE_ENV_KEYS.length)
})
