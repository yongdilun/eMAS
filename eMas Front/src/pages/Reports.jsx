import { useEffect, useState } from 'react'
import CalendarPicker from '../components/features/reports/CalendarPicker'
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
  { label: 'Downtime', key: 'downtime', api: reportsApi.downtime },
  { label: 'Maintenance Efficiency', key: 'maintenance-efficiency', api: reportsApi.maintenanceEfficiency },
]

const selectCls = 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-ink focus:outline-0 border border-hairline bg-surface-1 focus:border-l-primary focus:border-l-2 h-14 p-[15px] text-base font-normal leading-normal'
const inputCls = 'w-full rounded-lg border border-hairline bg-surface-1 text-ink h-14 px-4 text-sm focus:outline-none focus:ring-2 focus:ring-primary transition-colors placeholder-ink-subtle'

const Reports = () => {
  const toast = useToast()
  const [reportType, setReportType] = useState(REPORT_TYPES[0].key)
  const [machineId, setMachineId] = useState('')
  const [jobId, setJobId] = useState('')
  const [productId, setProductId] = useState('')
  const [materialId, setMaterialId] = useState('')
  const [dateRange, setDateRange] = useState('')
  const [startIso, setStartIso] = useState('')
  const [endIso, setEndIso] = useState('')
  const [loading, setLoading] = useState(false)
  const [reportFile, setReportFile] = useState(null)
  const [error, setError] = useState('')

  const selectedReport = REPORT_TYPES.find(r => r.key === reportType)

  useEffect(() => {
    return () => {
      if (reportFile?.url) URL.revokeObjectURL(reportFile.url)
    }
  }, [reportFile])

  const handleGenerateReport = async () => {
    if (!selectedReport) return
    setLoading(true)
    setError('')
    setReportFile(null)

    const params = {}
    if (startIso) params.start = startIso
    if (endIso) params.end = endIso
    if (machineId.trim()) params.machine_id = machineId.trim()
    if (jobId.trim()) params.job_id = jobId.trim()
    if (productId.trim()) params.product_id = productId.trim()
    if (materialId.trim()) params.material_id = materialId.trim()

    try {
      const file = await selectedReport.api(params)
      setReportFile(file)
      logger.info('PDF report generated', { type: reportType, filename: file.filename })
      toast.success('PDF report generated.')
    } catch (err) {
      logger.error('Failed to generate PDF report', err, { type: reportType, params })
      setError(apiErrorMessage(err, 'Could not generate report.'))
    } finally {
      setLoading(false)
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
    setStartIso('')
    setEndIso('')
  }

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <PageHeader title="Reports" subtitle="Generate PDF production reports." />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-1 flex flex-col gap-6">
          <label className="flex flex-col w-full">
            <p className="text-ink text-base font-medium leading-normal pb-2">Report Type</p>
            <select value={reportType} onChange={(e) => setReportType(e.target.value)} className={selectCls}>
              {REPORT_TYPES.map(r => (
                <option key={r.key} value={r.key} className="bg-surface-1">{r.label}</option>
              ))}
            </select>
          </label>

          <CalendarPicker onDateRangeChange={handleDateRangeChange} />

          <label className="flex flex-col w-full">
            <p className="text-ink text-base font-medium leading-normal pb-2">Machine ID</p>
            <input type="text" value={machineId} onChange={e => setMachineId(e.target.value)} placeholder="Optional" className={inputCls} />
          </label>

          <label className="flex flex-col w-full">
            <p className="text-ink text-base font-medium leading-normal pb-2">Job ID</p>
            <input type="text" value={jobId} onChange={e => setJobId(e.target.value)} placeholder="Optional" className={inputCls} />
          </label>

          <label className="flex flex-col w-full">
            <p className="text-ink text-base font-medium leading-normal pb-2">Product ID</p>
            <input type="text" value={productId} onChange={e => setProductId(e.target.value)} placeholder="Optional" className={inputCls} />
          </label>

          <label className="flex flex-col w-full">
            <p className="text-ink text-base font-medium leading-normal pb-2">Material ID</p>
            <input type="text" value={materialId} onChange={e => setMaterialId(e.target.value)} placeholder="Optional" className={inputCls} />
          </label>

          {error && (
            <div className="flex items-start gap-2 px-3 py-2 bg-red-50 border border-red-200 dark:border-red-800 rounded-lg text-sm text-ink-muted">
              <span className="material-symbols-outlined text-base mt-0.5">error</span>{error}
            </div>
          )}

          <button
            onClick={handleGenerateReport}
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 h-14 rounded-lg bg-primary text-white text-base font-bold hover:bg-primary/90 transition-colors disabled:opacity-60"
          >
            {loading ? (
              <><span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />Generating...</>
            ) : (
              <><span className="material-symbols-outlined">picture_as_pdf</span>Generate PDF</>
            )}
          </button>
        </div>

        <div className="lg:col-span-2 flex min-h-[70vh] flex-col rounded-lg border border-hairline bg-surface-1 overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-hairline px-4 py-3">
            <div className="min-w-0">
              <p className="text-ink text-sm font-semibold truncate">{selectedReport?.label || 'Report'}</p>
              <p className="text-ink-subtle text-xs truncate">{dateRange || 'Default date range'}</p>
            </div>
            {reportFile && (
              <div className="flex gap-2">
                <a
                  href={reportFile.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1.5 h-9 px-3 rounded-lg border border-hairline text-ink-muted text-sm font-medium hover:bg-surface-2 transition-colors"
                >
                  <span className="material-symbols-outlined text-base">open_in_new</span>View PDF
                </a>
                <a
                  href={reportFile.url}
                  download={reportFile.filename}
                  className="flex items-center gap-1.5 h-9 px-3 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors"
                >
                  <span className="material-symbols-outlined text-base">download</span>Download PDF
                </a>
              </div>
            )}
          </div>

          <div className="flex-1 bg-surface-2">
            {loading ? (
              <div className="h-full min-h-[520px] flex flex-col items-center justify-center gap-3 text-ink-muted">
                <span className="w-8 h-8 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
                <p className="text-sm">Generating PDF...</p>
              </div>
            ) : reportFile ? (
              <iframe
                title={`${selectedReport?.label || 'Report'} PDF preview`}
                src={reportFile.url}
                className="h-full min-h-[70vh] w-full bg-white"
              />
            ) : (
              <div className="h-full min-h-[520px] flex flex-col items-center justify-center gap-3 px-6 text-center text-ink-muted">
                <span className="material-symbols-outlined text-4xl">picture_as_pdf</span>
                <p className="text-sm font-medium text-ink">No PDF generated yet</p>
                <p className="max-w-sm text-xs">Choose filters and generate a report to preview it here.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default Reports
