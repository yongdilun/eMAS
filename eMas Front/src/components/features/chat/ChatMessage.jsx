/**
 * Chat message with avatar, timestamp, content, and optional embedded blocks.
 * Linear-inspired UI (DESIGN-linear.app.md): surface ladder, lavender accent, rounded-lg cards.
 */
import React from 'react'
import {
  formatBasedOnLine,
  formatCitationChipLabel,
  formatInlineCitationLabel,
  stripSourceFootnoteDefinitions,
} from './sourceFormatting'

const ChatMessage = ({
  message,
  isUser,
  timestamp,
  animateIn = true,
  renderBlocks,
  messageAfterBlocks = false,
  sources = [],
  safetyContent = null,
}) => {
  const hasMessage = message != null && String(message).trim() !== ''
  const bubbleAnim = !isUser && animateIn ? 'emas-chat-enter' : ''

  const renderFormattedText = (text) => {
    if (!text) return null
    return <div className="whitespace-pre-wrap">{renderCitationsAndBold(stripSourceFootnoteDefinitions(text))}</div>
  }

  const renderCitationsAndBold = (text) => {
    const boldParts = text.split(/(\*\*.*?\*\*)/g)
    return boldParts.map((bPart, j) => {
      if (bPart.startsWith('**') && bPart.endsWith('**')) {
        return (
          <strong key={j} className="font-semibold text-ink">
            {bPart.slice(2, -2)}
          </strong>
        )
      }

      const citeParts = bPart.split(/(\[\^\d+\])/g)
      return citeParts.map((cPart, k) => {
        const match = cPart.match(/\[\^(\d+)\]/)
        if (match) {
          const num = parseInt(match[1], 10)
          const source = (sources || []).find((s) => String(s.source_number) === String(num))
          const fullTitle = source?.title || source?.doc_id || `Source ${num}`
          const chipLabel = formatInlineCitationLabel(num)

          return (
            <span key={k} className="group relative mx-0.5 inline-flex items-center align-middle">
              <span className="inline-flex max-w-[7rem] items-center gap-1 rounded-md border border-primary/25 bg-primary/[0.08] px-1.5 py-0.5 text-[10px] font-semibold leading-tight text-primary shadow-sm transition-colors hover:border-primary/40 hover:bg-primary/[0.12]">
                <span className="min-w-0 flex-1 truncate text-left" title={fullTitle}>
                  {chipLabel}
                </span>
              </span>
              <span className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 w-max max-w-[260px] -translate-x-1/2 scale-0 rounded-lg border border-hairline bg-surface-3 p-2.5 text-[11px] font-medium text-ink shadow-2xl transition-all duration-200 group-hover:scale-100">
                <div className="mb-1 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-primary">
                  <span className="material-symbols-outlined text-[12px]">verified_user</span>
                  Cited document
                </div>
                <div className="leading-snug font-semibold">{fullTitle}</div>
                {source?.organization && (
                  <div className="mt-1.5 flex items-center gap-1 text-[10px] text-ink-subtle">
                    <span className="material-symbols-outlined text-[11px]">corporate_fare</span>
                    {source.organization}
                  </div>
                )}
                {source?.doc_id && (
                  <div className="mt-1 font-mono text-[9px] uppercase text-ink-tertiary">ID: {source.doc_id}</div>
                )}
                <span className="absolute left-1/2 top-full -ml-1 border-[6px] border-transparent border-t-surface-3" />
              </span>
            </span>
          )
        }
        return cPart
      })
    })
  }

  const renderSourcesList = () => {
    if (!sources || sources.length === 0) return null
    return (
      <div className="mt-5 border-t border-hairline pt-4">
        <div className="mb-2.5 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-ink-tertiary">
          <span className="material-symbols-outlined text-[12px]">library_books</span>
          Knowledge sources
        </div>
        <div className="flex flex-wrap gap-2">
          {sources.map((s, idx) => {
            const num = s.source_number ?? idx + 1
            const label = formatCitationChipLabel(s, num)
            const fullTitle = s.title || s.doc_id || label
            return (
              <div
                key={`${idx}-${num}`}
                className="group flex max-w-full items-start gap-1.5 rounded-md border border-hairline bg-surface-2 px-2 py-1.5 text-left text-[10px] text-ink-muted shadow-sm transition-colors hover:border-hairline-strong hover:bg-surface-3 sm:max-w-[18rem]"
                title={fullTitle}
              >
                <span className="material-symbols-outlined mt-0.5 shrink-0 text-[14px] text-ink-tertiary group-hover:text-primary">
                  description
                </span>
                <span className="min-w-0 flex-1 truncate font-medium leading-snug">{label}</span>
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  const renderSafetySection = () => {
    if (!safetyContent) return null
    const title = typeof safetyContent === 'object' ? safetyContent.title || 'Safety Advisory' : 'Safety Advisory'
    const content = typeof safetyContent === 'object' ? safetyContent.content || '' : safetyContent

    return (
      <div className="mt-3 flex overflow-hidden rounded-lg border border-hairline-strong bg-surface-2">
        <div className="w-[2px] shrink-0 bg-brand-secure/70" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 border-b border-hairline px-3 py-2 text-eyebrow uppercase text-brand-secure">
            <span
              className="material-symbols-outlined text-[14px] leading-none"
              style={{ fontVariationSettings: "'FILL' 1, 'wght' 500, 'GRAD' 0, 'opsz' 24" }}
            >
              shield
            </span>
            {title}
          </div>
          <div className="px-3 py-2.5 text-caption text-ink-muted">{content}</div>
        </div>
      </div>
    )
  }

  const hasAssistantBody = hasMessage || Boolean(renderBlocks)

  return (
    <div className={`mb-6 flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-hairline shadow-sm ${
          isUser ? 'bg-primary/10 text-primary' : 'bg-surface-2 text-ink-subtle'
        }`}
      >
        <span
          className="material-symbols-outlined text-lg"
          style={!isUser ? { fontVariationSettings: "'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24" } : {}}
        >
          {isUser ? 'person' : 'smart_toy'}
        </span>
      </div>
      <div
        className={`flex flex-col ${isUser ? 'max-w-[85%] items-end' : 'w-full max-w-2xl items-stretch'}`}
      >
        <div className={`mb-1.5 flex items-center gap-2 px-1 ${isUser ? 'flex-row-reverse' : ''}`}>
          <span className="text-[11px] font-bold uppercase tracking-wider text-ink-tertiary">
            {isUser ? 'You' : 'eMAS AI Assistant'}
          </span>
          {timestamp && <span className="text-[10px] text-ink-subtle opacity-60">{timestamp}</span>}
        </div>

        {isUser ? (
          <div
            className={`rounded-xl rounded-tr-none bg-primary px-4 py-3 text-[13px] leading-relaxed text-white shadow-md shadow-primary/10 transition-all duration-300 ${bubbleAnim}`}
          >
            <div className="relative">
              {messageAfterBlocks ? renderBlocks?.() : null}
              {hasMessage ? <div>{renderFormattedText(message)}</div> : null}
              {!messageAfterBlocks ? renderBlocks?.() : null}
            </div>
          </div>
        ) : (
          <div
            className={`overflow-hidden rounded-lg border border-hairline bg-surface-1 text-ink shadow-sm transition-all duration-300 ${bubbleAnim}`}
          >
            {hasAssistantBody ? (
              <div className="border-b border-hairline bg-surface-2 px-5 py-3">
                <div className="text-eyebrow uppercase tracking-[0.04em] text-ink-tertiary">Answer</div>
                {sources?.length > 0 && (
                  <p className="mt-1.5 text-caption leading-snug text-ink-subtle">{formatBasedOnLine(sources)}</p>
                )}
              </div>
            ) : null}
            <div className="px-5 py-4 text-[13px] leading-relaxed">
              <div className="relative">
                {messageAfterBlocks ? renderBlocks?.() : null}
                {hasMessage ? <div>{renderFormattedText(message)}</div> : null}
                {!messageAfterBlocks ? renderBlocks?.() : null}
                {!isUser && renderSourcesList()}
              </div>
            </div>
          </div>
        )}

        {!isUser && renderSafetySection()}
      </div>
    </div>
  )
}

export default ChatMessage
