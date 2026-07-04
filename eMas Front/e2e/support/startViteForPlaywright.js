import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
const testArtifactWatchIgnores = [
  '**/playwright-output/**',
  '**/playwright-report/**',
  '**/test-results/**',
  '**/.playwright-artifacts-*/**',
]

const args = new Map()
for (let i = 2; i < process.argv.length; i += 2) {
  args.set(process.argv[i], process.argv[i + 1])
}

const port = Number(args.get('--port') || process.env.PORT || 4175)
const factoryAgentUrl = args.get('--factory-agent-url') || process.env.VITE_FACTORY_AGENT_BASE_URL
const apiUrl = args.get('--api-url') || process.env.VITE_API_BASE_URL
const requestTimeoutMs = args.get('--request-timeout-ms') || process.env.VITE_FACTORY_AGENT_REQUEST_TIMEOUT_MS
const chatEmergencyDisabled =
  args.get('--chat-emergency-disabled') ||
  process.env.PLAYWRIGHT_CHAT_EMERGENCY_DISABLED ||
  process.env.VITE_FACTORY_AGENT_EMERGENCY_DISABLED
const chatEmergencyDisabledReason =
  args.get('--chat-emergency-disabled-reason') ||
  process.env.PLAYWRIGHT_CHAT_EMERGENCY_DISABLED_REASON ||
  process.env.VITE_FACTORY_AGENT_EMERGENCY_DISABLED_REASON

if (!factoryAgentUrl) {
  throw new Error('Missing --factory-agent-url for Playwright Vite server')
}

process.env.VITE_FACTORY_AGENT_BASE_URL = factoryAgentUrl
if (apiUrl) {
  process.env.VITE_API_BASE_URL = apiUrl
}
if (requestTimeoutMs) {
  process.env.VITE_FACTORY_AGENT_REQUEST_TIMEOUT_MS = requestTimeoutMs
}
if (chatEmergencyDisabled) {
  process.env.VITE_FACTORY_AGENT_EMERGENCY_DISABLED = chatEmergencyDisabled
}
if (chatEmergencyDisabledReason) {
  process.env.VITE_FACTORY_AGENT_EMERGENCY_DISABLED_REASON = chatEmergencyDisabledReason
}

const server = await createServer({
  root: repoRoot,
  configFile: false,
  plugins: [react()],
  resolve: {
    alias: {
      '@': resolve(repoRoot, 'src'),
    },
  },
  server: {
    host: '127.0.0.1',
    port,
    strictPort: true,
    watch: {
      ignored: testArtifactWatchIgnores,
    },
    fs: {
      allow: [repoRoot],
    },
  },
})

await server.listen()
server.printUrls()

let closing = false
async function close() {
  if (closing) return
  closing = true
  const forceExit = setTimeout(() => process.exit(0), 5_000)
  forceExit.unref?.()
  try {
    server.httpServer?.closeIdleConnections?.()
    server.httpServer?.closeAllConnections?.()
    await server.close()
  } finally {
    clearTimeout(forceExit)
    process.exit(0)
  }
}

process.on('SIGTERM', close)
process.on('SIGINT', close)
