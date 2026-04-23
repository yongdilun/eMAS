import { useState, useEffect } from 'react'
import { productionApi, stepsApi } from '../../../services/api'

const TABS = ['production', 'inspection']

const LogProductionModal = ({ isOpen, onClose, job, slots = [], onSlotsUpdated }) => {
  const [tab, setTab]     = useState('production')
  const [slotId, setSlotId] = useState('')
  const [prodForm, setProdForm] = useState({ qty_produced: '', qty_scrap: '', downtime_mins: '', notes: '' })
  const [inspecForm, setInspecForm] = useState({ result: 'pass', defect_count: '', notes: '' })
  const [loading, setLoading] = useState(false)
  const [msg, setMsg]     = useState('')

  useEffect(() => {
    if (!isOpen) return
    setTab('production')
    setSlotId(slots[0]?.slot_id || '')
    setProdForm({ qty_produced: '', qty_scrap: '', downtime_mins: '', notes: '' })
    setInspecForm({ result: 'pass', defect_count: '', notes: '' })
    setMsg('')
  }, [isOpen, slots])

  const handleProd = (e) => setProdForm(p => ({ ...p, [e.target.name]: e.target.value }))
  const handleInsp = (e) => setInspecForm(p => ({ ...p, [e.target.name]: e.target.value }))

  const submitProduction = async () => {
    if (!slotId)             { setMsg('Select a slot first.'); return }
    if (!prodForm.qty_produced) { setMsg('Quantity produced is required.'); return }
    setLoading(true); setMsg('')
    const now = new Date().toISOString()
    try {
      // API: POST /production-logs — fields: slot_id, quantity_produced, quantity_scrap, operator_notes, downtime_minutes
      await productionApi.log({
        slot_id:            slotId,
        quantity_produced:  parseFloat(prodForm.qty_produced),
        quantity_scrap:     parseFloat(prodForm.qty_scrap) || 0,
        operator_notes:     prodForm.notes || undefined,
        start_time:         now,
        ...(prodForm.downtime_mins ? { downtime_minutes: parseInt(prodForm.downtime_mins, 10) } : {}),
      })
      try {
        await stepsApi.updateSlot(slotId, {
          actual_end: now,
          status: 'completed',
        })
      } catch (slotErr) {
        if (slotErr?.status !== 404) throw slotErr
      }
      setMsg('Production logged ✓')
      onSlotsUpdated?.()
      setTimeout(onClose, 1000)
    } catch (err) { setMsg(`Error: ${err.message}`) }
    finally { setLoading(false) }
  }

  const submitInspection = async () => {
    setLoading(true); setMsg('')
    // API: POST /quality/inspections — fields: job_step_id, inspector_name, result, defect_count, notes
    // We use the first slot's job_step_id if available
    const firstSlot = slots.find(s => s.slot_id === slotId) || slots[0]
    const jobStepId = firstSlot?.job_step_id || job?.job_id || job?.id
    try {
      await productionApi.inspect({
        job_step_id:  jobStepId,
        result:       inspecForm.result,
        defect_count: parseInt(inspecForm.defect_count) || 0,
        notes:        inspecForm.notes || undefined,
      })
      setMsg('Inspection recorded ✓')
      setTimeout(onClose, 1000)
    } catch (err) { setMsg(`Error: ${err.message}`) }
    finally { setLoading(false) }
  }

  if (!isOpen) return null

  const inp = 'w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1b2528] text-gray-900 dark:text-white text-sm placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary transition-colors'

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
      <div className="bg-white dark:bg-[#111618] rounded-2xl shadow-2xl w-full max-w-lg border border-gray-200 dark:border-gray-700">
        <div className="p-6 border-b border-gray-200 dark:border-gray-700 flex items-start justify-between">
          <div>
            <h2 className="text-xl font-bold text-gray-900 dark:text-white">Log Production</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
              Job #{job?.id} · UC-PL01 / PL02
            </p>
          </div>
          <button onClick={onClose} className="p-2 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-200 dark:border-gray-700 px-6">
          {TABS.map(t => (
            <button key={t} onClick={() => { setTab(t); setMsg('') }}
              className={`py-3 px-4 text-sm font-medium border-b-2 transition-colors ${tab === t ? 'border-primary text-primary' : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}`}>
              {t === 'production' ? '📦 Production Log' : '🔍 Quality Inspection'}
            </button>
          ))}
        </div>

        <div className="p-6 space-y-4">
          {msg && (
            <p className={`text-sm px-3 py-2 rounded-lg ${msg.startsWith('Error') ? 'text-red-500 bg-red-50 dark:bg-red-900/20' : 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20'}`}>{msg}</p>
          )}

          {/* Slot selector */}
          {slots.length > 0 && (
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Slot</label>
              <select value={slotId} onChange={e => setSlotId(e.target.value)} className={inp}>
                {slots.map(sl => (
                  <option key={sl.slot_id} value={sl.slot_id} className="bg-white dark:bg-[#1b2528]">
                    {sl.slot_id} · {sl.machine_id} · {sl.quantity} units
                  </option>
                ))}
              </select>
            </div>
          )}

          {tab === 'production' ? (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Qty Produced *</label>
                  <input name="qty_produced" type="number" min="0" value={prodForm.qty_produced} onChange={handleProd} placeholder="0" className={inp} />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Qty Scrap</label>
                  <input name="qty_scrap" type="number" min="0" value={prodForm.qty_scrap} onChange={handleProd} placeholder="0" className={inp} />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Downtime (mins)</label>
                <input name="downtime_mins" type="number" min="0" value={prodForm.downtime_mins} onChange={handleProd} placeholder="0" className={inp} />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Notes</label>
                <textarea name="notes" value={prodForm.notes} onChange={handleProd} rows={2} placeholder="Optional…" className={`${inp} resize-none`} />
              </div>
              <button onClick={submitProduction} disabled={loading} className="w-full h-10 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-60 flex items-center justify-center gap-2">
                {loading ? <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/> : null}
                Submit Production Log
              </button>
            </>
          ) : (
            <>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Result</label>
                <div className="flex gap-3">
                  {['pass','fail','conditional'].map(r => (
                    <label key={r} className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg border-2 cursor-pointer text-sm font-medium transition-colors capitalize ${inspecForm.result === r ? (r==='pass'?'border-green-500 bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400':r==='fail'?'border-red-500 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400':'border-yellow-500 bg-yellow-50 dark:bg-yellow-900/20 text-yellow-600 dark:text-yellow-400') : 'border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-400'}`}>
                      <input type="radio" name="result" value={r} checked={inspecForm.result === r} onChange={handleInsp} className="sr-only" />
                      {r === 'pass' ? '✓' : r === 'fail' ? '✗' : '~'} {r}
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Defect Count</label>
                <input name="defect_count" type="number" min="0" value={inspecForm.defect_count} onChange={handleInsp} placeholder="0" className={inp} />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Notes</label>
                <textarea name="notes" value={inspecForm.notes} onChange={handleInsp} rows={2} placeholder="Describe findings…" className={`${inp} resize-none`} />
              </div>
              <button onClick={submitInspection} disabled={loading} className="w-full h-10 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-60 flex items-center justify-center gap-2">
                {loading ? <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/> : null}
                Submit Inspection
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export default LogProductionModal
