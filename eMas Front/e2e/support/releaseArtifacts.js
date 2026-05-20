import fs from 'node:fs'
import path from 'node:path'

import { expect as baseExpect, test as base } from '@playwright/test'

import { redactSensitiveArtifactText } from './artifactRedaction.js'
import { releaseArtifactDir } from './releaseEnv.js'

const repoRoot = path.resolve(process.cwd(), '..')
const artifactDir = releaseArtifactDir(repoRoot)

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
        body: redactSensitiveArtifactText(browserConsole),
        contentType: 'application/json',
      })
    }
    if (networkFailures.length) {
      await testInfo.attach('network-failures.json', {
        body: redactSensitiveArtifactText(networkFailures),
        contentType: 'application/json',
      })
    }
    if (testInfo.status !== testInfo.expectedStatus) {
      await attachReleaseStackArtifacts(testInfo)
    }
  },
})

export const expect = baseExpect

async function attachFileIfExists(testInfo, filePath, contentType = 'text/plain') {
  if (!fs.existsSync(filePath)) return
  if (contentType.startsWith('text/') || contentType === 'application/json') {
    await testInfo.attach(path.basename(filePath), {
      body: redactSensitiveArtifactText(fs.readFileSync(filePath, 'utf8')),
      contentType,
    })
    return
  }
  await testInfo.attach(path.basename(filePath), {
    path: filePath,
    contentType,
  })
}

export async function attachReleaseStackArtifacts(testInfo) {
  await attachFileIfExists(testInfo, path.join(artifactDir, 'env-fingerprint.json'), 'application/json')
  await attachFileIfExists(testInfo, path.join(artifactDir, 'go-api.log'))
  await attachFileIfExists(testInfo, path.join(artifactDir, 'factory-agent.log'))
  await attachFileIfExists(testInfo, path.join(artifactDir, 'release-proxy.log'))
  await attachFileIfExists(testInfo, path.join(artifactDir, 'release-stack.log'))
  await attachFileIfExists(testInfo, path.join(artifactDir, 'build.log'))
}
