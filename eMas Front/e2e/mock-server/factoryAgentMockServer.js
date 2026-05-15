import http from 'node:http'
import { randomUUID } from 'node:crypto'

const args = new Map()
for (let i = 2; i < process.argv.length; i += 2) {
  args.set(process.argv[i], process.argv[i + 1])
}

const port = Number(args.get('--port') || process.env.PORT || 8015)
const sessions = new Map()

function now() {
  return new Date().toISOString()
}

function sessionSummary(session) {
  return {
    session_id: session.session_id,
    user_id: session.user_id,
    name: session.name,
    status: session.status,
    created_at: session.created_at,
    updated_at: session.updated_at,
  }
}

function snapshot(session) {
  return {
    session: sessionSummary(session),
    messages: session.messages,
    timeline: [],
    activity_steps: [],
    pending_approval: null,
  }
}

function sendJson(res, status, body) {
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

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`)

  if (req.method === 'OPTIONS') {
    sendJson(res, 204, {})
    return
  }

  if (req.method === 'GET' && url.pathname === '/health') {
    sendJson(res, 200, { ok: true })
    return
  }

  if (req.method === 'GET' && url.pathname === '/sessions') {
    sendJson(res, 200, Array.from(sessions.values()).map(sessionSummary))
    return
  }

  if (req.method === 'POST' && url.pathname === '/sessions') {
    const body = await readJson(req)
    const id = `pw-session-${randomUUID()}`
    const session = {
      session_id: id,
      user_id: body.user_id || 'playwright-user',
      name: body.name || 'Playwright session',
      status: 'IDLE',
      created_at: now(),
      updated_at: now(),
      messages: [],
    }
    sessions.set(id, session)
    sendJson(res, 200, sessionSummary(session))
    return
  }

  const snapshotMatch = url.pathname.match(/^\/sessions\/([^/]+)\/snapshot$/)
  if (req.method === 'GET' && snapshotMatch) {
    const session = sessions.get(snapshotMatch[1])
    if (!session) {
      sendJson(res, 404, { detail: 'Session not found' })
      return
    }
    sendJson(res, 200, snapshot(session))
    return
  }

  const messagesMatch = url.pathname.match(/^\/sessions\/([^/]+)\/messages$/)
  if (req.method === 'POST' && messagesMatch) {
    const session = sessions.get(messagesMatch[1])
    if (!session) {
      sendJson(res, 404, { detail: 'Session not found' })
      return
    }
    const body = await readJson(req)
    const message = {
      id: `pw-message-${randomUUID()}`,
      role: body.role || 'user',
      content: body.content || '',
      mode: body.mode || 'normal',
      created_at: now(),
    }
    session.messages.push(message)
    session.updated_at = now()
    sendJson(res, 200, message)
    return
  }

  const planMatch = url.pathname.match(/^\/sessions\/([^/]+)\/plans$/)
  if (req.method === 'POST' && planMatch) {
    const session = sessions.get(planMatch[1])
    if (!session) {
      sendJson(res, 404, { detail: 'Session not found' })
      return
    }
    session.status = 'COMPLETED'
    session.updated_at = now()
    sendJson(res, 200, { status: 'COMPLETED', plan_id: `pw-plan-${randomUUID()}` })
    return
  }

  sendJson(res, 404, { detail: `No mock route for ${req.method} ${url.pathname}` })
})

server.listen(port, '127.0.0.1', () => {
  console.log(`Factory Agent mock listening on http://127.0.0.1:${port}`)
})

process.on('SIGTERM', () => server.close(() => process.exit(0)))
process.on('SIGINT', () => server.close(() => process.exit(0)))
