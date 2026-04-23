// Accepts data from GET /reports/job-completion
// Actual API shape: { job_id, slot_id, quantity_planned, quantity_produced }[]
// Also handles: [{ status, percentage, jobs }] (pre-aggregated)
// Falls back to demo data when API is unavailable

const DEMO = [
  { name: 'Completed',   percentage: 40, jobs: 4,  color: '#10b981' },
  { name: 'In Progress', percentage: 30, jobs: 3,  color: '#3b82f6' },
  { name: 'Scheduled',   percentage: 20, jobs: 2,  color: '#6366f1' },
  { name: 'Delayed',     percentage: 10, jobs: 1,  color: '#f59e0b' },
]

const STATUS_COLORS = {
  'completed':    '#10b981',
  'in-progress':  '#3b82f6',
  'in_progress':  '#3b82f6',
  'scheduled':    '#6366f1',
  'delayed':      '#f59e0b',
  'cancelled':    '#94a3b8',
}

const unwrapArr = (d) => {
  if (!d) return null
  if (Array.isArray(d)) return d
  if (Array.isArray(d.data)) return d.data
  if (d.data && Array.isArray(d.data.data)) return d.data.data
  return null
}

/**
 * Convert job-completion rows into aggregated status buckets.
 * Supports both:
 *  - Raw slot rows: { job_id, quantity_planned, quantity_produced }
 *  - Pre-aggregated: { status, percentage, jobs } or { name, percentage }
 */
const aggregate = (arr) => {
  if (!arr || arr.length === 0) return null

  // Already aggregated with percentage
  if (arr[0]?.percentage != null) {
    return arr.map(d => {
      const name = String(d.name ?? d.status ?? 'Unknown')
      const key  = name.toLowerCase().replace(/\s+/g, '-')
      return {
        name,
        percentage: Math.round(Number(d.percentage)),
        jobs: Number(d.jobs ?? d.count ?? 1),
        color: STATUS_COLORS[key] ?? '#94a3b8',
      }
    })
  }

  // Pre-aggregated by status
  if (arr[0]?.status != null && arr[0]?.job_id === undefined) {
    const total = arr.reduce((s, d) => s + Number(d.count ?? d.jobs ?? 1), 0) || 1
    return arr.map(d => {
      const raw = String(d.status ?? 'Unknown')
      const key = raw.toLowerCase().replace(/\s+/g, '-')
      const cnt = Number(d.count ?? d.jobs ?? 1)
      return {
        name: raw,
        percentage: Math.round((cnt / total) * 100),
        jobs: cnt,
        color: STATUS_COLORS[key] ?? '#94a3b8',
      }
    })
  }

  // Raw slot rows: { job_id, quantity_planned, quantity_produced }
  // Aggregate per job_id then classify
  const byJob = {}
  arr.forEach(d => {
    const id = String(d.job_id ?? d.jobId ?? d.id ?? '?')
    if (!byJob[id]) byJob[id] = { planned: 0, produced: 0 }
    byJob[id].planned  += Number(d.quantity_planned  ?? d.quantityPlanned  ?? 0)
    byJob[id].produced += Number(d.quantity_produced ?? d.quantityProduced ?? 0)
  })

  const counts = { 'completed': 0, 'in-progress': 0, 'scheduled': 0 }
  Object.values(byJob).forEach(j => {
    if (j.planned > 0 && j.produced >= j.planned) counts['completed']++
    else if (j.produced > 0)                       counts['in-progress']++
    else                                            counts['scheduled']++
  })

  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1
  return Object.entries(counts)
    .filter(([, c]) => c > 0)
    .map(([key, cnt]) => ({
      name: key === 'in-progress' ? 'In Progress' : key.charAt(0).toUpperCase() + key.slice(1),
      jobs: cnt,
      percentage: Math.round((cnt / total) * 100),
      color: STATUS_COLORS[key],
    }))
}

const JobTypeMixChart = ({ data }) => {
  const jobTypes = (() => {
    const arr = unwrapArr(data)
    const result = aggregate(arr)
    return result && result.length > 0 ? result : DEMO
  })()

  const radius = 55
  const strokeWidth = 18
  const circumference = 2 * Math.PI * radius
  let cumulative = 0
  const totalJobs = jobTypes.reduce((s, t) => s + (t.jobs ?? 0), 0)

  return (
    <div className="flex items-center justify-center gap-6 py-3">
      {/* Donut */}
      <div className="relative w-32 h-32 flex-shrink-0">
        <svg className="w-full h-full transform -rotate-90" viewBox="0 0 180 180">
          <circle cx="90" cy="90" r={radius} fill="none"
            stroke="currentColor" strokeWidth={strokeWidth}
            className="text-gray-100 dark:text-gray-800" />
          {jobTypes.map((t, i) => {
            const offset = -((cumulative / 100) * circumference)
            const seg = (t.percentage / 100) * circumference
            cumulative += t.percentage
            return (
              <circle key={i} cx="90" cy="90" r={radius} fill="none"
                stroke={t.color} strokeWidth={strokeWidth}
                strokeDasharray={`${seg} ${circumference}`}
                strokeDashoffset={offset}
                className="transition-opacity hover:opacity-80"
              />
            )
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <div className="text-lg font-bold text-gray-900 dark:text-white">{totalJobs}</div>
          <div className="text-[10px] text-gray-500 dark:text-gray-400">Total Jobs</div>
        </div>
      </div>

      {/* Legend */}
      <div className="flex-1 space-y-2">
        {jobTypes.map((t) => (
          <div key={t.name} className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: t.color }} />
              <span className="text-xs font-medium text-gray-700 dark:text-gray-300 capitalize">{t.name}</span>
            </div>
            <div className="flex items-baseline gap-2">
              {t.jobs != null && (
                <span className="text-xs text-gray-500 dark:text-gray-400">{t.jobs} jobs</span>
              )}
              <span className="text-xs font-semibold text-gray-900 dark:text-white min-w-[30px] text-right">
                {t.percentage}%
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default JobTypeMixChart
