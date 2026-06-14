import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { Link } from 'react-router-dom'
import GanttTable from '../components/features/gantt/GanttTable'
import PageHeader from '../components/shared/PageHeader'
import Modal from '../components/shared/Modal'
import UrgentInsertModal from '../components/features/scheduling/UrgentInsertModal'
import { RescheduleReviewPanel } from '../components/features/scheduling/RescheduleReviewModal'
import ShortageResolution from './ShortageResolution'
import {
    augmentScheduleBatchMessage,
    aiApi,
    apiErrorMessage,
    apiErrorToastOptions,
    isStaleProposalError,
    jobsApi,
    machinesApi,
    processesApi,
    schedulingApi,
    toData,
    toList,
    mergeBatchSummaryWithAggregate,
    unwrapSchedulingBatchPayload,
} from '../services/api'
import { applyReplenishmentClientNotice, isReplenishRecommendation, normalizeMachine } from '../services/normalizers'
import logger from '../services/logger'
import { useToast } from '../context/ToastContext'

/** Parse proposal_json if present; return proposed_slots and product_id. */
function parseProposalPayload(proposal) {
    if (!proposal) return { proposed_slots: [], product_id: null }
    if (proposal.proposed_slots && Array.isArray(proposal.proposed_slots)) {
        return { proposed_slots: proposal.proposed_slots, product_id: proposal.product_id }
    }
    if (proposal.proposal_json) {
        try {
            const parsed = typeof proposal.proposal_json === 'string'
                ? JSON.parse(proposal.proposal_json) : proposal.proposal_json
            return {
                proposed_slots: parsed?.proposed_slots || [],
                product_id: parsed?.product_id ?? proposal.product_id,
            }
        } catch {
            return { proposed_slots: [], product_id: proposal.product_id }
        }
    }
    return { proposed_slots: [], product_id: proposal.product_id }
}

/**
 * Map proposals to GanttTable jobs format.
 * job_id comes from the proposal, NOT from the slot — each slot must use proposal.job_id.
 */
function proposalsToGanttJobs(proposals) {
    return (proposals || []).map((p) => {
        const { proposed_slots: slots, product_id } = parseProposalPayload(p)
        const jobId = p.job_id
        if (!jobId) return null
        return {
            job_id: jobId,
            jobId,
            id: jobId,
            product_id: product_id ?? p.product_id,
            productId: product_id ?? p.product_id,
            proposal_id: p.proposal_id,
            deadline_status: p.deadline_status,
            summary: p.summary,
            feasible: p.feasible,
            material_shortages: p.material_shortages || [],
            shortage_resolutions: p.shortage_resolutions || [],
            partial_feasibility: p.partial_feasibility || null,
            deferred_nodes: p.deferred_nodes || [],
            convergence_warnings: p.convergence_warnings || [],
            global_score: p.global_score,
            slots: slots.map((s) => ({
                job_id: s.job_id ?? jobId,
                machine_id: s.machine_id,
                machineId: s.machine_id,
                scheduled_start: s.scheduled_start,
                scheduled_end: s.scheduled_end,
                actual_start: s.actual_start,
                actual_end: s.actual_end,
                step_name: s.step_name,
                step_id: s.step_id ?? s.stepId,
                stepId: s.step_id ?? s.stepId,
                quantity_planned: s.quantity_planned,
                status: s.status,
                estimated_duration_mins: s.estimated_duration_mins,
            })),
        }
    }).filter(Boolean).filter((j) => (j.slots || []).length > 0)
}

function proposalToPreviewJob(proposal) {
    if (!proposal) return null
    const { proposed_slots: slots, product_id } = parseProposalPayload(proposal)
    const jobId = proposal.job_id
    if (!jobId) return null
    return {
        job_id: jobId,
        jobId,
        id: jobId,
        product_id: product_id ?? proposal.product_id,
        productId: product_id ?? proposal.product_id,
        proposal_id: proposal.proposal_id,
        deadline_status: proposal.deadline_status,
        summary: proposal.summary,
        feasible: proposal.feasible,
        material_shortages: proposal.material_shortages || [],
        shortage_resolutions: proposal.shortage_resolutions || [],
        partial_feasibility: proposal.partial_feasibility || null,
        deferred_nodes: proposal.deferred_nodes || [],
        convergence_warnings: proposal.convergence_warnings || [],
        global_score: proposal.global_score,
        blocked_reasons: proposal.blocked_reasons || [],
        blocked_reason: proposal.blocked_reason,
        reason: proposal.reason,
        slots: (slots || []).map((s) => ({
            job_id: s.job_id ?? jobId,
            machine_id: s.machine_id,
            machineId: s.machine_id,
            scheduled_start: s.scheduled_start,
            scheduled_end: s.scheduled_end,
            actual_start: s.actual_start,
            actual_end: s.actual_end,
            step_name: s.step_name,
            step_id: s.step_id ?? s.stepId,
            stepId: s.step_id ?? s.stepId,
            quantity_planned: s.quantity_planned,
            status: s.status,
            estimated_duration_mins: s.estimated_duration_mins,
        })),
    }
}

/** Format an overlap item for display (string or structured object). */
function formatOverlap(o) {
    if (typeof o === 'string') return o
    if (!o || typeof o !== 'object') return JSON.stringify(o)
    const parts = []
    if (o.machine_id) parts.push(`machine ${o.machine_id}`)
    if (o.job_ids && Array.isArray(o.job_ids)) parts.push(`jobs ${o.job_ids.join(', ')}`)
    if (o.slot_ids && Array.isArray(o.slot_ids)) parts.push(`slots ${o.slot_ids.join(', ')}`)
    if (o.times) parts.push(o.times)
    if (parts.length > 0) return parts.join(' · ')
    return JSON.stringify(o)
}

function uniqueOverlapLines(overlaps) {
    return Array.from(new Set((overlaps || []).map((o) => formatOverlap(o)).filter(Boolean)))
}

/** Map jobs + slots from jobs API to GanttTable format. */
function appliedJobsToGanttJobs(jobs, slotsByJobId) {
    return (jobs || []).map((j) => {
        const jobId = j.job_id || j.jobId || j.id
        if (!jobId) return null
        const slots = slotsByJobId[jobId] || []
        if (slots.length === 0) return null
        return {
            job_id: jobId,
            jobId,
            id: jobId,
            product_id: j.product_id || j.productId,
            productId: j.product_id || j.productId,
            deadline_status: j.deadline_status,
            slots: slots.map((s) => ({
                job_id: s.job_id ?? jobId,
                machine_id: s.machine_id || s.machineId,
                machineId: s.machine_id || s.machineId,
                scheduled_start: s.scheduled_start || s.scheduledStart || s.start_time,
                scheduled_end: s.scheduled_end || s.scheduledEnd || s.end_time,
                actual_start: s.actual_start || s.actualStart,
                actual_end: s.actual_end || s.actualEnd,
                step_name: s.step_name || s.stepName,
                step_id: s.step_id ?? s.stepId,
                stepId: s.step_id ?? s.stepId,
                quantity_planned: s.quantity_planned ?? s.quantityPlanned,
                status: s.status || s.Status,
            })),
        }
    }).filter(Boolean)
}

const ORDER_BY_OPTIONS = [
    { value: 'epo', label: 'EPO' },
    { value: 'edd', label: 'EDD' },
    { value: 'fifo', label: 'FIFO' },
    { value: 'readiness', label: 'Readiness' },
]
const RETRY_POLICY = {
    primaryHorizonDays: 3,
    retryHorizonDays: 6,
    extendedHorizonDays: 14,
    maxRetryAttemptsPerTier: 1,
    topKMachines: 2,
}

const isProposalFeasible = (p) => p?.feasible !== false
const proposalBlockedReason = (p) => {
    const reasons = p?.blocked_reasons
    if (Array.isArray(reasons) && reasons.length > 0) return String(reasons[0])
    if (typeof p?.blocked_reason === 'string' && p.blocked_reason.trim()) return p.blocked_reason.trim()
    if (typeof p?.reason === 'string' && p.reason.trim()) return p.reason.trim()
    return 'no_feasible_window'
}

const byStepId = (shortages = []) =>
    (shortages || []).reduce((acc, s) => {
        const stepId = s?.job_step_id || 'unknown'
        if (!acc[stepId]) acc[stepId] = []
        acc[stepId].push(s)
        return acc
    }, {})

const buildPreviousDeficits = (shortages = []) => {
    const deficits = {}
        ; (shortages || []).forEach((s) => {
            const materialId = s?.material_id
            if (!materialId) return
            const deficit = Number(s?.max_deficit ?? 0)
            deficits[materialId] = Math.max(deficits[materialId] ?? 0, Number.isFinite(deficit) ? deficit : 0)
        })
    return deficits
}

const resolutionEntityId = (resolution) =>
    resolution?.material_id ||
    resolution?.product_id ||
    resolution?.target_product_id ||
    resolution?.replenishment?.material_id ||
    resolution?.replenishment?.product_id

/** Stable key when the same material_id can appear for multiple dependent products (dependency_product_id). */
const resolutionSelectionKey = (resolutionOrNormalized) => {
    const raw = resolutionOrNormalized?.raw || resolutionOrNormalized
    const entityId = resolutionEntityId(raw) || resolutionOrNormalized?.entity_id
    const dep = raw?.dependency_product_id ?? resolutionOrNormalized?.dependency_product_id
    if (!entityId) return ''
    return dep != null && dep !== '' ? `${entityId}::dep:${dep}` : String(entityId)
}

const suggestionQty = (replenishment) =>
    Number(
        replenishment?.suggested_qty ??
        replenishment?.suggested_quantity ??
        replenishment?.quantity ??
        replenishment?.qty ??
        0,
    )

const suggestionArriveAt = (replenishment) =>
    replenishment?.suggested_arrive_at ||
    replenishment?.arrive_at ||
    replenishment?.expected_arrival ||
    replenishment?.earliest_possible_arrival ||
    replenishment?.earliest_feasible_arrival

const normalizeId = (v) => (v == null ? '' : String(v).trim())

const buildNormalizedRecommendation = (resolution, source = 'primary') => {
    const replenishment = resolution?.replenishment || {}
    const entityId = resolutionEntityId(resolution) || 'unknown'
    const qty = suggestionQty(replenishment) || suggestionQty(resolution)
    const suggestedAt = suggestionArriveAt(replenishment) || suggestionArriveAt(resolution)
    return {
        source,
        entity_id: entityId,
        dependency_product_id: resolution?.dependency_product_id ?? null,
        option_type: resolution?.option_type || 'unknown',
        suggested_qty: qty > 0 ? qty : 0,
        suggested_arrive_at: suggestedAt || null,
        earliest_possible_arrival:
            replenishment?.earliest_possible_arrival ||
            resolution?.earliest_possible_arrival ||
            null,
        rationale: resolution?.rationale || resolution?.description || replenishment?.notes || '',
        replenishment,
        raw: resolution,
    }
}

const isMaterialReplenishmentResolution = (resolution) =>
    isReplenishRecommendation(buildNormalizedRecommendation(resolution, 'filter'))

/** 422: backend rejected approve because proposal is not feasible (contract §4E). */
const isInfeasibleApprovalBlockedError = (err, msg) => {
    const s = `${msg || ''} ${err?.message || ''}`.toLowerCase()
    return (
        err?.status === 422 &&
        (s.includes('not fully feasible') ||
            s.includes('cannot be approved') ||
            s.includes('proposal is not fully feasible'))
    )
}

const Scheduling = () => {
    const toast = useToast()
    const [proposals, setProposals] = useState([])
    const [machines, setMachines] = useState([])
    const [loading, setLoading] = useState(false)
    const [, setLoadingExisting] = useState(false)
    const [generateError, setGenerateError] = useState('')
    const [verifyResult, setVerifyResult] = useState(null)
    const [orderBy, setOrderBy] = useState('epo')
    const [rescheduleModalOpen, setRescheduleModalOpen] = useState(false)
    const [applyAllModalOpen, setApplyAllModalOpen] = useState(false)
    const [rejectAllModalOpen, setRejectAllModalOpen] = useState(false)
    const [batchMessage, setBatchMessage] = useState(null)
    const [appliedScheduleItems, setAppliedScheduleItems] = useState([])
    const [loadingApplied, setLoadingApplied] = useState(false)
    const [previewOpen, setPreviewOpen] = useState(false)
    const [previewLoading, setPreviewLoading] = useState(false)
    const [selectedJob, setSelectedJob] = useState(null)
    const [selectedSlot, setSelectedSlot] = useState(null)
    const [validationResults, setValidationResults] = useState([])
    const [urgentInsertModalOpen, setUrgentInsertModalOpen] = useState(false)
    const [batchSummary, setBatchSummary] = useState(null)
    const [bottleneckForecast, setBottleneckForecast] = useState(null)
    const [readinessByJobId, setReadinessByJobId] = useState({})
    const [previewMaterialsByStepId, setPreviewMaterialsByStepId] = useState({})
    const [expandedPreviewStepMaterials, setExpandedPreviewStepMaterials] = useState(new Set())
    const [hardBatchError, setHardBatchError] = useState(null)
    const [shortageCenterOpen, setShortageCenterOpen] = useState(false)
    const [shortageSelections, setShortageSelections] = useState({})
    const [replanStateByJobId, setReplanStateByJobId] = useState({})
    const [shortageActionLoading, setShortageActionLoading] = useState('')
    const [shortageAnalysisLoading, setShortageAnalysisLoading] = useState(false)
    const [infeasiblePreviewListExpanded, setInfeasiblePreviewListExpanded] = useState(false)

    const scheduleItems = useMemo(
        () => (proposals.length > 0 ? proposalsToGanttJobs(proposals) : appliedScheduleItems),
        [proposals, appliedScheduleItems],
    )
    const previewScheduleItems = useMemo(() => proposalsToGanttJobs(proposals), [proposals])
    const selectedProposal = useMemo(() => {
        if (!selectedJob) return null
        const candidateKeys = [
            normalizeId(selectedJob?.proposal_id),
            normalizeId(selectedJob?.id),
            normalizeId(selectedJob?.job_id),
        ].filter(Boolean)
        const found = proposals.find((p) => {
            const keys = [normalizeId(p?.proposal_id), normalizeId(p?.id), normalizeId(p?.job_id)].filter(Boolean)
            return keys.some((k) => candidateKeys.includes(k))
        })
        if (found) return found
        if (selectedJob?.proposal_id || selectedJob?.shortage_resolutions || selectedJob?.material_shortages) return selectedJob
        return null
    }, [selectedJob, proposals])
    const selectedShortages = useMemo(() => selectedProposal?.material_shortages || [], [selectedProposal])
    const selectedResolutionsPrimary = useMemo(() => selectedProposal?.shortage_resolutions || [], [selectedProposal])
    const selectedJobSlots = useMemo(() => selectedJob?.slots || [], [selectedJob])
    const selectedResolutionsFromShortages = useMemo(
        () => selectedShortages.flatMap((s) => s?.per_material_resolutions || []),
        [selectedShortages],
    )
    const normalizedRecommendations = useMemo(() => {
        return [
            ...selectedResolutionsPrimary.map((r) => buildNormalizedRecommendation(r, 'primary')),
            ...selectedResolutionsFromShortages.map((r) => buildNormalizedRecommendation(r, 'fallback')),
        ].filter(isReplenishRecommendation)
    }, [selectedResolutionsPrimary, selectedResolutionsFromShortages])
    const selectedResolutions = useMemo(
        () => [...selectedResolutionsPrimary, ...selectedResolutionsFromShortages].filter(isMaterialReplenishmentResolution),
        [selectedResolutionsPrimary, selectedResolutionsFromShortages],
    )
    const hasRecommendationActions = selectedResolutions.length > 0
    const selectedShortagesByStep = byStepId(selectedShortages)

    const infeasibleProposals = useMemo(
        () => proposals.filter((p) => !isProposalFeasible(p)),
        [proposals],
    )

    useEffect(() => {
        if (!previewOpen) setInfeasiblePreviewListExpanded(false)
    }, [previewOpen])

    useEffect(() => {
        if (!previewOpen) return
        if (selectedJob?.proposal_id) return
        const withRecommendations = proposals.find((p) => {
            if (isProposalFeasible(p)) return false
            const primaryCount = Array.isArray(p?.shortage_resolutions) ? p.shortage_resolutions.length : 0
            const fallbackCount = Array.isArray(p?.material_shortages)
                ? p.material_shortages.reduce((sum, s) => sum + (Array.isArray(s?.per_material_resolutions) ? s.per_material_resolutions.length : 0), 0)
                : 0
            return primaryCount > 0 || fallbackCount > 0
        })
        if (withRecommendations) {
            setSelectedJob(proposalToPreviewJob(withRecommendations))
            setSelectedSlot(null)
        }
    }, [previewOpen, proposals, selectedJob?.proposal_id])

    const formatDateTime = (iso) => {
        if (!iso) return '—'
        return new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    }

    const formatReadinessBadge = (r) => {
        if (!r) return null
        if (r.can_start_now) return { label: 'Ready now', cls: 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 border-emerald-400/50' }
        if (r.earliest_ready_at) {
            const dt = new Date(r.earliest_ready_at)
            const now = new Date()
            const hrs = Math.max(0, Math.round((dt - now) / (60 * 60 * 1000)))
            return { label: hrs < 1 ? 'Ready soon' : `Ready in ~${hrs}h`, cls: 'bg-amber-500/20 text-amber-700 dark:text-amber-400 border-amber-400/50' }
        }
        return null
    }

    useEffect(() => {
        if (!selectedProposal?.proposal_id) return
        const defaults = {}
        const seen = new Set()
            ; (selectedResolutions || []).forEach((r) => {
                const selKey = resolutionSelectionKey(r)
                if (!selKey || seen.has(selKey)) return
                const leadTimeConstrained =
                    r?.replenishment?.is_lead_time_constrained === true ||
                    r?.is_lead_time_constrained === true
                defaults[selKey] = leadTimeConstrained ? 'delay_jobs' : (r?.option_type || 'replenish')
                seen.add(selKey)
            })
            ; selectedShortages.forEach((s) => {
                const materialId = s?.material_id
                if (!materialId || defaults[materialId]) return
                defaults[materialId] = 'replenish'
            })
        setShortageSelections(defaults)
    }, [selectedProposal?.proposal_id, selectedResolutions, selectedShortages])

    const replaceProposalInState = useCallback((nextProposal) => {
        if (!nextProposal?.proposal_id) return
        setProposals((prev) => prev.map((p) =>
            p.proposal_id === nextProposal.proposal_id ? { ...p, ...nextProposal } : p
        ))
    }, [])

    const normalizeReplenishmentItem = (item, fallbackSnapshot, fallbackMaterialId) => {
        const materialId = item?.material_id || fallbackMaterialId
        if (!materialId) return null
        const qty = suggestionQty(item)
        const arriveAt = suggestionArriveAt(item)
        if (!(qty > 0) || !arriveAt) return null
        const payload = {
            material_id: materialId,
            quantity: qty,
            arrive_at: arriveAt,
        }
        if (item.notes) payload.notes = item.notes
        const snapshot = item.inventory_snapshot || fallbackSnapshot
        if (snapshot) payload.inventory_snapshot = snapshot
        return payload
    }

    const selectedReplenishmentPayload = (() => {
        const snapshotsByMaterial = {}
        selectedShortages.forEach((s) => {
            if (s?.material_id && s?.snapshot) snapshotsByMaterial[s.material_id] = s.snapshot
        })
        return normalizedRecommendations
            .filter((rec) => {
                const sel = shortageSelections[resolutionSelectionKey(rec)]
                return isReplenishRecommendation({ ...rec, option_type: sel || rec.option_type })
            })
            .map((rec) => {
                const shortage = selectedShortages.find((s) => normalizeId(s?.material_id) === normalizeId(rec.entity_id))
                return normalizeReplenishmentItem(
                    rec?.replenishment || rec?.raw?.replenishment || rec?.raw,
                    shortage?.snapshot || snapshotsByMaterial[rec.entity_id],
                    rec.entity_id,
                )
            })
            .filter(Boolean)
    })()

    const handleApplySingleRecommendation = async (recommendation) => {
        if (!selectedProposal?.proposal_id) return
        const entityId = recommendation?.entity_id
        if (!isReplenishRecommendation(recommendation)) {
            toast.info('This recommendation is not a material replenishment row.')
            return
        }
        const shortage = selectedShortages.find((s) => normalizeId(s?.material_id) === normalizeId(entityId))
        const payload = normalizeReplenishmentItem(
            recommendation?.replenishment || recommendation?.raw?.replenishment || recommendation?.raw,
            shortage?.snapshot,
            entityId,
        )
        if (!payload) {
            toast.info('This recommendation has no quantity/time payload for apply-replenishment.')
            return
        }
        setShortageActionLoading(`single-${resolutionSelectionKey(recommendation)}`)
        try {
            const rawApply = await aiApi.scheduling.applyReplenishment(selectedProposal.proposal_id, {
                suggestions: [payload],
            })
            const appliedData = toData(rawApply) || rawApply
            const notice = applyReplenishmentClientNotice(appliedData)
            if (notice?.level === 'warn') {
                toast.warning(notice.text)
            } else if (notice?.level === 'info') {
                toast.info(notice.text)
            } else {
                toast.success(`Added expected arrival for ${payload.material_id}.`)
            }
        } catch (err) {
            const msg = (err?.message || '').toLowerCase()
            if (err?.status === 409 && msg.includes('snapshot_conflict')) {
                toast.error('Inventory changed, refresh analysis and try again.')
            } else {
                toast.error(apiErrorMessage(err, 'Failed to apply recommendation.'), apiErrorToastOptions(err))
            }
        } finally {
            setShortageActionLoading('')
        }
    }

    const handleRefreshShortageAnalysis = async () => {
        if (!selectedProposal?.job_id) return
        setShortageAnalysisLoading(true)
        try {
            const response = await aiApi.scheduling.shortageAnalysis(selectedProposal.job_id)
            const analysis = toData(response) || response
            setProposals((prev) => prev.map((p) => {
                if (normalizeId(p?.job_id) !== normalizeId(selectedProposal.job_id)) return p
                return {
                    ...p,
                    material_shortages: analysis?.shortages || p.material_shortages || [],
                    shortage_resolutions:
                        analysis?.resolution_options ||
                        analysis?.replenishment_suggestions ||
                        p.shortage_resolutions ||
                        [],
                    global_score: analysis?.global_score ?? p.global_score,
                }
            }))
            toast.success('Shortage analysis refreshed.')
        } catch (err) {
            toast.error(apiErrorMessage(err, 'Failed to refresh shortage analysis.'), apiErrorToastOptions(err))
        } finally {
            setShortageAnalysisLoading(false)
        }
    }

    const handleApplyReplenishment = async () => {
        if (!selectedProposal?.proposal_id) return
        if (selectedReplenishmentPayload.length === 0) {
            toast.info('No material replenishment items selected for this proposal.')
            return
        }
        setShortageActionLoading('apply-replenishment')
        try {
            const rawApply = await aiApi.scheduling.applyReplenishment(selectedProposal.proposal_id, {
                suggestions: selectedReplenishmentPayload,
            })
            const appliedData = toData(rawApply) || rawApply
            const notice = applyReplenishmentClientNotice(appliedData)
            if (notice?.level === 'warn') {
                toast.warning(notice.text)
            } else if (notice?.level === 'info') {
                toast.info(notice.text)
            } else {
                toast.success('Apply-replenishment completed for selected material arrivals.')
            }
        } catch (err) {
            const msg = (err?.message || '').toLowerCase()
            if (err?.status === 409 && msg.includes('snapshot_conflict')) {
                toast.error('Inventory changed, refresh analysis and try again.')
            } else {
                toast.error(apiErrorMessage(err, 'Failed to apply replenishment.'), apiErrorToastOptions(err))
            }
        } finally {
            setShortageActionLoading('')
        }
    }

    const handleReplenishAndReplan = async () => {
        if (!selectedProposal?.job_id) return
        if (selectedReplenishmentPayload.length === 0) {
            toast.info('No material replenishment items selected for replan.')
            return
        }
        const jobId = selectedProposal.job_id
        const prevState = replanStateByJobId[jobId] || {}
        const attempt = Number(prevState.attempt || 0)
        if (prevState.stopped === true) {
            toast.info('Auto-replan was stopped for this job. Please use manual intervention.')
            return
        }
        if (attempt >= 3) {
            toast.info('Auto-loop capped at 3 attempts. Please continue with manual actions.')
            return
        }
        setShortageActionLoading('replan')
        try {
            const runReplan = async (arrivals, nextAttempt = attempt) => aiApi.scheduling.replenishAndReplan(jobId, {
                arrivals,
                attempt: nextAttempt,
                previous_deficits: prevState.previous_deficits || buildPreviousDeficits(selectedShortages),
                previous_global_score: prevState.previous_global_score ?? selectedProposal.global_score ?? 0,
                allow_partial: false,
            })
            let response
            try {
                response = await runReplan(selectedReplenishmentPayload, attempt)
            } catch (err) {
                const msg = (err?.message || '').toLowerCase()
                if (err?.status === 422 && msg.includes('lead_time_infeasible')) {
                    const earliestByMaterial = normalizedRecommendations.reduce((acc, rec) => {
                        if (rec?.entity_id && rec?.earliest_possible_arrival) acc[rec.entity_id] = rec.earliest_possible_arrival
                        return acc
                    }, {})
                    const adjustedArrivals = selectedReplenishmentPayload.map((a) => {
                        const earliest = earliestByMaterial[a.material_id]
                        if (!earliest) return a
                        return new Date(a.arrive_at) < new Date(earliest) ? { ...a, arrive_at: earliest } : a
                    })
                    response = await runReplan(adjustedArrivals, attempt + 1)
                    toast.info('Lead time adjusted to earliest possible arrival and retried.')
                } else {
                    throw err
                }
            }
            const payload = toData(response) || response
            const nextProposal = payload?.proposal_id ? payload : payload?.proposal || payload?.data || null
            if (nextProposal?.proposal_id) {
                replaceProposalInState({ ...selectedProposal, ...nextProposal, job_id: nextProposal.job_id ?? jobId })
            }
            const latestScore = nextProposal?.global_score ?? selectedProposal.global_score ?? 0
            const latestDeficits = buildPreviousDeficits(nextProposal?.material_shortages || selectedShortages)
            setReplanStateByJobId((prev) => ({
                ...prev,
                [jobId]: {
                    attempt: attempt + 1,
                    previous_deficits: latestDeficits,
                    previous_global_score: latestScore,
                    stopped: false,
                },
            }))
            toast.success('Replenish + replan completed. Proposal updated.')
        } catch (err) {
            const msg = (err?.message || '').toLowerCase()
            if (err?.status === 409 && msg.includes('snapshot_conflict')) {
                toast.error('Inventory changed. Reload shortage analysis and retry.')
                await handleRefreshShortageAnalysis()
            } else if (err?.status === 409 && msg.includes('convergence_failed')) {
                setReplanStateByJobId((prev) => ({
                    ...prev,
                    [jobId]: {
                        ...(prev[jobId] || {}),
                        stopped: true,
                    },
                }))
                toast.error('Convergence failed. Manual intervention required.')
            } else {
                toast.error(apiErrorMessage(err, 'Failed to run replenish + replan.'), apiErrorToastOptions(err))
            }
        } finally {
            setShortageActionLoading('')
        }
    }

    const loadExistingProposals = useCallback(async () => {
        setRescheduleModalOpen(false)
        setBatchMessage(null)
        setLoadingExisting(true)
        setGenerateError('')
        try {
            const data = await jobsApi.list({})
            const jobsList = toList(data)
            const jobIds = jobsList.map((j) => j.job_id || j.jobId || j.id).filter(Boolean)
            const proposalResults = await Promise.allSettled(
                jobIds.map((id) => aiApi.scheduling.listProposals(id))
            )
            const allProposals = []
            proposalResults.forEach((res, idx) => {
                if (res.status !== 'fulfilled') return
                const jobId = jobIds[idx]
                const list = toList(toData(res.value) || res.value)
                const latest = list.find((p) => (p.status || 'draft') === 'draft')
                if (latest && parseProposalPayload(latest).proposed_slots.length > 0) {
                    allProposals.push({ ...latest, job_id: latest.job_id ?? jobId })
                }
            })
            setProposals(allProposals)
            setVerifyResult(null)
            setValidationResults([])
        } catch (err) {
            logger.warn('Could not load existing proposals', { message: err?.message })
            setProposals([])
        } finally {
            setLoadingExisting(false)
        }
    }, [])

    const loadAppliedJobs = useCallback(async () => {
        setLoadingApplied(true)
        try {
            const data = await jobsApi.list({ status: 'scheduled' })
            const jobsList = toList(toData(data) ?? data)
            const jobIds = jobsList.map((j) => j.job_id || j.jobId || j.id).filter(Boolean)
            const slotsByJobId = {}
            await Promise.all(
                jobIds.map(async (id) => {
                    try {
                        const slotsRaw = await jobsApi.getSlots(id)
                        const slots = toList(toData(slotsRaw) ?? slotsRaw)
                        slotsByJobId[id] = slots
                    } catch {
                        slotsByJobId[id] = []
                    }
                })
            )
            const items = appliedJobsToGanttJobs(jobsList, slotsByJobId)
            setAppliedScheduleItems(items)
        } catch (err) {
            logger.warn('Could not load applied jobs', { message: err?.message })
            setAppliedScheduleItems([])
        } finally {
            setLoadingApplied(false)
        }
    }, [])

    useEffect(() => {
        loadAppliedJobs()
    }, [loadAppliedJobs])

    useEffect(() => {
        machinesApi.list()
            .then((data) => setMachines(toList(data).map(normalizeMachine)))
            .catch((err) => logger.warn('Could not load machines', { message: err?.message }))
    }, [])

    useEffect(() => {
        aiApi.scheduling.bottleneckForecast(7)
            .then((r) => setBottleneckForecast(toData(r) ?? r))
            .catch(() => setBottleneckForecast(null))
    }, [])

    // Fetch readiness for selected job and pre-fetch for visible jobs (limit 10)
    const fetchedReadinessRef = useRef(new Set())
    const keepDraftsOnCloseRef = useRef(false)
    useEffect(() => {
        const items = scheduleItems || []
        const toFetch = []
        if (selectedJob) {
            const jid = selectedJob.job_id || selectedJob.jobId || selectedJob.id
            const pid = selectedJob.product_id || selectedJob.productId
            const qty = selectedJob.quantity_total ?? selectedJob.quantity ?? 1
            if (jid && pid && !fetchedReadinessRef.current.has(jid)) toFetch.push({ jobId: jid, productId: pid, quantity: qty })
        }
        items.slice(0, 20).forEach((j) => {
            const jid = j.job_id || j.jobId || j.id
            const pid = j.product_id || j.productId
            const qty = j.quantity_total ?? j.quantity ?? 1
            if (jid && pid && !fetchedReadinessRef.current.has(jid) && !toFetch.some((t) => t.jobId === jid)) {
                toFetch.push({ jobId: jid, productId: pid, quantity: qty })
            }
        })
        toFetch.slice(0, 10).forEach(({ jobId, productId, quantity }) => {
            fetchedReadinessRef.current.add(jobId)
            schedulingApi.readiness(productId, quantity)
                .then((r) => {
                    const d = toData(r) ?? r
                    setReadinessByJobId((prev) => ({ ...prev, [jobId]: { can_start_now: d?.can_start_now, earliest_ready_at: d?.earliest_ready_at } }))
                })
                .catch(() => { fetchedReadinessRef.current.delete(jobId) })
        })
    }, [selectedJob, scheduleItems])

    // Load materials per step for preview sidebar (ProcessStepMaterial from GET /process-steps/:stepId/materials)
    useEffect(() => {
        const slots = selectedJobSlots
        const stepIds = slots.map((s) => s.step_id ?? s.stepId).filter(Boolean)
        if (stepIds.length === 0) {
            setPreviewMaterialsByStepId({})
            return
        }
        setPreviewMaterialsByStepId({})
        Promise.allSettled(
            stepIds.map((sid) =>
                processesApi.getStepMaterials(sid).then((r) => ({ stepId: sid, data: toList(r) }))
            )
        ).then((results) => {
            const byStep = {}
            results.forEach((res) => {
                if (res.status === 'fulfilled' && res.value?.data?.length > 0) {
                    byStep[res.value.stepId] = res.value.data
                }
            })
            setPreviewMaterialsByStepId(byStep)
        })
    }, [selectedJobSlots])

    const runSlotValidation = async (proposalsList) => {
        if (!proposalsList?.length) {
            setValidationResults([])
            return
        }
        const results = []
        for (const p of proposalsList) {
            const { proposed_slots } = parseProposalPayload(p)
            const firstSlot = proposed_slots[0]
            if (!firstSlot?.job_step_id || !firstSlot?.machine_id) continue
            try {
                const res = await schedulingApi.validateSlots({
                    job_step_id: firstSlot.job_step_id,
                    machine_id: firstSlot.machine_id,
                    scheduled_start: firstSlot.scheduled_start,
                    scheduled_end: firstSlot.scheduled_end,
                    quantity: firstSlot.quantity_planned ?? firstSlot.quantity ?? 0,
                    exclude_slot_id: '',
                })
                const data = toData(res) || res
                results.push({
                    proposal_id: p.proposal_id,
                    job_id: p.job_id,
                    valid: data?.valid,
                    hard_reasons: data?.hard_reasons || [],
                    soft_reasons: data?.soft_reasons || [],
                    total_penalty: data?.total_penalty ?? 0,
                })
            } catch (err) {
                if (err?.status === 404) {
                    setValidationResults([])
                    return
                }
                results.push({
                    proposal_id: p.proposal_id,
                    job_id: p.job_id,
                    valid: null,
                    hard_reasons: [err?.message || 'Validation failed'],
                    soft_reasons: [],
                    total_penalty: 0,
                })
            }
        }
        setValidationResults(results)
    }

    const runVerifyOverlaps = async (proposalIdsOrProposals, scope = 'proposals', jobIds = [], options = {}) => {
        const { suppressOverlapToast = false } = options
        const body = scope === 'applied'
            ? {
                scope: 'applied',
                ...(Array.isArray(jobIds) && jobIds.length > 0 ? { job_ids: jobIds } : {}),
            }
            : (() => {
                const ids = Array.isArray(proposalIdsOrProposals) && proposalIdsOrProposals.length > 0 && typeof proposalIdsOrProposals[0] === 'object'
                    ? proposalIdsOrProposals.map((p) => p.proposal_id || p.id).filter(Boolean)
                    : (proposalIdsOrProposals || [])
                return { scope: 'proposals', proposal_ids: ids }
            })()
        const verify = await aiApi.scheduling.verifyOverlaps(body)
        const payload = toData(verify) || verify
        setVerifyResult(payload)
        if (!suppressOverlapToast && !payload?.valid && payload?.overlaps?.length > 0 && scope === 'proposals') {
            toast.error('Schedule has overlaps. Resolve conflicts before applying.')
        }
        return payload
    }

    const handleApplyProposal = async (proposalId, jobId) => {
        if (!proposalId) return
        try {
            const reqKeyBase = `apply-one-${proposalId}-${Date.now()}`
            await aiApi.scheduling.approveProposal(proposalId, {
                skip_staleness_check: true,
                idempotency_key: `${reqKeyBase}-approve`,
            })
            await aiApi.scheduling.applyProposal(proposalId, {
                skip_staleness_check: true,
                idempotency_key: `${reqKeyBase}-apply`,
            })
            toast.success('Proposal applied. Slots created in job plan.')
            loadExistingProposals()
        } catch (err) {
            logger.error('Apply proposal failed', err, { proposalId })
            toast.error(apiErrorMessage(err, 'Failed to apply proposal.'), apiErrorToastOptions(err))
            if (isStaleProposalError(err)) {
                setProposals((prev) => prev.filter((p) => p.proposal_id !== proposalId))
                if (selectedJob?.job_id === jobId) setSelectedJob(null)
            }
        }
    }

    const handleRejectProposal = async (proposalId, jobId) => {
        if (!proposalId) return
        try {
            await aiApi.scheduling.rejectProposal(proposalId, {})
            setProposals((prev) => prev.filter((p) => p.proposal_id !== proposalId))
            if (selectedJob?.job_id === jobId) setSelectedJob(null)
            toast.success(`Proposal for ${jobId} rejected.`)
        } catch (err) {
            logger.error('Reject proposal failed', err, { proposalId })
            toast.error(apiErrorMessage(err, 'Failed to reject proposal.'), apiErrorToastOptions(err))
        }
    }

    const handleRescheduleAll = () => {
        setRescheduleModalOpen(true)
    }

    const handleRescheduleAllConfirm = async () => {
        setRescheduleModalOpen(false)
        setLoading(true)
        setGenerateError('')
        setVerifyResult(null)
        setHardBatchError(null)
        try {
            const batch = await aiApi.scheduling.rescheduleAll({ order_by: orderBy })
            const u = unwrapSchedulingBatchPayload(batch)
            const { proposals: proposalsList, summary, message, byMaterial, byProduct, materialReplenishmentAggregate } = u
            setProposals(proposalsList)
            setBatchMessage(message ? augmentScheduleBatchMessage(message) : null)
            setBatchSummary(
                mergeBatchSummaryWithAggregate({ summary, byMaterial, byProduct, materialReplenishmentAggregate }),
            )

            if (proposalsList.length > 0) {
                await Promise.all([
                    runVerifyOverlaps(proposalsList),
                    runSlotValidation(proposalsList),
                ])
            }

            if (summary) {
                const lateStr = summary.late_count > 0 ? ` (${summary.late_count} late)` : ''
                toast.success(`Rescheduled ${summary.generated || proposalsList.length} proposal(s)${lateStr}.`)
            }
            if (proposalsList.length > 0) {
                setPreviewOpen(true)
            } else {
                toast.info('Reschedule complete. No proposals to show.')
            }
        } catch (err) {
            logger.error('Reschedule all failed', err)
            setGenerateError(apiErrorMessage(err, 'Failed to reschedule.'))
            toast.error(apiErrorMessage(err, 'Failed to reschedule.'), apiErrorToastOptions(err))
        } finally {
            setLoading(false)
        }
    }

    const handleShortageCenterClose = () => {
        setShortageCenterOpen(false)
        setPreviewOpen(true)
    }

    const handleShortageApplySuccess = async (payload) => {
        const priorProposals = proposals
        const u = unwrapSchedulingBatchPayload(payload)
        const {
            proposals: proposalsList,
            summary: shortageSummary,
            message: shortageMsg,
            byMaterial,
            byProduct,
            materialReplenishmentAggregate,
        } = u
        if (proposalsList.length > 0 && priorProposals.length > 0) {
            const scheduleFingerprint = (list) =>
                [...list]
                    .map((p) => `${p.job_id || p.proposal_id}|${JSON.stringify(parseProposalPayload(p).proposed_slots)}`)
                    .sort()
                    .join('||')
            if (scheduleFingerprint(priorProposals) === scheduleFingerprint(proposalsList)) {
                toast.warning(
                    'The regenerated schedule matches the previous one. If material shortages are unchanged, the server may not be loading expected arrivals into reschedule, or arrivals were skipped.',
                )
            }
        }
        setProposals(proposalsList)
        setBatchMessage(shortageMsg ? augmentScheduleBatchMessage(shortageMsg) : null)
        setBatchSummary(
            mergeBatchSummaryWithAggregate({
                summary: shortageSummary,
                byMaterial,
                byProduct,
                materialReplenishmentAggregate,
            }),
        )
        setGenerateError('')
        setVerifyResult(null)
        setHardBatchError(null)

        if (proposalsList.length > 0) {
            await Promise.all([
                runVerifyOverlaps(proposalsList),
                runSlotValidation(proposalsList),
            ])
        }

        if (shortageSummary) {
            const lateStr = shortageSummary.late_count > 0 ? ` (${shortageSummary.late_count} late)` : ''
            toast.success(`Rescheduled ${shortageSummary.generated || proposalsList.length} proposal(s)${lateStr}.`)
        }
        if (proposalsList.length > 0) {
            setPreviewOpen(true)
        } else {
            toast.info('Reschedule complete. No proposals to show.')
        }
        setShortageCenterOpen(false)
    }

    const handleApplyAll = () => {
        setApplyAllModalOpen(true)
    }

    const handleRejectAll = () => {
        setRejectAllModalOpen(true)
    }

    const handlePreviewClose = async () => {
        if (previewLoading) return
        if (keepDraftsOnCloseRef.current) {
            keepDraftsOnCloseRef.current = false
            setPreviewOpen(false)
            return
        }
        if (proposals.length === 0) {
            setPreviewOpen(false)
            setSelectedJob(null)
            setSelectedSlot(null)
            return
        }
        setPreviewLoading(true)
        let discarded = 0
        for (const p of proposals) {
            if (!p.proposal_id) continue
            try {
                await aiApi.scheduling.rejectProposal(p.proposal_id, {})
                discarded++
            } catch (err) {
                toast.error(apiErrorMessage(err, `Failed to discard ${p.job_id}.`), apiErrorToastOptions(err))
            }
        }
        setPreviewLoading(false)
        setProposals([])
        setSelectedJob(null)
        setSelectedSlot(null)
        setPreviewOpen(false)
        loadAppliedJobs()
        if (discarded > 0) toast.info('Preview cancelled. Draft proposals discarded.')
    }

    const handleOpenResolutionCenter = () => {
        keepDraftsOnCloseRef.current = true
        setPreviewOpen(false)
        setShortageCenterOpen(true)
    }

    const handleRejectAllConfirm = async () => {
        setRejectAllModalOpen(false)
        setLoading(true)
        let rejected = 0
        let failed = 0
        for (const p of proposals) {
            if (!p.proposal_id) continue
            try {
                await aiApi.scheduling.rejectProposal(p.proposal_id, {})
                rejected++
            } catch (err) {
                failed++
                toast.error(apiErrorMessage(err, `Failed to reject ${p.job_id}.`), apiErrorToastOptions(err))
            }
        }
        setLoading(false)
        setProposals([])
        setSelectedJob(null)
        setSelectedSlot(null)
        setPreviewOpen(false)
        loadAppliedJobs()
        if (rejected > 0) toast.success(`Discarded ${rejected} proposal(s).`)
        if (failed > 0) toast.warning(`${failed} proposal(s) could not be discarded.`)
    }

    const handleApplyAllConfirm = async () => {
        setApplyAllModalOpen(false)
        if (hasOverlaps || hasValidationHardReasons) {
            toast.error('Schedule conflicts detected on machines. Regenerate before apply.')
            return
        }
        setLoading(true)
        const withId = proposals.filter((p) => p.proposal_id)
        const feasibleCandidates = withId.filter(isProposalFeasible)
        const infeasibleCandidates = withId.filter((p) => !isProposalFeasible(p))
        if (feasibleCandidates.length === 0) {
            const previewReason = infeasibleCandidates[0] ? proposalBlockedReason(infeasibleCandidates[0]) : 'no feasible proposals'
            toast.error(`No feasible proposals to apply (${previewReason}). Regenerate before retrying.`)
            setLoading(false)
            return
        }
        try {
            const proposalIdsForVerify = withId.map((p) => p.proposal_id).filter(Boolean)
            const preVerify = await runVerifyOverlaps(proposalIdsForVerify, 'proposals', [], { suppressOverlapToast: true })
            if (!preVerify?.valid) {
                const lines = uniqueOverlapLines(preVerify?.overlaps)
                const hint = lines.length > 0 ? lines.slice(0, 5).join('; ') : 'overlap pairs in preview'
                toast.error(`Schedule conflicts detected on machines: ${hint}. Regenerate before apply.`)
                setLoading(false)
                return
            }
        } catch (err) {
            toast.error(apiErrorMessage(err, 'Failed to verify proposal overlaps before apply.'), apiErrorToastOptions(err))
            setLoading(false)
            return
        }
        const batchId = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
        let applied = 0
        const appliedIds = new Set()
        const appliedJobIds = new Set()
        const lateJobIds = []
        const failedIds = new Set()
        let hardError = null
        let firstSoftErrorMsg = null
        let firstSoftErrorToastOptions = {}
        let skippedInfeasibleOnApprove = 0
        for (const p of feasibleCandidates) {
            try {
                const approveKey = `apply-all-${batchId}-${p.proposal_id}-approve`
                const applyKey = `apply-all-${batchId}-${p.proposal_id}-apply`
                if ((p.status || 'draft') === 'draft') {
                    try {
                        await aiApi.scheduling.approveProposal(p.proposal_id, {
                            skip_staleness_check: true,
                            idempotency_key: approveKey,
                        })
                    } catch (err) {
                        const msg = apiErrorMessage(err, '')
                        if (!/only draft proposals can be approved/i.test(msg)) throw err
                    }
                }
                await aiApi.scheduling.applyProposal(p.proposal_id, {
                    skip_staleness_check: true,
                    idempotency_key: applyKey,
                })
                applied++
                appliedIds.add(p.proposal_id)
                if (p.job_id) appliedJobIds.add(p.job_id)
                if (p.deadline_status?.is_late === true || p.deadline_status?.isLate === true) lateJobIds.push(p.job_id)
            } catch (err) {
                const msg = apiErrorMessage(err, `Failed to apply ${p.job_id}.`)
                const isWorkCalendar = /outside.*work calendar/i.test(err?.message || msg || '')
                const isStale = isStaleProposalError(err)
                if (isInfeasibleApprovalBlockedError(err, msg)) {
                    skippedInfeasibleOnApprove++
                    continue
                }
                failedIds.add(p.proposal_id)
                if (isWorkCalendar || isStale) {
                    hardError = { err, msg, isWorkCalendar, isStale, proposal: p }
                    break
                }
                if (!firstSoftErrorMsg) {
                    firstSoftErrorMsg = msg
                    firstSoftErrorToastOptions = apiErrorToastOptions(err)
                }
            }
        }
        setLoading(false)
        setProposals((prev) => prev.filter((p) => !appliedIds.has(p.proposal_id) && !failedIds.has(p.proposal_id)))
        if (selectedJob && (appliedIds.has(selectedJob.proposal_id) || failedIds.has(selectedJob.proposal_id))) {
            setSelectedJob(null)
        }
        if (hardError?.isWorkCalendar) {
            setHardBatchError({ type: 'work_calendar', message: hardError.msg })
            toast.error(hardError.msg, apiErrorToastOptions(hardError.err))
            try {
                await schedulingApi.refreshWorkCalendars()
                toast.info('A slot is outside work calendar. Refresh calendars and regenerate proposals.')
            } catch {
                toast.info('A slot is outside work calendar. Refresh calendars and regenerate proposals.')
            }
            return
        }
        if (hardError?.isStale) {
            setHardBatchError({
                type: 'stale',
                message: 'Some proposals are stale for this batch. Regenerate schedule or ensure skip_staleness_check is enabled.',
            })
            toast.error('Some proposals are stale for this batch. Regenerate schedule or ensure skip_staleness_check is enabled.')
            setRescheduleModalOpen(true)
            return
        }
        if (!hardError && firstSoftErrorMsg && failedIds.size > 0) {
            toast.error(
                failedIds.size === 1
                    ? firstSoftErrorMsg
                    : `${firstSoftErrorMsg} (${failedIds.size} proposal(s) failed; others may have applied.)`,
                firstSoftErrorToastOptions,
            )
        }
        if (!hardError && applied === 0 && skippedInfeasibleOnApprove > 0 && failedIds.size === 0 && !firstSoftErrorMsg) {
            toast.info(
                `No proposals applied: ${skippedInfeasibleOnApprove} blocked as not fully feasible. Regenerate proposals before retrying.`,
            )
        }
        if (applied > 0) {
            let postApplyVerifyOk = true
            try {
                const verifyApplied = await runVerifyOverlaps([], 'applied', Array.from(appliedJobIds), { suppressOverlapToast: true })
                if (verifyApplied && verifyApplied.valid === false) {
                    postApplyVerifyOk = false
                    const lines = uniqueOverlapLines(verifyApplied?.overlaps)
                    const hint = lines.length > 0 ? lines.slice(0, 5).join('; ') : 'overlap pairs in applied plan'
                    setHardBatchError({ type: 'overlap', message: `Schedule conflicts detected on machines: ${hint}. Regenerate before retry.` })
                    toast.error(`Schedule conflicts detected on machines: ${hint}. Regenerate before retry.`)
                }
            } catch (err) {
                postApplyVerifyOk = false
                toast.error(apiErrorMessage(err, 'Failed to verify applied overlaps for this batch.'), apiErrorToastOptions(err))
            }
            setPreviewOpen(false)
            loadAppliedJobs()
            if (failedIds.size > 0) loadExistingProposals()
            const lateStr = lateJobIds.length > 0
                ? `. Late: ${lateJobIds.slice(0, 5).join(', ')}${lateJobIds.length > 5 ? ` +${lateJobIds.length - 5} more` : ''}`
                : ''
            const skippedInfeasible = infeasibleCandidates.length + skippedInfeasibleOnApprove
            const skippedSuffix = skippedInfeasible > 0 ? ` · skipped ${skippedInfeasible} infeasible` : ''
            if (postApplyVerifyOk) {
                toast.success(`Applied ${applied}/${feasibleCandidates.length} proposals successfully${skippedSuffix}${lateStr}`)
            }
        }
    }

    const overlaps = verifyResult?.overlaps || []
    const hasOverlaps = verifyResult && !verifyResult.valid
    const validationHardReasons = validationResults.flatMap((r) =>
        (r.hard_reasons || []).map((msg) => ({ job_id: r.job_id, message: msg }))
    )
    const validationSoftReasons = validationResults.flatMap((r) =>
        (r.soft_reasons || []).map((msg) => ({ job_id: r.job_id, message: msg }))
    )
    const totalValidationPenalty = validationResults.reduce((s, r) => s + (r.total_penalty ?? 0), 0)
    const hasValidationHardReasons = validationHardReasons.length > 0
    const hasValidationSoftReasons = validationSoftReasons.length > 0
    const noFeasibleWindowDiagnostics = (() => {
        const source = [batchMessage, generateError, hardBatchError?.message].filter(Boolean).join(' | ')
        if (!source) return null
        const lc = source.toLowerCase()
        const hasNoFeasible =
            lc.includes('no feasible window') ||
            lc.includes('no_feasible_window') ||
            lc.includes('overlap_unresolved') ||
            lc.includes('horizon_cap')
        if (!hasNoFeasible) return null
        const expandedSteps = (source.match(/expanded_steps=([0-9]+)/i) || [])[1]
        const horizonEnd = (source.match(/horizon_end=([^,\s|]+)/i) || [])[1]
        const reasonCode = (source.match(/reason_code=([a-z0-9_]+)/i) || [])[1]
        return { expandedSteps, horizonEnd, reasonCode, raw: source }
    })()

    const uniqueOverlapMessages = uniqueOverlapLines(overlaps)

    const isSameSlot = (slotA, slotB) => {
        if (!slotA || !slotB) return false
        return (slotA.machine_id || slotA.machineId) === (slotB.machine_id || slotB.machineId) &&
            (slotA.scheduled_start || '') === (slotB.scheduled_start || '')
    }

    const handleSelectJobStep = (slot) => {
        if (!slot) return
        setSelectedSlot(slot)
    }

    return (
        <div className="flex h-full w-full flex-col">
            <div className="flex flex-col overflow-hidden flex-1 min-w-0 min-h-0">
                <div className="p-8 border-b border-hairline/50 flex-shrink-0">
                    <PageHeader title="Scheduling" subtitle="Generate and manage AI schedule proposals.">
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="text-xs font-medium text-ink-subtle mr-1">Order by:</span>
                            <select
                                value={orderBy}
                                onChange={(e) => setOrderBy(e.target.value)}
                                className="h-10 px-3 py-1.5 border border-hairline rounded-lg bg-surface-1 text-ink text-sm"
                            >
                                {ORDER_BY_OPTIONS.map((opt) => (
                                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                                ))}
                            </select>
                        </div>

                        <button
                            onClick={handleRescheduleAll}
                            disabled={loading}
                            className="flex items-center gap-2 h-10 px-4 bg-transparent border border-hairline text-ink rounded-lg text-sm font-semibold hover:bg-surface-2 transition-colors disabled:opacity-50"
                        >
                            {loading ? (
                                <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                            ) : (
                                <span className="material-symbols-outlined text-lg">restart_alt</span>
                            )}
                            <span>{loading ? 'Rescheduling…' : 'Reschedule All'}</span>
                        </button>

                        <Link
                            to="/jobs"
                            className="flex items-center gap-2 h-10 px-4 bg-transparent border border-hairline text-ink text-sm font-semibold rounded-lg hover:bg-surface-2 transition-colors"
                        >
                            <span className="material-symbols-outlined text-lg">work</span>
                            <span>Go to Jobs</span>
                        </Link>
                        <Link
                            to="/scheduling/shortage-resolution"
                            className="flex items-center gap-2 h-10 px-4 bg-amber-600 text-white text-sm font-semibold rounded-lg hover:bg-amber-500 transition-colors"
                        >
                            <span className="material-symbols-outlined text-lg">rule</span>
                            <span>Shortage Resolution Center</span>
                        </Link>
                    </PageHeader>
                </div>

                {generateError && (
                    <div className="mx-6 mt-3 flex items-center gap-2 px-4 py-2 bg-red-50 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-700">
                        <span className="material-symbols-outlined text-base">error</span>
                        {generateError}
                    </div>
                )}

                {batchMessage && (
                    <div className="mx-6 mt-3 flex items-start gap-2 px-4 py-3 bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-700 rounded-lg">
                        <span className="material-symbols-outlined text-amber-600 dark:text-amber-500 shrink-0">schedule</span>
                        <p className="text-sm text-amber-900 dark:text-amber-100 whitespace-pre-line">{batchMessage}</p>
                    </div>
                )}
                {bottleneckForecast && Array.isArray(bottleneckForecast.bottlenecks) && bottleneckForecast.bottlenecks.length > 0 && (
                    <div className="mx-6 mt-3 flex items-start gap-2 px-4 py-3 bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-700 rounded-lg">
                        <span className="material-symbols-outlined text-primary dark:text-primary shrink-0">trending_up</span>
                        <div className="text-sm text-blue-900 dark:text-blue-100">
                            <span className="font-semibold">Bottleneck forecast:</span>{' '}
                            {bottleneckForecast.bottlenecks.slice(0, 3).map((b, i) => (
                                <span key={i}>{b.machine_id || b.machine_name || '?'}{i < Math.min(2, bottleneckForecast.bottlenecks.length - 1) ? ', ' : ''}</span>
                            ))}
                        </div>
                    </div>
                )}

                <div className="flex-1 flex min-h-0 p-6 gap-0">
                    <div className="flex-1 overflow-hidden min-w-0">
                        {loadingApplied ? (
                            <div className="flex items-center justify-center h-64 text-ink-subtle gap-3">
                                <span className="w-5 h-5 border-2 border-hairline border-t-primary rounded-full animate-spin" />
                                Loading schedule…
                            </div>
                        ) : appliedScheduleItems.length === 0 ? (
                            <div className="flex flex-col items-center justify-center h-64 text-ink-subtle gap-3">
                                <span className="material-symbols-outlined text-5xl">calendar_today</span>
                                <p>No scheduled jobs yet.</p>
                                <p className="text-sm">Click &quot;Reschedule All&quot; to generate draft proposals, then Apply to create slots in the job plan.</p>
                            </div>
                        ) : (
                            <GanttTable
                                jobs={appliedScheduleItems}
                                machines={machines}
                                selectedJobId={selectedJob?.job_id || selectedJob?.id}
                                selectedSlot={selectedSlot}
                                isPreview={false}
                                onJobClick={(payload) => {
                                    if (!payload) { setSelectedJob(null); setSelectedSlot(null); return }
                                    setSelectedJob(payload.job)
                                    setSelectedSlot(payload.clickedSlot ?? null)
                                }}
                            />
                        )}
                    </div>
                    {selectedJob && !previewOpen && (
                        <aside className="flex-shrink-0 w-80 flex flex-col self-stretch rounded-l-xl -xl border border-hairline bg-surface-1 border-l-0">
                            <div className="p-6 border-b border-hairline flex items-start justify-between shrink-0">
                                <div>
                                    <h3 className="text-lg font-bold text-ink">Job Details</h3>
                                    <p className="text-sm text-ink-subtle mt-0.5">
                                        {selectedJob.job_id || selectedJob.jobId || selectedJob.id}
                                    </p>
                                </div>
                                <button
                                    type="button"
                                    onClick={() => { setSelectedJob(null); setSelectedSlot(null) }}
                                    className="p-1.5 rounded-lg text-ink-subtle hover:text-red-500 dark:hover:text-red-400 hover:bg-surface-2"
                                >
                                    <span className="material-symbols-outlined text-lg">close</span>
                                </button>
                            </div>
                            <div className="flex-1 overflow-y-auto p-6 space-y-5 min-h-0">
                                <div>
                                    <p className="text-xs font-medium text-ink-subtle">Job ID</p>
                                    <p className="mt-0.5 text-sm text-ink">{selectedJob.job_id || selectedJob.jobId || selectedJob.id || '—'}</p>
                                </div>
                                <div>
                                    <p className="text-xs font-medium text-ink-subtle">Product</p>
                                    <p className="mt-0.5 text-sm text-ink">{selectedJob.product_id || selectedJob.productId || '—'}</p>
                                </div>
                                {(() => {
                                    const rBadge = formatReadinessBadge(readinessByJobId[selectedJob.job_id || selectedJob.jobId || selectedJob.id])
                                    return rBadge ? (
                                        <div>
                                            <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-semibold border ${rBadge.cls}`}>
                                                <span className="material-symbols-outlined text-sm">schedule</span>
                                                {rBadge.label}
                                            </span>
                                        </div>
                                    ) : null
                                })()}
                                {selectedJob.proposal_id && (
                                    <div>
                                        <p className="text-xs font-medium text-ink-subtle">Proposal</p>
                                        <p className="mt-0.5 text-xs font-mono text-ink-muted">{selectedJob.proposal_id}</p>
                                    </div>
                                )}
                                {(selectedJob.deadline_status?.is_late || selectedJob.deadline_status?.isLate) && (
                                    <div>
                                        <p className="text-xs font-medium text-ink-subtle">Deadline status</p>
                                        <p className="mt-0.5 text-xs font-semibold text-ink-muted">
                                            Late by {selectedJob.deadline_status?.late_by || selectedJob.deadline_status?.lateBy || ''}
                                        </p>
                                    </div>
                                )}
                                {selectedJob.proposal_id && proposals.some((p) => p.proposal_id === selectedJob.proposal_id) && (
                                    <div className="flex gap-2">
                                        <button
                                            onClick={() => handleApplyProposal(selectedJob.proposal_id, selectedJob.job_id)}
                                            disabled={hasOverlaps || hasValidationHardReasons}
                                            className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg bg-primary text-white text-sm font-bold hover:bg-primary/90 disabled:opacity-50"
                                        >
                                            <span className="material-symbols-outlined text-base">check_circle</span>
                                            Apply
                                        </button>
                                        <button
                                            onClick={() => handleRejectProposal(selectedJob.proposal_id, selectedJob.job_id)}
                                            className="flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg border border-hairline text-ink-subtle text-sm font-semibold hover:bg-red-50 dark:hover:bg-red-900/20 hover:text-ink-muted dark:hover:text-red-400"
                                        >
                                            <span className="material-symbols-outlined text-base">cancel</span>
                                            Reject
                                        </button>
                                    </div>
                                )}
                                <div>
                                    <p className="text-xs font-medium text-ink-subtle mb-2">Step schedule ({selectedJob.slots?.length || 0})</p>
                                    <div className="space-y-2">
                                        {(selectedJob.slots || []).map((slot, i) => {
                                            const dur = slot.scheduled_start && slot.scheduled_end
                                                ? Math.round((new Date(slot.scheduled_end) - new Date(slot.scheduled_start)) / 60000)
                                                : null
                                            const machineLabel = machines.find((m) => (m.machine_id || m.machineId || m.id) === (slot.machine_id || slot.machineId))
                                            const isHighlighted = selectedSlot && isSameSlot(slot, selectedSlot)
                                            return (
                                                <div
                                                    key={slot.slot_id || i}
                                                    role="button"
                                                    tabIndex={0}
                                                    onClick={() => handleSelectJobStep(slot)}
                                                    onKeyDown={(e) => {
                                                        if (e.key === 'Enter' || e.key === ' ') {
                                                            e.preventDefault()
                                                            handleSelectJobStep(slot)
                                                        }
                                                    }}
                                                    className={`cursor-pointer p-3 rounded-lg border transition-colors ${isHighlighted
                                                            ? 'bg-primary/20 dark:bg-primary/30 border-primary dark:border-primary ring-2 ring-primary/50'
                                                            : 'bg-surface-1 border-hairline hover:border-primary/60 hover:bg-surface-2'
                                                        }`}
                                                >
                                                    <div className="flex items-center justify-between mb-1">
                                                        <span className="text-xs font-semibold text-ink">
                                                            {i + 1}. {slot.step_name || `Step ${i + 1}`}
                                                        </span>
                                                    </div>
                                                    <p className="text-xs text-ink-subtle">
                                                        {machineLabel?.machine_name || machineLabel?.machineName || slot.machine_id || '—'}
                                                    </p>
                                                    <p className="text-xs text-ink-muted mt-1">
                                                        {formatDateTime(slot.scheduled_start)} → {formatDateTime(slot.scheduled_end)}
                                                    </p>
                                                    {(dur != null || slot.quantity_planned != null || slot.estimated_duration_mins != null) && (
                                                        <p className="text-[11px] text-ink-subtle mt-1">
                                                            {dur != null && `${dur} min`}
                                                            {dur == null && slot.estimated_duration_mins != null && `~${slot.estimated_duration_mins} min`}
                                                            {dur != null && slot.quantity_planned != null && ' · '}
                                                            {slot.quantity_planned != null && `${slot.quantity_planned} units`}
                                                        </p>
                                                    )}
                                                    {(slot.actual_start || slot.actual_end) && (
                                                        <p className="text-[11px] text-ink-tertiary mt-1">
                                                            Actual: {formatDateTime(slot.actual_start) || '—'} → {formatDateTime(slot.actual_end) || '—'}
                                                        </p>
                                                    )}
                                                </div>
                                            )
                                        })}
                                    </div>
                                </div>
                            </div>
                        </aside>
                    )}
                </div>

            </div>

            <Modal
                isOpen={rescheduleModalOpen}
                onClose={() => setRescheduleModalOpen(false)}
                title="Reschedule All"
                zIndex={60}
            >
                <p className="text-ink-muted mb-4">
                    Reschedule All will cancel all existing slots, delete current proposals, and generate new ones.
                    New draft proposals will be created. You can optionally Apply to create slots, or leave them as drafts. Continue?
                </p>
                <div className="flex justify-end gap-2">
                    <button
                        onClick={() => setRescheduleModalOpen(false)}
                        className="px-4 py-2 rounded-lg border border-hairline text-ink hover:bg-surface-2"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleRescheduleAllConfirm}
                        disabled={loading}
                        className="px-4 py-2 rounded-lg bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
                    >
                        {loading ? 'Rescheduling…' : 'Continue'}
                    </button>
                </div>
            </Modal>

            <Modal
                isOpen={applyAllModalOpen}
                onClose={() => setApplyAllModalOpen(false)}
                title="Apply All"
                zIndex={60}
            >
                <p className="text-ink-muted mb-4">
                    Apply {proposals.length} proposal(s)? Each will be approved then applied to create slots in the job plan. Proposals not applied will remain as drafts.
                </p>
                <div className="flex justify-end gap-2">
                    <button
                        onClick={() => setApplyAllModalOpen(false)}
                        className="px-4 py-2 rounded-lg border border-hairline text-ink hover:bg-surface-2"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleApplyAllConfirm}
                        disabled={loading}
                        className="px-4 py-2 rounded-lg bg-primary text-on-primary hover:bg-primary-hover disabled:opacity-50"
                    >
                        {loading ? 'Applying…' : 'Write to job plan'}
                    </button>
                </div>
            </Modal>

            <Modal
                isOpen={previewOpen}
                onClose={handlePreviewClose}
                title="Schedule Preview"
                size="fullscreen"
            >
                <RescheduleReviewPanel
                    proposals={proposals}
                    machines={machines}
                    summary={batchSummary || {}}
                    validation={verifyResult || {}}
                    validationHardReasons={validationHardReasons}
                    validationSoftReasons={validationSoftReasons}
                    totalValidationPenalty={totalValidationPenalty}
                    loading={loading || previewLoading}
                    selectedJob={selectedJob}
                    selectedSlot={selectedSlot}
                    onSelectionChange={(job, slot) => {
                        setSelectedJob(job)
                        setSelectedSlot(slot)
                    }}
                    onApplyAll={handleApplyAll}
                    onDiscardAll={handleRejectAll}
                    onCancel={handlePreviewClose}
                    onResolve={handleOpenResolutionCenter}
                    onApplyProposal={handleApplyProposal}
                    onRejectProposal={handleRejectProposal}
                    disableApplyAll={hasOverlaps || hasValidationHardReasons || previewLoading || proposals.filter((p) => p.proposal_id && isProposalFeasible(p)).length === 0}
                    showResolveAction={true}
                    framed={false}
                    showHeader={false}
                    title="Schedule Preview"
                    message="Review draft proposals below. Apply to create slots in the job plan, or close to cancel and discard."
                    cancelLabel={previewLoading ? 'Discarding...' : 'Cancel (discard drafts)'}
                    discardLabel="Discard All"
                    applyLabel="Apply All"
                />
                {false && (
                <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
                    <p className="text-sm text-ink-subtle mb-3">
                        Review draft proposals below. Apply to create slots in the job plan, or close to cancel and discard.
                    </p>
                    {batchSummary?.late_jobs && batchSummary.late_jobs.length > 0 && (
                        <div className="mb-3 flex flex-col gap-2 px-4 py-3 bg-red-50/80 border border-red-200 dark:border-red-800 rounded-lg">
                            <div className="flex items-center gap-2 text-sm font-semibold text-red-700">
                                <span className="material-symbols-outlined text-base">schedule</span>
                                Late jobs ({batchSummary.late_jobs.length})
                            </div>
                            <ul className="text-xs text-ink-muted dark:text-red-300 space-y-0.5 list-disc list-inside">
                                {batchSummary.late_jobs.slice(0, 10).map((lj, i) => (
                                    <li key={i}>{lj.job_id}: {lj.late_by || `${lj.tardiness_mins || '?'} min`}</li>
                                ))}
                                {batchSummary.late_jobs.length > 10 && (
                                    <li>… and {batchSummary.late_jobs.length - 10} more</li>
                                )}
                            </ul>
                        </div>
                    )}
                    {((batchSummary?.blocked != null && batchSummary.blocked > 0) || (batchSummary?.skipped != null && batchSummary.skipped > 0) || infeasibleProposals.length > 0) && (
                        <div className="mb-3 flex flex-col gap-1 px-4 py-3 bg-amber-50/80 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
                            <div className="flex items-center gap-2 text-sm font-semibold text-amber-800 dark:text-amber-300 flex-wrap">
                                <span className="material-symbols-outlined text-base">block</span>
                                {(batchSummary?.blocked ?? 0) > 0 && (batchSummary?.skipped ?? 0) > 0 && (
                                    <span>{batchSummary?.blocked} jobs blocked, {batchSummary?.skipped} skipped</span>
                                )}
                                {(batchSummary?.blocked ?? 0) > 0 && (!(batchSummary?.skipped) || batchSummary.skipped === 0) && (
                                    <span>{batchSummary?.blocked} jobs blocked{batchSummary?.blocked_reason ? ` (${batchSummary.blocked_reason})` : ' (material shortage)'}</span>
                                )}
                                {(batchSummary?.skipped ?? 0) > 0 && (!(batchSummary?.blocked) || batchSummary.blocked === 0) && (
                                    <span>{batchSummary?.skipped} jobs skipped</span>
                                )}
                                {infeasibleProposals.length > 0 && (
                                    <span>{infeasibleProposals.length} proposals infeasible</span>
                                )}
                            </div>
                            {infeasibleProposals.length > 0 && (
                                <div>
                                    <ul className="text-xs text-amber-700 dark:text-amber-300 space-y-0.5 list-disc list-inside">
                                        {(infeasiblePreviewListExpanded ? infeasibleProposals : infeasibleProposals.slice(0, 5)).map((p, idx) => (
                                            <li key={`${p.proposal_id || p.job_id || idx}`}>
                                                <button
                                                    type="button"
                                                    onClick={() => {
                                                        setSelectedJob(proposalToPreviewJob(p))
                                                        setSelectedSlot(null)
                                                    }}
                                                    className="underline hover:no-underline"
                                                    title="Open recommendations for this proposal"
                                                >
                                                    {p.job_id || p.proposal_id}: {proposalBlockedReason(p)}
                                                </button>
                                            </li>
                                        ))}
                                    </ul>
                                    {infeasibleProposals.length > 5 && (
                                        <button
                                            type="button"
                                            onClick={() => setInfeasiblePreviewListExpanded((v) => !v)}
                                            className="mt-1.5 text-xs font-semibold text-amber-800 dark:text-amber-200 hover:underline"
                                        >
                                            {infeasiblePreviewListExpanded
                                                ? 'Show fewer'
                                                : `Show all ${infeasibleProposals.length} infeasible`}
                                        </button>
                                    )}
                                    <button
                                        type="button"
                                        onClick={handleOpenResolutionCenter}
                                        className="inline-flex items-center gap-1 mt-2 text-xs font-semibold text-amber-700 dark:text-amber-300 hover:underline"
                                    >
                                        <span className="material-symbols-outlined text-sm">rule</span>
                                        Open Shortage Resolution Center
                                    </button>
                                </div>
                            )}
                        </div>
                    )}
                    {noFeasibleWindowDiagnostics && (
                        <details className="mb-3">
                            <summary className="px-4 py-2 bg-red-50 border border-red-200 dark:border-red-800 rounded-lg text-sm font-medium text-red-800 dark:text-red-300 cursor-pointer hover:bg-surface-2 dark:hover:bg-red-900/30">
                                No feasible window found. Expand for diagnostics and recovery actions.
                            </summary>
                            <div className="mt-1 px-4 py-3 bg-red-50/50 border border-red-200 dark:border-red-800 rounded-lg space-y-2">
                                <ul className="text-xs text-red-700 dark:text-red-300 list-disc list-inside space-y-0.5">
                                    {noFeasibleWindowDiagnostics.reasonCode && <li>reason_code={noFeasibleWindowDiagnostics.reasonCode}</li>}
                                    {noFeasibleWindowDiagnostics.expandedSteps && <li>expanded_steps={noFeasibleWindowDiagnostics.expandedSteps}</li>}
                                    {noFeasibleWindowDiagnostics.horizonEnd && <li>horizon_end={noFeasibleWindowDiagnostics.horizonEnd}</li>}
                                </ul>
                                <p className="text-xs text-red-700 dark:text-red-300">
                                    Retry guidance: regenerate proposals after calendar/capacity updates, or split job set into smaller batches.
                                </p>
                                <div className="text-xs text-red-700 dark:text-red-300 bg-surface-2/60 border border-red-200 dark:border-red-800 rounded-md p-2">
                                    <p className="font-semibold mb-1">Retry policy (deterministic and bounded)</p>
                                    <ul className="list-disc list-inside space-y-0.5">
                                        <li>Primary strict-placement horizon: {RETRY_POLICY.primaryHorizonDays} days (fast, near-term)</li>
                                        <li>Retry horizon: {RETRY_POLICY.retryHorizonDays} days (congestion / weekend gaps; caps default adaptive candidate horizon)</li>
                                        <li>Extended fallback: up to {RETRY_POLICY.extendedHorizonDays} days only if primary + retry still fail with eligible NO_WINDOW-style reasons</li>
                                        <li>Retry/extended are forward-only; max_retry_attempts={RETRY_POLICY.maxRetryAttemptsPerTier} per tier for placement passes</li>
                                        <li>Strict placement: TOP_K_MACHINES={RETRY_POLICY.topKMachines} deterministic machine attempts</li>
                                        <li>Candidate ranking computed once per step cycle; no in-loop re-ranking</li>
                                        <li>Retry never relaxes constraints (global shift, machine calendar, resource calendar still required)</li>
                                        <li>Retry skipped for structural failures (calendar_outside_shift, overlap conflicts, precedence violations)</li>
                                        <li>Split fallback (same machine): earliest-first packing; slice_count ≤ maxSlicesPerStep; covered_minutes ≥ required_minutes; non-overlapping slices; precedence uses last_slice.end; gap policy explicit (max_gap_between_slices, default unlimited)</li>
                                    </ul>
                                    <p className="mt-2 text-[11px] opacity-90">
                                        Observability (logs): job_id, retry, extended_fallback, primary/retry/extended horizon days, result, final_reason, attempted_machine_ids, early_exit, attempts[] with result_enum (NO_WINDOW, OVERLAP, PRECEDENCE, CALENDAR, UNKNOWN).
                                    </p>
                                </div>
                                <div className="flex gap-2">
                                    <button
                                        type="button"
                                        onClick={() => setRescheduleModalOpen(true)}
                                        className="px-3 py-1.5 rounded-md bg-red-600 text-white text-xs font-semibold hover:bg-red-700"
                                    >
                                        Reschedule All
                                    </button>
                                </div>
                            </div>
                        </details>
                    )}
                    {hasOverlaps && uniqueOverlapMessages.length > 0 && (
                        <div className="mb-3 flex flex-col gap-2 px-4 py-3 bg-red-50 border border-red-200 dark:border-red-800 rounded-lg">
                            <div className="flex items-center gap-2 text-sm font-semibold text-red-700">
                                <span className="material-symbols-outlined text-base">warning</span>
                                Schedule conflicts: same machine used at overlapping times
                            </div>
                            <ul className="text-xs text-ink-muted dark:text-red-300 space-y-1 list-disc list-inside">
                                {uniqueOverlapMessages.map((msg, i) => (
                                    <li key={i}>{msg}</li>
                                ))}
                            </ul>
                        </div>
                    )}
                    {hasValidationHardReasons && validationHardReasons.length > 0 && (
                        <div className="mb-3 flex flex-col gap-2 px-4 py-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
                            <div className="flex items-center gap-2 text-sm font-semibold text-amber-800 dark:text-amber-300">
                                <span className="material-symbols-outlined text-base">report_problem</span>
                                Slot validation issues (blocking)
                            </div>
                            <ul className="text-xs text-amber-700 dark:text-amber-400 space-y-1 list-disc list-inside">
                                {validationHardReasons.slice(0, 10).map((v, i) => (
                                    <li key={i}>{v.job_id}: {v.message}</li>
                                ))}
                                {validationHardReasons.length > 10 && (
                                    <li>… and {validationHardReasons.length - 10} more</li>
                                )}
                            </ul>
                            {hasValidationSoftReasons && (
                                <details className="mt-2">
                                    <summary className="text-xs font-medium text-amber-600 dark:text-amber-500 cursor-pointer hover:underline">
                                        Soft issues ({validationSoftReasons.length}) · total penalty: {totalValidationPenalty}
                                    </summary>
                                    <ul className="text-xs text-amber-600 dark:text-amber-400 mt-1 space-y-0.5 list-disc list-inside">
                                        {validationSoftReasons.slice(0, 5).map((v, i) => (
                                            <li key={i}>{v.job_id}: {v.message}</li>
                                        ))}
                                        {validationSoftReasons.length > 5 && (
                                            <li>… and {validationSoftReasons.length - 5} more</li>
                                        )}
                                    </ul>
                                </details>
                            )}
                        </div>
                    )}
                    {!hasValidationHardReasons && hasValidationSoftReasons && (
                        <details className="mb-3">
                            <summary className="px-4 py-2 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg text-sm font-medium text-blue-800 dark:text-blue-300 cursor-pointer hover:bg-blue-100 dark:hover:bg-blue-900/30">
                                Soft validation issues ({validationSoftReasons.length}) · penalty: {totalValidationPenalty}
                            </summary>
                            <div className="mt-1 px-4 py-2 bg-blue-50/50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800 rounded-lg">
                                <ul className="text-xs text-blue-700 space-y-0.5 list-disc list-inside">
                                    {validationSoftReasons.slice(0, 8).map((v, i) => (
                                        <li key={i}>{v.job_id}: {v.message}</li>
                                    ))}
                                    {validationSoftReasons.length > 8 && (
                                        <li>… and {validationSoftReasons.length - 8} more</li>
                                    )}
                                </ul>
                            </div>
                        </details>
                    )}
                    <div className="flex flex-wrap items-center gap-3 mb-3">
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wide bg-amber-400/80 dark:bg-amber-600 text-amber-950 dark:text-amber-100">Draft</span>
                        <button
                            onClick={handleApplyAll}
                            disabled={hasOverlaps || hasValidationHardReasons || previewLoading || proposals.filter((p) => p.proposal_id && isProposalFeasible(p)).length === 0}
                            className="px-3 py-1.5 rounded-md bg-amber-600 text-white text-xs font-semibold hover:bg-amber-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                            Apply All
                        </button>
                        <button
                            onClick={handleRejectAll}
                            disabled={previewLoading}
                            className="px-3 py-1.5 rounded-md border border-hairline text-ink-subtle text-xs font-medium hover:bg-surface-2 disabled:opacity-50"
                        >
                            Discard All
                        </button>
                        <button
                            onClick={handlePreviewClose}
                            disabled={previewLoading}
                            className="px-3 py-1.5 rounded-md border border-red-300 dark:border-red-700 text-red-700 text-xs font-medium hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50"
                        >
                            {previewLoading ? 'Discarding…' : 'Cancel (discard drafts)'}
                        </button>
                        <button
                            type="button"
                            onClick={handleOpenResolutionCenter}
                            disabled={previewLoading}
                            className="px-3 py-1.5 rounded-md border border-amber-300 dark:border-amber-700 text-amber-700 dark:text-amber-300 text-xs font-semibold hover:bg-amber-50 dark:hover:bg-amber-900/20 disabled:opacity-50"
                        >
                            Resolve in Resolution Center
                        </button>
                        <div className="flex flex-wrap items-center gap-1.5">
                            {proposals.slice(0, 10).map((p) => {
                                const isLate = p.deadline_status?.is_late === true || p.deadline_status?.isLate === true
                                const lateBy = p.deadline_status?.late_by || p.deadline_status?.lateBy
                                return (
                                    <span key={p.proposal_id} className="inline-flex items-center gap-0.5">
                                        <button
                                            onClick={() => handleApplyProposal(p.proposal_id, p.job_id)}
                                            disabled={hasOverlaps || hasValidationHardReasons || previewLoading || !isProposalFeasible(p)}
                                            title={!isProposalFeasible(p) ? proposalBlockedReason(p) : undefined}
                                            className={`px-2.5 py-1 rounded-l-md text-xs font-semibold border disabled:opacity-50 flex items-center gap-1 ${isLate
                                                    ? 'bg-surface-2/80 text-red-900 dark:text-red-100 border border-r-0 border-red-400/50'
                                                    : 'bg-surface-1 text-amber-900 dark:text-amber-100 border border-r-0 border-amber-400/50'
                                                }`}
                                        >
                                            {p.job_id}
                                            {!isProposalFeasible(p) && (
                                                <span className="shrink-0 text-[9px] font-semibold px-1.5 py-0.5 rounded-md bg-amber-200/80 dark:bg-amber-700/40 text-amber-900 dark:text-amber-100 border border-amber-500/50">
                                                    Infeasible
                                                </span>
                                            )}
                                            {isLate && (
                                                <span className="shrink-0 text-[9px] font-semibold px-1.5 py-0.5 rounded-md bg-surface-1 text-ink-muted border border-red-400" title={lateBy ? `Late by ${lateBy}` : 'Late'}>
                                                    Late
                                                </span>
                                            )}
                                        </button>
                                        <button
                                            onClick={() => handleRejectProposal(p.proposal_id, p.job_id)}
                                            disabled={previewLoading}
                                            title="Reject proposal"
                                            className={`p-1 rounded-r-md border disabled:opacity-50 text-ink-subtle hover:text-ink-muted ${isLate ? 'border-red-400/50' : 'border-amber-400/50'
                                                }`}
                                        >
                                            <span className="material-symbols-outlined text-sm">close</span>
                                        </button>
                                    </span>
                                )
                            })}
                            {proposals.length > 10 && (
                                <span className="text-[10px] text-amber-600 dark:text-amber-400">+{proposals.length - 10} more</span>
                            )}
                        </div>
                    </div>
                    <div className="flex-1 flex min-h-0 gap-0 border border-amber-300/60 dark:border-amber-600/40 rounded-xl overflow-hidden">
                        <div className="flex-1 overflow-hidden min-w-0">
                            <GanttTable
                                jobs={previewScheduleItems}
                                machines={machines}
                                selectedJobId={selectedJob?.job_id || selectedJob?.id}
                                selectedSlot={selectedSlot}
                                isPreview={true}
                                onJobClick={(payload) => {
                                    if (!payload) { setSelectedJob(null); setSelectedSlot(null); return }
                                    setSelectedJob(payload.job)
                                    setSelectedSlot(payload.clickedSlot ?? null)
                                }}
                            />
                        </div>
                        {selectedJob && selectedProposal && (
                            <aside className="flex-shrink-0 w-80 flex flex-col border-l border-hairline bg-surface-1">
                                <div className="p-4 border-b border-hairline flex items-start justify-between shrink-0">
                                    <div>
                                        <h3 className="text-lg font-bold text-ink">Job Details</h3>
                                        <p className="text-sm text-ink-subtle mt-0.5">
                                            {selectedJob.job_id || selectedJob.jobId || selectedJob.id}
                                        </p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => { setSelectedJob(null); setSelectedSlot(null) }}
                                        className="p-1.5 rounded-lg text-ink-subtle hover:text-red-500 dark:hover:text-red-400 hover:bg-surface-2"
                                    >
                                        <span className="material-symbols-outlined text-lg">close</span>
                                    </button>
                                </div>
                                <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
                                    <div>
                                        <p className="text-xs font-medium text-ink-subtle">Job ID</p>
                                        <p className="mt-0.5 text-sm text-ink">{selectedJob.job_id || selectedJob.jobId || selectedJob.id || '—'}</p>
                                    </div>
                                    <div>
                                        <p className="text-xs font-medium text-ink-subtle">Product</p>
                                        <p className="mt-0.5 text-sm text-ink">{selectedJob.product_id || selectedJob.productId || '—'}</p>
                                    </div>
                                    {(() => {
                                        const rBadge = formatReadinessBadge(readinessByJobId[selectedJob.job_id || selectedJob.jobId || selectedJob.id])
                                        return rBadge ? (
                                            <div>
                                                <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-semibold border ${rBadge.cls}`}>
                                                    <span className="material-symbols-outlined text-sm">schedule</span>
                                                    {rBadge.label}
                                                </span>
                                            </div>
                                        ) : null
                                    })()}
                                    {selectedJob.proposal_id && (
                                        <div>
                                            <p className="text-xs font-medium text-ink-subtle">Proposal</p>
                                            <p className="mt-0.5 text-xs font-mono text-ink-muted">{selectedJob.proposal_id}</p>
                                        </div>
                                    )}
                                    {(selectedJob.deadline_status?.is_late || selectedJob.deadline_status?.isLate) && (
                                        <div>
                                            <p className="text-xs font-medium text-ink-subtle">Deadline status</p>
                                            <p className="mt-0.5 text-xs font-semibold text-ink-muted">
                                                Late by {selectedJob.deadline_status?.late_by || selectedJob.deadline_status?.lateBy || ''}
                                            </p>
                                        </div>
                                    )}
                                    {!isProposalFeasible(selectedProposal) && (
                                        <div>
                                            <p className="text-xs font-medium text-ink-subtle">Blocked reason</p>
                                            <p className="mt-0.5 text-xs font-semibold text-amber-700 dark:text-amber-300">
                                                {proposalBlockedReason(selectedProposal)}
                                            </p>
                                        </div>
                                    )}
                                    <div className="flex gap-2 flex-wrap">
                                        <button
                                            onClick={() => handleApplyProposal(selectedProposal.proposal_id, selectedProposal.job_id)}
                                            disabled={hasOverlaps || hasValidationHardReasons || previewLoading || !isProposalFeasible(selectedProposal)}
                                            title={!isProposalFeasible(selectedProposal) ? proposalBlockedReason(selectedProposal) : undefined}
                                            className="flex-1 min-w-[80px] flex items-center justify-center gap-1.5 py-2 rounded-lg bg-primary text-white text-sm font-bold hover:bg-primary/90 disabled:opacity-50"
                                        >
                                            <span className="material-symbols-outlined text-base">check_circle</span>
                                            Apply
                                        </button>
                                        <button
                                            onClick={() => handleRejectProposal(selectedProposal.proposal_id, selectedProposal.job_id)}
                                            disabled={previewLoading}
                                            className="flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg border border-hairline text-ink-subtle text-sm font-semibold hover:bg-red-50 dark:hover:bg-red-900/20 hover:text-ink-muted dark:hover:text-red-400"
                                        >
                                            <span className="material-symbols-outlined text-base">cancel</span>
                                            Reject
                                        </button>
                                        <button
                                            onClick={() => setUrgentInsertModalOpen(true)}
                                            disabled={previewLoading}
                                            className="flex items-center justify-center gap-1 px-3 py-2 rounded-lg border border-red-400 dark:border-red-600 text-red-700 text-xs font-semibold hover:bg-red-50 dark:hover:bg-red-900/20"
                                        >
                                            <span className="material-symbols-outlined text-sm">priority_high</span>
                                            Urgent
                                        </button>
                                    </div>
                                    {(selectedShortages.length > 0 || hasRecommendationActions) && (
                                        <div className="rounded-lg border border-amber-300/70 dark:border-amber-600/50 bg-amber-50/60 dark:bg-amber-900/10 p-3 space-y-3">
                                            <div className="flex items-center justify-between">
                                                <p className="text-xs font-semibold text-amber-800 dark:text-amber-300">
                                                    Recommendation actions ({selectedResolutions.length})
                                                </p>
                                                <div className="flex items-center gap-2">
                                                    <button
                                                        type="button"
                                                        onClick={handleRefreshShortageAnalysis}
                                                        disabled={shortageAnalysisLoading || shortageActionLoading !== ''}
                                                        className="h-6 px-2 rounded-md border border-amber-300 dark:border-amber-700 text-[10px] text-amber-800 dark:text-amber-300 hover:bg-amber-100/70 dark:hover:bg-amber-900/40 disabled:opacity-50"
                                                    >
                                                        {shortageAnalysisLoading ? 'Refreshing…' : 'Refresh analysis'}
                                                    </button>
                                                    {selectedProposal?.global_score != null && (
                                                        <span className="text-[11px] px-2 py-0.5 rounded-md bg-surface-1 text-amber-800 dark:text-amber-200 border border-amber-300/70 dark:border-amber-700">
                                                            Score: {selectedProposal.global_score}
                                                        </span>
                                                    )}
                                                </div>
                                            </div>
                                            {replanStateByJobId[selectedProposal?.job_id]?.stopped && (
                                                <div className="rounded-md border border-red-300 dark:border-red-700 bg-red-50/80 p-2 text-[11px] text-red-700 dark:text-red-300">
                                                    Replan loop stopped due to convergence failure. Manual intervention: adjust recommendation choices, refresh analysis, or regenerate proposals.
                                                </div>
                                            )}
                                            {Object.entries(selectedShortagesByStep).map(([stepId, items]) => (
                                                <div key={stepId} className="rounded-md border border-amber-200 dark:border-amber-700 p-2 space-y-1">
                                                    <p className="text-[11px] font-semibold text-amber-700 dark:text-amber-300">Step {stepId}</p>
                                                    {items.map((s, i) => (
                                                        <div key={`${s.material_id}-${i}`} className="text-[11px] text-amber-900 dark:text-amber-100">
                                                            <span className="font-medium">{s.material_name || s.material_id}</span>{' '}
                                                            <span className="opacity-90">deficit {s.max_deficit ?? 0}</span>{' '}
                                                            {s.shortage_start_at && <span className="opacity-80">at {formatDateTime(s.shortage_start_at)}</span>}{' '}
                                                            <span className={`px-1.5 py-0.5 rounded border ${s.all_step_materials_feasible === false
                                                                    ? 'bg-surface-2/70 text-red-700 border-red-300 dark:text-red-300 dark:border-red-700'
                                                                    : 'bg-emerald-100/70 text-emerald-700 border-emerald-300 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-700'
                                                                }`}>
                                                                {s.all_step_materials_feasible === false ? 'Blocked' : 'Feasible'}
                                                            </span>
                                                            {s.feasible_qty != null && (
                                                                <span className="ml-1 opacity-80">feasible qty {s.feasible_qty}</span>
                                                            )}
                                                        </div>
                                                    ))}
                                                </div>
                                            ))}
                                            {selectedProposal?.partial_feasibility && (
                                                <p className="text-[11px] text-amber-800 dark:text-amber-300">
                                                    Partial: run {selectedProposal.partial_feasibility.runnable_qty ?? 0}, defer {selectedProposal.partial_feasibility.deferred_qty ?? 0}
                                                </p>
                                            )}
                                            {selectedResolutions.length > 0 && (
                                                <div className="space-y-2">
                                                    <p className="text-[11px] font-semibold text-amber-800 dark:text-amber-300">Resolution by material</p>
                                                    {Array.from(new Set(selectedResolutions.map((r) => resolutionSelectionKey(r)).filter(Boolean))).map((selKey) => {
                                                        const options = selectedResolutions.filter((r) => resolutionSelectionKey(r) === selKey)
                                                        const materialId = resolutionEntityId(options[0]) || selKey
                                                        const depId = options[0]?.dependency_product_id
                                                        return (
                                                            <div key={selKey} className="flex items-center gap-2">
                                                                <span className="text-[11px] w-28 truncate text-amber-900 dark:text-amber-100" title={selKey}>
                                                                    {materialId}
                                                                    {depId ? <span className="block text-[10px] opacity-80 truncate">dep {depId}</span> : null}
                                                                </span>
                                                                <select
                                                                    value={shortageSelections[selKey] || options[0]?.option_type || 'replenish'}
                                                                    onChange={(e) => setShortageSelections((prev) => ({ ...prev, [selKey]: e.target.value }))}
                                                                    className="flex-1 h-8 px-2 text-xs rounded-md border border-amber-300 dark:border-amber-600 bg-surface-1 text-ink"
                                                                >
                                                                    {options.map((opt, idx) => (
                                                                        <option key={`${selKey}-${opt.option_type}-${idx}`} value={opt.option_type}>
                                                                            {opt.option_type}
                                                                        </option>
                                                                    ))}
                                                                </select>
                                                            </div>
                                                        )
                                                    })}
                                                </div>
                                            )}
                                            {normalizedRecommendations.length > 0 && (
                                                <div className="space-y-2">
                                                    <p className="text-[11px] font-semibold text-amber-800 dark:text-amber-300">Recommendation cards</p>
                                                    {normalizedRecommendations.map((rec, idx) => {
                                                        const entityId = rec?.entity_id || `unknown-${idx}`
                                                        const selKey = resolutionSelectionKey(rec)
                                                        const qty = rec?.suggested_qty || 0
                                                        const suggestedAt = rec?.suggested_arrive_at
                                                        const canApplyOneClick =
                                                            isReplenishRecommendation(rec) &&
                                                            qty > 0 &&
                                                            !!suggestedAt
                                                        return (
                                                            <div key={`${selKey}-${rec?.option_type}-${idx}`} className="rounded-md border border-amber-200 dark:border-amber-700 p-2">
                                                                <p className="text-[11px] text-amber-900 dark:text-amber-100">
                                                                    <span className="font-semibold">{entityId}</span>
                                                                    {rec?.dependency_product_id ? (
                                                                        <span className="text-[10px] opacity-80"> · subproduct {rec.dependency_product_id}</span>
                                                                    ) : null}{' '}
                                                                    · {rec?.option_type || 'unknown'}
                                                                    <span className="ml-1 px-1.5 py-0.5 rounded border border-amber-300/70 dark:border-amber-700 text-[10px]">
                                                                        {rec?.source}
                                                                    </span>
                                                                </p>
                                                                <p className="text-[11px] text-amber-800 dark:text-amber-300">
                                                                    Qty: {qty > 0 ? qty : '—'} · Suggested: {suggestedAt ? formatDateTime(suggestedAt) : '—'}
                                                                </p>
                                                                {rec?.earliest_possible_arrival && (
                                                                    <p className="text-[11px] text-amber-700 dark:text-amber-400">
                                                                        Earliest possible arrival: {formatDateTime(rec.earliest_possible_arrival)}
                                                                    </p>
                                                                )}
                                                                {rec?.rationale && (
                                                                    <p className="text-[11px] text-amber-700 dark:text-amber-400 mt-0.5">
                                                                        {rec?.rationale}
                                                                    </p>
                                                                )}
                                                                {canApplyOneClick && (
                                                                    <button
                                                                        type="button"
                                                                        onClick={() => handleApplySingleRecommendation(rec)}
                                                                        disabled={shortageActionLoading !== '' && shortageActionLoading !== `single-${selKey}`}
                                                                        className="mt-2 h-7 px-2 rounded-md bg-amber-700 text-white text-[11px] font-semibold hover:bg-amber-600 disabled:opacity-50"
                                                                    >
                                                                        {shortageActionLoading === `single-${selKey}`
                                                                            ? 'Applying…'
                                                                            : 'Add needed material'}
                                                                    </button>
                                                                )}
                                                            </div>
                                                        )
                                                    })}
                                                </div>
                                            )}
                                            {(selectedShortages.length > 0 && normalizedRecommendations.length === 0) && (
                                                <p className="text-[11px] text-amber-700 dark:text-amber-300 border border-amber-300/70 dark:border-amber-700 rounded-md p-2">
                                                    No actionable recommendation payload was found in this proposal yet. Try refresh analysis, then regenerate proposal.
                                                </p>
                                            )}
                                            <div className="grid grid-cols-2 gap-2">
                                                <button
                                                    type="button"
                                                    onClick={handleApplyReplenishment}
                                                    disabled={shortageActionLoading !== '' || selectedReplenishmentPayload.length === 0}
                                                    className="h-8 rounded-md bg-amber-600 text-white text-xs font-semibold hover:bg-amber-500 disabled:opacity-50"
                                                >
                                                    {shortageActionLoading === 'apply-replenishment' ? 'Applying…' : 'Apply replenishment'}
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={handleReplenishAndReplan}
                                                    disabled={shortageActionLoading !== '' || selectedReplenishmentPayload.length === 0}
                                                    className="h-8 rounded-md bg-primary text-white text-xs font-semibold hover:bg-primary/90 disabled:opacity-50"
                                                >
                                                    {shortageActionLoading === 'replan' ? 'Replanning…' : 'Replenish + replan'}
                                                </button>
                                            </div>
                                        </div>
                                    )}
                                    <div>
                                        <p className="text-xs font-medium text-ink-subtle mb-2">Step schedule ({selectedJob.slots?.length || 0})</p>
                                        <div className="space-y-2">
                                            {(selectedJob.slots || []).map((slot, i) => {
                                                const dur = slot.scheduled_start && slot.scheduled_end
                                                    ? Math.round((new Date(slot.scheduled_end) - new Date(slot.scheduled_start)) / 60000)
                                                    : null
                                                const machineLabel = machines.find((m) => (m.machine_id || m.machineId || m.id) === (slot.machine_id || slot.machineId))
                                                const isHighlighted = selectedSlot && isSameSlot(slot, selectedSlot)
                                                return (
                                                    <div
                                                        key={slot.slot_id || i}
                                                        role="button"
                                                        tabIndex={0}
                                                        onClick={() => handleSelectJobStep(slot)}
                                                        onKeyDown={(e) => {
                                                            if (e.key === 'Enter' || e.key === ' ') {
                                                                e.preventDefault()
                                                                handleSelectJobStep(slot)
                                                            }
                                                        }}
                                                        className={`cursor-pointer p-3 rounded-lg border transition-colors ${isHighlighted
                                                                ? 'bg-primary/20 dark:bg-primary/30 border-primary dark:border-primary ring-2 ring-primary/50'
                                                                : 'bg-surface-1/60 border-hairline hover:border-primary/60 hover:bg-surface-2'
                                                            }`}
                                                    >
                                                        <div className="flex items-center justify-between mb-1">
                                                            <span className="text-xs font-semibold text-ink">
                                                                {i + 1}. {slot.step_name || `Step ${i + 1}`}
                                                            </span>
                                                        </div>
                                                        <p className="text-xs text-ink-subtle">
                                                            {machineLabel?.machine_name || machineLabel?.machineName || slot.machine_id || '—'}
                                                        </p>
                                                        <p className="text-xs text-ink-muted mt-1">
                                                            {formatDateTime(slot.scheduled_start)} → {formatDateTime(slot.scheduled_end)}
                                                        </p>
                                                        {(dur != null || slot.quantity_planned != null || slot.estimated_duration_mins != null) && (
                                                            <p className="text-[11px] text-ink-subtle mt-1">
                                                                {dur != null && `${dur} min`}
                                                                {dur == null && slot.estimated_duration_mins != null && `~${slot.estimated_duration_mins} min`}
                                                                {dur != null && slot.quantity_planned != null && ' · '}
                                                                {slot.quantity_planned != null && `${slot.quantity_planned} units`}
                                                            </p>
                                                        )}
                                                        {(slot.actual_start || slot.actual_end) && (
                                                            <p className="text-[11px] text-ink-tertiary mt-1">
                                                                Actual: {formatDateTime(slot.actual_start) || '—'} → {formatDateTime(slot.actual_end) || '—'}
                                                            </p>
                                                        )}
                                                        {(() => {
                                                            const stepId = slot.step_id ?? slot.stepId
                                                            const mats = stepId ? (previewMaterialsByStepId[stepId] || []) : []
                                                            const inputs = mats.filter((m) => (m.role || '').toLowerCase() !== 'output')
                                                            const labels = inputs.map((m) => {
                                                                const qty = m.quantity_per_unit ?? m.quantity ?? 0
                                                                const u = m.unit || 'ea'
                                                                return `${m.material_id || m.product_id || m.material_name || '—'} (${qty} ${u})`
                                                            })
                                                            if (labels.length === 0) return null
                                                            const key = `${selectedJob?.job_id}-${i}-${stepId}`
                                                            const expanded = expandedPreviewStepMaterials.has(key)
                                                            return (
                                                                <div className="mt-1">
                                                                    <button
                                                                        type="button"
                                                                        onClick={(e) => {
                                                                            e.stopPropagation()
                                                                            setExpandedPreviewStepMaterials((prev) => {
                                                                                const next = new Set(prev)
                                                                                if (next.has(key)) next.delete(key)
                                                                                else next.add(key)
                                                                                return next
                                                                            })
                                                                        }}
                                                                        className="text-[11px] text-amber-600 dark:text-amber-400 hover:underline text-left"
                                                                    >
                                                                        {expanded ? 'Hide materials' : `Show materials (${labels.length})`}
                                                                    </button>
                                                                    {expanded && (
                                                                        <p className="text-[11px] text-amber-700 dark:text-amber-300 mt-0.5">
                                                                            {labels.join(', ')}
                                                                        </p>
                                                                    )}
                                                                </div>
                                                            )
                                                        })()}
                                                    </div>
                                                )
                                            })}
                                        </div>
                                    </div>
                                </div>
                            </aside>
                        )}
                    </div>
                </div>
                )}
            </Modal>

            <UrgentInsertModal
                isOpen={urgentInsertModalOpen}
                onClose={() => setUrgentInsertModalOpen(false)}
                job={selectedJob}
                onSuccess={() => { loadExistingProposals(); loadAppliedJobs() }}
            />

            <Modal
                isOpen={rejectAllModalOpen}
                onClose={() => setRejectAllModalOpen(false)}
                title="Discard All Proposals"
                zIndex={60}
            >
                <p className="text-ink-muted mb-4">
                    Discard all {proposals.length} proposal(s)? This will remove them from the draft bar. No changes will be made to existing job plan slots.
                </p>
                <div className="flex justify-end gap-2">
                    <button
                        onClick={() => setRejectAllModalOpen(false)}
                        className="px-4 py-2 rounded-lg border border-hairline text-ink hover:bg-surface-2"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleRejectAllConfirm}
                        disabled={loading}
                        className="px-4 py-2 rounded-lg bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
                    >
                        {loading ? 'Discarding…' : 'Discard All'}
                    </button>
                </div>
            </Modal>

            <Modal
                isOpen={shortageCenterOpen}
                onClose={handleShortageCenterClose}
                title="Shortage Resolution Center"
                size="fullscreen"
            >
                <ShortageResolution
                    embedded={true}
                    seedProposals={proposals}
                    batchSummary={batchSummary}
                    orderBy={orderBy}
                    onClose={handleShortageCenterClose}
                    onApplySuccess={handleShortageApplySuccess}
                />
            </Modal>
        </div>
    )
}

export default Scheduling
