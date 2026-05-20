const SECRET_PATTERNS = [
  {
    name: 'authorization bearer',
    pattern: /(authorization["']?\s*[:=]\s*["']?\s*bearer\s+)[^"',\s\\]+/gi,
  },
  {
    name: 'bearer token',
    pattern: /\b(bearer\s+)[a-z0-9._~+/=-]{12,}/gi,
  },
  {
    name: 'query secret',
    pattern: /((?:api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|password)=)[^&\s"']+/gi,
  },
  {
    name: 'json secret',
    pattern: /((?:api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|password)["']?\s*:\s*["'])[^"']+/gi,
  },
  {
    name: 'openai key',
    pattern: /\bsk-[a-z0-9_-]{12,}/gi,
  },
  {
    name: 'session path id',
    pattern: /(\/sessions\/)[^/?#\s"']+/gi,
  },
  {
    name: 'operational json id',
    pattern: /((?:session_id|operation_id|approval_id|trace_id)["']?\s*:\s*["'])[^"']+/gi,
  },
]

export const sensitiveArtifactSamples = {
  bearer: 'Bearer phase16-visible-token-abcdef123456',
  queryToken: 'phase16-query-token-abcdef123456',
  apiKey: 'sk-phase16unsafeartifact123456',
  sessionId: 'phase16-session-secret-abcdef',
  operationId: 'phase16-operation-secret-abcdef',
}

export function redactSensitiveArtifactText(value) {
  let output = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  for (const { pattern } of SECRET_PATTERNS) {
    output = output.replace(pattern, '$1<redacted>')
  }
  return output
}

export function findSensitiveArtifactLeaks(value) {
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  return Object.entries(sensitiveArtifactSamples)
    .filter(([, sample]) => text.includes(sample))
    .map(([name]) => name)
}

export function assertNoSensitiveArtifactLeaks(expect, value) {
  expect(findSensitiveArtifactLeaks(value)).toEqual([])
}
