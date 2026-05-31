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
  apiErrorToastOptions,
  mergeBatchSummaryWithAggregate,
  toData,
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
  const [, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)
  const [proposals, setProposals] = useState([])
  const [selectedProposalId, setSelectedProposalId] = useState('')
  const [focusedEntityId, setFocusedEntityId] = useState('')
  const [drafts, setDrafts] = useState({})
  const [showOnlyInfeasible] = useState(true)
  const [showOnlyWithSuggestions] = useState(true)
  const [localBatchSummary, setLocalBatchSummary] = useState(null)
  const [aggDrafts, setAggDrafts] = useState({})

  const effectiveBatchSummary = localBatchSummary ?? batchSummaryProp

  /** Server-supported batch qty/time; when set, legacy per-proposal apply skips +31m time nudging. */
  const hasServerMaterialReplenishmentAggregate = useMemo(() => {
    const mr =
      effectiveBatchSummary?.material_replenishment_aggregate ??
      effectiveBatchSummary?.materialReplenishmentAggregate
    return Array.isArray(mr) && mr.length > 0
  }, [effectiveBatchSummary])

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
      // Use the batch endpoint to get both proposals and the aggregate in one go
      const resp = await aiApi.scheduling.batchProposals({
        scope: 'all_unscheduled',
        order_by: orderBy,
      })
      const u = unwrapSchedulingBatchPayload(resp)
      const { proposals: proposalsList, summary, byMaterial, byProduct, materialReplenishmentAggregate } = u

      if (Array.isArray(proposalsList)) {
        setProposals(proposalsList)
        const first = proposalsList.find((p) => p.feasible === false && extractRecommendations(p).length > 0) || proposalsList[0]
        setSelectedProposalId(first?.proposal_id || '')
      }

      if (summary || byMaterial || byProduct || materialReplenishmentAggregate) {
        setLocalBatchSummary(
          mergeBatchSummaryWithAggregate({ summary, byMaterial, byProduct, materialReplenishmentAggregate }),
        )
      }
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Failed to load shortage proposals.'), apiErrorToastOptions(err))
    } finally {
      setLoading(false)
    }
  }, [orderBy, toast])

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
    setAggDrafts((prev) => {
      const next = { ...prev }
      normalizedAggregateLines.forEach((line) => {
        if (next[line.key] !== undefined) return
        next[line.key] = {
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

  const selectedRecommendationsAll = useMemo(() => {
    return filteredProposals
      .flatMap((proposal) => extractRecommendations(proposal))
      .map((rec) => {
        const d = drafts[rec.key] || {}
        return {
          ...rec,
          selected: d.selected !== false,
          selected_qty: recommendationQtyFromDraft(d, rec),
          selected_arrive_at: toIso(d.arriveAtLocal) || rec.suggested_arrive_at,
        }
      })
      .filter((rec) => rec.selected)
  }, [filteredProposals, drafts])

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

  const applyAndReplanAll = async () => {
    const legacyArrivals = buildApplyPayload(selectedRecommendationsAll)
    const useAggregate = hasAggregateLines && aggregateApplySuggestions.length > 0
    const useLegacy = !useAggregate && legacyArrivals.length > 0

    if (!useAggregate && !useLegacy) {
      if (selectedRecommendationsAll.length === 0 && !hasAggregateLines) {
        toast.info('Select at least one recommendation (Include), or adjust filters.')
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
      toast.error(
        apiErrorMessage(err, 'Failed to apply selected arrivals and reschedule.'),
        apiErrorToastOptions(err),
      )
    } finally {
      setActionLoading(false)
    }
  }

  const summarySelectedCount = hasAggregateLines ? normalizedAggregateLines.length : selectedRecommendationsAll.length

  return (
    <div className={`${embedded ? 'h-full' : 'p-6'} flex flex-col min-h-0`}>
      {embedded ? (
        <header className="mb-4 flex shrink-0 items-start justify-between gap-4 border-b border-hairline pb-4">
          <div className="min-w-0">
            <h2 className="text-xl font-bold text-ink">Shortage Resolution Center</h2>
            <p className="mt-1 max-w-3xl text-sm text-ink-muted">
              Resolve blocked jobs with editable recommended arrivals before returning to the schedule review.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="relative z-10 inline-flex h-9 shrink-0 items-center rounded-md border border-hairline px-3 text-sm hover:bg-surface-2"
          >
            Close
          </button>
        </header>
      ) : (
        <PageHeader
          title="Shortage Resolution Center"
          subtitle="Resolve blocked jobs in one page with editable recommended arrivals and bulk-assisted actions."
        >
          <Link to="/scheduling" className="h-9 px-3 rounded-md border border-hairline text-sm inline-flex items-center">
            Back to Scheduling
          </Link>
        </PageHeader>
      )}


      {hasAggregateLines && (
        <div className="mb-6 rounded-lg border border-hairline bg-surface-1 overflow-hidden">
          <div className="bg-surface-2 px-4 py-3 border-b border-hairline flex justify-between items-center">
            <div>
              <h3 className="text-sm font-semibold text-ink flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary text-[10px] text-white">
                  {normalizedAggregateLines.length}
                </span>
                Unified Material Shortage Resolution
              </h3>
              <p className="text-[11px] text-ink-subtle mt-0.5">
                Aggregated demand across all impacted jobs. Applying creates a single arrival record for each material.
              </p>
            </div>
          </div>
          <div className="p-4">
            <div className="grid grid-cols-12 gap-4 mb-2 px-2 text-[10px] font-bold text-ink-subtle uppercase tracking-wider">
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
                    className="grid grid-cols-12 gap-4 items-center p-3 rounded-lg border border-hairline bg-surface-1 transition-all"
                  >
                    <div className="col-span-4 flex items-center gap-3">
                      <div className="min-w-0">
                        <div className="font-semibold text-sm truncate" title={line.material_name || line.material_id}>
                          {line.material_name || line.material_id}
                        </div>
                        <div className="text-[10px] font-mono opacity-60 flex items-center gap-1">
                          {line.material_id}
                          <span className={`px-1 rounded-[4px] ${line.kind === 'schedule_production' ? 'bg-primary/10 text-primary' : 'bg-surface-2 text-ink-subtle '}`}>
                            {line.kind === 'schedule_production' ? 'Plan Production' : 'Material'}
                          </span>
                        </div>
                      </div>
                    </div>

                    <div className="col-span-2">
                      <div className="relative">
                        <input
                          type="number"
                          className="w-full h-8 pl-2 pr-1 text-sm font-medium rounded border border-hairline bg-surface-1 focus:ring-1 focus:ring-primary outline-none transition-all"
                          value={d.qty ?? line.qty}
                          onChange={(e) => handleAggregateDraftChange(line.key, 'qty', e.target.value)}
                        />
                      </div>
                    </div>

                    <div className="col-span-3">
                      <input
                        type="datetime-local"
                        className="w-full h-8 px-2 text-xs rounded border border-hairline bg-surface-1 focus:ring-1 focus:ring-primary outline-none transition-all"
                        value={d.arriveAtLocal ?? toLocalInput(line.arrive_at)}
                        onChange={(e) => handleAggregateDraftChange(line.key, 'arriveAtLocal', e.target.value)}
                      />
                    </div>

                    <div className="col-span-3">
                      {line.affected_job_ids?.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {line.affected_job_ids.slice(0, 4).map(jobId => (
                            <span key={jobId} className="px-1.5 py-0.5 rounded bg-surface-1 border border-hairline text-[9px] font-medium text-ink-subtle">
                              {jobId}
                            </span>
                          ))}
                          {line.affected_job_ids.length > 4 && (
                            <span className="text-[9px] text-ink-tertiary font-medium self-center">
                              +{line.affected_job_ids.length - 4} more
                            </span>
                          )}
                        </div>
                      ) : (
                        <span className="text-[10px] italic text-ink-tertiary">No specific jobs linked</span>
                      )}
                      {line.rationale && (
                        <div className="text-[9px] mt-1 text-ink-subtle italic line-clamp-1" title={line.rationale}>
                          {line.rationale}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}


      {!hasAggregateLines && (
        <div className="grid grid-cols-12 gap-4 flex-1 min-h-0">
          <aside className="col-span-3 rounded-lg border border-hairline overflow-auto">
            <div className="p-2 border-b border-hairline text-xs font-semibold">
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
                    className={`w-full text-left px-2 py-2 rounded text-xs border ${selectedProposalId === p.proposal_id
                        ? 'bg-primary/15 border-primary text-primary'
                        : 'border-hairline hover:bg-surface-2'
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
              <div className="p-8 rounded-lg border border-hairline bg-surface-1 text-center">
                <div className="w-10 h-10 bg-surface-2 rounded-full flex items-center justify-center mx-auto mb-3 text-ink-subtle">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                </div>
                <p className="text-sm font-medium text-ink">No recommendations available</p>
                <p className="text-xs text-ink-subtle mt-1">This proposal does not require any replenishment or scheduling adjustments.</p>
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

      <ResolutionSummaryBar
        selectedCount={summarySelectedCount}
        loading={actionLoading}
        onApplyReplan={applyAndReplanAll}
      />
    </div>
  )
}

export default ShortageResolution
