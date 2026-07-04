import { useState, useEffect, useCallback } from 'react'
import ProductionOutputChart from '../components/features/charts/ProductionOutputChart'
import MachineUtilizationChart from '../components/features/charts/MachineUtilizationChart'
import JobTypeMixChart from '../components/features/charts/JobTypeMixChart'
import DowntimeAnalysisChart from '../components/features/charts/DowntimeAnalysisChart'
import PageHeader from '../components/shared/PageHeader'
import { productionAnalyticsApi, toList, toData, apiErrorMessage } from '../services/api'
import logger from '../services/logger'

const DATE_RANGES = [
  { label: 'Last 24h', days: 1 },
  { label: 'Last 7d', days: 7 },
  { label: 'Last 30d', days: 30 },
]

const toIso = (d) => d.toISOString()
const num = (value) => {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

const ProductionData = () => {
  const [rangeIdx, setRangeIdx] = useState(1)
  const [summary, setSummary] = useState(null)
  const [outputData, setOutputData] = useState([])
  const [utilizationData, setUtilData] = useState([])
  const [jobTypeData, setJobTypeData] = useState([])
  const [downtimeData, setDowntimeData] = useState([])
  const [loading, setLoading] = useState(false)
  const [fetchError, setFetchError] = useState('')

  const fetchAll = useCallback(async () => {
    setLoading(true)
    setFetchError('')
    const now = new Date()
    const start = new Date(now)
    start.setDate(now.getDate() - DATE_RANGES[rangeIdx].days)
    const params = { start: toIso(start), end: toIso(now) }

    try {
      const [summaryRes, out, util, jobs, down] = await Promise.allSettled([
        productionAnalyticsApi.summary(params),
        productionAnalyticsApi.output(params),
        productionAnalyticsApi.machineUtilization(params),
        productionAnalyticsApi.jobCompletion(params),
        productionAnalyticsApi.downtime(params),
      ])

      if (summaryRes.status === 'fulfilled') setSummary(toData(summaryRes.value) || {})
      else setSummary(null)

      if (out.status === 'fulfilled') setOutputData(toList(out.value))
      else setOutputData([])

      if (util.status === 'fulfilled') setUtilData(toList(util.value))
      else setUtilData([])

      if (jobs.status === 'fulfilled') setJobTypeData(toList(jobs.value))
      else setJobTypeData([])

      if (down.status === 'fulfilled') setDowntimeData(toList(down.value))
      else setDowntimeData([])

      const names = ['summary', 'productionOutput', 'machineUtilization', 'jobCompletion', 'downtime']
      ;[summaryRes, out, util, jobs, down].forEach((r, i) => {
        if (r.status === 'rejected') {
          logger.warn(`ProductionData: ${names[i]} unavailable`, { message: r.reason?.message })
        }
      })

      const allFailed = [summaryRes, out, util, jobs, down].every(r => r.status === 'rejected')
      if (allFailed) setFetchError('Production analytics could not be loaded.')
    } catch (err) {
      logger.error('Unexpected error loading production analytics', err)
      setFetchError(apiErrorMessage(err, 'Production analytics could not be loaded.'))
    } finally {
      setLoading(false)
    }
  }, [rangeIdx])

  useEffect(() => { fetchAll() }, [fetchAll])

  const totalOutput = num(summary?.total_output)
  const utilPct = num(summary?.avg_utilization_pct)
  const totalJobs = num(summary?.total_jobs)
  const totalDowntime = num(summary?.downtime_hours)

  return (
    <div className="flex-1 p-6 overflow-y-auto">
      <PageHeader title="Production Data Visualization" subtitle="Real production analytics from logged production data.">
        <button
          onClick={fetchAll}
          disabled={loading}
          className="flex items-center gap-2 h-10 px-4 bg-transparent border border-hairline text-ink text-sm font-bold rounded-lg hover:bg-surface-2 transition-colors disabled:opacity-50"
        >
          <span className={`material-symbols-outlined text-lg ${loading ? 'animate-spin' : ''}`}>refresh</span>
          <span>Refresh</span>
        </button>
      </PageHeader>

      {fetchError && (
        <div className="mb-4 flex items-center gap-2 px-4 py-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-lg text-sm text-amber-700 dark:text-amber-400">
          <span className="material-symbols-outlined text-base">warning</span>{fetchError}
        </div>
      )}

      <div className="flex flex-wrap gap-2 mb-4">
        <div className="flex h-8 items-center gap-0.5 rounded-lg bg-surface-1 p-0.5">
          {DATE_RANGES.map((r, i) => (
            <button
              key={i}
              onClick={() => setRangeIdx(i)}
              className={`px-3 h-full rounded-md text-xs font-medium transition-colors ${rangeIdx === i ? 'bg-surface-2 text-ink' : 'text-ink-subtle hover:text-ink'}`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard
          title="Production Output vs. Time"
          value={`${totalOutput.toLocaleString()} Units`}
          sub={DATE_RANGES[rangeIdx].label}
          loading={loading}
        >
          <ProductionOutputChart data={outputData} />
        </ChartCard>

        <ChartCard
          title="Machine Utilization"
          value={`${utilPct.toFixed(1)}%`}
          sub={DATE_RANGES[rangeIdx].label}
          loading={loading}
        >
          <MachineUtilizationChart data={utilizationData} />
        </ChartCard>

        <ChartCard
          title="Job Completion"
          value={`${totalJobs.toLocaleString()} Jobs`}
          sub={DATE_RANGES[rangeIdx].label}
          loading={loading}
        >
          <JobTypeMixChart data={jobTypeData} />
        </ChartCard>

        <ChartCard
          title="Downtime Cause Analysis"
          value={`${totalDowntime.toFixed(1)} Hours`}
          sub={DATE_RANGES[rangeIdx].label}
          loading={loading}
        >
          <DowntimeAnalysisChart data={downtimeData} />
        </ChartCard>
      </div>
    </div>
  )
}

const ChartCard = ({ title, value, sub, loading, children }) => (
  <div className="flex flex-col gap-1.5 rounded-lg border border-hairline p-4 bg-surface-1">
    <p className="text-ink text-sm font-medium leading-normal">{title}</p>
    <p className="text-ink tracking-light text-xl font-bold leading-tight truncate">
      {loading ? <span className="inline-block w-24 h-6 bg-surface-2 rounded animate-pulse" /> : value}
    </p>
    <p className="text-ink-subtle text-xs font-normal leading-normal">{sub}</p>
    {children}
  </div>
)

export default ProductionData
