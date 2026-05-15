import { useEffect, useMemo, useState } from 'react'
import { factoryAgentApi } from '../../../../services/factoryAgentApi'
import { isInterruptBundleApprovalText, shortenApprovalRiskSummary } from './approvalInterruptDisplay.js'
import { castApprovalFieldValue } from './approvalFieldUtils.js'
import {
 buildOptionsFromRows,
 dedupeOptions,
 loadRowsByEndpoint,
 pickLookupEndpoints,
 shouldUseDynamicOptions,
} from './approvalLookupUtils.js'

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
 const rows = await factoryAgentApi.listTools({ max_tools: 100 })
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
 const casted = castApprovalFieldValue(raw, field)
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
