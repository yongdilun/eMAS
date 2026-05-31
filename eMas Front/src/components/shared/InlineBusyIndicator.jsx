const InlineBusyIndicator = ({ label = 'Working' }) => (
  <span className="inline-flex items-center justify-center gap-0.5 whitespace-nowrap leading-none" aria-live="polite">
    <span
      className="material-symbols-outlined animate-spin"
      style={{ fontSize: '1em', lineHeight: 1, width: '1em', height: '1em', overflow: 'hidden' }}
      aria-hidden="true"
    >
      progress_activity
    </span>
    <span>{label}</span>
    <span className="inline-flex w-3 justify-start gap-px leading-none" aria-hidden="true">
      <span className="animate-pulse">.</span>
      <span className="animate-pulse" style={{ animationDelay: '120ms' }}>.</span>
      <span className="animate-pulse" style={{ animationDelay: '240ms' }}>.</span>
    </span>
  </span>
)

export default InlineBusyIndicator
