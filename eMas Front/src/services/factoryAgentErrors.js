const STATUS_FALLBACKS = {
  401: 'Authentication failed. Please sign in again.',
  404: 'Requested resource was not found.',
  409: 'Version conflict detected. Please retry.',
  429: 'System is busy. Please wait and try again.',
  503: 'Service temporarily unavailable. Please retry shortly.',
}

export function normalizeFactoryAgentError(err, fallback = 'Request failed.') {
  if (!err) return fallback
  if (typeof err === 'string') return err
  const msg = String(err.message || '').toLowerCase()
  if (msg.includes('failed to fetch') || msg.includes('networkerror')) {
    return fallback || 'Cannot reach Factory Agent backend. Start the backend server and retry.'
  }
  if (err.message && typeof err.message === 'string') return err.message
  if (err.status && STATUS_FALLBACKS[err.status]) return STATUS_FALLBACKS[err.status]
  return fallback
}

export function classifyFactoryAgentError(err) {
  const status = Number(err?.status || 0)
  if (!status) return 'unknown'
  if (status === 401) return 'auth'
  if (status === 404) return 'not_found'
  if (status === 409) return 'conflict'
  if (status === 429) return 'rate_limit'
  if (status >= 500) return 'server'
  return 'client'
}
