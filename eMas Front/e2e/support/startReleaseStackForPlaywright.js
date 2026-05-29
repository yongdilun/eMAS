import fs from 'node:fs'
import path from 'node:path'
import { spawn, spawnSync } from 'node:child_process'

import { releaseRuntimeEnv } from './releaseEnv.js'

function normalizePathForSqlite(value) {
  return value.replace(/\\/g, '/')
}

const repoRoot = path.resolve(process.cwd(), '..')
const frontendRoot = path.join(repoRoot, 'eMas Front')
const env = releaseRuntimeEnv(repoRoot)

fs.rmSync(env.artifactDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 250 })
fs.mkdirSync(env.artifactDir, { recursive: true })
fs.mkdirSync(path.dirname(env.goDbPath), { recursive: true })

const children = []
const logs = {
  goApi: path.join(env.artifactDir, 'go-api.log'),
  factoryAgent: path.join(env.artifactDir, 'factory-agent.log'),
  releaseProxy: env.proxyLogPath,
  build: path.join(env.artifactDir, 'build.log'),
  stack: path.join(env.artifactDir, 'release-stack.log'),
}

const fingerprint = {
  kind: 'playwright-release-stack',
  created_at: new Date().toISOString(),
  repoRoot,
  releaseBuildId: env.releaseBuildId,
  backendSchemaVersion: env.backendSchemaVersion,
  ports: {
    goApi: env.goApiPort,
    factoryAgent: env.factoryAgentPort,
    proxy: env.proxyPort,
  },
  urls: {
    releaseBaseUrl: env.releaseBaseUrl,
    releaseFactoryAgentBaseUrl: env.releaseFactoryAgentBaseUrl,
    releaseGoApiBaseUrl: env.releaseGoApiBaseUrl,
    rollbackBaseUrl: env.rollbackBaseUrl,
    directGoApiBaseUrl: env.directGoApiBaseUrl,
    directFactoryAgentBaseUrl: env.directFactoryAgentBaseUrl,
    openApiUrl: env.openApiUrl,
  },
  frontendEnv: {
    VITE_FACTORY_AGENT_BASE_URL: '/agent',
    VITE_API_BASE_URL: '/api/v1',
    VITE_FACTORY_AGENT_BEARER_TOKEN: '<set>',
    VITE_FACTORY_AGENT_USER_ID: env.userId,
  },
  auth: {
    JWT_REQUIRED: '1',
    jwtSecret: '<set>',
    token: '<redacted>',
  },
  db: {
    goApi: env.goDbPath,
    factoryAgent: env.factoryAgentDbPath,
  },
  logs,
  platform: env.platform,
}
fs.writeFileSync(env.fingerprintPath, JSON.stringify(fingerprint, null, 2))

function append(logPath, line) {
  fs.appendFileSync(logPath, line)
}

function startProcess(name, command, args, options) {
  const logPath = logs[name]
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

function runBuild() {
  append(logs.build, `[${new Date().toISOString()}] npm run build\n`)
  const npmCli = process.env.npm_execpath || path.join(path.dirname(process.execPath), 'node_modules', 'npm', 'bin', 'npm-cli.js')
  const result = spawnSync(process.execPath, [npmCli, 'run', 'build'], {
    cwd: frontendRoot,
    env: {
      ...process.env,
      VITE_FACTORY_AGENT_BASE_URL: '/agent',
      VITE_API_BASE_URL: '/api/v1',
      VITE_FACTORY_AGENT_BEARER_TOKEN: env.bearerToken,
      VITE_FACTORY_AGENT_USER_ID: env.userId,
      VITE_FACTORY_AGENT_CHAT_MODE: 'user',
      VITE_FACTORY_AGENT_ACTIVITY_TIMELINE: 'true',
      VITE_FACTORY_AGENT_STREAM_BUFFER_MS: '10',
      VITE_FACTORY_AGENT_PROGRESS_STAGE_MIN_MS: '250',
    },
    encoding: 'utf8',
    windowsHide: true,
  })
  append(logs.build, result.stdout || '')
  append(logs.build, result.stderr || '')
  if (result.error) {
    append(logs.build, `[${new Date().toISOString()}] spawn error: ${result.error.stack || result.error.message}\n`)
  }
  if (result.status !== 0) {
    throw new Error(`release frontend build failed with exit code ${result.status} signal ${result.signal || 'none'}`)
  }
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
    if (child.killed) continue
    if (process.platform === 'win32' && child.pid) {
      spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true })
    } else {
      child.kill('SIGTERM')
    }
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
  await waitForJson(env.goApiHealthUrl, { timeoutMs: 60_000, label: 'release Go API' })

  runBuild()

  startProcess('releaseProxy', process.execPath, ['e2e/support/releaseProxyServer.js'], {
    cwd: frontendRoot,
    env: {
      RELEASE_PROXY_PORT: String(env.proxyPort),
      RELEASE_PROXY_DIST_DIR: path.join(frontendRoot, 'dist'),
      RELEASE_PROXY_ARTIFACT_DIR: env.artifactDir,
      RELEASE_PROXY_GO_API_BASE_URL: `http://127.0.0.1:${env.goApiPort}`,
      RELEASE_PROXY_FACTORY_AGENT_BASE_URL: env.directFactoryAgentBaseUrl,
      RELEASE_PROXY_BUILD_ID: env.releaseBuildId,
      RELEASE_PROXY_BACKEND_SCHEMA_VERSION: env.backendSchemaVersion,
      RELEASE_PROXY_FINGERPRINT_PATH: env.fingerprintPath,
      RELEASE_PROXY_LOG_PATH: env.proxyLogPath,
    },
  })
  await waitForJson(`${env.releaseBaseUrl}/__release/health`, { timeoutMs: 30_000, label: 'release proxy' })

  startProcess('factoryAgent', pythonExe(), ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(env.factoryAgentPort)], {
    cwd: path.join(repoRoot, 'factory-agent'),
    env: {
      APP_MODE: 'production',
      ALLOW_UNSAFE_PRODUCTION_CONFIG: '1',
      ENABLE_STARTUP_CREATE_ALL: '1',
      DATABASE_URL: `sqlite+aiosqlite:///${normalizePathForSqlite(env.factoryAgentDbPath)}`,
      GO_API_BASE_URL: env.releaseGoApiBaseUrl,
      OPENAPI_URL: env.openApiUrl,
      JWT_REQUIRED: '1',
      JWT_SECRET: env.jwtSecret,
      CORS_ALLOW_ORIGINS: `${env.releaseBaseUrl},http://localhost:${env.proxyPort}`,
      REDIS_URL: '',
      FACTORY_AGENT_ALLOW_OFFLINE_PLANNER_PROPOSER: '1',
      PLANNER_OPENAI_BASE_URL: '',
      SEMANTIC_INTAKE_OPENAI_BASE_URL: '',
      SUMMARY_OPENAI_BASE_URL: '',
      TOOL_RESULT_SUMMARY_OPENAI_BASE_URL: '',
      TOOL_SELECTOR_OPENAI_BASE_URL: '',
      RAG_RERANKER_OPENAI_BASE_URL: '',
      RAG_ANSWER_OPENAI_BASE_URL: '',
      OPENAI_BASE_URL: '',
      LLM_BASE_URL: '',
      PLANNER_API_KEY: '',
      OPENAI_API_KEY: '',
      LLM_API_KEY: '',
      PRODUCTION_PLANNER_OPENAI_BASE_URL: '',
      PRODUCTION_SEMANTIC_INTAKE_OPENAI_BASE_URL: '',
      PRODUCTION_SUMMARY_OPENAI_BASE_URL: '',
      PRODUCTION_TOOL_RESULT_SUMMARY_OPENAI_BASE_URL: '',
      PRODUCTION_TOOL_SELECTOR_OPENAI_BASE_URL: '',
      PRODUCTION_RAG_RERANKER_OPENAI_BASE_URL: '',
      PRODUCTION_RAG_ANSWER_OPENAI_BASE_URL: '',
      PRODUCTION_OPENAI_BASE_URL: '',
      PRODUCTION_LLM_BASE_URL: '',
      PRODUCTION_PLANNER_API_KEY: '',
      PRODUCTION_OPENAI_API_KEY: '',
      PRODUCTION_LLM_API_KEY: '',
      FACTORY_AGENT_PLAYWRIGHT_SEEDED_MODE: '1',
      FACTORY_AGENT_TOOLS_MD_PATH: path.join(env.artifactDir, 'factory-agent-tools.md'),
      SUMMARY_BACKEND: 'deterministic',
      TOOL_RESULT_SUMMARY_BACKEND: 'deterministic',
      TOOL_SELECTOR_RERANKER_ENABLED: '0',
      EMBEDDING_BACKEND: 'disabled',
      MEMORY_ENABLED: '0',
      VECTOR_MEMORY_ENABLED: '0',
      CHECKPOINT_ENABLED: '0',
      GRAPH_CHECKPOINT_BACKEND: 'memory',
      ENFORCE_TOOL_REGISTRY_HEALTH: '1',
      AUTO_REPAIR_TOOL_REGISTRY: '1',
      MIN_HEALTHY_TOOL_COUNT: '20',
      HTTP_TIMEOUT_S: '5',
    },
  })
  await waitForJson(env.releaseFactoryAgentReadyUrl, { timeoutMs: 90_000, label: 'release Factory Agent proxy path' })
  await waitForText(env.releaseBaseUrl, { timeoutMs: 30_000, label: 'release frontend' })
  append(logs.stack, `[${new Date().toISOString()}] release stack ready\n`)
} catch (err) {
  append(logs.stack, `[${new Date().toISOString()}] startup failed: ${err?.stack || err}\n`)
  stopAll()
  throw err
}

setInterval(() => {}, 1_000)
