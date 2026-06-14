import { defineConfig, devices } from '@playwright/test'
import { realLangGraphRuntimeEnv, seededRuntimeEnv } from './e2e/support/fullStackEnv.js'
import { releaseRuntimeEnv } from './e2e/support/releaseEnv.js'
import { syntheticRuntimeEnv } from './e2e/support/syntheticEnv.js'

const factoryAgentPort = Number(process.env.PLAYWRIGHT_FACTORY_AGENT_PORT || 8015)
const appPort = Number(process.env.PLAYWRIGHT_VITE_PORT || 4175)
const seededEnv = seededRuntimeEnv()
const realLangGraphEnv = realLangGraphRuntimeEnv()
const releaseEnv = releaseRuntimeEnv()
const selectedProjects = process.argv
  .flatMap((arg, index, all) => (arg === '--project' ? [all[index + 1]] : arg.startsWith('--project=') ? [arg.slice('--project='.length)] : []))
  .filter(Boolean)
const selectedGrep = process.argv
  .flatMap((arg, index, all) => (arg === '--grep' ? [all[index + 1]] : arg.startsWith('--grep=') ? [arg.slice('--grep='.length)] : []))
  .filter(Boolean)
const selectedSeeded = selectedProjects.some((project) => project === 'chromium-seeded')
const selectedDirectShortageResolution = process.argv.some((arg) => arg.includes('full-stack-shortage-resolution.spec.js'))
const selectedRealLangGraph = selectedProjects.some((project) => project === 'chromium-real-langgraph')
const selectedRelease = selectedProjects.some((project) => project === 'chromium-release')
const selectedSynthetic = selectedProjects.some((project) => project === 'chromium-synthetic')
const selectedMocked = selectedProjects.length === 0 || selectedProjects.some((project) => project === 'chromium')
const selectedReliability = selectedGrep.some((grep) => grep.includes('@reliability'))
const selectedSecurityPrivacy = selectedGrep.some((grep) => grep.includes('@security') || grep.includes('@privacy'))
const selectedOperational = selectedGrep.some((grep) => grep.includes('@operational'))
const syntheticEnv = syntheticRuntimeEnv({ validate: selectedSynthetic })
const mockedIgnorePatterns = ['(full-stack|release|real-langgraph)-.*\\.spec\\.js', 'production-synthetic\\.spec\\.js']
if (!selectedReliability) mockedIgnorePatterns.push('reliability-soak\\.spec\\.js')
if (!selectedSecurityPrivacy) mockedIgnorePatterns.push('security-privacy\\.spec\\.js')
if (!selectedOperational) mockedIgnorePatterns.push('operational-readiness\\.spec\\.js')
const mockedTestIgnore = new RegExp(mockedIgnorePatterns.join('|'))
if (selectedOperational) {
  process.env.PLAYWRIGHT_CHAT_EMERGENCY_DISABLED = '1'
  process.env.PLAYWRIGHT_CHAT_EMERGENCY_DISABLED_REASON =
    'Operational readiness drill: Factory Agent chat is temporarily disabled by the emergency feature flag.'
}
process.env.PLAYWRIGHT_SEEDED_GO_API_PORT = String(seededEnv.goApiPort)
process.env.PLAYWRIGHT_SEEDED_FACTORY_AGENT_PORT = String(seededEnv.factoryAgentPort)
process.env.PLAYWRIGHT_SEEDED_VITE_PORT = String(seededEnv.vitePort)
process.env.PLAYWRIGHT_SEEDED_ARTIFACT_DIR = seededEnv.artifactDir
process.env.PLAYWRIGHT_REAL_LANGGRAPH_GO_API_PORT = String(realLangGraphEnv.goApiPort)
process.env.PLAYWRIGHT_REAL_LANGGRAPH_FACTORY_AGENT_PORT = String(realLangGraphEnv.factoryAgentPort)
process.env.PLAYWRIGHT_REAL_LANGGRAPH_VITE_PORT = String(realLangGraphEnv.vitePort)
process.env.PLAYWRIGHT_REAL_LANGGRAPH_ARTIFACT_DIR = realLangGraphEnv.artifactDir
process.env.PLAYWRIGHT_RELEASE_GO_API_PORT = String(releaseEnv.goApiPort)
process.env.PLAYWRIGHT_RELEASE_FACTORY_AGENT_PORT = String(releaseEnv.factoryAgentPort)
process.env.PLAYWRIGHT_RELEASE_PROXY_PORT = String(releaseEnv.proxyPort)
process.env.PLAYWRIGHT_RELEASE_ARTIFACT_DIR = releaseEnv.artifactDir
process.env.PLAYWRIGHT_RELEASE_BUILD_ID = releaseEnv.releaseBuildId
process.env.PLAYWRIGHT_SYNTHETIC_ARTIFACT_DIR = syntheticEnv.artifactDir
process.env.PLAYWRIGHT_SYNTHETIC_RESULT_PATH = syntheticEnv.resultPath
process.env.PLAYWRIGHT_SYNTHETIC_NDJSON_PATH = syntheticEnv.ndjsonPath
process.env.PLAYWRIGHT_SYNTHETIC_BASE_URL = syntheticEnv.baseUrl
process.env.PLAYWRIGHT_SYNTHETIC_MODE = syntheticEnv.mode

const webServer = []
if (selectedMocked) {
  webServer.push(
    {
      command: `node e2e/mock-server/factoryAgentMockServer.js --port ${factoryAgentPort}`,
      url: `http://127.0.0.1:${factoryAgentPort}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: `node e2e/support/startViteForPlaywright.js --port ${appPort} --factory-agent-url http://127.0.0.1:${factoryAgentPort}${selectedReliability ? ' --request-timeout-ms 1200' : ''}`,
      url: `http://127.0.0.1:${appPort}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  )
}
if (selectedSeeded) {
  webServer.push({
    command: `node e2e/support/startSeededStackForPlaywright.js${selectedDirectShortageResolution ? ' --skip-factory-agent' : ''}`,
    url: seededEnv.viteBaseUrl,
    reuseExistingServer: false,
    timeout: 150_000,
  })
}
if (selectedRealLangGraph) {
  webServer.push({
    command: `node e2e/support/startRealLangGraphStackForPlaywright.js`,
    url: realLangGraphEnv.viteBaseUrl,
    reuseExistingServer: false,
    timeout: 150_000,
  })
}
if (selectedRelease) {
  webServer.push({
    command: `node e2e/support/startReleaseStackForPlaywright.js`,
    url: releaseEnv.releaseFactoryAgentReadyUrl,
    reuseExistingServer: false,
    timeout: 180_000,
  })
}
if (selectedSynthetic && !syntheticEnv.live) {
  webServer.push({
    command: `node e2e/support/startReleaseStackForPlaywright.js`,
    url: releaseEnv.releaseFactoryAgentReadyUrl,
    reuseExistingServer: false,
    timeout: 180_000,
  })
}

export default defineConfig({
  testDir: './e2e/specs',
  timeout: selectedReliability
    ? 360_000
    : selectedRelease || selectedSynthetic || selectedRealLangGraph
      ? 90_000
      : selectedSeeded
        ? 60_000
        : 30_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: true,
  workers: selectedSeeded || selectedRealLangGraph || selectedRelease || selectedSynthetic || process.env.CI ? 1 : undefined,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://127.0.0.1:${appPort}`,
    trace: process.env.CI ? 'on-first-retry' : 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer,
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      testIgnore: mockedTestIgnore,
    },
    {
      name: 'chromium-seeded',
      testMatch: /full-stack-.*\.spec\.js/,
      outputDir: 'playwright-output/chromium-seeded',
      use: {
        ...devices['Desktop Chrome'],
        baseURL: seededEnv.viteBaseUrl,
      },
    },
    {
      name: 'chromium-real-langgraph',
      testMatch: /real-langgraph-.*\.spec\.js/,
      use: {
        ...devices['Desktop Chrome'],
        baseURL: realLangGraphEnv.viteBaseUrl,
      },
    },
    {
      name: 'chromium-release',
      testMatch: /release-.*\.spec\.js/,
      use: {
        ...devices['Desktop Chrome'],
        baseURL: releaseEnv.releaseBaseUrl,
        trace: 'on',
        screenshot: 'on',
        video: 'on',
      },
    },
    {
      name: 'chromium-synthetic',
      testMatch: /production-synthetic\.spec\.js/,
      use: {
        ...devices['Desktop Chrome'],
        baseURL: syntheticEnv.baseUrl,
        trace: 'retain-on-failure',
        screenshot: 'off',
        video: 'off',
      },
    },
  ],
})
