import { useEffect, useMemo, useState } from 'react'
import CalendarPicker, { defaultReportDateRange } from '../components/features/reports/CalendarPicker'
import PageHeader from '../components/shared/PageHeader'
import {
  apiErrorMessage,
  inventoryApi,
  jobsApi,
  machinesApi,
  productsApi,
  reportsApi,
  toList,
} from '../services/api'
import {
  normalizeJob,
  normalizeMachine,
  normalizeMaterial,
  normalizeProduct,
} from '../services/normalizers'
import logger from '../services/logger'
import { useToast } from '../context/ToastContext'

const REPORT_TYPES = [
  { label: 'Production Output', key: 'production-output', api: reportsApi.productionOutput },
  { label: 'Machine Utilization', key: 'machine-utilization', api: reportsApi.machineUtilization },
  { label: 'Job Completion', key: 'job-completion', api: reportsApi.jobCompletion },
  { label: 'Inventory Trends', key: 'inventory-trends', api: reportsApi.inventoryTrends },
  { label: 'Quality Trends', key: 'quality-trends', api: reportsApi.qualityTrends },
  { label: 'OEE Trends', key: 'oee', api: reportsApi.oee },
  { label: 'Bottlenecks', key: 'bottlenecks', api: reportsApi.bottlenecks },
  { label: 'Downtime', key: 'downtime', api: reportsApi.downtime },
  { label: 'Maintenance Efficiency', key: 'maintenance-efficiency', api: reportsApi.maintenanceEfficiency },
]

const REPORT_FILTERS = {
  'production-output': { machine: true, job: true, product: true },
  'machine-utilization': { machine: true, job: true, product: true },
  'job-completion': { machine: true, job: true, product: true },
  'inventory-trends': { material: true },
  'quality-trends': {},
  oee: { machine: true },
  bottlenecks: { machine: true, job: true, product: true },
  downtime: { machine: true },
  'maintenance-efficiency': { machine: true },
}

const selectCls = 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-ink focus:outline-0 border border-hairline bg-surface-1 focus:border-l-primary focus:border-l-2 h-14 p-[15px] text-base font-normal leading-normal disabled:cursor-not-allowed disabled:opacity-60'
const fieldHintCls = 'pt-1 text-xs text-ink-subtle'

function dateRangeLabel(startDate, endDate) {
  if (!startDate && !endDate) return 'Default date range'
  if (startDate && endDate) return `${startDate} - ${endDate}`
  return startDate || endDate
}

function startIsoFromDateInput(value) {
  return value ? `${value}T00:00:00Z` : ''
}

function endIsoFromDateInput(value) {
  return value ? `${value}T23:59:59Z` : ''
}

function reportFilenameFallback(reportKey, startDate, endDate) {
  const safeType = String(reportKey || 'report').replace(/[^a-z0-9-]+/gi, '-').toLowerCase()
  const safeStart = startDate || 'start'
  const safeEnd = endDate || 'end'
  return `${safeType}-${safeStart}-${safeEnd}.pdf`
}

function normalizeOptions(rows, normalizer, idKey, labelKey) {
  return rows
    .map(normalizer)
    .map((item) => {
      const value = String(item?.[idKey] || '').trim()
      if (!value) return null
      const label = item?.[labelKey] && item[labelKey] !== value
        ? `${item[labelKey]} (${value})`
        : value
      return { value, label }
    })
    .filter(Boolean)
    .sort((a, b) => a.label.localeCompare(b.label))
}

function optionLabel(options, value) {
  if (!value) return ''
  return options.find((option) => option.value === value)?.label || value
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
  enabled,
  loading,
  allLabel,
  disabledHint,
}) {
  const fieldId = `report-filter-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
  return (
    <label htmlFor={fieldId} className="flex flex-col w-full">
      <p className="text-ink text-base font-medium leading-normal pb-2">{label}</p>
      <select
        id={fieldId}
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={!enabled || loading}
        className={selectCls}
      >
        <option value="">{loading ? 'Loading...' : allLabel}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value} className="bg-surface-1">
            {option.label}
          </option>
        ))}
      </select>
      {!enabled && <span className={fieldHintCls}>{disabledHint}</span>}
    </label>
  )
}

const Reports = () => {
  const toast = useToast()
  const initialRange = useMemo(() => defaultReportDateRange(), [])
  const [reportType, setReportType] = useState(REPORT_TYPES[0].key)
  const [machineId, setMachineId] = useState('')
  const [jobId, setJobId] = useState('')
  const [productId, setProductId] = useState('')
  const [materialId, setMaterialId] = useState('')
  const [startDate, setStartDate] = useState(initialRange.startDate)
  const [endDate, setEndDate] = useState(initialRange.endDate)
  const [lookupLoading, setLookupLoading] = useState(true)
  const [lookupError, setLookupError] = useState('')
  const [machineOptions, setMachineOptions] = useState([])
  const [jobOptions, setJobOptions] = useState([])
  const [productOptions, setProductOptions] = useState([])
  const [materialOptions, setMaterialOptions] = useState([])
  const [loading, setLoading] = useState(false)
  const [reportFile, setReportFile] = useState(null)
  const [error, setError] = useState('')
  const [filtersExpanded, setFiltersExpanded] = useState(false)

  const selectedReport = REPORT_TYPES.find((r) => r.key === reportType)
  const activeFilters = REPORT_FILTERS[reportType] || {}
  const displayRange = dateRangeLabel(startDate, endDate)
  const dateRangeValid = Boolean(startDate && endDate && startDate <= endDate)
  const hasAvailableFilters = Object.values(activeFilters).some(Boolean)
  const activeFilterLabels = useMemo(() => {
    const labels = []
    if (activeFilters.machine && machineId) labels.push(optionLabel(machineOptions, machineId))
    if (activeFilters.job && jobId) labels.push(optionLabel(jobOptions, jobId))
    if (activeFilters.product && productId) labels.push(optionLabel(productOptions, productId))
    if (activeFilters.material && materialId) labels.push(optionLabel(materialOptions, materialId))
    return labels.filter(Boolean)
  }, [activeFilters, machineId, jobId, productId, materialId, machineOptions, jobOptions, productOptions, materialOptions])
  const activeFilterSummary = activeFilterLabels.length
    ? activeFilterLabels.slice(0, 2).join(', ') + (activeFilterLabels.length > 2 ? ` +${activeFilterLabels.length - 2}` : '')
    : hasAvailableFilters ? 'None selected' : 'Not used'

  useEffect(() => {
    let cancelled = false
    setLookupLoading(true)
    setLookupError('')

    Promise.allSettled([
      machinesApi.list(),
      jobsApi.list({}),
      productsApi.list(),
      inventoryApi.list(),
    ]).then(([machines, jobs, products, materials]) => {
      if (cancelled) return
      if (machines.status === 'fulfilled') {
        setMachineOptions(normalizeOptions(toList(machines.value), normalizeMachine, 'machine_id', 'machine_name'))
      }
      if (jobs.status === 'fulfilled') {
        setJobOptions(normalizeOptions(toList(jobs.value), normalizeJob, 'job_id', 'job_id'))
      }
      if (products.status === 'fulfilled') {
        setProductOptions(normalizeOptions(toList(products.value), normalizeProduct, 'product_id', 'product_name'))
      }
      if (materials.status === 'fulfilled') {
        setMaterialOptions(normalizeOptions(toList(materials.value), normalizeMaterial, 'material_id', 'material_name'))
      }
      const failed = [machines, jobs, products, materials].some((result) => result.status === 'rejected')
      if (failed) setLookupError('Some filter options could not be loaded. You can still generate an unfiltered report.')
    }).finally(() => {
      if (!cancelled) setLookupLoading(false)
    })

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    return () => {
      if (reportFile?.url) URL.revokeObjectURL(reportFile.url)
    }
  }, [reportFile])

  useEffect(() => {
    setError('')
  }, [reportType, machineId, jobId, productId, materialId, startDate, endDate])

  useEffect(() => {
    const filters = REPORT_FILTERS[reportType] || {}
    if (!filters.machine) setMachineId('')
    if (!filters.job) setJobId('')
    if (!filters.product) setProductId('')
    if (!filters.material) setMaterialId('')
    if (!Object.values(filters).some(Boolean)) setFiltersExpanded(false)
  }, [reportType])

  const handleDateRangeChange = (range) => {
    setStartDate(range?.startDate || '')
    setEndDate(range?.endDate || '')
  }

  const handleClearFilters = () => {
    setMachineId('')
    setJobId('')
    setProductId('')
    setMaterialId('')
  }

  const handleGenerateReport = async () => {
    if (!selectedReport) return
    if (!dateRangeValid) {
      setError('Select a valid start and end date.')
      return
    }
    setLoading(true)
    setError('')
    setReportFile(null)

    const params = {
      start: startIsoFromDateInput(startDate),
      end: endIsoFromDateInput(endDate),
    }
    if (activeFilters.machine && machineId) params.machine_id = machineId
    if (activeFilters.job && jobId) params.job_id = jobId
    if (activeFilters.product && productId) params.product_id = productId
    if (activeFilters.material && materialId) params.material_id = materialId

    try {
      const file = await selectedReport.api(params)
      const fallbackFilename = reportFilenameFallback(reportType, startDate, endDate)
      const filename = file.filename && file.filename !== 'report.pdf' ? file.filename : fallbackFilename
      setReportFile({ ...file, filename, reportLabel: selectedReport.label, dateRange: displayRange })
      logger.info('PDF report generated', { type: reportType, filename, params })
      toast.success('PDF report generated.')
    } catch (err) {
      logger.error('Failed to generate PDF report', err, { type: reportType, params })
      setError(apiErrorMessage(err, 'Could not generate report.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <PageHeader title="Reports" subtitle="Generate PDF production reports." />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-1 flex flex-col gap-5">
          <label className="flex flex-col w-full">
            <p className="text-ink text-base font-medium leading-normal pb-2">Report Type</p>
            <select
              aria-label="Report Type"
              value={reportType}
              onChange={(e) => setReportType(e.target.value)}
              className={selectCls}
            >
              {REPORT_TYPES.map((r) => (
                <option key={r.key} value={r.key} className="bg-surface-1">{r.label}</option>
              ))}
            </select>
          </label>

          <CalendarPicker
            startDate={startDate}
            endDate={endDate}
            onDateRangeChange={handleDateRangeChange}
          />

          {(lookupError || error) && (
            <div className="flex items-start gap-2 px-3 py-2 bg-red-50 border border-red-200 dark:border-red-800 rounded-lg text-sm text-ink-muted">
              <span className="material-symbols-outlined text-base mt-0.5">error</span>
              <span>{error || lookupError}</span>
            </div>
          )}

          <button
            type="button"
            onClick={handleGenerateReport}
            disabled={loading || !dateRangeValid}
            className="w-full flex items-center justify-center gap-2 h-12 rounded-lg bg-primary text-white text-base font-bold hover:bg-primary/90 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {loading ? (
              <><span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />Generating...</>
            ) : (
              <><span className="material-symbols-outlined">picture_as_pdf</span>Generate PDF</>
            )}
          </button>

          <div className="overflow-hidden rounded-xl border border-hairline bg-surface-1">
            <button
              type="button"
              onClick={() => hasAvailableFilters && setFiltersExpanded((open) => !open)}
              disabled={!hasAvailableFilters}
              aria-expanded={filtersExpanded}
              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors enabled:hover:bg-surface-2 disabled:cursor-not-allowed"
            >
              <span className="flex min-w-0 items-center gap-3">
                <span className="material-symbols-outlined text-lg text-ink-muted">tune</span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-ink">Optional filters</span>
                  <span className="block truncate text-xs text-ink-subtle">{activeFilterSummary}</span>
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-2">
                {activeFilterLabels.length > 0 && (
                  <span className="rounded-md bg-primary px-2 py-1 text-xs font-semibold text-white">
                    {activeFilterLabels.length}
                  </span>
                )}
                {hasAvailableFilters && (
                  <span className={`material-symbols-outlined text-lg text-ink-muted transition-transform ${filtersExpanded ? 'rotate-180' : ''}`}>
                    expand_more
                  </span>
                )}
              </span>
            </button>

            {filtersExpanded && hasAvailableFilters && (
              <div className="flex flex-col gap-4 border-t border-hairline p-4">
                <FilterSelect
                  label="Machine ID"
                  value={machineId}
                  onChange={setMachineId}
                  options={machineOptions}
                  enabled={Boolean(activeFilters.machine)}
                  loading={lookupLoading}
                  allLabel="All machines"
                  disabledHint="This report does not use machine filtering."
                />

                <FilterSelect
                  label="Job ID"
                  value={jobId}
                  onChange={setJobId}
                  options={jobOptions}
                  enabled={Boolean(activeFilters.job)}
                  loading={lookupLoading}
                  allLabel="All jobs"
                  disabledHint="This report does not use job filtering."
                />

                <FilterSelect
                  label="Product ID"
                  value={productId}
                  onChange={setProductId}
                  options={productOptions}
                  enabled={Boolean(activeFilters.product)}
                  loading={lookupLoading}
                  allLabel="All products"
                  disabledHint="This report does not use product filtering."
                />

                <FilterSelect
                  label="Material ID"
                  value={materialId}
                  onChange={setMaterialId}
                  options={materialOptions}
                  enabled={Boolean(activeFilters.material)}
                  loading={lookupLoading}
                  allLabel="All materials"
                  disabledHint="Only inventory trend reports use material filtering."
                />

                <button
                  type="button"
                  onClick={handleClearFilters}
                  className="flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-hairline bg-surface-2 text-sm font-medium text-ink-muted transition-colors hover:bg-surface-3"
                >
                  <span className="material-symbols-outlined text-base">filter_alt_off</span>
                  Clear Filters
                </button>
              </div>
            )}
          </div>

        </div>

        <div className="lg:col-span-2 flex min-h-[70vh] flex-col rounded-lg border border-hairline bg-surface-1 overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-hairline px-4 py-3">
            <div className="min-w-0">
              <p className="text-ink text-sm font-semibold truncate">{reportFile?.reportLabel || selectedReport?.label || 'Report'}</p>
              <p className="text-ink-subtle text-xs truncate">{reportFile?.dateRange || displayRange}</p>
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
                title={`${reportFile.reportLabel || 'Report'} PDF preview`}
                src={reportFile.url}
                className="h-full min-h-[70vh] w-full bg-white"
              />
            ) : (
              <div className="h-full min-h-[520px] flex flex-col items-center justify-center gap-3 px-6 text-center text-ink-muted">
                <span className="material-symbols-outlined text-4xl">picture_as_pdf</span>
                <p className="text-sm font-medium text-ink">No PDF generated yet</p>
                <p className="max-w-sm text-xs">Choose a report, date range, and optional filters to preview it here.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default Reports
