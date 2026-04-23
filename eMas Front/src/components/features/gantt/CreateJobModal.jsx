import { useState, useEffect } from 'react'
import { jobsApi, productsApi, machinesApi, toList, toData, apiErrorMessage } from '../../../services/api'
import { normalizeProduct, normalizeMachine } from '../../../services/normalizers'
import logger from '../../../services/logger'

const EMPTY_FORM = {
  productId: '',
  productName: '',
  machine: '',
  startDate: '',
  startTime: '',
  duration: '',
  priority: 'medium',
  quantity: '',
  deadline: '',
  notes: '',
}

const CreateJobModal = ({ isOpen, onClose, onSave }) => {
  const [formData, setFormData] = useState(EMPTY_FORM)
  const [errors, setErrors] = useState({})
  const [products, setProducts] = useState([])
  const [machines, setMachines] = useState([])
  const [loading, setLoading] = useState(false)
  const [submitError, setSubmitError] = useState('')

  useEffect(() => {
    if (!isOpen) return
    Promise.all([productsApi.list(), machinesApi.list()])
      .then(([prods, machs]) => {
        setProducts(toList(prods).map(normalizeProduct))
        setMachines(toList(machs).map(normalizeMachine))
      })
      .catch((err) => {
        logger.warn('CreateJobModal: could not load products/machines dropdowns', { message: err?.message })
      })
  }, [isOpen])

  const handleChange = (e) => {
    const { name, value } = e.target
    setFormData((prev) => ({ ...prev, [name]: value }))
    if (errors[name]) setErrors((prev) => ({ ...prev, [name]: '' }))
  }

  const validate = () => {
    const e = {}
    if (!formData.productId)   e.productId   = 'Product ID is required'
    if (!formData.productName) e.productName = 'Product name is required'
    if (!formData.machine)     e.machine     = 'Machine is required'
    if (!formData.startDate)   e.startDate   = 'Start date is required'
    if (!formData.startTime)   e.startTime   = 'Start time is required'
    if (!formData.duration)    e.duration    = 'Duration is required'
    if (!formData.quantity)    e.quantity    = 'Quantity is required'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const handleSubmit = async () => {
    if (!validate()) return
    setLoading(true)
    setSubmitError('')

    const startIso = new Date(`${formData.startDate}T${formData.startTime}`).toISOString()
    const durationMins = Math.round(parseFloat(formData.duration) * 60)

    const payload = {
      product_id:     formData.productId,
      quantity_total: parseInt(formData.quantity, 10),
      priority:       formData.priority,
      deadline:       formData.deadline ? new Date(formData.deadline).toISOString() : undefined,
      notes:          formData.notes || undefined,
      slots: [
        {
          machine_id:    formData.machine,
          start_time:    startIso,
          duration_mins: durationMins,
          quantity:      parseInt(formData.quantity, 10),
        },
      ],
    }

    try {
      const raw = await jobsApi.create(payload)
      const created = toData(raw) ?? raw   // unwrap { success, data: JobResponse }
      logger.info('Job created', { jobId: created?.job_id, productId: formData.productId })
      if (onSave) onSave(created)
      setFormData(EMPTY_FORM)
      setErrors({})
      onClose()
    } catch (err) {
      logger.error('Failed to create job', err, { productId: formData.productId })
      setSubmitError(apiErrorMessage(err, 'Failed to create job. Please try again.'))
    } finally {
      setLoading(false)
    }
  }

  const handleCancel = () => {
    setFormData(EMPTY_FORM)
    setErrors({})
    setSubmitError('')
    onClose()
  }

  if (!isOpen) return null

  const fieldCls = (key) =>
    `w-full px-4 py-2.5 rounded-lg border ${
      errors[key]
        ? 'border-red-500 focus:ring-red-500'
        : 'border-gray-300 dark:border-gray-600 focus:ring-primary'
    } bg-white dark:bg-[#1b2528] text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 transition-colors`

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
      <div className="bg-white dark:bg-[#111618] rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto border border-gray-200 dark:border-gray-700">
        {/* Header */}
        <div className="sticky top-0 bg-white dark:bg-[#111618] border-b border-gray-200 dark:border-gray-700 px-6 py-4 z-10">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Create New Job</h2>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">Schedule a new production job</p>
        </div>

        {/* Form */}
        <div className="px-6 py-6 space-y-6">
          {submitError && (
            <div className="flex items-start gap-3 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
              <span className="material-symbols-outlined text-red-500 text-lg mt-0.5">error</span>
              <p className="text-sm text-red-700 dark:text-red-400">{submitError}</p>
            </div>
          )}

          {/* Product — single select that fills both productId and productName */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Product *
            </label>
            {products.length > 0 ? (
              <>
                <select
                  value={formData.productId}
                  onChange={e => {
                    const selected = products.find(p => p.product_id === e.target.value)
                    setFormData(prev => ({
                      ...prev,
                      productId:   selected?.product_id   || e.target.value,
                      productName: selected?.product_name || '',
                    }))
                    if (errors.productId) setErrors(prev => ({ ...prev, productId: '' }))
                  }}
                  className={fieldCls('productId')}
                >
                  <option value="">Select product…</option>
                  {products.map((p) => (
                    <option key={p.product_id} value={p.product_id}>
                      {p.product_name} ({p.product_id})
                    </option>
                  ))}
                </select>
                {formData.productId && (
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    ID: <span className="font-mono">{formData.productId}</span>
                  </p>
                )}
              </>
            ) : (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <input
                    type="text" name="productId" value={formData.productId}
                    onChange={handleChange} placeholder="Product ID e.g. P-001"
                    className={fieldCls('productId')}
                  />
                </div>
                <div>
                  <input
                    type="text" name="productName" value={formData.productName}
                    onChange={handleChange} placeholder="Product name"
                    className={fieldCls('productName')}
                  />
                </div>
              </div>
            )}
            {errors.productId && <p className="mt-1 text-sm text-red-500">{errors.productId}</p>}
            {errors.productName && <p className="mt-1 text-sm text-red-500">{errors.productName}</p>}
          </div>

          {/* Machine */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Assigned Machine *
            </label>
            {machines.length > 0 ? (
              <select
                name="machine" value={formData.machine}
                onChange={handleChange}
                className={fieldCls('machine')}
              >
                <option value="">Select machine…</option>
                {machines.map((m) => (
                  <option key={m.machine_id} value={m.machine_id}>
                    {m.machine_name}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text" name="machine" value={formData.machine}
                onChange={handleChange} placeholder="e.g. CNC Mill 01"
                className={fieldCls('machine')}
              />
            )}
            {errors.machine && <p className="mt-1 text-sm text-red-500">{errors.machine}</p>}
          </div>

          {/* Date & Time */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Start Date *
              </label>
              <input
                type="date" name="startDate" value={formData.startDate}
                onChange={handleChange} className={fieldCls('startDate')}
              />
              {errors.startDate && <p className="mt-1 text-sm text-red-500">{errors.startDate}</p>}
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Start Time *
              </label>
              <input
                type="time" name="startTime" value={formData.startTime}
                onChange={handleChange} className={fieldCls('startTime')}
              />
              {errors.startTime && <p className="mt-1 text-sm text-red-500">{errors.startTime}</p>}
            </div>
          </div>

          {/* Duration & Quantity */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Duration (hours) *
              </label>
              <input
                type="number" name="duration" value={formData.duration}
                onChange={handleChange} placeholder="2.5" step="0.5" min="0.5"
                className={fieldCls('duration')}
              />
              {errors.duration && <p className="mt-1 text-sm text-red-500">{errors.duration}</p>}
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Quantity (units) *
              </label>
              <input
                type="number" name="quantity" value={formData.quantity}
                onChange={handleChange} placeholder="500" min="1"
                className={fieldCls('quantity')}
              />
              {errors.quantity && <p className="mt-1 text-sm text-red-500">{errors.quantity}</p>}
            </div>
          </div>

          {/* Priority & Deadline */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Priority Level
              </label>
              <select
                name="priority" value={formData.priority} onChange={handleChange}
                className="w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1b2528] text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary transition-colors"
              >
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Deadline
              </label>
              <input
                type="date" name="deadline" value={formData.deadline}
                onChange={handleChange}
                className="w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1b2528] text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary transition-colors"
              />
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Notes (Optional)
            </label>
            <textarea
              name="notes" value={formData.notes} onChange={handleChange}
              placeholder="Additional information or special instructions…"
              rows="3"
              className="w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1b2528] text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary transition-colors resize-none"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="sticky bottom-0 bg-gray-50 dark:bg-[#1b2528] border-t border-gray-200 dark:border-gray-700 px-6 py-4 flex justify-end gap-3">
          <button
            onClick={handleCancel} disabled={loading}
            className="px-6 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 font-medium hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit} disabled={loading}
            className="px-6 py-2.5 rounded-lg bg-primary text-white font-medium hover:bg-primary/90 transition-colors flex items-center gap-2 disabled:opacity-60"
          >
            {loading ? (
              <>
                <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Creating…
              </>
            ) : (
              <>
                <span className="material-symbols-outlined text-lg">add_circle</span>
                Create Job
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

export default CreateJobModal
