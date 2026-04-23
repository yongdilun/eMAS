import { useState, useEffect } from 'react'
import { machinesApi } from '../../../services/api'
import { useToast } from '../../../context/ToastContext'

const RecordDowntimeModal = ({ isOpen, onClose, machine, onSuccess }) => {
  const toast = useToast()
  const [cause, setCause] = useState('')
  const [downUntil, setDownUntil] = useState('')
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState('')

  const getDefaultDownUntil = () => {
    const d = new Date()
    d.setHours(d.getHours() + 2)
    return d.toISOString().slice(0, 16)
  }

  useEffect(() => {
    if (isOpen) {
      setCause('')
      setDownUntil(getDefaultDownUntil())
      setMsg('')
    }
  }, [isOpen])

  const handleSubmit = async (e) => {
    e.preventDefault()
    const mid = machine?.machine_id
    if (!mid) { setMsg('No machine selected.'); return }
    if (!cause?.trim()) { setMsg('Cause is required.'); return }
    const startTime = new Date()
    const downUntilDate = downUntil ? new Date(downUntil) : new Date(startTime.getTime() + 2 * 60 * 60 * 1000)
    const downUntilIso = downUntilDate.toISOString()
    setLoading(true)
    setMsg('')
    try {
      await machinesApi.recordDowntime({
        machine_id: mid,
        cause: cause.trim(),
        start_time: startTime.toISOString(),
        end_time: downUntilIso,
      })
      setMsg('Downtime recorded successfully.')
      onSuccess?.()
      toast.info('Schedule may be outdated. Go to Scheduling to reschedule if needed.', { duration: 6000 })
      setTimeout(() => { onClose() }, 1200)
    } catch (err) {
      setMsg(err?.message || 'Failed to record downtime.')
    } finally {
      setLoading(false)
    }
  }

  if (!isOpen) return null

  const inp = 'w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1b2528] text-gray-900 dark:text-white text-sm'

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50" onClick={onClose}>
      <div className="bg-white dark:bg-[#111618] rounded-2xl shadow-2xl w-full max-w-md border border-gray-200 dark:border-gray-700" onClick={(e) => e.stopPropagation()}>
        <div className="p-6 border-b border-gray-200 dark:border-gray-700 flex items-start justify-between">
          <div>
            <h2 className="text-xl font-bold text-gray-900 dark:text-white">Record Downtime</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
              {machine?.machine_name || machine?.machine_id || 'Machine'}
            </p>
          </div>
          <button onClick={onClose} className="p-2 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800">
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {msg && (
            <p className={`text-sm px-3 py-2 rounded-lg ${msg.includes('Failed') ? 'text-red-600 bg-red-50 dark:bg-red-900/20' : 'text-green-600 bg-green-50 dark:bg-green-900/20'}`}>
              {msg}
            </p>
          )}
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Cause *</label>
            <input
              type="text"
              value={cause}
              onChange={(e) => setCause(e.target.value)}
              placeholder="e.g. Breakdown, Maintenance"
              className={inp}
              required
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Down until (optional)</label>
            <input
              type="datetime-local"
              value={downUntil}
              onChange={(e) => setDownUntil(e.target.value)}
              min={new Date().toISOString().slice(0, 16)}
              className={inp}
            />
            <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">Defaults to 2 hours from now if left empty</p>
          </div>
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose} className="flex-1 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800">
              Cancel
            </button>
            <button type="submit" disabled={loading || !cause?.trim()} className="flex-1 py-2 rounded-lg bg-primary text-white hover:bg-primary/90 disabled:opacity-50">
              {loading ? 'Recording…' : 'Record Downtime'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default RecordDowntimeModal
