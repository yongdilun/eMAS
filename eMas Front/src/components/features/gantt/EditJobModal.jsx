import { useState, useEffect } from 'react'
import { jobsApi, apiErrorMessage } from '../../../services/api'

const EditJobModal = ({ isOpen, onClose, job, onSave }) => {
  const [priority, setPriority] = useState('medium')
  const [deadline, setDeadline] = useState('')
  const [notes, setNotes] = useState('')
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    if (isOpen && job) {
      setPriority(job.priority || 'medium')
      setDeadline(job.deadline ? new Date(job.deadline).toISOString().slice(0, 16) : '')
      setNotes(job.notes || '')
      setMsg('')
    }
  }, [isOpen, job])

  const handleSubmit = async (e) => {
    e.preventDefault()
    const jobId = job?.job_id || job?.jobId || job?.id
    if (!jobId) { setMsg('No job selected.'); return }
    setLoading(true)
    setMsg('')
    try {
      await jobsApi.update(jobId, {
        priority: priority || undefined,
        deadline: deadline ? new Date(deadline).toISOString() : undefined,
        notes: notes || undefined,
      })
      onSave?.()
      onClose()
    } catch (err) {
      setMsg(apiErrorMessage(err, 'Failed to update job.'))
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
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">Edit Job</h2>
          <button onClick={onClose} className="p-2 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800">
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {msg && (
            <p className="text-sm px-3 py-2 rounded-lg text-red-600 bg-red-50 dark:bg-red-900/20">{msg}</p>
          )}
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Priority</label>
            <select value={priority} onChange={(e) => setPriority(e.target.value)} className={inp}>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Deadline</label>
            <input
              type="datetime-local"
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
              className={inp}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Notes</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              className={`${inp} resize-none`}
            />
          </div>
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose} className="flex-1 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800">
              Cancel
            </button>
            <button type="submit" disabled={loading} className="flex-1 py-2 rounded-lg bg-primary text-white hover:bg-primary/90 disabled:opacity-50">
              {loading ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default EditJobModal
