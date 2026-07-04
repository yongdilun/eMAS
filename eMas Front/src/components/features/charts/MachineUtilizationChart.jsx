const unwrapArr = (d) => {
  if (!d) return []
  if (Array.isArray(d)) return d
  if (Array.isArray(d.data)) return d.data
  if (d.data && Array.isArray(d.data.data)) return d.data.data
  return []
}

const processRows = (arr, rangeHours = 7 * 8) => {
  if (!arr || arr.length === 0) return []

  if (arr[0]?.utilization_pct != null || arr[0]?.pct != null) {
    return arr.map(d => ({
      machine_name: String(d.machine_name ?? d.name ?? d.MachineName ?? d.machine_id ?? 'Machine'),
      utilization_pct: Math.round(Number(d.utilization_pct ?? d.pct ?? 0)),
    }))
  }

  const byMachine = {}
  arr.forEach(d => {
    const id = String(d.machine_id ?? d.MachineID ?? d.machineId ?? d.name ?? 'Machine')
    if (!byMachine[id]) byMachine[id] = { name: id, mins: 0, utilization: null }
    byMachine[id].mins += Number(d.total_minutes ?? d.totalMinutes ?? 0)
    if (d.utilization != null) byMachine[id].utilization = Number(d.utilization)
  })

  const rangeMins = rangeHours * 60
  return Object.values(byMachine).map(m => ({
    machine_name: m.name,
    utilization_pct: m.utilization != null
      ? Math.min(Math.round(m.utilization * 100), 100)
      : Math.min(Math.round((m.mins / rangeMins) * 100), 100),
  }))
}

const MachineUtilizationChart = ({ data }) => {
  const rows = processRows(unwrapArr(data)).filter(row => row.utilization_pct > 0)

  if (rows.length === 0) {
    return (
      <div className="flex min-h-[150px] items-center justify-center rounded-lg border border-dashed border-hairline text-sm text-ink-muted">
        No production data
      </div>
    )
  }

  const getColor = (pct) => {
    if (pct >= 85) return 'bg-primary'
    if (pct >= 60) return 'bg-brand-secure'
    return 'bg-ink-muted'
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-3 px-2 py-2">
      {rows.map((m) => (
        <div key={m.machine_name} className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <span className="text-ink text-caption font-medium truncate max-w-[80%]">{m.machine_name}</span>
            <span className="text-ink-muted text-caption ml-1">{m.utilization_pct}%</span>
          </div>
          <div className="w-full h-2 bg-surface-2 rounded-full overflow-hidden">
            <div
              className={`h-full ${getColor(m.utilization_pct)} rounded-full transition-all duration-700`}
              style={{ width: `${Math.min(m.utilization_pct, 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

export default MachineUtilizationChart
