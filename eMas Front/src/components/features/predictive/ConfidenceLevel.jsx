// Fetches from GET /predictive/confidence
// Expected: { confidence_pct: 85 }  OR uses prop fallback
import { useState, useEffect } from 'react'
import { predictiveApi } from '../../../services/api'
import logger from '../../../services/logger'

const ConfidenceLevel = ({ percentage: propPct = 85 }) => {
  const [pct, setPct] = useState(propPct)

  useEffect(() => {
    predictiveApi.confidence()
      .then(data => {
        const v = data?.confidence_pct ?? data?.confidence ?? data?.pct ?? null
        if (v != null) setPct(Number(v))
      })
      .catch((err) => logger.debug('Confidence level API unavailable; using prop fallback', { message: err?.message }))
  }, [])

  const circumference = 2 * Math.PI * 52
  const offset = circumference - (pct / 100) * circumference
  const color = pct >= 80 ? 'text-primary' : pct >= 60 ? 'text-amber-400' : 'text-red-500'

  return (
    <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-zinc-200 bg-white p-6 text-center dark:border-[#394f56] dark:bg-[#101718]">
      <p className="text-lg font-medium text-zinc-900 dark:text-white">Model Confidence Level</p>
      <div className="relative flex h-32 w-32 items-center justify-center">
        <svg className="h-full w-full -rotate-90">
          <circle className="text-zinc-200 dark:text-[#27363a]" cx="64" cy="64" fill="transparent" r="52" stroke="currentColor" strokeWidth="10"/>
          <circle className={color} cx="64" cy="64" fill="transparent" r="52" stroke="currentColor"
            strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round" strokeWidth="10"/>
        </svg>
        <span className="absolute text-3xl font-bold text-zinc-900 dark:text-white">{pct}%</span>
      </div>
      <p className="text-sm text-zinc-500 dark:text-[#9ab4bc]">Confidence in current predictions</p>
    </div>
  )
}

export default ConfidenceLevel
