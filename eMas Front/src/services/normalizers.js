/**
 * eMAS Data Normalizers
 *
 * The backend may return any casing (snake_case, camelCase, PascalCase) and
 * may wrap scalar values in { value, label } objects. Each normalizer picks
 * the first truthy value across all known variants and always returns plain
 * JS primitives — never objects — so React can safely render any field.
 */

import logger from './logger'

/**
 * Safely convert a value to a plain string/number.
 * If it's an object like { value, label }, extract the inner value.
 */
const coerce = (v) => {
  if (v === undefined || v === null) return undefined
  if (typeof v === 'object' && !Array.isArray(v)) {
    // Common { value, label } pattern from some ORMs / serializers
    const inner = v.value ?? v.label ?? v.name ?? v.id ?? v.code
    if (inner !== undefined && inner !== null) return inner
    return undefined // avoid returning the raw object
  }
  return v
}

/** Capitalize first letter of a string (e.g. "running" → "Running") */
const cap = (s) => s ? String(s).charAt(0).toUpperCase() + String(s).slice(1) : s

/** Pick first truthy value from `keys` on `obj`, coerce to primitive */
const pick = (obj, keys, fallback = undefined) => {
  for (const k of keys) {
    const raw = obj[k]
    if (raw === undefined || raw === null || raw === '') continue
    const v = coerce(raw)
    if (v !== undefined && v !== null && v !== '') return v
  }
  return fallback
}

/** Unwrap single { success, data } wrapper if present */
export const unwrap = (item) => {
  if (!item || typeof item !== 'object') return item
  if (!Array.isArray(item) && 'success' in item && 'data' in item) return item.data ?? item
  return item
}

/**
 * Recursively unwrap API list responses that may be nested 1 or 2 levels deep.
 * Handles: [...], { data: [...] }, { success, data: [...] }, { success, data: { data: [...] } }
 */
export const unwrapList = (d) => {
  if (!d) return []
  if (Array.isArray(d)) return d
  // { data: [...] } or { success, data: [...] }
  if (Array.isArray(d.data)) return d.data
  // { success, data: { data: [...] } }
  if (d.data && Array.isArray(d.data.data)) return d.data.data
  // { items: [...] }, { results: [...] }, etc.
  for (const k of ['items', 'results', 'jobs', 'machines', 'products', 'materials', 'logs']) {
    if (Array.isArray(d[k])) return d[k]
  }
  return []
}

// ─── Product ──────────────────────────────────────────────────────────────────
export const normalizeProduct = (raw) => {
  const p = unwrap(raw) || raw || {}
  return {
    product_id: pick(p, ['product_id', 'ProductID', 'productId', 'id', 'ID']),
    product_name: pick(p, ['product_name', 'ProductName', 'productName', 'name', 'Name'], '—'),
    product_type: pick(p, ['product_type', 'ProductType', 'productType', 'category', 'Category', 'type', 'Type'], '—'),
    unit_of_measure: pick(p, ['unit_of_measure', 'UnitOfMeasure', 'unitOfMeasure', 'unit', 'Unit', 'uom', 'UOM'], '—'),
    description: pick(p, ['description', 'Description'], ''),
  }
}

// ─── Material / Inventory ─────────────────────────────────────────────────────
export const normalizeMaterial = (raw) => {
  const m = unwrap(raw) || raw || {}
  return {
    material_id: pick(m, ['material_id', 'MaterialID', 'materialId', 'id', 'ID']),
    material_name: pick(m, ['material_name', 'MaterialName', 'materialName', 'name', 'Name'], '—'),
    unit: pick(m, ['unit', 'Unit', 'uom', 'UOM'], ''),
    current_stock: pick(m, ['current_stock', 'CurrentStock', 'currentStock', 'stock', 'qty', 'quantity'], null),
    min_stock: pick(m, ['min_stock', 'MinStock', 'minStock', 'minimum_stock', 'reorder_level'], null),
    storage_location: pick(m, ['storage_location', 'StorageLocation', 'storageLocation', 'storage_area', 'StorageArea', 'storageArea', 'location', 'Location'], '—'),
    status: pick(m, ['status', 'Status'], null),
  }
}

// ─── Machine ──────────────────────────────────────────────────────────────────
export const normalizeMachine = (raw) => {
  const m = unwrap(raw) || raw || {}
  const rawStatus = pick(m, ['status', 'Status'], 'Idle')
  // Normalize status to Title Case to match STATUS_COLORS keys
  const statusMap = {
    running: 'Running', idle: 'Idle',
    maintenance: 'Maintenance', offline: 'Maintenance',
    'in maintenance': 'Maintenance', error: 'Maintenance',
  }
  const status = statusMap[String(rawStatus).toLowerCase()] ?? cap(String(rawStatus))
  return {
    machine_id: pick(m, ['machine_id', 'MachineID', 'machineId', 'id', 'ID']),
    machine_name: pick(m, ['machine_name', 'MachineName', 'machineName', 'name', 'Name'], '—'),
    machine_type: pick(m, ['machine_type', 'MachineType', 'machineType', 'type', 'Type'], '—'),
    status,
    capacity_per_hour: pick(m, ['capacity_per_hour', 'CapacityPerHour', 'capacityPerHour', 'max_capacity', 'MaxCapacity', 'maxCapacity', 'capacity'], null),
    maintenance_interval_days: pick(m, ['maintenance_interval_days', 'MaintenanceIntervalDays', 'maintenance_interval', 'maintenanceInterval'], null),
    last_maintenance_date: pick(m, ['last_maintenance_date', 'LastMaintenanceDate', 'last_maintenance', 'lastMaintenance'], '—'),
    location: pick(m, ['location', 'Location'], '—'),
    utilization_rate: pick(m, ['utilization_rate', 'UtilizationRate', 'utilizationRate', 'utilization'], null),
  }
}

// ─── Maintenance Alert ────────────────────────────────────────────────────────
export const normalizeMaintenanceAlert = (raw) => {
  const a = unwrap(raw) || raw || {}

  if (import.meta.env.DEV) {
    logger.info('[DEBUG] Maintenance alert raw keys:', Object.keys(a), a)
  }

  // Try every plausible date field name
  const rawDue = pick(a, [
    'due_date', 'DueDate', 'dueDate',
    'next_maintenance', 'nextMaintenance', 'next_maintenance_date', 'nextMaintenanceDate',
    'scheduled_date', 'scheduledDate', 'scheduled_at', 'scheduledAt',
    'maintenance_date', 'maintenanceDate', 'maintenance_due', 'maintenanceDue',
    'next_service_date', 'nextServiceDate', 'service_date', 'serviceDate',
    'due_at', 'dueAt',
  ])

  // Try every plausible days-numeric field name
  const rawDays = pick(a, [
    'days_until', 'DaysUntil', 'daysUntil',
    'days_remaining', 'daysRemaining',
    'days_ahead', 'daysAhead',
    'days_until_maintenance', 'daysUntilMaintenance',
    'days', 'Days',
  ])

  // Calculate days_until from date if not directly provided
  let days_until = rawDays != null ? Number(rawDays) : null
  if (days_until == null && rawDue) {
    try {
      const diff = new Date(String(rawDue)).getTime() - Date.now()
      if (!isNaN(diff)) days_until = Math.ceil(diff / (1000 * 60 * 60 * 24))
    } catch { /* ignore bad date strings */ }
  }

  return {
    machine_id: pick(a, ['machine_id', 'MachineID', 'machineId', 'id', 'ID'], '—'),
    machine_name: pick(a, ['machine_name', 'MachineName', 'machineName', 'name', 'Name'], null),
    days_until,
    due_date: rawDue,
  }
}

// ─── Job ──────────────────────────────────────────────────────────────────────
export const normalizeJob = (raw) => {
  const j = unwrap(raw) || raw || {}
  return {
    job_id: pick(j, ['job_id', 'JobID', 'jobId', 'id', 'ID']),
    product_id: pick(j, ['product_id', 'ProductID', 'productId'], '—'),
    quantity_total: pick(j, ['quantity_total', 'QuantityTotal', 'quantityTotal', 'quantity', 'Quantity'], null),
    quantity_completed: pick(j, ['quantity_completed', 'QuantityCompleted', 'quantityCompleted'], null),
    priority: pick(j, ['priority', 'Priority'], '—'),
    deadline: pick(j, ['deadline', 'Deadline'], null),
    status: pick(j, ['status', 'Status'], 'scheduled'),
    created_at: pick(j, ['created_at', 'CreatedAt', 'createdAt'], null),
    updated_at: pick(j, ['updated_at', 'UpdatedAt', 'updatedAt'], null),
    notes: pick(j, ['notes', 'Notes'], ''),
  }
}

// ─── Slot ─────────────────────────────────────────────────────────────────────
export const normalizeSlot = (raw) => {
  const s = unwrap(raw) || raw || {}
  return {
    slot_id: pick(s, ['slot_id', 'SlotID', 'slotId', 'id', 'ID']),
    job_step_id: pick(s, ['job_step_id', 'JobStepID', 'jobStepId']),
    machine_id: pick(s, ['machine_id', 'MachineID', 'machineId'], '—'),
    scheduled_start: pick(s, ['scheduled_start', 'ScheduledStart', 'scheduledStart', 'start_time', 'startTime']),
    scheduled_end: pick(s, ['scheduled_end', 'ScheduledEnd', 'scheduledEnd', 'end_time', 'endTime']),
    actual_start: pick(s, ['actual_start', 'ActualStart', 'actualStart']),
    actual_end: pick(s, ['actual_end', 'ActualEnd', 'actualEnd']),
    quantity_planned: pick(s, ['quantity_planned', 'QuantityPlanned', 'quantityPlanned', 'quantity', 'Quantity'], null),
    status: pick(s, ['status', 'Status'], 'scheduled'),
  }
}

// ─── Job Step ─────────────────────────────────────────────────────────────────
export const normalizeStep = (raw) => {
  const s = unwrap(raw) || raw || {}
  return {
    job_step_id: pick(s, ['job_step_id', 'JobStepID', 'jobStepId']),
    step_id: pick(s, ['step_id', 'StepID', 'stepId']),
    step_name: pick(s, ['step_name', 'StepName', 'stepName', 'name', 'Name'], null),
    step_sequence: pick(s, ['step_sequence', 'StepSequence', 'stepSequence', 'sequence', 'order'], null),
    quantity_target: pick(s, ['quantity_target', 'QuantityTarget', 'quantityTarget'], null),
    quantity_completed: pick(s, ['quantity_completed', 'QuantityCompleted', 'quantityCompleted'], null),
    status: pick(s, ['status', 'Status'], 'scheduled'),
  }
}

/**
 * Debug helper: log the keys of the first item in a list response.
 * Call this when data comes back but renders as blank.
 */
export const debugResponse = (label, rawResponse) => {
  if (!import.meta.env.DEV) return
  const list = Array.isArray(rawResponse)
    ? rawResponse
    : Array.isArray(rawResponse?.data)
      ? rawResponse.data
      : Array.isArray(rawResponse?.data?.data)
        ? rawResponse.data.data
        : []

  if (list.length === 0) {
    logger.warn(`[DEBUG] ${label}: response has 0 items`, rawResponse)
    return
  }
  logger.info(
    `[DEBUG] ${label}: ${list.length} items. First item keys: [${Object.keys(list[0] ?? {}).join(', ')}]`,
    list[0]
  )
}

export const normalizeShortageEntityId = (resolution = {}) =>
  resolution?.material_id ||
  resolution?.product_id ||
  resolution?.target_product_id ||
  resolution?.replenishment?.material_id ||
  resolution?.replenishment?.product_id ||
  null

/** Lowercase canonical option_type from API (replenish, delay_jobs, and related material actions). */
const canonicalizeOptionType = (resolution = {}) => {
  const raw = resolution?.option_type
  if (raw == null || raw === '') return 'unknown'
  return String(raw).trim().toLowerCase()
}

/**
 * Effective quantity for a recommendation row: empty draft falls back to suggested_qty (avoids 0 ?? bug).
 */
export const recommendationQtyFromDraft = (draft = {}, rec = {}) => {
  const raw = draft.qty
  if (raw === '' || raw == null) return Number(rec.suggested_qty ?? 0)
  const n = Number(raw)
  return Number.isFinite(n) ? n : Number(rec.suggested_qty ?? 0)
}

/**
 * True if this recommendation should be sent to apply-replenishment (material arrivals).
 * Handles case/variant option_type values and untyped per-material rows that still carry qty + time.
 */
export const isReplenishRecommendation = (rec = {}) => {
  const t = String(rec?.option_type ?? '').trim().toLowerCase()
  if (['replenish', 'purchase', 'purchase_order', 'order', 'expected_arrival'].includes(t)) return true
  if (['schedule_production', 'delay_jobs', 'split_time_windows', 'prioritize_critical'].includes(t)) return false
  if (!t || t === 'unknown') {
    const hasMaterial = rec?.entity_id && rec.entity_id !== 'unknown'
    const sel = rec?.selected_qty
    const q =
      sel != null && sel !== '' && Number(sel) > 0
        ? Number(sel)
        : Number(rec?.suggested_qty ?? 0)
    const hasTime = !!(rec?.selected_arrive_at || rec?.suggested_arrive_at)
    return hasMaterial && q > 0 && hasTime
  }
  return false
}

/**
 * Rows eligible for POST apply-replenishment: material replenish options only.
 */
export const isApplyReplenishmentSuggestion = (rec = {}) => {
  return isReplenishRecommendation(rec)
}

/**
 * Single suggestion item for apply-replenishment, or null if the row cannot be applied.
 */
export const mapRecommendationToApplyItem = (rec = {}) => {
  if (!isApplyReplenishmentSuggestion(rec)) return null
  const sel = rec?.selected_qty
  const qty =
    sel != null && sel !== '' && Number(sel) > 0
      ? Number(sel)
      : Number(rec?.suggested_qty ?? 0)
  const arriveAt = rec?.selected_arrive_at || rec?.suggested_arrive_at
  if (!(qty > 0) || !arriveAt || !rec?.entity_id) return null
  const payload = {
    material_id: rec.entity_id,
    quantity: qty,
    arrive_at: arriveAt,
  }
  if (rec?.snapshot) payload.inventory_snapshot = rec.snapshot
  return payload
}

const totalSkippedApplyDuplicates = (d = {}) => Number(d.skipped_duplicates ?? 0)

/** Backend treats arrivals in the same ±30m window as duplicates; stagger retries past that window. */
export const APPLY_REPLENISHMENT_DUPLICATE_WINDOW_NUDGE_MS = 31 * 60 * 1000

export const applyReplenishmentDuplicateSkipTotal = (d) => totalSkippedApplyDuplicates(d ?? {})

export const nudgeApplyReplenishmentSuggestionsArriveAt = (suggestions, deltaMs) =>
  (suggestions || []).map((s) => {
    const t = s?.arrive_at ? new Date(s.arrive_at).getTime() : NaN
    if (!Number.isFinite(t)) return s
    return { ...s, arrive_at: new Date(t + deltaMs).toISOString() }
  })

const pickList = (obj, keys) => {
  if (!obj) return []
  for (const k of keys) {
    const v = obj[k]
    if (Array.isArray(v) && v.length > 0) return v
  }
  return []
}

/**
 * Batch-level shortage aggregate from reschedule / batch-proposals (preferred source for bulk apply).
 * Per-job shortage_resolutions stay for drill-down only.
 */
export const extractBatchShortageAggregate = (src) => {
  if (!src || typeof src !== 'object') {
    return { byMaterial: [], byProduct: [], anchorProposalId: null }
  }
  const nested = src.batch_shortage || src.batchShortage || src.shortage_aggregate || src.shortageAggregate
  /** Preferred: batch proposals / reschedule-all `summary.material_replenishment_aggregate` (one row per raw material). */
  let byMaterial = pickList(src, ['material_replenishment_aggregate', 'materialReplenishmentAggregate'])
  if (!byMaterial.length) byMaterial = pickList(src, ['by_material', 'byMaterial'])
  if (!byMaterial.length && nested) byMaterial = pickList(nested, ['material_replenishment_aggregate', 'materialReplenishmentAggregate'])
  if (!byMaterial.length && nested) byMaterial = pickList(nested, ['by_material', 'byMaterial'])
  const anchorProposalId =
    pick(src, [
      'aggregate_anchor_proposal_id',
      'aggregateAnchorProposalId',
      'apply_anchor_proposal_id',
      'applyAnchorProposalId',
    ]) ||
    (nested &&
      pick(nested, ['aggregate_anchor_proposal_id', 'aggregateAnchorProposalId', 'apply_anchor_proposal_id'])) ||
    null
  return { byMaterial, byProduct: [], anchorProposalId }
}

/**
 * Normalized material lines for UI + apply from aggregate arrays.
 */
export const normalizeBatchAggregateLines = (byMaterial = [], byProduct = []) => {
  const lines = []
    ; (Array.isArray(byMaterial) ? byMaterial : []).forEach((row, idx) => {
      const material_id = pick(row, ['material_id', 'materialId', 'MaterialID'])
      const material_name = pick(row, ['material_name', 'materialName', 'MaterialName'])
      const q = Number(
        pick(row, ['recommended_qty', 'recommendedQty', 'quantity', 'qty', 'suggested_qty'], 0),
      )
      const arrive_at =
        pick(row, [
          'suggested_arrive_at',
          'suggestedArriveAt',
          'recommended_arrive_at',
          'recommendedArriveAt',
          'arrive_at',
        ]) || null
      const earliest_possible_arrival = pick(row, ['earliest_possible_arrival', 'earliestPossibleArrival'])
      if (!material_id || !(q > 0) || !arrive_at) return
      const snap = row.inventory_snapshot || row.inventorySnapshot
      const rawOpt = String(pick(row, ['option_type', 'optionType'], '')).trim().toLowerCase()
      if (rawOpt === 'schedule_production') return
      lines.push({
        key: `agg:m:${material_id}:${idx}`,
        kind: 'material',
        id: material_id,
        label: material_name || material_id,
        material_id,
        material_name,
        qty: q,
        arrive_at,
        earliest_possible_arrival,
        affected_job_ids: Array.isArray(row.affected_job_ids)
          ? row.affected_job_ids
          : Array.isArray(row.affectedJobIds)
            ? row.affectedJobIds
            : [],
        rationale: pick(row, ['rationale', 'Rationale', 'notes'], '') || '',
        snapshot: snap || null,
        selected: true,
        source: 'recommendation',
        raw: row,
      })
    })
  return lines
}

/** Build apply-replenishment `suggestions` from aggregate lines + per-line drafts (arriveAtLocal like ShortageResolution). */
export const buildAggregateApplySuggestions = (lines, draftsByKey = {}) => {
  const out = []
  for (const line of lines || []) {
    const d = draftsByKey[line.key]
    const selected = d?.selected !== undefined ? d.selected !== false : line.selected !== false
    if (!selected) continue
    const qtyRaw = d && d.qty !== undefined && d.qty !== '' ? Number(d.qty) : line.qty
    const qty = Number.isFinite(qtyRaw) && qtyRaw > 0 ? qtyRaw : line.qty
    let arriveIso = line.arrive_at
    if (d?.arriveAtLocal) {
      const t = new Date(d.arriveAtLocal).getTime()
      if (Number.isFinite(t)) arriveIso = new Date(t).toISOString()
    }
    if (!(qty > 0) || !arriveIso) continue
    const row = {
      material_id: line.material_id || line.id,
      quantity: qty,
      arrive_at: arriveIso,
    }
    if (line.snapshot) row.inventory_snapshot = line.snapshot
    out.push(row)
  }
  return out
}

const legacyApplyCreatedCount = (d = {}) =>
  (Array.isArray(d.created_arrivals) ? d.created_arrivals.length : 0) +
  (Number(d.created_count) || 0)

/**
 * Maps apply-replenishment JSON to a single UI notice. Warn only when the request had no valid rows
 * or (legacy) the server reported nothing new with no duplicate/coverage signal.
 * @returns {{ level: 'info' | 'warn', text: string } | null}
 */
export const applyReplenishmentClientNotice = (data) => {
  const d = data || {}
  const validRaw = d.input_suggestion_rows_valid
  const validN = validRaw === undefined || validRaw === null ? null : Number(validRaw)
  const msgIn = typeof d.apply_message === 'string' ? d.apply_message.trim() : ''
  const skippedDup = totalSkippedApplyDuplicates(d)

  if (validN === 0) {
    return {
      level: 'warn',
      text: msgIn || 'No valid suggestion rows in the apply request.',
    }
  }

  if (d.any_new_records === true) {
    if (msgIn && /new_expected_arrivals/i.test(msgIn)) return null
    return msgIn ? { level: 'info', text: msgIn } : null
  }

  if (d.any_new_records === false) {
    const dupish =
      skippedDup > 0 ||
      /duplicate|already covered|already\s+matched|within\s+.{0,40}window/i.test(msgIn)
    if (dupish) {
      return {
        level: 'warn',
        text:
          msgIn ||
          'Nothing new created; quantity is already covered within the duplicate-detection window.',
      }
    }
    if (validN != null && validN > 0) return null
    if (msgIn) return { level: 'info', text: msgIn }
  }

  const legacy = legacyApplyCreatedCount(d)
  if (legacy > 0) return null

  if (skippedDup > 0) {
    return {
      level: 'warn',
      text:
        msgIn ||
        'Duplicates skipped; coverage likely already matches within the window.',
    }
  }

  if (validN != null && validN > 0) return null

  if (validN === null && legacy === 0) {
    return {
      level: 'warn',
      text:
        msgIn ||
        'Apply-replenishment did not report new arrivals.',
    }
  }

  return null
}

export const normalizeRecommendation = (resolution = {}, source = 'primary') => {
  const replenishment = resolution?.replenishment || {}
  const qty = Number(
    replenishment?.suggested_qty ??
    replenishment?.suggested_quantity ??
    replenishment?.quantity ??
    replenishment?.qty ??
    resolution?.suggested_qty ??
    resolution?.quantity ??
    0
  )
  const suggestedAt =
    replenishment?.suggested_arrive_at ||
    replenishment?.arrive_at ||
    replenishment?.expected_arrival ||
    replenishment?.earliest_possible_arrival ||
    resolution?.suggested_arrive_at ||
    resolution?.arrive_at ||
    resolution?.earliest_possible_arrival ||
    null
  return {
    source,
    entity_id: normalizeShortageEntityId(resolution) || 'unknown',
    /** When set, material replenish supports this subproduct / dependent product (BOM context). */
    dependency_product_id: resolution?.dependency_product_id ?? null,
    option_type: canonicalizeOptionType(resolution),
    suggested_qty: Number.isFinite(qty) && qty > 0 ? qty : 0,
    suggested_arrive_at: suggestedAt,
    earliest_possible_arrival:
      replenishment?.earliest_possible_arrival || resolution?.earliest_possible_arrival || null,
    rationale: resolution?.rationale || resolution?.description || replenishment?.notes || '',
    snapshot: replenishment?.inventory_snapshot || resolution?.snapshot || null,
    replenishment,
    raw: resolution,
  }
}

export const aggregateMaterialShortageRowsFromProposals = (proposals = []) => {
  const perProposalMaterial = new Map()

  for (const proposal of Array.isArray(proposals) ? proposals : []) {
    const primary = Array.isArray(proposal?.shortage_resolutions)
      ? proposal.shortage_resolutions
      : Array.isArray(proposal?.shortageResolutions)
        ? proposal.shortageResolutions
        : []
    const materialShortages = Array.isArray(proposal?.material_shortages)
      ? proposal.material_shortages
      : Array.isArray(proposal?.materialShortages)
        ? proposal.materialShortages
        : []
    const fallback = materialShortages.flatMap((s) => {
      if (Array.isArray(s?.per_material_resolutions)) return s.per_material_resolutions
      if (Array.isArray(s?.perMaterialResolutions)) return s.perMaterialResolutions
      return []
    })
    const rows = [
      ...primary.map((row) => normalizeRecommendation(row, 'shortage_resolutions')),
      ...fallback.map((row) => normalizeRecommendation(row, 'per_material_resolutions')),
    ]

    for (const rec of rows) {
      if (!isApplyReplenishmentSuggestion(rec)) continue
      const materialId = String(rec.entity_id || '').trim()
      const qty = Number(rec.suggested_qty ?? 0)
      const arriveAt = rec.suggested_arrive_at
      if (!materialId || materialId === 'unknown' || !(qty > 0) || !arriveAt) continue

      const proposalKey = proposal?.proposal_id || proposal?.proposalId || proposal?.job_id || proposal?.jobId || ''
      const key = `${proposalKey}|${materialId}`
      const current = perProposalMaterial.get(key)
      const currentAt = current?.rec?.suggested_arrive_at ? new Date(current.rec.suggested_arrive_at).getTime() : NaN
      const nextAt = new Date(arriveAt).getTime()
      if (
        !current ||
        qty > current.qty ||
        (qty === current.qty && Number.isFinite(nextAt) && (!Number.isFinite(currentAt) || nextAt < currentAt))
      ) {
        perProposalMaterial.set(key, { proposal, rec, qty })
      }
    }
  }

  const byMaterial = new Map()
  const appendUnique = (list, value) => {
    const text = String(value || '').trim()
    if (text && !list.includes(text)) list.push(text)
  }

  for (const { proposal, rec, qty } of perProposalMaterial.values()) {
    const materialId = String(rec.entity_id || '').trim()
    const arriveAt = rec.suggested_arrive_at
    const replenishment = rec.replenishment || {}
    const existing = byMaterial.get(materialId) || {
      material_id: materialId,
      material_name:
        replenishment.material_name ||
        replenishment.materialName ||
        rec.raw?.material_name ||
        rec.raw?.materialName ||
        materialId,
      recommended_qty: 0,
      suggested_arrive_at: arriveAt,
      earliest_possible_arrival: rec.earliest_possible_arrival || arriveAt,
      affected_job_ids: [],
      option_type: 'replenish',
      rationale: rec.dependency_product_id
        ? 'Batch raw-material recommendation for subproduct manufacture.'
        : 'Batch material recommendation from proposal shortage resolutions.',
    }

    existing.recommended_qty = Number((Number(existing.recommended_qty || 0) + qty).toFixed(6))
    const existingAt = existing.suggested_arrive_at ? new Date(existing.suggested_arrive_at).getTime() : NaN
    const nextAt = arriveAt ? new Date(arriveAt).getTime() : NaN
    if (Number.isFinite(nextAt) && (!Number.isFinite(existingAt) || nextAt < existingAt)) {
      existing.suggested_arrive_at = arriveAt
    }
    const earliest = rec.earliest_possible_arrival || arriveAt
    const existingEarliest = existing.earliest_possible_arrival ? new Date(existing.earliest_possible_arrival).getTime() : NaN
    const nextEarliest = earliest ? new Date(earliest).getTime() : NaN
    if (Number.isFinite(nextEarliest) && (!Number.isFinite(existingEarliest) || nextEarliest < existingEarliest)) {
      existing.earliest_possible_arrival = earliest
    }
    appendUnique(existing.affected_job_ids, proposal?.job_id || proposal?.jobId)
    ; (Array.isArray(rec.raw?.affected_job_ids)
      ? rec.raw.affected_job_ids
      : Array.isArray(rec.raw?.affectedJobIds)
        ? rec.raw.affectedJobIds
        : []
    ).forEach((jobId) => appendUnique(existing.affected_job_ids, jobId))
    byMaterial.set(materialId, existing)
  }

  return [...byMaterial.values()].sort((a, b) => String(a.material_id).localeCompare(String(b.material_id)))
}

export const buildApplyPayload = (selectedRecommendations = []) =>
  selectedRecommendations.map(mapRecommendationToApplyItem).filter(Boolean)
