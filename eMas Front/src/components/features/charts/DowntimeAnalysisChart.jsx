// Accepts data from GET /reports/bottlenecks
// Actual API shape: { machine_id, step_id, queue_count, utilization, forecast }[]
// Also handles downtime shape: { cause, pct, hours }[]
// Falls back to demo data when API is unavailable
import { useState } from 'react'

const DEMO = [
  { cause: 'Unscheduled Maintenance', pct: 45, hours: 8.3, icon: '⚠️' },
  { cause: 'Material Shortage',       pct: 30, hours: 5.6, icon: '📦' },
  { cause: 'Operator Error',          pct: 25, hours: 4.6, icon: '👤' },
]

const COLORS = [
  { bar: 'from-rose-500 to-rose-600',    icon: '⚠️' },
  { bar: 'from-amber-500 to-amber-600',  icon: '📦' },
  { bar: 'from-teal-500 to-teal-600',    icon: '👤' },
  { bar: 'from-purple-500 to-purple-600',icon: '⚙️' },
  { bar: 'from-blue-500 to-blue-600',    icon: '🔧' },
]

const unwrapArr = (d) => {
  if (!d) return null
  if (Array.isArray(d)) return d
  if (Array.isArray(d.data)) return d.data
  if (d.data && Array.isArray(d.data.data)) return d.data.data
  return null
}

/**
 * Convert API rows to display rows, supporting:
 *  1. Downtime/cause shape: { cause, pct, hours }
 *  2. Bottleneck shape: { machine_id, utilization, queue_count }
 */
const processRows = (arr) => {
  if (!arr || arr.length === 0) return null

  // Already in display shape (has cause/pct/hours)
  if (arr[0]?.cause != null || arr[0]?.pct != null || arr[0]?.hours != null) {
    return arr.map(d => ({
      cause: String(d.cause ?? d.name ?? d.reason ?? d.Cause ?? '—'),
      pct:   Math.round(Number(d.pct ?? d.percentage ?? d.pct_total ?? d.Pct ?? 0)),
      hours: Number(d.hours ?? d.duration_hrs ?? d.total_hours ?? d.Hours ?? 0),
    }))
  }

  // Bottleneck shape: { machine_id, utilization, queue_count }
  // Normalise utilization: if 0–1 fraction, multiply ×100
  const rows = arr.map(d => {
    const rawUtil = Number(d.utilization ?? d.utilization_rate ?? 0)
    const pct = rawUtil <= 1 ? Math.round(rawUtil * 100) : Math.round(rawUtil)
    return {
      cause: String(d.machine_id ?? d.step_id ?? d.name ?? '—'),
      pct,
      hours: Number(d.queue_count ?? d.queueCount ?? 0),
    }
  })
  // Sort by pct descending, take top 5
  return rows.sort((a, b) => b.pct - a.pct).slice(0, 5)
}

const DowntimeAnalysisChart = ({ data }) => {
  const [hovered, setHovered] = useState(null)

  const rows = (() => {
    const arr = unwrapArr(data)
    const processed = processRows(arr)
    return processed && processed.length > 0 ? processed : DEMO
  })()

  // Determine if data is from bottleneck endpoint (shows queue_count not hours)
  const arr = unwrapArr(data)
  const isBottleneck = arr && arr.length > 0 && arr[0]?.machine_id != null && arr[0]?.cause == null

  return (
    <div className="flex flex-col gap-2 py-2">
      {rows.map((row, i) => {
        const c = COLORS[i % COLORS.length]
        return (
          <div key={i}
            className={`flex items-center gap-3 px-2 py-1.5 rounded-lg transition-colors cursor-default ${hovered === i ? 'bg-gray-50 dark:bg-gray-800/50' : ''}`}
            onMouseEnter={() => setHovered(i)}
            onMouseLeave={() => setHovered(null)}
          >
            <span className="text-base w-6 text-center flex-shrink-0">{row.icon ?? c.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300 truncate max-w-[70%]">
                  {row.cause}
                </span>
                <span className="text-xs font-bold text-gray-800 dark:text-white ml-1 shrink-0">
                  {row.pct}%
                  {row.hours > 0 && (
                    <span className="text-gray-500 dark:text-gray-400 font-normal ml-1">
                      · {isBottleneck ? `${row.hours} queued` : `${Number(row.hours).toFixed(1)}h`}
                    </span>
                  )}
                </span>
              </div>
              <div className="w-full h-1.5 bg-gray-200 dark:bg-gray-800 rounded-full overflow-hidden">
                <div
                  className={`h-full bg-gradient-to-r ${c.bar} rounded-full transition-all duration-700`}
                  style={{ width: `${Math.min(row.pct, 100)}%` }}
                />
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default DowntimeAnalysisChart
