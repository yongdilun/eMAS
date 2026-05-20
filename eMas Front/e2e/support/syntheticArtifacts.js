import { expect as baseExpect, test as base } from '@playwright/test'

import { attachSyntheticResults, classifySyntheticSignal, recordSyntheticResult } from './syntheticReporter.js'
import { redactSensitiveText } from './syntheticEnv.js'

export const test = base.extend({
  page: async ({ page }, use, testInfo) => {
    const browserConsole = []
    const networkFailures = []
    let recorded = false
    const started = Date.now()

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

    testInfo.recordSyntheticResult = (result) => {
      recorded = true
      return recordSyntheticResult(testInfo, result)
    }

    await use(page)

    if (!recorded) {
      const failed = testInfo.status !== testInfo.expectedStatus
      recordSyntheticResult(testInfo, {
        status: failed ? 'failed' : 'passed',
        metrics: { durationMs: Date.now() - started },
        alerts: failed ? classifySyntheticSignal({ missingFinalAnswer: true }) : [],
      })
    }

    if (browserConsole.length) {
      await testInfo.attach('browser-console-redacted.json', {
        body: redactSensitiveText(browserConsole),
        contentType: 'application/json',
      })
    }
    if (networkFailures.length) {
      await testInfo.attach('network-failures-redacted.json', {
        body: redactSensitiveText(networkFailures),
        contentType: 'application/json',
      })
    }
    if (testInfo.status !== testInfo.expectedStatus) {
      try {
        await testInfo.attach('synthetic-redacted-page.png', {
          body: await page.screenshot({
            fullPage: true,
            mask: [page.getByRole('dialog')],
            maskColor: '#111827',
          }),
          contentType: 'image/png',
        })
      } catch {
        // Failure artifacts are best-effort because the page may already be closed.
      }
      await attachSyntheticResults(testInfo)
    }
  },
})

export const expect = baseExpect

