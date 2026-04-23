import { useState, useEffect, useCallback } from 'react'
import AddItemModal from '../components/features/inventory/AddItemModal'
import AddExpectedArrivalModal from '../components/features/inventory/AddExpectedArrivalModal'
import PageHeader from '../components/shared/PageHeader'
import { inventoryApi, toList, apiErrorMessage } from '../services/api'
import { normalizeMaterial, debugResponse } from '../services/normalizers'
import logger from '../services/logger'
import { useToast } from '../context/ToastContext'

const STATUS_LABELS = { 'in_stock': 'In Stock', 'low_stock': 'Low Stock', 'out_of_stock': 'Out of Stock' }

const getStatus = (item) => {
  if (item.status) return STATUS_LABELS[item.status] || item.status
  const current = parseFloat(item.current_stock ?? 0)
  const min     = parseFloat(item.min_stock ?? 0)
  if (current <= 0) return 'Out of Stock'
  if (current < min) return 'Low Stock'
  return 'In Stock'
}

const statusBadge = (label) => {
  const cfg = {
    'In Stock':     { bg: 'bg-green-500/20', text: 'text-green-500',  dot: 'bg-green-400' },
    'Low Stock':    { bg: 'bg-yellow-500/20',text: 'text-yellow-500', dot: 'bg-yellow-400' },
    'Out of Stock': { bg: 'bg-red-500/20',   text: 'text-red-500',    dot: 'bg-red-400' },
  }
  const c = cfg[label] || cfg['In Stock']
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${c.bg} ${c.text}`}>
      <span className={`w-2 h-2 ${c.dot} rounded-full`}/>
      {label}
    </span>
  )
}

// ─── Consume / Receive Modal ──────────────────────────────────────────────────
const ConsumeModal = ({ isOpen, onClose, item, mode }) => {
  const [qty, setQty]       = useState('')
  const [jobId, setJobId]   = useState('')
  const [loading, setLoading] = useState(false)
  const [msg, setMsg]       = useState('')

  useEffect(() => { if (isOpen) { setQty(''); setJobId(''); setMsg('') } }, [isOpen])

  if (!isOpen) return null

  const submit = async () => {
    const q = parseFloat(qty)
    if (!q || q <= 0) { setMsg('Enter a valid quantity.'); return }
    setLoading(true); setMsg('')
    try {
      const mid = item.material_id
      if (mode === 'consume') {
        await inventoryApi.consume({ material_id: mid, quantity: q, reference_job_id: jobId || undefined })
      } else {
        await inventoryApi.receive({ material_id: mid, quantity: q })
      }
      setMsg(mode === 'consume' ? `Consumed ${q} ${item.unit || ''} ✓` : `Received ${q} ${item.unit || ''} ✓`)
      setTimeout(onClose, 900)
    } catch (err) {
      logger.error(`Inventory ${mode} failed`, err, { itemId: item.material_id })
      setMsg(`Error: ${err.message || 'Request failed'}`)
    } finally { setLoading(false) }
  }

  const isConsume = mode === 'consume'
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
      <div className="bg-white dark:bg-[#111618] rounded-2xl shadow-2xl w-full max-w-sm border border-gray-200 dark:border-gray-700">
        <div className="p-5 border-b border-gray-200 dark:border-gray-700">
          <h3 className="text-lg font-bold text-gray-900 dark:text-white">
            {isConsume ? 'Consume Material' : 'Receive Stock'} · UC-S01
          </h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{item.material_name}</p>
        </div>
        <div className="p-5 space-y-4">
          {msg && <p className={`text-sm px-3 py-2 rounded-lg ${msg.startsWith('Error') ? 'text-red-500 bg-red-50 dark:bg-red-900/20' : 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20'}`}>{msg}</p>}
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Quantity ({item.unit || 'units'})</label>
            <input type="number" min="0.01" step="0.01" value={qty} onChange={e => setQty(e.target.value)} placeholder="0" className="w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1b2528] text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-primary transition-colors" />
          </div>
          {isConsume && (
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Job ID (optional)</label>
              <input type="text" value={jobId} onChange={e => setJobId(e.target.value)} placeholder="e.g. P-2404" className="w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1b2528] text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-primary transition-colors" />
            </div>
          )}
        </div>
        <div className="p-5 pt-0 flex gap-3 justify-end">
          <button onClick={onClose} className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancel</button>
          <button onClick={submit} disabled={loading} className={`px-4 py-2 rounded-lg text-white text-sm font-medium flex items-center gap-2 transition-colors disabled:opacity-60 ${isConsume ? 'bg-amber-500 hover:bg-amber-600' : 'bg-green-600 hover:bg-green-700'}`}>
            {loading ? <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"/> : null}
            {isConsume ? 'Consume' : 'Receive'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────
const StorageInventory = () => {
  const toast = useToast()
  const [tab, setTab]               = useState('materials')
  const [items, setItems]           = useState([])
  const [loading, setLoading]       = useState(true)
  const [fetchError, setFetchError] = useState('')
  const [search, setSearch]         = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [sortBy, setSortBy]         = useState('material_name')
  const [sortDir, setSortDir]       = useState('asc')
  const [isAddOpen, setIsAddOpen]   = useState(false)
  const [editTarget, setEditTarget] = useState(null)
  const [actionMenu, setActionMenu] = useState(null)
  const [consumeTarget, setConsumeTarget] = useState(null)
  const [consumeMode, setConsumeMode]     = useState('consume')

  // Expected arrivals
  const [arrivals, setArrivals]           = useState([])
  const [arrivalsLoading, setArrivalsLoading] = useState(false)
  const [arrivalsError, setArrivalsError] = useState('')
  const [arrivalMaterialFilter, setArrivalMaterialFilter] = useState('')
  const [arrivalStatusFilter, setArrivalStatusFilter] = useState('pending')
  const [arrivalFrom, setArrivalFrom]     = useState('')
  const [arrivalTo, setArrivalTo]         = useState('')
  const [isAddArrivalOpen, setIsAddArrivalOpen] = useState(false)

  const fetchItems = useCallback(async () => {
    setLoading(true); setFetchError('')
    try {
      const params = {}
      if (statusFilter) params.status = statusFilter
      if (search)       params.q      = search
      params.sort_by  = sortBy
      params.sort_dir = sortDir
      const raw = await inventoryApi.list(params)
      debugResponse('Inventory', raw)
      const normalized = toList(raw).map(normalizeMaterial)
      setItems(normalized)
      logger.info('Inventory loaded', { count: normalized.length })
    } catch (err) {
      logger.error('Failed to load inventory', err, { page: 'StorageInventory' })
      setFetchError(apiErrorMessage(err, 'Unable to reach server. Showing cached data.'))
    } finally { setLoading(false) }
  }, [statusFilter, search, sortBy, sortDir])

  useEffect(() => { fetchItems() }, [fetchItems])

  const fetchArrivals = useCallback(async () => {
    setArrivalsLoading(true); setArrivalsError('')
    try {
      const params = {}
      if (arrivalMaterialFilter) params.material_id = arrivalMaterialFilter
      if (arrivalStatusFilter)  params.status = arrivalStatusFilter
      if (arrivalFrom)          params.from = new Date(arrivalFrom).toISOString()
      if (arrivalTo)            params.to = new Date(arrivalTo).toISOString()
      const raw = await inventoryApi.expectedArrivals.list(params)
      setArrivals(toList(raw))
    } catch (err) {
      setArrivalsError(apiErrorMessage(err, 'Unable to load expected arrivals.'))
    } finally { setArrivalsLoading(false) }
  }, [arrivalMaterialFilter, arrivalStatusFilter, arrivalFrom, arrivalTo])

  useEffect(() => {
    if (tab === 'expected') fetchArrivals()
  }, [tab, fetchArrivals])

  const openConsume = (item, mode) => { setConsumeTarget(item); setConsumeMode(mode); setActionMenu(null) }
  const openEdit    = (item) => { setEditTarget(item); setIsAddOpen(true); setActionMenu(null) }

  const handleSort = (col) => {
    if (sortBy === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortBy(col); setSortDir('asc') }
  }

  return (
    <div className="flex-1 p-8 overflow-y-auto" onClick={() => setActionMenu(null)}>
      <PageHeader title="Storage & Inventory" subtitle="Manage and track all materials in the factory." />

      {fetchError && (
        <div className="mb-4 flex items-center gap-2 px-4 py-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-xl text-sm text-amber-700 dark:text-amber-400">
          <span className="material-symbols-outlined text-base">warning</span>{fetchError}
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-gray-200 dark:border-gray-700 mb-6">
        <button
          onClick={() => setTab('materials')}
          className={`py-3 px-4 text-sm font-medium border-b-2 transition-colors ${tab === 'materials' ? 'border-primary text-primary' : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}`}
        >
          Materials
        </button>
        <button
          onClick={() => setTab('expected')}
          className={`py-3 px-4 text-sm font-medium border-b-2 transition-colors ${tab === 'expected' ? 'border-primary text-primary' : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}`}
        >
          Expected Arrivals
        </button>
      </div>

      {tab === 'materials' && (
      <>
      {/* Toolbar */}
      <div className="flex flex-wrap justify-between items-center gap-4 mb-6">
        <div className="flex flex-wrap items-center gap-3">
          {/* Search */}
          <div className="relative">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 dark:text-gray-400 text-lg pointer-events-none">search</span>
            <input
              type="text" value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search by name or ID…"
              className="pl-10 pr-4 py-2.5 h-10 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-sm text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary transition-colors w-64"
            />
          </div>
          {/* Status filter */}
          <select
            value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
            className="h-10 px-4 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary transition-colors"
          >
            <option value="">All Statuses</option>
            <option value="in_stock">In Stock</option>
            <option value="low_stock">Low Stock</option>
            <option value="out_of_stock">Out of Stock</option>
          </select>
        </div>
        <button
          onClick={() => { setEditTarget(null); setIsAddOpen(true) }}
          className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white font-semibold rounded-lg hover:bg-primary/90 transition-colors text-sm"
        >
          <span className="material-symbols-outlined text-lg">add</span>Add Item
        </button>
      </div>

      {/* Table */}
      <div className="bg-white dark:bg-gray-900 rounded-xl overflow-hidden border border-gray-300 dark:border-gray-700">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="bg-gray-100 dark:bg-gray-800">
              <tr className="border-b border-gray-300 dark:border-gray-700">
                <SortTh col="material_id"    label="Material ID"    sortBy={sortBy} sortDir={sortDir} onClick={handleSort}/>
                <SortTh col="material_name"  label="Material Name"  sortBy={sortBy} sortDir={sortDir} onClick={handleSort}/>
                <SortTh col="current_stock"  label="Current Stock"  sortBy={sortBy} sortDir={sortDir} onClick={handleSort}/>
                <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300">Min Required</th>
                <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300">Unit</th>
                <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300">Status</th>
                <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300">Location</th>
                <th className="px-6 py-4"/>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="px-6 py-12 text-center text-gray-500 dark:text-gray-400">
                  <div className="flex items-center justify-center gap-3">
                    <span className="w-5 h-5 border-2 border-gray-300 border-t-primary rounded-full animate-spin"/>Loading inventory…
                  </div>
                </td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={8} className="px-6 py-12 text-center text-gray-500 dark:text-gray-400">No inventory items found.</td></tr>
              ) : items.map(item => {
                // All fields already normalized by normalizeMaterial()
                const id       = item.material_id
                const name     = item.material_name
                const stock    = item.current_stock ?? '—'
                const minStock = item.min_stock ?? '—'
                const unit     = item.unit || ''
                const loc      = item.storage_location
                const label    = getStatus(item)
                return (
                  <tr key={id} className="border-b border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors last:border-b-0">
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400 font-mono">{id}</td>
                    <td className="px-6 py-4 whitespace-nowrap font-medium text-gray-900 dark:text-white text-sm">{name}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-gray-900 dark:text-white text-sm">{stock} {unit}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-gray-600 dark:text-gray-400 text-sm">{minStock} {unit}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-gray-600 dark:text-gray-400 text-sm">{unit || '—'}</td>
                    <td className="px-6 py-4 whitespace-nowrap">{statusBadge(label)}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-gray-600 dark:text-gray-400 text-sm">{loc}</td>
                    <td className="px-6 py-4 text-right relative">
                      <button
                        onClick={e => { e.stopPropagation(); setActionMenu(actionMenu === id ? null : id) }}
                        className="p-1.5 text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                      >
                        <span className="material-symbols-outlined text-lg">more_horiz</span>
                      </button>
                      {actionMenu === id && (
                        <div className="absolute right-4 top-10 z-20 bg-white dark:bg-[#1b2528] border border-gray-200 dark:border-gray-700 rounded-xl shadow-xl w-44 py-1" onClick={e => e.stopPropagation()}>
                          <MItem icon="edit"            label="Edit"           onClick={() => openEdit(item)} />
                          <MItem icon="remove_circle"   label="Consume Stock"  onClick={() => openConsume(item, 'consume')} />
                          <MItem icon="add_circle"      label="Receive Stock"  onClick={() => openConsume(item, 'receive')} />
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <AddItemModal
        isOpen={isAddOpen}
        item={editTarget}
        onClose={() => { setIsAddOpen(false); setEditTarget(null) }}
        onSave={fetchItems}
      />
      <ConsumeModal
        isOpen={!!consumeTarget}
        onClose={() => { setConsumeTarget(null); fetchItems() }}
        item={consumeTarget || {}}
        mode={consumeMode}
      />
      </>
      )}

      {tab === 'expected' && (
      <>
      {arrivalsError && (
        <div className="mb-4 flex items-center gap-2 px-4 py-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-xl text-sm text-amber-700 dark:text-amber-400">
          <span className="material-symbols-outlined text-base">warning</span>{arrivalsError}
        </div>
      )}
      <div className="flex flex-wrap justify-between items-center gap-4 mb-6">
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={arrivalMaterialFilter}
            onChange={e => setArrivalMaterialFilter(e.target.value)}
            className="h-10 px-4 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary"
          >
            <option value="">All materials</option>
            {items.map(m => (
              <option key={m.material_id} value={m.material_id}>{m.material_name} ({m.material_id})</option>
            ))}
          </select>
          <select
            value={arrivalStatusFilter}
            onChange={e => setArrivalStatusFilter(e.target.value)}
            className="h-10 px-4 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary"
          >
            <option value="pending">Pending</option>
            <option value="received">Received</option>
            <option value="cancelled">Cancelled</option>
          </select>
          <input
            type="date"
            value={arrivalFrom}
            onChange={e => setArrivalFrom(e.target.value)}
            placeholder="From"
            className="h-10 px-4 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary"
          />
          <input
            type="date"
            value={arrivalTo}
            onChange={e => setArrivalTo(e.target.value)}
            placeholder="To"
            className="h-10 px-4 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <button
          onClick={() => setIsAddArrivalOpen(true)}
          className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white font-semibold rounded-lg hover:bg-primary/90 transition-colors text-sm"
        >
          <span className="material-symbols-outlined text-lg">add</span>Add Expected Arrival
        </button>
      </div>
      <div className="bg-white dark:bg-gray-900 rounded-xl overflow-hidden border border-gray-300 dark:border-gray-700">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="bg-gray-100 dark:bg-gray-800">
              <tr className="border-b border-gray-300 dark:border-gray-700">
                <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300">Arrival ID</th>
                <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300">Material</th>
                <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300">Quantity</th>
                <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300">Expected arrival</th>
                <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300">Status</th>
                <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300">Notes</th>
              </tr>
            </thead>
            <tbody>
              {arrivalsLoading ? (
                <tr><td colSpan={6} className="px-6 py-12 text-center text-gray-500 dark:text-gray-400">
                  <div className="flex items-center justify-center gap-3">
                    <span className="w-5 h-5 border-2 border-gray-300 border-t-primary rounded-full animate-spin"/>Loading…
                  </div>
                </td></tr>
              ) : arrivals.length === 0 ? (
                <tr><td colSpan={6} className="px-6 py-12 text-center text-gray-500 dark:text-gray-400">No expected arrivals found.</td></tr>
              ) : arrivals.map(a => {
                const id = a.arrival_id || a.id
                return (
                  <tr key={id} className="border-b border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 last:border-b-0">
                    <td className="px-6 py-4 text-sm font-mono text-gray-600 dark:text-gray-400">{id}</td>
                    <td className="px-6 py-4 text-sm font-medium text-gray-900 dark:text-white">{a.material_name || a.material_id || '—'}</td>
                    <td className="px-6 py-4 text-sm text-gray-900 dark:text-white">{a.quantity}</td>
                    <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-400">{a.expected_arrive_at ? new Date(a.expected_arrive_at).toLocaleString() : '—'}</td>
                    <td className="px-6 py-4"><span className={`inline-flex px-2 py-1 rounded text-xs font-medium ${a.status === 'received' ? 'bg-green-500/20 text-green-600 dark:text-green-400' : a.status === 'cancelled' ? 'bg-gray-500/20 text-gray-600 dark:text-gray-400' : 'bg-amber-500/20 text-amber-600 dark:text-amber-400'}`}>{a.status || 'pending'}</span></td>
                    <td className="px-6 py-4 text-sm text-gray-500 dark:text-gray-400">{a.notes || '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
      <AddExpectedArrivalModal
        isOpen={isAddArrivalOpen}
        onClose={() => setIsAddArrivalOpen(false)}
        onSave={fetchArrivals}
        materials={items}
      />
      </>
      )}
    </div>
  )
}

const SortTh = ({ col, label, sortBy, sortDir, onClick }) => (
  <th
    className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300 cursor-pointer select-none group"
    onClick={() => onClick(col)}
  >
    <div className="flex items-center gap-1">
      {label}
      <span className={`material-symbols-outlined text-xs transition-opacity ${sortBy === col ? 'opacity-100 text-primary' : 'opacity-0 group-hover:opacity-50'}`}>
        {sortBy === col && sortDir === 'desc' ? 'arrow_downward' : 'arrow_upward'}
      </span>
    </div>
  </th>
)

const MItem = ({ icon, label, onClick }) => (
  <button onClick={onClick} className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
    <span className="material-symbols-outlined text-base">{icon}</span>{label}
  </button>
)

export default StorageInventory
