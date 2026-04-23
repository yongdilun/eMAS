const ResolutionSummaryBar = ({
  selectedCount = 0,
  selectedCurrentProposalCount = 0,
  replenishCount = 0,
  blockedJobs = 0,
  totalDeficit = 0,
  loading = false,
  onApplyReplan,
  onRescheduleOnly,
  onRefresh,
  onReset,
}) => {
  const applyDisabled = loading || selectedCount === 0

  return (
    <div className="sticky bottom-0 border-t border-gray-200 dark:border-gray-700 bg-white/95 dark:bg-gray-900/95 backdrop-blur p-3 mt-3">
      <div className="flex flex-wrap items-center gap-2 mb-2 text-xs">
        <span className="px-2 py-1 rounded bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
          Selected actions: {selectedCount}
        </span>
        <span className="px-2 py-1 rounded bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300">
          Current proposal selected: {selectedCurrentProposalCount}
        </span>
        <span className="px-2 py-1 rounded bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
          Apply-ready: {replenishCount}
        </span>
        <span className="px-2 py-1 rounded bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300">
          Blocked jobs: {blockedJobs}
        </span>
        <span className="px-2 py-1 rounded bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300">
          Total deficit: {totalDeficit}
        </span>
      </div>
      {selectedCount > 0 && replenishCount === 0 && (
        <p className="text-[11px] text-amber-800 dark:text-amber-200 mb-2 max-w-3xl">
          No <strong>apply-ready</strong> rows (need replenish or <strong>schedule_production</strong> with qty and arrival time). Use{' '}
          <strong>Reschedule all (no material apply)</strong> or refresh analysis.
        </p>
      )}
      <div className="flex flex-wrap gap-2 items-center">
        <button
          type="button"
          onClick={onApplyReplan}
          disabled={applyDisabled}
          className="h-9 px-3 rounded-md bg-primary text-white text-sm font-semibold hover:bg-primary/90 disabled:opacity-50"
        >
          {loading ? 'Running…' : 'Apply selected + Reschedule all'}
        </button>
        {typeof onRescheduleOnly === 'function' && (
          <button
            type="button"
            onClick={onRescheduleOnly}
            disabled={loading}
            className="h-9 px-3 rounded-md border border-primary text-primary text-sm font-semibold hover:bg-primary/10 disabled:opacity-50"
          >
            {loading ? 'Running…' : 'Reschedule all (no material apply)'}
          </button>
        )}
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="h-9 px-3 rounded-md border border-gray-300 dark:border-gray-600 text-sm"
        >
          Refresh analysis
        </button>
        <button
          type="button"
          onClick={onReset}
          disabled={loading}
          className="h-9 px-3 rounded-md border border-gray-300 dark:border-gray-600 text-sm"
        >
          Reset to recommendations
        </button>
      </div>
    </div>
  )
}

export default ResolutionSummaryBar
