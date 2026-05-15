export function castApprovalFieldValue(rawValue, field) {
  const schemaType = field?.type || 'string'
  if (rawValue === undefined || rawValue === null || rawValue === '') return undefined

  const text = String(rawValue).trim()

  if (schemaType === 'integer') {
    if (!/^[+-]?\d+$/.test(text)) return Number.NaN
    const parsed = Number(text)
    return Number.isSafeInteger(parsed) ? parsed : Number.NaN
  }

  if (schemaType === 'number') {
    if (!/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(text)) return Number.NaN
    const parsed = Number(text)
    return Number.isFinite(parsed) ? parsed : Number.NaN
  }

  if (schemaType === 'boolean') {
    if (rawValue === true || rawValue === false) return rawValue
    if (text.toLowerCase() === 'true') return true
    if (text.toLowerCase() === 'false') return false
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
    const d = new Date(text)
    if (Number.isNaN(d.getTime())) return Number.NaN
    return d.toISOString()
  }

  return String(rawValue)
}
