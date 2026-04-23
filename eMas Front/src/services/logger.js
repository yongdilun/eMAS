/**
 * eMAS Centralized Logger
 *
 * Usage:
 *   import logger from '../services/logger'
 *   logger.info('Jobs loaded', { count: 5 })
 *   logger.error('Failed to fetch machines', err, { page: 'MachineResources' })
 *
 * Levels: debug < info < warn < error
 * In production (NODE_ENV=production) debug/info are suppressed.
 *
 * Remote logging (POST /api/v1/logs) is only attempted when:
 *   1. The endpoint has previously responded with a non-404
 *   2. Level is 'error' (not 'warn') to prevent spam from known-missing endpoints
 */

const IS_DEV = import.meta.env.DEV

const LEVELS = { debug: 0, info: 1, warn: 2, error: 3 }
const MIN_LEVEL = IS_DEV ? LEVELS.debug : LEVELS.warn

const STYLES = {
  debug: 'color:#6b7280;font-weight:500',
  info:  'color:#0ea5e9;font-weight:600',
  warn:  'color:#f59e0b;font-weight:700',
  error: 'color:#ef4444;font-weight:700',
}

const ICONS = { debug: '🔍', info: 'ℹ️', warn: '⚠️', error: '❌' }

function print(level, message, data, context) {
  if (LEVELS[level] < MIN_LEVEL) return
  const ts  = new Date().toISOString().slice(11, 23)
  const tag = `[eMAS ${ICONS[level]} ${ts}]`

  if (level === 'error') {
    console.error(`%c${tag} ${message}`, STYLES[level], ...[data, context].filter(Boolean))
  } else if (level === 'warn') {
    console.warn(`%c${tag} ${message}`, STYLES[level], ...[data, context].filter(Boolean))
  } else if (IS_DEV) {
    console.log(`%c${tag} ${message}`, STYLES[level], ...[data, context].filter(Boolean))
  }
}

/**
 * Remote log state — disabled by default; backend has no POST /api/v1/logs route.
 * Set to true only when backend adds the endpoint.
 */
let remoteEnabled = false
let remoteChecked = true

async function remoteLog(level, message, error, context) {
  // Only send actual errors (not warns) to avoid spam from expected-missing endpoints
  if (level !== 'error') return
  // If we already know the endpoint doesn't exist, stop immediately
  if (!remoteEnabled) return

  try {
    const payload = {
      level,
      message,
      error: error ? { name: error.name, message: error.message, stack: error.stack } : undefined,
      context,
      user_agent: navigator.userAgent,
      url:        window.location.href,
      ts:         new Date().toISOString(),
    }
    const res = await fetch('http://localhost:8080/api/v1/logs', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    })
    remoteChecked = true
    // If backend doesn't have this endpoint, permanently disable remote logging
    if (res.status === 404 || res.status === 405) {
      remoteEnabled = false
      if (IS_DEV) console.info('%c[eMAS] /api/v1/logs not available — remote logging disabled', 'color:#6b7280')
    }
  } catch (_) {
    // Network error — disable to avoid repeated failures
    if (!remoteChecked) remoteEnabled = false
  }
}
void remoteChecked  // suppress unused warning

const logger = {
  debug: (message, data, context) => {
    print('debug', message, data, context)
  },

  info: (message, data, context) => {
    print('info', message, data, context)
  },

  // warn — console only, no remote call (avoids 404 storms for expected-missing APIs)
  warn: (message, data, context) => {
    print('warn', message, data, context)
  },

  /** @param {Error|unknown} error  @param {object} [context] */
  error: (message, error, context) => {
    print('error', message, error, context)
    remoteLog('error', message, error instanceof Error ? error : new Error(String(error ?? message)), context)
  },

  /** Log an API request — only logs non-2xx in dev */
  apiRequest: (method, path, durationMs, status) => {
    if (!IS_DEV) return
    const ok    = status >= 200 && status < 300
    const level = ok ? 'debug' : status >= 500 ? 'error' : 'warn'
    const icon  = ok ? '✅' : status >= 500 ? '🔴' : '🟡'
    // Don't log 404s on known-missing predictive/logs endpoints
    const isExpected404 = status === 404 && (
      path.includes('/predictive/') ||
      path.includes('/dashboard/kpis') ||
      path.includes('/alerts') ||
      path === '/logs'
    )
    if (isExpected404) return
    print(level, `${icon} ${method} ${path} → ${status} (${durationMs}ms)`)
  },

  /** Log an API error — only remote-logs true server errors, not 404s */
  apiError: (method, path, error) => {
    // Skip remote logging for known-unimplemented endpoints
    const is404 = error?.status === 404 || error?.message?.includes('404')
    print(is404 ? 'warn' : 'error', `API ${method} ${path} failed`, error)
    if (!is404) {
      remoteLog('error', `API ${method} ${path} failed`, error, { method, path })
    }
  },
}

export default logger
