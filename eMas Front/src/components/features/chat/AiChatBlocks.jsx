/**
 * Context card with embedded chart (e.g. OEE trend).
 */
export const AiChatContextCard = ({ title, chartData = [] }) => {
  if (!chartData?.length) return null
  const values = chartData.map((d) => d.y ?? d.value ?? 0)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const padding = 4
  const w = 280
  const h = 80
  const points = chartData
    .map((d, i) => {
      const x = padding + (i / Math.max(chartData.length - 1, 1)) * (w - padding * 2)
      const y = h - padding - ((d.y ?? d.value ?? 0) - min) / range * (h - padding * 2)
      return `${x},${y}`
    })
    .join(' ')

  return (
    <div className="mt-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-900 dark:bg-[#0d1214] p-3 text-xs">
      <div className="font-semibold text-gray-200 mb-2">{title}</div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-20" preserveAspectRatio="none">
        <polyline
          points={points}
          fill="none"
          stroke="rgb(96, 165, 250)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <polyline
          points={chartData.length > 1 ? points : ''}
          fill="none"
          stroke="rgb(248, 113, 113)"
          strokeWidth="1"
          strokeDasharray="4 2"
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity="0.8"
        />
      </svg>
      <div className="flex gap-4 mt-1 text-[10px] text-gray-400">
        <span className="flex items-center gap-1">
          <span className="w-2 h-0.5 bg-blue-400 rounded" />
          OEE (%)
        </span>
      </div>
    </div>
  )
}

/**
 * Presentational blocks for AI chat messages: result cards, assist, proposal, and action cards.
 */

const METHOD_STYLES = {
  GET: 'bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800',
  POST: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800',
  PUT: 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800',
  PATCH: 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800',
  DELETE: 'bg-red-500/15 text-red-700 dark:text-red-300 border-red-200 dark:border-red-800',
}

export const AiChatActionCard = ({ calls = [], onExecute, executingCallKey }) => {
  if (!calls.length) return null
  return (
    <div className="mt-3 space-y-2">
      {calls.map((call, i) => {
        const method = (call.method || 'GET').toUpperCase()
        const style = METHOD_STYLES[method] || METHOD_STYLES.GET
        const key = `${call.method}-${call.path}-${i}`
        const isExecuting = executingCallKey === key
        const needsApproval = true
        return (
          <div
            key={key}
            className="rounded-xl border border-gray-200/80 dark:border-gray-700/80 bg-white dark:bg-gray-800/80 p-3 shadow-sm"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <span className={`inline-flex px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wide border ${style}`}>
                  {method}
                </span>
                <p className="mt-1.5 text-sm text-gray-800 dark:text-gray-200">
                  {call.purpose || `${method} ${call.path}`}
                </p>
                <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400 break-all">
                  {call.path}
                </p>
              </div>
              <button
                type="button"
                onClick={() => onExecute(call, key)}
                disabled={isExecuting}
                className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-semibold bg-primary text-white hover:bg-primary/90 disabled:opacity-60 transition-colors"
              >
                {isExecuting ? (
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Running…
                  </span>
                ) : needsApproval ? 'Approve' : 'Run'}
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export const AiChatResultCard = ({ card }) => {
  if (card?.kind === 'oee_trend' && card?.chartData) {
    return <AiChatContextCard title={card.title || 'OEE Trend'} chartData={card.chartData} />
  }
  const tone =
    card.tone === 'critical'
      ? 'bg-red-500/10 text-red-600 dark:text-red-400'
      : card.tone === 'warning'
        ? 'bg-amber-500/10 text-amber-700 dark:text-amber-400'
        : card.tone === 'positive'
          ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
          : 'bg-blue-500/10 text-blue-600 dark:text-blue-400'

  return (
    <div className="mt-3 rounded-xl border border-gray-200/80 dark:border-gray-700/80 bg-white/90 dark:bg-gray-900/90 p-3.5 text-xs space-y-2 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold text-gray-800 dark:text-gray-100">
          {card.title || card.kind || 'Insight'}
        </div>
        <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${tone}`}>
          {card.tone || 'info'}
        </span>
      </div>
      {card.summary && (
        <p className="text-gray-700 dark:text-gray-300 text-xs leading-relaxed">{card.summary}</p>
      )}
      {Array.isArray(card.metrics) && card.metrics.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-1">
          {card.metrics.map((m, i) => (
            <div
              key={i}
              className="px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-800/80 text-gray-700 dark:text-gray-200"
            >
              <span className="font-semibold">{m.label}: </span>
              <span>{m.value}</span>
            </div>
          ))}
        </div>
      )}
      {Array.isArray(card.bullets) && card.bullets.length > 0 && (
        <ul className="list-disc list-inside text-gray-600 dark:text-gray-300 space-y-0.5">
          {card.bullets.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export const AiChatAssistBlock = ({ msg }) => {
  const data = msg.assist?.data || msg.assist || {}
  const delayRisk = data.delay_risk || {}
  return (
    <div className="mt-3 rounded-xl border border-indigo-200/80 dark:border-indigo-700/80 bg-indigo-50/70 dark:bg-indigo-900/25 p-3.5 text-xs space-y-1.5 shadow-sm">
      <div className="font-semibold text-indigo-800 dark:text-indigo-200">
        Scheduling assist for job {data.job_id || msg.jobId}
      </div>
      {delayRisk.risk_level && (
        <div className="text-gray-800 dark:text-gray-100">
          Risk level: <span className="font-semibold">{delayRisk.risk_level}</span>{' '}
          (score {delayRisk.risk_score})
        </div>
      )}
      {Array.isArray(data.explanation) && data.explanation.length > 0 && (
        <ul className="list-disc list-inside text-gray-700 dark:text-gray-300 space-y-0.5">
          {data.explanation.slice(0, 3).map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export const AiChatProposalBlock = ({ msg, onApprove, onApply }) => {
  const proposal = msg.proposal?.data || msg.proposal || {}
  const slots = proposal.proposed_slots || []
  return (
    <div className="mt-3 rounded-xl border border-emerald-200/80 dark:border-emerald-700/80 bg-emerald-50/70 dark:bg-emerald-900/25 p-3.5 text-xs space-y-2 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold text-emerald-800 dark:text-emerald-200">
          Proposal {proposal.proposal_id || ''} for job {proposal.job_id || msg.jobId}
        </div>
        <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/15 text-emerald-700 dark:text-emerald-300">
          {proposal.status || 'draft'}
        </span>
      </div>
      {Array.isArray(proposal.summary) && proposal.summary.length > 0 && (
        <ul className="list-disc list-inside text-gray-800 dark:text-gray-100 space-y-0.5">
          {proposal.summary.slice(0, 3).map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
      {slots.length > 0 && (
        <div className="mt-1 max-h-40 overflow-y-auto border border-emerald-200/60 dark:border-emerald-800/60 rounded-lg">
          <table className="w-full text-[11px]">
            <thead className="bg-emerald-100/60 dark:bg-emerald-900/40">
              <tr>
                <th className="px-2 py-1.5 text-left font-medium">Step</th>
                <th className="px-2 py-1.5 text-left font-medium">Machine</th>
                <th className="px-2 py-1.5 text-left font-medium">Start</th>
                <th className="px-2 py-1.5 text-left font-medium">End</th>
              </tr>
            </thead>
            <tbody>
              {slots.slice(0, 20).map((s, i) => (
                <tr key={i} className="border-t border-emerald-100/80 dark:border-emerald-800/80">
                  <td className="px-2 py-1.5">{s.step_name}</td>
                  <td className="px-2 py-1.5">{s.machine_name || s.machine_id}</td>
                  <td className="px-2 py-1.5">
                    {s.scheduled_start ? new Date(s.scheduled_start).toLocaleString() : '—'}
                  </td>
                  <td className="px-2 py-1.5">
                    {s.scheduled_end ? new Date(s.scheduled_end).toLocaleString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex gap-2 pt-2">
        <button
          type="button"
          onClick={() => onApprove(proposal)}
          className="px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 transition-colors"
        >
          Approve proposal
        </button>
        <button
          type="button"
          onClick={() => onApply(proposal)}
          className="px-3 py-1.5 rounded-lg bg-primary text-white text-xs font-semibold hover:bg-primary/90 transition-colors"
        >
          Apply to schedule
        </button>
      </div>
    </div>
  )
}
