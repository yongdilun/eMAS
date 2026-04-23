import ProductionOutputChart from './ProductionOutputChart'

const MOCK_CHART_DATA = [
  { label: 'Mon', planned: 1200, units: 1187 },
  { label: 'Tue', planned: 1000, units: 992 },
  { label: 'Wed', planned: 950, units: 1048 },
  { label: 'Thu', planned: 1200, units: 1195 },
  { label: 'Fri', planned: 1100, units: 1082 },
]

const MOCK_TABLE_ROWS = [
  { slot_id: 'SLOT-2409-1', machine_id: 'M-CNC-01', date: '2026-03-04', quantity_produced: 1187, quantity_scrap: 4 },
  { slot_id: 'SLOT-2409-2', machine_id: 'M-LTH-01', date: '2026-03-04', quantity_produced: 992, quantity_scrap: 2 },
  { slot_id: 'SLOT-2410-1', machine_id: 'M-CNC-02', date: '2026-03-05', quantity_produced: 1048, quantity_scrap: 1 },
  { slot_id: 'SLOT-2410-2', machine_id: 'M-PRS-01', date: '2026-03-05', quantity_produced: 1195, quantity_scrap: 3 },
  { slot_id: 'SLOT-2411-1', machine_id: 'M-CNC-01', date: '2026-03-06', quantity_produced: 1082, quantity_scrap: 0 },
  { slot_id: 'SLOT-2411-2', machine_id: 'M-LTH-02', date: '2026-03-06', quantity_produced: 987, quantity_scrap: 5 },
  { slot_id: 'SLOT-2412-1', machine_id: 'M-CTG-01', date: '2026-03-07', quantity_produced: 756, quantity_scrap: 2 },
  { slot_id: 'SLOT-2412-2', machine_id: 'M-QC-01', date: '2026-03-07', quantity_produced: 1200, quantity_scrap: 0 },
]

const ReportPreview = ({
  reportType = 'Production Output',
  dateRange  = '',
  data       = null,
  loading    = false,
}) => {
  // Normalise API data into rows for the table; use mock when no data
  const rows = (() => {
    if (data) {
      if (Array.isArray(data)) return data
      const arrayKey = Object.keys(data).find((k) => Array.isArray(data[k]))
      if (arrayKey) return data[arrayKey]
      return [data]
    }
    return MOCK_TABLE_ROWS
  })()

  const headers = rows && rows.length > 0 ? Object.keys(rows[0]) : []
  const isMockData = !data

  const fmt = (v) => {
    if (v === null || v === undefined) return '—'
    if (typeof v === 'object') return JSON.stringify(v)
    if (typeof v === 'number') return v.toLocaleString()
    return String(v)
  }

  return (
    <div className="lg:col-span-2 flex flex-col gap-6 bg-white dark:bg-[#101718] border border-gray-300 dark:border-[#27363a] p-6 rounded-xl">
      {/* Panel Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">{reportType} Report</h2>
          <p className="text-sm text-gray-600 dark:text-[#9ab4bc]">{dateRange || 'Last 7 days'}</p>
        </div>
        <div className="flex items-center gap-2">
          <button className="flex items-center justify-center size-10 rounded-lg border border-gray-300 dark:border-[#394f56] bg-white dark:bg-[#1b2528] text-gray-900 dark:text-white hover:border-primary transition-colors">
            <span className="material-symbols-outlined text-xl">share</span>
          </button>
        </div>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center h-48 gap-3 text-gray-500 dark:text-gray-400">
          <span className="w-6 h-6 border-2 border-gray-300 border-t-primary rounded-full animate-spin"/>
          Generating report…
        </div>
      )}

      {/* Report content (mock when no API data) */}
      {!loading && rows && (
        <>
          {/* Summary */}
          <div className="bg-primary/10 border border-primary/20 p-4 rounded-lg">
            <div className="flex items-center gap-2 mb-2">
              <span className="material-symbols-outlined text-primary text-xl">auto_awesome</span>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Report Summary</h3>
            </div>
            <p className="text-sm text-gray-700 dark:text-[#9ab4bc] leading-relaxed">
              {rows.length} record{rows.length !== 1 ? 's' : ''} returned for <strong>{reportType}</strong>
              {dateRange ? ` · ${dateRange}` : ' · Last 7 days'}.
            </p>
          </div>

          {/* Chart */}
          <div className="w-full min-h-[280px] bg-gray-50 dark:bg-[#1b2528] rounded-lg p-6 border border-gray-200 dark:border-[#27363a]">
            <ProductionOutputChart data={isMockData ? MOCK_CHART_DATA : data} />
          </div>

          {/* Data table */}
          {rows.length > 0 && headers.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-gray-300 dark:border-[#394f56] text-gray-900 dark:text-white">
                  <tr>
                    {headers.map((h) => (
                      <th key={h} className="p-3 text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                        {h.replace(/_/g, ' ')}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={i} className="border-b border-gray-200 dark:border-[#27363a] last:border-b-0 hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors">
                      {headers.map((h) => (
                        <td key={h} className="p-3 text-gray-900 dark:text-white">{fmt(row[h])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {rows.length === 0 && (
            <div className="py-12 text-center text-gray-500 dark:text-gray-400 text-sm">No data returned for the selected filters.</div>
          )}
        </>
      )}
    </div>
  )
}

export default ReportPreview
