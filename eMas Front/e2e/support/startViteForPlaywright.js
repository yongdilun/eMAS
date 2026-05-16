import { createServer } from 'vite'

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
  server: {
    host: '127.0.0.1',
    port,
    strictPort: true,
  },
})

await server.listen()
server.printUrls()

async function close() {
  await server.close()
  process.exit(0)
}

process.on('SIGTERM', close)
process.on('SIGINT', close)
