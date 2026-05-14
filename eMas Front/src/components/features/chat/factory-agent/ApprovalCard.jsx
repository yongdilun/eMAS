import { useEffect, useMemo, useState } from 'react'
import { factoryAgentApi } from '../../../../services/factoryAgentApi'
import { toList } from '../../../../services/api'
import { isInterruptBundleApprovalText, shortenApprovalRiskSummary } from './approvalInterruptDisplay.js'

const levelStyles = {
 NONE: 'bg-primary/10 text-primary',
 LOW: 'bg-primary/10 text-primary',
 MEDIUM: 'bg-surface-3 text-ink-muted',
 HIGH: 'bg-surface-3 text-ink-muted',
 CRITICAL: 'bg-inverse-canvas text-inverse-ink',
}

function normalizeArgs(args) {
 if (!args || typeof args !== 'object' || Array.isArray(args)) return {}
 return args
}

function humanizeFieldName(name) {
 return String(name || 'field')
 .replace(/\{.*?\}/g, '')
 .replace(/[_-]+/g, ' ')
 .replace(/\bid\b/gi, 'ID')
 .replace(/\s+/g, ' ')
 .trim()
}

function resolveSchemaType(schema = {}) {
 const type = schema?.type
 if (Array.isArray(type)) {
 const nonNull = type.find((item) => item !== 'null')
 return nonNull || 'string'
 }
 return type || 'string'
}

function getTemporalInputType(schema = {}, fieldName = '') {
 const lowerFormat = String(schema?.format || '').toLowerCase()
 if (lowerFormat === 'date') return 'date'
 if (lowerFormat === 'time') return 'time'
 if (lowerFormat === 'date-time' || lowerFormat === 'datetime') return 'datetime-local'

 const key = String(fieldName || '').toLowerCase()
 if (/(^|_)(datetime|timestamp|created_at|updated_at|started_at|ended_at|scheduled_at|actual_start|actual_end)$/.test(key)) {
 return 'datetime-local'
 }
 if (/(^|_)(date|deadline)$/.test(key) || key.endsWith('_date')) {
 return 'date'
 }
 if (/(^|_)(time)$/.test(key) || key.endsWith('_time')) {
 return 'time'
 }
 return null
}

function toDatetimeLocalString(rawValue) {
 if (rawValue == null || rawValue === '') return ''
 const value = String(rawValue)
 if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value)) return value.slice(0, 16)
 const d = new Date(value)
 if (Number.isNaN(d.getTime())) return value
 const pad = (n) => String(n).padStart(2, '0')
 return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function shouldUseDynamicOptions(fieldName, schemaType, enumOptions) {
 if (schemaType !== 'string') return false
 if (enumOptions && enumOptions.length > 0) return false
 return true
}

function isIdLikeField(fieldName = '') {
 return String(fieldName || '').toLowerCase().endsWith('_id')
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

 // Strong boost for canonical resource collection endpoints (e.g., /products for product_id)
 if (fieldTokens.length > 0) {
 const primary = fieldTokens[0]
 const canonical = `${primary}s`
 if (endpointLast === canonical || endpointLast === primary) score += 5
 }

 const blacklist = ['approval', 'metrics', 'health', 'debug', 'session', 'plan', 'chat']
 if (blacklist.some((token) => endpointTokens.has(token))) score -= 3
 return score
}

function pickLookupEndpoints(fieldName, tools = []) {
 const candidates = []
 for (const tool of tools) {
 if (!isListLookupTool(tool)) continue
 const score = scoreLookupToolForField(fieldName, tool)
 if (score >= 2) candidates.push({ endpoint: String(tool.endpoint || ''), score })
 }
 candidates.sort((a, b) => b.score - a.score || a.endpoint.localeCompare(b.endpoint))
 return candidates.map((c) => c.endpoint)
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
 const label = pick(labelCandidates) || value
 if (!value) return null
 const valueKey = (valueCandidates.map((key) => resolveActualKey(key)).find((k) => k && item[k] != null && item[k] !== '') || '').toLowerCase()
 const labelKey = (labelCandidates.map((key) => resolveActualKey(key)).find((k) => k && item[k] != null && item[k] !== '') || '').toLowerCase()
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

async function loadRowsByEndpoint(endpoint) {
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

function buildOptionsFromRows(rows, fieldName) {
 const stem = String(fieldName || '').toLowerCase().replace(/_id$/, '').replace(/_name$/, '')
 const options = rows.map((item) => normalizeOption(item, { fieldName, fallbackStem: stem })).filter(Boolean)
 return { options: dedupeOptions(options), score: scoreEndpointOptions(fieldName, options) }
}

function dedupeOptions(options = []) {
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

function castFieldValue(rawValue, field) {
 const schemaType = field?.type || 'string'
 if (rawValue === undefined || rawValue === null || rawValue === '') return undefined
 if (schemaType === 'integer') {
 const parsed = Number.parseInt(String(rawValue), 10)
 return Number.isNaN(parsed) ? Number.NaN : parsed
 }
 if (schemaType === 'number') {
 const parsed = Number.parseFloat(String(rawValue))
 return Number.isNaN(parsed) ? Number.NaN : parsed
 }
 if (schemaType === 'boolean') {
 if (rawValue === true || rawValue === false) return rawValue
 if (String(rawValue).toLowerCase() === 'true') return true
 if (String(rawValue).toLowerCase() === 'false') return false
 return undefined
 }
 if (schemaType === 'array' || schemaType === 'object') {
 if (typeof rawValue !== 'string') return rawValue
 try {
 return JSON.parse(rawValue)
 } catch {
 return Number.NaN
 }
 }
 if (field?.inputType === 'datetime-local') {
 const d = new Date(String(rawValue))
 if (Number.isNaN(d.getTime())) return Number.NaN
 return d.toISOString()
 }
 return String(rawValue)
}

const ApprovalCard = ({ approval, mode = 'user', reason, onReasonChange, onApprove, onReject, deciding }) => {
 const safeApproval = approval || {}

 const level = safeApproval.side_effect_level || 'HIGH'
 const badgeClass = levelStyles[level] || levelStyles.HIGH
 const isPlanApproval = safeApproval.subject_type === 'plan'
 const isDevMode = mode === 'dev'
 const [tools, setTools] = useState([])
 const [formValues, setFormValues] = useState(() => normalizeArgs(safeApproval.args))
 const [dynamicOptionsByField, setDynamicOptionsByField] = useState({})
 const [showValidationErrors, setShowValidationErrors] = useState(false)

 useEffect(() => {
 // Keep user edits stable while this same approval stays open.
 setFormValues(normalizeArgs(safeApproval.args))
 setShowValidationErrors(false)
 }, [safeApproval?.approval_id])

 useEffect(() => {
 let cancelled = false
 const loadTools = async () => {
 try {
 const rows = await factoryAgentApi.listTools({ max_tools: 200 })
 if (!cancelled) setTools(Array.isArray(rows) ? rows : [])
 } catch {
 if (!cancelled) setTools([])
 }
 }
 loadTools()
 return () => {
 cancelled = true
 }
 }, [])

 const tool = useMemo(() => (tools || []).find((t) => t?.name === safeApproval.tool_name) || null, [tools, safeApproval?.tool_name])
 const schema = useMemo(() => tool?.input_schema || {}, [tool?.input_schema])
 const required = useMemo(() => {
 const req = tool?.input_schema?.required
 return Array.isArray(req) ? req : []
 }, [tool?.input_schema?.required])

 const fields = useMemo(() => {
 const properties = schema?.properties || {}
 const names = Object.keys(properties)
 const requiredSet = new Set(required)
 names.sort((a, b) => {
 const aReq = requiredSet.has(a) ? 0 : 1
 const bReq = requiredSet.has(b) ? 0 : 1
 if (aReq !== bReq) return aReq - bReq
 return a.localeCompare(b)
 })
 return names.map((name) => {
 const fieldSchema = properties[name] || {}
 const type = resolveSchemaType(fieldSchema)
 const enumOptions = Array.isArray(fieldSchema.enum) ? fieldSchema.enum : null
 const temporalType = getTemporalInputType(fieldSchema, name)
 const sourceEndpoints = shouldUseDynamicOptions(name, type, enumOptions)
 ? pickLookupEndpoints(name, tools)
 : []
 return {
 name,
 schema: fieldSchema,
 type,
 required: requiredSet.has(name),
 enumOptions,
 inputType: temporalType,
 sourceEndpoints,
 }
 })
 }, [required, schema, tools])

 useEffect(() => {
 let cancelled = false
 const candidates = fields.filter((f) => Array.isArray(f.sourceEndpoints) && f.sourceEndpoints.length > 0)
 if (candidates.length === 0) {
 setDynamicOptionsByField({})
 return () => {
 cancelled = true
 }
 }

 const hydrateFieldOptions = async () => {
 const endpointCache = {}
 const getRows = (endpoint) => {
 if (!endpointCache[endpoint]) endpointCache[endpoint] = loadRowsByEndpoint(endpoint)
 return endpointCache[endpoint]
 }
 const entries = await Promise.all(
 candidates.map(async (field) => {
 try {
 let best = []
 let bestScore = -1000
 for (const endpoint of field.sourceEndpoints.slice(0, 8)) {
 const rows = await getRows(endpoint)
 const shaped = buildOptionsFromRows(rows, field.name)
 const lexicalBias = Math.max(0, 8 - field.sourceEndpoints.indexOf(endpoint)) * 0.1
 const finalScore = shaped.score + lexicalBias
 if (shaped.options.length > 0 && finalScore > bestScore) {
 best = shaped.options
 bestScore = finalScore
 }
 }
 return [field.name, best]
 } catch {
 return [field.name, []]
 }
 }),
 )
 if (!cancelled) {
 setDynamicOptionsByField(Object.fromEntries(entries))
 }
 }
 hydrateFieldOptions()

 return () => {
 cancelled = true
 }
 }, [fields])

 const displayRiskSummary = useMemo(() => {
 const raw = safeApproval.risk_summary || ''
 if (!raw.trim()) return 'No risk summary provided.'
 if (isInterruptBundleApprovalText(raw)) return shortenApprovalRiskSummary(raw) || raw.trim()
 return raw
 }, [safeApproval.risk_summary])

 const resolved = useMemo(() => {
 const baseArgs = normalizeArgs(safeApproval.args)
 const unknownArgs = { ...baseArgs }
 for (const f of fields) delete unknownArgs[f.name]

 const nextArgs = { ...unknownArgs }
 const errors = []

 for (const field of fields) {
 const raw = formValues[field.name]
 const casted = castFieldValue(raw, field)
 if (field.required && (casted === undefined || casted === null || casted === '')) {
 errors.push(`${humanizeFieldName(field.name)} is required`)
 continue
 }
 if (Number.isNaN(casted)) {
 errors.push(`${humanizeFieldName(field.name)} has invalid value`)
 continue
 }
 if (casted !== undefined) {
 nextArgs[field.name] = casted
 }
 }
 return { args: nextArgs, errors }
 }, [fields, formValues, safeApproval.args])

 const handleApprove = () => {
 if (resolved.errors.length > 0) {
 setShowValidationErrors(true)
 return
 }
 setShowValidationErrors(false)
 onApprove(resolved.args || undefined)
 }

 if (!approval) return null

 return (
 <div className="mt-3 rounded-lg border border-hairline bg-surface-1 p-4">
 <div className="flex items-center justify-between gap-3">
 <h3 className="text-sm font-semibold text-ink">{isPlanApproval ? 'Plan approval required' : 'Approval required'}</h3>
 <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${badgeClass}`}>
 {level}
 </span>
 </div>

 <div className="mt-2 text-xs text-ink-muted">
 {isDevMode ? (
 <div><span className="font-semibold">{isPlanApproval ? 'Plan' : 'Tool'}:</span> {isPlanApproval ? (safeApproval.plan_id || 'Execution proposal') : safeApproval.tool_name}</div>
 ) : (
 <div><span className="font-semibold">Action:</span> {isPlanApproval ? 'Review execution proposal' : 'Review proposed factory action'}</div>
 )}
 <div className="mt-1"><span className="font-semibold">Risk:</span> {displayRiskSummary}</div>
 </div>

 {required.length > 0 ? (
 <div className="mt-2 text-[11px] text-ink-muted">
 <span className="font-semibold">{isDevMode ? 'Required fields' : 'Required information'}:</span>{' '}
 {required.map((k) => (
 <span
 key={k}
 className={`inline-flex items-center px-1.5 py-0.5 rounded mr-1 mt-1 ${
 resolved.args && resolved.args[k] != null && resolved.args[k] !== ''
 ? 'bg-primary/10 text-primary'
 : 'bg-surface-3 text-ink-subtle'
 }`}
 >
 {isDevMode ? k : humanizeFieldName(k)}
 </span>
 ))}
 </div>
 ) : null}

 <div className="mt-3 space-y-2">
 <div className="text-xs font-semibold text-ink-muted">Review and edit request</div>
 {fields.map((field) => {
 const value = formValues[field.name]
 const id = `approval-${safeApproval.approval_id}-${field.name}`
 const dynamicOptions = Array.isArray(dynamicOptionsByField[field.name]) ? dynamicOptionsByField[field.name] : []
 const enumOptions = (field.enumOptions || []).map((opt) => ({ value: String(opt), label: String(opt) }))
 const hasSelectSource = enumOptions.length > 0 || dynamicOptions.length > 0
 const baseSelectOptions = dedupeOptions([...enumOptions, ...dynamicOptions])
 const selectedInOptions = baseSelectOptions.some((opt) => opt.value === String(value ?? ''))
 const valueOption =
 hasSelectSource && !selectedInOptions && value != null && value !== ''
 ? [{ value: String(value), label: String(value) }]
 : []
 const allSelectOptions = dedupeOptions([...baseSelectOptions, ...valueOption])
 const common = {
 id,
 className: 'mt-1 w-full rounded-md border border-hairline bg-surface-2 px-3 py-2 text-xs text-ink outline-none focus:border-primary focus:ring-2 focus:ring-primary/30',
 }

 return (
 <label key={field.name} htmlFor={id} className="block">
 <span className="text-[11px] text-ink-subtle">
 {isDevMode ? field.name : humanizeFieldName(field.name)}{field.required ? ' *' : ''}
 </span>
 {hasSelectSource && allSelectOptions.length > 0 ? (
 <select
 {...common}
 value={value == null ? '' : String(value)}
 onChange={(e) => setFormValues((prev) => ({ ...prev, [field.name]: e.target.value }))}
 >
 <option value="">Select...</option>
 {allSelectOptions.map((opt) => (
 <option key={`${field.name}-${opt.value}`} value={opt.value}>
 {opt.label}
 </option>
 ))}
 </select>
 ) : field.type === 'boolean' ? (
 <select
 {...common}
 value={value == null ? '' : String(value)}
 onChange={(e) => setFormValues((prev) => ({ ...prev, [field.name]: e.target.value }))}
 >
 <option value="">Select...</option>
 <option value="true">true</option>
 <option value="false">false</option>
 </select>
 ) : field.type === 'array' || field.type === 'object' ? (
 <textarea
 {...common}
 rows={3}
 value={typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value, null, 2)}
 onChange={(e) => setFormValues((prev) => ({ ...prev, [field.name]: e.target.value }))}
 placeholder={isDevMode ? `Enter ${field.type} as JSON` : 'Enter details'}
 />
 ) : (
 <input
 {...common}
 type={field.inputType || (field.type === 'integer' || field.type === 'number' ? 'number' : 'text')}
 value={
 value == null
 ? ''
 : field.inputType === 'datetime-local'
 ? toDatetimeLocalString(value)
 : String(value)
 }
 step={field.type === 'integer' ? 1 : field.type === 'number' ? 'any' : undefined}
 onChange={(e) => setFormValues((prev) => ({ ...prev, [field.name]: e.target.value }))}
 />
 )}
 </label>
 )
 })}
 {showValidationErrors && resolved.errors.length > 0 ? (
 <div className="rounded-md border border-hairline bg-surface-2 px-3 py-2 text-[11px] text-ink-muted">
 {resolved.errors.join(' | ')}
 </div>
 ) : null}
 </div>

 <textarea
 value={reason}
 onChange={(e) => onReasonChange(e.target.value)}
 placeholder="Optional rejection reason"
 className="mt-3 w-full rounded-md border border-hairline bg-surface-2 px-3 py-2 text-xs text-ink outline-none placeholder:text-ink-tertiary focus:border-primary focus:ring-2 focus:ring-primary/30"
 rows={2}
 />

 <div className="mt-3 flex items-center gap-2">
 <button
 type="button"
 disabled={deciding}
 aria-busy={deciding ? 'true' : 'false'}
 onClick={handleApprove}
 className="inline-flex min-w-[7.5rem] items-center justify-center gap-2 px-3 py-1.5 rounded-md text-xs font-semibold bg-primary text-white hover:bg-primary-hover disabled:opacity-70"
 >
 {deciding ? (
 <>
 <span
 className="inline-block h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-white/35 border-t-white"
 aria-hidden
 />
 <span>Approving...</span>
 </>
 ) : (
 'Approve'
 )}
 </button>
 <button
 type="button"
 disabled={deciding}
 onClick={onReject}
 className="px-3 py-1.5 rounded-md text-xs font-semibold bg-inverse-canvas text-inverse-ink hover:opacity-90 disabled:opacity-60"
 >
 Reject
 </button>
 </div>
 </div>
 )
}

export default ApprovalCard
