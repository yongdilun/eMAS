// Fetches from GET /predictive/recommendations
// Expected: [{ title, action, icon?, severity? }]
// Falls back to demo data when endpoint unavailable
import { useState, useEffect } from 'react'
import { predictiveApi, toList } from '../../../services/api'
import logger from '../../../services/logger'

const DEMO = [
  { icon: 'auto_fix_high', title: 'Schedule pre-emptive maintenance on Coating Station 01 before next shift.', action: 'More Info'        },
  { icon: 'route',         title: 'Re-route JOB-2403 to Lathe 02 to avoid bottleneck on Lathe 01.',          action: 'Apply Suggestion' },
]

const AIRecommendations = () => {
  const [recs,    setRecs]    = useState(DEMO)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    predictiveApi.recommendations()
      .then(data => {
        const rows = toList(data)
        if (rows.length > 0) setRecs(rows)
      })
      .catch((err) => logger.debug('AI recommendations API unavailable; using demo data', { message: err?.message }))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-zinc-200 bg-white p-6 dark:border-[#394f56] dark:bg-[#101718]">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-zinc-900 dark:text-white">AI-Powered Recommendations</h2>
        {loading && <span className="w-4 h-4 border-2 border-gray-300 border-t-primary rounded-full animate-spin" />}
      </div>
      <ul className="flex flex-col gap-4">
        {recs.map((rec, i) => {
          const sv = (v, fb) => { const x = v; return x != null ? String(typeof x === 'object' ? (x.value ?? x.label ?? fb) : x) : fb }
          const icon   = sv(rec.icon,   'lightbulb')
          const title  = sv(rec.title ?? rec.recommendation ?? rec.message, '—')
          const action = sv(rec.action ?? rec.action_label, '')
          return (
            <li key={i} className="flex items-start gap-3">
              <span className="material-symbols-outlined mt-0.5 text-lg text-primary">{icon}</span>
              <div className="flex flex-col gap-0.5">
                <p className="text-sm font-medium text-zinc-900 dark:text-white leading-snug">{title}</p>
                {action && (
                  <button className="text-sm font-medium text-primary/80 hover:text-primary transition-colors text-left">
                    {action}
                  </button>
                )}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export default AIRecommendations
