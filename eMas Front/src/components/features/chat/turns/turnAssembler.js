import { compactInterruptApprovalHeadline } from '../factory-agent/approvalInterruptDisplay.js'

export const getReadableAction = (toolName) => {
  const raw = String(toolName || '').trim()
  const lower = raw.toLowerCase()
  if (!lower) return 'Processing'
  if (lower.startsWith('get')) return 'Finding'
  if (lower.startsWith('list')) return 'Finding'
  if (lower.startsWith('post') || lower.startsWith('create')) return 'Creating'
  if (lower.startsWith('put') || lower.startsWith('patch') || lower.startsWith('update')) return 'Updating'
  if (lower.startsWith('delete') || lower.startsWith('remove')) return 'Deleting'
  return 'Processing'
}

const safeStr = (v) => (v == null ? '' : String(v))

function isGenericProgressText(value) {
  const normalized = String(value || '').trim().toLowerCase()
  return (
    !normalized ||
    normalized === 'tool started.' ||
    normalized === 'step started.' ||
    normalized === 'execution started.' ||
    normalized === 'execution completed successfully.' ||
    /^[-\w{}]+ completed\.$/.test(normalized)
  )
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

function readableToolTarget(toolName) {
  const parts = String(toolName || '')
    .replace(/\{.*?\}/g, '')
    .split('__')
    .pop()
    .replaceAll('_', ' ')
    .replaceAll('-', ' ')
    .trim()
  if (!parts) return 'records'
  return parts
}

function parseJsonObject(value) {
  try {
    const parsed = JSON.parse(String(value || ''))
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null
  } catch {
    return null
  }
}

function toolEntityLabel(toolName, plural) {
  let cleaned = String(toolName || 'records').replace(/__+/g, '_')
  cleaned = cleaned.includes('_') ? cleaned.split('_').slice(1).join('_') : cleaned
  cleaned = cleaned
    .replace(/\{id\}/g, '')
    .replace(/_id\b/g, '')
    .replace(/^[_\-\s/{}]+|[_\-\s/{}]+$/g, '')
  let noun = (cleaned || 'record').split('_')[0].replaceAll('-', ' ')
  if (plural && !noun.endsWith('s')) noun = `${noun}s`
  if (!plural && noun.endsWith('s')) noun = noun.slice(0, -1)
  return noun || (plural ? 'records' : 'record')
}

function resultRows(result) {
  if (!result || typeof result !== 'object') return []
  for (const key of ['data', 'items']) {
    if (Array.isArray(result[key])) {
      return result[key].filter((row) => row && typeof row === 'object' && !Array.isArray(row))
    }
  }
  return []
}

function resultHasEmptyRows(result) {
  if (!result || typeof result !== 'object') return false
  return ['data', 'items'].some((key) => Array.isArray(result[key]) && result[key].length === 0)
}

function idValues(rows, limit = 6) {
  const ids = []
  for (const row of rows) {
    for (const [key, value] of Object.entries(row || {})) {
      const normalized = String(key || '').toLowerCase().replaceAll('-', '_')
      if ((normalized === 'id' || normalized.endsWith('_id')) && value != null && value !== '') {
        ids.push(String(value))
        break
      }
    }
    if (ids.length >= limit) break
  }
  return ids
}

function filterPhrase(args, noun) {
  const payload = args && typeof args === 'object' ? args : {}
  const parts = []
  if (payload.priority != null && payload.priority !== '') parts.push(`${payload.priority}-priority`)
  if (payload.status != null && payload.status !== '') parts.push(String(payload.status))
  parts.push(noun)
  return parts.join(' ')
}

function toolResultObject(tool) {
  const detailResult = tool?.details?.result
  if (detailResult && typeof detailResult === 'object' && !Array.isArray(detailResult)) return detailResult
  return parseJsonObject(tool?.content)
}

function summarizeToolResult(tool) {
  if (!tool) return null
  const result = toolResultObject(tool)
  const rows = resultRows(result)
  const presentationRows = Array.isArray(tool?.details?.presentation?.table?.rows)
    ? tool.details.presentation.table.rows.filter((row) => row && typeof row === 'object' && !Array.isArray(row))
    : []
  const displayRows = rows.length ? rows : presentationRows
  const args = tool?.details?.args

  if (displayRows.length) {
    const noun = toolEntityLabel(tool.tool_name, displayRows.length !== 1)
    const descriptor = filterPhrase(args, noun)
    const ids = idValues(displayRows)
    if (ids.length) {
      const suffix = displayRows.length > ids.length ? `, +${displayRows.length - ids.length} more` : ''
      return `Found ${displayRows.length} ${descriptor}: ${ids.join(', ')}${suffix}. Details are shown in the table below.`
    }
    return `Found ${displayRows.length} ${descriptor}. Details are shown in the table below.`
  }

  if (resultHasEmptyRows(result)) {
    return `No ${filterPhrase(args, toolEntityLabel(tool.tool_name, true))} matched.`
  }

  if (result?.not_found) {
    const text = result._summary || result.detail || 'Requested resource was not found.'
    return String(text).trim() || null
  }

  for (const key of ['_summary', 'summary', 'message', 'detail', 'status']) {
    const value = result?.[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }

  const content = String(tool?.content || '').trim()
  if (content && !isGenericProgressText(content) && !looksLikeRawJsonText(content) && !isPlanLikeAnswer(content)) {
    return content
  }
  return null
}

function latestToolSummary(turn) {
  const tools = Array.isArray(turn?.tools) ? turn.tools : []
  for (let i = tools.length - 1; i >= 0; i -= 1) {
    const summary = summarizeToolResult(tools[i])
    if (summary) return summary
  }
  return null
}

function latestPlanForAnswer(turn) {
  const thinking = Array.isArray(turn?.thinking) ? turn.thinking : []
  if (!thinking.length) return null
  for (let i = thinking.length - 1; i >= 0; i -= 1) {
    const row = thinking[i]
    const status = String(row?.details?.status || row?.status || '').toUpperCase()
    if (status === 'COMPLETED') return row
  }
  return thinking[thinking.length - 1]
}

function nonGenericToolLines(turn) {
  const tools = Array.isArray(turn?.tools) ? turn.tools : []
  return tools
    .map((t) => (t?.content ? String(t.content).trim() : ''))
    .filter(Boolean)
    .filter((line, idx, lines) => lines.indexOf(line) === idx)
    .filter((line) => !isGenericProgressText(line))
    .filter((line) => !looksLikeRawJsonText(line))
    .filter((line) => !isPlanLikeAnswer(line))
}

function pickLatestTurnIdByTime(userEvents, atIso) {
  if (!userEvents.length) return null
  if (!atIso) return userEvents[userEvents.length - 1].turn_id || userEvents[userEvents.length - 1].event_id || null
  const at = new Date(atIso).getTime()
  if (!Number.isFinite(at)) return userEvents[userEvents.length - 1].turn_id || userEvents[userEvents.length - 1].event_id || null
  let selected = null
  for (const e of userEvents) {
    const t = new Date(e.created_at).getTime()
    if (!Number.isFinite(t)) continue
    if (t <= at) selected = e
    else break
  }
  const fallback = selected || userEvents[userEvents.length - 1]
  return fallback.turn_id || fallback.event_id || null
}

export function assembleFactoryAgentTurns(timeline = []) {
  const events = Array.isArray(timeline) ? timeline : []
  const userEvents = events.filter((e) => e?.event_type === 'user_message')

  const turnsById = new Map()
  const toolBlocksByKey = new Map()
  const getOrCreateTurn = (turnId, createdAt) => {
    const key = turnId || `turn:${createdAt || 'unknown'}:${Math.random().toString(36).slice(2, 8)}`
    const existing = turnsById.get(key)
    if (existing) return existing
    const next = {
      id: key,
      created_at: createdAt || null,
      user: null,
      thinking: [],
      tools: [],
      approvals: [],
      confirmations: [],
      status: [],
      terminal: null,
      debug: [],
      sources: [],
      safetyContent: null,
    }
    turnsById.set(key, next)
    return next
  }

  const upsertToolBlock = (turn, e, patch) => {
    const stepId = e.step_id || e.stepId || (e.details && e.details.step_id) || null
    const key = `${turn.id}:${stepId || e.event_id || e.id}`
    const existing = toolBlocksByKey.get(key) || null
    if (existing) {
      Object.assign(existing, patch)
      return
    }
    const next = { ...patch }
    turn.tools.push(next)
    toolBlocksByKey.set(key, next)
  }

  for (const e of events) {
    if (!e) continue
    const turnId =
      e.turn_id ||
      (e.event_type === 'user_message'
        ? (e.event_id || e.id)
        : pickLatestTurnIdByTime(userEvents, e.created_at))
    const turn = getOrCreateTurn(turnId, e.created_at)

    if (e.event_type === 'user_message') {
      turn.user = {
        id: e.event_id || e.id,
        content: e.content,
        created_at: e.created_at,
      }
      continue
    }

    if (e.event_type === 'plan_created') {
      turn.thinking.push({
        id: e.event_id || e.id,
        content: e.content,
        created_at: e.created_at,
        details: e.details || null,
      })
      if (e.details?.sources) turn.sources = e.details.sources
      if (e.details?.safety_content) turn.safetyContent = e.details.safety_content
      continue
    }

    if (e.event_type === 'tool_started') {
      upsertToolBlock(turn, e, {
        id: e.step_id || e.event_id || e.id,
        step_id: e.step_id || null,
        tool_name: e.tool_name,
        action: getReadableAction(e.tool_name),
        status: e.status || 'IN_PROGRESS',
        content: e.content,
        created_at: e.created_at,
        details: e.details || null,
      })
      continue
    }

    if (e.event_type === 'tool_result') {
      upsertToolBlock(turn, e, {
        id: e.step_id || e.event_id || e.id,
        step_id: e.step_id || null,
        tool_name: e.tool_name,
        action: getReadableAction(e.tool_name),
        status: e.status || null,
        content: e.content,
        created_at: e.created_at,
        details: e.details || null,
      })
      continue
    }

    if (e.event_type === 'approval_required' || e.event_type === 'approval_decided') {
      turn.approvals.push({
        id: e.event_id || e.id,
        event_type: e.event_type,
        tool_name: e.tool_name,
        approval_id: e.approval_id,
        step_id: e.step_id,
        status: e.status || null,
        content: e.content,
        created_at: e.created_at,
        details: e.details || null,
      })
      continue
    }

    if (e.event_type === 'confirmation_required' || e.event_type === 'confirmation_decided') {
      turn.confirmations.push({
        id: e.event_id || e.id,
        event_type: e.event_type,
        status: e.status || null,
        content: e.content,
        created_at: e.created_at,
        details: e.details || null,
      })
      continue
    }

    if (['execution_started', 'replan_requested', 'session_blocked', 'session_failed', 'session_completed'].includes(e.event_type)) {
      const item = {
        id: e.event_id || e.id,
        event_type: e.event_type,
        content: e.content,
        created_at: e.created_at,
        status: e.status || null,
        details: e.details || null,
      }
      turn.status.push(item)
      if (e.event_type === 'session_blocked' || e.event_type === 'session_failed' || e.event_type === 'session_completed') {
        turn.terminal = item
      }
      // RAG conversation replies surface their citations on the
      // session_completed event (the underlying no-op plan is filtered out
      // of the timeline by the backend).
      if (e.event_type === 'session_completed') {
        const detailSources = Array.isArray(e.details?.sources) ? e.details.sources : null
        if (detailSources && detailSources.length && (!turn.sources || turn.sources.length === 0)) {
          turn.sources = detailSources
        }
        if (e.details?.safety_content && !turn.safetyContent) {
          turn.safetyContent = e.details.safety_content
        }
      }
      continue
    }

    turn.debug.push(e)
  }

  const turns = Array.from(turnsById.values()).map(turn => {
    // Inject legacy-compatible structure for AiChatPanel / mergeLegacyAssistantTurnContent
    const lastThinking = turn.thinking?.[turn.thinking.length - 1]
    const content = turn.terminal?.content || lastThinking?.content || ""
    
    turn.assistants = [{
      content: content,
      sources: turn.sources || [],
      safetyContent: turn.safetyContent || null,
      blocks: [],
      timestamp: turn.terminal?.created_at || lastThinking?.created_at || turn.created_at
    }]
    return turn
  })

  turns.sort((a, b) => safeStr(a.user?.created_at || a.created_at).localeCompare(safeStr(b.user?.created_at || b.created_at)))

  return turns
}

/** Remove approval-wait copy that can leak into the completed-session bubble. */
function stripApprovalWaitPhrases(text) {
  if (!text || typeof text !== 'string') return text
  if (!/please approve|waiting for your approval/i.test(text)) return text
  const lines = text.split('\n')
  const kept = lines.filter((line) => {
    const t = line.trim().toLowerCase()
    if (!t) return true
    if (t.startsWith('please approve')) return false
    if (t.startsWith('waiting for your approval')) return false
    if (t === 'please approve to continue.' || t === 'please approve to continue') return false
    return true
  })
  return kept.join('\n').replace(/\n{3,}/g, '\n\n').trim() || text
}

export function computeFactoryAgentTurnSummary(turn) {
  if (!turn) return 'Working...'

  const toTs = (value) => {
    const ts = Date.parse(value || '')
    return Number.isFinite(ts) ? ts : -Infinity
  }

  const lastApproval = Array.isArray(turn.approvals) ? turn.approvals[turn.approvals.length - 1] : null
  const lastConfirmation = Array.isArray(turn.confirmations) ? turn.confirmations[turn.confirmations.length - 1] : null
  const lastTool = Array.isArray(turn.tools) ? turn.tools[turn.tools.length - 1] : null
  const terminal = turn.terminal || null
  const toolSummary = latestToolSummary(turn)
  const approvalTs = toTs(lastApproval?.created_at)
  const confirmationTs = toTs(lastConfirmation?.created_at)
  const latestProgressTs = Math.max(toTs(lastTool?.created_at), toTs(terminal?.created_at))
  const waitingOnApproval = latestProgressTs <= approvalTs
  const waitingOnConfirmation = latestProgressTs <= confirmationTs

  if (lastConfirmation?.event_type === 'confirmation_required' && waitingOnConfirmation) {
    return lastConfirmation.content || 'Please confirm the filter.'
  }

  // Terminal outcomes before approval heuristics: `waitingOnApproval` stays true after approve
  // when tool/checkpoint timestamps precede `approval_decided`, which wrongly surfaced
  // interrupt-era "Please approve…" copy even after `session_completed`.
  if (terminal?.event_type === 'session_blocked' || terminal?.event_type === 'session_failed') {
    return terminal.content || lastTool?.content || 'Execution stopped.'
  }
  if (terminal?.event_type === 'session_completed') {
    const lastPlan = latestPlanForAnswer(turn)

    // RAG / Conversation Support: If no tools were executed, the plan explanation IS the answer.
    if (lastPlan?.content && (!turn.tools || turn.tools.length === 0)) {
      return stripApprovalWaitPhrases(lastPlan.content)
    }

    // Prefer the last tool result when completion is a generic status line.
    const isGenericComplete = String(terminal.content || '').toLowerCase().includes('execution completed successfully')
    const terminalIsPlanLike = isPlanLikeAnswer(terminal.content) || looksLikeRawJsonText(terminal.content)
    if (isGenericComplete || terminalIsPlanLike) {
      if (toolSummary) return stripApprovalWaitPhrases(toolSummary)
      const deduped = nonGenericToolLines(turn)
      if (deduped.length >= 2) return stripApprovalWaitPhrases(deduped.join('\n'))
      if (deduped.length === 1) return stripApprovalWaitPhrases(deduped[0])
      if (lastPlan?.content && !isPlanLikeAnswer(lastPlan.content)) {
        return stripApprovalWaitPhrases(lastPlan.content)
      }
      if (lastTool?.content) return stripApprovalWaitPhrases(lastTool.content)
    }
    return stripApprovalWaitPhrases(terminal.content || 'Execution completed.')
  }

  if (lastApproval?.event_type === 'approval_required' && waitingOnApproval) {
    const bui = lastApproval.details?.args?.bundle_ui
    if (bui && typeof bui === 'object' && bui.headline) return String(bui.headline)
    const raw = lastApproval.content || ''
    const compact = compactInterruptApprovalHeadline(raw)
    if (compact) return compact
    return raw || 'Waiting for approval.'
  }
  if (lastApproval?.event_type === 'approval_decided' && waitingOnApproval) {
    return lastApproval.content || (String(lastApproval.status || '').toUpperCase() === 'REJECTED' ? 'Approval rejected.' : 'Approval decided.')
  }

  const lastPlan = latestPlanForAnswer(turn)
  const planIsCompleted = String(lastPlan?.details?.status || '').toUpperCase() === 'COMPLETED'
  const lastToolDone = String(lastTool?.status || '').toUpperCase() === 'DONE'
  
  // LangGraph snapshots can briefly or historically have a completed plan
  // without a terminal event. In that shape the plan summary is the answer.
  if (lastPlan?.content && planIsCompleted && lastToolDone) {
    const lc = String(lastPlan.content).toLowerCase()
    const looksLikeInterruptBundle =
      lc.includes('jobs affected:') ||
      lc.includes('current vs requested priority') ||
      (lc.includes('from low') && lc.includes('high'))
    if (looksLikeInterruptBundle && toolSummary) {
      return stripApprovalWaitPhrases(toolSummary)
    }
    if (looksLikeInterruptBundle && !toolSummary) {
      const deduped = nonGenericToolLines(turn)
      if (deduped.length) return stripApprovalWaitPhrases(deduped.join('\n'))
    }
    if ((isPlanLikeAnswer(lastPlan.content) || looksLikeRawJsonText(lastPlan.content)) && toolSummary) {
      return stripApprovalWaitPhrases(toolSummary)
    }
    return stripApprovalWaitPhrases(lastPlan.content)
  }
  if (lastPlan?.content && planIsCompleted && !lastTool && (!turn.status || turn.status.length === 0)) {
    return stripApprovalWaitPhrases(lastPlan.content)
  }

  if (lastToolDone && toolSummary) return stripApprovalWaitPhrases(toolSummary)
  if (lastTool || turn.status?.length) {
    const label = readableToolTarget(lastTool?.tool_name)
    const action = lastTool?.action || getReadableAction(lastTool?.tool_name)
    return `${action} ${label}...`
  }
  if (lastPlan?.content) return 'Understanding your request...'
  if (turn.user?.content) return 'Understanding your request...'

  return 'Working...'
}

export function assembleLegacyTurns(messages = []) {
  const rows = Array.isArray(messages) ? messages : []
  const turns = []
  let current = null

  const startTurn = (userMsg) => {
    current = {
      id: userMsg?.turnId || userMsg?.id || `turn:${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      user: userMsg || null,
      assistants: [],
    }
    turns.push(current)
  }

  for (const m of rows) {
    if (!m) continue
    if (m.role === 'user') {
      startTurn(m)
      continue
    }
    if (!current) startTurn(null)
    current.assistants.push(m)
  }

  return turns
}

export function mergeLegacyAssistantTurnContent(turn) {
  const assistants = Array.isArray(turn?.assistants) ? turn.assistants : []
  const primary = assistants.find((a) => a?.content) || assistants[0] || null
  if (!primary) return { content: '', blocks: [] }

  const blocks = []

  // Thinking (intent/confidence/entities/BDI) is hidden by default; surfaced as a collapsible.
  const thinkingPayload = {
    intent: primary.intent,
    confidence: primary.confidence,
    ambiguous: primary.ambiguous,
    clarifications: primary.clarifications,
    bdi_result: primary.bdi_result,
  }
  blocks.push({ type: 'thinking', title: 'Thinking', payload: thinkingPayload })

  const toolBlocks = []
  for (const a of assistants) {
    const calls = a?.suggested_calls || a?.suggestedCalls || []
    for (const call of calls) {
      toolBlocks.push({
        type: 'tool_call',
        title: call?.purpose || `${call?.method || 'GET'} ${call?.path || ''}`,
        tool_name: call?.path,
        action: getReadableAction(call?.method || ''),
        status: call?.requires_approval ? 'PENDING_APPROVAL' : 'SUGGESTED',
        payload: call,
      })
    }

    const execBlocks = Array.isArray(a?.tool_blocks) ? a.tool_blocks : []
    for (const b of execBlocks) {
      if (b?.kind !== 'tool') continue
      toolBlocks.push({
        type: 'tool_call',
        title: b?.call?.purpose || `${b?.call?.method || 'GET'} ${b?.call?.path || ''}`,
        tool_name: b?.call?.path,
        action: getReadableAction(b?.call?.method || ''),
        status: b?.status || 'DONE',
        payload: { call: b.call, status: b.status, result: b.result, error: b.error },
      })
    }
  }
  if (toolBlocks.length) blocks.push(...toolBlocks)

  return { 
    content: primary.content || '', 
    blocks,
    sources: primary.sources || [],
    safetyContent: primary.safetyContent || null
  }
}
