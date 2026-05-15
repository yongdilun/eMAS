import ProductionOutputChart from './ProductionOutputChart'

const ReportPreview = ({
    reportType = 'Production Output',
    dateRange = '',
    data = null,
    loading = false,
}) => {
    // Normalise API data into rows for the table.
    const rows = (() => {
        if (data) {
            if (Array.isArray(data)) return data
            const arrayKey = Object.keys(data).find((k) => Array.isArray(data[k]))
            if (arrayKey) return data[arrayKey]
            return [data]
        }
        return []
    })()

    const headers = rows && rows.length > 0 ? Object.keys(rows[0]) : []

    const fmt = (v) => {
        if (v === null || v === undefined) return '—'
        if (typeof v === 'object') return JSON.stringify(v)
        if (typeof v === 'number') return v.toLocaleString()
        return String(v)
    }

    return (
        <div className="lg:col-span-2 flex flex-col gap-6 bg-surface-1 border border-hairline p-6 rounded-xl">
            {/* Panel Header */}
            <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                    <h2 className="text-2xl font-bold text-ink">{reportType} Report</h2>
                    <p className="text-sm text-ink-subtle dark:text-[#9ab4bc]">{dateRange || 'Last 7 days'}</p>
                </div>
                <div className="flex items-center gap-2">
                    <button className="flex items-center justify-center size-10 rounded-lg border border-hairline bg-surface-1 text-ink hover:border-primary transition-colors">
                        <span className="material-symbols-outlined text-xl">share</span>
                    </button>
                </div>
            </div>

            {/* Loading state */}
            {loading && (
                <div className="flex items-center justify-center h-48 gap-3 text-ink-subtle">
                    <span className="w-6 h-6 border-2 border-gray-300 border-t-primary rounded-full animate-spin" />
                    Generating report…
                </div>
            )}

            {/* Report content */}
            {!loading && rows && (
                <>
                    {/* Summary */}
                    <div className={`${data ? 'bg-primary/10 border-primary/20' : 'bg-surface-2 border-hairline'} border p-4 rounded-lg`}>
                        <div className="flex items-center gap-2 mb-2">
                            <span className="material-symbols-outlined text-primary text-xl">auto_awesome</span>
                            <h3 className="text-lg font-semibold text-ink">Report Summary</h3>
                        </div>
                        <p className="text-sm text-ink-muted dark:text-[#9ab4bc] leading-relaxed">
                            {data ? (
                                <>
                                    {rows.length} record{rows.length !== 1 ? 's' : ''} returned for <strong>{reportType}</strong>
                                    {dateRange ? ` · ${dateRange}` : ' · Last 7 days'}.
                                </>
                            ) : (
                                'Report data is unavailable. No demo report rows are being shown.'
                            )}
                        </p>
                    </div>

                    {/* Chart */}
                    <div className="w-full min-h-[280px] bg-surface-2 dark:bg-[#1b2528] rounded-lg p-6 border border-hairline">
                        <ProductionOutputChart data={data} />
                    </div>

                    {/* Data table */}
                    {rows.length > 0 && headers.length > 0 && (
                        <div className="overflow-x-auto">
                            <table className="w-full text-left text-sm">
                                <thead className="border-b border-hairline text-ink">
                                    <tr>
                                        {headers.map((h) => (
                                            <th key={h} className="p-3 text-xs font-semibold uppercase tracking-wider text-ink-subtle">
                                                {h.replace(/_/g, ' ')}
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {rows.map((row, i) => (
                                        <tr key={i} className="border-b border-hairline last:border-b-0 hover:bg-surface-2 /40 transition-colors">
                                            {headers.map((h) => (
                                                <td key={h} className="p-3 text-ink">{fmt(row[h])}</td>
                                            ))}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}

                    {rows.length === 0 && (
                        <div className="py-12 text-center text-ink-subtle text-sm">No data returned for the selected filters.</div>
                    )}
                </>
            )}
        </div>
    )
}

export default ReportPreview
