const ClearAllChatsDialog = ({
  open,
  sessionCount,
  clearing,
  onCancel,
  onConfirm,
}) => {
  if (!open) return null

  return (
    <div
      className="absolute inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Clear all chats confirmation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !clearing) onCancel()
      }}
    >
      <div className="w-full max-w-md rounded-lg border border-hairline bg-surface-1 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-ink">
              Clear all chats?
            </div>
            <div className="mt-1 text-xs text-ink-subtle">
              This will permanently remove every chat session and approval for this operator.
            </div>
          </div>
          <button
            type="button"
            className="p-1.5 rounded-lg hover:bg-surface-2 text-ink-subtle"
            onClick={() => {
              if (!clearing) onCancel()
            }}
            aria-label="Close"
          >
            <span className="material-symbols-outlined text-lg">close</span>
          </button>
        </div>

        <div className="mt-3 rounded-md border border-hairline bg-surface-2 px-3 py-2">
          <div className="text-xs font-semibold text-ink">
            {sessionCount === 1 ? '1 chat will be cleared.' : `${sessionCount} chats will be cleared.`}
          </div>
          <div className="mt-0.5 text-[11px] text-ink-subtle">
            This action cannot be undone.
          </div>
        </div>

        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            disabled={clearing}
            className="px-3 py-1.5 rounded-md text-xs font-semibold bg-surface-2 text-ink hover:bg-surface-3 disabled:opacity-60"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={clearing}
            className="px-3 py-1.5 rounded-md text-xs font-semibold bg-inverse-canvas text-inverse-ink hover:opacity-90 disabled:opacity-60"
            onClick={onConfirm}
          >
            {clearing ? 'Clearing...' : 'Clear all'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default ClearAllChatsDialog
