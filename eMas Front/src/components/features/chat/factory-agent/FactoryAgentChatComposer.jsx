const FactoryAgentChatComposer = ({
  input,
  onInputChange,
  disabled,
  placeholder,
  canCancel,
  isCancelling,
  isSending,
  onCancel,
  onSend,
}) => {
  const hasDraft = Boolean(input.trim())
  const submitsMessage = !canCancel || hasDraft
  const buttonDisabled = submitsMessage ? disabled || !hasDraft || isSending : isCancelling

  return (
    <form
      className="mx-4 mb-4 mt-2 flex flex-shrink-0 items-center gap-2 rounded-lg border border-hairline bg-surface-1 p-2.5"
      onSubmit={(e) => {
        e.preventDefault()
        onSend()
      }}
    >
      <textarea
        rows={1}
        value={input}
        onChange={(e) => onInputChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        className="flex-1 resize-none rounded-md border border-hairline bg-surface-2 px-4 py-2.5 text-sm text-ink outline-none placeholder:text-ink-tertiary focus:border-primary focus:ring-2 focus:ring-primary/30"
      />
      <button
        type={submitsMessage ? 'submit' : 'button'}
        onClick={submitsMessage ? undefined : onCancel}
        disabled={buttonDisabled}
        className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-md transition-colors disabled:opacity-60 ${submitsMessage
          ? 'bg-primary text-white hover:bg-primary-hover'
          : 'border border-hairline bg-surface-2 text-ink hover:bg-surface-3'
          }`}
        aria-label={submitsMessage ? 'Send' : 'Cancel current run'}
      >
        {submitsMessage ? (
          isSending ? (
            <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          ) : (
            <span className="material-symbols-outlined text-xl">send</span>
          )
        ) : (
          <span className="material-symbols-outlined text-xl fill">stop</span>
        )}
      </button>
    </form>
  )
}

export default FactoryAgentChatComposer
