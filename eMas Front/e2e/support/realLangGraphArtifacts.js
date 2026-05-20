import fs from 'node:fs'
import path from 'node:path'

import { expect as baseExpect, test as base } from '@playwright/test'

import { realLangGraphArtifactDir } from './fullStackEnv.js'

const repoRoot = path.resolve(process.cwd(), '..')
const artifactDir = realLangGraphArtifactDir(repoRoot)

export const test = base.extend({
  page: async ({ page }, use, testInfo) => {
    const browserConsole = []
    const networkFailures = []

    page.on('console', (message) => {
      if (['error', 'warning'].includes(message.type())) {
        browserConsole.push({
          type: message.type(),
          text: message.text(),
          location: message.location(),
        })
      }
    })
    page.on('pageerror', (error) => {
      browserConsole.push({ type: 'pageerror', text: error?.stack || error?.message || String(error) })
    })
    page.on('requestfailed', (request) => {
      networkFailures.push({
        method: request.method(),
        url: request.url(),
        failure: request.failure()?.errorText || '',
      })
    })
    page.on('response', (response) => {
      if (response.status() >= 400) {
        networkFailures.push({
          method: response.request().method(),
          url: response.url(),
          status: response.status(),
          statusText: response.statusText(),
        })
      }
    })

    await use(page)

    if (browserConsole.length) {
      await testInfo.attach('browser-console.json', {
        body: JSON.stringify(browserConsole, null, 2),
        contentType: 'application/json',
      })
    }
    if (networkFailures.length) {
      await testInfo.attach('network-failures.json', {
        body: JSON.stringify(networkFailures, null, 2),
        contentType: 'application/json',
      })
    }
    if (testInfo.status !== testInfo.expectedStatus) {
      await attachRealLangGraphStackArtifacts(testInfo)
    }
  },
})

export const expect = baseExpect

async function attachFileIfExists(testInfo, filePath, contentType = 'text/plain') {
  if (!fs.existsSync(filePath)) return
  await testInfo.attach(path.basename(filePath), {
    path: filePath,
    contentType,
  })
}

export async function attachRealLangGraphStackArtifacts(testInfo) {
  await attachFileIfExists(testInfo, path.join(artifactDir, 'env-fingerprint.json'), 'application/json')
  await attachFileIfExists(testInfo, path.join(artifactDir, 'go-api.log'))
  await attachFileIfExists(testInfo, path.join(artifactDir, 'factory-agent.log'))
  await attachFileIfExists(testInfo, path.join(artifactDir, 'vite.log'))
  await attachFileIfExists(testInfo, path.join(artifactDir, 'real-langgraph-stack.log'))
}
