import { useState, useEffect, useCallback } from 'react'
import ProductionOutputChart from '../components/features/charts/ProductionOutputChart'
import MachineUtilizationChart from '../components/features/charts/MachineUtilizationChart'
import JobTypeMixChart from '../components/features/charts/JobTypeMixChart'
import DowntimeAnalysisChart from '../components/features/charts/DowntimeAnalysisChart'
import PageHeader from '../components/shared/PageHeader'
import { reportsApi } from '../services/api'
import { unwrap } from '../services/normalizers'
import logger from '../services/logger'

const DATE_RANGES = [
  { label: 'Last 24h',  days: 1 },
  { label: 'Last 7d',   days: 7 },
  { label: 'Last 30d',  days: 30 },
]

const toIso = (d) => d.toISOString()

const ProductionData = () => {
  const [rangeIdx, setRangeIdx]           = useState(1)
  const [outputData, setOutputData]       = useState(null)
  const [utilizationData, setUtilData]    = useState(null)
  const [jobTypeData, setJobTypeData]     = useState(null)
  const [downtimeData, setDowntimeData]   = useState(null)
  const [loading, setLoading]             = useState(false)
  const [fetchError, setFetchError]       = useState('')

  const fetchAll = useCallback(async () => {
    setLoading(true); setFetchError('')
    const now   = new Date()
    const start = new Date(now); start.setDate(now.getDate() - DATE_RANGES[rangeIdx].days)
    const params = { start: toIso(start), end: toIso(now) }
    try {
      const [out, util, jobs, down] = await Promise.allSettled([
        reportsApi.productionOutput(params),
        reportsApi.machineUtilization(params),
        reportsApi.jobCompletion(params),
        reportsApi.bottlenecks(params),
      ])
      if (out.status   === 'fulfilled') setOutputData(unwrap(out.value)   ?? out.value)
      if (util.status  === 'fulfilled') setUtilData(unwrap(util.value)   ?? util.value)
      if (jobs.status  === 'fulfilled') setJobTypeData(unwrap(jobs.value) ?? jobs.value)
      if (down.status  === 'fulfilled') setDowntimeData(unwrap(down.value) ?? down.value)

      const names = ['productionOutput', 'machineUtilization', 'jobCompletion', 'bottlenecks']
      ;[out, util, jobs, down].forEach((r, i) => {
        if (r.status === 'rejected') {
          logger.warn(`ProductionData: ${names[i]} unavailable`, { message: r.reason?.message })
        }
      })

      const allFailed = [out, util, jobs, down].every(r => r.status === 'rejected')
      if (allFailed) setFetchError('All chart data failed to load. Showing demo data.')
    } catch (err) {
      logger.error('Unexpected error loading production data', err)
      setFetchError('Some chart data could not be loaded from server.')
    } finally { setLoading(false) }
  }, [rangeIdx])

  useEffect(() => { fetchAll() }, [fetchAll])

  // Summary stats derived from API data (fallback to demo values)
  // Accept multiple field name variants from backend
  const pf = (d, keys, fb) => { if (!d) return fb; for (const k of keys) if (d[k] != null) return Number(d[k]); return fb }
  const totalOutput   = pf(outputData,      ['total_units','totalUnits','units','total'],                           24180)
  const outputChange  = pf(outputData,      ['change_pct','changePct','change','pct_change'],                       5.2)
  const utilPct       = pf(utilizationData, ['avg_pct','avgPct','average_pct','avg','average'],                     85.2)
  const utilChange    = pf(utilizationData, ['change_pct','changePct','change'],                                    -1.8)
  const totalJobs     = pf(jobTypeData,     ['total_jobs','totalJobs','total','count'],                             1240)
  const jobsChange    = pf(jobTypeData,     ['change_pct','changePct','change'],                                    2.1)
  // Bottleneck API returns array — calculate a summary total queue/utilization
  const _dtArr = Array.isArray(downtimeData) ? downtimeData
    : Array.isArray(downtimeData?.data) ? downtimeData.data : null
  const _dtTotal = _dtArr ? _dtArr.reduce((s, d) => s + Number(d.queue_count ?? d.total_hours ?? d.hours ?? 0), 0) : null
  const totalDowntime = pf(downtimeData, ['total_hours','totalHours','total_downtime','hours','downtime_hours'], _dtTotal ?? 18.5)
  const downtimeChange = pf(downtimeData, ['change_pct','changePct','change'], 8.0)

  return (
    <div className="flex-1 p-6 overflow-y-auto">
      <PageHeader title="Production Data Visualization" subtitle="Real-time analytics and performance metrics.">
        <button
          onClick={fetchAll}
          disabled={loading}
          className="flex items-center gap-2 h-10 px-4 bg-transparent border border-gray-300 dark:border-gray-600 text-gray-800 dark:text-white text-sm font-bold rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors disabled:opacity-50"
        >
          <span className={`material-symbols-outlined text-lg ${loading ? 'animate-spin' : ''}`}>refresh</span>
          <span>Refresh</span>
        </button>
        <button
          className="flex items-center gap-2 h-10 px-4 bg-primary text-white text-sm font-bold rounded-lg hover:bg-primary/90 transition-colors"
        >
          <span className="material-symbols-outlined text-lg">download</span>
          <span>Export</span>
        </button>
      </PageHeader>

      {fetchError && (
        <div className="mb-4 flex items-center gap-2 px-4 py-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-xl text-sm text-amber-700 dark:text-amber-400">
          <span className="material-symbols-outlined text-base">warning</span>{fetchError} Showing demo data.
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-2 mb-4">
        {/* Date range toggle */}
        <div className="flex h-8 items-center gap-0.5 rounded-lg bg-gray-200 dark:bg-[#27363a] p-0.5">
          {DATE_RANGES.map((r, i) => (
            <button key={i} onClick={() => setRangeIdx(i)}
              className={`px-3 h-full rounded-md text-xs font-medium transition-colors ${rangeIdx === i ? 'bg-white dark:bg-[#101718] text-gray-900 dark:text-white shadow-sm' : 'text-gray-600 dark:text-[#9ab4bc] hover:text-gray-900 dark:hover:text-white'}`}>
              {r.label}
            </button>
          ))}
        </div>
        {['Machine Type', 'Shift Period', 'Status'].map((f) => (
          <button key={f} className="flex h-8 shrink-0 items-center justify-center gap-x-1.5 rounded-lg bg-gray-200 dark:bg-[#27363a] pl-3 pr-1.5 hover:bg-gray-300 dark:hover:bg-[#394f56] transition-colors">
            <p className="text-gray-900 dark:text-white text-xs font-medium">{f}</p>
            <span className="material-symbols-outlined text-sm text-gray-600 dark:text-white">expand_more</span>
          </button>
        ))}
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard
          title="Production Output vs. Time"
          value={`${totalOutput.toLocaleString()} Units`}
          sub={DATE_RANGES[rangeIdx].label}
          change={outputChange}
          loading={loading}
        >
          <ProductionOutputChart data={outputData} />
        </ChartCard>

        <ChartCard
          title="Machine Utilization"
          value={`${utilPct}%`}
          sub={DATE_RANGES[rangeIdx].label}
          change={utilChange}
          loading={loading}
        >
          <MachineUtilizationChart data={utilizationData} />
        </ChartCard>

        <ChartCard
          title="Job Type Mix"
          value={`${totalJobs.toLocaleString()} Jobs`}
          sub={DATE_RANGES[rangeIdx].label}
          change={jobsChange}
          loading={loading}
        >
          <JobTypeMixChart data={jobTypeData} />
        </ChartCard>

        <ChartCard
          title="Downtime Cause Analysis"
          value={`${totalDowntime} Hours`}
          sub={DATE_RANGES[rangeIdx].label}
          change={downtimeChange}
          loading={loading}
        >
          <DowntimeAnalysisChart data={downtimeData} />
        </ChartCard>
      </div>
    </div>
  )
}

const ChartCard = ({ title, value, sub, change, loading, children }) => {
  const positive = change >= 0
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-gray-200 dark:border-[#394f56] p-4 bg-white dark:bg-[#101718]">
      <p className="text-gray-900 dark:text-white text-sm font-medium leading-normal">{title}</p>
      <p className="text-gray-900 dark:text-white tracking-light text-xl font-bold leading-tight truncate">
        {loading ? <span className="inline-block w-24 h-6 bg-gray-200 dark:bg-gray-700 rounded animate-pulse"/> : value}
      </p>
      <div className="flex gap-1">
        <p className="text-gray-500 dark:text-[#9ab4bc] text-xs font-normal leading-normal">{sub}</p>
        {change != null && !loading && (
          <p className={`text-xs font-medium leading-normal ${positive ? 'text-green-500 dark:text-[#0bda57]' : 'text-red-500 dark:text-[#fa5f38]'}`}>
            {positive ? '+' : ''}{change}%
          </p>
        )}
      </div>
      {children}
    </div>
  )
}

export default ProductionData
