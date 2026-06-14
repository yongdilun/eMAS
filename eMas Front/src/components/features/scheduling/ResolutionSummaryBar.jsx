import InlineBusyIndicator from '../../shared/InlineBusyIndicator'

const ResolutionSummaryBar = ({
  selectedCount = 0,
  loading = false,
  onApplyReplan,
  onReplanOnly,
  avoidFloatingAssistant = false,
}) => {
  const applyDisabled = loading || selectedCount === 0

  return (
    <div
      className={`sticky bottom-0 mt-3 border-t border-hairline bg-surface-1/95 p-3 backdrop-blur ${
        avoidFloatingAssistant ? 'pb-20 md:pb-3 md:pr-36' : ''
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-auto text-xs font-medium text-ink-subtle">
          {selectedCount} row{selectedCount === 1 ? '' : 's'} selected for apply
        </span>
        <button
          type="button"
          onClick={onApplyReplan}
          disabled={applyDisabled}
          className="inline-flex h-9 min-w-[10rem] items-center justify-center rounded-md bg-primary px-4 text-sm font-semibold text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
        >
          {loading ? <InlineBusyIndicator label="Running" /> : 'Apply and Replan'}
        </button>
        {onReplanOnly && (
          <button
            type="button"
            onClick={onReplanOnly}
            disabled={loading}
            className="inline-flex h-9 min-w-[8rem] items-center justify-center rounded-md border border-hairline bg-surface-2 px-4 text-sm font-semibold text-ink transition-colors hover:bg-surface-3 disabled:opacity-50"
          >
            Replan only
          </button>
        )}
      </div>
    </div>
  )
}

export default ResolutionSummaryBar
