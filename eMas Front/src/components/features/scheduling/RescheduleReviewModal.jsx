import { useMemo, useState } from 'react'
import GanttTable from '../gantt/GanttTable'
import ShortageResolution from '../../../pages/ShortageResolution'
import InlineBusyIndicator from '../../shared/InlineBusyIndicator'
import {
  mergeBatchSummaryWithAggregate,
  unwrapSchedulingBatchPayload,
} from '../../../services/api'

function readJsonLike(value) {
  if (!value) return null
  if (typeof value === 'object') return value
  if (typeof value !== 'string') return null
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

function firstPresent(source, keys, fallback = '') {
  const object = source && typeof source === 'object' ? source : {}
  for (const key of keys) {
    const value = object[key]
    if (value != null && String(value).trim()) return value
  }
  return fallback
}

export function parseProposalPayload(proposal) {
  if (!proposal) return { proposed_slots: [], product_id: null }
  if (proposal.proposed_slots && Array.isArray(proposal.proposed_slots)) {
    return { proposed_slots: proposal.proposed_slots, product_id: proposal.product_id }
  }
  const parsed = readJsonLike(proposal.proposal_json)
  if (parsed) {
    return {
      proposed_slots: Array.isArray(parsed?.proposed_slots) ? parsed.proposed_slots : [],
      product_id: parsed?.product_id ?? proposal.product_id,
    }
  }
  return { proposed_slots: [], product_id: proposal.product_id }
}

export function proposalsToGanttJobs(proposals) {
  return (proposals || []).map((proposal) => {
    const { proposed_slots: slots, product_id: productId } = parseProposalPayload(proposal)
    const jobId = firstPresent(proposal, ['job_id', 'jobId', 'job'], '')
    if (!jobId) return null
    return {
      job_id: jobId,
      jobId,
      id: jobId,
      product_id: productId ?? proposal.product_id ?? proposal.productId,
      productId: productId ?? proposal.product_id ?? proposal.productId,
      proposal_id: proposal.proposal_id || proposal.proposalId || proposal.id,
      deadline_status: proposal.deadline_status || proposal.deadlineStatus,
      summary: proposal.summary,
      feasible: proposal.feasible,
      material_shortages: proposal.material_shortages || proposal.materialShortages || [],
      shortage_resolutions: proposal.shortage_resolutions || proposal.shortageResolutions || [],
      partial_feasibility: proposal.partial_feasibility || proposal.partialFeasibility || null,
      deferred_nodes: proposal.deferred_nodes || proposal.deferredNodes || [],
      convergence_warnings: proposal.convergence_warnings || proposal.convergenceWarnings || [],
      global_score: proposal.global_score ?? proposal.globalScore,
      blocked_reasons: proposal.blocked_reasons || proposal.blockedReasons || [],
      blocked_reason: proposal.blocked_reason || proposal.blockedReason,
      reason: proposal.reason,
      slots: (slots || []).map((slot) => ({
        job_id: slot.job_id ?? slot.jobId ?? jobId,
        machine_id: slot.machine_id ?? slot.machineId,
        machineId: slot.machine_id ?? slot.machineId,
        scheduled_start: slot.scheduled_start ?? slot.scheduledStart ?? slot.start_time ?? slot.startTime,
        scheduled_end: slot.scheduled_end ?? slot.scheduledEnd ?? slot.end_time ?? slot.endTime,
        actual_start: slot.actual_start ?? slot.actualStart,
        actual_end: slot.actual_end ?? slot.actualEnd,
        step_name: slot.step_name ?? slot.stepName,
        step_id: slot.step_id ?? slot.stepId,
        stepId: slot.step_id ?? slot.stepId,
        quantity_planned: slot.quantity_planned ?? slot.quantityPlanned,
        status: slot.status,
        estimated_duration_mins: slot.estimated_duration_mins ?? slot.estimatedDurationMins,
      })),
    }
  }).filter(Boolean).filter((job) => (job.slots || []).length > 0)
}

export function proposalToPreviewJob(proposal) {
  return proposalsToGanttJobs([proposal])[0] || null
}

export const isProposalFeasible = (proposal) => proposal?.feasible !== false

export function proposalBlockedReason(proposal) {
  const reasons = proposal?.blocked_reasons || proposal?.blockedReasons
  if (Array.isArray(reasons) && reasons.length > 0) return String(reasons[0])
  if (typeof proposal?.blocked_reason === 'string' && proposal.blocked_reason.trim()) return proposal.blocked_reason.trim()
  if (typeof proposal?.blockedReason === 'string' && proposal.blockedReason.trim()) return proposal.blockedReason.trim()
  if (typeof proposal?.reason === 'string' && proposal.reason.trim()) return proposal.reason.trim()
  return 'no_feasible_window'
}

function normalizeProposals(proposals, proposalIds = []) {
  const list = Array.isArray(proposals) ? proposals : []
  if (list.length > 0) return list
  return (proposalIds || []).map((id, index) => ({
    proposal_id: String(id || `Proposal ${index + 1}`),
    status: 'draft',
  }))
}

function proposalIdOf(proposal, fallback = '') {
  return String(firstPresent(proposal, ['proposal_id', 'proposalId', 'id'], fallback) || fallback)
}

function jobIdOf(proposal, fallback = '-') {
  return String(firstPresent(proposal, ['job_id', 'jobId', 'job'], fallback) || fallback)
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString([], {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function proposalTimeRange(proposal) {
  const { proposed_slots: slots } = parseProposalPayload(proposal)
  const starts = slots.map((slot) => slot.scheduled_start || slot.scheduledStart || slot.start_time || slot.startTime).filter(Boolean)
  const ends = slots.map((slot) => slot.scheduled_end || slot.scheduledEnd || slot.end_time || slot.endTime).filter(Boolean)
  const start = starts.sort()[0] || firstPresent(proposal, ['start_time', 'startTime', 'scheduled_start', 'scheduledStart'], null)
  const end = ends.sort().at(-1) || firstPresent(proposal, ['end_time', 'endTime', 'scheduled_end', 'scheduledEnd'], null)
  return { start, end, slots }
}

function proposalMachineLabel(proposal, machines = []) {
  const { slots } = proposalTimeRange(proposal)
  const ids = Array.from(new Set(
    slots
      .map((slot) => slot.machine_id || slot.machineId || slot.machine)
      .filter(Boolean)
      .map(String),
  ))
  if (ids.length === 0) {
    return String(firstPresent(proposal, ['machine_id', 'machineId', 'machine'], '-') || '-')
  }
  const labels = ids.slice(0, 2).map((id) => {
    const machine = machines.find((item) => {
      const machineId = item.machine_id || item.machineId || item.id
      return String(machineId || '') === id
    })
    return machine?.machine_name || machine?.machineName || id
  })
  return `${labels.join(', ')}${ids.length > 2 ? ` +${ids.length - 2}` : ''}`
}

function buildRows(proposals, machines) {
  return (proposals || []).map((proposal, index) => {
    const id = proposalIdOf(proposal, `Proposal ${index + 1}`)
    const { start, end, slots } = proposalTimeRange(proposal)
    return {
      id,
      proposal,
      job: jobIdOf(proposal),
      product: String(firstPresent(proposal, ['product_id', 'productId'], '-') || '-'),
      machine: proposalMachineLabel(proposal, machines),
      start,
      end,
      slotCount: slots.length,
      status: String(firstPresent(proposal, ['status', 'state'], 'draft') || 'draft'),
      feasible: isProposalFeasible(proposal),
      blockedReason: proposalBlockedReason(proposal),
      isLate: proposal?.deadline_status?.is_late === true || proposal?.deadlineStatus?.isLate === true,
    }
  })
}

function findProposalForJob(proposals, job) {
  if (!job) return null
  const keys = [
    job.proposal_id,
    job.proposalId,
    job.id,
    job.job_id,
    job.jobId,
  ].filter(Boolean).map((value) => String(value).toLowerCase())
  return (proposals || []).find((proposal) => {
    const proposalKeys = [
      proposal.proposal_id,
      proposal.proposalId,
      proposal.id,
      proposal.job_id,
      proposal.jobId,
    ].filter(Boolean).map((value) => String(value).toLowerCase())
    return proposalKeys.some((key) => keys.includes(key))
  }) || null
}

function normalizeInteraction(interaction) {
  if (!interaction || typeof interaction !== 'object') return {}
  const payload = interaction.payload && typeof interaction.payload === 'object' ? interaction.payload : {}
  return {
    title: interaction.title || payload.title,
    message: interaction.message || payload.message,
    proposals: interaction.proposals || payload.proposals || interaction.proposal_preview || payload.proposal_preview || [],
    proposalIds: interaction.proposal_ids || interaction.proposalIds || payload.proposal_ids || payload.proposalIds || [],
    summary: interaction.summary || payload.summary || {},
    validation: interaction.validation || payload.validation || {},
  }
}

function countFromSummary(summary, keys, fallback) {
  for (const key of keys) {
    const value = summary?.[key]
    if (value != null && Number.isFinite(Number(value))) return Number(value)
  }
  return fallback
}

function SelectionDetails({ job, proposal, machines, selectedSlot, onClear, onApplyProposal, onRejectProposal, loading, disableApply }) {
  if (!job && !proposal) return null
  const detailJob = job || proposalToPreviewJob(proposal) || {}
  const detailProposal = proposal || detailJob
  const slots = detailJob.slots || []
  return (
    <aside className="flex min-h-0 w-full shrink-0 flex-col border-l border-hairline bg-surface-1 lg:w-80">
      <div className="flex shrink-0 items-start justify-between gap-3 border-b border-hairline p-4">
        <div className="min-w-0">
          <h3 className="text-base font-bold text-ink">Job details</h3>
          <p className="mt-0.5 truncate text-xs text-ink-subtle">
            {detailJob.job_id || detailJob.jobId || detailJob.id || jobIdOf(detailProposal)}
          </p>
        </div>
        <button
          type="button"
          onClick={onClear}
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-subtle hover:bg-surface-2 hover:text-ink"
          aria-label="Close job details"
        >
          <span className="material-symbols-outlined text-[18px]" aria-hidden="true">close</span>
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        <div>
          <p className="text-xs font-medium text-ink-subtle">Job ID</p>
          <p className="mt-0.5 text-sm text-ink">{detailJob.job_id || detailJob.jobId || detailJob.id || jobIdOf(detailProposal)}</p>
        </div>
        <div>
          <p className="text-xs font-medium text-ink-subtle">Product</p>
          <p className="mt-0.5 text-sm text-ink">{detailJob.product_id || detailJob.productId || detailProposal?.product_id || '-'}</p>
        </div>
        {(detailJob.proposal_id || detailProposal?.proposal_id) && (
          <div>
            <p className="text-xs font-medium text-ink-subtle">Proposal</p>
            <p className="mt-0.5 break-all font-mono text-xs text-ink-muted">{detailJob.proposal_id || detailProposal.proposal_id}</p>
          </div>
        )}
        {!isProposalFeasible(detailProposal) && (
          <div className="rounded-md border border-amber-300/70 bg-amber-50/70 p-3 text-xs text-amber-800">
            <p className="font-semibold">Blocked reason</p>
            <p className="mt-1">{proposalBlockedReason(detailProposal)}</p>
          </div>
        )}
        {(onApplyProposal || onRejectProposal) && detailProposal?.proposal_id && (
          <div className="flex flex-wrap gap-2">
            {onApplyProposal && (
              <button
                type="button"
                onClick={() => onApplyProposal(detailProposal.proposal_id, detailProposal.job_id)}
                disabled={loading || disableApply || !isProposalFeasible(detailProposal)}
                className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-bold text-white hover:bg-primary/90 disabled:opacity-50"
                title={!isProposalFeasible(detailProposal) ? proposalBlockedReason(detailProposal) : undefined}
              >
                <span className="material-symbols-outlined text-base" aria-hidden="true">check_circle</span>
                Apply
              </button>
            )}
            {onRejectProposal && (
              <button
                type="button"
                onClick={() => onRejectProposal(detailProposal.proposal_id, detailProposal.job_id)}
                disabled={loading}
                className="inline-flex items-center justify-center gap-1.5 rounded-md border border-hairline px-3 py-2 text-sm font-semibold text-ink-subtle hover:bg-surface-2"
              >
                <span className="material-symbols-outlined text-base" aria-hidden="true">cancel</span>
                Reject
              </button>
            )}
          </div>
        )}
        <div>
          <p className="mb-2 text-xs font-medium text-ink-subtle">Step schedule ({slots.length})</p>
          <div className="space-y-2">
            {slots.length === 0 ? (
              <p className="rounded-md border border-hairline bg-surface-2 p-3 text-xs text-ink-subtle">
                No slot details were included for this proposal.
              </p>
            ) : slots.map((slot, index) => {
              const machineId = slot.machine_id || slot.machineId
              const machine = machines.find((item) => String(item.machine_id || item.machineId || item.id || '') === String(machineId || ''))
              const highlighted = selectedSlot && (
                String(selectedSlot.machine_id || selectedSlot.machineId || '') === String(machineId || '') &&
                String(selectedSlot.scheduled_start || selectedSlot.scheduledStart || '') === String(slot.scheduled_start || slot.scheduledStart || '')
              )
              return (
                <div
                  key={`${slot.step_id || slot.stepId || index}-${slot.scheduled_start || index}`}
                  className={`rounded-md border p-3 ${highlighted ? 'border-primary bg-primary/10' : 'border-hairline bg-surface-1/70'}`}
                >
                  <p className="text-xs font-semibold text-ink">
                    {index + 1}. {slot.step_name || slot.stepName || `Step ${index + 1}`}
                  </p>
                  <p className="mt-1 text-xs text-ink-subtle">
                    {machine?.machine_name || machine?.machineName || machineId || '-'}
                  </p>
                  <p className="mt-1 text-xs text-ink-muted">
                    {formatDateTime(slot.scheduled_start || slot.scheduledStart)} to {formatDateTime(slot.scheduled_end || slot.scheduledEnd)}
                  </p>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </aside>
  )
}

export function RescheduleReviewPanel({
  title = 'Review generated schedule',
  message = 'Review the generated proposals before applying them.',
  proposals = [],
  proposalIds = [],
  summary = {},
  validation = {},
  machines = [],
  loading = false,
  selectedJob = null,
  selectedSlot = null,
  onSelectionChange,
  onApplyAll,
  onCancel,
  onDiscardAll,
  onResolve,
  onApplyProposal,
  onRejectProposal,
  onClose,
  actionState = null,
  disableApplyAll = false,
  showIndividualActions = true,
  showResolveAction = false,
  applyLabel = 'Apply all',
  cancelLabel = 'Cancel',
  discardLabel = 'Discard all',
  closeLabel = 'Cancel reschedule',
  showHeader = true,
  className = '',
  validationHardReasons = [],
  validationSoftReasons = [],
  totalValidationPenalty = 0,
  maxRows = 25,
  framed = true,
}) {
  const normalizedProposals = useMemo(() => normalizeProposals(proposals, proposalIds), [proposals, proposalIds])
  const ids = useMemo(
    () => (proposalIds?.length ? proposalIds : normalizedProposals.map((proposal, index) => proposalIdOf(proposal, `Proposal ${index + 1}`))).filter(Boolean),
    [normalizedProposals, proposalIds],
  )
  const rows = useMemo(() => buildRows(normalizedProposals, machines), [normalizedProposals, machines])
  const ganttJobs = useMemo(() => proposalsToGanttJobs(normalizedProposals), [normalizedProposals])
  const [internalJob, setInternalJob] = useState(null)
  const [internalSlot, setInternalSlot] = useState(null)
  const activeJob = selectedJob || internalJob
  const activeSlot = selectedSlot || internalSlot
  const selectedProposal = findProposalForJob(normalizedProposals, activeJob)
  const feasibleCount = countFromSummary(summary, ['feasible_count', 'feasibleCount'], rows.filter((row) => row.feasible).length || ids.length)
  const conflictCount = countFromSummary(validation, ['conflict_count', 'conflictCount'], countFromSummary(summary, ['conflict_count', 'conflictCount'], 0))
  const lateCount = countFromSummary(summary, ['late_count', 'lateCount'], rows.filter((row) => row.isLate).length)
  const blockedRows = rows.filter((row) => !row.feasible)
  const applyDisabled = loading || disableApplyAll || ids.length === 0
  const isApplying = loading && actionState !== 'cancel'
  const isCancelling = loading && actionState === 'cancel'
  const [summaryCollapsed, setSummaryCollapsed] = useState(false)

  const setSelection = (job, slot = null) => {
    if (onSelectionChange) {
      onSelectionChange(job, slot)
      return
    }
    setInternalJob(job)
    setInternalSlot(slot)
  }

  const clearSelection = () => setSelection(null, null)

  const panelClass = framed
    ? `flex h-full min-h-[520px] flex-col overflow-hidden rounded-md border border-hairline bg-surface-1 ${className}`
    : `flex h-full min-h-[520px] flex-col overflow-hidden bg-surface-1 ${className}`

  return (
    <div className={panelClass}>
      {showHeader && (
        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-hairline px-5 py-4">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-ink">{title}</div>
            <div className="mt-1 text-xs leading-5 text-ink-subtle">{message}</div>
          </div>
          {(onClose || onCancel) && (
            <button
              type="button"
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-hairline bg-surface-2 text-ink-muted hover:bg-surface-3 disabled:opacity-60"
              disabled={loading}
              onClick={onClose || onCancel}
              aria-label={closeLabel}
              title={closeLabel}
            >
              <span className="material-symbols-outlined text-[18px]" aria-hidden="true">close</span>
            </button>
          )}
        </div>
      )}

      <div className="shrink-0 border-b border-hairline px-4 py-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs">
            {[
              ['Proposals', ids.length],
              ['Feasible', feasibleCount],
              ['Conflicts', conflictCount],
              ['Late', lateCount],
            ].map(([label, value]) => (
              <div key={label} className="inline-flex items-baseline gap-1.5 rounded-md border border-hairline bg-surface-2 px-2 py-1">
                <span className="text-[10px] font-medium uppercase text-ink-tertiary">{label}</span>
                <span className="text-sm font-semibold text-ink">{value}</span>
              </div>
            ))}
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-1.5">
            <span className="inline-flex items-center gap-1 rounded-md bg-amber-400/80 px-2 py-1 text-[10px] font-bold uppercase text-amber-950">
              Draft
            </span>
            {onApplyAll && (
              <button
                type="button"
                onClick={() => onApplyAll(ids)}
                disabled={applyDisabled}
                className="inline-flex min-w-[6.5rem] items-center justify-center rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isApplying ? <InlineBusyIndicator label="Applying" /> : applyLabel}
              </button>
            )}
            {onDiscardAll && (
              <button
                type="button"
                onClick={onDiscardAll}
                disabled={loading}
                className="rounded-md border border-hairline px-3 py-1.5 text-xs font-medium text-ink-subtle hover:bg-surface-2 disabled:opacity-60"
              >
                {discardLabel}
              </button>
            )}
            {onCancel && (
              <button
                type="button"
                onClick={onCancel}
                disabled={loading}
                className="rounded-md border border-red-300 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
              >
                {isCancelling ? <InlineBusyIndicator label="Cancelling" /> : cancelLabel}
              </button>
            )}
            {showResolveAction && onResolve && (
              <button
                type="button"
                onClick={onResolve}
                disabled={loading}
                className="rounded-md border border-amber-300 px-3 py-1.5 text-xs font-semibold text-amber-700 hover:bg-amber-50 disabled:opacity-60"
              >
                Resolve in Resolution Center
              </button>
            )}
            <button
              type="button"
              onClick={() => setSummaryCollapsed((prev) => !prev)}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-hairline text-ink-subtle hover:bg-surface-2"
              aria-expanded={!summaryCollapsed}
              aria-label={summaryCollapsed ? 'Show proposal details' : 'Hide proposal details'}
              title={summaryCollapsed ? 'Show proposal details' : 'Hide proposal details'}
            >
              <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
                {summaryCollapsed ? 'unfold_more' : 'unfold_less'}
              </span>
            </button>
          </div>
        </div>

        {!summaryCollapsed && (conflictCount > 0 || validationHardReasons.length > 0 || blockedRows.length > 0 || validationSoftReasons.length > 0) && (
          <div className="mt-2 space-y-1.5">
            {conflictCount > 0 && (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-1.5 text-xs text-red-700">
                Schedule conflicts were detected. Resolve conflicts before applying.
              </div>
            )}
            {validationHardReasons.length > 0 && (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-800">
                <p className="font-semibold">Blocking validation issues ({validationHardReasons.length})</p>
                <ul className="mt-1 list-inside list-disc space-y-0.5">
                  {validationHardReasons.slice(0, 5).map((item, index) => (
                    <li key={`${item.job_id || index}-${item.message || index}`}>{item.job_id ? `${item.job_id}: ` : ''}{item.message || String(item)}</li>
                  ))}
                </ul>
              </div>
            )}
            {blockedRows.length > 0 && (
              <div className="rounded-md border border-amber-200 bg-amber-50/80 px-3 py-1.5 text-xs text-amber-800">
                <span className="font-semibold">{blockedRows.length} proposal(s) are infeasible</span>
                <span className="ml-2">{blockedRows.slice(0, 3).map((row) => `${row.job}: ${row.blockedReason}`).join('; ')}</span>
                {blockedRows.length > 3 && (
                  <span className="ml-2 font-medium">Showing first 3.</span>
                )}
              </div>
            )}
            {validationSoftReasons.length > 0 && (
              <details className="text-xs text-blue-700">
                <summary className="cursor-pointer font-medium">
                  Soft validation issues ({validationSoftReasons.length}) - penalty {totalValidationPenalty}
                </summary>
                <ul className="mt-1 list-inside list-disc space-y-0.5">
                  {validationSoftReasons.slice(0, 5).map((item, index) => (
                    <li key={`${item.job_id || index}-${item.message || index}`}>{item.job_id ? `${item.job_id}: ` : ''}{item.message || String(item)}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}

        {!summaryCollapsed && showIndividualActions && rows.length > 0 && (
          <div className="mt-2 flex min-w-0 flex-wrap items-center gap-1.5">
            {rows.slice(0, 10).map((row) => (
              <span key={row.id} className="inline-flex items-center gap-0.5">
                <button
                  type="button"
                  onClick={() => {
                    const job = proposalToPreviewJob(row.proposal)
                    if (job) setSelection(job, null)
                  }}
                  className={`rounded-md border px-2.5 py-1 text-xs font-semibold ${row.isLate ? 'border-red-400/50 bg-red-50 text-red-800' : 'border-amber-400/50 bg-surface-1 text-amber-900'}`}
                  title={!row.feasible ? row.blockedReason : undefined}
                >
                  {row.job}
                  {!row.feasible && <span className="ml-1 rounded bg-amber-200 px-1 text-[9px]">Infeasible</span>}
                  {row.isLate && <span className="ml-1 rounded bg-surface-1 px-1 text-[9px]">Late</span>}
                </button>
                {onRejectProposal && row.proposal?.proposal_id && (
                  <button
                    type="button"
                    onClick={() => onRejectProposal(row.proposal.proposal_id, row.proposal.job_id)}
                    disabled={loading}
                    title="Reject proposal"
                    className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-hairline text-ink-subtle hover:bg-surface-2 disabled:opacity-60"
                  >
                    <span className="material-symbols-outlined text-sm" aria-hidden="true">close</span>
                  </button>
                )}
              </span>
            ))}
            {rows.length > 10 && (
              <span className="text-[10px] text-amber-600">+{rows.length - 10} more</span>
            )}
          </div>
        )}
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-h-0 min-w-0 overflow-hidden">
          {ganttJobs.length > 0 ? (
            <GanttTable
              jobs={ganttJobs}
              machines={machines}
              selectedJobId={activeJob?.job_id || activeJob?.jobId || activeJob?.id}
              selectedSlot={activeSlot}
              isPreview={true}
              onJobClick={(payload) => {
                if (!payload) {
                  clearSelection()
                  return
                }
                setSelection(payload.job, payload.clickedSlot ?? null)
              }}
            />
          ) : (
            <div className="h-full overflow-auto p-5">
              <table className="w-full border-collapse text-left text-xs">
                <thead className="sticky top-0 bg-surface-1 text-[11px] uppercase text-ink-tertiary">
                  <tr>
                    <th className="border-b border-hairline px-2 py-2 font-semibold">Proposal</th>
                    <th className="border-b border-hairline px-2 py-2 font-semibold">Job</th>
                    <th className="border-b border-hairline px-2 py-2 font-semibold">Product</th>
                    <th className="border-b border-hairline px-2 py-2 font-semibold">Machine</th>
                    <th className="border-b border-hairline px-2 py-2 font-semibold">Start</th>
                    <th className="border-b border-hairline px-2 py-2 font-semibold">End</th>
                    <th className="border-b border-hairline px-2 py-2 font-semibold">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, maxRows).map((row) => (
                    <tr key={row.id} className="border-b border-hairline/70">
                      <td className="px-2 py-2 font-mono text-[11px] text-ink">{row.id}</td>
                      <td className="px-2 py-2 text-ink-muted">{row.job}</td>
                      <td className="px-2 py-2 text-ink-muted">{row.product}</td>
                      <td className="px-2 py-2 text-ink-muted">{row.machine}</td>
                      <td className="px-2 py-2 text-ink-muted">{formatDateTime(row.start)}</td>
                      <td className="px-2 py-2 text-ink-muted">{formatDateTime(row.end)}</td>
                      <td className="px-2 py-2 text-ink-muted">{row.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {rows.length > maxRows && (
                <div className="mt-3 text-xs text-ink-subtle">Showing {maxRows} of {rows.length} proposals.</div>
              )}
            </div>
          )}
        </div>
        <SelectionDetails
          job={activeJob}
          proposal={selectedProposal}
          machines={machines}
          selectedSlot={activeSlot}
          onClear={clearSelection}
          onApplyProposal={onApplyProposal}
          onRejectProposal={onRejectProposal}
          loading={loading}
          disableApply={disableApplyAll}
        />
      </div>
    </div>
  )
}

export default function RescheduleReviewModal({
  open = true,
  interaction = null,
  layer = 'fixed',
  deciding = false,
  decidingAction = null,
  onApply,
  onCancel,
  onClose,
  ...panelProps
}) {
  const [view, setView] = useState('review')
  const [localInteraction, setLocalInteraction] = useState(null)
  if (!open) return null
  if (interaction && interaction.kind && interaction.kind !== 'reschedule_all_review') return null

  const activeInteraction = localInteraction || interaction
  const normalized = normalizeInteraction(activeInteraction)
  const proposals = panelProps.proposals ?? normalized.proposals
  const proposalIds = panelProps.proposalIds ?? normalized.proposalIds
  const summary = panelProps.summary ?? normalized.summary
  const validation = panelProps.validation ?? normalized.validation
  const title = panelProps.title ?? normalized.title ?? 'Review generated schedule'
  const message = panelProps.message ?? normalized.message ?? 'Review the generated proposals before applying them.'
  const ids = proposalIds?.length ? proposalIds : normalizeProposals(proposals, proposalIds).map((proposal, index) => proposalIdOf(proposal, `Proposal ${index + 1}`))

  const overlayClass = layer === 'absolute'
    ? 'absolute inset-0 z-40 flex min-h-0 items-center justify-center bg-black/35 p-4'
    : 'fixed inset-0 z-[80] flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm'
  const dialogHeightClass = layer === 'absolute' ? 'max-h-full' : 'max-h-[88vh]'
  const handleResolutionApplySuccess = async (payload) => {
    const unwrapped = unwrapSchedulingBatchPayload(payload)
    const nextProposals = Array.isArray(unwrapped.proposals) ? unwrapped.proposals : []
    const nextIds = nextProposals.map((proposal) => proposal.proposal_id || proposal.proposalId || proposal.id).filter(Boolean)
    const nextSummary = mergeBatchSummaryWithAggregate({
      summary: unwrapped.summary,
      byMaterial: unwrapped.byMaterial,
      byProduct: unwrapped.byProduct,
      materialReplenishmentAggregate: unwrapped.materialReplenishmentAggregate,
    })
    setLocalInteraction({
      ...(activeInteraction || {}),
      proposals: nextProposals,
      proposal_ids: nextIds,
      summary: nextSummary,
      message: unwrapped.message || activeInteraction?.message || 'Review the regenerated proposals before applying them.',
    })
    setView('review')
  }

  return (
    <div className={overlayClass}>
      <div
        className={`flex ${dialogHeightClass} w-full max-w-[1600px] flex-col overflow-hidden rounded-md border border-hairline bg-surface-1 shadow-2xl`}
        role="dialog"
        aria-modal="true"
        aria-label="Review generated reschedule"
      >
        {view === 'resolution' ? (
          <div className="min-h-0 flex-1 overflow-hidden p-5">
            <ShortageResolution
              embedded={true}
              seedProposals={proposals}
              batchSummary={summary}
              orderBy={panelProps.orderBy || 'epo'}
              onClose={() => setView('review')}
              onApplySuccess={handleResolutionApplySuccess}
            />
          </div>
        ) : (
          <RescheduleReviewPanel
            {...panelProps}
            framed={false}
            title={title}
            message={message}
            proposals={proposals}
            proposalIds={ids}
            summary={summary}
            validation={validation}
            loading={deciding || panelProps.loading}
            actionState={decidingAction}
            onApplyAll={(selectedIds) => onApply?.(activeInteraction, selectedIds)}
            onCancel={() => onCancel?.(activeInteraction)}
            onClose={() => (onClose || onCancel)?.(activeInteraction)}
            onResolve={() => setView('resolution')}
            showResolveAction={panelProps.showResolveAction ?? true}
            showIndividualActions={panelProps.showIndividualActions ?? true}
            applyLabel={panelProps.applyLabel || 'Apply all'}
            cancelLabel={panelProps.cancelLabel || 'Cancel'}
          />
        )}
      </div>
    </div>
  )
}
