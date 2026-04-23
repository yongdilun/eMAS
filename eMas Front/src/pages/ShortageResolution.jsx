import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import PageHeader from '../components/shared/PageHeader'
import RecommendationCard from '../components/features/scheduling/RecommendationCard'
import ShortageTable from '../components/features/scheduling/ShortageTable'
import ResolutionSummaryBar from '../components/features/scheduling/ResolutionSummaryBar'
import { useToast } from '../context/ToastContext'
import {
  aiApi,
  apiErrorMessage,
  jobsApi,
  mergeBatchSummaryWithAggregate,
  toData,
  toList,
  unwrapSchedulingBatchPayload,
} from '../services/api'
import {
  APPLY_REPLENISHMENT_DUPLICATE_WINDOW_NUDGE_MS,
  applyReplenishmentClientNotice,
  applyReplenishmentDuplicateSkipTotal,
  buildAggregateApplySuggestions,
  buildApplyPayload,
  extractBatchShortageAggregate,
  isApplyReplenishmentSuggestion,
  mapRecommendationToApplyItem,
  normalizeBatchAggregateLines,
  nudgeApplyReplenishmentSuggestionsArriveAt,
  normalizeRecommendation,
  recommendationQtyFromDraft,
} from '../services/normalizers'

/** Legacy per-proposal apply: stagger times to dodge duplicate-window skips when no batch aggregate API. */
const APPLY_DEDUPE_MAX_OFFSET_STEPS = 24

const toLocalInput = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const toIso = (local) => {
  if (!local) return null
  const d = new Date(local)
  if (Number.isNaN(d.getTime())) return null
  return d.toISOString()
}

const ShortageResolution = ({
  seedProposals = null,
  batchSummary: batchSummaryProp = null,
  embedded = false,
  onClose,
  onApplySuccess,
  orderBy = 'epo',
}) => {
  const toast = useToast()
  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)
  const [proposals, setProposals] = useState([])
  const [selectedProposalId, setSelectedProposalId] = useState('')
  const [focusedEntityId, setFocusedEntityId] = useState('')
  const [drafts, setDrafts] = useState({})
  const [showOnlyInfeasible, setShowOnlyInfeasible] = useState(true)
  const [showOnlyWithSuggestions, setShowOnlyWithSuggestions] = useState(true)
  const [localBatchSummary, setLocalBatchSummary] = useState(null)
  const [aggDrafts, setAggDrafts] = useState({})
  const [useBatchAggregateApply, setUseBatchAggregateApply] = useState(true)

  const [showDrillDown, setShowDrillDown] = useState(false)

  const effectiveBatchSummary = localBatchSummary ?? batchSummaryProp

  /** Server-supported batch qty/time; when set, legacy per-proposal apply skips +31m time nudging. */
  const hasServerMaterialReplenishmentAggregate = useMemo(() => {
    const mr =
      effectiveBatchSummary?.material_replenishment_aggregate ??
      effectiveBatchSummary?.materialReplenishmentAggregate
    return Array.isArray(mr) && mr.length > 0
  }, [effectiveBatchSummary])

  useEffect(() => {
    if (hasServerMaterialReplenishmentAggregate) {
      setUseBatchAggregateApply(true)
    }
  }, [hasServerMaterialReplenishmentAggregate])

  const extractRecommendations = (proposal) => {
    const primary = proposal?.shortage_resolutions || []
    const fallback = (proposal?.material_shortages || []).flatMap((s) => s?.per_material_resolutions || [])
    const normalized = [
      ...primary.map((r) => normalizeRecommendation(r, 'shortage_resolutions')),
      ...fallback.map((r) => normalizeRecommendation(r, 'per_material_resolutions')),
    ]
      .filter((r) => {
        const hasSignal =
          (r?.entity_id && r.entity_id !== 'unknown') ||
          (r?.suggested_qty ?? 0) > 0 ||
          !!r?.suggested_arrive_at ||
          !!r?.rationale
        return hasSignal
      })

    const seen = new Set()
    return normalized
      .filter((r) => {
        const sig = [
          proposal?.proposal_id || '',
          r?.entity_id || '',
          r?.dependency_product_id ?? '',
          r?.option_type || '',
          String(r?.suggested_qty ?? ''),
          String(r?.suggested_arrive_at ?? ''),
          String(r?.rationale ?? ''),
        ].join('|')
        if (seen.has(sig)) return false
        seen.add(sig)
        return true
      })
      .map((r, idx) => ({
        ...r,
        proposal_id: proposal?.proposal_id,
        job_id: proposal?.job_id,
        key: `${proposal?.proposal_id || 'no-proposal'}__${r.entity_id}__${r.dependency_product_id ?? ''}__${r.option_type}__${idx}`,
      }))
  }

  const loadDraftProposals = useCallback(async () => {
    setLoading(true)
    try {
      const jobs = toList(await jobsApi.list({}))
      const jobIds = jobs.map((j) => j.job_id || j.jobId || j.id).filter(Boolean)
      const results = await Promise.allSettled(jobIds.map((id) => aiApi.scheduling.listProposals(id)))
      const next = []
      results.forEach((res, idx) => {
        if (res.status !== 'fulfilled') return
        const list = toList(toData(res.value) || res.value)
        const draft = list.find((p) => (p.status || 'draft') === 'draft')
        if (!draft?.proposal_id) return
        next.push({ ...draft, job_id: draft.job_id || jobIds[idx] })
      })
      setProposals(next)
      const first = next.find((p) => p.feasible === false && extractRecommendations(p).length > 0) || next[0]
      setSelectedProposalId(first?.proposal_id || '')
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Failed to load shortage proposals.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (Array.isArray(seedProposals) && seedProposals.length > 0) {
      setProposals(seedProposals)
      const first = seedProposals.find((p) => p.feasible === false && extractRecommendations(p).length > 0) || seedProposals[0]
      setSelectedProposalId(first?.proposal_id || '')
      return
    }
    loadDraftProposals()
  }, [loadDraftProposals, seedProposals])

  const batchAggregate = useMemo(
    () => extractBatchShortageAggregate(effectiveBatchSummary),
    [effectiveBatchSummary],
  )

  const normalizedAggregateLines = useMemo(
    () => normalizeBatchAggregateLines(batchAggregate.byMaterial, batchAggregate.byProduct),
    [batchAggregate.byMaterial, batchAggregate.byProduct],
  )

  const hasAggregateLines = normalizedAggregateLines.length > 0

  useEffect(() => {
    if (!hasAggregateLines) setUseBatchAggregateApply(false)
  }, [hasAggregateLines])

  useEffect(() => {
    setAggDrafts((prev) => {
      const next = { ...prev }
      normalizedAggregateLines.forEach((line) => {
        if (next[line.key] !== undefined) return
        next[line.key] = {
          selected: true,
          qty: line.qty,
          arriveAtLocal: toLocalInput(line.arrive_at),
        }
      })
      return next
    })
  }, [normalizedAggregateLines])

  const aggregateApplySuggestions = useMemo(
    () => buildAggregateApplySuggestions(normalizedAggregateLines, aggDrafts),
    [normalizedAggregateLines, aggDrafts],
  )

  const filteredProposals = useMemo(() => {
    return proposals.filter((p) => {
      if (showOnlyInfeasible && p.feasible !== false) return false
      const hasSuggestions = extractRecommendations(p).length > 0
      if (showOnlyWithSuggestions && !hasSuggestions) return false
      return true
    })
  }, [proposals, showOnlyInfeasible, showOnlyWithSuggestions])

  const selectedProposal = useMemo(
    () => filteredProposals.find((p) => p.proposal_id === selectedProposalId) || proposals.find((p) => p.proposal_id === selectedProposalId) || null,
    [filteredProposals, proposals, selectedProposalId],
  )

  const recommendations = useMemo(
    () => (selectedProposal ? extractRecommendations(selectedProposal) : []),
    [selectedProposal],
  )

  useEffect(() => {
    if (filteredProposals.length === 0) return
    setDrafts((prev) => {
      const next = { ...prev }
      filteredProposals.forEach((proposal) => {
        const recs = extractRecommendations(proposal)
        recs.forEach((rec) => {
          if (next[rec.key]) return
          next[rec.key] = {
            selected: true,
            qty: rec.suggested_qty || '',
            arriveAtLocal: toLocalInput(rec.suggested_arrive_at),
          }
        })
      })
      return next
    })
  }, [filteredProposals])

  const selectedRecommendationsCurrent = useMemo(() => {
    return recommendations
      .map((rec) => {
        const d = drafts[rec.key] || {}
        return {
          ...rec,
          selected: d.selected === true,
          selected_qty: recommendationQtyFromDraft(d, rec),
          selected_arrive_at: toIso(d.arriveAtLocal) || rec.suggested_arrive_at,
        }
      })
      .filter((rec) => rec.selected)
  }, [recommendations, drafts])

  const selectedRecommendationsAll = useMemo(() => {
    return filteredProposals
      .flatMap((proposal) => extractRecommendations(proposal))
      .map((rec) => {
        const d = drafts[rec.key] || {}
        return {
          ...rec,
          selected: d.selected === true,
          selected_qty: recommendationQtyFromDraft(d, rec),
          selected_arrive_at: toIso(d.arriveAtLocal) || rec.suggested_arrive_at,
        }
      })
      .filter((rec) => rec.selected)
  }, [filteredProposals, drafts])

  const selectedApplyReadyCount = selectedRecommendationsAll.filter((r) => isApplyReplenishmentSuggestion(r)).length
  const aggregateApplyReadyCount = aggregateApplySuggestions.length
  const blockedJobs = proposals.filter((p) => p.feasible === false).length

  const totalDeficit = (selectedProposal?.material_shortages || []).reduce((sum, s) => sum + Number(s.max_deficit ?? 0), 0)

  const handleDraftChange = (key, field, value) => {
    setDrafts((prev) => ({
      ...prev,
      [key]: { ...(prev[key] || {}), [field]: value },
    }))
  }

  const handleAggregateDraftChange = (key, field, value) => {
    setAggDrafts((prev) => ({
      ...prev,
      [key]: { ...(prev[key] || {}), [field]: value },
    }))
  }

  const resetAllDrafts = useCallback(() => {
    setDrafts({})
    const next = {}
    normalizedAggregateLines.forEach((line) => {
      next[line.key] = {
        selected: true,
        qty: line.qty,
        arriveAtLocal: toLocalInput(line.arrive_at),
      }
    })
    setAggDrafts(next)
  }, [normalizedAggregateLines])

  const refreshAnalysis = async () => {
    if (!selectedProposal?.job_id) return
    setActionLoading(true)
    try {
      const res = await aiApi.scheduling.shortageAnalysis(selectedProposal.job_id)
      const data = toData(res) || res
      setProposals((prev) => prev.map((p) => {
        if (p.proposal_id !== selectedProposal.proposal_id) return p
        return {
          ...p,
          material_shortages: data?.shortages || p.material_shortages || [],
          shortage_resolutions: data?.resolution_options || data?.replenishment_suggestions || p.shortage_resolutions || [],
          global_score: data?.global_score ?? p.global_score,
        }
      }))
      toast.success('Shortage analysis refreshed.')
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Failed to refresh shortage analysis.'))
    } finally {
      setActionLoading(false)
    }
  }

  /** When `allowTimeNudge` is false (batch has `material_replenishment_aggregate`), one attempt per proposal — no +31m stagger. */
  const applyLegacyGroupedWithNudge = async (groupedByProposal, allowTimeNudge = true) => {
    const applyWarnTexts = []
    const applyInfoTexts = []
    let applyCalls = 0
    for (const proposalId of Object.keys(groupedByProposal)) {
      const suggestions = groupedByProposal[proposalId].filter((s) => s.quantity > 0 && !!s.arrive_at)
      if (suggestions.length === 0) continue
      applyCalls += 1
      let appliedData
      let notice = null
      if (!allowTimeNudge) {
        const rawApply = await aiApi.scheduling.applyReplenishment(proposalId, { suggestions })
        appliedData = toData(rawApply) || rawApply
        notice = applyReplenishmentClientNotice(appliedData)
      } else {
        let offsetMs = 0
        for (let step = 0; step < APPLY_DEDUPE_MAX_OFFSET_STEPS; step += 1) {
          const rows = nudgeApplyReplenishmentSuggestionsArriveAt(suggestions, offsetMs)
          const rawApply = await aiApi.scheduling.applyReplenishment(proposalId, { suggestions: rows })
          appliedData = toData(rawApply) || rawApply
          const dup = applyReplenishmentDuplicateSkipTotal(appliedData)
          const stalled = appliedData?.any_new_records === false && dup > 0
          if (!stalled) {
            notice = applyReplenishmentClientNotice(appliedData)
            break
          }
          offsetMs += APPLY_REPLENISHMENT_DUPLICATE_WINDOW_NUDGE_MS
          if (step === APPLY_DEDUPE_MAX_OFFSET_STEPS - 1) {
            notice = applyReplenishmentClientNotice(appliedData)
          }
        }
      }
      if (notice?.level === 'warn') applyWarnTexts.push(notice.text)
      else if (notice?.level === 'info') applyInfoTexts.push(notice.text)
    }
    return { applyCalls, applyWarnTexts, applyInfoTexts }
  }

  const rescheduleAllWithoutApply = async () => {
    setActionLoading(true)
    try {
      const resp = await aiApi.scheduling.rescheduleAll({ order_by: orderBy })
      const u = unwrapSchedulingBatchPayload(resp)
      const { proposals: proposalsList, summary, byMaterial, byProduct, materialReplenishmentAggregate } = u
      setLocalBatchSummary(
        mergeBatchSummaryWithAggregate({ summary, byMaterial, byProduct, materialReplenishmentAggregate }),
      )
      if (embedded && typeof onApplySuccess === 'function') {
        setDrafts({})
        await Promise.resolve(onApplySuccess(resp))
        return
      }
      if (Array.isArray(proposalsList) && proposalsList.length > 0) {
        setProposals(proposalsList)
        const first = proposalsList.find((p) => extractRecommendations(p).length > 0) || proposalsList[0]
        setSelectedProposalId(first?.proposal_id || '')
      } else {
        await loadDraftProposals()
      }
      setDrafts({})
      toast.success('Schedule regenerated (no material arrivals applied).')
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Failed to reschedule.'))
    } finally {
      setActionLoading(false)
    }
  }

  const applyAndReplanAll = async () => {
    const legacyArrivals = buildApplyPayload(selectedRecommendationsAll)
    const useAggregate = useBatchAggregateApply && hasAggregateLines && aggregateApplySuggestions.length > 0
    const useLegacy = !useAggregate && legacyArrivals.length > 0

    if (!useAggregate && !useLegacy) {
      if (selectedRecommendationsAll.length === 0 && !hasAggregateLines) {
        toast.info('Select at least one recommendation (Include), or adjust filters.')
      } else if (useBatchAggregateApply && hasAggregateLines && aggregateApplySuggestions.length === 0) {
        toast.info('Enable at least one batch row with quantity and arrival time, or switch to per-job cards.')
      } else {
        const noneApplyEligible = selectedRecommendationsAll.every((r) => !isApplyReplenishmentSuggestion(r))
        if (noneApplyEligible) {
          toast.info(
            'No selected rows are apply-replenishment eligible (replenish or schedule_production with qty and time). Use "Reschedule all (no material apply)" or refresh analysis for options.',
          )
        } else {
          toast.info('No apply rows with quantity and arrival time. Edit qty/time on included recommendations.')
        }
      }
      return
    }

    setActionLoading(true)
    try {
      let applyCalls = 0
      const applyWarnTexts = []
      const applyInfoTexts = []

      if (useAggregate) {
        const anchor =
          batchAggregate.anchorProposalId ||
          proposals.find((p) => p.feasible === false && p.proposal_id)?.proposal_id ||
          proposals.find((p) => p.proposal_id)?.proposal_id
        let aggregateNotice = null
        try {
          const rawBatch = await aiApi.scheduling.applyReplenishmentBatch({
            suggestions: aggregateApplySuggestions,
            order_by: orderBy,
          })
          applyCalls += 1
          const appliedData = toData(rawBatch) || rawBatch
          aggregateNotice = applyReplenishmentClientNotice(appliedData)
        } catch (err) {
          if (err.status === 404) {
            if (!anchor) {
              toast.error(
                'Batch replenishment API is not available yet, and no anchor proposal_id was found for a single apply-replenishment call.',
              )
              setActionLoading(false)
              return
            }
            const rawApply = await aiApi.scheduling.applyReplenishment(anchor, {
              suggestions: aggregateApplySuggestions,
            })
            applyCalls += 1
            const appliedData = toData(rawApply) || rawApply
            aggregateNotice = applyReplenishmentClientNotice(appliedData)
          } else {
            throw err
          }
        }
        if (aggregateNotice?.level === 'warn') applyWarnTexts.push(aggregateNotice.text)
        else if (aggregateNotice?.level === 'info') applyInfoTexts.push(aggregateNotice.text)
      } else {
        const groupedByProposal = selectedRecommendationsAll.reduce((acc, rec) => {
          const item = mapRecommendationToApplyItem(rec)
          if (!item || !rec.proposal_id) return acc
          if (!acc[rec.proposal_id]) acc[rec.proposal_id] = []
          acc[rec.proposal_id].push(item)
          return acc
        }, {})
        const legacy = await applyLegacyGroupedWithNudge(
          groupedByProposal,
          !hasServerMaterialReplenishmentAggregate,
        )
        applyCalls = legacy.applyCalls
        applyWarnTexts.push(...legacy.applyWarnTexts)
        applyInfoTexts.push(...legacy.applyInfoTexts)
      }

      if (applyCalls === 0) {
        toast.error(
          'No replenishment calls were made. Selected rows may not be material arrivals, or qty/time is missing.',
        )
        return
      }
      if (applyWarnTexts.length > 0) {
        toast.warning(applyWarnTexts[0])
      } else if (applyInfoTexts.length > 0) {
        toast.info([...new Set(applyInfoTexts)].join(' '))
      }

      const resp = await aiApi.scheduling.rescheduleAll({ order_by: orderBy })
      const u = unwrapSchedulingBatchPayload(resp)
      const { proposals: proposalsList, summary, byMaterial, byProduct, materialReplenishmentAggregate } = u
      setLocalBatchSummary(
        mergeBatchSummaryWithAggregate({ summary, byMaterial, byProduct, materialReplenishmentAggregate }),
      )
      if (embedded && typeof onApplySuccess === 'function') {
        setDrafts({})
        await Promise.resolve(onApplySuccess(resp))
        return
      }
      if (Array.isArray(proposalsList) && proposalsList.length > 0) {
        setProposals(proposalsList)
        const first = proposalsList.find((p) => extractRecommendations(p).length > 0) || proposalsList[0]
        setSelectedProposalId(first?.proposal_id || '')
      } else {
        await loadDraftProposals()
      }
      setDrafts({})
      toast.success(`Applied selected arrivals and regenerated schedule.`)
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Failed to apply selected arrivals and reschedule.'))
    } finally {
      setActionLoading(false)
    }
  }

  const summaryReplenishCount = useBatchAggregateApply && hasAggregateLines ? aggregateApplyReadyCount : selectedApplyReadyCount
  const summarySelectedCount =
    useBatchAggregateApply && hasAggregateLines
      ? normalizedAggregateLines.filter((l) => aggDrafts[l.key]?.selected !== false).length
      : selectedRecommendationsAll.length

  return (
    <div className={`${embedded ? 'h-full' : 'p-6'} flex flex-col min-h-0`}>
      <PageHeader
        title="Shortage Resolution Center"
        subtitle="Resolve blocked jobs in one page with editable recommended arrivals and bulk-assisted actions."
      >
        {embedded ? (
          <button
            type="button"
            onClick={onClose}
            className="h-9 px-3 rounded-md border border-gray-300 dark:border-gray-600 text-sm inline-flex items-center"
          >
            Close
          </button>
        ) : (
          <Link to="/scheduling" className="h-9 px-3 rounded-md border border-gray-300 dark:border-gray-600 text-sm inline-flex items-center">
            Back to Scheduling
          </Link>
        )}
      </PageHeader>

      <div className="mb-3 flex flex-wrap gap-2 items-center">
        <label className="text-xs inline-flex items-center gap-1">
          <input type="checkbox" checked={showOnlyInfeasible} onChange={(e) => setShowOnlyInfeasible(e.target.checked)} />
          Infeasible only
        </label>
        <label className="text-xs inline-flex items-center gap-1">
          <input type="checkbox" checked={showOnlyWithSuggestions} onChange={(e) => setShowOnlyWithSuggestions(e.target.checked)} />
          Has suggestions
        </label>
        {!embedded && (
          <button
            type="button"
            onClick={loadDraftProposals}
            disabled={loading}
            className="h-8 px-3 rounded-md border border-gray-300 dark:border-gray-600 text-xs"
          >
            {loading ? 'Loading…' : 'Reload proposals'}
          </button>
        )}
      </div>

      {hasAggregateLines && (
        <div className="mb-6 rounded-xl border border-emerald-200 dark:border-emerald-800 bg-white dark:bg-gray-900 shadow-sm overflow-hidden">
          <div className="bg-emerald-50/50 dark:bg-emerald-950/20 px-4 py-3 border-b border-emerald-100 dark:border-emerald-900 flex justify-between items-center">
            <div>
              <h3 className="text-sm font-bold text-emerald-900 dark:text-emerald-100 flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500 text-[10px] text-white">
                  {normalizedAggregateLines.length}
                </span>
                Unified Material Shortage Resolution
              </h3>
              <p className="text-[11px] text-emerald-700 dark:text-emerald-300 mt-0.5">
                Aggregated demand across all impacted jobs. Applying creates a single arrival record for each material.
              </p>
            </div>
            <label className="flex items-center gap-2 cursor-pointer text-xs font-medium text-emerald-800 dark:text-emerald-200">
              <input
                type="checkbox"
                checked={useBatchAggregateApply}
                onChange={(e) => setUseBatchAggregateApply(e.target.checked)}
                className="rounded text-emerald-600 focus:ring-emerald-500"
              />
              Use Unified Mode
            </label>
          </div>
          
          {useBatchAggregateApply && (
            <div className="p-4">
              <div className="grid grid-cols-12 gap-4 mb-2 px-2 text-[10px] font-bold text-gray-500 uppercase tracking-wider">
                <div className="col-span-4">Material / Component</div>
                <div className="col-span-2">Required Qty</div>
                <div className="col-span-3">Suggested Arrival</div>
                <div className="col-span-3">Impacted Jobs</div>
              </div>
              <div className="space-y-2 max-h-[40vh] overflow-y-auto pr-2">
                {normalizedAggregateLines.map((line) => {
                  const d = aggDrafts[line.key] || {}
                  return (
                    <div
                      key={line.key}
                      className={`grid grid-cols-12 gap-4 items-center p-3 rounded-lg border transition-all ${
                        d.selected !== false 
                          ? 'border-emerald-200 bg-emerald-50/30 dark:border-emerald-800/50 dark:bg-emerald-900/10' 
                          : 'border-gray-100 bg-gray-50/50 dark:border-gray-800 dark:bg-gray-900/50 opacity-60'
                      }`}
                    >
                      <div className="col-span-4 flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={d.selected !== false}
                          onChange={(e) => handleAggregateDraftChange(line.key, 'selected', e.target.checked)}
                          className="rounded text-emerald-600 focus:ring-emerald-500"
                        />
                        <div className="min-w-0">
                          <div className="font-bold text-sm truncate" title={line.material_name || line.material_id}>
                            {line.material_name || line.material_id}
                          </div>
                          <div className="text-[10px] font-mono opacity-60 flex items-center gap-1">
                            {line.material_id}
                            <span className={`px-1 rounded-[4px] ${line.kind === 'schedule_production' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300' : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'}`}>
                              {line.kind === 'schedule_production' ? 'Plan Production' : 'Material'}
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="col-span-2">
                        <div className="relative">
                          <input
                            type="number"
                            className="w-full h-8 pl-2 pr-1 text-sm font-medium rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none transition-all"
                            value={d.qty ?? line.qty}
                            onChange={(e) => handleAggregateDraftChange(line.key, 'qty', e.target.value)}
                            disabled={d.selected === false}
                          />
                        </div>
                      </div>

                      <div className="col-span-3">
                        <input
                          type="datetime-local"
                          className="w-full h-8 px-2 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none transition-all"
                          value={d.arriveAtLocal ?? toLocalInput(line.arrive_at)}
                          onChange={(e) => handleAggregateDraftChange(line.key, 'arriveAtLocal', e.target.value)}
                          disabled={d.selected === false}
                        />
                        {line.earliest_possible_arrival && (
                          <div className="text-[9px] mt-1 text-gray-500">
                            Earliest: {new Date(line.earliest_possible_arrival).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}
                          </div>
                        )}
                      </div>

                      <div className="col-span-3">
                        {line.affected_job_ids?.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {line.affected_job_ids.slice(0, 4).map(jobId => (
                              <span key={jobId} className="px-1.5 py-0.5 rounded bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-[9px] font-medium text-gray-600 dark:text-gray-400">
                                {jobId}
                              </span>
                            ))}
                            {line.affected_job_ids.length > 4 && (
                              <span className="text-[9px] text-gray-400 font-medium self-center">
                                +{line.affected_job_ids.length - 4} more
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="text-[10px] italic text-gray-400">No specific jobs linked</span>
                        )}
                        {line.rationale && (
                          <div className="text-[9px] mt-1 text-emerald-700 dark:text-emerald-400 italic line-clamp-1" title={line.rationale}>
                            {line.rationale}
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {!hasAggregateLines && (
        <div className="mb-3 text-xs text-amber-800 dark:text-amber-200 rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50/60 dark:bg-amber-950/20 px-3 py-2">
          No <code className="text-[10px]">summary.material_replenishment_aggregate</code> (or other batch aggregate) in the last batch response.
          Bulk apply falls back to per-proposal shortage rows; +31m time nudge runs only in that legacy path when the server reports duplicate skips.
        </div>
      )}

      {(!hasAggregateLines || !useBatchAggregateApply || showDrillDown) && (
        <div className="grid grid-cols-12 gap-4 flex-1 min-h-0">
          <aside className="col-span-3 rounded-lg border border-gray-200 dark:border-gray-700 overflow-auto">
            <div className="p-2 border-b border-gray-200 dark:border-gray-700 text-xs font-semibold">
              Proposals ({filteredProposals.length})
            </div>
            <div className="p-2 space-y-1">
              {filteredProposals.map((p) => {
                const recCount = extractRecommendations(p).length
                return (
                  <button
                    type="button"
                    key={p.proposal_id}
                    onClick={() => setSelectedProposalId(p.proposal_id)}
                    className={`w-full text-left px-2 py-2 rounded text-xs border ${
                      selectedProposalId === p.proposal_id
                        ? 'bg-primary/15 border-primary text-primary'
                        : 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800'
                    }`}
                  >
                    <div className="font-semibold">{p.job_id}</div>
                    <div className="opacity-80">
                      {p.feasible === false ? 'Infeasible' : 'Feasible'} · recommendations {recCount}
                    </div>
                  </button>
                )
              })}
            </div>
          </aside>

          <section className="col-span-6 min-h-0 overflow-auto space-y-3">
            {recommendations.length === 0 && (
              <div className="p-4 rounded-lg border border-amber-300 bg-amber-50 text-sm text-amber-800">
                No recommendations available for this proposal.
              </div>
            )}
            {recommendations.map((rec) => (
              <RecommendationCard
                key={rec.key}
                recommendation={rec}
                value={drafts[rec.key]}
                onToggleSelected={(checked) => handleDraftChange(rec.key, 'selected', checked)}
                onFieldChange={(field, value) => handleDraftChange(rec.key, field, value)}
                onFocusShortage={setFocusedEntityId}
              />
            ))}
          </section>

          <section className="col-span-3 min-h-0 overflow-auto">
            <ShortageTable shortages={selectedProposal?.material_shortages || []} focusedEntityId={focusedEntityId} />
          </section>
        </div>
      )}

      {hasAggregateLines && useBatchAggregateApply && !showDrillDown && (
        <div className="flex-1 flex flex-col items-center justify-center p-8 text-center bg-gray-50/50 dark:bg-gray-900/20 rounded-xl border border-dashed border-gray-200 dark:border-gray-800">
          <div className="w-16 h-16 bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 rounded-full flex items-center justify-center mb-4">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h4 className="text-lg font-bold text-gray-900 dark:text-gray-100">Unified Mode Active</h4>
          <p className="text-sm text-gray-500 max-w-md mt-2">
            You are resolving shortages at the material level. Individual job recommendations are hidden to prevent fragmentation.
          </p>
          <div className="flex gap-4 mt-6">
            <button 
              onClick={() => setShowDrillDown(true)}
              className="px-4 py-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-xs font-semibold hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
            >
              View job-level drill down
            </button>
            <button 
              onClick={() => setUseBatchAggregateApply(false)}
              className="px-4 py-2 rounded-lg text-primary text-xs font-semibold hover:bg-primary/5 transition-colors"
            >
              Switch to per-job mode
            </button>
          </div>
        </div>
      )}

      {hasAggregateLines && useBatchAggregateApply && showDrillDown && (
        <div className="mt-4 flex justify-center">
          <button 
            onClick={() => setShowDrillDown(false)}
            className="px-4 py-2 rounded-lg bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 text-xs font-semibold hover:bg-emerald-200 dark:hover:bg-emerald-800/50 transition-colors"
          >
            Hide job-level drill down
          </button>
        </div>
      )}

      <ResolutionSummaryBar
        selectedCount={summarySelectedCount}
        selectedCurrentProposalCount={selectedRecommendationsCurrent.length}
        replenishCount={summaryReplenishCount}
        blockedJobs={blockedJobs}
        totalDeficit={totalDeficit}
        loading={actionLoading}
        onApplyReplan={applyAndReplanAll}
        onRescheduleOnly={rescheduleAllWithoutApply}
        onRefresh={refreshAnalysis}
        onReset={resetAllDrafts}
      />
    </div>
  )
}

export default ShortageResolution
