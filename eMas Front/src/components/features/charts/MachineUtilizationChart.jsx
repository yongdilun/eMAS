// Accepts data from GET /reports/machine-utilization
// Actual API shape: { machine_id, step_id, total_minutes, slot_count }[]
// Also handles: { machine_name, utilization_pct }[] (pre-computed)
// Falls back to demo data when API is unavailable

const DEMO = [
  { machine_name: 'CNC Mill 01',       utilization_pct: 92 },
  { machine_name: 'CNC Mill 02',       utilization_pct: 88 },
  { machine_name: 'Hydraulic Press',   utilization_pct: 78 },
  { machine_name: 'Lathe 01',          utilization_pct: 65 },
  { machine_name: 'Coating Station',   utilization_pct: 85 },
  { machine_name: 'Assembly Station',  utilization_pct: 91 },
]

const unwrapArr = (d) => {
  if (!d) return null
  if (Array.isArray(d)) return d
  if (Array.isArray(d.data)) return d.data
  if (d.data && Array.isArray(d.data.data)) return d.data.data
  return null
}

const processRows = (arr, rangeHours = 7 * 8) => {
  if (!arr || arr.length === 0) return null

  // Pre-computed shape: already has utilization_pct
  if (arr[0]?.utilization_pct != null || arr[0]?.pct != null) {
    return arr.map(d => ({
      machine_name:    String(d.machine_name ?? d.name ?? d.MachineName ?? d.machine_id ?? '—'),
      utilization_pct: Math.round(Number(d.utilization_pct ?? d.pct ?? 0)),
    }))
  }

  // Raw shape: { machine_id, total_minutes, utilization? } — aggregate by machine_id
  const byMachine = {}
  arr.forEach(d => {
    const id = String(d.machine_id ?? d.MachineID ?? d.machineId ?? d.name ?? '?')
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
  const rows = (() => {
    const arr = unwrapArr(data)
    const processed = processRows(arr)
    return processed && processed.length > 0 ? processed : DEMO
  })()

  const getColor = (pct) => {
    if (pct >= 85) return 'from-primary to-cyan-400'
    if (pct >= 60) return 'from-amber-500 to-yellow-400'
    return 'from-red-500 to-rose-400'
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-3 px-2 py-2">
      {rows.map((m) => (
        <div key={m.machine_name} className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <span className="text-gray-700 dark:text-gray-300 text-xs font-medium truncate max-w-[80%]">{m.machine_name}</span>
            <span className="text-gray-500 dark:text-gray-400 text-xs font-semibold ml-1">{m.utilization_pct}%</span>
          </div>
          <div className="w-full h-2 bg-gray-200 dark:bg-gray-800 rounded-full overflow-hidden">
            <div
              className={`h-full bg-gradient-to-r ${getColor(m.utilization_pct)} rounded-full transition-all duration-700`}
              style={{ width: `${Math.min(m.utilization_pct, 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

export default MachineUtilizationChart
