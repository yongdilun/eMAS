const FactoryAgentChatComposer = ({
  input,
  onInputChange,
  messageMode,
  onMessageModeChange,
  disabled,
  placeholder,
  canCancel,
  isCancelling,
  isSending,
  onCancel,
  onSend,
}) => (
  <form
    className="mx-4 mb-4 mt-2 flex flex-shrink-0 items-center gap-2 rounded-lg border border-hairline bg-surface-1 p-2.5"
    onSubmit={(e) => {
      e.preventDefault()
      onSend()
    }}
  >
    <select
      value={messageMode}
      onChange={(e) => onMessageModeChange(e.target.value)}
      disabled={disabled}
      className="h-11 rounded-md border border-hairline bg-surface-2 px-3 text-xs text-ink outline-none focus:border-primary focus:ring-2 focus:ring-primary/30"
      aria-label="Message mode"
    >
      <option value="normal">Normal</option>
      <option value="plan">Plan</option>
    </select>
    <textarea
      rows={1}
      value={input}
      onChange={(e) => onInputChange(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      className="flex-1 resize-none rounded-md border border-hairline bg-surface-2 px-4 py-2.5 text-sm text-ink outline-none placeholder:text-ink-tertiary focus:border-primary focus:ring-2 focus:ring-primary/30"
    />
    <button
      type={canCancel ? 'button' : 'submit'}
      onClick={canCancel ? onCancel : undefined}
      disabled={canCancel ? isCancelling : disabled || !input.trim()}
      className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-md transition-colors disabled:opacity-60 ${canCancel
        ? 'border border-hairline bg-surface-2 text-ink hover:bg-surface-3'
        : 'bg-primary text-white hover:bg-primary-hover'
        }`}
      aria-label={canCancel ? 'Cancel current run' : 'Send'}
    >
      {canCancel ? (
        <span className="material-symbols-outlined text-xl fill">stop</span>
      ) : isSending ? (
        <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
      ) : (
        <span className="material-symbols-outlined text-xl">send</span>
      )}
    </button>
  </form>
)

export default FactoryAgentChatComposer
