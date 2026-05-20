import { formatReportValue, toReportNumber } from './reportValueFormatter'

const ProductionOutputChart = ({ data }) => {
    const rows = (() => {
        const arr = Array.isArray(data) ? data : (data?.data ?? null)
        if (!arr || arr.length === 0) return []
        return arr.map((d) => {
            const label = d.label ?? d.day ?? d.date ?? d.period ?? d.date_range ?? d.range ?? '-'
            const planned = d.planned ?? d.target ?? null
            return {
                label: formatReportValue(label),
                units: toReportNumber(d.units ?? d.actual ?? d.qty_produced ?? 0),
                planned: planned == null ? null : toReportNumber(planned, null),
            }
        })
    })()

    if (rows.length === 0) {
        return (
            <div className="w-full min-h-[240px] flex items-center justify-center rounded-lg border border-hairline bg-surface-1 px-4 text-center text-sm text-ink-subtle">
                Production chart data is unavailable. No demo chart values are being shown.
            </div>
        )
    }

    const maxValue = Math.max(...rows.map(r => Math.max(r.units, r.planned ?? r.units))) * 1.2 || 1400
    const gridCount = 4
    const gridLines = Array.from({ length: gridCount + 1 }, (_, i) =>
        Math.round((maxValue / gridCount) * i)
    )

    return (
        <div className="w-full min-h-[240px] flex flex-col">
            <div className="flex items-center justify-between mb-4 shrink-0">
                <h3 className="text-base font-semibold text-ink">
                    Production Output - Planned vs Actual
                </h3>
                <div className="flex items-center gap-4">
                    <div className="flex items-center gap-1.5">
                        <div className="w-3 h-3 rounded bg-gradient-to-br from-blue-400 to-blue-600" />
                        <span className="text-xs text-ink-subtle">Planned</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                        <div className="w-3 h-3 rounded bg-gradient-to-br from-green-400 to-green-600" />
                        <span className="text-xs text-ink-subtle">Actual</span>
                    </div>
                </div>
            </div>

            <div className="flex-1 relative min-h-[180px]">
                <div className="absolute inset-0 flex flex-col justify-between py-2 pointer-events-none">
                    {[...gridLines].reverse().map((v, i) => (
                        <div key={i} className="flex items-center">
                            <span className="text-[10px] text-gray-400 dark:text-ink-subtle w-10 text-right pr-2 shrink-0">
                                {v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v}
                            </span>
                            <div className="flex-1 border-t border-hairline" />
                        </div>
                    ))}
                </div>

                <div className="absolute inset-0 pl-12 pt-2 pb-2 flex items-end gap-3">
                    {rows.map((item, i) => {
                        const actualH = (item.units / maxValue) * 100
                        const plannedH = item.planned != null ? (item.planned / maxValue) * 100 : null
                        const over = item.planned != null ? item.units > item.planned : null
                        const variancePct = item.planned
                            ? Math.abs(((item.units - item.planned) / item.planned * 100)).toFixed(1)
                            : '0.0'

                        return (
                            <div key={i} className="flex-1 flex flex-col items-center gap-2">
                                <div className="w-full flex justify-center gap-1.5 items-end" style={{ height: 160 }}>
                                    {plannedH != null && (
                                        <div className="relative group" style={{ width: '40%' }}>
                                            <div
                                                className="w-full bg-gradient-to-t from-blue-600 to-blue-400 rounded-t-md transition-all duration-500"
                                                style={{ height: `${plannedH}%` }}
                                            >
                                                <div className="absolute -top-7 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity bg-gray-900 text-white px-1.5 py-0.5 rounded text-[10px] whitespace-nowrap pointer-events-none">
                                                    {item.planned.toLocaleString()}
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                    <div className="relative group" style={{ width: '40%' }}>
                                        <div
                                            className="w-full bg-gradient-to-t from-green-600 to-green-400 rounded-t-md transition-all duration-500"
                                            style={{ height: `${actualH}%` }}
                                        >
                                            <div className="absolute -top-7 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity bg-gray-900 text-white px-1.5 py-0.5 rounded text-[10px] whitespace-nowrap pointer-events-none">
                                                {item.units.toLocaleString()}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div className="flex flex-col items-center gap-0.5">
                                    <span className="text-xs font-semibold text-ink">{item.label}</span>
                                    {over != null && (
                                        <span className={`text-[10px] font-medium flex items-center gap-0.5 ${over ? 'text-semantic-success ' : 'text-red-500 '}`}>
                                            <span className="material-symbols-outlined text-xs">{over ? 'trending_up' : 'trending_down'}</span>
                                            {variancePct}%
                                        </span>
                                    )}
                                </div>
                            </div>
                        )
                    })}
                </div>
            </div>

            <div className="text-center text-[10px] text-gray-400 dark:text-ink-subtle mt-1 pl-10">Units (Daily Production)</div>
        </div>
    )
}

export default ProductionOutputChart
