import { toList } from '../../../../services/api'

export function shouldUseDynamicOptions(fieldName, schemaType, enumOptions) {
  if (schemaType !== 'string') return false
  if (enumOptions && enumOptions.length > 0) return false
  return true
}

function isIdLikeField(fieldName = '') {
  return String(fieldName || '').toLowerCase().endsWith('_id')
}

const preferredLookupEndpointsByField = {
  product_id: ['/products'],
  machine_id: ['/machines'],
  material_id: ['/materials'],
  inventory_id: ['/inventory'],
  job_id: ['/jobs'],
}

function tokenize(value = '') {
  return String(value || '')
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean)
}

function singularize(token) {
  if (token.endsWith('ies')) return `${token.slice(0, -3)}y`
  if (token.endsWith('s') && token.length > 3) return token.slice(0, -1)
  return token
}

function isListLookupTool(tool) {
  if (!tool || String(tool.method || '').toUpperCase() !== 'GET') return false
  const endpoint = String(tool.endpoint || '')
  if (!endpoint || endpoint.includes('{')) return false
  return true
}

function scoreLookupToolForField(fieldName, tool) {
  const endpoint = String(tool?.endpoint || '').toLowerCase()
  const endpointTrimmed = endpoint.replace(/\/+$/, '')
  const endpointParts = endpointTrimmed.split('/').filter(Boolean)
  const endpointLast = endpointParts[endpointParts.length - 1] || ''
  const endpointTokens = new Set(tokenize(endpoint).map(singularize))
  const fieldTokensRaw = tokenize(fieldName)
  const fieldTokens = fieldTokensRaw
    .map((token) => token.replace(/^x$/, ''))
    .filter(Boolean)
    .map(singularize)
    .filter((token) => token !== 'id' && token !== 'name')

  if (fieldTokens.length === 0) return -1

  let score = 0
  for (const token of fieldTokens) {
    if (endpointTokens.has(token)) score += 3
  }

  const isIdField = isIdLikeField(fieldName)
  if (isIdField && fieldTokens.some((token) => endpoint.includes(`/${token}`))) score += 2
  if (endpoint.includes('/reference/')) score += 1

  if (fieldTokens.length > 0) {
    const primary = fieldTokens[0]
    const canonical = `${primary}s`
    if (endpointLast === canonical || endpointLast === primary) score += 5
    if (isIdField && endpoint.includes('/reference/') && endpointLast !== canonical && endpointLast !== primary) {
      score -= 8
    }
  }

  const blacklist = ['approval', 'metrics', 'health', 'debug', 'session', 'plan', 'chat']
  if (blacklist.some((token) => endpointTokens.has(token))) score -= 3
  return score
}

export function pickLookupEndpoints(fieldName, tools = []) {
  const preferred = preferredLookupEndpointsByField[String(fieldName || '').toLowerCase()] || []
  const candidates = []
  for (const tool of tools) {
    if (!isListLookupTool(tool)) continue
    const score = scoreLookupToolForField(fieldName, tool)
    if (score >= 2) candidates.push({ endpoint: String(tool.endpoint || ''), score })
  }
  candidates.sort((a, b) => b.score - a.score || a.endpoint.localeCompare(b.endpoint))
  return dedupeEndpoints([...preferred, ...candidates.map((c) => c.endpoint)])
}

function dedupeEndpoints(endpoints = []) {
  const seen = new Set()
  const out = []
  for (const endpoint of endpoints) {
    const value = String(endpoint || '').trim()
    if (!value || seen.has(value)) continue
    seen.add(value)
    out.push(value)
  }
  return out
}

function normalizeOption(item, { fieldName = '', valueKeys = [], labelKeys = [], fallbackStem = '' } = {}) {
  if (typeof item === 'string' || typeof item === 'number') {
    const s = String(item)
    return { value: s, label: s, valueKey: '__primitive__', labelKey: '__primitive__' }
  }
  if (!item || typeof item !== 'object') return null

  const normalizeKeyToken = (value) => String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '')
  const exactKeys = new Map(Object.keys(item).map((k) => [k.toLowerCase(), k]))
  const normalizedKeys = new Map(Object.keys(item).map((k) => [normalizeKeyToken(k), k]))

  const resolveActualKey = (candidate) => {
    const direct = exactKeys.get(String(candidate).toLowerCase())
    if (direct) return direct
    return normalizedKeys.get(normalizeKeyToken(candidate)) || null
  }

  const pick = (keys) => {
    for (const key of keys) {
      const actualKey = resolveActualKey(key)
      if (!actualKey) continue
      const val = item[actualKey]
      if (val != null && val !== '') return String(val)
    }
    return ''
  }

  const stem = singularize(String(fallbackStem || '').toLowerCase())
  const field = String(fieldName || '').toLowerCase()
  const valueCandidates = isIdLikeField(field)
    ? [field, `${stem}_id`, ...valueKeys, 'id', 'uuid', 'key', 'code']
    : [`${stem}_id`, ...valueKeys, 'id', 'value', 'code', 'uuid', 'key', 'name']

  const labelCandidates = [`${stem}_name`, ...labelKeys, 'display', 'name', 'title', 'label', 'description', 'id', 'value']
  const value = pick(valueCandidates)
  let label = pick(labelCandidates) || value
  if (!value) return null
  const valueKey = (valueCandidates.map((key) => resolveActualKey(key)).find((k) => k && item[k] != null && item[k] !== '') || '').toLowerCase()
  const labelKey = (labelCandidates.map((key) => resolveActualKey(key)).find((k) => k && item[k] != null && item[k] !== '') || '').toLowerCase()
  if (isIdLikeField(fieldName) && label && label !== value && !label.includes(value)) {
    label = `${label} (${value})`
  }
  return { value, label, valueKey, labelKey }
}

function buildApiUrl(endpoint) {
  const base = (import.meta.env?.VITE_API_BASE_URL || 'http://localhost:8080/api/v1').replace(/\/+$/, '')
  const normalized = String(endpoint || '')
  if (!normalized) return null
  if (normalized.startsWith('http://') || normalized.startsWith('https://')) return normalized
  if (normalized.startsWith('/api/v1/')) return `${base}${normalized.slice('/api/v1'.length)}`
  if (normalized.startsWith('/')) return `${base}${normalized}`
  return `${base}/${normalized}`
}

export async function loadRowsByEndpoint(endpoint) {
  const url = buildApiUrl(endpoint)
  if (!url) return []
  const response = await fetch(url, { method: 'GET' })
  if (!response.ok) return []
  const raw = await response.json()
  return toList(raw)
}

function scoreEndpointOptions(fieldName, options = []) {
  if (!Array.isArray(options) || options.length === 0) return -1000
  const stem = String(fieldName || '').toLowerCase().replace(/_id$/, '').replace(/_name$/, '')
  const exactIdKey = `${stem}_id`
  const isIdField = isIdLikeField(fieldName)
  const normalizeKeyToken = (value) => String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '')
  const normalizedFieldName = normalizeKeyToken(fieldName)
  const normalizedExactIdKey = normalizeKeyToken(exactIdKey)

  let score = Math.min(options.length, 50)
  for (const option of options) {
    const valueKey = String(option?.valueKey || '').toLowerCase()
    const labelKey = String(option?.labelKey || '').toLowerCase()
    const normalizedValueKey = normalizeKeyToken(valueKey)
    const normalizedLabelKey = normalizeKeyToken(labelKey)
    if (isIdField) {
      if (normalizedValueKey === normalizedFieldName) score += 8
      else if (normalizedValueKey === normalizedExactIdKey) score += 6
      else if (normalizedValueKey === 'id') score += 5
      else if (normalizedValueKey.endsWith('id')) score += 2
      else if (normalizedValueKey === 'uuid' || normalizedValueKey === 'key' || normalizedValueKey === 'code') score += 1
      else score -= 4
    } else {
      if (normalizedValueKey === normalizeKeyToken(`${stem}_name`) || normalizedValueKey === 'name' || normalizedValueKey === 'title') score += 2
      if (normalizedValueKey.endsWith('id')) score += 1
    }
    if (normalizedLabelKey.includes('name') || normalizedLabelKey === 'title' || normalizedLabelKey === 'display') score += 1
  }
  return score
}

export function buildOptionsFromRows(rows, fieldName) {
  const stem = String(fieldName || '').toLowerCase().replace(/_id$/, '').replace(/_name$/, '')
  const options = rows.map((item) => normalizeOption(item, { fieldName, fallbackStem: stem })).filter(Boolean)
  return { options: dedupeOptions(options), score: scoreEndpointOptions(fieldName, options) }
}

export function dedupeOptions(options = []) {
  const seen = new Set()
  const out = []
  for (const option of options) {
    const key = `${option?.value ?? ''}|${option?.label ?? ''}`
    if (!option?.value || seen.has(key)) continue
    seen.add(key)
    out.push(option)
  }
  return out
}
