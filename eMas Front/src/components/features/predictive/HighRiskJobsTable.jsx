// Fetches from GET /predictive/high-risk-jobs
// Expected: [{ job_id, machine_id|machine_name, issue|predicted_issue, risk_level }]
// Shows an explicit unavailable state when endpoint data is unavailable.
import { useState, useEffect } from 'react'
import { predictiveApi, toList } from '../../../services/api'
import logger from '../../../services/logger'

const RISK_STYLE = {
  High: 'bg-primary/10 text-primary',
  Medium: 'bg-surface-2 text-ink-muted',
  Low: 'bg-semantic-success/10 text-semantic-success',
}

const HighRiskJobsTable = () => {
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    predictiveApi.highRiskJobs()
      .then(data => {
        const rows = toList(data)
        setJobs(rows)
      })
      .catch((err) => {
        logger.debug('High-risk jobs API unavailable', { message: err?.message })
        setError('High-risk job data is unavailable. No demo risk rows are being shown.')
        setJobs([])
      })
      .finally(() => setLoading(false))
  }, [])

  const s = (v, fb = '—') => { const x = v; return (x !== undefined && x !== null) ? String(typeof x === 'object' ? (x.value ?? x.label ?? x.name ?? fb) : x) : fb }
  const normalise = (j) => ({
    id: s(j.job_id ?? j.id),
    machine: s(j.machine_name ?? j.machine_id ?? j.machine),
    issue: s(j.issue ?? j.predicted_issue ?? j.reason),
    riskLevel: s(j.risk_level ?? j.riskLevel, 'Low'),
  })

  return (
    <div className="rounded-lg border border-hairline bg-surface-1 overflow-hidden">
      <div className="flex items-center justify-between border-b border-hairline px-4 py-3 bg-surface-2">
        <h2 className="text-lg font-semibold text-ink">High-Risk Jobs</h2>
        {loading && <span className="w-4 h-4 border-2 border-hairline border-t-primary rounded-full animate-spin" />}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm text-ink-muted">
          <thead className="text-xs uppercase text-ink-subtle bg-surface-1 border-b border-hairline">
            <tr>
              {['Job ID', 'Machine', 'Predicted Issue', 'Risk Level'].map(h => (
                <th key={h} className="px-5 py-3 font-semibold tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {!loading && jobs.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-5 py-8 text-center text-ink-subtle">
                  {error || 'No high-risk jobs returned.'}
                </td>
              </tr>
            ) : jobs.map((job) => {
              const r = normalise(job)
              return (
                <tr key={r.id} className="border-b border-hairline last:border-b-0 hover:bg-surface-2 transition-colors">
                  <td className="px-5 py-3 font-semibold text-ink whitespace-nowrap">{r.id}</td>
                  <td className="px-5 py-3 whitespace-nowrap text-ink-muted">{r.machine}</td>
                  <td className="px-5 py-3 text-ink-subtle">{r.issue}</td>
                  <td className="px-5 py-3">
                    <span className={`inline-flex items-center rounded-pill px-2.5 py-0.5 text-[11px] font-medium ${RISK_STYLE[r.riskLevel] ?? RISK_STYLE.Low}`}>
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
