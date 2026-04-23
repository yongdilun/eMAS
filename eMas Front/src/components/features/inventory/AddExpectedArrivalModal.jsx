import { useState, useEffect } from 'react'
import { inventoryApi } from '../../../services/api'

const EMPTY = { materialId: '', quantity: '', expectedArriveAt: '', notes: '' }

const AddExpectedArrivalModal = ({ isOpen, onClose, onSave, materials }) => {
  const [form, setForm] = useState(EMPTY)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!isOpen) { setForm(EMPTY); setError('') }
  }, [isOpen])

  const handleChange = (e) => {
    const { name, value } = e.target
    setForm(prev => ({ ...prev, [name]: value }))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    const qty = parseFloat(form.quantity)
    if (!form.materialId) { setError('Material is required.'); return }
    if (!qty || qty <= 0) { setError('Quantity must be greater than 0.'); return }
    if (!form.expectedArriveAt) { setError('Expected arrival date/time is required.'); return }

    setLoading(true); setError('')
    try {
      const payload = {
        material_id:         form.materialId,
        quantity:            qty,
        expected_arrive_at:  new Date(form.expectedArriveAt).toISOString(), // RFC3339
        notes:               form.notes || undefined,
      }
      await inventoryApi.expectedArrivals.create(payload)
      if (onSave) onSave()
      setForm(EMPTY)
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to create expected arrival.')
    } finally {
      setLoading(false)
    }
  }

  if (!isOpen) return null

  const inp = 'w-full px-4 py-2.5 rounded-lg bg-white dark:bg-[#1b2528] border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-primary transition-colors placeholder-gray-400 dark:placeholder-gray-500'

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
      <div className="bg-white dark:bg-[#111618] rounded-2xl shadow-2xl w-full max-w-md border border-gray-200 dark:border-gray-700">
        <div className="p-6 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">Schedule Expected Arrival</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">Add inventory expected to arrive on a future date.</p>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="flex items-center gap-2 px-3 py-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-600 dark:text-red-400">
              <span className="material-symbols-outlined text-base">error</span>{error}
            </div>
          )}
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Material *</label>
            <select
              name="materialId"
              value={form.materialId}
              onChange={handleChange}
              className={`${inp} bg-white dark:bg-[#1b2528]`}
              required
            >
              <option value="">Select material…</option>
              {(materials || []).map(m => (
                <option key={m.material_id || m.id} value={m.material_id || m.id} className="bg-white dark:bg-[#1b2528]">
                  {m.material_name || m.name} ({m.material_id || m.id})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Quantity *</label>
            <input
              name="quantity"
              type="number"
              min="0.01"
              step="0.01"
              value={form.quantity}
              onChange={handleChange}
              placeholder="0"
              className={inp}
              required
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Expected arrival date & time * (RFC3339)</label>
            <input
              name="expectedArriveAt"
              type="datetime-local"
              value={form.expectedArriveAt}
              onChange={handleChange}
              className={inp}
              required
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Notes</label>
            <textarea
              name="notes"
              value={form.notes}
              onChange={handleChange}
              rows={2}
              placeholder="Optional notes…"
              className={`${inp} resize-none`}
            />
          </div>
          <div className="flex gap-3 justify-end pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
              Cancel
            </button>
            <button type="submit" disabled={loading} className="px-4 py-2 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors flex items-center gap-2 disabled:opacity-60">
              {loading ? <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"/> : null}
              Schedule
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default AddExpectedArrivalModal
