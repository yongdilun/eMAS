/**
 * Chat timestamps use a fixed operations timezone (Malaysia, UTC+8) so they stay
 * consistent regardless of the operator's browser/OS locale.
 * Override with VITE_FACTORY_AGENT_DISPLAY_TIMEZONE (IANA), e.g. Asia/Singapore.
 */
export const FACTORY_AGENT_DISPLAY_TIMEZONE = (() => {
  const raw = String(import.meta.env?.VITE_FACTORY_AGENT_DISPLAY_TIMEZONE ?? 'Asia/Kuala_Lumpur').trim()
  return raw || 'Asia/Kuala_Lumpur'
})()

const DISPLAY_TIME_OPTIONS = {
  timeZone: FACTORY_AGENT_DISPLAY_TIMEZONE,
  hour: '2-digit',
  minute: '2-digit',
}

export function parseFactoryAgentTime(dateLike) {
  if (dateLike instanceof Date) return dateLike
  if (typeof dateLike === 'number') {
    const millis = Math.abs(dateLike) < 1_000_000_000_000 ? dateLike * 1000 : dateLike
    return new Date(millis)
  }
  if (typeof dateLike === 'string') {
    const trimmed = dateLike.trim()
    if (!trimmed) return new Date(NaN)
    if (/^-?\d+(\.\d+)?$/.test(trimmed)) {
      return parseFactoryAgentTime(Number(trimmed))
    }
    const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(trimmed)
    return new Date(hasTimezone ? trimmed : `${trimmed}Z`)
  }
  return new Date(dateLike)
}

export function formatFactoryAgentTime(dateLike) {
  try {
    const d = parseFactoryAgentTime(dateLike)
    if (Number.isNaN(d.getTime())) {
      return new Date().toLocaleTimeString(undefined, DISPLAY_TIME_OPTIONS)
    }
    return d.toLocaleTimeString(undefined, DISPLAY_TIME_OPTIONS)
  } catch {
    return new Date().toLocaleTimeString(undefined, DISPLAY_TIME_OPTIONS)
  }
}
