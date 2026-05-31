import InlineBusyIndicator from '../../shared/InlineBusyIndicator'

const ResolutionSummaryBar = ({
  selectedCount = 0,
  loading = false,
  onApplyReplan,
}) => {
  const applyDisabled = loading || selectedCount === 0

  return (
    <div className="sticky bottom-0 mt-3 border-t border-hairline bg-surface-1/95 p-3 backdrop-blur">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onApplyReplan}
          disabled={applyDisabled}
          className="inline-flex h-9 min-w-[10rem] items-center justify-center rounded-md bg-primary px-4 text-sm font-semibold text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
        >
          {loading ? <InlineBusyIndicator label="Running" /> : 'Apply and Replan'}
        </button>
      </div>
    </div>
  )
}

export default ResolutionSummaryBar
