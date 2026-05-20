import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'

import { redactSensitiveArtifactText } from './artifactRedaction.js'

const port = Number(process.env.RELEASE_PROXY_PORT)
const distDir = process.env.RELEASE_PROXY_DIST_DIR
const artifactDir = process.env.RELEASE_PROXY_ARTIFACT_DIR
const goApiBaseUrl = new URL(process.env.RELEASE_PROXY_GO_API_BASE_URL)
const factoryAgentBaseUrl = new URL(process.env.RELEASE_PROXY_FACTORY_AGENT_BASE_URL)
const releaseBuildId = process.env.RELEASE_PROXY_BUILD_ID || 'playwright-release'
const backendSchemaVersion = process.env.RELEASE_PROXY_BACKEND_SCHEMA_VERSION || 'playwright-seeded-schema-v1'
const fingerprintPath = process.env.RELEASE_PROXY_FINGERPRINT_PATH || path.join(artifactDir, 'env-fingerprint.json')
const logPath = process.env.RELEASE_PROXY_LOG_PATH || path.join(artifactDir, 'release-proxy.log')

const faults = {
  goApiUnavailable: false,
  factoryAgentUnavailable: false,
  authFailure: false,
  providerUnavailable: false,
  schemaMismatch: false,
}

function appendLog(entry) {
  fs.mkdirSync(path.dirname(logPath), { recursive: true })
  fs.appendFileSync(logPath, `${redactSensitiveArtifactText({ at: new Date().toISOString(), ...entry })}\n`)
}

function send(res, status, body, headers = {}) {
  const payload = typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body, null, 2)
  res.writeHead(status, {
    'access-control-allow-origin': '*',
    'access-control-allow-methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS',
    'access-control-allow-headers': 'authorization,content-type,x-user-id,x-user-role',
    'x-release-build-id': releaseBuildId,
    ...headers,
  })
  res.end(payload)
}

function htmlDiagnostic(title, detail) {
  return `<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>${title}</title></head>
  <body>
    <main role="main">
      <h1>${title}</h1>
      <p>${detail}</p>
    </main>
  </body>
</html>`
}

function contentTypeFor(filePath) {
  if (filePath.endsWith('.html')) return 'text/html; charset=utf-8'
  if (filePath.endsWith('.js')) return 'text/javascript; charset=utf-8'
  if (filePath.endsWith('.css')) return 'text/css; charset=utf-8'
  if (filePath.endsWith('.json')) return 'application/json'
  if (filePath.endsWith('.png')) return 'image/png'
  if (filePath.endsWith('.svg')) return 'image/svg+xml'
  if (filePath.endsWith('.ico')) return 'image/x-icon'
  return 'application/octet-stream'
}

function safeStaticPath(urlPath) {
  const decoded = decodeURIComponent(urlPath.split('?')[0])
  const relative = decoded === '/' ? 'index.html' : decoded.replace(/^\/+/, '')
  const resolved = path.resolve(distDir, relative)
  if (!resolved.startsWith(path.resolve(distDir))) return null
  return fs.existsSync(resolved) && fs.statSync(resolved).isFile() ? resolved : path.join(distDir, 'index.html')
}

function precheckStatus(query) {
  const factoryAgentBaseUrl = query.get('factoryAgentBaseUrl') ?? '/agent'
  const apiBaseUrl = query.get('apiBaseUrl') ?? '/api/v1'
  if (faults.schemaMismatch || query.get('schemaMismatch') === '1') {
    return {
      ok: false,
      status: 503,
      code: 'schema_mismatch',
      message: 'Release precheck failed: migration/schema mismatch or backend readiness failure.',
    }
  }
  if (!factoryAgentBaseUrl || factoryAgentBaseUrl !== '/agent') {
    return {
      ok: false,
      status: 422,
      code: 'bad_factory_agent_env',
      message: 'Release precheck failed: VITE_FACTORY_AGENT_BASE_URL must be /agent for nginx/proxy release validation.',
    }
  }
  if (!apiBaseUrl || apiBaseUrl !== '/api/v1') {
    return {
      ok: false,
      status: 422,
      code: 'bad_go_api_env',
      message: 'Release precheck failed: VITE_API_BASE_URL must be /api/v1 for nginx/proxy release validation.',
    }
  }
  return {
    ok: true,
    status: 200,
    code: 'ok',
    message: 'Release precheck passed.',
  }
}

function proxyRequest(req, res, upstreamBase, stripPrefix, faultName) {
  if (faultName === 'factoryAgentUnavailable' && faults.authFailure) {
    appendLog({ kind: 'fault', faultName: 'authFailure', method: req.method, url: req.url })
    send(res, 401, { error: 'auth token expired or revoked controlled release fault', no_fake_completion: true }, {
      'content-type': 'application/json',
    })
    return
  }
  if (
    faultName === 'factoryAgentUnavailable' &&
    faults.providerUnavailable &&
    req.method === 'POST' &&
    /^\/agent\/sessions\/[^/]+\/plans$/.test(new URL(req.url, `http://${req.headers.host}`).pathname)
  ) {
    appendLog({ kind: 'fault', faultName: 'providerUnavailable', method: req.method, url: req.url })
    send(res, 503, { error: 'model/RAG provider dependency unavailable controlled release fault', no_fake_completion: true }, {
      'content-type': 'application/json',
    })
    return
  }
  if (faults[faultName]) {
    appendLog({ kind: 'fault', faultName, method: req.method, url: req.url })
    send(res, 503, { error: `${faultName} controlled release fault`, no_fake_completion: true }, {
      'content-type': 'application/json',
    })
    return
  }

  const incoming = new URL(req.url, `http://${req.headers.host}`)
  const upstreamPath = incoming.pathname.replace(stripPrefix, '') || '/'
  const upstream = new URL(upstreamPath + incoming.search, upstreamBase)
  const headers = { ...req.headers, host: upstream.host }
  delete headers.connection

  appendLog({ kind: 'proxy', method: req.method, url: req.url, upstream: upstream.toString() })
  const proxy = http.request(
    upstream,
    {
      method: req.method,
      headers,
    },
    (upstreamRes) => {
      const responseHeaders = {
        ...upstreamRes.headers,
        'access-control-allow-origin': '*',
        'access-control-allow-methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS',
        'access-control-allow-headers': 'authorization,content-type,x-user-id,x-user-role',
        'x-release-build-id': releaseBuildId,
      }
      res.writeHead(upstreamRes.statusCode || 502, responseHeaders)
      upstreamRes.pipe(res)
    },
  )
  proxy.on('error', (err) => {
    appendLog({ kind: 'proxy-error', method: req.method, url: req.url, error: err.message })
    send(res, 502, { error: err.message, no_fake_completion: true }, { 'content-type': 'application/json' })
  })
  req.pipe(proxy)
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`)
  appendLog({ kind: 'request', method: req.method, url: req.url })

  if (req.method === 'OPTIONS') {
    send(res, 204, '', { 'content-length': '0' })
    return
  }

  if (url.pathname === '/__release/health') {
    send(res, 200, { status: 'ready', releaseBuildId, backendSchemaVersion }, { 'content-type': 'application/json' })
    return
  }

  if (url.pathname === '/__release/fingerprint') {
    const body = fs.existsSync(fingerprintPath) ? fs.readFileSync(fingerprintPath) : '{}'
    send(res, 200, body, { 'content-type': 'application/json' })
    return
  }

  if (url.pathname === '/__release/precheck') {
    const status = precheckStatus(url.searchParams)
    const wantsHtml = String(req.headers.accept || '').includes('text/html')
    if (wantsHtml && !status.ok) {
      send(res, status.status, htmlDiagnostic('Release precheck failed', status.message), { 'content-type': 'text/html; charset=utf-8' })
      return
    }
    send(res, status.status, status, { 'content-type': 'application/json' })
    return
  }

  if (url.pathname === '/__release/version') {
    const candidate = url.searchParams.get('frontendBuildId') || releaseBuildId
    if (candidate !== releaseBuildId) {
      send(
        res,
        409,
        {
          ok: false,
          code: 'version_mismatch',
          message: 'Browser cache/version mismatch: stale frontend build is incompatible with this backend schema.',
          expectedFrontendBuildId: releaseBuildId,
          receivedFrontendBuildId: candidate,
          backendSchemaVersion,
        },
        { 'content-type': 'application/json' },
      )
      return
    }
    send(res, 200, { ok: true, releaseBuildId, backendSchemaVersion }, { 'content-type': 'application/json' })
    return
  }

  if (url.pathname === '/__release/faults') {
    if (req.method === 'GET') {
      send(res, 200, faults, { 'content-type': 'application/json' })
      return
    }
    if (req.method === 'POST') {
      let body = ''
      req.on('data', (chunk) => {
        body += chunk
      })
      req.on('end', () => {
        const next = body ? JSON.parse(body) : {}
        for (const key of Object.keys(faults)) {
          if (Object.prototype.hasOwnProperty.call(next, key)) faults[key] = Boolean(next[key])
        }
        appendLog({ kind: 'faults-updated', faults })
        send(res, 200, faults, { 'content-type': 'application/json' })
      })
      return
    }
  }

  if (url.pathname === '/__release/logs') {
    const body = fs.existsSync(logPath) ? redactSensitiveArtifactText(fs.readFileSync(logPath, 'utf8')) : ''
    send(res, 200, body, { 'content-type': 'text/plain; charset=utf-8' })
    return
  }

  if (url.pathname === '/agent' || url.pathname.startsWith('/agent/')) {
    proxyRequest(req, res, factoryAgentBaseUrl, /^\/agent/, 'factoryAgentUnavailable')
    return
  }

  if (url.pathname === '/api' || url.pathname.startsWith('/api/')) {
    proxyRequest(req, res, goApiBaseUrl, /^/, 'goApiUnavailable')
    return
  }

  const filePath = safeStaticPath(url.pathname)
  if (!filePath) {
    send(res, 403, 'Forbidden', { 'content-type': 'text/plain; charset=utf-8' })
    return
  }
  const isIndex = path.basename(filePath) === 'index.html'
  send(res, 200, fs.readFileSync(filePath), {
    'content-type': contentTypeFor(filePath),
    'cache-control': isIndex ? 'no-store' : 'public, max-age=31536000, immutable',
  })
})

server.listen(port, '127.0.0.1', () => {
  appendLog({ kind: 'listening', port, distDir, goApiBaseUrl: goApiBaseUrl.toString(), factoryAgentBaseUrl: factoryAgentBaseUrl.toString() })
})

async function close() {
  server.close(() => process.exit(0))
}

process.on('SIGTERM', close)
process.on('SIGINT', close)
