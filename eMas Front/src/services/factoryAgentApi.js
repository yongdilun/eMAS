import logger from './logger'
import { normalizeFactoryAgentError } from './factoryAgentErrors'

export const FACTORY_AGENT_BASE_URL = (
  import.meta.env?.VITE_FACTORY_AGENT_BASE_URL ||
  'http://127.0.0.1:8000'
).replace(/\/+$/, '')

const STATIC_BEARER = import.meta.env?.VITE_FACTORY_AGENT_BEARER_TOKEN || ''
const REQUEST_TIMEOUT_MS = Number(import.meta.env?.VITE_FACTORY_AGENT_REQUEST_TIMEOUT_MS || 75_000)
const FACTORY_AGENT_USER_ID = import.meta.env?.VITE_FACTORY_AGENT_USER_ID || 'frontend-operator'

export const factoryAgentStreamAuth = {
  hasBearerToken: Boolean(STATIC_BEARER),
  eventSourceEnabled: !STATIC_BEARER,
  disabledReason: STATIC_BEARER
    ? 'Factory Agent REST uses a static bearer token, but browser EventSource cannot attach Authorization headers. Snapshot polling remains enabled.'
    : '',
}

export function buildFactoryAgentUrl(path) {
  const value = String(path || '').trim()
  if (!value) return FACTORY_AGENT_BASE_URL
  try {
    return new URL(value).toString()
  } catch {
    // Relative Factory Agent deployments usually mount the API behind /agent.
  }
  if (!value.startsWith('/')) return `${FACTORY_AGENT_BASE_URL}/${value}`
  if (
    FACTORY_AGENT_BASE_URL.startsWith('/') &&
    (value === FACTORY_AGENT_BASE_URL || value.startsWith(`${FACTORY_AGENT_BASE_URL}/`))
  ) {
    return value
  }
  return `${FACTORY_AGENT_BASE_URL}${value}`
}

function buildUrl(path) {
  return buildFactoryAgentUrl(path)
}

async function parseErrorBody(res) {
  try {
    const text = await res.text()
    if (!text) return `${res.status} ${res.statusText}`
    try {
      const json = JSON.parse(text)
      if (typeof json.detail === 'string') return json.detail
      if (json.detail && typeof json.detail === 'object') return JSON.stringify(json.detail)
      return json.message || json.error || text
    } catch {
      return text
    }
  } catch {
    return `${res.status} ${res.statusText}`
  }
}

async function request(method, path, body, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    'X-User-Id': FACTORY_AGENT_USER_ID,
    ...(options.headers || {}),
  }

  const token = options.bearerToken || STATIC_BEARER
  if (token) headers.Authorization = `Bearer ${token}`

  const init = { method, headers }
  if (body !== undefined) init.body = JSON.stringify(body)

  const startedAt = Date.now()
  const url = buildUrl(path)
  let timeoutId = null
  if (Number.isFinite(REQUEST_TIMEOUT_MS) && REQUEST_TIMEOUT_MS > 0) {
    const controller = new AbortController()
    init.signal = controller.signal
    timeoutId = globalThis.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  }
  logger.debug(`[factory-agent] -> ${method} ${path}`, body)

  let response
  try {
    response = await fetch(url, init)
  } catch (err) {
    if (err?.name === 'AbortError') {
      const e = new Error(`Factory Agent request timed out after ${REQUEST_TIMEOUT_MS} ms. Retry or cancel the current run.`)
      e.type = 'TIMEOUT'
      e.path = path
      e.original = err
      throw e
    }
    const e = new Error(
      normalizeFactoryAgentError(
        err,
        `Cannot reach Factory Agent backend at ${FACTORY_AGENT_BASE_URL}. ${err?.message || 'Network error.'}`,
      ),
    )
    e.type = 'NETWORK'
    e.original = err
    throw e
  } finally {
    if (timeoutId) globalThis.clearTimeout(timeoutId)
  }

  logger.apiRequest(method, `factory-agent${path}`, Date.now() - startedAt, response.status)

  if (!response.ok) {
    const detail = await parseErrorBody(response)
    const e = new Error(normalizeFactoryAgentError({ status: response.status, message: detail }, `${response.status} ${response.statusText}`))
    e.status = response.status
    e.type = response.status === 401 ? 'AUTH' : response.status === 404 ? 'NOT_FOUND' : response.status === 409 ? 'CONFLICT' : response.status === 429 ? 'RATE_LIMIT' : response.status >= 500 ? 'SERVER' : 'CLIENT'
    e.path = path
    throw e
  }

  const text = await response.text()
  if (!text) return null
  return JSON.parse(text)
}

export const factoryAgentApi = {
  createSession: ({ user_id, name }, options) => request('POST', '/sessions', { user_id, name }, options),
  listSessions: (params = {}, options) => {
    const q = new URLSearchParams()
    if (params.user_id) q.set('user_id', params.user_id)
    const suffix = q.toString() ? `?${q.toString()}` : ''
    return request('GET', `/sessions${suffix}`, undefined, options)
  },
  getSession: (sessionId, options) => request('GET', `/sessions/${sessionId}`, undefined, options),
  updateSession: (sessionId, payload, options) => request('PATCH', `/sessions/${sessionId}`, payload, options),
  getSnapshot: (sessionId, options) => request('GET', `/sessions/${sessionId}/snapshot`, undefined, options),
  getMessages: (sessionId, options) => request('GET', `/sessions/${sessionId}/messages`, undefined, options),
  getSteps: (sessionId, options) => request('GET', `/sessions/${sessionId}/steps`, undefined, options),
  deleteSession: (sessionId, options) => request('DELETE', `/sessions/${sessionId}`, undefined, options),

  listTools: (params = {}, options) => {
    const q = new URLSearchParams()
    if (params.intent) q.set('intent', params.intent)
    if (params.max_tools != null) q.set('max_tools', String(params.max_tools))
    const suffix = q.toString() ? `?${q.toString()}` : ''
    return request('GET', `/tools${suffix}`, undefined, options)
  },

  addMessage: (sessionId, { content, role = 'user', mode = 'normal' }, options) =>
    request('POST', `/sessions/${sessionId}/messages`, { content, role, mode }, options),

  createPlan: (sessionId, draft, options) => {
    const body = draft ? { draft } : {}
    return request('POST', `/sessions/${sessionId}/plans`, body, options)
  },

  execute: (sessionId, params = {}, options) => {
    const q = new URLSearchParams()
    if (params.background != null) q.set('background', String(Boolean(params.background)))
    if (params.expected_version != null) q.set('expected_version', String(params.expected_version))
    const suffix = q.toString() ? `?${q.toString()}` : ''
    return request('POST', `/sessions/${sessionId}/execute${suffix}`, {}, options)
  },

  confirm: (sessionId, payload = {}, options) =>
    request('POST', `/sessions/${sessionId}/confirm`, payload, options),

  cancelSession: (sessionId, options) => request('POST', `/sessions/${sessionId}/cancel`, {}, options),

  listPendingApprovals: (params = {}, options) => {
    const q = new URLSearchParams()
    if (params.session_id) q.set('session_id', params.session_id)
    const suffix = q.toString() ? `?${q.toString()}` : ''
    return request('GET', `/approvals/pending${suffix}`, undefined, options)
  },
  getApproval: (approvalId, options) => request('GET', `/approvals/${approvalId}`, undefined, options),

  approve: (approvalId, payload = {}, options) =>
    request('POST', `/approvals/${approvalId}/approve`, payload, options),

  reject: (approvalId, payload = {}, options) =>
    request('POST', `/approvals/${approvalId}/reject`, payload, options),
}

export const FACTORY_AGENT_STATUS = {
  IDLE: 'IDLE',
  PLANNING: 'PLANNING',
  WAITING_APPROVAL: 'WAITING_APPROVAL',
  WAITING_CONFIRMATION: 'WAITING_CONFIRMATION',
  EXECUTING: 'EXECUTING',
  BLOCKED: 'BLOCKED',
  FAILED: 'FAILED',
  COMPLETED: 'COMPLETED',
}
