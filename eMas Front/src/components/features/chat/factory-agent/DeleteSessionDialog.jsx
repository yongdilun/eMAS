const DeleteSessionDialog = ({
  session,
  deleting,
  onCancel,
  onConfirm,
}) => {
  if (!session) return null

  return (
    <div
      className="absolute inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Delete session confirmation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !deleting) onCancel()
      }}
    >
      <div className="w-full max-w-md rounded-lg border border-hairline bg-surface-1 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-ink">
              Delete session?
            </div>
            <div className="mt-1 text-xs text-ink-subtle">
              This will permanently remove the chat history and approvals for:
            </div>
          </div>
          <button
            type="button"
            className="p-1.5 rounded-lg hover:bg-surface-2 text-ink-subtle"
            onClick={() => {
              if (!deleting) onCancel()
            }}
            aria-label="Close"
          >
            <span className="material-symbols-outlined text-lg">close</span>
          </button>
        </div>

        <div className="mt-3 rounded-md border border-hairline bg-surface-2 px-3 py-2">
          <div className="text-xs font-semibold text-ink truncate">
            {session.name || session.session_id}
          </div>
          <div className="mt-0.5 text-[11px] text-ink-subtle">
            Session ID: {session.session_id}
          </div>
        </div>

        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            disabled={deleting}
            className="px-3 py-1.5 rounded-md text-xs font-semibold bg-surface-2 text-ink hover:bg-surface-3 disabled:opacity-60"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={deleting}
            className="px-3 py-1.5 rounded-md text-xs font-semibold bg-inverse-canvas text-inverse-ink hover:opacity-90 disabled:opacity-60"
            onClick={onConfirm}
          >
            {deleting ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default DeleteSessionDialog
