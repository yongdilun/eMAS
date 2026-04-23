import { useState, useEffect } from 'react'
import KPI from '../components/features/dashboard/KPI'
import Alert from '../components/features/dashboard/Alert'
import ProductionChart from '../components/features/dashboard/ProductionChart'
import QuickActions from '../components/features/dashboard/QuickActions'
import PageHeader from '../components/shared/PageHeader'
import { dashboardApi, alertsApi, reportsApi, toList, toData } from '../services/api'
import { debugResponse, unwrap } from '../services/normalizers'
import logger from '../services/logger'

// Fallback demo values shown until API responds
const DEMO_KPIS = {
  oee:         { value: '85.2%',        change: 1.5,  isPositive: true  },
  production:  { value: '10,450 units', change: 5.0,  isPositive: true  },
  downtime:    { value: '2.1 hrs',      change: 0.2,  isPositive: false },
  utilization: { value: '78%',          change: 2.5,  isPositive: true  },
}

const Dashboard = () => {
  const [kpis,      setKpis]      = useState(DEMO_KPIS)
  const [alerts,    setAlerts]    = useState([])
  const [chartData, setChartData] = useState(null)
  const [loading,   setLoading]   = useState(true)

  useEffect(() => {
    Promise.allSettled([
      dashboardApi.kpis(),
      alertsApi.list({ status: 'active' }),
      reportsApi.productionOutput(),
    ]).then(([kpiRes, alertRes, prodRes]) => {
      // ── KPIs from /dashboard/kpis ──────────────────────────────────────────
      if (kpiRes.status === 'fulfilled' && kpiRes.value) {
        const raw = kpiRes.value
        const d   = toData(raw) ?? unwrap(raw) ?? raw
        logger.info('Dashboard KPIs raw keys:', Object.keys(d || {}))
        logger.info('Dashboard KPIs loaded', d)
        const next = { ...DEMO_KPIS }
        // Accept any casing the backend uses
        const p = (keys) => { for (const k of keys) if (d[k] != null) return d[k]; return null }

        const oeePct     = p(['oee_pct','OeePct','oeePct','oee','OEE'])
        const prodUnits  = p(['production_units','ProductionUnits','productionUnits','units_produced','total_units'])
        const dtHrs      = p(['downtime_hrs','DowntimeHrs','downtimeHrs','downtime_hours','downtime'])
        const utilPct    = p(['utilization_pct','UtilizationPct','utilizationPct','utilization','utilization_rate'])
        const oeeCh      = p(['oee_change','OeeChange','oeeChange']) ?? 0
        const prodCh     = p(['production_change','ProductionChange','productionChange']) ?? 0
        const dtCh       = p(['downtime_change','DowntimeChange','downtimeChange']) ?? 0
        const utilCh     = p(['utilization_change','UtilizationChange','utilizationChange']) ?? 0

        if (oeePct    != null) next.oee        = { value: `${Number(oeePct).toFixed(1)}%`,                   change: Math.abs(oeeCh),  isPositive: oeeCh  >= 0 }
        if (prodUnits != null) next.production  = { value: `${Number(prodUnits).toLocaleString()} units`,     change: Math.abs(prodCh), isPositive: prodCh >= 0 }
        if (dtHrs     != null) next.downtime    = { value: `${Number(dtHrs).toFixed(1)} hrs`,                  change: Math.abs(dtCh),   isPositive: dtCh   <= 0 }
        if (utilPct   != null) next.utilization = { value: `${Number(utilPct).toFixed(1)}%`,                  change: Math.abs(utilCh), isPositive: utilCh >= 0 }
        setKpis(next)
      } else {
        logger.warn('Dashboard KPIs unavailable; using demo values', { reason: kpiRes.reason?.message })
      }

      // ── Alerts from /alerts ────────────────────────────────────────────────
      if (alertRes.status === 'fulfilled') {
        const rows = toList(alertRes.value)
        debugResponse('Alerts', alertRes.value)
        if (rows.length > 0) {
          setAlerts(rows.slice(0, 4).map(r => {
            const ap = (keys) => { for (const k of keys) if (r[k] != null) return r[k]; return null }
            return {
              type:  ap(['type','Type','alert_type','alertType','severity']) ?? 'info',
              title: ap(['title','Title','message','Message','description','name']) ?? ap(['machine_id','machineId']) ?? 'System alert',
              time:  ap(['time','Time','created_at','createdAt','timestamp']) ?? '',
            }
          }))
        }
      } else {
        logger.warn('Alerts unavailable', { reason: alertRes.reason?.message })
      }

      // ── Production chart data from /reports/production-output ──────────────
      if (prodRes.status === 'fulfilled' && prodRes.value) {
        setChartData(toData(prodRes.value) ?? prodRes.value)
      } else {
        logger.warn('Production output chart unavailable', { reason: prodRes.reason?.message })
      }
    }).finally(() => setLoading(false))
  }, [])

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <PageHeader
        title="Dashboard Overview"
        subtitle="Real-time factory performance at a glance."
      >
        <button className="p-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors">
          <span className="material-symbols-outlined">notifications</span>
        </button>
        <button className="p-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors">
          <span className="material-symbols-outlined">account_circle</span>
        </button>
      </PageHeader>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
        <KPI title="OEE"                 value={kpis.oee.value}         change={kpis.oee.change}         isPositive={kpis.oee.isPositive}         loading={loading} />
        <KPI title="Production Volume"   value={kpis.production.value}  change={kpis.production.change}  isPositive={kpis.production.isPositive}  loading={loading} />
        <KPI title="Downtime"            value={kpis.downtime.value}    change={kpis.downtime.change}    isPositive={kpis.downtime.isPositive}    loading={loading} />
        <KPI title="Machine Utilization" value={kpis.utilization.value} change={kpis.utilization.change} isPositive={kpis.utilization.isPositive} loading={loading} />
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Production Chart */}
        <div className="lg:col-span-2 flex flex-col gap-2 rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-white/5 p-6">
          <div className="flex justify-between items-start">
            <div>
              <p className="text-gray-900 dark:text-white text-lg font-medium">Production Output</p>
              <p className="text-gray-600 dark:text-white/60 text-sm">Last 24 Hours</p>
            </div>
            <div className="flex gap-1 items-center">
              <p className="text-gray-600 dark:text-white/60 text-sm">Total:</p>
              <p className="text-gray-900 dark:text-white text-sm font-bold">{kpis.production.value}</p>
              <p className={`text-sm font-medium ml-2 ${kpis.production.isPositive ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
                {kpis.production.isPositive ? '+' : '-'}{kpis.production.change}%
              </p>
            </div>
          </div>
          <ProductionChart data={chartData} />
        </div>

        {/* Side Panels */}
        <div className="flex flex-col gap-6">
          {/* Alerts Panel */}
          <div className="flex flex-col gap-4 rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-white/5 p-6">
            <div className="flex items-center justify-between">
              <p className="text-gray-900 dark:text-white text-lg font-medium">Active Alerts</p>
              {loading && (
                <span className="w-4 h-4 border-2 border-gray-300 border-t-primary rounded-full animate-spin" />
              )}
            </div>
            <div className="flex flex-col gap-4">
              {alerts.length > 0 ? (
                alerts.map((a, i) => (
                  <Alert key={i} type={a.type} title={a.title} time={a.time} />
                ))
              ) : (
                <>
                  <Alert type="error"   title="Machine #3 Overheating"        time="2 min ago"  />
                  <Alert type="warning" title="Low Supply Levels"              time="15 min ago" />
                  <Alert type="info"    title="Production Anomaly Detected"    time="45 min ago" />
                </>
              )}
            </div>
          </div>

          {/* Quick Actions */}
          <QuickActions />
        </div>
      </div>
    </div>
  )
}

export default Dashboard
