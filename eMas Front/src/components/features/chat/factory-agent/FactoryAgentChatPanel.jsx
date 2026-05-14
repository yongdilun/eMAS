/* eslint-disable react/prop-types */
import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import ChatMessage from '../ChatMessage'
import ApprovalCard from './ApprovalCard'
import ActivityTimeline from './ActivityTimeline'
import { useFactoryAgentChat } from './useFactoryAgentChat'
import { FACTORY_AGENT_STATUS } from '../../../../services/factoryAgentApi'
import { resolveApprovalTablePresentation } from './approvalInterruptDisplay.js'
import { TablePresentation } from '../turns/TurnBlocks'
import { assistantAnswerAllowed, friendlySessionStatus } from './activityTimelineUtils'
import {
  formatInlineCitationLabel,
  stripSourceFootnoteDefinitions,
} from '../sourceFormatting'
import { formatFactoryAgentTime } from './factoryAgentDisplayTime.js'

const CHAT_VIEW_MODE = (import.meta.env?.VITE_FACTORY_AGENT_CHAT_MODE || 'user').trim().toLowerCase() === 'dev' ? 'dev' : 'user'
const ACTIVITY_TIMELINE_ENABLED = !['0', 'false', 'off'].includes(
  String(import.meta.env?.VITE_FACTORY_AGENT_ACTIVITY_TIMELINE ?? 'true').trim().toLowerCase(),
)
const STREAM_BUFFER_MS = Number(import.meta.env?.VITE_FACTORY_AGENT_STREAM_BUFFER_MS || 40)
const PROGRESS_STAGE_MIN_MS = Number(import.meta.env?.VITE_FACTORY_AGENT_PROGRESS_STAGE_MIN_MS || 700)

function isProgressSummary(text) {
  const normalized = String(text || '').trim()
  if (!normalized) return true
  return normalized.endsWith('...') && !normalized.includes('\n') && normalized.length <= 90
}

function looksLikeRawJsonText(value) {
  const text = String(value || '').trim()
  if (!text || !['{', '['].includes(text[0])) return false
  try {
    JSON.parse(text)
    return true
  } catch {
    return false
  }
}

function isPlanLikeAnswer(value) {
  const normalized = String(value || '').trim().toLowerCase()
  if (!normalized) return false
  return (
    normalized.includes('executing the following plan') ||
    normalized.includes('risk summary:') ||
    normalized.includes('before executing') ||
    /^operators can\b/.test(normalized)
  )
}

function containsInternalText(value) {
  const text = String(value || '')
  return (
    text.includes('__') ||
    text.includes('{id}') ||
    /\b(IN_PROGRESS|DONE|NOT_STARTED|AMBIGUOUS)\b/.test(text) ||
    /\b(tool_name|validator_failed|planner_reentered|tool_rerun|trace id|args|result)\b/i.test(text)
  )
}

function isUserVisibleDetailText(value) {
  const text = String(value || '').trim()
  return Boolean(text) && !isProgressSummary(text) && !looksLikeRawJsonText(text) && !isPlanLikeAnswer(text) && !containsInternalText(text)
}

function dedupeLines(lines = []) {
  const seen = new Set()
  return lines.filter((line) => {
    const normalized = String(line || '').trim()
    if (!normalized || seen.has(normalized)) return false
    seen.add(normalized)
    return true
  })
}

function formatToolName(toolName) {
  return String(toolName || '')
    .replaceAll('_', ' ')
    .replaceAll('-', ' ')
    .trim()
}

function toDeveloperStatus(turn) {
  const terminalType = turn?.terminal?.event_type
  if (terminalType === 'session_completed') return 'Completed'
  if (terminalType === 'session_failed') return 'Failed'
  if (terminalType === 'session_blocked') return 'Blocked'

  const approval = Array.isArray(turn?.approvals) ? turn.approvals[turn.approvals.length - 1] : null
  if (approval?.event_type === 'approval_required') return 'Waiting for approval'

  const lastTool = Array.isArray(turn?.tools) ? turn.tools[turn.tools.length - 1] : null
  if (lastTool?.status === 'FAILED') return 'Request failed'
  if (lastTool?.status === 'DONE') return 'Request completed'
  if (lastTool) return 'Working'
  if (Array.isArray(turn?.thinking) && turn.thinking.length) return 'Thinking'
  return 'Working'
}

function toDeveloperResult(turn) {
  const lastTool = Array.isArray(turn?.tools) ? turn.tools[turn.tools.length - 1] : null
  const result = lastTool?.details?.result
  const lastError = lastTool?.details?.last_error

  if (result?.not_found) return '404 Not Found'
  if (typeof lastError === 'string' && lastError.trim()) return lastError.trim()
  if (typeof lastTool?.status === 'string' && lastTool.status.trim()) return lastTool.status.trim()
  if (turn?.terminal?.event_type === 'session_completed') return 'Completed'
  if (turn?.terminal?.event_type === 'session_failed') return 'Failed'
  if (turn?.terminal?.event_type === 'session_blocked') return 'Blocked'
  return null
}

function buildUserDetailLines(turn) {
  const thinking = Array.isArray(turn?.thinking) ? turn.thinking : []
  const tools = Array.isArray(turn?.tools) ? turn.tools : []
  const approvals = Array.isArray(turn?.approvals) ? turn.approvals : []
  const terminal = turn?.terminal || null

  const lines = []
  const planExplanation = thinking[thinking.length - 1]?.details?.plan_explanation || thinking[thinking.length - 1]?.content
  if (isUserVisibleDetailText(planExplanation)) {
    lines.push(planExplanation)
  }

  for (const tool of tools) {
    if (isUserVisibleDetailText(tool?.content)) {
      lines.push(tool.content)
    }
  }

  for (const approval of approvals) {
    if (approval?.content) lines.push(approval.content)
  }

  if (terminal?.details?.reason) lines.push(`Reason: ${terminal.details.reason}`)
  if (terminal?.details?.rejection_reason) lines.push(`Reason: ${terminal.details.rejection_reason}`)

  return dedupeLines(lines).slice(0, 4)
}

function buildDeveloperDetailLines(turn) {
  const lastTool = Array.isArray(turn?.tools) ? turn.tools[turn.tools.length - 1] : null
  const traceId = lastTool?.step_id || turn?.terminal?.id || turn?.id || null
  const toolLabel = formatToolName(lastTool?.tool_name)

  return dedupeLines([
    `Status: ${toDeveloperStatus(turn)}`,
    toolLabel ? `Tool: ${toolLabel}` : null,
    toDeveloperResult(turn) ? `Result: ${toDeveloperResult(turn)}` : null,
    traceId ? `Trace ID: ${traceId}` : null,
  ])
}

function renderCitationsAndBold(text, sources = []) {
  if (!text) return null

  // Handle bold
  const boldParts = text.split(/(\*\*.*?\*\*)/g)
  return boldParts.map((bPart, j) => {
    if (bPart.startsWith('**') && bPart.endsWith('**')) {
      return <strong key={j} className="font-semibold text-ink">{bPart.slice(2, -2)}</strong>
    }

    // Handle [^1] citations
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

function StreamedAssistantText({ text, streamKey, enabled, sources = [], onStreamComplete }) {
  const cleanText = useMemo(() => stripSourceFootnoteDefinitions(text), [text])
  const [displayed, setDisplayed] = useState(enabled ? '' : cleanText)
  const onStreamCompleteRef = useRef(onStreamComplete)
  onStreamCompleteRef.current = onStreamComplete

  useEffect(() => {
    const notifyComplete = () => {
      onStreamCompleteRef.current?.()
    }

    if (!enabled) {
      setDisplayed(cleanText)
      notifyComplete()
      return undefined
    }

    const tokens = String(cleanText || '').match(/\S+\s*/g) || []
    if (!tokens.length) {
      setDisplayed(cleanText)
      notifyComplete()
      return undefined
    }

    let index = 0
    let nextValue = ''
    setDisplayed('')

    const timer = window.setInterval(() => {
      if (index >= tokens.length) {
        window.clearInterval(timer)
        return
      }

      nextValue += tokens[index]
      index += 1
      setDisplayed(nextValue)

      if (index >= tokens.length) {
        window.clearInterval(timer)
        notifyComplete()
      }
    }, Number.isFinite(STREAM_BUFFER_MS) && STREAM_BUFFER_MS > 0 ? STREAM_BUFFER_MS : 40)

    return () => window.clearInterval(timer)
  }, [enabled, streamKey, cleanText])

  return <>{renderCitationsAndBold(displayed || (enabled ? '' : cleanText), sources)}</>
}

function useStagedAssistantSummary(rawSummary) {
  const initial = rawSummary || 'Working...'
  const [displayed, setDisplayed] = useState(initial)
  const displayedRef = useRef(initial)
  const lastDisplayedAtRef = useRef(Date.now())
  const timerRef = useRef(null)

  useEffect(() => {
    const next = rawSummary || 'Working...'
    if (next === displayedRef.current) return undefined

    if (timerRef.current) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }

    const minMs = Number.isFinite(PROGRESS_STAGE_MIN_MS) && PROGRESS_STAGE_MIN_MS > 0 ? PROGRESS_STAGE_MIN_MS : 0
    const shouldHold = isProgressSummary(displayedRef.current) || isProgressSummary(next)
    const elapsed = Date.now() - lastDisplayedAtRef.current
    const delay = shouldHold ? Math.max(0, minMs - elapsed) : 0

    timerRef.current = window.setTimeout(() => {
      displayedRef.current = next
      lastDisplayedAtRef.current = Date.now()
      setDisplayed(next)
      timerRef.current = null
    }, delay)

    return () => {
      if (timerRef.current) {
        window.clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [rawSummary])

  return displayed
}

/** Any LangGraph interrupt approval for a write bundle (not only while still PENDING). */
function turnHasLangGraphWriteBundle(turn) {
  const approvals = Array.isArray(turn?.approvals) ? turn.approvals : []
  return approvals.some((a) => String(a.tool_name || a.details?.tool?.name || '') === '__langgraph_commit__')
}

function tablePriorityColumnKey(presentation) {
  const cols = Array.isArray(presentation?.table?.columns) ? presentation.table.columns : []
  const hit = cols.find(
    (c) =>
      String(c.key || '')
        .toLowerCase()
        .includes('priority') ||
      String(c.label || '')
        .toLowerCase()
        .includes('priority'),
  )
  return hit?.key || null
}

function tablePriorityValues(presentation) {
  const key = tablePriorityColumnKey(presentation)
  if (!key) return []
  const rows = Array.isArray(presentation?.table?.rows) ? presentation.table.rows : []
  return rows.map((r) => String(r?.[key] || '').trim().toLowerCase()).filter(Boolean)
}

function interruptStyleSummary(summaryText) {
  const s = String(summaryText || '').toLowerCase()
  return s.includes('jobs affected:') || s.includes('current vs requested priority')
}

/** Snapshot table still all "low" while the bubble text is the approval bundle or claims high — hide. */
function targetPriorityFromSummary(summaryText) {
  const s = String(summaryText || '').toLowerCase()
  const match = s.match(/\bpriority\s+(?:set\s+)?(?:to|as)\s+(low|medium|high|urgent)\b/)
  if (match) return match[1]
  const compact = s.match(/\b(low|medium|high|urgent)-priority\b/)
  return compact ? compact[1] : null
}

function tableContradictsSummary(presentation, summaryText) {
  const values = tablePriorityValues(presentation)
  if (!values.length) return false
  const s = String(summaryText || '').toLowerCase()
  const target = targetPriorityFromSummary(summaryText)
  if (target && values.every((value) => value !== target)) return true
  if (interruptStyleSummary(summaryText)) return true
  return (
    /\bpriority\s+(?:set\s+)?(?:to|as)\s+(low|medium|high|urgent)\b/.test(s) ||
    (s.includes('high') && (s.includes('prior') || s.includes('priority')))
  )
}

function bundleFromDecidedApprovals(approvals, getStashed) {
  const decided = (Array.isArray(approvals) ? approvals : []).filter(
    (a) => a?.event_type === 'approval_decided' && a?.approval_id,
  )
  for (let i = decided.length - 1; i >= 0; i -= 1) {
    const row = decided[i]
    const fromRow = resolveApprovalTablePresentation(row)
    if (fromRow) return fromRow
    const stashed = getStashed(row.approval_id)
    if (stashed) return stashed
  }
  return null
}

/**
 * Latest table presentation for the turn. For LangGraph write bundles, list/GET snapshots often
 * still show pre-commit state (e.g. priority "low") while the narrative says "high" — hide those
 * until session completes, and after complete skip stale tables when a newer snapshot is absent.
 */
function bundleUiPresentationFromTurn(turn, pendingApproval, getStashedBundlePresentation) {
  const getStashed =
    typeof getStashedBundlePresentation === 'function' ? getStashedBundlePresentation : () => null
  if (pendingApproval) {
    const fromPending = resolveApprovalTablePresentation({
      event_type: 'approval_required',
      content: pendingApproval.risk_summary
        ? `Waiting for your approval: ${pendingApproval.risk_summary}`
        : '',
      risk_summary: pendingApproval.risk_summary,
      details: { args: pendingApproval.args || {} },
      args: pendingApproval.args,
    })
    if (fromPending) return fromPending
  }
  const approvals = Array.isArray(turn?.approvals) ? turn.approvals : []
  const completed = turn?.terminal?.event_type === 'session_completed'

  if (completed) {
    const fromDecided = bundleFromDecidedApprovals(approvals, getStashed)
    if (fromDecided) return fromDecided
    return null
  }

  if (approvals.some((a) => a?.event_type === 'approval_decided')) {
    const fromDecided = bundleFromDecidedApprovals(approvals, getStashed)
    if (fromDecided) return fromDecided
  }

  const reqs = approvals.filter((a) => a?.event_type === 'approval_required')
  for (let i = reqs.length - 1; i >= 0; i -= 1) {
    const row = reqs[i]
    const fromRow = resolveApprovalTablePresentation(row)
    if (fromRow) return fromRow
    const stashed = row?.approval_id ? getStashed(row.approval_id) : null
    if (stashed) return stashed
  }
  return null
}

function getLatestToolPresentation(turn) {
  const bundle = turnHasLangGraphWriteBundle(turn)
  const completed = turn?.terminal?.event_type === 'session_completed'
  if (bundle && !completed) {
    return null
  }

  const tools = Array.isArray(turn?.tools) ? turn.tools : []
  const summary = String(turn?.summary || '')
  for (let index = tools.length - 1; index >= 0; index -= 1) {
    const presentation = tools[index]?.details?.presentation
    if (presentation?.render_hint === 'table' && presentation?.table?.rows?.length) {
      if (bundle && completed && tableContradictsSummary(presentation, summary)) {
        continue
      }
      return presentation
    }
  }
  return null
}

function TurnDetails({ mode, turn }) {
  const lines = useMemo(
    () => (mode === 'dev' ? buildDeveloperDetailLines(turn) : buildUserDetailLines(turn)),
    [mode, turn],
  )

  if (!lines.length) return null

  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-xs font-medium text-ink-subtle">
        Show details
      </summary>
      <div className="mt-2 space-y-1 text-xs text-ink-subtle">
        {lines.map((line) => (
          <div key={line} className="whitespace-pre-wrap break-words">
            {line}
          </div>
        ))}
      </div>
    </details>
  )
}

function ConfirmationOptions({ turn, onConfirm, disabled }) {
  const [showOther, setShowOther] = useState(false)
  const latest = Array.isArray(turn?.confirmations) ? turn.confirmations[turn.confirmations.length - 1] : null
  const confirmation = latest?.details?.confirmation
  const primaryOptions = Array.isArray(confirmation?.options) ? confirmation.options : []
  const otherOptions = Array.isArray(confirmation?.other_possible_fields) ? confirmation.other_possible_fields : []

  if (!primaryOptions.length && !otherOptions.length) return null

  const renderOption = (option, variant = 'primary') => {
    const count = Number(option?.match_count)
    const countLabel = Number.isFinite(count) && count >= 0 ? ` · ${count} match${count === 1 ? '' : 'es'}` : ''
    const modeLabel = option?.match_mode ? ` · ${option.match_mode}` : ''
    const isOther = variant === 'other'
    return (
      <button
        key={`${variant}-${option.field}-${option.value}`}
        type="button"
        disabled={disabled}
        onClick={() => onConfirm(option)}
        className={`rounded-md border px-3 py-2 text-xs font-medium transition-colors disabled:opacity-60 ${isOther
          ? 'border-hairline bg-surface-2 text-ink-muted hover:bg-surface-3'
          : 'border-primary/30 bg-primary/10 text-primary hover:bg-primary/15'
          }`}
        title={option.reason || undefined}
      >
        {option.label || `${option.field}: ${option.value}`}
        {countLabel}
        {modeLabel}
      </button>
    )
  }

  return (
    <div className="mt-3 space-y-2">
      <div className="flex flex-wrap gap-2">
        {primaryOptions.map((option) => renderOption(option))}
      </div>
      {otherOptions.length > 0 && (
        <button
          type="button"
          onClick={() => setShowOther((prev) => !prev)}
          className="flex items-center gap-1 text-[11px] font-medium text-ink-subtle hover:text-primary dark:hover:text-primary transition-colors"
        >
          <span className="material-symbols-outlined text-sm">
            {showOther ? 'expand_less' : 'expand_more'}
          </span>
          {showOther ? 'Hide other possible fields' : `Other possible fields (${otherOptions.length})`}
        </button>
      )}
      {showOther && otherOptions.length > 0 && (
        <div className="flex flex-wrap gap-2 border-t border-hairline pt-2">
          {otherOptions.map((option) => renderOption(option, 'other'))}
        </div>
      )}
    </div>
  )
}


function AssistantTurnBubble({
  turn,
  timestamp,
  activitySteps,
  showApprovalCard,
  pendingApproval,
  getStashedBundlePresentation,
  approvalReason,
  setApprovalReason,
  decideApproval,
  decideConfirmation,
  isDecidingApproval,
  isSending,
  mode,
  shouldAnimateText,
  hideProgressSummary,
  showResumeBanner,
  session,
  isLatestTurn,
}) {
  const rawSummary = turn?.summary || 'Working...'
  const summary = useStagedAssistantSummary(rawSummary)
  const summaryIsProgress = isProgressSummary(summary)
  const answerAllowed = assistantAnswerAllowed({
    activityTimelineEnabled: ACTIVITY_TIMELINE_ENABLED,
    isLatestTurn,
    sessionStatus: session?.status,
    activitySteps,
    turn,
  })
  const showSummary = !(hideProgressSummary && summaryIsProgress) && answerAllowed
  const showDetails = showSummary && !summaryIsProgress
  const streamEnabled = shouldAnimateText && showDetails
  const [textStreamDone, setTextStreamDone] = useState(() => !streamEnabled)

  useLayoutEffect(() => {
    setTextStreamDone(!streamEnabled)
  }, [streamEnabled, summary, turn?.id])

  const handleAssistantTextStreamComplete = useCallback(() => {
    setTextStreamDone(true)
  }, [])

  const bundlePresentation = bundleUiPresentationFromTurn(turn, pendingApproval, getStashedBundlePresentation)
  const presentation = bundlePresentation || getLatestToolPresentation(turn)
  const tableAnimKey = `${turn?.id || 'turn'}:${presentation?.table?.total_rows || 0}:${summary}`
  // Collapse the bundle table only once the server confirms approval_decided in the
  // timeline. Do NOT use !pendingApproval — that can be optimistically null on click,
  // causing the <details> element to remount collapsed before the card even disappears.
  const hasServerDecidedApproval = Boolean(
    Array.isArray(turn?.approvals) &&
    turn.approvals.some((a) => a?.event_type === 'approval_decided'),
  )
  const collapseBundleTable = Boolean(presentation && hasServerDecidedApproval)

  return (
    <ChatMessage
      message=""
      isUser={false}
      timestamp={timestamp}
      sources={turn.sources}
      safetyContent={turn.safetyContent}
      showStreamGatedExtras={textStreamDone && answerAllowed}
      renderBlocks={() => (
        <>
          <ActivityTimeline steps={activitySteps} />
          {showResumeBanner ? (
            <div className="mb-2 rounded-md border border-primary/25 bg-primary/5 px-3 py-2 text-xs text-ink">
              Applying approved changes…
            </div>
          ) : null}
          {showSummary ? (
            <div className="whitespace-pre-wrap break-words text-ink">
              <StreamedAssistantText
                text={summary}
                streamKey={`${turn?.id || 'turn'}:${summary}`}
                enabled={streamEnabled}
                sources={turn.sources}
                onStreamComplete={handleAssistantTextStreamComplete}
              />
            </div>
          ) : null}
          {presentation && showDetails ? (
            <TablePresentation
              presentation={presentation}
              animate={shouldAnimateText && showDetails}
              animateKey={tableAnimKey}
              defaultCollapsed={collapseBundleTable}
            />
          ) : null}
          {showDetails && !showApprovalCard ? <TurnDetails mode={mode} turn={turn} /> : null}
          <ConfirmationOptions turn={turn} onConfirm={decideConfirmation} disabled={isSending} />
          {showApprovalCard ? (
            <div className="mt-3">
              <ApprovalCard
                approval={pendingApproval}
                mode={mode}
                reason={approvalReason}
                onReasonChange={setApprovalReason}
                onApprove={(args) => decideApproval('approve', args)}
                onReject={() => decideApproval('reject')}
                deciding={isDecidingApproval}
              />
            </div>
          ) : null}
        </>
      )}
    />
  )
}

function statusLoadingText(status) {
  if (status === FACTORY_AGENT_STATUS.PLANNING) return 'Understanding your request...'
  if (status === FACTORY_AGENT_STATUS.EXECUTING) return 'Gathering information...'
  if (status === FACTORY_AGENT_STATUS.WAITING_APPROVAL) return 'Waiting for approval...'
  if (status === FACTORY_AGENT_STATUS.WAITING_CONFIRMATION) return 'Waiting for confirmation...'
  return 'Working...'
}

const FactoryAgentChatPanel = ({ onClose, onHeaderMouseDown }) => {
  const chatRef = useRef(null)
  const shouldAutoScrollRef = useRef(true)
  const {
    session,
    messages,
    turns,
    activitySteps,
    sessionList,
    activeSessionName,
    input,
    setInput,
    loading,
    isSending,
    isCancelling,
    error,
    pendingApproval,
    approvalReason,
    messageMode,
    clientProgress,
    setApprovalReason,
    setMessageMode,
    isDecidingApproval,
    isPollingSession,
    getStashedBundlePresentation,
    isResumingAfterApproval,
    handleSend,
    handleCancel,
    decideApproval,
    decideConfirmation,
    startNewSession,
    switchSession,
    renameSession,
    deleteSession,
  } = useFactoryAgentChat()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [editingSessionId, setEditingSessionId] = useState(null)
  const [editingName, setEditingName] = useState('')
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [isDeletingSession, setIsDeletingSession] = useState(false)

  useEffect(() => {
    if (!chatRef.current) return
    if (!shouldAutoScrollRef.current) return
    chatRef.current.scrollTop = chatRef.current.scrollHeight
  }, [turns, messages, isSending, pendingApproval, session?.status])

  const handleChatScroll = () => {
    if (!chatRef.current) return
    const el = chatRef.current
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    shouldAutoScrollRef.current = distanceToBottom < 120
  }

  useEffect(() => {
    shouldAutoScrollRef.current = true
  }, [session?.session_id])

  const inputDisabled =
    isSending ||
    isDecidingApproval ||
    session?.status === FACTORY_AGENT_STATUS.PLANNING

  const showTopSessionProgress = Boolean(
    session?.session_id &&
    (isDecidingApproval ||
      isPollingSession ||
      isSending ||
      [
        FACTORY_AGENT_STATUS.PLANNING,
        FACTORY_AGENT_STATUS.EXECUTING,
        FACTORY_AGENT_STATUS.WAITING_APPROVAL,
        FACTORY_AGENT_STATUS.WAITING_CONFIRMATION,
      ].includes(session?.status)),
  )
  const canCancel = Boolean(session?.session_id) && [FACTORY_AGENT_STATUS.PLANNING, FACTORY_AGENT_STATUS.EXECUTING, FACTORY_AGENT_STATUS.WAITING_APPROVAL, FACTORY_AGENT_STATUS.WAITING_CONFIRMATION, FACTORY_AGENT_STATUS.BLOCKED].includes(session?.status)
  const mode = CHAT_VIEW_MODE === 'dev' ? 'dev' : 'user'

  let placeholder = 'Ask factory agent...'
  if (session?.status === FACTORY_AGENT_STATUS.PLANNING) placeholder = 'Planning in progress...'
  if (session?.status === FACTORY_AGENT_STATUS.EXECUTING) placeholder = 'Send a follow-up message for the next replan point...'
  if (session?.status === FACTORY_AGENT_STATUS.WAITING_APPROVAL) placeholder = 'Request a plan change while approval is pending...'
  const displayStatus = friendlySessionStatus(session?.status, isSending)

  return (
    <div className="flex h-full relative">
      {deleteTarget ? (
        <div
          className="absolute inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
          role="dialog"
          aria-modal="true"
          aria-label="Delete session confirmation"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !isDeletingSession) setDeleteTarget(null)
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
                  if (!isDeletingSession) setDeleteTarget(null)
                }}
                aria-label="Close"
              >
                <span className="material-symbols-outlined text-lg">close</span>
              </button>
            </div>

            <div className="mt-3 rounded-md border border-hairline bg-surface-2 px-3 py-2">
              <div className="text-xs font-semibold text-ink truncate">
                {deleteTarget.name || deleteTarget.session_id}
              </div>
              <div className="mt-0.5 text-[11px] text-ink-subtle">
                Session ID: {deleteTarget.session_id}
              </div>
            </div>

            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                disabled={isDeletingSession}
                className="px-3 py-1.5 rounded-md text-xs font-semibold bg-surface-2 text-ink hover:bg-surface-3 disabled:opacity-60"
                onClick={() => setDeleteTarget(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={isDeletingSession}
                className="px-3 py-1.5 rounded-md text-xs font-semibold bg-inverse-canvas text-inverse-ink hover:opacity-90 disabled:opacity-60"
                onClick={async () => {
                  setIsDeletingSession(true)
                  try {
                    const ok = await deleteSession(deleteTarget.session_id)
                    if (ok) setDeleteTarget(null)
                  } finally {
                    setIsDeletingSession(false)
                  }
                }}
              >
                {isDeletingSession ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      <aside
        className={`${sidebarCollapsed ? 'w-14' : 'w-72'} border-r border-hairline bg-surface-1 transition-all duration-200 flex flex-col`}
      >
        <div className="px-2.5 py-2 border-b border-hairline flex items-center gap-2">
          {!sidebarCollapsed ? (
            <>
              <button
                type="button"
                onClick={startNewSession}
                className="flex-1 px-2.5 py-2 rounded-md text-xs font-semibold bg-primary text-white hover:bg-primary-hover"
              >
                New Session
              </button>
              <button
                type="button"
                onClick={() => setSidebarCollapsed(true)}
                className="p-2 rounded-md hover:bg-surface-2 text-ink-subtle"
                aria-label="Collapse sessions"
              >
                <span className="material-symbols-outlined text-lg">left_panel_close</span>
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setSidebarCollapsed(false)}
              className="w-full p-2 rounded-md hover:bg-surface-2 text-ink-subtle"
              aria-label="Expand sessions"
            >
              <span className="material-symbols-outlined text-lg">left_panel_open</span>
            </button>
          )}
        </div>

        {!sidebarCollapsed ? (
          <div className="overflow-y-auto p-2 space-y-1">
            {sessionList.length === 0 ? (
              <div className="px-2 py-3 text-xs text-ink-subtle">
                No sessions yet.
              </div>
            ) : (
              sessionList.map((item) => {
                const isActive = item.session_id === session?.session_id
                const isEditing = editingSessionId === item.session_id
                return (
                  <div
                    key={item.session_id}
                    className={`group rounded-lg border transition-colors ${isActive
                      ? 'border-primary/50 bg-primary/[0.14] shadow-[inset_4px_0_0_0_#5e6ad2] ring-1 ring-inset ring-primary/20'
                      : 'border-transparent bg-transparent hover:border-hairline hover:bg-surface-2'
                      }`}
                  >
                    <button
                      type="button"
                      onClick={() => switchSession(item.session_id)}
                      className="w-full text-left px-2.5 py-2"
                    >
                      {isEditing ? (
                        <input
                          autoFocus
                          value={editingName}
                          onChange={(e) => setEditingName(e.target.value)}
                          onBlur={() => {
                            renameSession(item.session_id, editingName)
                            setEditingSessionId(null)
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              renameSession(item.session_id, editingName)
                              setEditingSessionId(null)
                            }
                            if (e.key === 'Escape') {
                              setEditingSessionId(null)
                            }
                          }}
                          className="w-full rounded-md border border-hairline bg-surface-2 px-2 py-1 text-sm text-ink outline-none focus:border-primary focus:ring-2 focus:ring-primary/30"
                        />
                      ) : (
                        <div className="flex items-start gap-2">
                          <div className="min-w-0 flex-1">
                            <div className={`truncate text-sm text-ink ${isActive ? 'font-semibold' : 'font-medium'}`}>
                              {item.name}
                            </div>
                            <div className="mt-0.5 text-[11px] uppercase tracking-wide text-ink-subtle">
                              {friendlySessionStatus(item.status)}
                            </div>
                          </div>
                          <span
                            role="button"
                            tabIndex={0}
                            onClick={(e) => {
                              e.preventDefault()
                              e.stopPropagation()
                              setEditingSessionId(item.session_id)
                              setEditingName(item.name || '')
                            }}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault()
                                e.stopPropagation()
                                setEditingSessionId(item.session_id)
                                setEditingName(item.name || '')
                              }
                            }}
                            className="material-symbols-outlined text-base text-ink-subtle opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-opacity"
                          >
                            edit
                          </span>
                          <span
                            role="button"
                            tabIndex={0}
                            onClick={(e) => {
                              e.preventDefault()
                              e.stopPropagation()
                              setDeleteTarget(item)
                            }}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault()
                                e.stopPropagation()
                                setDeleteTarget(item)
                              }
                            }}
                            className="material-symbols-outlined text-base text-ink-subtle opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-opacity"
                            aria-label="Delete session"
                            title="Delete session"
                          >
                            delete
                          </span>
                        </div>
                      )}
                    </button>
                  </div>
                )
              })
            )}
          </div>
        ) : null}
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center justify-between px-4 py-3 border-b border-hairline bg-surface-1">
          <div
            className="flex items-center gap-3 cursor-move select-none flex-1 min-w-0"
            onMouseDown={onHeaderMouseDown}
            data-drag-handle
            role="presentation"
          >
            <h2 className="text-lg font-semibold text-ink truncate">
              {activeSessionName || 'Factory Agent Chat'}
            </h2>
            <span className="flex items-center gap-1.5 rounded-full bg-surface-2 px-2 py-0.5 text-xs font-medium text-ink-subtle">
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
              {displayStatus}
            </span>
          </div>
          <div className="flex items-center gap-1">
            {onClose && (
              <button
                type="button"
                onClick={onClose}
                className="p-2 rounded-md hover:bg-surface-2 text-ink-subtle"
                aria-label="Close"
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            )}
          </div>
        </div>

        {showTopSessionProgress ? (
          <div
            className="h-1 w-full shrink-0 bg-primary/35 motion-safe:animate-pulse"
            role="status"
            aria-busy="true"
            aria-label={displayStatus}
          />
        ) : null}

        {error && (
          <div className="border-b border-hairline bg-surface-2 px-4 py-2 text-sm text-ink-muted">
            {error}
          </div>
        )}

        <div ref={chatRef} onScroll={handleChatScroll} className="flex-1 overflow-y-auto bg-canvas px-4 py-4">
          {loading && (turns?.length || 0) === 0 && messages.length === 0 ? (
            <div className="flex items-center justify-center h-32 text-ink-subtle text-sm">
              Loading...
            </div>
          ) : (turns?.length || 0) === 0 && messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center min-h-[200px] text-center px-4">
              <div className="w-14 h-14 rounded-full bg-primary/10 flex items-center justify-center mb-4">
                <span className="material-symbols-outlined text-3xl text-primary">smart_toy</span>
              </div>
              <p className="text-ink-muted text-sm font-medium">
                Start a session from the sidebar.
              </p>
              <p className="text-ink-subtle text-xs mt-1.5">
                Ask for operations tasks requiring safe approvals.
              </p>
              <div className="flex flex-wrap justify-center gap-2 mt-4">
                {[
                  'Show status for machine with machine id M-CNC-01',
                  'Find all low priority jobs',
                  'According to the LOTO procedure, what notification is required before starting lockout',
                ].map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() => handleSend(prompt)}
                    className="px-3 py-1.5 rounded-md border border-hairline bg-surface-1 text-xs font-medium text-ink-muted transition-colors hover:bg-surface-2"
                    disabled={inputDisabled}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {(turns || []).map((turn, index) => {
                const hasApprovalCard =
                  pendingApproval &&
                  !isResumingAfterApproval &&
                  session?.status === FACTORY_AGENT_STATUS.WAITING_APPROVAL &&
                  Array.isArray(turn.approvals) &&
                  turn.approvals.some((a) => a?.event_type === 'approval_required' && a?.approval_id === pendingApproval.approval_id)

                const userTs = turn.user?.created_at ? formatFactoryAgentTime(turn.user.created_at) : null
                const assistantTs = turn.created_at ? formatFactoryAgentTime(turn.created_at) : null
                const isLatestTurn = index === turns.length - 1
                const shouldAnimateText =
                  isLatestTurn &&
                  ![FACTORY_AGENT_STATUS.PLANNING, FACTORY_AGENT_STATUS.EXECUTING, FACTORY_AGENT_STATUS.WAITING_APPROVAL].includes(session?.status)
                const hideLegacyProgress = ACTIVITY_TIMELINE_ENABLED && isLatestTurn && isProgressSummary(turn?.summary)
                const latestActivitySteps = isLatestTurn ? activitySteps : []
                const shouldRenderAssistant =
                  !hideLegacyProgress || latestActivitySteps.length > 0 || hasApprovalCard
                const showResumeBanner =
                  isLatestTurn &&
                  isResumingAfterApproval &&
                  session?.status === FACTORY_AGENT_STATUS.EXECUTING &&
                  !hasApprovalCard

                return (
                  <Fragment key={turn.id}>
                    {turn.user?.content ? (
                      <ChatMessage message={turn.user.content} isUser timestamp={userTs} />
                    ) : null}
                    {shouldRenderAssistant ? (
                      <AssistantTurnBubble
                        turn={turn}
                        timestamp={assistantTs}
                        activitySteps={latestActivitySteps}
                        showApprovalCard={hasApprovalCard}
                        pendingApproval={pendingApproval}
                        getStashedBundlePresentation={getStashedBundlePresentation}
                        approvalReason={approvalReason}
                        setApprovalReason={setApprovalReason}
                        decideApproval={decideApproval}
                        decideConfirmation={decideConfirmation}
                        isDecidingApproval={isDecidingApproval}
                        isSending={isSending}
                        mode={mode}
                        shouldAnimateText={shouldAnimateText}
                        hideProgressSummary={hideLegacyProgress}
                        showResumeBanner={showResumeBanner}
                        session={session}
                        isLatestTurn={isLatestTurn}
                      />
                    ) : null}
                  </Fragment>
                )
              })}

              {messages
                .filter((m) => String(m.id || '').startsWith('optimistic-') && m.role === 'user')
                .map((m) => (
                  <ChatMessage key={m.id} message={m.content} isUser timestamp={m.timestamp} />
                ))}
            </>
          )}

          {isSending && (turns?.length || 0) === 0 && (
            <ChatMessage
              message={clientProgress?.content || statusLoadingText(session?.status)}
              isUser={false}
              timestamp={formatFactoryAgentTime(Date.now())}
            />
          )}
        </div>

        <form
          className="mx-4 mb-4 mt-2 flex flex-shrink-0 items-center gap-2 rounded-lg border border-hairline bg-surface-1 p-2.5"
          onSubmit={(e) => {
            e.preventDefault()
            handleSend()
          }}
        >
          <select
            value={messageMode}
            onChange={(e) => setMessageMode(e.target.value)}
            disabled={inputDisabled}
            className="h-11 rounded-md border border-hairline bg-surface-2 px-3 text-xs text-ink outline-none focus:border-primary focus:ring-2 focus:ring-primary/30"
            aria-label="Message mode"
          >
            <option value="normal">Normal</option>
            <option value="plan">Plan</option>
          </select>
          <textarea
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={placeholder}
            disabled={inputDisabled}
            className="flex-1 resize-none rounded-md border border-hairline bg-surface-2 px-4 py-2.5 text-sm text-ink outline-none placeholder:text-ink-tertiary focus:border-primary focus:ring-2 focus:ring-primary/30"
          />
          <button
            type={canCancel ? 'button' : 'submit'}
            onClick={canCancel ? handleCancel : undefined}
            disabled={canCancel ? isCancelling : inputDisabled || !input.trim()}
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
      </div>
    </div>
  )
}

export default FactoryAgentChatPanel
