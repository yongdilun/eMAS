// Fetches from GET /predictive/high-risk-jobs
// Expected: [{ job_id, machine_id|machine_name, issue|predicted_issue, risk_level }]
// Falls back to demo data when endpoint is unavailable (endpoint not yet implemented)
import { useState, useEffect } from 'react'
import { predictiveApi, toList } from '../../../services/api'
import logger from '../../../services/logger'

const DEMO = [
  { job_id: 'JOB-2403', machine_name: 'Coating Station 01', issue: 'Overdue Maintenance',  risk_level: 'High'   },
  { job_id: 'JOB-2406', machine_name: 'CNC Mill 02',        issue: 'High Load Duration',   risk_level: 'Medium' },
  { job_id: 'JOB-2401', machine_name: 'CNC Mill 01',        issue: 'Coolant Pressure Drop', risk_level: 'Low'  },
]

const RISK_STYLE = {
  High:   'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
  Medium: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  Low:    'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
}

const HighRiskJobsTable = () => {
  const [jobs,    setJobs]    = useState(DEMO)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    predictiveApi.highRiskJobs()
      .then(data => {
        const rows = toList(data)
        if (rows.length > 0) setJobs(rows)
      })
      .catch((err) => logger.debug('High-risk jobs API unavailable; using demo data', { message: err?.message }))
      .finally(() => setLoading(false))
  }, [])

  const s = (v, fb = '—') => { const x = v; return (x !== undefined && x !== null) ? String(typeof x === 'object' ? (x.value ?? x.label ?? x.name ?? fb) : x) : fb }
  const normalise = (j) => ({
    id:        s(j.job_id    ?? j.id),
    machine:   s(j.machine_name ?? j.machine_id ?? j.machine),
    issue:     s(j.issue ?? j.predicted_issue ?? j.reason),
    riskLevel: s(j.risk_level ?? j.riskLevel, 'Low'),
  })

  return (
    <div className="rounded-xl border border-zinc-200 bg-white dark:border-[#394f56] dark:bg-[#101718]">
      <div className="flex items-center justify-between border-b border-zinc-200 dark:border-[#394f56] px-4 py-3">
        <h2 className="text-lg font-bold text-zinc-900 dark:text-white">High-Risk Jobs</h2>
        {loading && <span className="w-4 h-4 border-2 border-gray-300 border-t-primary rounded-full animate-spin" />}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm text-zinc-500 dark:text-zinc-400">
          <thead className="text-xs uppercase text-zinc-600 dark:text-zinc-400 border-b border-zinc-100 dark:border-zinc-800">
            <tr>
              {['Job ID','Machine','Predicted Issue','Risk Level'].map(h => (
                <th key={h} className="px-5 py-3 font-semibold tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => {
              const r = normalise(job)
              return (
                <tr key={r.id} className="border-b border-zinc-100 dark:border-zinc-800 last:border-b-0 hover:bg-zinc-50 dark:hover:bg-white/5 transition-colors">
                  <td className="px-5 py-3 font-semibold text-zinc-900 dark:text-white whitespace-nowrap">{r.id}</td>
                  <td className="px-5 py-3 whitespace-nowrap">{r.machine}</td>
                  <td className="px-5 py-3">{r.issue}</td>
                  <td className="px-5 py-3">
                    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${RISK_STYLE[r.riskLevel] ?? RISK_STYLE.Low}`}>
                      {r.riskLevel}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default HighRiskJobsTable
