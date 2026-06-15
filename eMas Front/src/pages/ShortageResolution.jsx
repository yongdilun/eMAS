import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  augmentScheduleBatchMessage,
  inventoryApi,
  mergeBatchSummaryWithAggregate,
  toData,
  toList,
  unwrapSchedulingBatchPayload,
} from '../services/api'
import {
  APPLY_REPLENISHMENT_DUPLICATE_WINDOW_NUDGE_MS,
  applyReplenishmentClientNotice,
  applyReplenishmentDuplicateSkipTotal,
  aggregateMaterialShortageRowsFromProposals,
  buildAggregateApplySuggestions,
  buildApplyPayload,
  extractBatchAccelerationAggregate,
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
const MAX_MATERIAL_CONVERGENCE_PASSES = 5
const MATERIAL_SHORTAGE_RE = /material[_\s-]*shortage|raw[_\s-]*material/i

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

const aggregateLineId = (line) => line?.id || line?.material_id || ''

const aggregateLineLabel = (line) => line?.label || line?.material_name || line?.material_id || 'Unknown'

const aggregateLineKindLabel = (line) => line?.source === 'acceleration' ? 'Optional acceleration' : 'Material arrival'

const suggestionMaterialId = (row) => String(row?.material_id || row?.id || '').trim()

const aggregateApplySignature = (suggestions = []) =>
  JSON.stringify(
    (suggestions || [])
      .map((row) => ({
        material_id: suggestionMaterialId(row),
        quantity: Number(row?.quantity ?? row?.qty ?? 0),
        arrive_at: row?.arrive_at || row?.suggested_arrive_at || '',
      }))
      .filter((row) => row.material_id && row.quantity > 0 && row.arrive_at)
      .sort((a, b) => `${a.material_id}|${a.arrive_at}`.localeCompare(`${b.material_id}|${b.arrive_at}`)),
  )

const materialAggregateApplySuggestionsFromSummary = (summary, excludedMaterialIds = new Set()) => {
  const aggregate = extractBatchShortageAggregate(summary)
  const lines = normalizeBatchAggregateLines(aggregate.byMaterial, aggregate.byProduct)
  const suggestions = buildAggregateApplySuggestions(lines, {})
  return suggestions.filter((row) => {
    const materialId = suggestionMaterialId(row)
    return materialId && !excludedMaterialIds.has(materialId)
  })
}

const materialAggregateApplySuggestionsFromProposals = (proposals, excludedMaterialIds = new Set()) => {
  const rows = aggregateMaterialShortageRowsFromProposals(proposals)
  const lines = normalizeBatchAggregateLines(rows, [])
  const suggestions = buildAggregateApplySuggestions(lines, {})
  return suggestions.filter((row) => {
    const materialId = suggestionMaterialId(row)
    return materialId && !excludedMaterialIds.has(materialId)
  })
}

const materialAggregateApplySuggestionsFromBatch = (summary, proposals, excludedMaterialIds = new Set()) => {
  const summaryRows = materialAggregateApplySuggestionsFromSummary(summary, excludedMaterialIds)
  if (summaryRows.length > 0) return summaryRows
  return materialAggregateApplySuggestionsFromProposals(proposals, excludedMaterialIds)
}

const proposalHasMaterialShortage = (proposal) => {
  if (!proposal || proposal.feasible !== false) return false
  const reasons = [
    ...(Array.isArray(proposal.blocked_reasons) ? proposal.blocked_reasons : []),
    ...(Array.isArray(proposal.blockedReasons) ? proposal.blockedReasons : []),
    proposal.blocked_reason,
    proposal.blockedReason,
    proposal.reason,
  ]
    .filter(Boolean)
    .map(String)
  if (reasons.some((reason) => MATERIAL_SHORTAGE_RE.test(reason))) return true
  if (Array.isArray(proposal.material_shortages) && proposal.material_shortages.length > 0) return true
  if (Array.isArray(proposal.materialShortages) && proposal.materialShortages.length > 0) return true
  const resolutionRows = Array.isArray(proposal.shortage_resolutions)
    ? proposal.shortage_resolutions
    : Array.isArray(proposal.shortageResolutions)
      ? proposal.shortageResolutions
      : []
  return resolutionRows.some((row) => {
    const type = String(row?.option_type || row?.optionType || '').toLowerCase()
    return type.includes('replenish') || !!(row?.material_id || row?.materialId || row?.replenishment?.material_id)
  })
}

const countMaterialShortageInfeasible = (proposals = []) =>
  (Array.isArray(proposals) ? proposals : []).filter(proposalHasMaterialShortage).length

const normalizeLookupMaterial = (item = {}) => {
  const id = item.material_id || item.MaterialID || item.materialId || item.id
  if (!id) return null
  return {
    id,
    label: item.material_name || item.MaterialName || item.materialName || item.name || id,
  }
}

const earliestLocalInput = (a, b) => {
  const at = a ? new Date(a).getTime() : NaN
  const bt = b ? new Date(b).getTime() : NaN
  if (!Number.isFinite(at)) return b || ''
  if (!Number.isFinite(bt)) return a || ''
  return at <= bt ? a : b
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
  const [batchMessage, setBatchMessage] = useState('')
  const [aggDrafts, setAggDrafts] = useState({})
  const [removedAggregateKeys, setRemovedAggregateKeys] = useState(() => new Set())
  const [manualAggregateLines, setManualAggregateLines] = useState([])
  const [addLineOpen, setAddLineOpen] = useState(false)
  const [lookupLoading, setLookupLoading] = useState(false)
  const [lookupError, setLookupError] = useState('')
  const [materialOptions, setMaterialOptions] = useState([])
  const [newLineDraft, setNewLineDraft] = useState({
    kind: 'material',
    id: '',
    qty: '',
    arriveAtLocal: '',
  })
  const draftLoadPromiseRef = useRef(null)

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
    if (draftLoadPromiseRef.current) return draftLoadPromiseRef.current

    draftLoadPromiseRef.current = (async () => {
      setLoading(true)
      try {
        // Use the batch endpoint to get both proposals and the aggregate in one go
        const resp = await aiApi.scheduling.batchProposals({
          scope: 'all_unscheduled',
          order_by: orderBy,
        })
        const u = unwrapSchedulingBatchPayload(resp)
        const {
          proposals: proposalsList,
          summary,
          byMaterial,
          byProduct,
          materialReplenishmentAggregate,
          materialAccelerationAggregate,
        } = u
        setBatchMessage(augmentScheduleBatchMessage(u.message) || '')

        if (Array.isArray(proposalsList)) {
          setProposals(proposalsList)
          const first = proposalsList.find((p) => p.feasible === false && extractRecommendations(p).length > 0) || proposalsList[0]
          setSelectedProposalId(first?.proposal_id || '')
        }

        if (summary || byMaterial || byProduct || materialReplenishmentAggregate) {
          setLocalBatchSummary(
            mergeBatchSummaryWithAggregate({
              summary,
              byMaterial,
              byProduct,
              materialReplenishmentAggregate,
              materialAccelerationAggregate,
            }),
          )
        }
      } catch (err) {
        toast.error(apiErrorMessage(err, 'Failed to load shortage proposals.'), apiErrorToastOptions(err))
      } finally {
        setLoading(false)
        draftLoadPromiseRef.current = null
      }
    })()

    return draftLoadPromiseRef.current
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
  const accelerationAggregate = useMemo(
    () => extractBatchAccelerationAggregate(effectiveBatchSummary),
    [effectiveBatchSummary],
  )
  const normalizedAccelerationLines = useMemo(
    () =>
      normalizeBatchAggregateLines(accelerationAggregate.byMaterial, accelerationAggregate.byProduct).map((line) => ({
        ...line,
        key: line.key.replace(/^agg:/, 'acc:'),
        selected: false,
        source: 'acceleration',
        rationale: line.rationale || 'Optional material acceleration for feasible late jobs.',
      })),
    [accelerationAggregate.byMaterial, accelerationAggregate.byProduct],
  )
  const proposalAggregateLines = useMemo(() => {
    if (normalizedAggregateLines.length > 0) return []
    const rows = aggregateMaterialShortageRowsFromProposals(proposals)
    return normalizeBatchAggregateLines(rows, [])
  }, [normalizedAggregateLines.length, proposals])
  const requiredAggregateLines = normalizedAggregateLines.length > 0
    ? normalizedAggregateLines
    : proposalAggregateLines
  const effectiveAggregateLines = useMemo(
    () => [...requiredAggregateLines, ...normalizedAccelerationLines],
    [requiredAggregateLines, normalizedAccelerationLines],
  )

  useEffect(() => {
    setManualAggregateLines([])
    setRemovedAggregateKeys(new Set())
    setAggDrafts({})
  }, [effectiveBatchSummary])

  const aggregateLines = useMemo(
    () =>
      [...effectiveAggregateLines, ...manualAggregateLines]
        .filter((line) => !removedAggregateKeys.has(line.key)),
    [effectiveAggregateLines, manualAggregateLines, removedAggregateKeys],
  )

  const hasAggregateLines = effectiveAggregateLines.length > 0 || manualAggregateLines.length > 0
  const requiredAggregateCount = aggregateLines.filter((line) => line.source !== 'acceleration').length
  const optionalAccelerationCount = aggregateLines.filter((line) => line.source === 'acceleration').length
  const optionalAccelerationSelectedCount = aggregateLines.filter((line) => {
    if (line.source !== 'acceleration') return false
    const d = aggDrafts[line.key] || {}
    return (d.selected !== undefined ? d.selected !== false : line.selected !== false)
  }).length
  const allOptionalAccelerationSelected =
    optionalAccelerationCount > 0 && optionalAccelerationSelectedCount === optionalAccelerationCount

  const handleOptionalAccelerationToggle = (checked) => {
    setAggDrafts((prev) => {
      const next = { ...prev }
      aggregateLines
        .filter((line) => line.source === 'acceleration')
        .forEach((line) => {
          next[line.key] = { ...(next[line.key] || {}), selected: checked }
        })
      return next
    })
  }

  useEffect(() => {
    setAggDrafts((prev) => {
      const next = { ...prev }
      aggregateLines.forEach((line) => {
        if (next[line.key] !== undefined) return
        next[line.key] = {
          selected: line.selected !== false,
          qty: line.qty,
          arriveAtLocal: toLocalInput(line.arrive_at),
        }
      })
      return next
    })
  }, [aggregateLines])

  const aggregateApplySuggestions = useMemo(
    () => buildAggregateApplySuggestions(aggregateLines, aggDrafts),
    [aggregateLines, aggDrafts],
  )

  const normalizedMaterialOptions = useMemo(
    () => materialOptions.map(normalizeLookupMaterial).filter(Boolean),
    [materialOptions],
  )

  const newLineOptions = normalizedMaterialOptions

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

  const loadAddLineOptions = useCallback(async () => {
    if (lookupLoading) return
    if (materialOptions.length > 0) return
    setLookupLoading(true)
    setLookupError('')
    try {
      const materialsResp = await inventoryApi.list()
      setMaterialOptions(toList(materialsResp))
    } catch (err) {
      const message = apiErrorMessage(err, 'Failed to load materials.')
      setLookupError(message)
      toast.error(message, apiErrorToastOptions(err))
    } finally {
      setLookupLoading(false)
    }
  }, [lookupLoading, materialOptions.length, toast])

  const openAddLine = () => {
    setAddLineOpen(true)
    loadAddLineOptions()
  }

  const resetNewLineDraft = () => {
    setNewLineDraft({
      kind: 'material',
      id: '',
      qty: '',
      arriveAtLocal: '',
    })
  }

  const removeAggregateLine = (line) => {
    if (line.source === 'manual') {
      setManualAggregateLines((prev) => prev.filter((item) => item.key !== line.key))
    } else {
      setRemovedAggregateKeys((prev) => {
        const next = new Set(prev)
        next.add(line.key)
        return next
      })
    }
    setAggDrafts((prev) => ({
      ...prev,
      [line.key]: { ...(prev[line.key] || {}), selected: false },
    }))
  }

  const addAggregateLine = () => {
    const id = newLineDraft.id
    const qty = Number(newLineDraft.qty)
    const arriveAtIso = toIso(newLineDraft.arriveAtLocal)
    if (!id || !(qty > 0) || !arriveAtIso) {
      toast.info('Choose a material, then enter quantity and arrival time.')
      return
    }

    const option = newLineOptions.find((item) => item.id === id)
    const label = option?.label || id
    const kind = 'material'
    const existing = [...effectiveAggregateLines, ...manualAggregateLines].find(
      (line) => line.kind === kind && aggregateLineId(line) === id,
    )

    if (existing) {
      setRemovedAggregateKeys((prev) => {
        const next = new Set(prev)
        next.delete(existing.key)
        return next
      })
      setAggDrafts((prev) => {
        const current = prev[existing.key] || {}
        const currentQty = Number(current.qty ?? existing.qty ?? 0)
        const mergedQty = (Number.isFinite(currentQty) ? currentQty : 0) + qty
        const currentLocal = current.arriveAtLocal ?? toLocalInput(existing.arrive_at)
        return {
          ...prev,
          [existing.key]: {
            ...current,
            selected: true,
            qty: mergedQty,
            arriveAtLocal: earliestLocalInput(currentLocal, newLineDraft.arriveAtLocal),
          },
        }
      })
      setAddLineOpen(false)
      resetNewLineDraft()
      return
    }

    const key = `manual:${kind}:${id}:${Date.now()}`
    setManualAggregateLines((prev) => [
      ...prev,
      {
        key,
        kind,
        id,
        label,
        material_id: id,
        material_name: label,
        qty,
        arrive_at: arriveAtIso,
        selected: true,
        source: 'manual',
        affected_job_ids: [],
        rationale: 'Added by planner.',
      },
    ])
    setAggDrafts((prev) => ({
      ...prev,
      [key]: {
        selected: true,
        qty,
        arriveAtLocal: newLineDraft.arriveAtLocal,
      },
    }))
    setAddLineOpen(false)
    resetNewLineDraft()
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

  const handleRescheduleResponse = async (resp) => {
    const u = unwrapSchedulingBatchPayload(resp)
    const {
      proposals: proposalsList,
      summary,
      byMaterial,
      byProduct,
      materialReplenishmentAggregate,
      materialAccelerationAggregate,
    } = u
    setBatchMessage(augmentScheduleBatchMessage(u.message) || '')
    setLocalBatchSummary(
      mergeBatchSummaryWithAggregate({
        summary,
        byMaterial,
        byProduct,
        materialReplenishmentAggregate,
        materialAccelerationAggregate,
      }),
    )
    setDrafts({})
    setAggDrafts({})
    setManualAggregateLines([])
    setRemovedAggregateKeys(new Set())
    if (embedded && typeof onApplySuccess === 'function') {
      await Promise.resolve(onApplySuccess(resp))
      return true
    }
    if (Array.isArray(proposalsList) && proposalsList.length > 0) {
      setProposals(proposalsList)
      const first = proposalsList.find((p) => extractRecommendations(p).length > 0) || proposalsList[0]
      setSelectedProposalId(first?.proposal_id || '')
    } else {
      await loadDraftProposals()
    }
    return false
  }

  const replanOnly = async () => {
    setActionLoading(true)
    try {
      const resp = await aiApi.scheduling.rescheduleAll({ order_by: orderBy })
      const handedOff = await handleRescheduleResponse(resp)
      if (!handedOff) {
        toast.success('Regenerated schedule without applying material rows.')
      }
    } catch (err) {
      toast.error(
        apiErrorMessage(err, 'Failed to regenerate schedule.'),
        apiErrorToastOptions(err),
      )
    } finally {
      setActionLoading(false)
    }
  }

  const applyAggregateSuggestionsOnce = async (suggestions, proposalList = proposals) => {
    const anchor =
      batchAggregate.anchorProposalId ||
      proposalList.find((p) => p.feasible === false && p.proposal_id)?.proposal_id ||
      proposalList.find((p) => p.proposal_id)?.proposal_id

    try {
      const rawBatch = await aiApi.scheduling.applyReplenishmentBatch({
        suggestions,
        order_by: orderBy,
      })
      const appliedData = toData(rawBatch) || rawBatch
      return applyReplenishmentClientNotice(appliedData)
    } catch (err) {
      if (err.status !== 404) throw err
      if (!anchor) {
        throw new Error(
          'Batch replenishment API is not available yet, and no anchor proposal_id was found for a single apply-replenishment call.',
        )
      }
      const rawApply = await aiApi.scheduling.applyReplenishment(anchor, { suggestions })
      const appliedData = toData(rawApply) || rawApply
      return applyReplenishmentClientNotice(appliedData)
    }
  }

  const convergeMaterialShortageAfterReplan = async ({
    initialResp,
    excludedMaterialIds,
    seenSignatures,
    applyWarnTexts,
    applyInfoTexts,
    appliedMaterialPasses,
  }) => {
    let latestResp = initialResp
    let additionalApplyCalls = 0
    let passes = appliedMaterialPasses
    let stoppedByRepeat = false
    let stoppedByCap = false

    while (latestResp) {
      const u = unwrapSchedulingBatchPayload(latestResp)
      const latestSummary = mergeBatchSummaryWithAggregate({
        summary: u.summary,
        byMaterial: u.byMaterial,
        byProduct: u.byProduct,
        materialReplenishmentAggregate: u.materialReplenishmentAggregate,
        materialAccelerationAggregate: u.materialAccelerationAggregate,
      })
      const followupSuggestions = materialAggregateApplySuggestionsFromBatch(
        latestSummary,
        u.proposals,
        excludedMaterialIds,
      )
      const remainingMaterialShortages = countMaterialShortageInfeasible(u.proposals)

      if (remainingMaterialShortages === 0 || followupSuggestions.length === 0) {
        return { latestResp, additionalApplyCalls, passes, stoppedByRepeat, stoppedByCap }
      }
      if (passes >= MAX_MATERIAL_CONVERGENCE_PASSES) {
        stoppedByCap = true
        return { latestResp, additionalApplyCalls, passes, stoppedByRepeat, stoppedByCap }
      }

      const signature = aggregateApplySignature(followupSuggestions)
      if (!signature || seenSignatures.has(signature)) {
        stoppedByRepeat = true
        return { latestResp, additionalApplyCalls, passes, stoppedByRepeat, stoppedByCap }
      }
      seenSignatures.add(signature)

      const notice = await applyAggregateSuggestionsOnce(followupSuggestions, u.proposals)
      additionalApplyCalls += 1
      passes += 1
      if (notice?.level === 'warn') applyWarnTexts.push(notice.text)
      else if (notice?.level === 'info') applyInfoTexts.push(notice.text)

      latestResp = await aiApi.scheduling.rescheduleAll({ order_by: orderBy })
    }

    return { latestResp, additionalApplyCalls, passes, stoppedByRepeat, stoppedByCap }
  }

  const applyAndReplanAll = async () => {
    const legacyArrivals = buildApplyPayload(selectedRecommendationsAll)
    const useAggregate = hasAggregateLines && aggregateApplySuggestions.length > 0
    const useLegacy = !useAggregate && legacyArrivals.length > 0

    if (!useAggregate && !useLegacy) {
      if (hasAggregateLines) {
        toast.info('No selected material rows with quantity and arrival time. Include a row or use Replan only.')
      } else if (selectedRecommendationsAll.length === 0) {
        toast.info('Select at least one recommendation (Include), or adjust filters.')
      } else {
        const noneApplyEligible = selectedRecommendationsAll.every((r) => !isApplyReplenishmentSuggestion(r))
        if (noneApplyEligible) {
          toast.info('No selected rows are material arrivals with quantity and time. Use Replan only or refresh analysis for options.')
        } else {
          toast.info('No apply rows with quantity and arrival time. Edit qty/time on included recommendations.')
        }
      }
      return
    }

    setActionLoading(true)
    try {
      let applyCalls = 0
      let appliedMaterialPasses = 0
      let latestResp = null
      let stoppedByRepeat = false
      let stoppedByCap = false
      const applyWarnTexts = []
      const applyInfoTexts = []
      const seenSignatures = new Set()
      const excludedMaterialIds = new Set(
        [
          ...normalizedAggregateLines.filter((line) => removedAggregateKeys.has(line.key)),
          ...aggregateLines.filter((line) => {
            const d = aggDrafts[line.key] || {}
            const selected = d.selected !== undefined ? d.selected !== false : line.selected !== false
            return !selected
          }),
        ]
          .map(suggestionMaterialId)
          .filter(Boolean),
      )

      if (useAggregate) {
        const signature = aggregateApplySignature(aggregateApplySuggestions)
        if (signature) seenSignatures.add(signature)
        const aggregateNotice = await applyAggregateSuggestionsOnce(aggregateApplySuggestions, proposals)
        applyCalls += 1
        appliedMaterialPasses += 1
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

      latestResp = await aiApi.scheduling.rescheduleAll({ order_by: orderBy })
      const convergence = await convergeMaterialShortageAfterReplan({
        initialResp: latestResp,
        excludedMaterialIds,
        seenSignatures,
        applyWarnTexts,
        applyInfoTexts,
        appliedMaterialPasses,
      })
      latestResp = convergence.latestResp || latestResp
      applyCalls += convergence.additionalApplyCalls
      appliedMaterialPasses = convergence.passes
      stoppedByRepeat = convergence.stoppedByRepeat
      stoppedByCap = convergence.stoppedByCap

      const finalPayload = unwrapSchedulingBatchPayload(latestResp)
      const finalSummary = mergeBatchSummaryWithAggregate({
        summary: finalPayload.summary,
        byMaterial: finalPayload.byMaterial,
        byProduct: finalPayload.byProduct,
        materialReplenishmentAggregate: finalPayload.materialReplenishmentAggregate,
        materialAccelerationAggregate: finalPayload.materialAccelerationAggregate,
      })
      const remainingMaterialShortages = countMaterialShortageInfeasible(finalPayload.proposals)
      const remainingMaterialRows = materialAggregateApplySuggestionsFromBatch(
        finalSummary,
        finalPayload.proposals,
        excludedMaterialIds,
      ).length
      const handedOff = await handleRescheduleResponse(latestResp)
      if (!handedOff) {
        if (remainingMaterialShortages > 0 || remainingMaterialRows > 0) {
          const reason = stoppedByCap
            ? `Stopped after ${MAX_MATERIAL_CONVERGENCE_PASSES} material passes.`
            : stoppedByRepeat
              ? 'Stopped because the same material recommendation repeated.'
              : 'No new material recommendation was returned for the remaining shortage.'
          toast.warning(
            `${reason} ${remainingMaterialShortages} material-shortage proposal(s) and ${remainingMaterialRows} material row(s) remain.`,
          )
        } else {
          const suffix = appliedMaterialPasses > 1 ? ` after ${appliedMaterialPasses} material passes` : ''
          toast.success(`Applied selected arrivals and regenerated schedule${suffix}.`)
        }
      }
    } catch (err) {
      toast.error(
        apiErrorMessage(err, 'Failed to apply selected arrivals and reschedule.'),
        apiErrorToastOptions(err),
      )
    } finally {
      setActionLoading(false)
    }
  }

  const summarySelectedCount = hasAggregateLines ? aggregateApplySuggestions.length : selectedRecommendationsAll.length

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

      {batchMessage && (
        <div
          role="alert"
          className="mb-4 rounded-md border border-amber-300/70 bg-amber-50 px-4 py-3 text-sm text-amber-900 shadow-sm dark:border-amber-400/30 dark:bg-amber-950/35 dark:text-amber-100"
        >
          <p className="whitespace-pre-line">{batchMessage}</p>
        </div>
      )}


      {hasAggregateLines && (
        <div className="mb-6 overflow-hidden rounded-md border border-hairline bg-surface-1">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-hairline bg-surface-2 px-4 py-3">
            <div className="min-w-0">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
                <span className="flex h-5 min-w-5 items-center justify-center rounded-md bg-primary px-1.5 text-[10px] text-white">
                  {aggregateLines.length}
                </span>
                {requiredAggregateCount > 0 ? 'Unified Material Shortage Resolution' : 'Optional Material Acceleration'}
              </h3>
              <p className="mt-0.5 text-[11px] text-ink-subtle">
                {requiredAggregateCount > 0
                  ? 'Required material rows are included by default. Optional acceleration rows are off until included.'
                  : 'All jobs are feasible. Optional acceleration rows can reduce lateness and are off by default.'}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {optionalAccelerationCount > 0 && (
                <label className="inline-flex h-8 items-center gap-2 rounded-md border border-hairline bg-surface-1 px-3 text-xs font-semibold text-ink hover:bg-surface-3">
                  <input
                    aria-label="Include optional acceleration"
                    type="checkbox"
                    checked={allOptionalAccelerationSelected}
                    onChange={(e) => handleOptionalAccelerationToggle(e.target.checked)}
                    className="h-4 w-4 rounded border-hairline bg-surface-1 text-primary focus:ring-primary"
                  />
                  <span>Include optional acceleration</span>
                </label>
              )}
              <button
                type="button"
                onClick={openAddLine}
                className="inline-flex h-8 items-center rounded-md border border-hairline bg-surface-1 px-3 text-xs font-semibold text-ink hover:bg-surface-3"
              >
                Add line
              </button>
            </div>
          </div>

          {addLineOpen && (
            <div className="border-b border-hairline bg-surface-1 px-4 py-3">
              <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(12rem,1fr)_8rem_13rem_auto] xl:items-end">
                <label className="text-xs font-medium text-ink-subtle">
                  Material
                  <select
                    aria-label="Material"
                    className="mt-1 h-9 w-full rounded-md border border-hairline bg-surface-2 px-2 text-sm text-ink outline-none focus:ring-1 focus:ring-primary"
                    value={newLineDraft.id}
                    disabled={lookupLoading}
                    onInput={(e) => setNewLineDraft((prev) => ({ ...prev, id: e.target.value }))}
                    onChange={(e) => setNewLineDraft((prev) => ({ ...prev, id: e.target.value }))}
                  >
                    <option value="">{lookupLoading ? 'Loading...' : 'Select one'}</option>
                    {newLineOptions.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.id} - {item.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs font-medium text-ink-subtle">
                  Qty
                  <input
                    aria-label="New line quantity"
                    type="number"
                    min="0"
                    step="0.01"
                    className="mt-1 h-9 w-full rounded-md border border-hairline bg-surface-2 px-2 text-sm text-ink outline-none focus:ring-1 focus:ring-primary"
                    value={newLineDraft.qty}
                    onInput={(e) => setNewLineDraft((prev) => ({ ...prev, qty: e.target.value }))}
                    onChange={(e) => setNewLineDraft((prev) => ({ ...prev, qty: e.target.value }))}
                  />
                </label>
                <label className="text-xs font-medium text-ink-subtle">
                  Arrival time
                  <input
                    aria-label="New line arrival time"
                    type="datetime-local"
                    className="mt-1 h-9 w-full rounded-md border border-hairline bg-surface-2 px-2 text-sm text-ink outline-none focus:ring-1 focus:ring-primary [color-scheme:light] dark:[color-scheme:dark]"
                    value={newLineDraft.arriveAtLocal}
                    onInput={(e) => setNewLineDraft((prev) => ({ ...prev, arriveAtLocal: e.target.value }))}
                    onChange={(e) => setNewLineDraft((prev) => ({ ...prev, arriveAtLocal: e.target.value }))}
                  />
                </label>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={addAggregateLine}
                    className="h-9 rounded-md bg-primary px-3 text-xs font-semibold text-white hover:bg-primary/90"
                  >
                    Add selected line
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setAddLineOpen(false)
                      resetNewLineDraft()
                    }}
                    className="h-9 rounded-md border border-hairline px-3 text-xs font-semibold text-ink-subtle hover:bg-surface-2 hover:text-ink"
                  >
                    Cancel
                  </button>
                </div>
              </div>
              {lookupError && (
                <p className="mt-2 text-xs text-red-600 dark:text-red-300">{lookupError}</p>
              )}
            </div>
          )}

          <div className="p-4">
            <div className="mb-2 hidden grid-cols-[2rem_minmax(12rem,1.4fr)_9rem_13rem_minmax(10rem,1fr)_4rem] gap-3 px-2 text-[10px] font-bold uppercase text-ink-subtle xl:grid">
              <div>Use</div>
                  <div>Material</div>
              <div>Qty</div>
              <div>Arrival</div>
              <div>Impacted jobs</div>
              <div></div>
            </div>
            <div className="max-h-[45vh] space-y-2 overflow-y-auto pr-2">
              {aggregateLines.length === 0 && (
                <div className="rounded-md border border-dashed border-hairline bg-surface-2 p-6 text-center text-sm text-ink-subtle">
                  No active material rows. Add a material line, or use Replan only.
                </div>
              )}
              {aggregateLines.map((line) => {
                const d = aggDrafts[line.key] || {}
                const selected = d.selected !== undefined ? d.selected !== false : line.selected !== false
                const id = aggregateLineId(line)
                const label = aggregateLineLabel(line)
                return (
                  <div
                    key={line.key}
                    data-shortage-line-kind={line.kind || 'material'}
                    data-shortage-line-id={id}
                    data-material-action-source={line.source || 'recommendation'}
                    className={`grid grid-cols-1 gap-3 rounded-md border p-3 transition-colors xl:grid-cols-[2rem_minmax(12rem,1.4fr)_9rem_13rem_minmax(10rem,1fr)_4rem] xl:items-center ${
                      selected
                        ? line.source === 'acceleration'
                          ? 'border-sky-300/60 bg-sky-50/60 hover:bg-sky-50 dark:border-sky-500/30 dark:bg-sky-950/20 dark:hover:bg-sky-950/30'
                          : 'border-hairline bg-surface-1 hover:bg-surface-2'
                        : line.source === 'acceleration'
                          ? 'border-sky-200/60 bg-surface-2/70 dark:border-sky-500/20'
                        : 'border-hairline bg-surface-2/70'
                    }`}
                  >
                    <label className="flex items-center gap-2 text-xs font-medium text-ink-subtle xl:justify-center">
                      <input
                        aria-label={`Include ${id}`}
                        type="checkbox"
                        checked={selected}
                        onChange={(e) => handleAggregateDraftChange(line.key, 'selected', e.target.checked)}
                        className="h-4 w-4 rounded border-hairline bg-surface-1 text-primary focus:ring-primary"
                      />
                      <span className="xl:hidden">Include</span>
                    </label>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-ink" title={label}>
                        {label}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-ink-subtle">
                        <span className="font-mono">{id}</span>
                        <span
                          className="rounded border border-hairline bg-surface-2 px-1.5 py-0.5 font-semibold text-ink-subtle"
                        >
                          {aggregateLineKindLabel(line)}
                        </span>
                        {line.source === 'manual' && (
                          <span className="rounded border border-hairline bg-surface-2 px-1.5 py-0.5 font-semibold text-ink-subtle">
                            Added
                          </span>
                        )}
                      </div>
                    </div>
                    <label className="text-xs font-medium text-ink-subtle">
                      <span className="xl:hidden">Qty</span>
                      <input
                        aria-label={`Quantity for ${id}`}
                        type="number"
                        min="0"
                        step="0.01"
                        disabled={!selected}
                        className="mt-1 h-9 w-full rounded-md border border-hairline bg-surface-2 px-2 text-sm font-medium text-ink outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:border-hairline-strong disabled:text-ink-subtle disabled:opacity-100 xl:mt-0"
                        value={d.qty ?? line.qty}
                        onInput={(e) => handleAggregateDraftChange(line.key, 'qty', e.target.value)}
                        onChange={(e) => handleAggregateDraftChange(line.key, 'qty', e.target.value)}
                      />
                    </label>
                    <label className="text-xs font-medium text-ink-subtle">
                      <span className="xl:hidden">Arrival time</span>
                      <input
                        aria-label={`Arrival time for ${id}`}
                        type="datetime-local"
                        disabled={!selected}
                        className="mt-1 h-9 w-full rounded-md border border-hairline bg-surface-2 px-2 text-xs text-ink outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:border-hairline-strong disabled:text-ink-subtle disabled:opacity-100 xl:mt-0 [color-scheme:light] dark:[color-scheme:dark]"
                        value={d.arriveAtLocal ?? toLocalInput(line.arrive_at)}
                        onInput={(e) => handleAggregateDraftChange(line.key, 'arriveAtLocal', e.target.value)}
                        onChange={(e) => handleAggregateDraftChange(line.key, 'arriveAtLocal', e.target.value)}
                      />
                    </label>
                    <div className="min-w-0">
                      {line.affected_job_ids?.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {line.affected_job_ids.slice(0, 4).map((jobId) => (
                            <span key={jobId} className="rounded border border-hairline bg-surface-2 px-1.5 py-0.5 text-[9px] font-medium text-ink-subtle">
                              {jobId}
                            </span>
                          ))}
                          {line.affected_job_ids.length > 4 && (
                            <span className="self-center text-[9px] font-medium text-ink-tertiary">
                              +{line.affected_job_ids.length - 4} more
                            </span>
                          )}
                        </div>
                      ) : (
                        <span className="text-[10px] italic text-ink-tertiary">No linked jobs</span>
                      )}
                      {line.rationale && (
                        <div className="mt-1 truncate text-[10px] text-ink-subtle" title={line.rationale}>
                          {line.rationale}
                        </div>
                      )}
                    </div>
                    <button
                      type="button"
                      aria-label={`Remove ${id}`}
                      onClick={() => removeAggregateLine(line)}
                      className="h-8 rounded-md border border-hairline px-2 text-xs font-semibold text-ink-subtle hover:bg-red-50 hover:text-red-700 dark:hover:bg-red-900/20 dark:hover:text-red-300"
                    >
                      Remove
                    </button>
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
        onReplanOnly={replanOnly}
        avoidFloatingAssistant={!embedded}
      />
    </div>
  )
}

export default ShortageResolution
