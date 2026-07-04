// Accepts data from GET /production-analytics/machine-utilization
// Actual API shape: { machine_id, step_id, total_minutes, slot_count }[]
// Also handles: { machine_name, utilization_pct }[] (pre-computed)
// Falls back to machine list with 0% while utilization data is unavailable.

/** Unwrap arrays that may be nested inside { data: [...] } or { success, data: [...] } */
const unwrapArr = (d) => {
    if (!d) return null
    if (Array.isArray(d)) return d
    if (Array.isArray(d.data)) return d.data
    if (d.data && Array.isArray(d.data.data)) return d.data.data
    return null
}

/**
 * Convert raw API rows into { name, pct } display rows.
 * Handles both pre-computed utilization_pct and raw total_minutes.
 */
const processRows = (arr, rangeHours = 7 * 8) => {
    if (!arr || arr.length === 0) return null

    // Pre-computed shape: { machine_name/name, utilization_pct/utilization/pct }
    if (arr[0]?.utilization_pct != null || arr[0]?.pct != null) {
        return arr.map(d => ({
            name: String(d.machine_name ?? d.name ?? d.MachineName ?? d.machine_id ?? '—'),
            pct: Math.round(Number(d.utilization_pct ?? d.pct ?? d.utilization ?? 0)),
        }))
    }

    // Raw shape: { machine_id, total_minutes, utilization? } — aggregate by machine_id
    const byMachine = {}
    arr.forEach(d => {
        const id = String(d.machine_id ?? d.MachineID ?? d.machineId ?? d.name ?? '?')
        if (!byMachine[id]) byMachine[id] = { name: id, mins: 0, utilization: null }
        byMachine[id].mins += Number(d.total_minutes ?? d.totalMinutes ?? d.duration_mins ?? 0)
        // If utilization fraction already provided, prefer it
        if (d.utilization != null) byMachine[id].utilization = Number(d.utilization)
    })

    const rangeMins = rangeHours * 60
    return Object.values(byMachine).map(m => ({
        name: m.name,
        pct: m.utilization != null
            ? Math.min(Math.round(m.utilization * 100), 100)
            : Math.min(Math.round((m.mins / rangeMins) * 100), 100),
    }))
}

/** Resolve machine_id to machine_name when machines list is available */
const resolveNames = (rows, machines) => {
    if (!rows?.length || !machines?.length) return rows
    return rows.map((r) => {
        const m = machines.find(
            (mach) => String(mach.machine_id ?? mach.id ?? '') === String(r.name)
        )
        return { ...r, name: m?.machine_name ?? r.name }
    })
}

const UtilizationChart = ({ machines = [], utilizationData = null }) => {
    const rows = (() => {
        const arr = unwrapArr(utilizationData)
        const processed = processRows(arr)
        const resolved = processed && processed.length > 0
            ? resolveNames(processed, machines)
            : null

        if (resolved && resolved.length > 0) return resolved

        // Fallback: show real machine names without pretending utilization data is available.
        if (machines.length > 0) {
            return machines.slice(0, 8).map(m => ({
                name: String(m.machine_name ?? m.machine_id ?? '—'),
                pct: Math.round(Number(m.utilization_rate ?? 0)),
            }))
        }

        return []
    })()
    const hasUtilizationData = Boolean(processRows(unwrapArr(utilizationData))?.length)

    // Prefer pre-computed avg from API, else calculate from rows
    const apiData = unwrapArr(utilizationData)
    const avgFromApi = utilizationData?.avg_pct ?? utilizationData?.data?.avg_pct ?? null
    const avg = avgFromApi != null
        ? Math.round(Number(avgFromApi))
        : rows.length > 0
            ? Math.round(rows.reduce((s, r) => s + r.pct, 0) / rows.length)
            : 0
    void apiData

    const getColor = (pct) => {
        if (pct >= 85) return 'bg-primary'
        if (pct >= 60) return 'bg-amber-500'
        return 'bg-red-500'
    }

    return (
        <div className="mb-4 bg-surface-1 rounded-xl border border-hairline p-5">
            <div className="flex flex-col gap-2">
                <p className="text-ink text-sm font-semibold leading-normal">
                    Overall Machine Utilization
                </p>
                <div className="flex items-baseline gap-2">
                    <p className="text-ink text-[28px] font-bold leading-tight">{avg}%</p>
                    <p className={`${hasUtilizationData ? 'text-semantic-success dark:text-[#0bda57]' : 'text-ink-subtle'} text-sm font-medium flex items-center`}>
                        <span className="material-symbols-outlined text-base">trending_up</span>
                        {hasUtilizationData ? 'Real-time' : 'Unavailable'}
                    </p>
                </div>

                {!hasUtilizationData ? (
                    <div className="rounded-lg border border-hairline bg-surface-2 px-4 py-3 text-sm text-ink-subtle">
                        Utilization data is unavailable. No demo machine values are being shown.
                    </div>
                ) : null}

                {rows.length > 0 ? (
                    <div className="flex flex-col gap-2 pt-2">
                        {rows.map((row) => (
                            <div key={row.name} className="flex items-center gap-3">
                                <p className="text-ink-subtle dark:text-[#9cb3ba] text-xs w-28 shrink-0 truncate text-right">{row.name}</p>
                                <div className="flex-1 h-2 bg-gray-200 dark:bg-[#283539] rounded-full overflow-hidden">
                                    <div
                                        className={`h-full ${getColor(row.pct)} rounded-full transition-all duration-700`}
                                        style={{ width: `${Math.min(row.pct, 100)}%` }}
                                    />
                                </div>
                                <span className="text-[11px] text-ink-subtle w-8 text-right">{row.pct}%</span>
                            </div>
                        ))}
                    </div>
                ) : null}
            </div>
        </div>
    )
}

export default UtilizationChart
