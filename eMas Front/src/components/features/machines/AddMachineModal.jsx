import { useState, useEffect } from 'react'
import { machinesApi, referenceApi } from '../../../services/api'
import logger from '../../../services/logger'
import RefSelect from '../../shared/RefSelect'
import { useRefObjects } from '../../../hooks/useRefData'

const EMPTY_FORM = {
  machineId: '',
  machineName: '',
  type: '',
  status: 'Idle',
  maxCapacity: '',
  maintenanceInterval: '',
  maintenanceDate: '',
  location: '',
}

const AddMachineModal = ({ isOpen, onClose, onSave, machine }) => {
  const isEdit = !!machine
  const [formData, setFormData] = useState(EMPTY_FORM)
  const [capabilities, setCapabilities] = useState([])
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')
  const { objects: stepTypes } = useRefObjects(referenceApi.stepTypes.list)

  useEffect(() => {
    if (!isOpen) return
    if (machine) {
      setFormData({
        machineId:           machine.machine_id || machine.id || '',
        machineName:         machine.machine_name || machine.name || '',
        type:                machine.machine_type || machine.type || '',
        status:              machine.status || 'Idle',
        maxCapacity:         machine.capacity_per_hour ?? machine.max_capacity ?? '',
        maintenanceInterval: machine.maintenance_interval_days ?? machine.maintenance_interval ?? '',
        maintenanceDate:     machine.last_maintenance_date || machine.last_maintenance || '',
        location:            machine.location || '',
      })
    } else {
      setFormData(EMPTY_FORM)
    }
    setError('')
  }, [isOpen, machine])

  const handleChange = (e) => {
    const { name, value } = e.target
    setFormData((prev) => ({ ...prev, [name]: value }))
  }

  const handleSubmit = async () => {
    if (!formData.machineId || !formData.machineName || !formData.type) {
      setError('Machine ID, Name, and Type are required.')
      return
    }
    setLoading(true)
    setError('')

    const payload = {
      machine_id:                formData.machineId,
      machine_name:              formData.machineName,
      machine_type:              formData.type,           // API: machine_type
      status:                    formData.status,
      capacity_per_hour:         formData.maxCapacity ? parseInt(formData.maxCapacity, 10) : undefined,  // API: capacity_per_hour
      maintenance_interval_days: formData.maintenanceInterval ? parseInt(formData.maintenanceInterval, 10) : undefined,  // API: maintenance_interval_days
      last_maintenance_date:     formData.maintenanceDate || undefined,  // API: last_maintenance_date
      location:                  formData.location || undefined,
    }

    try {
      const machineId = formData.machineId
      if (isEdit) {
        await machinesApi.update(machineId, payload)
      } else {
        await machinesApi.create(payload)
      }
      for (const cap of capabilities) {
        if (cap.step_id) {
          try {
            await machinesApi.addCapability(machineId, {
              step_id: cap.step_id,
              efficiency_factor: cap.efficiency_factor != null && cap.efficiency_factor !== '' ? Number(cap.efficiency_factor) : undefined,
            })
          } catch (capErr) {
            logger.warn('Could not add capability', { step_id: cap.step_id, message: capErr?.message })
          }
        }
      }
      if (onSave) onSave(payload)
      setFormData(EMPTY_FORM)
      setCapabilities([])
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to save. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleCancel = () => {
    setFormData(EMPTY_FORM)
    setError('')
    onClose()
  }

  if (!isOpen) return null

  const inputCls = 'w-full bg-white dark:bg-[#283539] text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-[#3b4e54] focus:ring-primary focus:border-primary px-3 py-2 focus:outline-none focus:ring-2 transition-colors'

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
      <div className="bg-white dark:bg-[#111618] rounded-xl border border-gray-300 dark:border-[#3b4e54] w-full max-w-lg shadow-2xl max-h-[90vh] overflow-y-auto">
        <div className="p-6 border-b border-gray-300 dark:border-[#3b4e54]">
          <h2 className="text-gray-900 dark:text-white text-xl font-bold">
            {isEdit ? 'Edit Machine' : 'Add a New Machine'}
          </h2>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
            {isEdit ? 'Update machine details.' : 'Register a new machine with capabilities.'}
          </p>
        </div>

        <form className="p-6 grid grid-cols-1 sm:grid-cols-2 gap-4" onSubmit={(e) => e.preventDefault()}>
          {error && (
            <div className="sm:col-span-2 flex items-center gap-2 px-3 py-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-600 dark:text-red-400">
              <span className="material-symbols-outlined text-base">error</span>
              {error}
            </div>
          )}

          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-gray-700 dark:text-[#9cb3ba] mb-1">
              Machine ID *
            </label>
            <input
              className={inputCls} name="machineId" value={formData.machineId}
              onChange={handleChange} placeholder="e.g., MCH-006" type="text"
              disabled={isEdit}
            />
          </div>

          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-gray-700 dark:text-[#9cb3ba] mb-1">
              Machine Name *
            </label>
            <input
              className={inputCls} name="machineName" value={formData.machineName}
              onChange={handleChange} placeholder="e.g., Haas VF-2" type="text"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-[#9cb3ba] mb-1">
              Type *
            </label>
            <RefSelect
              className={inputCls}
              name="type"
              value={formData.type}
              onChange={(v) => setFormData(p => ({ ...p, type: v }))}
              fetcher={referenceApi.machineTypes.list}
              placeholder="Select machine type…"
              allowCustom
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-[#9cb3ba] mb-1">
              Status
            </label>
            <select className={inputCls} name="status" value={formData.status} onChange={handleChange}>
              <option className="bg-white dark:bg-[#283539]">Running</option>
              <option className="bg-white dark:bg-[#283539]">Idle</option>
              <option className="bg-white dark:bg-[#283539]">Maintenance</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-[#9cb3ba] mb-1">
              Max Capacity (units/day)
            </label>
            <input
              className={inputCls} name="maxCapacity" value={formData.maxCapacity}
              onChange={handleChange} placeholder="e.g., 500" type="number"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-[#9cb3ba] mb-1">
              Maintenance Interval (days)
            </label>
            <input
              className={inputCls} name="maintenanceInterval" value={formData.maintenanceInterval}
              onChange={handleChange} placeholder="e.g., 90" type="number"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-[#9cb3ba] mb-1">
              Last Maintenance Date
            </label>
            <input
              className={inputCls} name="maintenanceDate" value={formData.maintenanceDate}
              onChange={handleChange} type="date"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-[#9cb3ba] mb-1">
              Location
            </label>
            <RefSelect
              className={inputCls}
              name="location"
              value={formData.location}
              onChange={(v) => setFormData(p => ({ ...p, location: v }))}
              fetcher={referenceApi.locations.list}
              toLabel={(item) => (typeof item === 'string' ? item : (item.display || item.name || ''))}
              placeholder="Select location…"
              allowCustom
            />
          </div>

          <div className="sm:col-span-2 border-t border-gray-200 dark:border-gray-700 pt-4 mt-2">
            <div className="flex items-center justify-between mb-2">
              <label className="block text-sm font-medium text-gray-700 dark:text-[#9cb3ba]">
                Capabilities (step types this machine can perform)
              </label>
              <button
                type="button"
                onClick={() => setCapabilities((prev) => [...prev, { step_id: '', efficiency_factor: 1 }])}
                className="text-sm text-primary font-medium hover:underline flex items-center gap-1"
              >
                <span className="material-symbols-outlined text-base">add</span>
                Add capability
              </button>
            </div>
            {capabilities.length === 0 ? (
              <p className="text-sm text-gray-500 dark:text-gray-400">No capabilities added. Click “Add capability” to assign step types.</p>
            ) : (
              <ul className="space-y-2">
                {capabilities.map((cap, idx) => (
                  <li key={idx} className="flex items-center gap-2">
                    <select
                      className={`${inputCls} flex-1`}
                      value={cap.step_id}
                      onChange={(e) => setCapabilities((prev) => prev.map((c, i) => i === idx ? { ...c, step_id: e.target.value } : c))}
                    >
                      <option value="">Select step type…</option>
                      {stepTypes.map((st) => (
                        <option key={st.id ?? st.name} value={String(st.id ?? st.name)} className="bg-white dark:bg-[#283539]">
                          {st.name || st.display || st.id}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      min="0.1"
                      max="2"
                      step="0.1"
                      placeholder="1.0"
                      className={`${inputCls} w-20`}
                      value={cap.efficiency_factor ?? ''}
                      onChange={(e) => setCapabilities((prev) => prev.map((c, i) => i === idx ? { ...c, efficiency_factor: e.target.value === '' ? '' : Number(e.target.value) } : c))}
                    />
                    <button
                      type="button"
                      onClick={() => setCapabilities((prev) => prev.filter((_, i) => i !== idx))}
                      className="p-2 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg"
                      aria-label="Remove capability"
                    >
                      <span className="material-symbols-outlined text-lg">close</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </form>

        <div className="p-6 bg-gray-50 dark:bg-gray-900 border-t border-gray-300 dark:border-[#3b4e54] flex justify-end gap-4 rounded-b-xl">
          <button
            onClick={handleCancel}
            className="h-10 px-5 bg-gray-200 dark:bg-[#283539] text-gray-900 dark:text-white rounded-lg text-sm font-bold hover:bg-gray-300 dark:hover:bg-[#3b4e54] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit} disabled={loading}
            className="h-10 px-5 bg-primary text-white rounded-lg text-sm font-bold hover:bg-primary/80 transition-colors flex items-center gap-2 disabled:opacity-60"
          >
            {loading ? (
              <>
                <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Saving…
              </>
            ) : isEdit ? 'Update Machine' : 'Save Machine'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default AddMachineModal
