const EMPTY_VALUE = '-'
const MAX_OBJECT_SUMMARY_LENGTH = 180

function stableStringify(value) {
    const seen = new WeakSet()
    return JSON.stringify(value, (_key, val) => {
        if (!val || typeof val !== 'object') return val
        if (seen.has(val)) return '[Circular]'
        seen.add(val)
        if (Array.isArray(val)) return val
        return Object.keys(val)
            .sort()
            .reduce((acc, key) => {
                acc[key] = val[key]
                return acc
            }, {})
    })
}

function summarizeObject(value) {
    const json = stableStringify(value)
    if (!json) return EMPTY_VALUE
    if (json.length <= MAX_OBJECT_SUMMARY_LENGTH) return json
    return `${json.slice(0, MAX_OBJECT_SUMMARY_LENGTH - 1)}...`
}

export function formatReportValue(value) {
    if (value === null || value === undefined || value === '') return EMPTY_VALUE
    if (typeof value === 'string') return value
    if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString() : EMPTY_VALUE
    if (typeof value === 'boolean') return value ? 'Yes' : 'No'
    if (value instanceof Date) {
        return Number.isNaN(value.getTime()) ? EMPTY_VALUE : value.toLocaleDateString()
    }
    if (Array.isArray(value)) {
        if (value.length === 0) return EMPTY_VALUE
        return value.map((item) => formatReportValue(item)).join(', ')
    }
    if (typeof value === 'object') {
        if ('start' in value || 'end' in value) {
            const start = formatReportValue(value.start)
            const end = formatReportValue(value.end)
            if (start !== EMPTY_VALUE && end !== EMPTY_VALUE) return `${start} - ${end}`
            return start !== EMPTY_VALUE ? start : end
        }
        return summarizeObject(value)
    }
    return String(value)
}

export function toReportNumber(value, fallback = 0) {
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string' && value.trim() !== '') {
        const parsed = Number(value)
        if (Number.isFinite(parsed)) return parsed
    }
    return fallback
}
