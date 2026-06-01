import http from 'node:http'
import { randomUUID } from 'node:crypto'
import {
  activityStreamForScenario,
  createNormalUseHistorySession,
  createScenarioSession,
  getScenario,
  mockTools,
  notificationStreamForScenario,
  resolveScenarioForPrompt,
  scenarioNames,
  summarizeScenarioSession,
} from './fixtureStore.js'
import { normalUseHistoryFixtures } from '../support/normalUseScenarios.js'
import {
  securityAuthFailureTargetAnswer,
  securityCrossSessionLeakApproval,
  securityCrossSessionLeakAudit,
  securityCrossSessionLeakFinal,
  securityCrossSessionLeakHidden,
  securityCrossSessionLeakSource,
  securityOtherUserSecret,
  securitySafeOwnAnswer,
  securityTamperSessionName,
  securityUnsafeActionBlocked,
} from '../support/securityScenarios.js'

const args = new Map()
for (let i = 2; i < process.argv.length; i += 2) {
  args.set(process.argv[i], process.argv[i + 1])
}

const port = Number(args.get('--port') || process.env.PORT || 8015)
const sessions = new Map()
let requestLog = []
let connectionLog = []
let sseFrameLog = []

function now() {
  return new Date().toISOString()
}

function nowPlus(ms) {
  return new Date(Date.now() + ms).toISOString()
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

function writeSseHeaders(res) {
  res.writeHead(200, {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-User-Id',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, OPTIONS',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
    'Content-Type': 'text/event-stream',
  })
}

function sendSseEvent(res, event, data, id = 1) {
  res.write(`id: ${id}\n`)
  res.write(`event: ${event}\n`)
  res.write(`data: ${JSON.stringify(data)}\n\n`)
}

function sendRawSseFrame(res, raw) {
  res.write(`${raw}\n\n`)
}

function logConnection({ req, url, event, connectionId, sessionId, scenarioName = null, stream, status = null }) {
  connectionLog.push({
    at: now(),
    event,
    connection_id: connectionId,
    method: req.method,
    path: url.pathname,
    query: Object.fromEntries(url.searchParams.entries()),
    session_id: sessionId,
    scenario_name: scenarioName,
    stream,
    last_event_id: req.headers['last-event-id'] || null,
    status,
  })
}

function logSseFrame({ req, url, connectionId, sessionId, scenarioName = null, stream, frame, raw = null }) {
  sseFrameLog.push({
    at: now(),
    connection_id: connectionId,
    method: req.method,
    path: url.pathname,
    query: Object.fromEntries(url.searchParams.entries()),
    session_id: sessionId,
    scenario_name: scenarioName,
    stream,
    id: frame?.id ?? null,
    event: frame?.event ?? null,
    data_type: frame?.data?.type ?? null,
    data: frame?.data ?? null,
    raw,
  })
}

function logRequest({ req, url, sessionId = null, scenarioName = null, prompt = null, body = null, status = null }) {
  requestLog.push({
    at: now(),
    method: req.method,
    path: url.pathname,
    query: Object.fromEntries(url.searchParams.entries()),
    session_id: sessionId,
    scenario_name: scenarioName,
    prompt: prompt || body?.content || body?.prompt || null,
    status,
    body,
  })
}

function requestUserId(req) {
  const value = req.headers['x-user-id']
  if (Array.isArray(value)) return String(value[0] || '').trim()
  return String(value || '').trim()
}

function authorizationError(req, url, res, status, detail, logMeta = {}) {
  sendJson(req, url, res, status, { detail }, logMeta)
  return false
}

function authorizeUserRequest(req, url, res, { body = null, requiredUserId = null, allowMissing = false } = {}) {
  const userId = requestUserId(req)
  if (!userId && !allowMissing) {
    return authorizationError(req, url, res, 401, 'Authentication required for this Factory Agent request.', { body })
  }
  if (requiredUserId && userId && String(requiredUserId) !== userId) {
    return authorizationError(req, url, res, 403, 'Authenticated user cannot create or impersonate another user session.', { body })
  }
  return true
}

function authorizeSessionRequest(req, url, res, session, { allowMissingStreamUser = false } = {}) {
  if (!session) return true
  const userId = requestUserId(req)
  if (!userId) {
    if (allowMissingStreamUser && !session.security?.require_stream_auth) return true
    return authorizationError(req, url, res, 401, 'Authentication required for this session.', { sessionId: session.session_id, scenarioName: session.scenario_name })
  }
  if (session.user_id !== userId) {
    return authorizationError(req, url, res, 404, 'Session not found.', { sessionId: session.session_id, scenarioName: session.scenario_name })
  }
  return true
}

function latestSessionWithPendingApproval(approvalId) {
  const ts = (value) => {
    const parsed = Date.parse(value || '')
    return Number.isFinite(parsed) ? parsed : 0
  }
  return Array.from(sessions.values())
    .filter((candidate) => candidate.pending_approval?.approval_id === approvalId)
    .sort((a, b) => ts(b.updated_at) - ts(a.updated_at))[0] || null
}

function seedSecuritySession({ sessionId, userId, name, secret, scenarioName = 'securityOwnerIsolatedRead', requireStreamAuth = false }) {
  const session = createScenarioSession({
    sessionId,
    userId,
    name,
    scenarioName,
  })
  session.status = 'COMPLETED'
  session.current_turn_id = `${sessionId}-turn`
  session.messages.push({
    id: `${sessionId}-message`,
    role: 'user',
    content: 'Private session seed',
    mode: 'normal',
    created_at: now(),
  })
  session.timeline.push({
    event_id: `${sessionId}-user`,
    turn_id: session.current_turn_id,
    event_type: 'user_message',
    role: 'user',
    content: 'Private session seed',
    status: 'DONE',
    created_at: now(),
  })
  session.timeline.push({
    event_id: `${sessionId}-complete`,
    turn_id: session.current_turn_id,
    event_type: 'session_completed',
    content: secret,
    status: 'COMPLETED',
    details: { reason: 'phase16_security_seed' },
    created_at: now(),
  })
  session.security = { require_stream_auth: requireStreamAuth }
  sessions.set(sessionId, session)
  return summarizeScenarioSession(session)
}

function seedSecurityCompletedLeakSession({ sessionId, userId, name }) {
  const session = createScenarioSession({
    sessionId,
    userId,
    name,
    scenarioName: 'securityOwnerIsolatedRead',
  })
  const turnId = `${sessionId}-turn`
  const planId = `${sessionId}-plan`
  const stepId = `${sessionId}-step`
  const sources = [
    {
      source_number: 1,
      title: securityCrossSessionLeakSource,
      doc_id: 'PHASE17-LEAK-SOURCE',
      organization: 'Private fixture',
    },
  ]
  session.status = 'COMPLETED'
  session.current_turn_id = turnId
  session.operation_id = planId
  session.plan = {
    plan_id: planId,
    session_id: sessionId,
    status: 'COMPLETED',
    objective: 'Private cross-session leakage fixture.',
    created_at: nowPlus(20),
    updated_at: nowPlus(30),
    steps: [
      {
        id: stepId,
        plan_id: planId,
        tool_name: 'private_audit_lookup',
        status: 'DONE',
        created_at: nowPlus(25),
        updated_at: nowPlus(35),
      },
    ],
  }
  session.steps = [...session.plan.steps]
  session.messages.push({
    id: `${sessionId}-message`,
    role: 'user',
    content: 'Private cross-session leakage fixture',
    mode: 'normal',
    created_at: nowPlus(10),
  })
  session.timeline.push(
    {
      event_id: `${sessionId}-user`,
      turn_id: turnId,
      event_type: 'user_message',
      role: 'user',
      content: 'Private cross-session leakage fixture',
      status: 'DONE',
      created_at: nowPlus(10),
    },
    {
      event_id: `${sessionId}-plan-created`,
      turn_id: turnId,
      event_type: 'plan_created',
      content: 'Private source and audit evidence loaded.',
      status: 'COMPLETED',
      operation_id: planId,
      details: {
        plan_id: planId,
        plan_explanation: 'Private source and audit evidence loaded.',
      },
      created_at: nowPlus(20),
    },
    {
      event_id: `${sessionId}-tool-result`,
      turn_id: turnId,
      event_type: 'tool_result',
      step_id: stepId,
      tool_name: 'private_audit_lookup',
      content: securityCrossSessionLeakAudit,
      status: 'DONE',
      operation_id: planId,
      details: {
        args: { session_scope: 'private' },
        result: {
          audit_evidence: securityCrossSessionLeakAudit,
          source_evidence: securityCrossSessionLeakSource,
        },
        presentation: {
          render_hint: 'table',
          table: {
            columns: [
              { key: 'evidence', label: 'Private Evidence' },
            ],
            rows: [
              { evidence: securityCrossSessionLeakSource },
            ],
            displayed_rows: 1,
            total_rows: 1,
          },
        },
      },
      created_at: nowPlus(30),
    },
    {
      event_id: `${sessionId}-complete`,
      turn_id: turnId,
      event_type: 'session_completed',
      content: securityCrossSessionLeakFinal,
      status: 'COMPLETED',
      operation_id: planId,
      details: {
        reason: securityCrossSessionLeakHidden,
        sources,
      },
      created_at: nowPlus(40),
    },
  )
  sessions.set(sessionId, session)
  return summarizeScenarioSession(session)
}

function seedSecurityPendingApprovalLeakSession({ sessionId, userId, name }) {
  const session = createScenarioSession({
    sessionId,
    userId,
    name,
    scenarioName: 'securityUnsafeToolBlocked',
  })
  const turnId = `${sessionId}-turn`
  const planId = `${sessionId}-plan`
  const stepId = `${sessionId}-step`
  session.status = 'WAITING_APPROVAL'
  session.current_turn_id = turnId
  session.operation_id = planId
  session.plan = {
    plan_id: planId,
    session_id: sessionId,
    status: 'PENDING_APPROVAL',
    objective: 'Private pending approval fixture.',
    created_at: nowPlus(20),
    updated_at: nowPlus(30),
    steps: [
      {
        id: stepId,
        plan_id: planId,
        tool_name: 'private_destructive_fixture',
        status: 'WAITING_APPROVAL',
        created_at: nowPlus(25),
      },
    ],
  }
  session.steps = [...session.plan.steps]
  session.pending_approval = {
    approval_id: `${sessionId}-approval`,
    session_id: sessionId,
    subject_type: 'tool',
    tool_name: 'private_destructive_fixture',
    side_effect_level: 'HIGH',
    risk_summary: securityCrossSessionLeakApproval,
    args: { private_evidence: securityCrossSessionLeakAudit },
    status: 'PENDING',
    created_at: nowPlus(30),
    expires_at: nowPlus(300_000),
  }
  session.messages.push({
    id: `${sessionId}-message`,
    role: 'user',
    content: 'Private approval leakage fixture',
    mode: 'normal',
    created_at: nowPlus(10),
  })
  session.timeline.push(
    {
      event_id: `${sessionId}-user`,
      turn_id: turnId,
      event_type: 'user_message',
      role: 'user',
      content: 'Private approval leakage fixture',
      status: 'DONE',
      created_at: nowPlus(10),
    },
    {
      event_id: `${sessionId}-approval-required`,
      turn_id: turnId,
      event_type: 'approval_required',
      approval_id: session.pending_approval.approval_id,
      tool_name: session.pending_approval.tool_name,
      content: securityCrossSessionLeakApproval,
      status: 'PENDING',
      details: {
        args: session.pending_approval.args,
        side_effect_level: session.pending_approval.side_effect_level,
      },
      created_at: nowPlus(30),
    },
  )
  sessions.set(sessionId, session)
  return summarizeScenarioSession(session)
}

function sendJson(req, url, res, status, body, logMeta = {}) {
  if (res.destroyed || res.writableEnded) return
  logRequest({ req, url, ...logMeta, status })
  res.writeHead(status, {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-User-Id',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, OPTIONS',
    'Content-Type': 'application/json',
  })
  res.end(JSON.stringify(body))
}

function pdfFixtureBytes(label = 'Factory Agent PDF evidence') {
  const searchableEvidence = [
    'After removing the lockout or tagout devices but before reenergizing the machine',
    'Before lockout or tagout devices are removed and energy is restored',
    'Affected employees must be notified by the employer before lockout or tagout devices are applied.',
  ].join(' ')
  const safeLabel = `${searchableEvidence} ${String(label)}`.replace(/[()\\]/g, ' ')
  const stream = `BT /F1 12 Tf 24 100 Td (${safeLabel}) Tj ET`
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 320 180] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
    `<< /Length ${Buffer.byteLength(stream, 'utf8')} >>\nstream\n${stream}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  let body = '%PDF-1.4\n'
  const offsets = [0]
  for (const [index, objectBody] of objects.entries()) {
    offsets.push(Buffer.byteLength(body, 'utf8'))
    body += `${index + 1} 0 obj\n${objectBody}\nendobj\n`
  }
  const xrefOffset = Buffer.byteLength(body, 'utf8')
  body += `xref\n0 ${objects.length + 1}\n`
  body += '0000000000 65535 f \n'
  for (const offset of offsets.slice(1)) {
    body += `${String(offset).padStart(10, '0')} 00000 n \n`
  }
  body += `trailer\n<< /Root 1 0 R /Size ${objects.length + 1} >>\nstartxref\n${xrefOffset}\n%%EOF\n`
  return Buffer.from(body, 'utf8')
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let raw = ''
    req.on('data', (chunk) => {
      raw += chunk
    })
    req.on('end', () => {
      if (!raw) {
        resolve({})
        return
      }
      try {
        resolve(JSON.parse(raw))
      } catch (err) {
        reject(err)
      }
    })
  })
}

function filteredRequestLog(url) {
  const contains = url.searchParams.get('contains')
  const sessionId = url.searchParams.get('session_id')
  const scenarioName = url.searchParams.get('scenario')
  return requestLog.filter((entry) => {
    if (sessionId && entry.session_id !== sessionId) return false
    if (scenarioName && entry.scenario_name !== scenarioName) return false
    if (contains) {
      const haystack = JSON.stringify(entry).toLowerCase()
      if (!haystack.includes(contains.toLowerCase())) return false
    }
    return true
  })
}

function filteredConnectionLog(url) {
  const sessionId = url.searchParams.get('session_id')
  const scenarioName = url.searchParams.get('scenario')
  const stream = url.searchParams.get('stream')
  const event = url.searchParams.get('event')
  return connectionLog.filter((entry) => {
    if (sessionId && entry.session_id !== sessionId) return false
    if (scenarioName && entry.scenario_name !== scenarioName) return false
    if (stream && entry.stream !== stream) return false
    if (event && entry.event !== event) return false
    return true
  })
}

function filteredSseFrameLog(url) {
  const sessionId = url.searchParams.get('session_id')
  const scenarioName = url.searchParams.get('scenario')
  const stream = url.searchParams.get('stream')
  const event = url.searchParams.get('event')
  const dataType = url.searchParams.get('type')
  return sseFrameLog.filter((entry) => {
    if (sessionId && entry.session_id !== sessionId) return false
    if (scenarioName && entry.scenario_name !== scenarioName) return false
    if (stream && entry.stream !== stream) return false
    if (event && entry.event !== event) return false
    if (dataType && entry.data_type !== dataType) return false
    return true
  })
}

function snapshot(session) {
  const scenario = getScenario(session.scenario_name)
  return scenario.snapshot(session)
}

async function runSseScript({ req, res, url, sessionId, stream, frames }) {
  const session = sessions.get(sessionId)
  const scenarioName = session?.scenario_name || null
  const connectionId = `pw-sse-${randomUUID()}`
  let closed = false

  const markClosed = () => {
    if (closed) return
    closed = true
    logConnection({
      req,
      url,
      event: 'close',
      connectionId,
      sessionId,
      scenarioName,
      stream,
    })
  }

  writeSseHeaders(res)
  logRequest({ req, url, sessionId, scenarioName, status: 200 })
  logConnection({
    req,
    url,
    event: 'open',
    connectionId,
    sessionId,
    scenarioName,
    stream,
    status: 200,
  })

  res.on('close', markClosed)
  req.on('aborted', markClosed)

  for (const frame of frames) {
    if (closed || res.writableEnded) return
    if (frame.delayMs) await sleep(frame.delayMs)
    if (closed || res.writableEnded) return
    if (frame.close) {
      res.end()
      return
    }
    if (frame.raw) {
      logSseFrame({ req, url, connectionId, sessionId, scenarioName, stream, frame: null, raw: frame.raw })
      sendRawSseFrame(res, frame.raw)
      continue
    }
    logSseFrame({ req, url, connectionId, sessionId, scenarioName, stream, frame })
    sendSseEvent(res, frame.event, frame.data, frame.id)
    frame.afterSent?.(session)
  }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`)

  if (req.method === 'OPTIONS') {
    sendJson(req, url, res, 204, {})
    return
  }

  if (req.method === 'GET' && url.pathname === '/health') {
    sendJson(req, url, res, 200, { ok: true })
    return
  }

  const documentPdfMatch = url.pathname.match(/^\/documents\/([^/]+)\/pdf$/)
  if (req.method === 'GET' && documentPdfMatch) {
    const body = pdfFixtureBytes(`Factory Agent PDF evidence for ${decodeURIComponent(documentPdfMatch[1])}`)
    logRequest({ req, url, status: 200 })
    res.writeHead(200, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-User-Id',
      'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, OPTIONS',
      'Content-Type': 'application/pdf',
      'Content-Disposition': `inline; filename="${documentPdfMatch[1]}.pdf"`,
    })
    res.end(body)
    return
  }

  if (req.method === 'GET' && url.pathname === '/__test/scenarios') {
    sendJson(req, url, res, 200, { scenarios: scenarioNames() })
    return
  }

  if (req.method === 'GET' && url.pathname === '/__test/requests') {
    sendJson(req, url, res, 200, { requests: filteredRequestLog(url) })
    return
  }

  if (req.method === 'GET' && url.pathname === '/__test/sse-connections') {
    sendJson(req, url, res, 200, { connections: filteredConnectionLog(url) })
    return
  }

  if (req.method === 'GET' && url.pathname === '/__test/sse-events') {
    sendJson(req, url, res, 200, { events: filteredSseFrameLog(url) })
    return
  }

  if (req.method === 'POST' && url.pathname === '/__test/reset') {
    sessions.clear()
    requestLog = []
    connectionLog = []
    sseFrameLog = []
    sendJson(req, url, res, 200, { ok: true })
    return
  }

  if (req.method === 'POST' && url.pathname === '/__test/normal-use-history') {
    const body = await readJson(req)
    const runId = body.run_id || randomUUID().slice(0, 8)
    const seeded = normalUseHistoryFixtures(runId)
    const created = seeded.sessions.map((item, index) => {
      const sessionId = `pw-normal-use-history-${runId}-${String(index + 1).padStart(2, '0')}`
      const session = createNormalUseHistorySession({
        ...item,
        sessionId,
        userId: body.user_id || 'frontend-operator',
      })
      sessions.set(sessionId, session)
      return summarizeScenarioSession(session)
    })
    sendJson(req, url, res, 200, {
      ok: true,
      run_id: runId,
      sessions: created,
      target: created.find((session) => session.name === seeded.target.name),
      target_prompt: seeded.target.prompt,
      target_answer: seeded.target.answer,
      decoy_answer: seeded.sessions.find((session) => session.key === 'history-07')?.answer || null,
    }, { body })
    return
  }

  if (req.method === 'POST' && url.pathname === '/__test/security-sessions') {
    const body = await readJson(req)
    const runId = body.run_id || randomUUID().slice(0, 8)
    const ownerUserId = body.owner_user_id || 'frontend-operator'
    const otherUserId = body.other_user_id || 'other-operator'
    const ownerSessionId = `pw-security-owner-${runId}`
    const otherSessionId = `pw-security-other-${runId}`
    const streamAuthSessionId = `pw-security-stream-auth-${runId}`
    const crossSessionFinalId = `pw-security-cross-final-${runId}`
    const crossSessionApprovalId = `pw-security-cross-approval-${runId}`
    const authFailureTargetId = `pw-security-auth-target-${runId}`
    const owner = seedSecuritySession({
      sessionId: ownerSessionId,
      userId: ownerUserId,
      name: `Phase 16 current operator session ${runId}`,
      secret: securitySafeOwnAnswer,
    })
    const other = seedSecuritySession({
      sessionId: otherSessionId,
      userId: otherUserId,
      name: `${securityTamperSessionName} ${runId}`,
      secret: securityOtherUserSecret,
    })
    const streamAuth = seedSecuritySession({
      sessionId: streamAuthSessionId,
      userId: ownerUserId,
      name: `Phase 16 auth-required stream session ${runId}`,
      secret: 'Phase 16 stream auth diagnostic transcript.',
      requireStreamAuth: true,
    })
    const crossSessionFinal = seedSecurityCompletedLeakSession({
      sessionId: crossSessionFinalId,
      userId: ownerUserId,
      name: `Phase 17 private final evidence session ${runId}`,
    })
    const crossSessionApproval = seedSecurityPendingApprovalLeakSession({
      sessionId: crossSessionApprovalId,
      userId: ownerUserId,
      name: `Phase 17 private pending approval session ${runId}`,
    })
    const authFailureTarget = seedSecuritySession({
      sessionId: authFailureTargetId,
      userId: ownerUserId,
      name: `Phase 17 auth failure target session ${runId}`,
      secret: securityAuthFailureTargetAnswer,
    })
    sendJson(req, url, res, 200, {
      ok: true,
      run_id: runId,
      owner,
      other,
      stream_auth: streamAuth,
      cross_session_final: crossSessionFinal,
      cross_session_approval: crossSessionApproval,
      auth_failure_target: authFailureTarget,
      other_secret: securityOtherUserSecret,
    }, { body })
    return
  }

  if (req.method === 'GET' && url.pathname === '/tools') {
    const intent = String(url.searchParams.get('intent') || '').toLowerCase()
    const tools = mockTools().filter((tool) => {
      if (!intent.includes('delete') && !intent.includes('unsafe')) return tool.name !== 'phase16_unsafe_delete_production_jobs'
      return tool.is_read_only
    })
    sendJson(req, url, res, 200, tools)
    return
  }

  if (req.method === 'GET' && url.pathname === '/sessions') {
    if (!authorizeUserRequest(req, url, res, { allowMissing: false })) return
    const userId = requestUserId(req)
    sendJson(req, url, res, 200, Array.from(sessions.values()).filter((session) => session.user_id === userId).map(summarizeScenarioSession))
    return
  }

  if (req.method === 'DELETE' && url.pathname === '/sessions') {
    if (!authorizeUserRequest(req, url, res, { allowMissing: false })) return
    const userId = requestUserId(req)
    const deletedIds = []
    for (const [sessionId, session] of sessions.entries()) {
      if (session.user_id !== userId) continue
      sessions.delete(sessionId)
      deletedIds.push(sessionId)
    }
    sendJson(req, url, res, 200, {
      ok: true,
      user_id: userId,
      deleted_count: deletedIds.length,
      session_ids: deletedIds,
    })
    return
  }

  if (req.method === 'POST' && url.pathname === '/sessions') {
    const body = await readJson(req)
    if (!authorizeUserRequest(req, url, res, { body, requiredUserId: body.user_id || 'playwright-user' })) return
    const id = `pw-session-${randomUUID()}`
    const session = createScenarioSession({
      sessionId: id,
      userId: body.user_id || 'playwright-user',
      name: body.name || 'Playwright session',
    })
    sessions.set(id, session)
    sendJson(req, url, res, 200, summarizeScenarioSession(session), {
      sessionId: id,
      scenarioName: session.scenario_name,
      body,
    })
    return
  }

  const deleteSessionMatch = url.pathname.match(/^\/sessions\/([^/]+)$/)
  if (req.method === 'DELETE' && deleteSessionMatch) {
    const session = sessions.get(deleteSessionMatch[1])
    if (!session) {
      sendJson(req, url, res, 404, { detail: 'Session not found' }, { sessionId: deleteSessionMatch[1] })
      return
    }
    if (!authorizeSessionRequest(req, url, res, session)) return
    sessions.delete(session.session_id)
    sendJson(req, url, res, 200, { ok: true, session_id: session.session_id }, {
      sessionId: session.session_id,
      scenarioName: session.scenario_name,
    })
    return
  }

  const snapshotMatch = url.pathname.match(/^\/sessions\/([^/]+)\/snapshot$/)
  if (req.method === 'GET' && snapshotMatch) {
    const session = sessions.get(snapshotMatch[1])
    if (!session) {
      sendJson(req, url, res, 404, { detail: 'Session not found' }, { sessionId: snapshotMatch[1] })
      return
    }
    if (!authorizeSessionRequest(req, url, res, session)) return
    sendJson(req, url, res, 200, snapshot(session), {
      sessionId: session.session_id,
      scenarioName: session.scenario_name,
    })
    return
  }

  const messagesMatch = url.pathname.match(/^\/sessions\/([^/]+)\/messages$/)
  if (req.method === 'POST' && messagesMatch) {
    const session = sessions.get(messagesMatch[1])
    if (!session) {
      sendJson(req, url, res, 404, { detail: 'Session not found' }, { sessionId: messagesMatch[1] })
      return
    }
    if (!authorizeSessionRequest(req, url, res, session)) return
    const body = await readJson(req)
    const scenario = resolveScenarioForPrompt(body.content)
    session.scenario_name = scenario.name
    const message = {
      id: `pw-message-${randomUUID()}`,
      role: body.role || 'user',
      content: body.content || '',
      mode: body.mode || 'normal',
      created_at: now(),
    }
    session.messages.push(message)
    session.last_prompt = message.content
    scenario.onMessage(session, message.content)
    sendJson(req, url, res, 200, message, {
      sessionId: session.session_id,
      scenarioName: scenario.name,
      prompt: session.last_prompt,
      body,
    })
    return
  }

  const planMatch = url.pathname.match(/^\/sessions\/([^/]+)\/plans$/)
  if (req.method === 'POST' && planMatch) {
    const session = sessions.get(planMatch[1])
    if (!session) {
      sendJson(req, url, res, 404, { detail: 'Session not found' }, { sessionId: planMatch[1] })
      return
    }
    if (!authorizeSessionRequest(req, url, res, session)) return
    const body = await readJson(req)
    const scenario = getScenario(session.scenario_name)
    const result = await scenario.onPlan(session, sleep)
    sendJson(req, url, res, result.status, result.body, {
      sessionId: session.session_id,
      scenarioName: scenario.name,
      prompt: session.last_prompt,
      body,
    })
    return
  }

  const executeMatch = url.pathname.match(/^\/sessions\/([^/]+)\/execute$/)
  if (req.method === 'POST' && executeMatch) {
    const session = sessions.get(executeMatch[1])
    if (!session) {
      sendJson(req, url, res, 404, { detail: 'Session not found' }, { sessionId: executeMatch[1] })
      return
    }
    if (!authorizeSessionRequest(req, url, res, session)) return
    const body = await readJson(req)
    const scenario = getScenario(session.scenario_name)
    const result = await scenario.onExecute(session, sleep)
    sendJson(req, url, res, result.status, result.body, {
      sessionId: session.session_id,
      scenarioName: scenario.name,
      prompt: session.last_prompt,
      body,
    })
    return
  }

  const cancelMatch = url.pathname.match(/^\/sessions\/([^/]+)\/cancel$/)
  if (req.method === 'POST' && cancelMatch) {
    const session = sessions.get(cancelMatch[1])
    if (!session) {
      sendJson(req, url, res, 404, { detail: 'Session not found' }, { sessionId: cancelMatch[1] })
      return
    }
    if (!authorizeSessionRequest(req, url, res, session)) return
    const body = await readJson(req)
    const scenario = getScenario(session.scenario_name)
    if (typeof scenario.onCancel === 'function') {
      const result = await scenario.onCancel(session, body)
      session.updated_at = now()
      sendJson(req, url, res, result.status, result.body, {
        sessionId: session.session_id,
        scenarioName: session.scenario_name,
        prompt: session.last_prompt,
        body,
      })
      return
    }
    const turnId = session.current_turn_id || `pw-cancel-${session.messages.length || 1}`
    session.status = 'FAILED'
    session.operation_id = null
    session.steps = session.steps.map((step) => ({
      ...step,
      status: 'CANCELLED',
      updated_at: now(),
    }))
    session.timeline.push({
      event_id: `pw-cancelled-${randomUUID()}`,
      turn_id: turnId,
      event_type: 'session_failed',
      content: 'Run cancelled by operator request.',
      status: 'FAILED',
      details: { reason: 'cancelled_by_user' },
      created_at: now(),
    })
    session.updated_at = now()
    sendJson(req, url, res, 200, { status: 'FAILED', session_id: session.session_id }, {
      sessionId: session.session_id,
      scenarioName: session.scenario_name,
      prompt: session.last_prompt,
      body,
    })
    return
  }

  if (req.method === 'GET' && url.pathname === '/approvals/pending') {
    if (!authorizeUserRequest(req, url, res, { allowMissing: false })) return
    const sessionId = url.searchParams.get('session_id')
    const approvals = Array.from(sessions.values())
      .filter((session) => (!sessionId || session.session_id === sessionId) && session.user_id === requestUserId(req))
      .map((session) => session.pending_approval)
      .filter(Boolean)
    sendJson(req, url, res, 200, approvals)
    return
  }

  const approveMatch = url.pathname.match(/^\/approvals\/([^/]+)\/approve$/)
  if (req.method === 'POST' && approveMatch) {
    const approvalId = approveMatch[1]
    const session = latestSessionWithPendingApproval(approvalId)
    if (!session) {
      sendJson(req, url, res, 404, { detail: 'Approval not found' })
      return
    }
    if (!authorizeSessionRequest(req, url, res, session)) return
    const body = await readJson(req)
    const scenario = getScenario(session.scenario_name)
    if (typeof scenario.onApprove === 'function') {
      const result = await scenario.onApprove(session, approvalId, body)
      session.updated_at = now()
      sendJson(req, url, res, result.status, result.body, {
        sessionId: session.session_id,
        scenarioName: session.scenario_name,
        body,
      })
      return
    }
    if (session.scenario_name === 'securityUnsafeToolBlocked') {
      session.status = 'FAILED'
      session.pending_approval = null
      session.updated_at = now()
      session.timeline.push({
        event_id: 'pw-security-unsafe-blocked',
        turn_id: session.current_turn_id || 'pw-turn-security-unsafe-tool',
        event_type: 'session_failed',
        content: securityUnsafeActionBlocked,
        status: 'FAILED',
        details: { reason: 'tool_allowlist_blocked' },
        created_at: now(),
      })
      sendJson(req, url, res, 403, { detail: securityUnsafeActionBlocked }, {
        sessionId: session.session_id,
        scenarioName: session.scenario_name,
      })
      return
    }
    sendJson(req, url, res, 409, { detail: 'Approval fixture does not support approval.' })
    return
  }

  const rejectMatch = url.pathname.match(/^\/approvals\/([^/]+)\/reject$/)
  if (req.method === 'POST' && rejectMatch) {
    const approvalId = rejectMatch[1]
    const session = latestSessionWithPendingApproval(approvalId)
    if (!session) {
      sendJson(req, url, res, 404, { detail: 'Approval not found' })
      return
    }
    if (!authorizeSessionRequest(req, url, res, session)) return
    const body = await readJson(req)
    const scenario = getScenario(session.scenario_name)
    if (typeof scenario.onReject === 'function') {
      const result = await scenario.onReject(session, approvalId, body)
      session.updated_at = now()
      sendJson(req, url, res, result.status, result.body, {
        sessionId: session.session_id,
        scenarioName: session.scenario_name,
        body,
      })
      return
    }
    session.status = 'FAILED'
    session.pending_approval = null
    session.updated_at = now()
    session.timeline.push({
      event_id: 'pw-security-unsafe-rejected',
      turn_id: session.current_turn_id || 'pw-turn-security-unsafe-tool',
      event_type: 'session_failed',
      content: 'Unsafe action rejected; no factory action was executed.',
      status: 'FAILED',
      details: { reason: 'operator_rejected_unsafe_action' },
      created_at: now(),
    })
    sendJson(req, url, res, 200, { status: 'REJECTED', approval_id: approvalId }, {
      sessionId: session.session_id,
      scenarioName: session.scenario_name,
    })
    return
  }

  const eventsMatch = url.pathname.match(/^\/sessions\/([^/]+)\/events$/)
  if (req.method === 'GET' && eventsMatch) {
    const sessionId = eventsMatch[1]
    const session = sessions.get(sessionId)
    if (session && !authorizeSessionRequest(req, url, res, session, { allowMissingStreamUser: true })) return
    runSseScript({
      req,
      res,
      url,
      sessionId,
      stream: 'notification',
      frames: notificationStreamForScenario(session),
    }).catch((err) => {
      if (!res.writableEnded) res.destroy(err)
    })
    return
  }

  const activityEventsMatch = url.pathname.match(/^\/sessions\/([^/]+)\/events\/activity$/)
  if (req.method === 'GET' && activityEventsMatch) {
    const sessionId = activityEventsMatch[1]
    const session = sessions.get(sessionId)
    if (session && !authorizeSessionRequest(req, url, res, session, { allowMissingStreamUser: true })) return
    runSseScript({
      req,
      res,
      url,
      sessionId,
      stream: 'activity',
      frames: activityStreamForScenario(session),
    }).catch((err) => {
      if (!res.writableEnded) res.destroy(err)
    })
    return
  }

  sendJson(req, url, res, 404, { detail: `No mock route for ${req.method} ${url.pathname}` })
})

server.listen(port, '127.0.0.1', () => {
  console.log(`Factory Agent mock listening on http://127.0.0.1:${port}`)
})

process.on('SIGTERM', () => server.close(() => process.exit(0)))
process.on('SIGINT', () => server.close(() => process.exit(0)))
