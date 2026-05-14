/**
 * Shared labels and cleanup helpers for RAG citations.
 */

export function formatDocDisplayName(source, fallbackNum) {
  const raw = source?.title || source?.doc_id || ''
  const stripped = String(raw).replace(/\.[^/.]+$/, '').trim()
  if (stripped) return stripped
  return fallbackNum != null ? `Source ${fallbackNum}` : 'Source'
}

export function formatCitationChipLabel(source, sourceNumber) {
  const name = formatDocDisplayName(source, sourceNumber)
  return `${name} - Source ${sourceNumber}`
}

export function formatInlineCitationLabel(sourceNumber) {
  return `Source ${sourceNumber}`
}

export function stripSourceFootnoteDefinitions(text) {
  return String(text || '')
    .split('\n')
    .filter((line) => {
      const trimmed = line.trim()
      if (/^\[\^\d+\]:\s*\[SOURCE\s+\d+:/i.test(trimmed)) return false
      if (/^\[SOURCE\s+\d+:/i.test(trimmed)) return false
      return true
    })
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

export function formatBasedOnLine(sources = []) {
  if (!sources.length) return ''
  if (sources.length === 1) {
    return `Based on ${formatDocDisplayName(sources[0], sources[0].source_number)}`
  }
  const first = formatDocDisplayName(sources[0], sources[0].source_number)
  const rest = sources.length - 1
  return `Based on ${first} and ${rest} other source${rest === 1 ? '' : 's'}`
}
