import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import UtilizationChart from '../components/features/machines/UtilizationChart'
import AddMachineModal from '../components/features/machines/AddMachineModal'
import RecordDowntimeModal from '../components/features/machines/RecordDowntimeModal'
import PageHeader from '../components/shared/PageHeader'
import { machinesApi, reportsApi, jobsApi, schedulingApi, toList, toData, apiErrorMessage } from '../services/api'
import { normalizeMachine, normalizeMaintenanceAlert, debugResponse } from '../services/normalizers'
import logger from '../services/logger'
import { useToast } from '../context/ToastContext'

const STATUS_COLORS = {
  Running:     { dot: 'bg-green-400',  text: 'text-green-500'  },
  Idle:        { dot: 'bg-amber-400',  text: 'text-amber-500'  },
  Maintenance: { dot: 'bg-red-400',    text: 'text-red-500'    },
}

const MachineResources = () => {
  const toast = useToast()
  const [machines, setMachines]           = useState([])
  const [alerts, setAlerts]               = useState([])
  const [utilizationData, setUtilData]    = useState(null)
  const [typeFilter, setTypeFilter]       = useState('')
  const [statusFilter, setStatusFilter]   = useState('')
  const [isModalOpen, setIsModalOpen]     = useState(false)
  const [loading, setLoading]             = useState(true)
  const [fetchError, setFetchError]       = useState('')
  const [actionTarget, setActionTarget]   = useState(null)
  const [actionMenuOpen, setActionMenuOpen] = useState(null)
  const [downtimeModalOpen, setDowntimeModalOpen] = useState(false)
  const [downtimeMachine, setDowntimeMachine] = useState(null)
  const [rerouteForMachine, setRerouteForMachine] = useState(null)
  const [rerouteRecs, setRerouteRecs] = useState([])

  const MOCK_UTILIZATION = {
    data: [
      { machine_name: 'Assembly Station 01', utilization_pct: 72 },
      { machine_name: 'CNC Mill 01',       utilization_pct: 85 },
      { machine_name: 'CNC Mill 02',       utilization_pct: 68 },
      { machine_name: 'Coating Station 01', utilization_pct: 42 },
      { machine_name: 'Lathe 01',          utilization_pct: 60 },
      { machine_name: 'Lathe 02',          utilization_pct: 92 },
      { machine_name: 'Hydraulic Press 01', utilization_pct: 70 },
      { machine_name: 'Quality Control Station', utilization_pct: 55 },
    ],
    avg_pct: 68,
  }

  const fetchMachines = useCallback(async () => {
    setLoading(true)
    setFetchError('')
    try {
      const params = {}
      if (typeFilter)   params.type   = typeFilter
      if (statusFilter) params.status = statusFilter
      const raw = await machinesApi.list(params)
      debugResponse('Machines', raw)
      const normalized = toList(raw).map(normalizeMachine)
      setMachines(normalized)
      logger.info('Machines loaded', { count: normalized.length })
    } catch (err) {
      logger.error('Failed to load machines', err, { page: 'MachineResources' })
      setFetchError(apiErrorMessage(err, 'Unable to reach server. Showing last known data.'))
    } finally {
      setLoading(false)
    }
  }, [typeFilter, statusFilter])

  useEffect(() => { fetchMachines() }, [fetchMachines])

  useEffect(() => {
    machinesApi.maintenanceAlerts({ days_ahead: 7 })
      .then((data) => setAlerts(toList(data).map(normalizeMaintenanceAlert)))
      .catch((err) => logger.warn('Maintenance alerts unavailable', { message: err?.message }))
  }, [])

  useEffect(() => {
    const fetchUtilization = async () => {
      try {
        const data = await reportsApi.machineUtilization()
        const arr = Array.isArray(data) ? data : toList(toData(data) ?? data)
        const hasRealData = arr?.some((r) => (r.total_minutes ?? 0) > 0 || (r.utilization_pct ?? r.utilization ?? r.pct ?? 0) > 0)
        if (hasRealData && arr?.length > 0) {
          setUtilData(data)
          return
        }
      } catch (err) {
        logger.warn('Machine utilization API unavailable', { message: err?.message })
      }
      try {
        const jobsRaw = await jobsApi.list({})
        const jobs = toList(toData(jobsRaw) ?? jobsRaw)
        const jobIds = jobs.map((j) => j.job_id ?? j.jobId ?? j.id).filter(Boolean)
        const RANGE_DAYS = 7
        const RANGE_HOURS_PER_DAY = 8
        const rangeMins = RANGE_DAYS * RANGE_HOURS_PER_DAY * 60
        const byMachine = {}
        await Promise.all(
          jobIds.slice(0, 50).map(async (id) => {
            const slotsRaw = await jobsApi.getSlots(id)
            const slots = toList(toData(slotsRaw) ?? slotsRaw)
            slots.forEach((s) => {
              const mid = s.machine_id ?? s.machineId ?? s.MachineID
              if (!mid) return
              const start = s.scheduled_start ? new Date(s.scheduled_start).getTime() : null
              const end = s.scheduled_end ? new Date(s.scheduled_end).getTime() : null
              if (start != null && end != null && end > start) {
                const mins = Math.round((end - start) / 60000)
                if (!byMachine[mid]) byMachine[mid] = { machine_id: mid, total_minutes: 0 }
                byMachine[mid].total_minutes += mins
              }
            })
          })
        )
        const vals = Object.values(byMachine)
        if (vals.length > 0) {
          const computed = {
            data: vals.map((m) => ({
              machine_id: m.machine_id,
              total_minutes: m.total_minutes,
              utilization: Math.min(m.total_minutes / rangeMins, 1),
            })),
            avg_pct: Math.round(
              vals.reduce((s, m) => s + Math.min((m.total_minutes / rangeMins) * 100, 100), 0) / vals.length
            ),
          }
          setUtilData(computed)
        } else {
          setUtilData(MOCK_UTILIZATION)
        }
      } catch (err) {
        logger.warn('Could not compute utilization from slots', { message: err?.message })
        setUtilData(MOCK_UTILIZATION)
      }
    }
    fetchUtilization()
  }, [])

  const handleSaveMachine = async (formData) => {
    fetchMachines()
  }

  const handleEditMachine = (machine) => {
    setActionTarget(machine)
    setIsModalOpen(true)
    setActionMenuOpen(null)
  }

  const handleDeleteMachine = async (machine) => {
    const mid = machine.machine_id
    if (!window.confirm(`Decommission machine ${mid}?`)) return
    try {
      await machinesApi.update(mid, { status: 'Maintenance' })  // mark offline
      logger.info('Machine decommissioned', { machineId: mid })
      toast.success(`Machine ${mid} decommissioned.`)
      fetchMachines()
    } catch (err) {
      logger.error('Failed to decommission machine', err, { machineId: mid })
      toast.error(apiErrorMessage(err, 'Failed to decommission machine.'))
    }
    setActionMenuOpen(null)
  }

  const handleOpenRecordDowntime = (machine) => {
    setDowntimeMachine(machine)
    setDowntimeModalOpen(true)
    setActionMenuOpen(null)
  }

  const handleRerouteRecommendations = (machine) => {
    const mid = machine.machine_id
    setRerouteForMachine(machine)
    setRerouteRecs([])
    machinesApi.rerouteRecommendations(mid)
      .then((r) => setRerouteRecs(Array.isArray(r) ? r : (r?.data ? toList(r.data) : toList(r))))
      .catch(() => setRerouteRecs([]))
    setActionMenuOpen(null)
  }

  // Already normalized — machine_type is always a plain string
  const machineTypes = [...new Set(machines.map((m) => String(m.machine_type || '')).filter(Boolean))]

  return (
    <div className="flex-1 p-8 overflow-y-auto" onClick={() => setActionMenuOpen(null)}>
      <PageHeader title="Machine & Resources" subtitle="Monitor and manage all manufacturing equipment." />

      {/* Maintenance alerts banner */}
      {alerts.length > 0 && (
        <div className="mb-4 flex items-start gap-3 px-4 py-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-xl text-sm text-amber-700 dark:text-amber-400">
          <span className="material-symbols-outlined text-lg mt-0.5">build_circle</span>
          <div>
            <span className="font-semibold">Upcoming Maintenance:</span>{' '}
            {alerts.map((a) => {
              const label = a.machine_name || a.machine_id || '?'
              let days
              if (a.days_until != null) {
                const d = Number(a.days_until)
                if (d < 0)      days = 'Overdue'
                else if (d === 0) days = 'Today'
                else              days = `${d}d`
              } else if (a.due_date) {
                days = new Date(a.due_date).toLocaleDateString([], { month: 'short', day: 'numeric' })
              }
              return days ? `${label} (${days})` : label
            }).join(' · ')}
          </div>
        </div>
      )}

      {fetchError && (
        <div className="mb-4 flex items-center gap-2 px-4 py-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-xl text-sm text-red-600 dark:text-red-400">
          <span className="material-symbols-outlined text-base">error</span>
          {fetchError}
        </div>
      )}

      {/* Toolbar */}
      <div className="flex flex-wrap justify-between items-center gap-4 mb-6 px-4 py-3 bg-gray-100 dark:bg-[#111618] rounded-xl border border-gray-300 dark:border-[#3b4e54]">
        <div className="flex flex-wrap items-center gap-4">
          {/* Type filter */}
          <div className="relative min-w-[200px]">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-gray-600 dark:text-[#9cb3ba]">
              filter_list
            </span>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="w-full h-10 pl-10 pr-4 bg-white dark:bg-[#283539] text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-[#3b4e54] focus:ring-primary focus:border-primary"
            >
              <option value="">Filter by Type</option>
              {machineTypes.length > 0
                ? machineTypes.map((t) => <option key={t}>{t}</option>)
                : ['CNC Mill', 'Lathe', '3D Printer', 'Welding Robot', 'Stamping Press'].map((t) => (
                    <option key={t}>{t}</option>
                  ))}
            </select>
          </div>

          {/* Status filter */}
          <div className="relative min-w-[200px]">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-gray-600 dark:text-[#9cb3ba]">
              bolt
            </span>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-full h-10 pl-10 pr-4 bg-white dark:bg-[#283539] text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-[#3b4e54] focus:ring-primary focus:border-primary"
            >
              <option value="">Filter by Status</option>
              <option>Running</option>
              <option>Idle</option>
              <option>Maintenance</option>
            </select>
          </div>
        </div>

        <button
          onClick={() => { setActionTarget(null); setIsModalOpen(true) }}
          className="flex items-center justify-center gap-2 h-10 px-5 bg-primary text-white rounded-lg text-sm font-bold hover:bg-primary/80 transition-colors"
        >
          <span className="material-symbols-outlined text-xl" style={{ fontVariationSettings: "'FILL' 1" }}>
            add
          </span>
          Add New Machine
        </button>
      </div>

      {/* Utilization chart */}
      <UtilizationChart machines={machines} utilizationData={utilizationData} />

      {/* Table */}
      <div className="overflow-x-auto @container">
        <div className="overflow-hidden rounded-xl border border-gray-300 dark:border-[#3b4e54] bg-white dark:bg-[#111618]">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-100 dark:bg-[#1b2427]">
                {['Machine ID', 'Name', 'Status', 'Type', 'Capacity', 'Last Maintenance', 'Actions'].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-gray-900 dark:text-white text-sm font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-gray-500 dark:text-gray-400">
                    <div className="flex items-center justify-center gap-3">
                      <span className="w-5 h-5 border-2 border-gray-300 border-t-primary rounded-full animate-spin" />
                      Loading machines…
                    </div>
                  </td>
                </tr>
              ) : machines.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-gray-500 dark:text-gray-400">
                    No machines found.
                  </td>
                </tr>
              ) : (
                machines.map((machine) => {
                  // All fields already normalized by normalizeMachine()
                  const id       = machine.machine_id
                  const name     = machine.machine_name
                  const type     = machine.machine_type
                  const status   = machine.status
                  const cap      = machine.capacity_per_hour
                  const capacity = cap != null ? `${cap} u/hr` : '—'
                  const rawDate   = machine.last_maintenance_date
                  const lastMaint = rawDate && rawDate !== '—'
                    ? (() => { try { return new Date(rawDate).toLocaleDateString() } catch { return rawDate } })()
                    : '—'
                  const sc = STATUS_COLORS[status] || STATUS_COLORS.Idle

                  return (
                    <tr key={id} className="border-t border-t-gray-200 dark:border-t-[#3b4e54]">
                      <td className="h-16 px-4 py-2 text-gray-900 dark:text-white text-sm font-medium">{id}</td>
                      <td className="h-16 px-4 py-2 text-gray-700 dark:text-gray-300 text-sm">{name}</td>
                      <td className="h-16 px-4 py-2 text-sm">
                        <div className={`flex items-center gap-2 font-medium ${sc.text}`}>
                          <span className={`h-2 w-2 rounded-full ${sc.dot}`} />
                          {status}
                        </div>
                      </td>
                      <td className="h-16 px-4 py-2 text-gray-600 dark:text-[#9cb3ba] text-sm">{type}</td>
                      <td className="h-16 px-4 py-2 text-gray-600 dark:text-[#9cb3ba] text-sm">{capacity}</td>
                      <td className="h-16 px-4 py-2 text-gray-600 dark:text-[#9cb3ba] text-sm">{lastMaint}</td>
                      <td className="h-16 px-4 py-2 text-gray-600 dark:text-[#9cb3ba] relative">
                        <button
                          onClick={(e) => { e.stopPropagation(); setActionMenuOpen(actionMenuOpen === id ? null : id) }}
                          className="p-2 hover:text-gray-900 dark:hover:text-white transition-colors rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
                        >
                          <span className="material-symbols-outlined">more_vert</span>
                        </button>

                        {actionMenuOpen === id && (
                          <div
                            className="absolute right-4 top-12 z-20 bg-white dark:bg-[#1b2528] border border-gray-200 dark:border-gray-700 rounded-xl shadow-xl w-48 py-1"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <MenuItem icon="edit" label="Edit Machine" onClick={() => handleEditMachine(machine)} />
                            <MenuItem icon="build" label="Record Downtime" onClick={() => handleOpenRecordDowntime(machine)} />
                            {(status === 'Maintenance' || status === 'maintenance') && (
                              <MenuItem icon="route" label="Reroute suggestions" onClick={() => handleRerouteRecommendations(machine)} />
                            )}
                            <MenuItem icon="delete" label="Decommission" danger onClick={() => handleDeleteMachine(machine)} />
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <AddMachineModal
        isOpen={isModalOpen}
        machine={actionTarget}
        onClose={() => { setIsModalOpen(false); setActionTarget(null) }}
        onSave={handleSaveMachine}
      />
      <RecordDowntimeModal
        isOpen={downtimeModalOpen}
        onClose={() => { setDowntimeModalOpen(false); setDowntimeMachine(null) }}
        machine={downtimeMachine}
        onSuccess={() => { toast.success('Downtime recorded successfully.'); fetchMachines() }}
      />
      {rerouteForMachine && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50" onClick={() => setRerouteForMachine(null)}>
          <div className="bg-white dark:bg-[#111618] rounded-2xl shadow-2xl w-full max-w-md border border-gray-200 dark:border-gray-700 p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between mb-4">
              <h2 className="text-xl font-bold text-gray-900 dark:text-white">Reroute suggestions</h2>
              <button onClick={() => setRerouteForMachine(null)} className="p-2 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800">
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
              {rerouteForMachine.machine_name || rerouteForMachine.machine_id} is in maintenance. Suggested alternatives:
            </p>
            {rerouteRecs.length > 0 ? (
              <ul className="space-y-2 text-sm">
                {rerouteRecs.slice(0, 5).map((rec, i) => (
                  <li key={i} className="p-2 rounded-lg bg-gray-50 dark:bg-gray-800/50">
                    {rec.machine_id || rec.machine_name || rec.job_id || JSON.stringify(rec)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-gray-500 dark:text-gray-400">No recommendations. Go to Scheduling to reschedule.</p>
            )}
            <Link
              to="/scheduling"
              className="mt-4 inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary/90"
            >
              <span className="material-symbols-outlined text-lg">calendar_today</span>
              Go to Scheduling
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}

const MenuItem = ({ icon, label, onClick, danger }) => (
  <button
    onClick={onClick}
    className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-colors hover:bg-gray-50 dark:hover:bg-gray-800 ${
      danger ? 'text-red-500' : 'text-gray-700 dark:text-gray-300'
    }`}
  >
    <span className="material-symbols-outlined text-base">{icon}</span>
    {label}
  </button>
)

export default MachineResources
