import { createServer } from 'vite'

const args = new Map()
for (let i = 2; i < process.argv.length; i += 2) {
  args.set(process.argv[i], process.argv[i + 1])
}

const port = Number(args.get('--port') || process.env.PORT || 4175)
const factoryAgentUrl = args.get('--factory-agent-url') || process.env.VITE_FACTORY_AGENT_BASE_URL

if (!factoryAgentUrl) {
  throw new Error('Missing --factory-agent-url for Playwright Vite server')
}

process.env.VITE_FACTORY_AGENT_BASE_URL = factoryAgentUrl

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
