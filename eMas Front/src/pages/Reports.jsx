import { useState } from 'react'
import CalendarPicker from '../components/features/reports/CalendarPicker'
import ReportPreview from '../components/features/reports/ReportPreview'
import { formatReportValue } from '../components/features/reports/reportValueFormatter'
import PageHeader from '../components/shared/PageHeader'
import { reportsApi, apiErrorMessage } from '../services/api'
import logger from '../services/logger'
import { useToast } from '../context/ToastContext'

const REPORT_TYPES = [
    { label: 'Production Output', key: 'production-output', api: reportsApi.productionOutput },
    { label: 'Machine Utilization', key: 'machine-utilization', api: reportsApi.machineUtilization },
    { label: 'Job Completion', key: 'job-completion', api: reportsApi.jobCompletion },
    { label: 'Inventory Trends', key: 'inventory-trends', api: reportsApi.inventoryTrends },
    { label: 'Quality Trends', key: 'quality-trends', api: reportsApi.qualityTrends },
    { label: 'OEE Trends', key: 'oee', api: reportsApi.oee },
    { label: 'Bottleneck Forecasts', key: 'bottlenecks', api: reportsApi.bottlenecks },
    { label: 'Maintenance Efficiency', key: 'maintenance-efficiency', api: reportsApi.maintenanceEfficiency },
]

const selectCls = `form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-ink focus:outline-0 border border-hairline bg-surface-1 focus:border-l-primary focus:border-l-2 h-14 p-[15px] text-base font-normal leading-normal`

const Reports = () => {
    const toast = useToast()
    const [reportType, setReportType] = useState(REPORT_TYPES[0].key)
    const [productionLine, setProductionLine] = useState('')
    const [machineId, setMachineId] = useState('')
    const [dateRange, setDateRange] = useState('')
    const [startIso, setStartIso] = useState('')
    const [endIso, setEndIso] = useState('')
    const [loading, setLoading] = useState(false)
    const [reportData, setReportData] = useState(null)
    const [error, setError] = useState('')

    const selectedReport = REPORT_TYPES.find(r => r.key === reportType)

    const handleGenerateReport = async () => {
        if (!selectedReport) return
        setLoading(true); setError(''); setReportData(null)
        const params = {}
        if (startIso) params.start = startIso
        if (endIso) params.end = endIso
        if (machineId) params.machine_id = machineId
        if (productionLine) params.line = productionLine
        try {
            const data = await selectedReport.api(params)
            setReportData(data)
            logger.info('Report generated', { type: reportType })
        } catch (err) {
            logger.error('Failed to generate report', err, { type: reportType, params })
            setError(apiErrorMessage(err, 'Could not generate report.'))
        } finally {
            setLoading(false)
        }
    }

    const handleExport = (fmt) => {
        if (!reportData) return
        try {
            const json = JSON.stringify(reportData, null, 2)
            const blob = new Blob([json], { type: 'application/json' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `${reportType}-report.json`
            a.click()
            URL.revokeObjectURL(url)
            logger.info('Report exported', { type: reportType, format: fmt })
            toast.success(`Report exported as ${fmt}.`)
        } catch (err) {
            logger.error('Report export failed', err, { type: reportType })
            toast.error('Failed to export report.')
        }
    }

    const handleDateRangeChange = (range) => {
        if (range && typeof range === 'object') {
            setDateRange(formatReportValue(range))
            const start = range.start instanceof Date ? range.start : new Date(range.start)
            const end = range.end instanceof Date ? range.end : new Date(range.end)
            if (!Number.isNaN(start.getTime()) && !Number.isNaN(end.getTime())) {
                const endOfDay = new Date(end)
                endOfDay.setHours(23, 59, 59, 999)
                setStartIso(start.toISOString())
                setEndIso(endOfDay.toISOString())
            }
            return
        }
        setDateRange(range || '')
        // Parse "Oct 5, 2023 – Oct 9, 2023" → ISO
        try {
            const parts = range.split(/\s*[-–]\s*/)
            if (parts.length === 2) {
                setStartIso(new Date(parts[0]).toISOString())
                setEndIso(new Date(parts[1] + ' 23:59:59').toISOString())
            }
        } catch { /* ignore parse errors */ }
    }

    return (
        <div className="flex-1 p-8 overflow-y-auto">
            <PageHeader title="Reports" subtitle="Generate and export detailed production reports." />

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-[96px]">
                {/* Left Column: Controls */}
                <div className="lg:col-span-1 flex flex-col gap-6">
                    {/* Report Type */}
                    <label className="flex flex-col w-full">
                        <p className="text-ink text-base font-medium leading-normal pb-2">Report Type</p>
                        <select value={reportType} onChange={(e) => setReportType(e.target.value)} className={selectCls}>
                            {REPORT_TYPES.map(r => (
                                <option key={r.key} value={r.key} className="bg-surface-1">{r.label}</option>
                            ))}
                        </select>
                    </label>

                    {/* CalendarPicker */}
                    <CalendarPicker onDateRangeChange={handleDateRangeChange} />

                    {/* Machine ID */}
                    <label className="flex flex-col w-full">
                        <p className="text-ink text-base font-medium leading-normal pb-2">Machine ID (optional)</p>
                        <input
                            type="text" value={machineId} onChange={e => setMachineId(e.target.value)}
                            placeholder="e.g. M-01"
                            className="w-full rounded-lg border border-hairline bg-surface-1 text-ink h-14 px-4 text-sm focus:outline-none focus:ring-2 focus:ring-primary transition-colors placeholder-ink-subtle"
                        />
                    </label>

                    {/* Production Line filter */}
                    <label className="flex flex-col w-full">
                        <p className="text-ink text-base font-medium leading-normal pb-2">Filter by Production Line</p>
                        <select value={productionLine} onChange={(e) => setProductionLine(e.target.value)} className={selectCls}>
                            <option value="" className="bg-surface-1">All Lines</option>
                            <option className="bg-surface-1">Line 1</option>
                            <option className="bg-surface-1">Line 2</option>
                            <option className="bg-surface-1">Line 3</option>
                        </select>
                    </label>

                    {/* Error */}
                    {error && (
                        <div className="flex items-start gap-2 px-3 py-2 bg-red-50 border border-red-200 dark:border-red-800 rounded-lg text-sm text-ink-muted">
                            <span className="material-symbols-outlined text-base mt-0.5">error</span>{error}
                        </div>
                    )}

                    {/* Generate Report Button */}
                    <button
                        onClick={handleGenerateReport} disabled={loading}
                        className="w-full flex items-center justify-center gap-2 h-14 rounded-lg bg-primary text-white text-base font-bold hover:bg-primary/90 transition-colors disabled:opacity-60"
                    >
                        {loading ? (
                            <><span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />Generating…</>
                        ) : (
                            <><span className="material-symbols-outlined">autorenew</span>Generate Report</>
                        )}
                    </button>

                    {/* Export buttons – only shown when data is loaded */}
                    {reportData && (
                        <div className="flex gap-2">
                            {['JSON', 'CSV'].map(fmt => (
                                <button key={fmt} onClick={() => handleExport(fmt)}
                                    className="flex-1 flex items-center justify-center gap-1.5 h-10 rounded-lg border border-hairline text-ink-muted text-sm font-medium hover:bg-surface-2 transition-colors">
                                    <span className="material-symbols-outlined text-base">download</span>{fmt}
                                </button>
                            ))}
                        </div>
                    )}
                </div>

                {/* Right Column: Report Preview */}
                <ReportPreview
                    reportType={selectedReport?.label || reportType}
                    dateRange={dateRange}
                    data={reportData}
                    loading={loading}
                />
            </div>
        </div>
    )
}

export default Reports
