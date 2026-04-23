import { useState, useEffect, useCallback } from 'react'
import PageHeader from '../components/shared/PageHeader'
import { productsApi, processesApi, formulasApi, machinesApi, inventoryApi, referenceApi, toList, toData, apiErrorMessage } from '../services/api'
import RefSelect from '../components/shared/RefSelect'
import { useRefObjects } from '../hooks/useRefData'
import { normalizeProduct, debugResponse } from '../services/normalizers'
import logger from '../services/logger'
import { useToast } from '../context/ToastContext'

// ─── Product Form Modal ───────────────────────────────────────────────────────
// API fields: product_id, product_name, product_type, unit_of_measure, description
const EMPTY_PRODUCT = { productId: '', productName: '', productType: '', unitOfMeasure: 'pcs', description: '' }

const ProductModal = ({ isOpen, onClose, onSave, product }) => {
  const isEdit = !!product
  const [form, setForm]       = useState(EMPTY_PRODUCT)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState('')

  useEffect(() => {
    if (!isOpen) return
    setForm(product
      ? {
          productId:     product.product_id || product.id || '',
          productName:   product.product_name || product.name || '',
          productType:   product.product_type || product.category || '',
          unitOfMeasure: product.unit_of_measure || product.unit || 'pcs',
          description:   product.description || '',
        }
      : EMPTY_PRODUCT)
    setError('')
  }, [isOpen, product])

  const handle = (e) => setForm((p) => ({ ...p, [e.target.name]: e.target.value }))

  const submit = async () => {
    if (!form.productId || !form.productName) { setError('Product ID and Name are required.'); return }
    setLoading(true); setError('')
    const payload = {
      product_id:      form.productId,
      product_name:    form.productName,
      product_type:    form.productType    || undefined,
      unit_of_measure: form.unitOfMeasure  || undefined,
      description:     form.description   || undefined,
    }
    try {
      const raw = isEdit
        ? (await productsApi.update?.(form.productId, payload)) ?? (await productsApi.create(payload))
        : await productsApi.create(payload)
      const saved = toData(raw) ?? raw ?? payload
      logger.info(isEdit ? 'Product updated' : 'Product created', { productId: form.productId })
      if (onSave) onSave(saved)
      onClose()
    } catch (err) {
      logger.error(isEdit ? 'Failed to update product' : 'Failed to create product', err, { productId: form.productId })
      setError(apiErrorMessage(err))
    } finally { setLoading(false) }
  }

  if (!isOpen) return null
  const inp = 'w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1b2528] text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary transition-colors text-sm'
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
      <div className="bg-white dark:bg-[#111618] rounded-2xl shadow-2xl w-full max-w-lg border border-gray-200 dark:border-gray-700">
        <div className="p-6 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">{isEdit ? 'Edit Product' : 'Add New Product'}</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Define the product used in production jobs.</p>
        </div>
        <div className="p-6 space-y-4">
          {error && <p className="text-sm text-red-500 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg">{error}</p>}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Product ID *</label>
              <input name="productId" value={form.productId} onChange={handle} placeholder="P-001" className={inp} disabled={isEdit} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Unit of Measure</label>
              <select name="unitOfMeasure" value={form.unitOfMeasure} onChange={handle} className={inp}>
                {['pcs','kg','L','m','set'].map(u => <option key={u} className="bg-white dark:bg-[#1b2528]">{u}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Product Name *</label>
            <input name="productName" value={form.productName} onChange={handle} placeholder="e.g. Valve Body Assembly" className={inp} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Product Type</label>
            <RefSelect
              className={inp}
              name="productType"
              value={form.productType}
              onChange={(v) => setForm(p => ({ ...p, productType: v }))}
              fetcher={referenceApi.productTypes.list}
              placeholder="Select product type…"
              allowCustom
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Description</label>
            <textarea name="description" value={form.description} onChange={handle} rows={2} placeholder="Optional notes…" className={`${inp} resize-none`} />
          </div>
        </div>
        <div className="px-6 py-4 bg-gray-50 dark:bg-[#1b2528] border-t border-gray-200 dark:border-gray-700 rounded-b-2xl flex justify-end gap-3">
          <button onClick={onClose} className="px-5 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancel</button>
          <button onClick={submit} disabled={loading} className="px-5 py-2 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors flex items-center gap-2 disabled:opacity-60">
            {loading ? <><span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"/>Saving…</> : isEdit ? 'Update' : 'Create Product'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── BOM / Formula Modal (UC-P01) ─────────────────────────────────────────────
const BomModal = ({ isOpen, onClose, product }) => {
  const [processes, setProcesses] = useState([])
  const [allFormulas, setAllFormulas] = useState([])  // [{id, name}] for name lookup
  const [materials, setMaterials] = useState([])
  const [subProducts, setSubProducts] = useState([])
  const [newProcess, setNewProcess] = useState({ processName: '', steps: [{ stepName: '', machineType: '' }] })
  const [newFormula, setNewFormula] = useState({
    formulaName: '',
    ingredients: [{ type: 'material', materialId: '', productId: '', quantity: '', unit: 'kg' }],
  })
  const [tab, setTab]  = useState('process')
  const [loading, setLoading] = useState(false)
  const [msg, setMsg]  = useState('')
  const [draggedStepIndex, setDraggedStepIndex] = useState(null)
  const [expandedSubProducts, setExpandedSubProducts] = useState(new Set())
  const [subProductChildren, setSubProductChildren] = useState({})
  const [materialsByStepId, setMaterialsByStepId] = useState({})
  const [expandedBomStepMaterials, setExpandedBomStepMaterials] = useState(new Set())
  const [addMaterialForStep, setAddMaterialForStep] = useState(null)
  const [addMaterialForm, setAddMaterialForm] = useState({ type: 'material', materialId: '', productId: '', role: 'input', quantity: '', unit: 'kg' })
  const [materialActionLoading, setMaterialActionLoading] = useState(false)

  // Reference lookup data — always live from DB, no manual state
  const { objects: stepTypes } = useRefObjects(referenceApi.stepTypes.list)

  // Load a formula's ingredients into the edit form
  const applyFormulaIngredients = useCallback((fid, fname) => {
    if (!fid) return
    formulasApi.getIngredients(fid).then(raw => {
      const ings = toList(raw)
      const seen = new Set()
      const deduped = ings.filter(i => {
        const isP = !!(i.product_id || i.ProductID)
        const key = `${isP ? 'p' : 'm'}-${i.material_id || i.MaterialID || i.product_id || i.ProductID}`
        if (seen.has(key)) return false
        seen.add(key); return true
      })
      const mapped = deduped.length > 0 ? deduped.map(i => {
        const isProduct = !!(i.product_id || i.ProductID)
        return {
          type:       isProduct ? 'product' : 'material',
          materialId: i.material_id  || i.MaterialID  || '',
          productId:  i.product_id   || i.ProductID   || '',
          quantity:   String(i.quantity_per_unit ?? i.quantity ?? ''),
          unit:       i.unit || 'kg',
        }
      }) : [{ type: 'material', materialId: '', productId: '', quantity: '', unit: 'kg' }]
      setNewFormula({ formulaName: fname || '', ingredients: mapped })
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!isOpen || !product) return
    const parentId = product.product_id || product.ProductID || product.id
    Promise.all([
      processesApi.getByProduct(parentId).catch(() => null),
      formulasApi.list().catch(() => []),
      productsApi.get(parentId).catch(() => null),  // product details may include formula_id(s)
      inventoryApi.list().catch(() => []),
      productsApi.list().catch(() => []),
    ]).then(([proc, forms, productDetail, mats, prods]) => {
      if (proc) {
        // Guard: backend may return { success: false } with 200 when no process exists
        if (proc.success === false) {
          // No process linked to this product — do not show existing process banner
        } else {
          // Unwrap { success, data: <object> }
          const unwrapped = toData(proc) ?? proc
          const procObj = Array.isArray(unwrapped) ? unwrapped[0] : unwrapped
          // Support both snake_case and PascalCase (backend may return either)
          const realId = procObj?.process_id || procObj?.ProcessID || procObj?.id
          if (procObj && realId) {
            // Fetch steps separately if not embedded
            const applyProcess = (p, steps) => {
              setProcesses([{ ...p, steps }])
              const pName = p.process_name || p.ProcessName || p.name || ''
              const mapped = (steps || []).map(s => ({
                stepName: s.step_name || s.stepName || s.StepName || '',
                machineType: s.machine_type_required || s.machineType || s.MachineTypeRequired || '',
                stepId: s.step_id || s.stepId || s.stepID || s.id || s.process_step_id || s.ProcessStepID || null,
              }))
              setNewProcess({
                processName: pName,
                steps: mapped.length > 0 ? mapped : [{ stepName: '', machineType: '' }],
              })
            }
            if (!Array.isArray(procObj.steps) || procObj.steps.length === 0) {
              processesApi.getSteps(realId).then(stepsRaw => {
                let steps = toList(stepsRaw)
                if (steps.length === 0 && stepsRaw && typeof stepsRaw === 'object') {
                  const nested = stepsRaw?.data?.steps ?? stepsRaw?.steps
                  if (Array.isArray(nested)) steps = nested
                }
                applyProcess(procObj, steps)
              }).catch(() => applyProcess(procObj, []))
            } else {
              applyProcess(procObj, procObj.steps)
            }
          }
        }
      }
      // Build flat formula list for name lookups
      const formulaList = toList(forms).map(f => ({
        id:   f.FormulaID || f.formula_id || f.id || '',
        name: f.FormulaName || f.formula_name || f.name || '',
      })).filter(f => f.id)
      setAllFormulas(formulaList)

      // Backend now returns FormulaID on every product — use it directly
      const prodData = toData(productDetail) ?? productDetail
      const fid = prodData?.FormulaID || prodData?.formula_id || prodData?.formulaId || ''
      if (fid) {
        const fname = formulaList.find(f => f.id === fid)?.name || ''
        applyFormulaIngredients(fid, fname)
      } else {
        setNewFormula({ formulaName: '', ingredients: [{ type: 'material', materialId: '', productId: '', quantity: '', unit: 'kg' }] })
      }

      setMaterials(toList(mats).map(m => ({
        id:   m.material_id || m.MaterialID || m.id || '',
        name: String(m.material_name || m.MaterialName || m.name || m.material_id || m.MaterialID || ''),
      })).filter(m => m.id))
      // Store formulaId alongside id/name so sub-product expansion can use it directly
      setSubProducts(toList(prods).map(p => ({
        id:        p.product_id || p.ProductID || p.id || '',
        name:      String(p.product_name || p.ProductName || p.name || p.product_id || p.ProductID || ''),
        formulaId: p.FormulaID || p.formula_id || p.formulaId || '',
      })).filter(p => p.id && p.id !== parentId))
    })
  }, [isOpen, product])

  useEffect(() => {
    if (!isOpen) {
      setAddMaterialForStep(null)
      setAddMaterialForm({ type: 'material', materialId: '', productId: '', role: 'input', quantity: '', unit: 'kg' })
    }
  }, [isOpen])

  // Load materials per step (GET /process-steps/:step_id/materials) for Process Routing tab
  useEffect(() => {
    const fromRaw = (processes[0]?.steps || []).map(s =>
      s.step_id || s.stepId || s.stepID || s.id || s.process_step_id || s.ProcessStepID
    ).filter(Boolean)
    const fromForm = (newProcess.steps || []).map(s => s.stepId).filter(Boolean)
    const processId = processes[0]?.process_id || processes[0]?.ProcessID
    const derived = processId ? (newProcess.steps || []).map((_, idx) => `${processId}-${idx + 1}`) : []
    const stepIds = [...new Set([...fromRaw, ...fromForm, ...derived])]
    if (stepIds.length === 0) {
      setMaterialsByStepId({})
      return
    }
    setMaterialsByStepId({})
    Promise.allSettled(
      stepIds.map(sid =>
        processesApi.getStepMaterials(sid, 'all').then(r => ({ stepId: sid, data: toList(r) }))
      )
    ).then(results => {
      const byStep = {}
      results.forEach(res => {
        if (res.status === 'fulfilled' && res.value?.data) {
          byStep[res.value.stepId] = res.value.data
        }
      })
      setMaterialsByStepId(byStep)
    })
  }, [processes[0]?.steps, newProcess.steps])

  const refetchStepMaterials = useCallback((stepId) => {
    if (!stepId) return
    processesApi.getStepMaterials(stepId, 'all').then(r => {
      setMaterialsByStepId(prev => ({ ...prev, [stepId]: toList(r) }))
    }).catch(() => {})
  }, [])

  const handleAddStepMaterial = async (stepId) => {
    const f = addMaterialForm
    const materialId = f.type === 'material' ? (f.materialId || '').trim() : ''
    const productId = f.type === 'product' ? (f.productId || '').trim() : ''
    const qty = parseFloat(f.quantity)
    if ((!materialId && !productId) || isNaN(qty) || qty <= 0) {
      setMsg('Select material or product and enter quantity > 0.')
      return
    }
    setMaterialActionLoading(true)
    setMsg('')
    try {
      await processesApi.addStepMaterial(stepId, {
        material_id: materialId || '',
        product_id: productId || '',
        role: f.role || 'input',
        quantity_per_unit: qty,
        unit: f.unit || 'kg',
      })
      setAddMaterialForStep(null)
      setAddMaterialForm({ type: 'material', materialId: '', productId: '', role: 'input', quantity: '', unit: 'kg' })
      refetchStepMaterials(stepId)
    } catch (err) {
      setMsg(apiErrorMessage(err, 'Failed to add material.'))
    } finally {
      setMaterialActionLoading(false)
    }
  }

  const handleRemoveStepMaterial = async (stepId, materialRecordId) => {
    if (!materialRecordId) return
    setMaterialActionLoading(true)
    setMsg('')
    try {
      await processesApi.removeStepMaterial(stepId, materialRecordId)
      refetchStepMaterials(stepId)
    } catch (err) {
      setMsg(apiErrorMessage(err, 'Failed to remove material.'))
    } finally {
      setMaterialActionLoading(false)
    }
  }

  // When step name is selected, auto-fill default machine type from step template
  const handleStepNameChange = (i, stepName) => {
    const template = stepTypes.find(s => s.name === stepName)
    setNewProcess(p => {
      const st = [...p.steps]
      st[i] = {
        ...st[i],
        stepName,
        machineType: template?.default_machine_type || st[i].machineType || '',
      }
      return { ...p, steps: st }
    })
  }

  const addProcessStep = () => setNewProcess(p => ({ ...p, steps: [...p.steps, { stepName: '', machineType: '' }] }))
  const addIngredient  = () => setNewFormula(f => ({
    ...f,
    ingredients: [...f.ingredients, { type: 'material', materialId: '', productId: '', quantity: '', unit: 'kg' }],
  }))

  const fetchSubProductIngredients = (productId) => {
    // undefined = not fetched yet; null = in-flight; [] = done (empty)
    if (subProductChildren[productId] !== undefined) return
    setSubProductChildren(prev => ({ ...prev, [productId]: null }))
    const resolve = (ings) => setSubProductChildren(prev => ({ ...prev, [productId]: ings ?? [] }))

    // Backend returns FormulaID on every product — use it directly from subProducts list
    const subProd = subProducts.find(p => p.id === productId)
    const fid = subProd?.formulaId
    if (fid) {
      formulasApi.getIngredients(fid).then(raw => resolve(toList(raw))).catch(() => resolve([]))
    } else {
      // formulaId missing from cached list (shouldn't happen) — fetch product directly
      productsApi.get(productId).then(raw => {
        const p = toData(raw) ?? raw
        const id = p?.FormulaID || p?.formula_id || p?.formulaId
        if (id) {
          formulasApi.getIngredients(id).then(r => resolve(toList(r))).catch(() => resolve([]))
        } else {
          resolve([])
        }
      }).catch(() => resolve([]))
    }
  }

  const toggleSubProduct = (productId) => {
    setExpandedSubProducts(prev => {
      const next = new Set(prev)
      if (next.has(productId)) next.delete(productId)
      else {
        next.add(productId)
        fetchSubProductIngredients(productId)
      }
      return next
    })
  }

  const saveProcess = async () => {
    if (!newProcess.processName) { setMsg('Process name required.'); return }
    setLoading(true); setMsg('')
    const pid = product.product_id || product.id
    try {
      const proc = await processesApi.create({ process_id: `PRC-${Date.now()}`, product_id: pid, process_name: newProcess.processName })
      const created = toData(proc) ?? proc
      const realId = created?.process_id || created?.ProcessID || proc?.process_id
      const validSteps = newProcess.steps.filter(s => s.stepName)
      const addStepResponses = []
      for (const s of validSteps) {
        const resp = await processesApi.addStep(realId, { step_name: s.stepName, machine_type_required: s.machineType })
        addStepResponses.push(toData(resp) ?? resp ?? {})
      }
      logger.info('Process routing saved', { productId: pid })
      setMsg('Process routing saved ✓')
      processesApi.getSteps(realId).then(stepsRaw => {
        let steps = toList(stepsRaw)
        if (steps.length === 0 && stepsRaw && typeof stepsRaw === 'object') {
          const nested = stepsRaw?.data?.steps ?? stepsRaw?.steps
          if (Array.isArray(nested)) steps = nested
        }
        const pName = newProcess.processName
        const getStep = (s, idx) => {
          const fromAdd = addStepResponses[idx]
          const stepId = s?.step_id || s?.stepId || s?.stepID || s?.id || s?.process_step_id || s?.ProcessStepID ||
            fromAdd?.step_id || fromAdd?.stepId || fromAdd?.id || fromAdd?.ProcessStepID ||
            (realId ? `${realId}-${idx + 1}` : null)
          return {
            stepName: s?.step_name || s?.stepName || s?.StepName || validSteps[idx]?.stepName || '',
            machineType: s?.machine_type_required || s?.machineType || s?.MachineTypeRequired || validSteps[idx]?.machineType || '',
            stepId,
          }
        }
        const stepsToMap = steps?.length > 0 ? steps : validSteps.map(s => ({ step_name: s.stepName, machine_type_required: s.machineType }))
        const mapped = stepsToMap.map((s, idx) => getStep(s, idx))
        setProcesses([{ process_id: realId, process_name: pName, steps: steps?.length > 0 ? steps : mapped }])
        setNewProcess({ processName: pName, steps: mapped.length > 0 ? mapped : [{ stepName: '', machineType: '' }] })
      }).catch(() => {
        const mapped = validSteps.map((s, idx) => ({
          stepName: s.stepName,
          machineType: s.machineType,
          stepId: addStepResponses[idx]?.step_id || addStepResponses[idx]?.stepId || addStepResponses[idx]?.id || (realId ? `${realId}-${idx + 1}` : null),
        }))
        setProcesses([{ process_id: realId, process_name: newProcess.processName, steps: mapped }])
        setNewProcess({ processName: newProcess.processName, steps: mapped })
      })
    } catch (err) {
      logger.error('Failed to save process routing', err, { productId: pid })
      setMsg(`Error: ${apiErrorMessage(err)}`)
    } finally { setLoading(false) }
  }

  const saveFormula = async () => {
    if (!newFormula.formulaName) { setMsg('Formula name required.'); return }
    const validIngredients = newFormula.ingredients.filter(i =>
      (i.type === 'material' && i.materialId) || (i.type === 'product' && i.productId)
    )
    setLoading(true); setMsg('')
    try {
      const fid = `F-${Date.now()}`
      await formulasApi.create({ formula_id: fid, formula_name: newFormula.formulaName })
      for (const ing of validIngredients) {
        const payload = {
          quantity_per_unit: parseFloat(ing.quantity) || 0,
          unit: ing.unit,
        }
        if (ing.type === 'material') {
          payload.material_id = ing.materialId
          payload.component_type = 'material'
        } else {
          payload.product_id = ing.productId
          payload.component_type = 'product'
        }
        await formulasApi.addIngredient(fid, payload)
      }
      await productsApi.linkBom(product.product_id || product.id, { formula_id: fid })
      logger.info('Formula & BOM saved', { productId: product.product_id || product.id, ingredientCount: validIngredients.length })
      setMsg('Formula saved ✓')
      setNewFormula({ formulaName: '', ingredients: [{ type: 'material', materialId: '', productId: '', quantity: '', unit: 'kg' }] })
    } catch (err) {
      logger.error('Failed to save formula', err, { productId: product.product_id || product.id })
      setMsg(`Error: ${apiErrorMessage(err)}`)
    } finally { setLoading(false) }
  }

  if (!isOpen || !product) return null

  const inp = 'px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1b2528] text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-primary transition-colors placeholder-gray-400 dark:placeholder-gray-500'

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
      <div className="bg-white dark:bg-[#111618] rounded-2xl shadow-2xl w-full max-w-3xl max-h-[90vh] overflow-y-auto border border-gray-200 dark:border-gray-700">
        <div className="p-6 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-gray-900 dark:text-white">BOM & Process Routing</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{product.product_name || product.name} · UC-P01</p>
          </div>
          <button onClick={onClose} className="p-2 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-200 dark:border-gray-700 px-6">
          {['process','formula'].map(t => (
            <button key={t} onClick={() => setTab(t)} className={`py-3 px-4 text-sm font-medium border-b-2 transition-colors capitalize ${tab === t ? 'border-primary text-primary' : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}`}>
              {t === 'process' ? '⚙️ Process Routing' : '🧪 Formula / Recipe'}
            </button>
          ))}
        </div>

        <div className="p-6 space-y-5">
          {msg && <p className={`text-sm px-3 py-2 rounded-lg ${msg.startsWith('Error') ? 'text-red-500 bg-red-50 dark:bg-red-900/20' : 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20'}`}>{msg}</p>}

          {tab === 'process' && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Process Name</label>
                <input value={newProcess.processName} onChange={e => setNewProcess(p => ({ ...p, processName: e.target.value }))} placeholder="e.g. Standard CNC Routing" className={`${inp} w-full`} />
              </div>
              <div>
                <p className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-3">Steps — drag to reorder</p>
                <div className="space-y-2">
                  {newProcess.steps.map((s, i) => (
                    <div
                      key={i}
                      draggable
                      onDragStart={() => setDraggedStepIndex(i)}
                      onDragOver={e => { e.preventDefault(); e.currentTarget.classList.add('ring-2', 'ring-primary/50', 'bg-primary/5') }}
                      onDragLeave={e => e.currentTarget.classList.remove('ring-2', 'ring-primary/50', 'bg-primary/5')}
                      onDrop={e => {
                        e.preventDefault()
                        e.currentTarget.classList.remove('ring-2', 'ring-primary/50', 'bg-primary/5')
                        if (draggedStepIndex === null) return
                        const from = draggedStepIndex, to = i
                        if (from === to) { setDraggedStepIndex(null); return }
                        setNewProcess(p => {
                          const st = [...p.steps]
                          const [moved] = st.splice(from, 1)
                          st.splice(to, 0, moved)
                          return { ...p, steps: st }
                        })
                        setDraggedStepIndex(null)
                      }}
                      onDragEnd={() => setDraggedStepIndex(null)}
                      className={`p-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50/50 dark:bg-[#1a2225] transition-all ${draggedStepIndex === i ? 'opacity-60 scale-[0.98]' : 'hover:border-gray-300 dark:hover:border-gray-600'}`}
                    >
                      <div className="flex gap-3 items-center">
                        <span className="flex-shrink-0 cursor-grab active:cursor-grabbing text-gray-400 hover:text-primary" title="Drag to reorder">
                          <span className="material-symbols-outlined text-xl">drag_indicator</span>
                        </span>
                        <span className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/20 text-primary flex items-center justify-center text-xs font-bold">
                          {i + 1}
                        </span>
                        <select
                          value={s.stepName}
                          onChange={e => handleStepNameChange(i, e.target.value)}
                          className={`${inp} flex-1 min-w-0`}
                        >
                          <option value="">{stepTypes.length === 0 ? 'Loading…' : 'Select step type…'}</option>
                          {stepTypes.map(t => (
                            <option key={t.id ?? t.name} value={t.name} className="bg-white dark:bg-[#1b2528]">{t.name}</option>
                          ))}
                        </select>
                        <RefSelect
                          className={`${inp} flex-1 min-w-0`}
                          value={s.machineType}
                          onChange={(v) => setNewProcess(p => { const st=[...p.steps]; st[i]={...st[i],machineType:v}; return {...p,steps:st} })}
                          fetcher={referenceApi.machineTypes.list}
                          placeholder="Machine type…"
                          allowCustom
                        />
                        <button
                          type="button"
                          onClick={() => setNewProcess(p => {
                            const next = p.steps.filter((_, j) => j !== i)
                            return { ...p, steps: next.length > 0 ? next : [{ stepName: '', machineType: '' }] }
                          })}
                          className="flex-shrink-0 p-1.5 rounded-md text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                          title="Remove step"
                        >
                          <span className="material-symbols-outlined text-lg">close</span>
                        </button>
                      </div>
                      {(() => {
                        const processId = processes[0]?.process_id || processes[0]?.ProcessID
                        const rawStep = processes[0]?.steps?.[i]
                        const derivedStepId = processId ? `${processId}-${i + 1}` : null
                        const stepId = s.stepId || rawStep?.step_id || rawStep?.stepId || rawStep?.stepID || rawStep?.id || rawStep?.process_step_id || rawStep?.ProcessStepID || derivedStepId
                        if (!stepId) {
                          return (
                            <div className="mt-2 ml-9 pl-2 border-l-2 border-gray-300/50">
                              <span className="text-xs text-gray-400 dark:text-gray-500">
                                Materials — save process first to view
                              </span>
                            </div>
                          )
                        }
                        const mats = materialsByStepId[stepId] ?? null
                        const items = mats || []
                        const labels = items.map(m => {
                          const qty = m.quantity_per_unit ?? m.quantity ?? 0
                          const u = m.unit || 'ea'
                          const role = (m.role || '').toLowerCase()
                          const suffix = role === 'output' ? ' (output)' : ''
                          return `${m.material_name || m.material_id || m.product_id || '—'} (${qty} ${u})${suffix}`
                        })
                        const key = String(stepId)
                        const expanded = expandedBomStepMaterials.has(key)
                        const count = labels.length
                        return (
                          <div className="mt-2 ml-9 pl-2 border-l-2 border-amber-400/30">
                            <button
                              type="button"
                              onClick={() => setExpandedBomStepMaterials(prev => {
                                const next = new Set(prev)
                                if (next.has(key)) next.delete(key)
                                else next.add(key)
                                return next
                              })}
                              className="text-xs text-amber-600 dark:text-amber-400 hover:underline"
                            >
                              {expanded ? 'Hide materials' : count > 0 ? `Show materials (${count})` : 'Materials (none)'}
                            </button>
                            {expanded && (
                              <div className="mt-0.5 space-y-1.5">
                                {items.map(m => {
                                  const qty = m.quantity_per_unit ?? m.quantity ?? 0
                                  const u = m.unit || 'ea'
                                  const role = (m.role || '').toLowerCase()
                                  const suffix = role === 'output' ? ' (output)' : ''
                                  const label = `${m.material_name || m.material_id || m.product_id || '—'} (${qty} ${u})${suffix}`
                                  return (
                                    <div key={m.id} className="flex items-center justify-between gap-2 group">
                                      <span className="text-xs text-amber-700 dark:text-amber-300">{label}</span>
                                      <button
                                        type="button"
                                        onClick={() => handleRemoveStepMaterial(stepId, m.id)}
                                        disabled={materialActionLoading}
                                        className="p-1 rounded text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 opacity-0 group-hover:opacity-100 transition-opacity disabled:opacity-50"
                                        title="Remove material"
                                      >
                                        <span className="material-symbols-outlined text-sm">close</span>
                                      </button>
                                    </div>
                                  )
                                })}
                                {addMaterialForStep === stepId ? (
                                  <div className="pt-1.5 space-y-1.5 border-t border-amber-400/30">
                                    <div className="flex items-center gap-1.5 flex-wrap">
                                      {[{v:'material',l:'MAT'},{v:'product',l:'SUB'}].map(opt => (
                                        <button key={opt.v} type="button" onClick={() => setAddMaterialForm(f => ({ ...f, type: opt.v, materialId: '', productId: '' }))}
                                          className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${addMaterialForm.type === opt.v ? 'bg-amber-600 text-white' : 'bg-gray-200 dark:bg-gray-700 text-gray-500'}`}>
                                          {opt.l}
                                        </button>
                                      ))}
                                    </div>
                                    <div className="flex items-center gap-2 flex-wrap">
                                      {addMaterialForm.type === 'material' ? (
                                        <select value={addMaterialForm.materialId} onChange={e => setAddMaterialForm(f => ({ ...f, materialId: e.target.value }))} className={`${inp} text-xs py-1.5 flex-1 min-w-0`}>
                                          <option value="">Select material…</option>
                                          {materials.map(m => <option key={m.id} value={m.id} className="bg-white dark:bg-[#1b2528]">{m.name} ({m.id})</option>)}
                                        </select>
                                      ) : (
                                        <select value={addMaterialForm.productId} onChange={e => setAddMaterialForm(f => ({ ...f, productId: e.target.value }))} className={`${inp} text-xs py-1.5 flex-1 min-w-0`}>
                                          <option value="">Select sub-product…</option>
                                          {subProducts.map(p => <option key={p.id} value={p.id} className="bg-white dark:bg-[#1b2528]">{p.name} ({p.id})</option>)}
                                        </select>
                                      )}
                                      <select value={addMaterialForm.role} onChange={e => setAddMaterialForm(f => ({ ...f, role: e.target.value }))} className={`${inp} text-xs py-1.5 w-20`}>
                                        <option value="input">Input</option>
                                        <option value="output">Output</option>
                                      </select>
                                      <input value={addMaterialForm.quantity} type="number" min="0" step="0.01" onChange={e => setAddMaterialForm(f => ({ ...f, quantity: e.target.value }))} placeholder="Qty" className={`${inp} w-16 text-xs py-1.5 text-right tabular-nums`} />
                                      <select value={addMaterialForm.unit} onChange={e => setAddMaterialForm(f => ({ ...f, unit: e.target.value }))} className={`${inp} text-xs py-1.5 w-14`}>
                                        {(addMaterialForm.type === 'product' ? ['pcs','set'] : ['kg','g','pcs','L','ml','m','set']).map(u => <option key={u} className="bg-white dark:bg-[#1b2528]">{u}</option>)}
                                      </select>
                                    </div>
                                    <div className="flex items-center gap-2">
                                      <button type="button" onClick={() => handleAddStepMaterial(stepId)} disabled={materialActionLoading} className="text-xs font-medium text-amber-600 dark:text-amber-400 hover:underline disabled:opacity-60 flex items-center gap-1">
                                        {materialActionLoading ? <span className="w-3 h-3 border border-amber-400 border-t-transparent rounded-full animate-spin"/> : <span className="material-symbols-outlined text-sm">add</span>}
                                        Add
                                      </button>
                                      <button type="button" onClick={() => { setAddMaterialForStep(null); setAddMaterialForm({ type: 'material', materialId: '', productId: '', role: 'input', quantity: '', unit: 'kg' }) }} className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">
                                        Cancel
                                      </button>
                                    </div>
                                  </div>
                                ) : (
                                  <button type="button" onClick={() => setAddMaterialForStep(stepId)} className="text-xs text-amber-600 dark:text-amber-400 hover:underline flex items-center gap-0.5">
                                    <span className="material-symbols-outlined text-sm">add</span> Add material
                                  </button>
                                )}
                              </div>
                            )}
                          </div>
                        )
                      })()}
                    </div>
                  ))}
                </div>
                <button onClick={addProcessStep} className="mt-3 text-sm text-primary font-medium hover:underline flex items-center gap-1">
                  <span className="material-symbols-outlined text-lg">add</span>
                  Add step
                </button>
              </div>
              <button onClick={saveProcess} disabled={loading} className="w-full h-10 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-60 flex items-center justify-center gap-2">
                {loading ? <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/> : null}
                Save Process Routing
              </button>
            </div>
          )}

          {tab === 'formula' && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Formula Name</label>
                <input value={newFormula.formulaName} onChange={e => setNewFormula(f => ({ ...f, formulaName: e.target.value }))} placeholder="e.g. Valve Body Mix" className={`${inp} w-full`} />
              </div>
              <div>
                {/* Quantity context label */}
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-medium text-gray-600 dark:text-gray-400" title="Production recipe. Some items may also appear in the product BOM.">
                    Recipe ingredients
                  </p>
                  <span className="text-xs text-primary bg-primary/10 px-2 py-0.5 rounded-full">
                    Qty = per 1 unit of <strong>{product.product_name || product.name}</strong>
                  </span>
                </div>
                <div className="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
                  {/* Column header */}
                  <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-50 dark:bg-gray-800/60 border-b border-gray-200 dark:border-gray-700 text-xs font-medium text-gray-400 dark:text-gray-500">
                    <span className="w-[70px] flex-shrink-0">Type</span>
                    <span className="flex-1">Component</span>
                    <span className="w-14 text-right">Qty</span>
                    <span className="w-12 text-right">Unit</span>
                    <span className="w-6" />
                  </div>

                  {newFormula.ingredients.map((ing, i) => {
                    const setIng = (patch) => setNewFormula(f => {
                      const ins = [...f.ingredients]; ins[i] = { ...ins[i], ...patch }; return { ...f, ingredients: ins }
                    })
                    const removeSelf = () => setNewFormula(f => {
                      const next = f.ingredients.filter((_, j) => j !== i)
                      return { ...f, ingredients: next.length > 0 ? next : [{ type: 'material', materialId: '', productId: '', quantity: '', unit: 'kg' }] }
                    })
                    const isSubProduct = ing.type === 'product' && !!ing.productId
                    const subName = subProducts.find(p => p.id === ing.productId)?.name || ing.productId
                    const childState = isSubProduct ? subProductChildren[ing.productId] : []
                    const childrenLoading = childState === undefined || childState === null
                    const children = Array.isArray(childState) ? childState : []
                    const expanded = isSubProduct && expandedSubProducts.has(ing.productId)

                    if (isSubProduct) {
                      return (
                        <div key={`sp-${i}`} className="border-b border-gray-100 dark:border-gray-700/50 last:border-0">
                          <div className="flex items-center gap-2 px-3 py-2 group hover:bg-gray-50/50 dark:hover:bg-gray-800/30 transition-colors">
                            <button
                              type="button"
                              onClick={() => toggleSubProduct(ing.productId)}
                              className="w-5 h-5 flex items-center justify-center text-gray-400 hover:text-primary flex-shrink-0 transition-colors"
                            >
                              <span className={`material-symbols-outlined text-base transition-transform duration-150 ${expanded ? 'rotate-90' : ''}`}>chevron_right</span>
                            </button>
                            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 flex-shrink-0 tracking-wide">
                              SUB
                            </span>
                            <span className="flex-1 text-sm font-medium text-gray-800 dark:text-gray-200 truncate">{subName}</span>
                            <span className="text-xs text-gray-400 dark:text-gray-500 flex-shrink-0 tabular-nums">{ing.quantity || '—'}</span>
                            <span className="w-12 text-xs text-gray-400 dark:text-gray-500 text-right flex-shrink-0">{ing.unit}</span>
                            <button
                              type="button"
                              onClick={removeSelf}
                              className="w-6 flex items-center justify-center text-gray-300 dark:text-gray-600 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                              title="Remove"
                            >
                              <span className="material-symbols-outlined text-base">close</span>
                            </button>
                          </div>
                          {expanded && (
                            <div className="border-t border-gray-100 dark:border-gray-700/40 bg-gray-50/60 dark:bg-gray-800/20">
                              {childrenLoading ? (
                                <div className="flex items-center gap-2 pl-10 pr-3 py-2 text-xs text-gray-400">
                                  <span className="material-symbols-outlined text-sm animate-spin">refresh</span> Loading…
                                </div>
                              ) : children.length === 0 ? (
                                <div className="pl-10 pr-3 py-2 text-xs text-gray-400 italic">No formula ingredients found for this sub-product.</div>
                              ) : children.map((c, j) => {
                                const isLast = j === children.length - 1
                                const name = c.material_name || c.MaterialName || c.product_name || c.ProductName || c.material_id || c.product_id || '—'
                                const qty = c.quantity_per_unit ?? c.quantity ?? '—'
                                const u = c.unit || ''
                                return (
                                  <div key={j} className="flex items-center gap-2 pl-10 pr-3 py-1.5 border-b border-gray-100/50 dark:border-gray-700/20 last:border-0">
                                    <span className="text-gray-300 dark:text-gray-600 text-xs font-mono flex-shrink-0">{isLast ? '└─' : '├─'}</span>
                                    <span className="flex-1 text-xs text-gray-600 dark:text-gray-400">{name}</span>
                                    <span className="text-xs text-gray-500 dark:text-gray-400 tabular-nums">{qty}</span>
                                    <span className="w-12 text-xs text-gray-400 text-right">{u}</span>
                                    <span className="w-6" />
                                  </div>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      )
                    }

                    return (
                      <div key={`mat-${i}`} className="flex items-center gap-2 px-3 py-2 border-b border-gray-100 dark:border-gray-700/50 last:border-0 group hover:bg-gray-50/50 dark:hover:bg-gray-800/30 transition-colors">
                        {/* Compact type toggle */}
                        <div className="flex rounded border border-gray-200 dark:border-gray-600 overflow-hidden text-[10px] flex-shrink-0 font-semibold tracking-wide">
                          {[{v:'material',l:'MAT'},{v:'product',l:'SUB'}].map(opt => (
                            <button key={opt.v} type="button" onClick={() => setIng({ type: opt.v, materialId: '', productId: '' })}
                              className={`px-1.5 py-1 transition-colors ${ing.type === opt.v ? 'bg-primary text-white' : 'bg-white dark:bg-[#1b2528] text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700'}`}>
                              {opt.l}
                            </button>
                          ))}
                        </div>
                        {/* Component select */}
                        {ing.type === 'material' ? (
                          <select value={ing.materialId} onChange={e => setIng({ materialId: e.target.value })} className={`${inp} flex-1 text-sm py-1.5`}>
                            <option value="">Select material…</option>
                            {materials.map(m => <option key={m.id} value={m.id} className="bg-white dark:bg-[#1b2528]">{m.name} ({m.id})</option>)}
                          </select>
                        ) : (
                          <select value={ing.productId} onChange={e => setIng({ productId: e.target.value })} className={`${inp} flex-1 text-sm py-1.5`}>
                            <option value="">Select sub-product…</option>
                            {subProducts.map(p => <option key={p.id} value={p.id} className="bg-white dark:bg-[#1b2528]">{p.name} ({p.id})</option>)}
                          </select>
                        )}
                        {/* Qty */}
                        <input value={ing.quantity} type="number" min="0" step="0.01" onChange={e => setIng({ quantity: e.target.value })} placeholder="0" className={`${inp} w-20 text-right py-1.5 tabular-nums`} />
                        {/* Unit */}
                        <select value={ing.unit} onChange={e => setIng({ unit: e.target.value })} className={`${inp} w-16 py-1.5`}>
                          {(ing.type === 'product' ? ['pcs','set'] : ['kg','g','pcs','L','ml','m','set']).map(u => <option key={u} className="bg-white dark:bg-[#1b2528]">{u}</option>)}
                        </select>
                        {/* Remove */}
                        <button type="button" onClick={removeSelf}
                          className="w-6 flex items-center justify-center text-gray-300 dark:text-gray-600 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" title="Remove">
                          <span className="material-symbols-outlined text-base">close</span>
                        </button>
                      </div>
                    )
                  })}

                  {/* Add row */}
                  <div className="px-3 py-2 bg-gray-50/50 dark:bg-gray-800/20 border-t border-gray-200 dark:border-gray-700">
                    <button onClick={addIngredient} className="flex items-center gap-1 text-xs text-primary font-medium hover:underline">
                      <span className="material-symbols-outlined text-sm">add</span> Add ingredient
                    </button>
                  </div>
                </div>
              </div>
              <button onClick={saveFormula} disabled={loading} className="w-full h-10 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-60 flex items-center justify-center gap-2">
                {loading ? <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/> : null}
                Save Formula
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────
const Products = () => {
  const toast = useToast()
  const [products, setProducts]         = useState([])
  const [loading, setLoading]           = useState(true)
  const [fetchError, setFetchError]     = useState('')
  const [search, setSearch]             = useState('')
  const [modalOpen, setModalOpen]       = useState(false)
  const [bomModalOpen, setBomModalOpen] = useState(false)
  const [editTarget, setEditTarget]     = useState(null)
  const [bomTarget, setBomTarget]       = useState(null)
  const [actionMenu, setActionMenu]     = useState(null)

  const fetchProducts = useCallback(async () => {
    setLoading(true); setFetchError('')
    try {
      const raw = await productsApi.list()
      debugResponse('Products', raw)
      const normalized = toList(raw).map(normalizeProduct)
      setProducts(normalized)
      logger.info('Products loaded', { count: normalized.length })
    } catch (err) {
      logger.error('Failed to load products', err, { page: 'Products' })
      setFetchError(apiErrorMessage(err, 'Unable to reach server.'))
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchProducts() }, [fetchProducts])

  const filtered = products.filter(p => {
    const q = search.toLowerCase()
    return !q || (p.product_name||'').toLowerCase().includes(q) || String(p.product_id||'').toLowerCase().includes(q)
  })

  const openEdit = (p) => { setEditTarget(p); setModalOpen(true); setActionMenu(null) }
  const openBom  = (p) => { setBomTarget(p); setBomModalOpen(true); setActionMenu(null) }

  return (
    <div className="flex-1 p-8 overflow-y-auto" onClick={() => setActionMenu(null)}>
      <PageHeader title="Products & BOM" subtitle="Manage products, process routing, and bill of materials.">
        <button
          onClick={() => { setEditTarget(null); setModalOpen(true) }}
          className="flex items-center gap-2 h-10 px-4 bg-primary text-white text-sm font-bold rounded-lg hover:bg-primary/90 transition-colors"
        >
          <span className="material-symbols-outlined text-lg">add</span>
          Add Product
        </button>
      </PageHeader>

      {fetchError && (
        <div className="mb-4 flex items-center gap-2 px-4 py-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-xl text-sm text-amber-700 dark:text-amber-400">
          <span className="material-symbols-outlined text-base">warning</span>{fetchError}
        </div>
      )}

      {/* Search */}
      <div className="mb-6 relative max-w-sm">
        <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 dark:text-gray-400">search</span>
        <input
          value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search by name or ID…"
          className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-sm text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary transition-colors"
        />
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-[#111618]">
        <table className="w-full">
          <thead className="bg-gray-50 dark:bg-[#1b2427]">
            <tr>
              {['Product ID','Name','Category','Unit','BOM / Routing','Actions'].map(h => (
                <th key={h} className="px-6 py-3 text-left text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wider">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} className="px-6 py-12 text-center text-gray-500 dark:text-gray-400">
                <div className="flex items-center justify-center gap-3">
                  <span className="w-5 h-5 border-2 border-gray-300 border-t-primary rounded-full animate-spin"/>Loading products…
                </div>
              </td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={6} className="px-6 py-12 text-center text-gray-500 dark:text-gray-400">No products found.</td></tr>
            ) : filtered.map(p => {
              // Already normalized — fields are guaranteed to exist
              const id       = p.product_id
              const name     = p.product_name
              const category = p.product_type
              const unit     = p.unit_of_measure
              return (
                <tr key={id} className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors">
                  <td className="px-6 py-4 text-sm text-gray-500 dark:text-gray-400 font-mono">{id}</td>
                  <td className="px-6 py-4 text-sm font-semibold text-gray-900 dark:text-white">{name}</td>
                  <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-400">{category}</td>
                  <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-400">{unit}</td>
                  <td className="px-6 py-4">
                    <button
                      onClick={(e) => { e.stopPropagation(); openBom(p) }}
                      className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:text-primary/80 px-2.5 py-1.5 rounded-lg hover:bg-primary/10 transition-colors"
                    >
                      <span className="material-symbols-outlined text-base">schema</span>
                      Manage BOM
                    </button>
                  </td>
                  <td className="px-6 py-4 relative">
                    <button
                      onClick={(e) => { e.stopPropagation(); setActionMenu(actionMenu === id ? null : id) }}
                      className="p-2 rounded-lg text-gray-500 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                    >
                      <span className="material-symbols-outlined text-lg">more_vert</span>
                    </button>
                    {actionMenu === id && (
                      <div className="absolute right-4 top-12 z-20 bg-white dark:bg-[#1b2528] border border-gray-200 dark:border-gray-700 rounded-xl shadow-xl w-40 py-1" onClick={e => e.stopPropagation()}>
                        <MItem icon="edit" label="Edit" onClick={() => openEdit(p)} />
                        <MItem icon="schema" label="BOM & Routing" onClick={() => openBom(p)} />
                      </div>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <ProductModal isOpen={modalOpen} onClose={() => setModalOpen(false)} onSave={fetchProducts} product={editTarget} />
      <BomModal isOpen={bomModalOpen} onClose={() => setBomModalOpen(false)} product={bomTarget} />
    </div>
  )
}

const MItem = ({ icon, label, onClick }) => (
  <button onClick={onClick} className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
    <span className="material-symbols-outlined text-base">{icon}</span>{label}
  </button>
)

export default Products
