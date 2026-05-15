import { defineConfig, devices } from '@playwright/test'

const factoryAgentPort = Number(process.env.PLAYWRIGHT_FACTORY_AGENT_PORT || 8015)
const appPort = Number(process.env.PLAYWRIGHT_VITE_PORT || 4175)

export default defineConfig({
  testDir: './e2e/specs',
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: true,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://127.0.0.1:${appPort}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: `node e2e/mock-server/factoryAgentMockServer.js --port ${factoryAgentPort}`,
      url: `http://127.0.0.1:${factoryAgentPort}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: `node e2e/support/startViteForPlaywright.js --port ${appPort} --factory-agent-url http://127.0.0.1:${factoryAgentPort}`,
      url: `http://127.0.0.1:${appPort}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
