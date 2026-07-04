import { useState } from 'react'

const COLORS = ['bg-primary', 'bg-brand-secure', 'bg-ink-muted', 'bg-ink-subtle', 'bg-hairline-strong']

const unwrapArr = (d) => {
  if (!d) return []
  if (Array.isArray(d)) return d
  if (Array.isArray(d.data)) return d.data
  if (d.data && Array.isArray(d.data.data)) return d.data.data
  return []
}

const processRows = (arr) => {
  if (!arr || arr.length === 0) return []
  const base = arr.map(d => ({
    cause: String(d.cause ?? d.name ?? d.reason ?? 'Unspecified'),
    hours: Number(d.downtime_hours ?? d.hours ?? d.duration_hours ?? d.total_hours ?? 0) ||
      Number(d.duration_minutes ?? d.minutes ?? 0) / 60,
    pct: d.pct ?? d.percentage ?? null,
  }))
  const totalHours = base.reduce((sum, row) => sum + row.hours, 0)
  return base
    .map(row => ({
      ...row,
      pct: row.pct != null ? Math.round(Number(row.pct)) : Math.round(totalHours > 0 ? (row.hours / totalHours) * 100 : 0),
    }))
    .filter(row => row.hours > 0 || row.pct > 0)
    .sort((a, b) => b.hours - a.hours)
    .slice(0, 5)
}

const DowntimeAnalysisChart = ({ data }) => {
  const [hovered, setHovered] = useState(null)
  const rows = processRows(unwrapArr(data))

  if (rows.length === 0) {
    return (
      <div className="flex min-h-[150px] items-center justify-center rounded-lg border border-dashed border-hairline text-sm text-ink-muted">
        No production data
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 py-2">
      {rows.map((row, i) => {
        const color = COLORS[i % COLORS.length]
        return (
          <div
            key={`${row.cause}-${i}`}
            className={`flex items-center gap-3 px-2 py-1.5 rounded-lg transition-colors cursor-default ${hovered === i ? 'bg-surface-2' : ''}`}
            onMouseEnter={() => setHovered(i)}
            onMouseLeave={() => setHovered(null)}
          >
            <span className="material-symbols-outlined text-base w-6 text-center flex-shrink-0 text-ink-muted">timer</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between mb-1">
                <span className="text-ink text-caption font-medium truncate max-w-[70%]">{row.cause}</span>
                <span className="text-ink text-caption font-medium ml-1 shrink-0">
                  {row.pct}%
                  <span className="text-ink-muted text-caption ml-1">{Number(row.hours).toFixed(1)}h</span>
                </span>
              </div>
              <div className="w-full h-1.5 bg-surface-2 rounded-full overflow-hidden">
                <div className={`h-full ${color} rounded-full transition-all duration-700`} style={{ width: `${Math.min(row.pct, 100)}%` }} />
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default DowntimeAnalysisChart
