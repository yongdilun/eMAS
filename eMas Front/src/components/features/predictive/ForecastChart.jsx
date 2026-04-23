// Fetches from GET /predictive/forecast?type=delays|failures
// Expected: { data: [{ label, value }] }
// Falls back to static demo SVG when endpoint unavailable
import { useState, useEffect } from 'react'
import { predictiveApi } from '../../../services/api'
import logger from '../../../services/logger'

const LABELS = ['12 AM', '4 AM', '8 AM', '12 PM', '4 PM', '8 PM', '12 AM']

const ForecastChart = ({ mode = 'Delays' }) => {
  const [pts, setPts] = useState(null)

  useEffect(() => {
    const type = mode === 'Delays' ? 'delays' : 'failures'
    predictiveApi.forecast({ type })
      .then(data => {
        const arr = Array.isArray(data) ? data : (data?.data ?? null)
        if (arr && arr.length > 0) {
          setPts(arr.map(d => ({
            label: d.label ?? d.time ?? d.hour ?? '—',
            value: d.value ?? d.count ?? d.probability ?? 0,
          })))
        }
      })
      .catch((err) => logger.debug('Forecast chart API unavailable; using static demo', { mode, message: err?.message }))
  }, [mode])

  if (pts && pts.length > 0) {
    const W = 472, H = 149, pad = 10
    const maxV = Math.max(...pts.map(p => p.value)) || 1
    const xStep = (W - pad * 2) / (pts.length - 1 || 1)
    const coords = pts.map((p, i) => ({
      x: pad + i * xStep,
      y: pad + (1 - p.value / maxV) * (H - pad * 2),
      ...p,
    }))
    const path = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ')
    const fill = `${path} L${coords[coords.length-1].x},${H} L${coords[0].x},${H} Z`

    return (
      <div className="mt-4 flex min-h-[250px] flex-col gap-4 pt-4">
        <svg fill="none" height="100%" preserveAspectRatio="none" viewBox={`-3 0 ${W} ${H}`} width="100%">
          <defs>
            <linearGradient id="fg" gradientUnits="userSpaceOnUse" x1="236" x2="236" y1="1" y2={H}>
              <stop stopColor="#00c3ff" stopOpacity="0.3"/>
              <stop offset="1" stopColor="#00c3ff" stopOpacity="0"/>
            </linearGradient>
          </defs>
          <path d={fill} fill="url(#fg)"/>
          <path d={path} stroke="#00c3ff" strokeLinecap="round" strokeWidth="3"/>
        </svg>
        <div className="flex justify-around">
          {pts.map(p => (
            <p key={p.label} className="text-xs font-bold text-zinc-400 dark:text-[#9ab4bc]">{p.label}</p>
          ))}
        </div>
      </div>
    )
  }

  // Static fallback SVG
  return (
    <div className="mt-4 flex min-h-[250px] flex-col gap-4 pt-4">
      <svg fill="none" height="100%" preserveAspectRatio="none" viewBox="-3 0 478 150" width="100%">
        <defs>
          <linearGradient gradientUnits="userSpaceOnUse" id="chartGradient" x1="236" x2="236" y1="1" y2="149">
            <stop stopColor="#00c3ff" stopOpacity="0.3"/>
            <stop offset="1" stopColor="#00c3ff" stopOpacity="0"/>
          </linearGradient>
        </defs>
        <path d="M0 109C18.1538 109 18.1538 21 36.3077 21C54.4615 21 54.4615 41 72.6154 41C90.7692 41 90.7692 93 108.923 93C127.077 93 127.077 33 145.231 33C163.385 33 163.385 101 181.538 101C199.692 101 199.692 61 217.846 61C236 61 236 45 254.154 45C272.308 45 272.308 121 290.462 121C308.615 121 308.615 149 326.769 149C344.923 149 344.923 1 363.077 1C381.231 1 381.231 81 399.385 81C417.538 81 417.538 129 435.692 129C453.846 129 453.846 25 472 25V149H0V109Z" fill="url(#chartGradient)"/>
        <path d="M0 109C18.1538 109 18.1538 21 36.3077 21C54.4615 21 54.4615 41 72.6154 41C90.7692 41 90.7692 93 108.923 93C127.077 93 127.077 33 145.231 33C163.385 33 163.385 101 181.538 101C199.692 101 199.692 61 217.846 61C236 61 236 45 254.154 45C272.308 45 272.308 121 290.462 121C308.615 121 308.615 149 326.769 149C344.923 149 344.923 1 363.077 1C381.231 1 381.231 81 399.385 81C417.538 81 417.538 129 435.692 129C453.846 129 453.846 25 472 25" stroke="#00c3ff" strokeLinecap="round" strokeWidth="3"/>
      </svg>
      <div className="flex justify-around">
        {LABELS.map(t => (
          <p key={t} className="text-xs font-bold text-zinc-400 dark:text-[#9ab4bc]">{t}</p>
        ))}
      </div>
    </div>
  )
}

export default ForecastChart
