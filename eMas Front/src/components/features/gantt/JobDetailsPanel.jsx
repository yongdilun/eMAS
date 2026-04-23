import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { jobsApi, stepsApi, schedulingApi, productsApi, formulasApi, processesApi, aiApi, toList, toData, apiErrorMessage } from '../../../services/api'
import { normalizeStep, normalizeSlot } from '../../../services/normalizers'
import LogProductionModal from '../production/LogProductionModal'
import ReportDelayModal from '../scheduling/ReportDelayModal'
import UrgentInsertModal from '../scheduling/UrgentInsertModal'
import EditJobModal from './EditJobModal'
import logger from '../../../services/logger'

const STATUS_MAP = {
  'in-progress': { dot: 'bg-yellow-400',  text: 'text-yellow-500',  label: 'In Progress' },
  scheduled:     { dot: 'bg-blue-400',    text: 'text-blue-500',    label: 'Scheduled'   },
  completed:     { dot: 'bg-green-400',   text: 'text-green-500',   label: 'Completed'   },
  delayed:       { dot: 'bg-red-400',     text: 'text-red-500',     label: 'Delayed'     },
}

const fmt = (iso) => {
  if (!iso) return '—'
  return new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

const JobDetailsPanel = ({ job, onEdit, onCancel, onJobUpdated, onClose }) => {
  const [steps, setSteps]     = useState([])
  const [slots, setSlots]     = useState([])
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [actionLoading, setActionLoading] = useState('')
  const [actionError, setActionError]     = useState('')
  const [logModalOpen, setLogModalOpen]   = useState(false)
  const [delayModalOpen, setDelayModalOpen] = useState(false)
  const [urgentModalOpen, setUrgentModalOpen] = useState(false)
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [earliestCompletion, setEarliestCompletion] = useState(null)
  const [readiness, setReadiness] = useState(null)
  const [delayRisk, setDelayRisk] = useState(null)
  const [solverPreview, setSolverPreview] = useState(null)
  const [materials, setMaterials] = useState([])
  const [materialsByStepId, setMaterialsByStepId] = useState({})
  const [expandedStepMaterials, setExpandedStepMaterials] = useState(new Set())
  const [explosionByStep, setExplosionByStep] = useState(null)

  const loadStepsAndSlots = useCallback(() => {
    const jobId = job?.job_id || job?.id
    if (!jobId) { setSteps([]); setSlots([]); return }
    setLoadingDetail(true)
    setActionError('')
    Promise.all([jobsApi.getSteps(jobId), jobsApi.getSlots(jobId)])
      .then(([s, sl]) => {
        setSteps(toList(s).map(normalizeStep))
        setSlots(toList(sl).map(normalizeSlot))
      })
      .catch((err) => {
        logger.warn('Could not load job steps/slots', { jobId: job?.id, message: err?.message })
        setSteps([]); setSlots([])
      })
      .finally(() => setLoadingDetail(false))
  }, [job?.job_id, job?.id])

  useEffect(() => {
    loadStepsAndSlots()
  }, [loadStepsAndSlots])

  // Load materials (BOM) for this job's product — try explosion first (step-level), fallback to formula ingredients
  useEffect(() => {
    const productId = job?.product_id || job?.productId || job?.product?.product_id || job?.product?.id
    const qty = job?.quantity_total ?? job?.quantity ?? 1
    if (!productId) { setMaterials([]); setExplosionByStep(null); return }
    setMaterials([])
    setExplosionByStep(null)
    // Try explosion API first (may return step-level material breakdown)
    schedulingApi.explosion(productId, qty).then((raw) => {
      const data = toData(raw) ?? raw
      if (data?.by_step && Array.isArray(data.by_step)) {
        setExplosionByStep(data.by_step)
        setMaterials([])
        return
      }
      if (Array.isArray(data?.items)) {
        setMaterials(data.items)
        return
      }
      if (Array.isArray(data)) {
        setMaterials(data)
        return
      }
      // Fallback: fetch product → formula_id → ingredients
      productsApi.get(productId).then((pRaw) => {
        const p = toData(pRaw) ?? pRaw
        const fid = p?.formula_id ?? p?.FormulaID ?? p?.formulaId
        if (!fid) return
        formulasApi.getIngredients(fid).then((iRaw) => {
          const ings = toList(iRaw)
          setMaterials(ings.map((i) => ({
            material_id: i.material_id ?? i.MaterialID ?? i.materialId ?? '',
            material_name: i.material_name ?? i.MaterialName ?? i.name ?? i.material_id ?? '—',
            quantity: i.quantity_per_unit ?? i.quantity ?? i.quantity_required ?? 0,
            unit: i.unit ?? 'ea',
            step_id: i.step_id ?? i.stepId ?? null,
          })))
        }).catch(() => {})
      }).catch(() => {})
    }).catch(() => {
      // Explosion failed — fallback to formula
      productsApi.get(productId).then((pRaw) => {
        const p = toData(pRaw) ?? pRaw
        const fid = p?.formula_id ?? p?.FormulaID ?? p?.formulaId
        if (!fid) return
        formulasApi.getIngredients(fid).then((iRaw) => {
          const ings = toList(iRaw)
          setMaterials(ings.map((i) => ({
            material_id: i.material_id ?? i.MaterialID ?? i.materialId ?? '',
            material_name: i.material_name ?? i.MaterialName ?? i.name ?? i.material_id ?? '—',
            quantity: i.quantity_per_unit ?? i.quantity ?? i.quantity_required ?? 0,
            unit: i.unit ?? 'ea',
            step_id: i.step_id ?? i.stepId ?? null,
          })))
        }).catch(() => {})
      }).catch(() => {})
    })
  }, [job?.product_id, job?.productId, job?.product?.product_id, job?.product?.id, job?.quantity_total, job?.quantity])

  // Load earliest completion estimate
  useEffect(() => {
    const jobId = job?.job_id || job?.id
    if (!jobId) { setEarliestCompletion(null); return }
    schedulingApi.earliestCompletion(jobId).then((r) => setEarliestCompletion(toData(r) ?? r)).catch(() => setEarliestCompletion(null))
  }, [job?.job_id, job?.id])

  // Load readiness (can_start_now, earliest_ready_at)
  useEffect(() => {
    const productId = job?.product_id || job?.productId || job?.product?.product_id || job?.product?.id
    const qty = job?.quantity_total ?? job?.quantity ?? 1
    if (!productId) { setReadiness(null); return }
    schedulingApi.readiness(productId, qty).then((r) => setReadiness(toData(r) ?? r)).catch(() => setReadiness(null))
  }, [job?.product_id, job?.productId, job?.product?.product_id, job?.product?.id, job?.quantity_total, job?.quantity])

  // Load delay risk (material/sub-product shortage counts)
  useEffect(() => {
    const jobId = job?.job_id || job?.id
    if (!jobId) { setDelayRisk(null); return }
    aiApi.scheduling.delayRisk(jobId).then((r) => setDelayRisk(toData(r) ?? r)).catch(() => setDelayRisk(null))
  }, [job?.job_id, job?.id])

  // Load solver preview (step dependencies, predecessors)
  useEffect(() => {
    const jobId = job?.job_id || job?.id
    if (!jobId) { setSolverPreview(null); return }
    schedulingApi.solverPreview(jobId).then((r) => setSolverPreview(toData(r) ?? r)).catch(() => setSolverPreview(null))
  }, [job?.job_id, job?.id])

  // Load materials per step (ProcessStepMaterial) from GET /process-steps/:stepId/materials
  useEffect(() => {
    const stepIds = (steps || []).map((s) => s.step_id ?? s.stepId).filter(Boolean)
    if (stepIds.length === 0) { setMaterialsByStepId({}); return }
    setMaterialsByStepId({})
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
      setMaterialsByStepId(byStep)
    })
  }, [steps?.map((s) => s.step_id ?? s.stepId).join(',')])

  const handleDuplicate = async () => {
    const jobId = job?.job_id || job?.id
    if (!jobId) return
    setActionLoading('dup')
    setActionError('')
    try {
      await jobsApi.duplicate(jobId)
      logger.info('Job duplicated', { jobId })
      if (onJobUpdated) onJobUpdated()
    } catch (err) {
      logger.error('Failed to duplicate job', err, { jobId })
      setActionError(apiErrorMessage(err))
    } finally {
      setActionLoading('')
    }
  }

  if (!job) {
    return (
      <aside className="flex-shrink-0 w-80 border-l border-gray-200 dark:border-gray-700/50 bg-white dark:bg-[#101718] flex flex-col">
        <div className="p-6 border-b border-gray-200 dark:border-gray-700/50 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">Job Details</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">Select a job to view details</p>
          </div>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg text-gray-500 hover:text-red-500 dark:text-gray-400 dark:hover:text-red-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            >
              <span className="material-symbols-outlined text-base">close</span>
            </button>
          )}
        </div>
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="text-center">
            <span className="material-symbols-outlined text-5xl text-gray-300 dark:text-gray-600">
              event_note
            </span>
            <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">Click any job step in the Gantt chart</p>
          </div>
        </div>
      </aside>
    )
  }

  const statusCfg = STATUS_MAP[job.status] || STATUS_MAP.scheduled

  return (
    <aside className="flex-shrink-0 w-80 border-l border-gray-200 dark:border-gray-700/50 bg-white dark:bg-[#101718] flex flex-col">
      {/* Header */}
      <div className="p-6 border-b border-gray-200 dark:border-gray-700/50 flex items-start justify-between">
        <div>
          <h3 className="text-2xl font-bold text-gray-900 dark:text-white">Job #{job.id}</h3>
          <span className={`inline-flex items-center gap-1.5 mt-1.5 text-sm font-medium ${statusCfg.text}`}>
            <span className={`w-2 h-2 rounded-full ${statusCfg.dot}`} />
            {statusCfg.label}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              title="Hide details"
              className="p-1.5 rounded-lg text-gray-500 hover:text-red-500 dark:text-gray-400 dark:hover:text-red-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            >
              <span className="material-symbols-outlined text-lg">close</span>
            </button>
          )}
          <button
            onClick={handleDuplicate}
            disabled={actionLoading === 'dup'}
            title="Duplicate job (UC-J08)"
            className="p-1.5 rounded-lg text-gray-500 hover:text-primary dark:text-gray-400 dark:hover:text-primary hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-lg">content_copy</span>
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-5">
        {actionError && (
          <p className="text-xs text-red-500 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg">{actionError}</p>
        )}

        {/* Core info — API fields: job_id, product_id, quantity_total, priority, deadline */}
        <Row label="Job ID"   value={job.job_id || job.id || '—'} />
        <Row label="Product"  value={job.product_id || job.name || job.productName || '—'} />
        <Row label="Priority" value={job.priority ? capitalize(job.priority) : '—'} />
        <Row label="Quantity" value={job.quantity_total != null ? `${job.quantity_total} units` : (job.quantity || '—')} />
        <Row label="Completed" value={job.quantity_completed != null ? `${job.quantity_completed} units` : '—'} />
        <Row label="Deadline" value={fmt(job.deadline)} />
        {readiness && (
          <div>
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Readiness</p>
            <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-semibold border ${
              readiness.can_start_now
                ? 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 border-emerald-400/50'
                : readiness.earliest_ready_at
                  ? 'bg-amber-500/20 text-amber-700 dark:text-amber-400 border-amber-400/50'
                  : 'bg-gray-500/20 text-gray-600 dark:text-gray-400 border-gray-400/50'
            }`}>
              <span className="material-symbols-outlined text-sm">schedule</span>
              {readiness.can_start_now
                ? 'Ready now'
                : readiness.earliest_ready_at
                  ? `Ready in ~${Math.max(0, Math.round((new Date(readiness.earliest_ready_at) - new Date()) / (60 * 60 * 1000)))}h`
                  : '—'}
            </span>
          </div>
        )}
        {earliestCompletion?.earliest_completion && (
          <Row label="Earliest completion" value={fmt(earliestCompletion.earliest_completion)} />
        )}
        {delayRisk && ((delayRisk.material_shortage_count ?? delayRisk.MaterialShortageCount ?? 0) > 0 || (delayRisk.sub_product_shortage_count ?? delayRisk.SubProductShortageCount ?? 0) > 0) && (
          <div>
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Material shortage</p>
            <p className="text-sm text-amber-600 dark:text-amber-400">
              {(delayRisk.material_shortage_count ?? delayRisk.MaterialShortageCount ?? 0) > 0 && (
                <span>{(delayRisk.material_shortage_count ?? delayRisk.MaterialShortageCount)} materials short</span>
              )}
              {(delayRisk.material_shortage_count ?? delayRisk.MaterialShortageCount ?? 0) > 0 && (delayRisk.sub_product_shortage_count ?? delayRisk.SubProductShortageCount ?? 0) > 0 && ', '}
              {(delayRisk.sub_product_shortage_count ?? delayRisk.SubProductShortageCount ?? 0) > 0 && (
                <span>{(delayRisk.sub_product_shortage_count ?? delayRisk.SubProductShortageCount)} sub-products short</span>
              )}
            </p>
            <Link
              to="/storage-inventory"
              className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              <span className="material-symbols-outlined text-sm">inventory_2</span>
              View inventory
            </Link>
          </div>
        )}
        {job.notes && <Row label="Notes" value={job.notes} />}

        {/* Timestamps */}
        {(job.created_at || job.updated_at) && (
          <div>
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">Timeline</p>
            {job.created_at && <Row label="Created"  value={fmt(job.created_at)} />}
            {job.updated_at && <Row label="Updated"  value={fmt(job.updated_at)} />}
          </div>
        )}

        {/* Steps */}
        {loadingDetail ? (
          <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
            <span className="w-3 h-3 border border-gray-300 border-t-primary rounded-full animate-spin" />
            Loading steps…
          </div>
        ) : steps.length > 0 && (
          <div>
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">
              Job Steps ({steps.length})
            </p>
            <ol className="space-y-2">
              {steps.map((s, i) => {
                const stepId = s.step_id ?? s.stepId
                const stepEntry = explosionByStep?.[i]
                const matsFromExplosion = Array.isArray(stepEntry) ? stepEntry : (stepEntry?.materials ?? stepEntry?.items ?? [])
                const matsFromFormula = materials.filter((m) => m.step_id && (String(m.step_id) === String(stepId)))
                const matsFromApi = materialsByStepId[stepId] || []
                const matsToShow = explosionByStep ? matsFromExplosion : (materials.some((m) => m.step_id) ? matsFromFormula : null)
                const useApiMats = matsFromApi.length > 0
                const matLabels = useApiMats
                  ? matsFromApi
                      .filter((m) => (m.role || '').toLowerCase() !== 'output')
                      .map((m) => {
                        const qty = m.quantity_per_unit ?? m.quantity ?? 0
                        const u = m.unit || 'ea'
                        return `${m.material_id || m.product_id || m.material_name || '—'} (${qty} ${u})`
                      })
                  : (matsToShow || []).map((m) => m.material_name || m.material_id || m.name || m.MaterialName || '—')
                const solverStep = solverPreview?.steps?.[i]
                const predIds = solverStep?.predecessors ?? solverStep?.depends_on ?? solverStep?.predecessor_ids
                const predNums = Array.isArray(predIds) && predIds.length > 0
                  ? predIds.map((id) => {
                      const idx = solverPreview?.steps?.findIndex((st) => (st.step_id ?? st.stepId ?? st.job_step_id) === id || String(st.step_sequence) === String(id))
                      return idx >= 0 ? idx + 1 : id
                    })
                  : (i > 0 ? Array.from({ length: i }, (_, k) => k + 1) : [])
                const depLabel = predNums.length > 0 ? `Depends on: Step ${predNums.join(', ')}` : null
                return (
                  <li key={s.job_step_id || s.step_id || i} className="flex items-start gap-2 text-sm">
                    <span className="flex-shrink-0 w-5 h-5 rounded-full bg-primary/20 text-primary text-xs flex items-center justify-center font-bold mt-0.5">
                      {s.step_sequence ?? i + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-gray-800 dark:text-gray-200 font-medium">
                        {s.step_name || s.name || s.step_id || `Step ${s.step_sequence ?? i + 1}`}
                      </p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        {s.status ? capitalize(s.status) : ''}
                        {s.quantity_target != null ? ` · Target: ${s.quantity_target}` : ''}
                        {s.quantity_completed != null ? ` · Done: ${s.quantity_completed}` : ''}
                      </p>
                      {depLabel && (
                        <p className="text-xs text-blue-600 dark:text-blue-400 mt-1">{depLabel}</p>
                      )}
                      {((solverStep?.min_wait_minutes != null && solverStep.min_wait_minutes > 0) || (solverStep?.transfer_minutes != null && solverStep.transfer_minutes > 0)) && (
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                          {(solverStep?.min_wait_minutes ?? 0) > 0 && `${solverStep.min_wait_minutes} min wait`}
                          {(solverStep?.min_wait_minutes ?? 0) > 0 && (solverStep?.transfer_minutes ?? 0) > 0 && ' + '}
                          {(solverStep?.transfer_minutes ?? 0) > 0 && `${solverStep.transfer_minutes} min transfer`}
                        </p>
                      )}
                      {matLabels.length > 0 && (
                        <div className="mt-1">
                          <button
                            type="button"
                            onClick={() => {
                              setExpandedStepMaterials((prev) => {
                                const next = new Set(prev)
                                const key = String(stepId ?? i)
                                if (next.has(key)) next.delete(key)
                                else next.add(key)
                                return next
                              })
                            }}
                            className="text-xs text-amber-600 dark:text-amber-400 hover:underline text-left"
                          >
                            {expandedStepMaterials.has(String(stepId ?? i)) ? 'Hide materials' : `Show materials (${matLabels.length})`}
                          </button>
                          {expandedStepMaterials.has(String(stepId ?? i)) && (
                            <p className="text-xs text-amber-700 dark:text-amber-300 mt-0.5">
                              {matLabels.join(', ')}
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  </li>
                )
              })}
            </ol>
          </div>
        )}

        {/* Materials (product-level BOM when not shown per-step) */}
        {!explosionByStep && materials.length > 0 && !materials.some((m) => m.step_id) && (
          <div>
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">
              Materials for this job
            </p>
            <ul className="space-y-1.5 text-sm">
              {materials.map((m, i) => (
                <li key={m.material_id || i} className="flex justify-between items-baseline gap-2">
                  <span className="text-gray-800 dark:text-gray-200 truncate">{m.material_name || m.material_id || '—'}</span>
                  <span className="text-xs text-gray-500 dark:text-gray-400 shrink-0 tabular-nums">
                    {(m.quantity ?? 0) * (job?.quantity_total ?? job?.quantity ?? 1)} {m.unit || 'ea'}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Slots */}
        {!loadingDetail && slots.length > 0 && (
          <div>
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">
              Scheduled Slots ({slots.length})
            </p>
            <div className="space-y-2">
              {slots.map((sl, i) => (
                <SlotCard
                  key={sl.slot_id || i}
                  slot={sl}
                  index={i}
                  onUpdated={loadStepsAndSlots}
                  onError={setActionError}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Footer actions */}
      <div className="p-6 pb-24 border-t border-gray-200 dark:border-gray-700/50 space-y-2">
        <button
          onClick={() => setLogModalOpen(true)}
          className="w-full flex items-center justify-center gap-1.5 h-10 px-4 rounded-lg bg-primary/10 text-primary text-sm font-bold hover:bg-primary/20 transition-colors"
        >
          <span className="material-symbols-outlined text-base">assignment_add</span>
          Log Production
        </button>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => setDelayModalOpen(true)}
            className="flex-1 min-w-[100px] flex items-center justify-center gap-1 h-9 px-3 rounded-lg border border-amber-400 dark:border-amber-600 text-amber-700 dark:text-amber-400 text-xs font-semibold hover:bg-amber-50 dark:hover:bg-amber-900/20"
          >
            <span className="material-symbols-outlined text-sm">schedule</span>
            Report Delay
          </button>
          <button
            onClick={() => setUrgentModalOpen(true)}
            className="flex-1 min-w-[100px] flex items-center justify-center gap-1 h-9 px-3 rounded-lg border border-red-400 dark:border-red-600 text-red-700 dark:text-red-400 text-xs font-semibold hover:bg-red-50 dark:hover:bg-red-900/20"
          >
            <span className="material-symbols-outlined text-sm">priority_high</span>
            Urgent Insert
          </button>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setEditModalOpen(true)}
            className="flex-1 flex items-center justify-center gap-1.5 h-10 px-4 rounded-lg bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-white text-sm font-bold hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors"
          >
            <span className="material-symbols-outlined text-base">edit</span>
            Edit
          </button>
          <button
            onClick={onCancel}
            className="flex-1 flex items-center justify-center gap-1.5 h-10 px-4 rounded-lg bg-red-500/90 text-white text-sm font-bold hover:bg-red-500 transition-colors"
          >
            <span className="material-symbols-outlined text-base">cancel</span>
            Cancel
          </button>
        </div>
      </div>

      <LogProductionModal
        isOpen={logModalOpen}
        onClose={() => setLogModalOpen(false)}
        job={job}
        slots={slots}
        onSlotsUpdated={loadStepsAndSlots}
      />
      <ReportDelayModal
        isOpen={delayModalOpen}
        onClose={() => setDelayModalOpen(false)}
        job={job}
        onSuccess={() => onJobUpdated?.()}
      />
      <UrgentInsertModal
        isOpen={urgentModalOpen}
        onClose={() => setUrgentModalOpen(false)}
        job={job}
        onSuccess={() => onJobUpdated?.()}
      />
      <EditJobModal
        isOpen={editModalOpen}
        onClose={() => setEditModalOpen(false)}
        job={job}
        onSave={() => { onJobUpdated?.(); setEditModalOpen(false) }}
      />
    </aside>
  )
}

const SlotCard = ({ slot: sl, index: i, onUpdated, onError }) => {
  const [loading, setLoading] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const status = (sl.status || 'scheduled').toLowerCase()
  const isPlanned = status === 'planned' || status === 'scheduled'
  const isRunning = status === 'running' || status === 'in-progress'
  const isPaused = status === 'paused'
  const isCompleted = status === 'completed'
  const isCancelled = status === 'cancelled'

  const durationMins = sl.scheduled_start && sl.scheduled_end
    ? Math.round((new Date(sl.scheduled_end) - new Date(sl.scheduled_start)) / 60000)
    : sl.duration_mins ?? null

  const handleAction = async (fn) => {
    if (!sl.slot_id) return
    setLoading(true)
    onError?.('')
    try {
      await fn()
      onUpdated?.()
    } catch (err) {
      onError?.(apiErrorMessage(err))
    } finally {
      setLoading(false)
      setMenuOpen(false)
    }
  }

  const handleStart = () => handleAction(() =>
    stepsApi.updateSlot(sl.slot_id, { status: 'running', actual_start: new Date().toISOString() })
  )
  const handlePause = () => handleAction(() =>
    stepsApi.updateSlot(sl.slot_id, { status: 'paused' })
  )
  const handleResume = () => handleAction(() =>
    stepsApi.updateSlot(sl.slot_id, { status: 'running' })
  )
  const handleComplete = () => handleAction(() =>
    stepsApi.updateSlot(sl.slot_id, { status: 'completed' })
  )
  const handleCancel = () => {
    if (!window.confirm(`Cancel slot ${sl.slot_id}?`)) return
    handleAction(() => stepsApi.cancelSlot(sl.slot_id))
  }

  return (
    <div className="p-3 rounded-lg bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 relative">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">
          {sl.machine_id || `Slot ${i + 1}`}
        </span>
        <div className="flex items-center gap-1">
          {!isCancelled && !isCompleted && (
            <div className="relative">
              <button
                type="button"
                onClick={() => setMenuOpen((o) => !o)}
                disabled={loading}
                className="p-1 rounded text-gray-500 hover:bg-gray-200 dark:hover:bg-gray-700"
              >
                <span className="material-symbols-outlined text-sm">more_horiz</span>
              </button>
              {menuOpen && (
                <div className="absolute right-0 top-7 z-20 py-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg shadow-lg min-w-[120px]">
                  {isPlanned && (
                    <button type="button" onClick={handleStart} className="w-full text-left px-3 py-1.5 text-xs hover:bg-gray-100 dark:hover:bg-gray-700">
                      Start
                    </button>
                  )}
                  {isRunning && (
                    <button type="button" onClick={handlePause} className="w-full text-left px-3 py-1.5 text-xs hover:bg-gray-100 dark:hover:bg-gray-700">
                      Pause
                    </button>
                  )}
                  {isPaused && (
                    <button type="button" onClick={handleResume} className="w-full text-left px-3 py-1.5 text-xs hover:bg-gray-100 dark:hover:bg-gray-700">
                      Resume
                    </button>
                  )}
                  {(isRunning || isPaused) && (
                    <button type="button" onClick={handleComplete} className="w-full text-left px-3 py-1.5 text-xs text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20">
                      Complete
                    </button>
                  )}
                  <button type="button" onClick={handleCancel} className="w-full text-left px-3 py-1.5 text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20">
                    Cancel slot
                  </button>
                </div>
              )}
            </div>
          )}
          <SlotBadge status={sl.status} />
        </div>
      </div>
      <p className="text-xs text-gray-500 dark:text-gray-400">
        {fmt(sl.scheduled_start || sl.start_time)}
        {durationMins != null ? ` · ${durationMins} min` : ''}
        {(sl.quantity_planned ?? sl.quantity) != null ? ` · ${sl.quantity_planned ?? sl.quantity} units` : ''}
      </p>
      {(sl.actual_start || sl.actual_end) && (
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          Actual: {fmt(sl.actual_start) || '—'} → {fmt(sl.actual_end) || '—'}
        </p>
      )}
    </div>
  )
}

const Row = ({ label, value }) => (
  <div>
    <p className="text-xs font-medium text-gray-500 dark:text-gray-400">{label}</p>
    <p className="mt-0.5 text-sm text-gray-900 dark:text-white">{value}</p>
  </div>
)

const SlotBadge = ({ status }) => {
  const cfg = {
    completed:   'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400',
    'in-progress':'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400',
    running:     'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400',
    paused:      'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400',
    planned:     'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
    scheduled:   'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
    cancelled:   'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400',
  }
  const cls = cfg[status] || cfg.scheduled
  return (
    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${cls}`}>
      {status || 'scheduled'}
    </span>
  )
}

const capitalize = (s) => s.charAt(0).toUpperCase() + s.slice(1)

export default JobDetailsPanel
