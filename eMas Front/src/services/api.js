import logger from './logger'

const BASE_URL = 'http://localhost:8080/api/v1'

/**
 * Parse a backend error response into a human-readable message.
 * Backends often return { detail: "..." } or { message: "..." } or plain text.
 */
async function parseErrorBody(res) {
  try {
    const text = await res.text()
    if (!text) return `${res.status} ${res.statusText}`
    try {
      const json = JSON.parse(text)
      return json.detail || json.message || json.error || text
    } catch {
      return text
    }
  } catch {
    return `${res.status} ${res.statusText}`
  }
}

/**
 * Client timeout for long-running scheduling calls (batch-proposals, reschedule-all, verify-overlaps, etc.).
 * Override with VITE_SCHEDULING_LONG_TIMEOUT_MS (milliseconds), e.g. 3600000 for 60 minutes.
 * If you still see "Request timed out or cancelled; partial results returned" in the API message, the
 * backend stopped early—increase the server-side timeout for those routes as well.
 */
export const SCHEDULING_LONG_TIMEOUT_MS = (() => {
  const raw = import.meta.env?.VITE_SCHEDULING_LONG_TIMEOUT_MS
  const n = raw != null && raw !== '' ? Number(raw) : NaN
  if (Number.isFinite(n) && n > 0) return n
  return 1800000 // default 30 minutes
})()

async function request(method, path, body, extraHeaders, options) {
  const headers = { 'Content-Type': 'application/json', ...(extraHeaders || {}) }
  const opts = {
    method,
    headers,
  }
  if (body !== undefined) opts.body = JSON.stringify(body)

  const timeoutMs = (options || {}).timeoutMs
  let abortController
  let abortTimerId
  if (timeoutMs > 0) {
    abortController = new AbortController()
    opts.signal = abortController.signal
    abortTimerId = setTimeout(() => abortController.abort(), timeoutMs)
  }

  const startMs = Date.now()
  let res

  logger.debug(`→ ${method} ${path}`, body ?? undefined)

  try {
    res = await fetch(`${BASE_URL}${path}`, opts)
  } catch (networkErr) {
    const msg = `Network error reaching ${BASE_URL}${path}`
    logger.error(msg, networkErr, { method, path })
    const isAbort = networkErr.name === 'AbortError'
    const err = new Error(
      isAbort
        ? `Request aborted after ${timeoutMs > 0 ? Math.round(timeoutMs / 60000) : '?'} min (this app’s fetch limit). Set VITE_SCHEDULING_LONG_TIMEOUT_MS to wait longer, or if the server already responded with “partial results”, raise backend/proxy timeouts instead.`
        : `Cannot connect to eMAS server. Is the backend running? (${networkErr.message})`
    )
    err.type = isAbort ? 'TIMEOUT' : 'NETWORK'
    err.original = networkErr
    throw err
  } finally {
    if (abortTimerId) clearTimeout(abortTimerId)
  }

  const durationMs = Date.now() - startMs
  logger.apiRequest(method, path, durationMs, res.status)

  if (!res.ok) {
    const detail = await parseErrorBody(res)
    const msg = `[${res.status}] ${method} ${path}: ${detail}`
    logger.apiError(method, path, new Error(msg))
    const err = new Error(detail || `Request failed with status ${res.status}`)
    err.status = res.status
    err.type   = res.status >= 500 ? 'SERVER' : res.status === 404 ? 'NOT_FOUND' : res.status === 401 ? 'AUTH' : 'CLIENT'
    err.path   = path
    throw err
  }

  try {
    const text = await res.text()
    if (!text) return null
    return JSON.parse(text)
  } catch (parseErr) {
    logger.error(`Failed to parse JSON from ${method} ${path}`, parseErr)
    const err = new Error('The server returned an invalid response.')
    err.type = 'PARSE'
    throw err
  }
}

const get   = (path)                       => request('GET',    path)
const post  = (path, body, headers, opts)  => request('POST',   path, body, headers, opts)
const put   = (path, body, headers, opts)  => request('PUT',    path, body, headers, opts)
const patch = (path, body, headers, opts)  => request('PATCH',  path, body, headers, opts)
const del   = (path)                       => request('DELETE', path)

/** POST with X-User-Role: planner for scheduling write operations */
const postPlanner = (path, body, options = {}) =>
  request('POST', path, body, { 'X-User-Role': 'planner' }, options)

/**
 * All API responses are wrapped as { success: boolean, data: T, error?: string }.
 * toList() extracts an array from the wrapper (or falls back gracefully).
 */
export const toList = (d) => {
  if (!d) return []
  if (Array.isArray(d)) return d
  for (const k of ['data', 'items', 'results', 'jobs', 'machines', 'products',
                    'materials', 'processes', 'formulas', 'slots', 'steps', 'proposals']) {
    if (Array.isArray(d[k])) return d[k]
  }
  return []
}

/**
 * Extract a single object from the API wrapper { success, data }.
 * Returns the inner `data` object, or the value itself if already unwrapped.
 * Returns null for { success: false } wrappers so callers don't treat them as data.
 */
export const toData = (d) => {
  if (!d) return null
  if (typeof d === 'object' && !Array.isArray(d)) {
    // If this is a response wrapper and success is false, there is no data
    if (d.success === false) return null
    if (d.data !== undefined) return d.data
  }
  return d
}

/**
 * batch-proposals / reschedule-all may return `{ success, message, data: { proposals, summary } }`.
 * `toData()` alone drops top-level `message`, which carries partial-result / timeout warnings.
 */
export function unwrapSchedulingBatchPayload(raw) {
  if (raw == null || typeof raw !== 'object') {
    return {
      proposals: [],
      summary: null,
      message: null,
      byMaterial: [],
      byProduct: [],
      materialReplenishmentAggregate: [],
    }
  }
  const inner = toData(raw)
  const layer = inner != null && typeof inner === 'object' && !Array.isArray(inner) ? inner : raw
  const proposals = Array.isArray(layer.proposals) ? layer.proposals : []
  const summary = layer.summary ?? raw.summary ?? null
  const message =
    layer.message ??
    raw.message ??
    raw.error ??
    (typeof raw.detail === 'string' ? raw.detail : null) ??
    null
  const pickArr = (obj, keys) => {
    if (!obj || typeof obj !== 'object') return []
    for (const k of keys) {
      const v = obj[k]
      if (Array.isArray(v) && v.length > 0) return v
    }
    return []
  }
  const nested = layer.batch_shortage || layer.batchShortage || layer.shortage_aggregate || layer.shortageAggregate
  const byMaterial =
    pickArr(layer, ['by_material', 'byMaterial']).length > 0
      ? pickArr(layer, ['by_material', 'byMaterial'])
      : pickArr(summary || {}, ['by_material', 'byMaterial']).length > 0
        ? pickArr(summary || {}, ['by_material', 'byMaterial'])
        : pickArr(nested || {}, ['by_material', 'byMaterial'])
  const byProduct =
    pickArr(layer, ['by_product', 'byProduct', 'schedule_production_aggregate', 'scheduleProductionAggregate']).length > 0
      ? pickArr(layer, ['by_product', 'byProduct', 'schedule_production_aggregate', 'scheduleProductionAggregate'])
      : pickArr(summary || {}, ['by_product', 'byProduct', 'schedule_production_aggregate', 'scheduleProductionAggregate']).length > 0
        ? pickArr(summary || {}, ['by_product', 'byProduct', 'schedule_production_aggregate', 'scheduleProductionAggregate'])
        : pickArr(nested || {}, ['by_product', 'byProduct', 'schedule_production_aggregate', 'scheduleProductionAggregate'])
  const materialReplenishmentAggregate =
    pickArr(summary || {}, ['material_replenishment_aggregate', 'materialReplenishmentAggregate']).length > 0
      ? pickArr(summary || {}, ['material_replenishment_aggregate', 'materialReplenishmentAggregate'])
      : pickArr(layer, ['material_replenishment_aggregate', 'materialReplenishmentAggregate']).length > 0
        ? pickArr(layer, ['material_replenishment_aggregate', 'materialReplenishmentAggregate'])
        : []
  return { proposals, summary, message, byMaterial, byProduct, materialReplenishmentAggregate }
}

/**
 * Merge batch `summary` with aggregate arrays so `extractBatchShortageAggregate(summary)` finds them.
 * `material_replenishment_aggregate` (batch raw-material lines) takes precedence for bulk apply qty/time.
 */
export function mergeBatchSummaryWithAggregate({
  summary,
  byMaterial = [],
  byProduct = [],
  materialReplenishmentAggregate = [],
}) {
  const base = summary && typeof summary === 'object' ? { ...summary } : {}
  if (materialReplenishmentAggregate.length) {
    base.material_replenishment_aggregate = materialReplenishmentAggregate
  }
  if (byMaterial.length) base.by_material = byMaterial
  if (byProduct.length) base.by_product = byProduct
  if (Object.keys(base).length === 0) return null
  return base
}

/** Append guidance when the API reports a timed-out / partial batch (usually server/proxy/solver, not the browser). */
export function augmentScheduleBatchMessage(message) {
  if (message == null || typeof message !== 'string') return message
  if (!/partial results|timed out.*cancel/i.test(message)) return message
  const min = Math.round(SCHEDULING_LONG_TIMEOUT_MS / 60000)
  return `${message}\n\n— This usually means the batch was cut short on the server or reverse proxy (nginx/IIS, etc.), not the browser. This app waits up to ${min} min per request (override: VITE_SCHEDULING_LONG_TIMEOUT_MS). Raise backend and proxy timeouts for batch-proposals / reschedule-all; skipped jobs follow from the partial run.`
}

/**
 * Friendly label for an API error suitable for showing in a toast.
 * @param {Error} err
 * @param {string} fallback
 */
export function apiErrorMessage(err, fallback = 'An unexpected error occurred.') {
  if (!err) return fallback
  if (err.type === 'NETWORK') return 'Cannot connect to the eMAS server. Please check that the backend is running.'
  if (err.type === 'TIMEOUT') return err.message || 'Request timed out. Batch proposals can take 90+ seconds. Please try again.'
  if (err.type === 'AUTH')    return 'Your session has expired. Please refresh and try again.'
  if (err.type === 'NOT_FOUND') return 'The requested resource was not found.'
  if (err.type === 'SERVER')  return `Server error: ${err.message}`
  if (isStaleProposalError(err)) return 'Proposal is stale. Use Reschedule All to regenerate fresh proposals.'
  if (err.message && /outside.*work calendar/i.test(err.message)) {
    return `${err.message} Check resource/machine calendar setup or regenerate proposals.`
  }
  if (err.message)            return err.message
  return fallback
}

/** Returns true if the error indicates a stale proposal (409 or message contains stale/regenerate). */
export function isStaleProposalError(err) {
  if (!err) return false
  if (err.status === 409) return true
  const m = (err.message || '').toLowerCase()
  return m.includes('stale') || m.includes('regenerat')
}

/**
 * Execute a suggested_call from the AI API: { method, path, body, purpose, requires_approval }.
 * Uses X-User-Role: planner for write operations (POST, PUT, PATCH, DELETE).
 */
export async function executeSuggestedCall(call, options = {}) {
  const method = String(call?.method || 'GET').toUpperCase()
  const { path, body } = call
  const isWrite = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)
  const url = path.startsWith('http') ? path : `${BASE_URL}${path.replace(/^\/api\/v1/, '')}`
  const headers = {
    'Content-Type': 'application/json',
    ...(isWrite ? { 'X-User-Role': 'planner' } : {}),
    ...(options.headers || {}),
  }
  const opts = { method, headers }
  if (body && ['POST', 'PUT', 'PATCH'].includes(method)) {
    opts.body = JSON.stringify(body)
  }
  const res = await fetch(url, opts)
  if (!res.ok) {
    const detail = await parseErrorBody(res)
    const err = new Error(detail || `Request failed with status ${res.status}`)
    err.status = res.status
    throw err
  }
  const text = await res.text()
  return text ? JSON.parse(text) : null
}

// ─── Jobs ────────────────────────────────────────────────────────────────────
export const jobsApi = {
  list: (params = {}) => {
    const q = new URLSearchParams(params).toString()
    return get(`/jobs${q ? `?${q}` : ''}`)
  },
  get:       (id)        => get(`/jobs/${id}`),
  getSteps:  (id)        => get(`/jobs/${id}/steps`),
  getSlots:  (id)        => get(`/jobs/${id}/slots`),
  create:    (data)      => post('/jobs', data),
  update:    (id, data)  => put(`/jobs/${id}`, data),
  cancel:    (id)        => del(`/jobs/${id}`),
  duplicate: (id)        => post(`/jobs/${id}/duplicate`),
}

// ─── Job Steps & Slots ───────────────────────────────────────────────────────
export const stepsApi = {
  create:     (data)     => post('/job-steps', data),
  split:      (data)     => post('/job-steps/split', data),
  getSlots:   (stepId)   => get(`/job-steps/${stepId}/slots`),
  getSlot:    (slotId)   => get(`/slots/${slotId}`),
  /** PATCH /slots/:id — supports actual_start, actual_end, status for production logging */
  updateSlot: (slotId, data) => patch(`/slots/${slotId}`, data),
  cancelSlot: (slotId)   => del(`/slots/${slotId}`),
}

// ─── Scheduling events & validation ──────────────────────────────────────────
export const schedulingApi = {
  /**
   * POST /scheduling/events — emit machine_down, job_delay, urgent_insert.
   * Payload: { type, payload } where payload is a JSON string with event-specific data.
   * When AI_AUTO_RESCHEDULE_ON_EVENT=true, triggers automatic reschedule.
   */
  emitEvent: (body) => postPlanner('/scheduling/events', body),
  /**
   * POST /scheduling/slots/validate — validate slot placement.
   * Returns validation_reasons, hard_reasons, soft_reasons, total_penalty.
   */
  validateSlots: (body) => postPlanner('/scheduling/slots/validate', body),
  /** GET /scheduling/products/:id/readiness — material/sub-product readiness for scheduling */
  readiness: (productId, quantity = 1) =>
    get(`/scheduling/products/${productId}/readiness?quantity=${quantity}`),
  /** GET /scheduling/products/:id/explosion — recursive material and sub-product demand (may include step-level breakdown) */
  explosion: (productId, quantity = 1) =>
    get(`/scheduling/products/${productId}/explosion?quantity=${quantity}`),
  /** GET /scheduling/jobs/:id/earliest-completion — earliest completion estimate */
  earliestCompletion: (jobId) => get(`/scheduling/jobs/${jobId}/earliest-completion`),
  /** GET /scheduling/jobs/:id/solver-preview — solver-ready preview with steps, constraints, predecessors */
  solverPreview: (jobId) => get(`/scheduling/jobs/${jobId}/solver-preview`),
  /** GET /scheduling/settings — scheduling config (split_strategy, objective, auto_reschedule_on_event) */
  getSettings: () => get('/scheduling/settings'),
  /** PUT /scheduling/settings — update scheduling config */
  updateSettings: (data) => put('/scheduling/settings', data),
  /** POST /scheduling/refresh-work-calendars — apply work template to resource/machine calendars */
  refreshWorkCalendars: () => postPlanner('/scheduling/refresh-work-calendars', {}),
}

// ─── Machines ────────────────────────────────────────────────────────────────
export const machinesApi = {
  list: (params = {}) => {
    const q = new URLSearchParams(params).toString()
    return get(`/machines${q ? `?${q}` : ''}`)
  },
  get:              (id)        => get(`/machines/${id}`),
  create:           (data)      => post('/machines', data),
  update:           (id, data)  => put(`/machines/${id}`, data),
  addCapability:    (id, data)  => post(`/machines/${id}/capabilities`, data),
  recordDowntime:   (data)      => post('/machines/downtime', data),
  maintenanceAlerts:(params = {}) => {
    const q = new URLSearchParams(params).toString()
    return get(`/machines/maintenance-alerts${q ? `?${q}` : ''}`)
  },
  rerouteRecommendations: (machineId) =>
    get(`/machines/reroute-recommendations?machine_id=${machineId}`),
}

// ─── Products ────────────────────────────────────────────────────────────────
export const productsApi = {
  list:    ()           => get('/products'),
  get:     (id)         => get(`/products/${id}`),
  create:  (data)       => post('/products', data),
  update:  (id, data)   => put(`/products/${id}`, data),
  linkBom: (id, data)   => put(`/products/${id}/bom`, data),
}

// ─── Processes (routing) ─────────────────────────────────────────────────────
export const processesApi = {
  list:        ()           => get('/processes'),
  get:         (id)         => get(`/processes/${id}`),
  getByProduct:(prodId)     => get(`/products/${prodId}/process`),
  getSteps:    (id)         => get(`/processes/${id}/steps`),
  create:      (data)       => post('/processes', data),
  addStep:     (id, data)   => post(`/processes/${id}/steps`, data),
  delete:      (id)         => del(`/processes/${id}`),
  /** GET /process-steps/:stepId/materials — role: input | output | all (default input) */
  getStepMaterials: (stepId, role = 'input') =>
    get(`/process-steps/${stepId}/materials${role ? `?role=${role}` : ''}`),
  /** POST /process-steps/:stepId/materials — add material to step */
  addStepMaterial: (stepId, body) => post(`/process-steps/${stepId}/materials`, body),
  /** DELETE /process-steps/:stepId/materials/:id — remove material from step */
  removeStepMaterial: (stepId, materialRecordId) =>
    del(`/process-steps/${stepId}/materials/${materialRecordId}`),
}

// ─── Formulas ────────────────────────────────────────────────────────────────
export const formulasApi = {
  list:           ()           => get('/formulas'),
  get:            (id)         => get(`/formulas/${id}`),
  getIngredients: (id)         => get(`/formulas/${id}/ingredients`),
  create:         (data)       => post('/formulas', data),
  addIngredient:  (id, data)   => post(`/formulas/${id}/ingredients`, data),
  delete:         (id)         => del(`/formulas/${id}`),
}

// ─── Inventory ───────────────────────────────────────────────────────────────
export const inventoryApi = {
  list: (params = {}) => {
    const q = new URLSearchParams(params).toString()
    return get(`/inventory/materials${q ? `?${q}` : ''}`)
  },
  get:     (id)        => get(`/inventory/materials/${id}`),
  create:  (data)      => post('/inventory/materials', data),
  update:  (id, data)  => put(`/inventory/materials/${id}`, data),
  // Field: reference_job_id (not job_id) per API spec
  consume: (data)      => post('/inventory/consume', data),
  receive: (data)      => post('/inventory/receive', data),
  // Expected arrivals
  expectedArrivals: {
    list: (params = {}) => {
      const q = new URLSearchParams(params).toString()
      return get(`/inventory/expected-arrivals${q ? `?${q}` : ''}`)
    },
    create: (data) => post('/inventory/expected-arrivals', data),
  },
}

// ─── Production & Quality ────────────────────────────────────────────────────
export const productionApi = {
  log:     (data) => post('/production-logs', data),
  inspect: (data) => post('/quality/inspections', data),
}

// ─── Maintenance ─────────────────────────────────────────────────────────────
export const maintenanceApi = {
  record: (data) => post('/maintenance', data),
}

// ─── Reports & Analytics ─────────────────────────────────────────────────────
export const reportsApi = {
  productionOutput:      (params = {}) => get(`/reports/production-output?${new URLSearchParams(params)}`),
  machineUtilization:    (params = {}) => get(`/reports/machine-utilization?${new URLSearchParams(params)}`),
  jobCompletion:         (params = {}) => get(`/reports/job-completion?${new URLSearchParams(params)}`),
  inventoryTrends:       (params = {}) => get(`/reports/inventory-trends?${new URLSearchParams(params)}`),
  qualityTrends:         (params = {}) => get(`/reports/quality-trends?${new URLSearchParams(params)}`),
  oee:                   (params = {}) => get(`/reports/oee?${new URLSearchParams(params)}`),
  bottlenecks:           (params = {}) => get(`/reports/bottlenecks?${new URLSearchParams(params)}`),
  maintenanceEfficiency: (params = {}) => get(`/reports/maintenance-efficiency?${new URLSearchParams(params)}`),
}

// ─── Dashboard ───────────────────────────────────────────────────────────────
// GET /dashboard/kpis → { oee_pct, oee_change, production_units, production_change,
//                          downtime_hrs, downtime_change, utilization_pct, utilization_change }
export const dashboardApi = {
  kpis: () => get('/dashboard/kpis'),
}

// ─── Alerts ──────────────────────────────────────────────────────────────────
// GET /alerts → [{ type, title, time, machine_id? }]
export const alertsApi = {
  list: (params = {}) => {
    const q = new URLSearchParams(params).toString()
    return get(`/alerts${q ? `?${q}` : ''}`)
  },
}

// ─── AI / NLP ────────────────────────────────────────────────────────────────
export const aiApi = {
  /**
   * Natural-language orchestration endpoint.
   * By default we stay in suggest_only mode; executeReadonly=true enables
   * safe read-only execution on the backend.
   */
  command: (query, executeReadonly = false) => {
    const body = { query }
    if (executeReadonly) body.execute_readonly = true
    return post('/ai/command', body)
  },

  /**
   * Chat/conversation persistence (see docs/AI_CHAT_API_SPEC.md).
   */
  chats: {
    list:         () => get('/ai/chats'),
    create:       (data = {}) => post('/ai/chats', data),
    get:          (id) => get(`/ai/chats/${id}`),
    sendMessage:  (id, { query }) => post(`/ai/chats/${id}/messages`, { query }),
  },

  /**
   * AI scheduling helpers mapped to /ai/scheduling/* endpoints.
   * These are thin wrappers; all business logic stays in the UI.
   */
  scheduling: {
    assist:        (jobId)      => get(`/ai/scheduling/jobs/${jobId}/assist`),
    delayRisk:     (jobId)      => get(`/ai/scheduling/jobs/${jobId}/delay-risk`),
    explanation:   (jobId)      => get(`/ai/scheduling/jobs/${jobId}/explanation`),
    draftProposal: (jobId)      => get(`/ai/scheduling/jobs/${jobId}/proposal`),
    createProposal:(jobId, data = {}) =>
      postPlanner(`/ai/scheduling/jobs/${jobId}/proposals`, data, { timeoutMs: SCHEDULING_LONG_TIMEOUT_MS }),
    listProposals: (jobId)      => get(`/ai/scheduling/jobs/${jobId}/proposals`),
    getProposal:   (proposalId) => get(`/ai/scheduling/proposals/${proposalId}`),
    approveProposal: (proposalId, data = {}) =>
      postPlanner(`/ai/scheduling/proposals/${proposalId}/approve`, data, { timeoutMs: SCHEDULING_LONG_TIMEOUT_MS }),
    rejectProposal: (proposalId, data = {}) =>
      postPlanner(`/ai/scheduling/proposals/${proposalId}/reject`, data, { timeoutMs: SCHEDULING_LONG_TIMEOUT_MS }),
    applyProposal: (proposalId, data = {}) =>
      postPlanner(`/ai/scheduling/proposals/${proposalId}/apply`, data, { timeoutMs: SCHEDULING_LONG_TIMEOUT_MS }),
    shortageAnalysis: (jobId) =>
      get(`/ai/scheduling/jobs/${jobId}/shortage-analysis`),
    applyReplenishment: (proposalId, data = {}) =>
      postPlanner(`/ai/scheduling/proposals/${proposalId}/apply-replenishment`, data, {
        timeoutMs: SCHEDULING_LONG_TIMEOUT_MS,
      }),
    /** Batch-level replenishment (one coherent line per material / product). Optional until backend ships it. */
    applyReplenishmentBatch: (data = {}) =>
      postPlanner('/ai/scheduling/apply-replenishment-batch', data, {
        timeoutMs: SCHEDULING_LONG_TIMEOUT_MS,
      }),
    replenishAndReplan: (jobId, data = {}) =>
      postPlanner(`/ai/scheduling/jobs/${jobId}/replenish-and-replan`, data, {
        timeoutMs: SCHEDULING_LONG_TIMEOUT_MS,
      }),
    batchProposals: (body = {}) => {
      const hasScope = body?.scope === 'all_unscheduled'
      const hasJobIds = Array.isArray(body?.job_ids) && body.job_ids.length > 0
      const payload = hasScope || hasJobIds ? body : { scope: 'all_unscheduled', order_by: body?.order_by || 'epo' }
      return postPlanner('/ai/scheduling/batch-proposals', payload, { timeoutMs: SCHEDULING_LONG_TIMEOUT_MS })
    },
    rescheduleAll:  (body = {}) => postPlanner('/ai/scheduling/reschedule-all', body, { timeoutMs: SCHEDULING_LONG_TIMEOUT_MS }),
    verifyOverlaps: (body) =>
      postPlanner('/ai/scheduling/verify-overlaps', body, { timeoutMs: SCHEDULING_LONG_TIMEOUT_MS }),
    splitSuggestion: (jobStepId) => get(`/ai/scheduling/job-steps/${jobStepId}/split-suggestion`),
    machineRanking:  (jobStepId, start, end) =>
      get(`/ai/scheduling/job-steps/${jobStepId}/machine-ranking?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`),
    bottleneckForecast: (daysAhead = 7) =>
      get(`/ai/scheduling/bottleneck-forecast?days_ahead=${daysAhead}`),
  },
}

// ─── Predictive Analysis ─────────────────────────────────────────────────────
// NOTE: These endpoints are NOT yet in the backend spec (see MISSING_APIS.md)
export const predictiveApi = {
  highRiskJobs:    (params = {}) => get(`/predictive/high-risk-jobs?${new URLSearchParams(params)}`),
  recommendations: ()            => get('/predictive/recommendations'),
  forecast:        (params = {}) => get(`/predictive/forecast?${new URLSearchParams(params)}`),
  confidence:      ()            => get('/predictive/confidence'),
}

// ─── Settings ────────────────────────────────────────────────────────────────
export const settingsApi = {
  get:    () => get('/settings'),
  update: (data) => put('/settings', data),
}

// ─── Reference / Lookup data (API-ADDENDUM.md) ───────────────────────────────
// Returns { data: item[], error: string|null } so callers can show real errors.
export async function refGet(path) {
  try {
    const raw = await get(path)
    const items = toList(raw)
    if (items.length === 0 && raw && !Array.isArray(raw)) {
      // Backend may have returned { success: true, data: [] } — that is valid and empty
      logger.debug(`[ref] ${path} returned empty list`, raw)
    }
    return { data: items, error: null }
  } catch (err) {
    // 404 = endpoint not yet implemented → silent (no error shown)
    if (err.status === 404) {
      logger.debug(`[ref] ${path} → 404, endpoint not yet implemented`)
      return { data: [], error: null }
    }
    logger.error(`[ref] Failed to load ${path}`, err)
    return { data: [], error: err.message || 'Failed to load options' }
  }
}
const refPost   = (path, body) => post(path, body)
const refDelete = (path)       => del(path)

export const referenceApi = {
  machineTypes:     { list: () => refGet('/reference/machine-types'),
                      create: (body) => refPost('/reference/machine-types', body),
                      remove: (id)   => refDelete(`/reference/machine-types/${id}`) },
  productTypes:     { list: () => refGet('/reference/product-types'),
                      create: (body) => refPost('/reference/product-types', body),
                      remove: (id)   => refDelete(`/reference/product-types/${id}`) },
  locations:        { list: () => refGet('/reference/locations'),
                      create: (body) => refPost('/reference/locations', body),
                      remove: (id)   => refDelete(`/reference/locations/${id}`) },
  storageLocations: { list: () => refGet('/reference/storage-locations'),
                      create: (body) => refPost('/reference/storage-locations', body),
                      remove: (id)   => refDelete(`/reference/storage-locations/${id}`) },
  stepTypes:        { list: () => refGet('/reference/step-types'),
                      create: (body) => refPost('/reference/step-types', body),
                      remove: (id)   => refDelete(`/reference/step-types/${id}`) },
}
