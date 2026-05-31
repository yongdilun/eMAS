const InlineBusyIndicator = ({ label = 'Working' }) => (
  <span className="inline-flex items-center justify-center gap-1" aria-live="polite">
    <span className="material-symbols-outlined animate-spin text-base" aria-hidden="true">
      progress_activity
    </span>
    <span>{label}</span>
    <span className="inline-flex w-4 justify-start gap-0.5" aria-hidden="true">
      <span className="animate-pulse">.</span>
      <span className="animate-pulse" style={{ animationDelay: '120ms' }}>.</span>
      <span className="animate-pulse" style={{ animationDelay: '240ms' }}>.</span>
    </span>
  </span>
)

export default InlineBusyIndicator
