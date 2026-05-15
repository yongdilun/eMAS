import http from 'node:http'
import { randomUUID } from 'node:crypto'
import {
  activityStreamForScenario,
  createScenarioSession,
  getScenario,
  notificationStreamForScenario,
  resolveScenarioForPrompt,
  scenarioNames,
  summarizeScenarioSession,
} from './fixtureStore.js'

const args = new Map()
for (let i = 2; i < process.argv.length; i += 2) {
  args.set(process.argv[i], process.argv[i + 1])
}

const port = Number(args.get('--port') || process.env.PORT || 8015)
const sessions = new Map()
let requestLog = []
let connectionLog = []

function now() {
  return new Date().toISOString()
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

function writeSseHeaders(res) {
  res.writeHead(200, {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
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

function sendJson(req, url, res, status, body, logMeta = {}) {
  logRequest({ req, url, ...logMeta, status })
  res.writeHead(status, {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, OPTIONS',
    'Content-Type': 'application/json',
  })
  res.end(JSON.stringify(body))
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
    sendSseEvent(res, frame.event, frame.data, frame.id)
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

  if (req.method === 'POST' && url.pathname === '/__test/reset') {
    sessions.clear()
    requestLog = []
    connectionLog = []
    sendJson(req, url, res, 200, { ok: true })
    return
  }

  if (req.method === 'GET' && url.pathname === '/sessions') {
    sendJson(req, url, res, 200, Array.from(sessions.values()).map(summarizeScenarioSession))
    return
  }

  if (req.method === 'POST' && url.pathname === '/sessions') {
    const body = await readJson(req)
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

  const snapshotMatch = url.pathname.match(/^\/sessions\/([^/]+)\/snapshot$/)
  if (req.method === 'GET' && snapshotMatch) {
    const session = sessions.get(snapshotMatch[1])
    if (!session) {
      sendJson(req, url, res, 404, { detail: 'Session not found' }, { sessionId: snapshotMatch[1] })
      return
    }
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
    const body = await readJson(req)
    const scenario = getScenario(session.scenario_name)
    const result = scenario.onPlan(session)
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

  const eventsMatch = url.pathname.match(/^\/sessions\/([^/]+)\/events$/)
  if (req.method === 'GET' && eventsMatch) {
    const sessionId = eventsMatch[1]
    const session = sessions.get(sessionId)
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
