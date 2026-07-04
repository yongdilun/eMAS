const STATUS_COLORS = {
  completed: '#5e6ad2',
  'in-progress': '#7a7fad',
  in_progress: '#7a7fad',
  scheduled: '#8a8f98',
  delayed: '#d0d6e0',
  cancelled: '#62666d',
}

const unwrapArr = (d) => {
  if (!d) return []
  if (Array.isArray(d)) return d
  if (Array.isArray(d.data)) return d.data
  if (d.data && Array.isArray(d.data.data)) return d.data.data
  return []
}

const titleCase = (value) => String(value).replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase())

const aggregate = (arr) => {
  if (!arr || arr.length === 0) return []

  if (arr[0]?.percentage != null) {
    return arr.map(d => {
      const name = String(d.name ?? d.status ?? 'Unknown')
      const key = name.toLowerCase().replace(/\s+/g, '-')
      return {
        name,
        percentage: Math.round(Number(d.percentage)),
        jobs: Number(d.jobs ?? d.count ?? 1),
        color: STATUS_COLORS[key] ?? '#94a3b8',
      }
    })
  }

  if (arr[0]?.status != null && arr[0]?.job_id === undefined) {
    const total = arr.reduce((s, d) => s + Number(d.count ?? d.jobs ?? 1), 0) || 1
    return arr.map(d => {
      const raw = String(d.status ?? 'Unknown')
      const key = raw.toLowerCase().replace(/\s+/g, '-')
      const cnt = Number(d.count ?? d.jobs ?? 1)
      return {
        name: titleCase(raw),
        percentage: Math.round((cnt / total) * 100),
        jobs: cnt,
        color: STATUS_COLORS[key] ?? '#94a3b8',
      }
    })
  }

  const byJob = {}
  arr.forEach(d => {
    const id = String(d.job_id ?? d.jobId ?? d.id ?? 'Unknown')
    if (!byJob[id]) byJob[id] = { planned: 0, produced: 0 }
    byJob[id].planned += Number(d.quantity_planned ?? d.quantityPlanned ?? 0)
    byJob[id].produced += Number(d.quantity_produced ?? d.quantityProduced ?? 0)
  })

  const counts = { completed: 0, 'in-progress': 0, scheduled: 0 }
  Object.values(byJob).forEach(j => {
    if (j.planned > 0 && j.produced >= j.planned) counts.completed++
    else if (j.produced > 0) counts['in-progress']++
    else counts.scheduled++
  })

  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1
  return Object.entries(counts)
    .filter(([, c]) => c > 0)
    .map(([key, cnt]) => ({
      name: titleCase(key),
      jobs: cnt,
      percentage: Math.round((cnt / total) * 100),
      color: STATUS_COLORS[key],
    }))
}

const JobTypeMixChart = ({ data }) => {
  const jobTypes = aggregate(unwrapArr(data))

  if (jobTypes.length === 0) {
    return (
      <div className="flex min-h-[150px] items-center justify-center rounded-lg border border-dashed border-hairline text-sm text-ink-muted">
        No production data
      </div>
    )
  }

  const radius = 55
  const strokeWidth = 18
  const circumference = 2 * Math.PI * radius
  let cumulative = 0
  const totalJobs = jobTypes.reduce((s, t) => s + (t.jobs ?? 0), 0)

  return (
    <div className="flex items-center justify-center gap-6 py-3">
      <div className="relative w-32 h-32 flex-shrink-0">
        <svg className="w-full h-full transform -rotate-90" viewBox="0 0 180 180" role="img" aria-label="Job completion chart">
          <circle cx="90" cy="90" r={radius} fill="none" stroke="currentColor" strokeWidth={strokeWidth} className="text-surface-2" />
          {jobTypes.map((t, i) => {
            const offset = -((cumulative / 100) * circumference)
            const seg = (t.percentage / 100) * circumference
            cumulative += t.percentage
            return (
              <circle
                key={i}
                cx="90"
                cy="90"
                r={radius}
                fill="none"
                stroke={t.color}
                strokeWidth={strokeWidth}
                strokeDasharray={`${seg} ${circumference}`}
                strokeDashoffset={offset}
                className="transition-opacity hover:opacity-80"
              />
            )
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <div className="text-lg font-bold text-ink">{totalJobs}</div>
          <div className="text-[10px] text-ink-muted">Total Jobs</div>
        </div>
      </div>

      <div className="flex-1 space-y-2">
        {jobTypes.map((t) => (
          <div key={t.name} className="flex items-center justify-between">
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: t.color }} />
              <span className="text-ink text-caption font-medium truncate">{t.name}</span>
            </div>
            <div className="flex items-baseline gap-2">
              {t.jobs != null && <span className="text-ink-muted text-caption">{t.jobs} jobs</span>}
              <span className="text-ink text-caption font-medium min-w-[30px] text-right">{t.percentage}%</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default JobTypeMixChart
