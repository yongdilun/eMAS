import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import JobDetailsPanel from '../components/features/gantt/JobDetailsPanel'
import CreateJobModal from '../components/features/gantt/CreateJobModal'
import PageHeader from '../components/shared/PageHeader'
import FilterSortPanel from '../components/shared/FilterSortPanel'
import { jobsApi, machinesApi, toList, apiErrorMessage, apiErrorToastOptions } from '../services/api'
import { normalizeMachine, normalizeJob } from '../services/normalizers'
import logger from '../services/logger'
import { useToast } from '../context/ToastContext'

const FILTER_FIELDS = [
    { key: 'machine_id', label: 'Machine', type: 'select', options: [] },
    { key: 'status', label: 'Status', type: 'select', options: ['scheduled', 'in-progress', 'completed', 'delayed'] },
    { key: 'priority', label: 'Priority', type: 'select', options: ['urgent', 'high', 'medium', 'low'] },
    { key: 'start', label: 'Start Date (from)', type: 'date' },
    { key: 'end', label: 'Start Date (to)', type: 'date' },
    { key: 'product_id', label: 'Product ID', type: 'text', placeholder: 'e.g. P-001' },
]

const SORT_FIELDS = [
    { key: 'deadline', label: 'Deadline' },
    { key: 'priority', label: 'Priority' },
    { key: 'created_at', label: 'Date Created' },
    { key: 'quantity_total', label: 'Quantity' },
    { key: 'completion', label: 'Completion %' },
]

const STATUS_STYLES = {
    scheduled: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 ',
    'in-progress': 'bg-surface-2 text-yellow-700 ',
    completed: 'bg-semantic-success/20 text-green-700 ',
    delayed: 'bg-surface-2 text-red-700 ',
}

const Jobs = () => {
    const toast = useToast()
    const [selectedJob, setSelectedJob] = useState(null)
    const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
    const [isFilterOpen, setIsFilterOpen] = useState(false)
    const [showDetailsPanel, setShowDetailsPanel] = useState(true)

    const [jobs, setJobs] = useState([])
    const [machines, setMachines] = useState([])
    const [loading, setLoading] = useState(true)
    const [fetchError, setFetchError] = useState('')
    const [activeFilters, setActiveFilters] = useState({})
    const [activeSort, setActiveSort] = useState({ sortBy: '', sortDir: 'asc' })

    const filterCount = Object.entries(activeFilters).filter(([k, v]) => v && !k.startsWith('_')).length

    const fetchJobs = useCallback(async () => {
        setLoading(true)
        setFetchError('')
        try {
            const params = {}
            Object.entries(activeFilters).forEach(([k, v]) => { if (v && !k.startsWith('_')) params[k] = v })
            if (activeSort.sortBy) {
                params.sort_by = activeSort.sortBy
                params.sort_dir = activeSort.sortDir
            }
            const data = await jobsApi.list(params)
            const normalized = toList(data).map(normalizeJob)
            setJobs(normalized)
            logger.info('Jobs loaded', { count: normalized.length })
        } catch (err) {
            logger.error('Failed to load jobs', err, { page: 'Jobs' })
            setFetchError(apiErrorMessage(err, 'Unable to reach server. Showing cached data.'))
            setJobs([])
        } finally {
            setLoading(false)
        }
    }, [activeFilters, activeSort])

    useEffect(() => { fetchJobs() }, [fetchJobs])

    useEffect(() => {
        machinesApi.list()
            .then((data) => setMachines(toList(data).map(normalizeMachine)))
            .catch((err) => logger.warn('Could not load machines for filter', { message: err?.message }))
    }, [])

    const handleApplyFilters = (combined) => {
        const { _sortBy, _sortDir, ...rest } = combined
        setActiveFilters(rest)
        setActiveSort({ sortBy: _sortBy || '', sortDir: _sortDir || 'asc' })
    }

    const handleCancelJob = async () => {
        if (!selectedJob) return
        const jobId = selectedJob.job_id || selectedJob.jobId || selectedJob.id
        if (!jobId) {
            toast.error('Cannot determine job ID. Select a job.')
            return
        }
        try {
            await jobsApi.cancel(jobId)
            logger.info('Job cancelled', { jobId })
            toast.success(`Job ${jobId} cancelled successfully.`)
            setSelectedJob(null)
            fetchJobs()
        } catch (err) {
            logger.error('Failed to cancel job', err, { jobId })
            toast.error(apiErrorMessage(err, 'Failed to cancel job.'), apiErrorToastOptions(err))
        }
    }

    const handleSaveJob = (created) => {
        if (created) setJobs((prev) => [created, ...prev])
        fetchJobs()
    }

    const filterFieldsWithMachines = FILTER_FIELDS.map((f) =>
        f.key === 'machine_id'
            ? { ...f, options: machines.map((m) => ({ value: m.machine_id || m.id, label: m.machine_name || m.name || m.machine_id || m.id })) }
            : f
    )

    return (
        <div className="flex h-full w-full">
            <div className="flex-1 flex flex-col overflow-hidden">
                <div className="p-8 border-b border-hairline/50 flex-shrink-0">
                    <PageHeader title="Jobs" subtitle="Manage production jobs.">
                        <button
                            onClick={() => setIsFilterOpen(true)}
                            className="relative flex items-center gap-2 h-10 px-4 bg-transparent border border-hairline text-ink text-sm font-bold rounded-lg hover:bg-surface-2 transition-colors"
                        >
                            <span className="material-symbols-outlined text-lg">filter_list</span>
                            <span>Filter &amp; Sort</span>
                            {filterCount > 0 && (
                                <span className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-primary text-white text-[10px] font-bold flex items-center justify-center">
                                    {filterCount}
                                </span>
                            )}
                        </button>

                        <button
                            onClick={() => setIsCreateModalOpen(true)}
                            className="flex items-center gap-2 h-10 px-4 bg-primary text-white text-sm font-bold rounded-lg hover:bg-primary/90 transition-colors"
                        >
                            <span className="material-symbols-outlined text-lg">add</span>
                            <span>Create Job</span>
                        </button>

                        <Link
                            to="/scheduling"
                            className="flex items-center gap-2 h-10 px-4 bg-transparent border border-hairline text-ink text-sm font-semibold rounded-lg hover:bg-surface-2 transition-colors"
                        >
                            <span className="material-symbols-outlined text-lg">calendar_today</span>
                            <span>Go to Scheduling</span>
                        </Link>

                        <button
                            type="button"
                            onClick={() => setShowDetailsPanel((v) => !v)}
                            className="flex items-center gap-2 h-10 px-3 bg-transparent border border-hairline text-ink text-xs font-semibold rounded-lg hover:bg-surface-2 transition-colors"
                        >
                            <span className="material-symbols-outlined text-base">
                                {showDetailsPanel ? 'chevron_right' : 'chevron_left'}
                            </span>
                            <span>{showDetailsPanel ? 'Hide Details' : 'Show Details'}</span>
                        </button>
                    </PageHeader>
                </div>

                {filterCount > 0 && (
                    <div className="px-6 pt-3 flex flex-wrap gap-2">
                        {Object.entries(activeFilters).filter(([, v]) => v).map(([k, v]) => (
                            <span
                                key={k}
                                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary/10 text-primary text-xs font-medium"
                            >
                                {k.replace(/_/g, ' ')}: <strong>{v}</strong>
                                <button
                                    onClick={() => setActiveFilters((p) => { const n = { ...p }; n[k] = ''; return n })}
                                    className="hover:text-primary/60 transition-colors"
                                >
                                    <span className="material-symbols-outlined text-xs">close</span>
                                </button>
                            </span>
                        ))}
                        <button
                            onClick={() => setActiveFilters({})}
                            className="text-xs text-ink-subtle hover:text-red-500 transition-colors underline"
                        >
                            Clear all
                        </button>
                    </div>
                )}

                {fetchError && (
                    <div className="mx-6 mt-3 flex items-center gap-2 px-4 py-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-lg text-sm text-amber-700 dark:text-amber-400">
                        <span className="material-symbols-outlined text-base">warning</span>
                        {fetchError}
                    </div>
                )}

                <div className="flex-1 flex overflow-hidden p-6">
                    <div className="flex-1 overflow-y-auto">
                        {loading ? (
                            <div className="flex items-center justify-center h-64 text-ink-subtle gap-3">
                                <span className="w-5 h-5 border-2 border-hairline border-t-primary rounded-full animate-spin" />
                                Loading jobs…
                            </div>
                        ) : jobs.length === 0 ? (
                            <div className="flex flex-col items-center justify-center h-64 text-ink-subtle gap-3">
                                <span className="material-symbols-outlined text-5xl">work</span>
                                <p>No jobs found. Create a job or adjust filters.</p>
                            </div>
                        ) : (
                            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                                {jobs.map((job) => {
                                    const jobId = job.job_id || job.jobId || job.id
                                    const status = (job.status || 'scheduled').toLowerCase()
                                    const statusCls = STATUS_STYLES[status] || STATUS_STYLES.scheduled
                                    const isSelected = selectedJob && (selectedJob.job_id || selectedJob.jobId || selectedJob.id) === jobId
                                    return (
                                        <button
                                            key={jobId}
                                            onClick={() => setSelectedJob(job)}
                                            className={`text-left p-4 rounded-lg border transition-all ${isSelected
                                                    ? 'ring-2 ring-primary bg-primary/5 dark:bg-primary/10 border-primary'
                                                    : 'bg-surface-1/50 border-hairline hover:border-hairline '
                                                }`}
                                        >
                                            <div className="flex items-start justify-between gap-2">
                                                <span className="font-bold text-sm text-ink truncate">{jobId}</span>
                                                <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full shrink-0 ${statusCls}`}>
                                                    {status}
                                                </span>
                                            </div>
                                            <div className="mt-2 text-xs text-ink-subtle truncate">
                                                {job.product_id || '—'}
                                            </div>
                                            {(job.quantity_total != null || job.deadline) && (
                                                <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-ink-subtle">
                                                    {job.quantity_total != null && <span>{job.quantity_total} units</span>}
                                                    {job.deadline && (
                                                        <span>Deadline: {new Date(job.deadline).toLocaleDateString()}</span>
                                                    )}
                                                </div>
                                            )}
                                        </button>
                                    )
                                })}
                            </div>
                        )}
                    </div>

                    {showDetailsPanel && (
                        <JobDetailsPanel
                            job={selectedJob}
                            onEdit={() => { }}
                            onCancel={handleCancelJob}
                            onJobUpdated={fetchJobs}
                            onClose={() => setShowDetailsPanel(false)}
                        />
                    )}
                </div>

                <CreateJobModal
                    isOpen={isCreateModalOpen}
                    onClose={() => setIsCreateModalOpen(false)}
                    onSave={handleSaveJob}
                />

                <FilterSortPanel
                    isOpen={isFilterOpen}
                    onClose={() => setIsFilterOpen(false)}
                    filters={activeFilters}
                    onApply={handleApplyFilters}
                    filterFields={filterFieldsWithMachines}
                    sortFields={SORT_FIELDS}
                />
            </div>
        </div>
    )
}

export default Jobs
