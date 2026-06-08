import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import ChatMessage from '../ChatMessage'
import ApprovalCard from './ApprovalCard'
import ActivityTimeline from './ActivityTimeline'
import ClearAllChatsDialog from './ClearAllChatsDialog'
import DeleteSessionDialog from './DeleteSessionDialog'
import FactoryAgentChatComposer from './FactoryAgentChatComposer'
import FactoryAgentSessionSidebar from './FactoryAgentSessionSidebar'
import ResponseDocumentRenderer, { SourceDrawer } from './ResponseDocumentRenderer'
import { useFactoryAgentChat } from './useFactoryAgentChat'
import { FACTORY_AGENT_STATUS } from '../../../../services/factoryAgentApi'
import { compactInterruptApprovalHeadline, resolveApprovalTablePresentation } from './approvalInterruptDisplay.js'
import { TablePresentation } from '../turns/TurnBlocks'
import {
  assistantAnswerAllowed,
  friendlySessionStatus,
  truncateActivityAfterTerminal,
} from './activityTimelineUtils'
import {
  diagnosticFactsForPresentation,
  tablePresentationFromTypedPresentation,
} from './presentationContract.js'
import { normalizeResponseDocument } from './responseDocumentContract.js'
import {
  formatInlineCitationLabel,
  stripSourceFootnoteDefinitions,
} from '../sourceFormatting'
import { formatFactoryAgentTime } from './factoryAgentDisplayTime.js'
import RescheduleReviewModal from '../../scheduling/RescheduleReviewModal'

const CHAT_VIEW_MODE = (import.meta.env?.VITE_FACTORY_AGENT_CHAT_MODE || 'user').trim().toLowerCase() === 'dev' ? 'dev' : 'user'
const ACTIVITY_TIMELINE_ENABLED = !['0', 'false', 'off'].includes(
  String(import.meta.env?.VITE_FACTORY_AGENT_ACTIVITY_TIMELINE ?? 'true').trim().toLowerCase(),
)
const STREAM_BUFFER_MS = Number(import.meta.env?.VITE_FACTORY_AGENT_STREAM_BUFFER_MS || 40)
const PROGRESS_STAGE_MIN_MS = Number(import.meta.env?.VITE_FACTORY_AGENT_PROGRESS_STAGE_MIN_MS || 700)
const STARTER_PROMPTS = Object.freeze([
  'Read JOB-SEED-005. If it has a product, read the product too.',
  'Change planned low-priority jobs to medium priority, then show the id and status of the updated jobs.',
  'According to the LOTO procedure, what steps must workers complete before beginning service or maintenance?',
])

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
  lines.push(...diagnosticFactsForPresentation(turn?.presentation))
  const planExplanation = thinking[thinking.length - 1]?.details?.plan_explanation || thinking[thinking.length - 1]?.content
  if (isUserVisibleDetailText(planExplanation)) {
    lines.push(planExplanation)
  }

  for (const tool of tools) {
    if (isUserVisibleDetailText(tool?.content)) {
      lines.push(tool.content)
    }
  }

  const completed = terminal?.event_type === 'session_completed'
  for (const approval of approvals) {
    if (!approval?.content) continue
    if (completed && approvalWaitSummary(approval.content)) continue
    if (completed && /approved request to change record/i.test(approval.content)) continue
    lines.push(approval.content)
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

function approvalWaitSummary(summaryText) {
  const s = String(summaryText || '').toLowerCase()
  return (
    s.includes('waiting for your approval') ||
    s.includes('please approve') ||
    s.includes('will be updated from') ||
    s.includes('change list is shown')
  )
}

function completedVisibleSummary(turn, rawSummary) {
  if (turn?.terminal?.event_type !== 'session_completed' || !approvalWaitSummary(rawSummary)) {
    return rawSummary
  }
  return buildUserDetailLines(turn).find((line) => !approvalWaitSummary(line)) || rawSummary
}

function pendingApprovalVisibleSummary(approval) {
  if (!approval) return null
  const bundleUi = approval.args?.bundle_ui
  if (bundleUi && typeof bundleUi === 'object' && bundleUi.headline) {
    return String(bundleUi.headline)
  }
  const risk = String(approval.risk_summary || '').trim()
  const compact = compactInterruptApprovalHeadline(risk)
  if (compact) return compact
  if (risk) return risk
  return 'Waiting for approval.'
}

function pendingApprovalFromResponseDocument(document) {
  if (!document || document.state !== 'waiting_approval') return null
  const blocks = Array.isArray(document.blocks) ? document.blocks : []
  const block = [...blocks].reverse().find((item) => item?.type === 'approval_required' && item.approval_id)
  if (!block) return null
  const blockArgs = block.args && typeof block.args === 'object' ? block.args : {}
  const details = block.details && typeof block.details === 'object' ? block.details : {}
  const args = { ...blockArgs }
  for (const key of ['preview', 'selected_graph_tool_call', 'staged_graph_tool_calls', 'bundle_ui']) {
    if (args[key] == null && block[key] != null) args[key] = block[key]
  }
  if (args.preview_details == null && Object.keys(details).length > 0) args.preview_details = details
  const toolName =
    block.tool_name ||
    details.tool_name ||
    args.selected_graph_tool_call?.tool_name ||
    args.bundle_ui?.write_tool_name ||
    null
  return {
    approval_id: block.approval_id,
    operation_id: block.operation_id || document.operation_id || null,
    tool_name: toolName,
    risk_summary: block.summary || block.title || 'Review the proposed change before it is applied.',
    status: 'PENDING',
    ...(Object.keys(args).length > 0 ? { args } : {}),
  }
}

/** Snapshot table still all "low" while the bubble text is the approval bundle or claims high - hide. */
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
 * still show pre-commit state (e.g. priority "low") while the narrative says "high" - hide those
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

  if (completed) return null

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
  const typedPresentation = tablePresentationFromTypedPresentation(turn?.presentation)
  const typedKind = String(turn?.presentation?.kind || '')
  if (typedPresentation && ['mutation_result', 'partial_failure'].includes(typedKind)) {
    return typedPresentation
  }

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
      const answerFields = Array.isArray(tools[index]?.details?.answer_model?.fields)
        ? tools[index].details.answer_model.fields
        : []
      const tableColumns = new Set((presentation.table.columns || []).map((column) => String(column.key || column.label || '').toLowerCase()))
      const facts = answerFields
        .filter((field) => field?.label && field?.value != null)
        .filter((field) => !tableColumns.has(String(field.key || field.label || '').toLowerCase()))
        .map((field) => `${field.label}: ${field.value}`)
      if (!facts.length) return presentation
      return {
        ...presentation,
        analysis: {
          ...(presentation.analysis || {}),
          facts: [...(Array.isArray(presentation.analysis?.facts) ? presentation.analysis.facts : []), ...facts],
        },
      }
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
    const countLabel = Number.isFinite(count) && count >= 0 ? ` \u00b7 ${count} match${count === 1 ? '' : 'es'}` : ''
    const modeLabel = option?.match_mode ? ` \u00b7 ${option.match_mode}` : ''
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
  onOpenSourceEvidence,
  activeSourceEvidence,
}) {
  const responseDocumentResult = normalizeResponseDocument(turn?.responseDocument)
  const responseDocument = responseDocumentResult.document
  const hasResponseDocument = responseDocumentResult.status !== 'absent'
  const responseDocumentPendingApproval = pendingApprovalFromResponseDocument(responseDocument)
  const pendingApprovalMatchesResponseDocument =
    pendingApproval?.approval_id &&
    responseDocumentPendingApproval?.approval_id &&
    String(pendingApproval.approval_id) === String(responseDocumentPendingApproval.approval_id)
  const effectivePendingApproval =
    responseDocumentPendingApproval && !pendingApprovalMatchesResponseDocument
      ? responseDocumentPendingApproval
      : pendingApproval || responseDocumentPendingApproval
  const showResponseDocumentApprovalActions = Boolean(
    hasResponseDocument &&
    isLatestTurn &&
    effectivePendingApproval?.approval_id &&
    responseDocument?.state === 'waiting_approval',
  )
  const rawSummary = hasResponseDocument
    ? responseDocument?.message || responseDocument?.summary || 'Working...'
    : turn?.presentation
      ? completedVisibleSummary(turn, turn?.summary || 'Working...')
      : pendingApprovalVisibleSummary(pendingApproval) || completedVisibleSummary(turn, turn?.summary || 'Working...')
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

  const bundlePresentation = hasResponseDocument
    ? null
    : bundleUiPresentationFromTurn(turn, pendingApproval, getStashedBundlePresentation)
  const presentation = hasResponseDocument ? null : (bundlePresentation || getLatestToolPresentation(turn))
  const tableAnimKey = `${turn?.id || 'turn'}:${presentation?.table?.total_rows || 0}:${summary}`
  // Collapse the bundle table only once the server confirms approval_decided in the
  // timeline. Do NOT use !pendingApproval - that can be optimistically null on click,
  // causing the <details> element to remount collapsed before the card even disappears.
  const hasServerDecidedApproval = Boolean(
    Array.isArray(turn?.approvals) &&
    turn.approvals.some((a) => a?.event_type === 'approval_decided'),
  )
  const collapseBundleTable = Boolean(presentation && !pendingApproval && hasServerDecidedApproval)
  const chatSources = hasResponseDocument ? [] : turn.sources
  const chatSafetyContent = hasResponseDocument ? null : turn.safetyContent

  return (
    <ChatMessage
      message=""
      isUser={false}
      timestamp={timestamp}
      sources={chatSources}
      safetyContent={chatSafetyContent}
      showStreamGatedExtras={textStreamDone && answerAllowed}
      renderBlocks={() => (
        <>
          {hasResponseDocument ? (
            <ResponseDocumentRenderer
              document={responseDocument}
              liveActivitySteps={activitySteps}
              isLatestTurn={isLatestTurn}
              sessionStatus={session?.status}
              pendingApproval={effectivePendingApproval}
              showApprovalActions={showApprovalCard || showResponseDocumentApprovalActions}
              decideApproval={decideApproval}
              isDecidingApproval={isDecidingApproval}
              approvalReason={approvalReason}
              setApprovalReason={setApprovalReason}
              onOpenSourceEvidence={onOpenSourceEvidence}
              selectedSourceEvidence={activeSourceEvidence}
            />
          ) : (
            <>
              <ActivityTimeline steps={activitySteps} />
              {showResumeBanner ? (
                <div className="mb-2 rounded-md border border-primary/25 bg-primary/5 px-3 py-2 text-xs text-ink">
                  Applying approved changes{'\u2026'}
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
              {showDetails && !pendingApproval ? <TurnDetails mode={mode} turn={turn} /> : null}
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
  if (status === FACTORY_AGENT_STATUS.WAITING_USER_ACTION) return 'Waiting for your schedule decision...'
  return 'Working...'
}

function displayStatusFromActivity(steps, sessionStatus) {
  const activeStatuses = new Set([
    FACTORY_AGENT_STATUS.PLANNING,
    FACTORY_AGENT_STATUS.EXECUTING,
    FACTORY_AGENT_STATUS.WAITING_APPROVAL,
    FACTORY_AGENT_STATUS.WAITING_CONFIRMATION,
    FACTORY_AGENT_STATUS.WAITING_USER_ACTION,
  ])
  if (!activeStatuses.has(sessionStatus)) return null
  const rows = truncateActivityAfterTerminal(steps)
  const latest = rows[rows.length - 1]
  const label = String(latest?.label || '').trim()
  if (!label || label === 'Run complete') return null
  return label
}

function isBackendUnavailableError(error) {
  const text = String(error || '').toLowerCase()
  return (
    text.includes('cannot reach factory-agent') ||
    text.includes('cannot reach factory agent') ||
    text.includes('cannot connect to factory-agent') ||
    text.includes('service temporarily unavailable') ||
    text.includes('service unavailable') ||
    text.includes('factoryagentunavailable') ||
    text.includes('controlled release fault')
  )
}

function isTerminalAttentionStatus(status) {
  return status === FACTORY_AGENT_STATUS.FAILED || status === FACTORY_AGENT_STATUS.BLOCKED
}

function responseDocumentIsTerminal(document) {
  const state = String(document?.state || document?.status || '').toLowerCase()
  return ['blocked', 'failed', 'completed', 'cancelled', 'rejected', 'expired'].includes(state)
}

function latestTurnHasTerminalResponseDocument(turns = []) {
  const rows = Array.isArray(turns) ? turns : []
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const normalized = normalizeResponseDocument(rows[i]?.responseDocument)
    if (normalized.status === 'absent') continue
    return responseDocumentIsTerminal(normalized.document)
  }
  return false
}

function FactoryAgentDiagnostics({
  error,
  sessionStatus,
  streamDiagnostics = [],
  retrying,
  onRetryConnection,
  terminalResponseDocumentAvailable = false,
  runStarted = false,
}) {
  const diagnostics = Array.isArray(streamDiagnostics) ? streamDiagnostics.filter((item) => item?.message) : []
  const candidateError = terminalResponseDocumentAvailable ? null : error
  const backendUnavailable = isBackendUnavailableError(candidateError)
  const terminalAttention = !backendUnavailable && isTerminalAttentionStatus(sessionStatus)
  const visibleError = runStarted && !backendUnavailable && !terminalAttention ? null : candidateError
  if (!visibleError && diagnostics.length === 0) return null
  const title = backendUnavailable
    ? 'Factory Agent is disconnected'
    : terminalAttention
      ? 'Run needs attention'
      : 'Factory Agent chat could not start'
  const retryLabel = terminalAttention ? 'Refresh run status' : 'Try starting chat again'

  return (
    <div className="border-b border-hairline bg-surface-2 px-4 py-2 text-sm text-ink-muted">
      {visibleError ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="font-semibold text-ink">
              {title}
            </div>
            <div className="mt-0.5">{visibleError}</div>
          </div>
          {onRetryConnection ? (
            <button
              type="button"
              onClick={onRetryConnection}
              disabled={retrying}
              className="rounded-md border border-hairline bg-surface-1 px-2.5 py-1.5 text-xs font-semibold text-ink transition-colors hover:bg-surface-3 disabled:opacity-60"
            >
              {retrying ? 'Retrying...' : retryLabel}
            </button>
          ) : null}
        </div>
      ) : null}
      {diagnostics.length > 0 ? (
        <div className={error ? 'mt-2 space-y-1 border-t border-hairline pt-2' : 'space-y-1'}>
          {diagnostics.map((item) => (
            <div key={item.source} className="flex items-start gap-2 text-xs text-ink-subtle">
              <span className="material-symbols-outlined mt-0.5 text-sm">settings_input_antenna</span>
              <span>{item.message}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function FullscreenWindowIcon({ isFullscreen }) {
  return (
    <span
      className="material-symbols-outlined text-[13px] leading-none"
      aria-hidden="true"
      data-ai-assistant-fullscreen-icon={isFullscreen ? 'restore' : 'maximize'}
    >
      {isFullscreen ? 'filter_none' : 'check_box_outline_blank'}
    </span>
  )
}

function sourceEvidenceKey(evidence) {
  const source = evidence?.source || {}
  return [
    evidence?.documentId,
    evidence?.revision,
    source.source_id,
    source.doc_id,
    source.chunk_id,
    source.source_number,
    source.title,
  ]
    .map((value) => String(value ?? '').trim())
    .join('\u001f')
}

const FactoryAgentChatPanel = ({
  onClose,
  onHeaderMouseDown,
  isFullscreen = false,
  onToggleFullscreen,
  useChatState = useFactoryAgentChat,
}) => {
  const chatRef = useRef(null)
  const shouldAutoScrollRef = useRef(true)
  const sourceEvidenceAutoCollapsedSidebarRef = useRef(false)
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
    isRetryingConnection,
    error,
    streamDiagnostics,
    pendingApproval,
    pendingInteraction,
    approvalReason,
    clientProgress,
    setApprovalReason,
    isDecidingApproval,
    isDecidingInteraction,
    decidingInteractionDecision,
    getStashedBundlePresentation,
    isResumingAfterApproval,
    handleSend,
    handleCancel,
    retryConnection,
    decideApproval,
    decideInteraction,
    decideConfirmation,
    startNewSession,
    switchSession,
    renameSession,
    deleteSession,
    clearAllSessions,
  } = useChatState()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [editingSessionId, setEditingSessionId] = useState(null)
  const [editingName, setEditingName] = useState('')
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [isDeletingSession, setIsDeletingSession] = useState(false)
  const [clearAllChatsOpen, setClearAllChatsOpen] = useState(false)
  const [isClearingAllChats, setIsClearingAllChats] = useState(false)
  const [sourceEvidence, setSourceEvidence] = useState(null)
  const [sourceEvidencePdf, setSourceEvidencePdf] = useState(null)
  const activeSourceEvidence = useMemo(() => {
    if (!sourceEvidence) return null
    return sourceEvidence
  }, [sourceEvidence])
  const latestResponseDocumentKey = useMemo(() => {
    const turnWithDocument = [...(turns || [])].reverse().find((turn) => turn?.responseDocument)
    const document = turnWithDocument?.responseDocument
    if (!document) return null
    return `${document.document_id || document.id || turnWithDocument.id || 'response-document'}:${document.revision ?? 'unknown'}`
  }, [turns])

  const closeSourceEvidence = useCallback(() => {
    setSourceEvidence(null)
    setSourceEvidencePdf(null)
    if (sourceEvidenceAutoCollapsedSidebarRef.current) {
      sourceEvidenceAutoCollapsedSidebarRef.current = false
      setSidebarCollapsed(false)
    }
  }, [])

  const handleOpenSourceEvidence = useCallback((payload) => {
    if (!payload?.source) return
    const nextEvidence = {
      source: payload.source,
      sources: Array.isArray(payload.sources) ? payload.sources : [],
      documentId: payload.documentId || null,
      revision: payload.revision ?? null,
    }
    if (sourceEvidence && sourceEvidenceKey(sourceEvidence) === sourceEvidenceKey(nextEvidence)) {
      closeSourceEvidence()
      return
    }
    if (!sourceEvidence && !sidebarCollapsed) {
      sourceEvidenceAutoCollapsedSidebarRef.current = true
      setSidebarCollapsed(true)
    }
    setSourceEvidence(nextEvidence)
    setSourceEvidencePdf(null)
  }, [closeSourceEvidence, sidebarCollapsed, sourceEvidence])

  useEffect(() => {
    closeSourceEvidence()
  }, [closeSourceEvidence, latestResponseDocumentKey, session?.session_id])

  useEffect(() => {
    if (!chatRef.current) return
    if (!shouldAutoScrollRef.current) return
    chatRef.current.scrollTop = chatRef.current.scrollHeight
  }, [turns, messages, isSending, pendingApproval, pendingInteraction, session?.status])

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
    loading ||
    isSending ||
    isDecidingApproval ||
    isDecidingInteraction ||
    session?.status === FACTORY_AGENT_STATUS.PLANNING ||
    session?.status === FACTORY_AGENT_STATUS.WAITING_USER_ACTION
  const effectiveSessionStatus = pendingApproval
    ? FACTORY_AGENT_STATUS.WAITING_APPROVAL
    : session?.status
  const sessionShowsActiveProgress = [
    FACTORY_AGENT_STATUS.PLANNING,
    FACTORY_AGENT_STATUS.EXECUTING,
    FACTORY_AGENT_STATUS.WAITING_APPROVAL,
    FACTORY_AGENT_STATUS.WAITING_CONFIRMATION,
    FACTORY_AGENT_STATUS.WAITING_USER_ACTION,
  ].includes(effectiveSessionStatus)

  const showTopSessionProgress = Boolean(
    session?.session_id &&
    (isDecidingApproval ||
      isSending ||
      sessionShowsActiveProgress),
  )
  const terminalResponseDocumentAvailable = latestTurnHasTerminalResponseDocument(turns)
  const canCancel = Boolean(session?.session_id) &&
    sessionShowsActiveProgress &&
    effectiveSessionStatus !== FACTORY_AGENT_STATUS.WAITING_USER_ACTION &&
    !terminalResponseDocumentAvailable
  const mode = CHAT_VIEW_MODE === 'dev' ? 'dev' : 'user'

  let placeholder = 'Ask factory agent...'
  if (effectiveSessionStatus === FACTORY_AGENT_STATUS.PLANNING) placeholder = 'Planning in progress...'
  if (effectiveSessionStatus === FACTORY_AGENT_STATUS.EXECUTING) placeholder = 'Send a follow-up message for the next replan point...'
  if (effectiveSessionStatus === FACTORY_AGENT_STATUS.WAITING_APPROVAL) placeholder = 'Send a revision; pending approval stays open...'
  if (effectiveSessionStatus === FACTORY_AGENT_STATUS.WAITING_USER_ACTION) placeholder = 'Review the schedule window before continuing...'
  const displayStatus =
    displayStatusFromActivity(activitySteps, effectiveSessionStatus) ||
    friendlySessionStatus(effectiveSessionStatus, isSending)
  const showPendingInteractionModal =
    effectiveSessionStatus === FACTORY_AGENT_STATUS.WAITING_USER_ACTION &&
    pendingInteraction?.kind === 'reschedule_all_review'
  const runStartedWithProgress = Boolean(
    session?.session_id &&
    sessionShowsActiveProgress &&
    (
      (Array.isArray(activitySteps) && activitySteps.length > 0) ||
      (Array.isArray(turns) && turns.some((turn) => normalizeResponseDocument(turn?.responseDocument).status !== 'absent'))
    ),
  )

  return (
    <div className="flex h-full relative">
      <DeleteSessionDialog
        session={deleteTarget}
        deleting={isDeletingSession}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={async () => {
          setIsDeletingSession(true)
          try {
            const ok = await deleteSession(deleteTarget.session_id)
            if (ok) setDeleteTarget(null)
          } finally {
            setIsDeletingSession(false)
          }
        }}
      />
      <ClearAllChatsDialog
        open={clearAllChatsOpen}
        sessionCount={sessionList.length}
        clearing={isClearingAllChats}
        onCancel={() => setClearAllChatsOpen(false)}
        onConfirm={async () => {
          setIsClearingAllChats(true)
          try {
            const ok = await clearAllSessions()
            if (ok) setClearAllChatsOpen(false)
          } finally {
            setIsClearingAllChats(false)
          }
        }}
      />
      {showPendingInteractionModal ? (
        <RescheduleReviewModal
          interaction={pendingInteraction}
          layer="fixed"
          deciding={isDecidingInteraction}
          decidingAction={decidingInteractionDecision}
          onApply={(interaction, proposalIds) => decideInteraction('apply', interaction, proposalIds)}
          onCancel={(interaction) => decideInteraction('cancel', interaction)}
        />
      ) : null}
      <FactoryAgentSessionSidebar
        collapsed={sidebarCollapsed}
        onCollapsedChange={setSidebarCollapsed}
        sessions={sessionList}
        activeSessionId={session?.session_id}
        editingSessionId={editingSessionId}
        editingName={editingName}
        onEditingNameChange={setEditingName}
        onStartNewSession={startNewSession}
        onSwitchSession={switchSession}
        onStartEditing={(item) => {
          setEditingSessionId(item.session_id)
          setEditingName(item.name || '')
        }}
        onStopEditing={() => setEditingSessionId(null)}
        onRenameSession={renameSession}
        onDeleteSession={setDeleteTarget}
        onClearAllChats={() => setClearAllChatsOpen(true)}
        clearAllChatsDisabled={!sessionList.length || isClearingAllChats}
      />

      <div className="flex-1 flex flex-col min-w-0">
        <div
          className="flex h-14 shrink-0 items-center justify-between border-b border-hairline bg-surface-1 px-4 py-2"
          data-chatbot-topbar=""
        >
          <div
            className="flex items-center gap-3 cursor-move select-none flex-1 min-w-0"
            onMouseDown={onHeaderMouseDown}
            data-drag-handle
            role="presentation"
          >
            <h2 className="truncate text-base font-semibold text-ink">
              {activeSessionName || 'Factory Agent Chat'}
            </h2>
            <span className="flex items-center gap-1.5 rounded-full bg-surface-2 px-2 py-0.5 text-xs font-medium text-ink-subtle">
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
              {displayStatus}
            </span>
          </div>
          <div className="flex items-center gap-1">
            {onToggleFullscreen ? (
              <button
                type="button"
                onClick={onToggleFullscreen}
                className="inline-flex h-9 w-9 items-center justify-center rounded-md text-ink hover:bg-surface-2 focus:outline-none focus:ring-2 focus:ring-primary/30"
                aria-label={isFullscreen ? 'Exit full screen' : 'Full screen'}
                title={isFullscreen ? 'Exit full screen' : 'Full screen'}
                data-ai-assistant-fullscreen-toggle=""
                data-ai-assistant-fullscreen-state={isFullscreen ? 'fullscreen' : 'windowed'}
              >
                <FullscreenWindowIcon isFullscreen={isFullscreen} />
              </button>
            ) : null}
            {onClose && (
              <button
                type="button"
                onClick={onClose}
                className="inline-flex h-9 w-9 items-center justify-center rounded-md text-ink-subtle hover:bg-surface-2 focus:outline-none focus:ring-2 focus:ring-primary/30"
                aria-label="Close"
              >
                <span className="material-symbols-outlined text-[17px] leading-none">close</span>
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

        <FactoryAgentDiagnostics
          error={error}
          sessionStatus={effectiveSessionStatus}
          streamDiagnostics={streamDiagnostics}
          retrying={isRetryingConnection}
          onRetryConnection={retryConnection}
          terminalResponseDocumentAvailable={terminalResponseDocumentAvailable}
          runStarted={runStartedWithProgress}
        />

        <div className="flex min-h-0 flex-1 bg-canvas" data-chatbot-workspace="">
          <div className="flex min-w-0 flex-1 flex-col" data-chatbot-workspace-main="">
            <div ref={chatRef} onScroll={handleChatScroll} className="flex-1 overflow-y-auto px-4 py-4">
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
                {STARTER_PROMPTS.map((prompt) => (
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
                const isLatestTurn = index === turns.length - 1
                const turnOwnsPendingApproval = Boolean(
                  pendingApproval &&
                  (
                    (
                      Array.isArray(turn.approvals) &&
                      turn.approvals.some((a) => a?.event_type === 'approval_required' && a?.approval_id === pendingApproval.approval_id)
                    ) ||
                    isLatestTurn
                  ),
                )
                const pendingApprovalForTurn = turnOwnsPendingApproval ? pendingApproval : null
                const hasApprovalCard =
                  pendingApprovalForTurn &&
                  !isResumingAfterApproval &&
                  effectiveSessionStatus === FACTORY_AGENT_STATUS.WAITING_APPROVAL &&
                  turnOwnsPendingApproval

                const userTs = turn.user?.created_at ? formatFactoryAgentTime(turn.user.created_at) : null
                const assistantTs = turn.created_at ? formatFactoryAgentTime(turn.created_at) : null
                const shouldAnimateText =
                  isLatestTurn &&
                  ![FACTORY_AGENT_STATUS.PLANNING, FACTORY_AGENT_STATUS.EXECUTING, FACTORY_AGENT_STATUS.WAITING_APPROVAL].includes(effectiveSessionStatus)
                const hideLegacyProgress = ACTIVITY_TIMELINE_ENABLED && isLatestTurn && isProgressSummary(turn?.summary)
                const latestActivitySteps = isLatestTurn ? activitySteps : []
                const shouldRenderAssistant =
                  turn?.responseDocument != null || !hideLegacyProgress || latestActivitySteps.length > 0 || hasApprovalCard
                const showResumeBanner =
                  isLatestTurn &&
                  isResumingAfterApproval &&
                  effectiveSessionStatus === FACTORY_AGENT_STATUS.EXECUTING &&
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
                        pendingApproval={pendingApprovalForTurn}
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
                        onOpenSourceEvidence={handleOpenSourceEvidence}
                        activeSourceEvidence={activeSourceEvidence}
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
              {messages
                .filter((m) => String(m.id || '').startsWith('optimistic-') && m.role !== 'user')
                .map((m) => (
                  <ChatMessage key={m.id} message={m.content} isUser={false} timestamp={m.timestamp} />
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

            <FactoryAgentChatComposer
              input={input}
              onInputChange={setInput}
              disabled={inputDisabled}
              placeholder={placeholder}
              canCancel={canCancel}
              isCancelling={isCancelling}
              isSending={isSending}
              onCancel={handleCancel}
              onSend={handleSend}
            />
          </div>
          <SourceDrawer
            source={sourceEvidence?.source}
            sources={sourceEvidence?.sources || []}
            pdfSource={sourceEvidencePdf}
            onOpenPdf={setSourceEvidencePdf}
            onBack={() => setSourceEvidencePdf(null)}
            onClose={closeSourceEvidence}
          />
        </div>
      </div>
    </div>
  )
}

export default FactoryAgentChatPanel
