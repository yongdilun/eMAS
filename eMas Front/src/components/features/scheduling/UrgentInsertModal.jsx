import { useState } from 'react'
import { schedulingApi } from '../../../services/api'
import { useToast } from '../../../context/ToastContext'

const UrgentInsertModal = ({ isOpen, onClose, job, onSuccess }) => {
  const toast = useToast()
  const [reason, setReason] = useState('')
  const [priority, setPriority] = useState('high')
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    const jobId = job?.job_id || job?.jobId || job?.id
    if (!jobId) { setMsg('No job selected.'); return }
    setLoading(true)
    setMsg('')
    try {
      await schedulingApi.emitEvent({
        type: 'urgent_insert',
        payload: JSON.stringify({ job_id: jobId, priority, reason: reason || 'Urgent insert' }),
      })
      setMsg('Urgent insert emitted.')
      onSuccess?.()
      toast.info('Schedule may be outdated. Go to Scheduling to reschedule if needed.', { duration: 6000 })
      setTimeout(() => { setReason(''); setPriority('high'); onClose() }, 1500)
    } catch (err) {
      if (err?.status === 404) setMsg('Event API not available.')
      else setMsg(err?.message || 'Failed to emit urgent insert.')
    } finally {
      setLoading(false)
    }
  }

  if (!isOpen) return null

  const inp = 'w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1b2528] text-gray-900 dark:text-white text-sm'

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
      <div className="bg-white dark:bg-[#111618] rounded-2xl shadow-2xl w-full max-w-md border border-gray-200 dark:border-gray-700">
        <div className="p-6 border-b border-gray-200 dark:border-gray-700 flex items-start justify-between">
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">Urgent Insert</h2>
          <button onClick={onClose} className="p-2 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800">
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {msg && (
            <p className={`text-sm px-3 py-2 rounded-lg ${msg.startsWith('Failed') || msg.startsWith('Event') ? 'text-amber-600 bg-amber-50 dark:bg-amber-900/20' : 'text-green-600 bg-green-50 dark:bg-green-900/20'}`}>
              {msg}
            </p>
          )}
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Reason</label>
            <input
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Rush order"
              className={inp}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Priority</label>
            <select value={priority} onChange={(e) => setPriority(e.target.value)} className={inp}>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </div>
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose} className="flex-1 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800">
              Cancel
            </button>
            <button type="submit" disabled={loading} className="flex-1 py-2 rounded-lg bg-primary text-white hover:bg-primary/90 disabled:opacity-50">
              {loading ? 'Emitting…' : 'Urgent Insert'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default UrgentInsertModal
