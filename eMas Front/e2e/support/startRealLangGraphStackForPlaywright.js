import fs from 'node:fs'
import path from 'node:path'
import { spawn } from 'node:child_process'

import { realLangGraphRuntimeEnv } from './fullStackEnv.js'

const repoRoot = path.resolve(process.cwd(), '..')
const env = realLangGraphRuntimeEnv(repoRoot)

fs.rmSync(env.artifactDir, { recursive: true, force: true })
fs.mkdirSync(env.artifactDir, { recursive: true })
fs.mkdirSync(path.dirname(env.goDbPath), { recursive: true })

const children = []
const fingerprint = {
  kind: 'playwright-real-langgraph-stack',
  created_at: new Date().toISOString(),
  repoRoot,
  ports: {
    goApi: env.goApiPort,
    factoryAgent: env.factoryAgentPort,
    vite: env.vitePort,
  },
  urls: {
    goApiBaseUrl: env.goApiBaseUrl,
    factoryAgentBaseUrl: env.factoryAgentBaseUrl,
    viteBaseUrl: env.viteBaseUrl,
    openApiUrl: env.openApiUrl,
  },
  db: {
    goApi: env.goDbPath,
    factoryAgent: env.factoryAgentDbPath,
  },
  logs: {
    goApi: path.join(env.artifactDir, 'go-api.log'),
    factoryAgent: path.join(env.artifactDir, 'factory-agent.log'),
    vite: path.join(env.artifactDir, 'vite.log'),
  },
  platform: env.platform,
}
fs.writeFileSync(env.fingerprintPath, JSON.stringify(fingerprint, null, 2))

function append(logPath, line) {
  fs.mkdirSync(path.dirname(logPath), { recursive: true })
  fs.appendFileSync(logPath, line)
}

function startProcess(name, command, args, options) {
  const logPath = fingerprint.logs[name]
  append(logPath, `[${new Date().toISOString()}] starting ${command} ${args.join(' ')}\n`)
  const child = spawn(command, args, {
    cwd: options.cwd,
    env: { ...process.env, ...options.env },
    shell: false,
    windowsHide: true,
  })
  children.push({ name, child, logPath })
  child.stdout.on('data', (chunk) => append(logPath, chunk.toString()))
  child.stderr.on('data', (chunk) => append(logPath, chunk.toString()))
  child.on('exit', (code, signal) => {
    append(logPath, `[${new Date().toISOString()}] exited code=${code} signal=${signal}\n`)
  })
  return child
}

async function waitForJson(url, { timeoutMs, label }) {
  const started = Date.now()
  let lastError = ''
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url)
      const text = await response.text()
      if (response.ok) return text ? JSON.parse(text) : {}
      lastError = `${response.status} ${response.statusText}: ${text.slice(0, 300)}`
    } catch (err) {
      lastError = err?.message || String(err)
    }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  throw new Error(`${label} did not become ready at ${url}: ${lastError}`)
}

async function waitForText(url, { timeoutMs, label }) {
  const started = Date.now()
  let lastError = ''
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url)
      const text = await response.text()
      if (response.ok) return text
      lastError = `${response.status} ${response.statusText}: ${text.slice(0, 300)}`
    } catch (err) {
      lastError = err?.message || String(err)
    }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  throw new Error(`${label} did not become ready at ${url}: ${lastError}`)
}

function pythonExe() {
  const candidate = path.join(repoRoot, 'factory-agent', '.venv', 'Scripts', 'python.exe')
  return fs.existsSync(candidate) ? candidate : 'python'
}

function stopAll() {
  for (const { child } of [...children].reverse()) {
    if (!child.killed) child.kill('SIGTERM')
  }
}

process.on('SIGTERM', () => {
  stopAll()
  process.exit(0)
})
process.on('SIGINT', () => {
  stopAll()
  process.exit(0)
})
process.on('exit', stopAll)

try {
  startProcess('goApi', 'go', ['run', './cmd/e2e_server'], {
    cwd: path.join(repoRoot, 'emas'),
    env: {
      E2E_SERVER_ADDR: `127.0.0.1:${env.goApiPort}`,
      E2E_SQLITE_PATH: env.goDbPath,
      GIN_MODE: 'release',
    },
  })
  await waitForJson(env.goApiHealthUrl, { timeoutMs: 60_000, label: 'seeded Go API' })

  startProcess('factoryAgent', pythonExe(), ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(env.factoryAgentPort)], {
    cwd: path.join(repoRoot, 'factory-agent'),
    env: {
      APP_MODE: 'development',
      DATABASE_URL: env.factoryAgentDatabaseUrl,
      GO_API_BASE_URL: env.goApiBaseUrl,
      OPENAPI_URL: env.openApiUrl,
      JWT_REQUIRED: '0',
      CORS_ALLOW_ORIGINS: `${env.viteBaseUrl},http://localhost:${env.vitePort}`,
      FACTORY_AGENT_PLAYWRIGHT_SEEDED_MODE: '0',
      FACTORY_AGENT_PRELOAD_OPENAPI_TOOLS: '1',
      FACTORY_AGENT_TOOLS_MD_PATH: path.join(env.artifactDir, 'factory-agent-tools.md'),
      SUMMARY_BACKEND: 'deterministic',
      TOOL_RESULT_SUMMARY_BACKEND: 'deterministic',
      TOOL_SELECTOR_BACKEND: 'retrieval',
      TOOL_SELECTOR_RERANKER_ENABLED: '0',
      EMBEDDING_BACKEND: 'disabled',
      MEMORY_ENABLED: '0',
      VECTOR_MEMORY_ENABLED: '0',
      CHECKPOINT_ENABLED: '0',
      GRAPH_CHECKPOINT_BACKEND: 'memory',
      ENFORCE_TOOL_REGISTRY_HEALTH: '1',
      AUTO_REPAIR_TOOL_REGISTRY: '1',
      MIN_HEALTHY_TOOL_COUNT: '20',
      PLANNER_MAX_RETRIES: '0',
      HTTP_TIMEOUT_S: '5',
    },
  })
  await waitForJson(env.factoryAgentReadyUrl, { timeoutMs: 90_000, label: 'Factory Agent real LangGraph' })

  startProcess('vite', process.execPath, [
    'e2e/support/startViteForPlaywright.js',
    '--port',
    String(env.vitePort),
    '--factory-agent-url',
    env.factoryAgentBaseUrl,
    '--api-url',
    env.goApiBaseUrl,
  ], {
    cwd: path.join(repoRoot, 'eMas Front'),
    env: {
      PLAYWRIGHT_REAL_LANGGRAPH_ARTIFACT_DIR: env.artifactDir,
    },
  })
  await waitForText(env.viteBaseUrl, { timeoutMs: 60_000, label: 'Vite' })
  append(path.join(env.artifactDir, 'real-langgraph-stack.log'), `[${new Date().toISOString()}] real LangGraph stack ready\n`)
} catch (err) {
  append(path.join(env.artifactDir, 'real-langgraph-stack.log'), `[${new Date().toISOString()}] startup failed: ${err?.stack || err}\n`)
  stopAll()
  throw err
}

setInterval(() => {}, 1_000)
