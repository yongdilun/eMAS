import assert from 'node:assert/strict'
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'

export async function createViteSsrServer() {
  return createServer({
    appType: 'custom',
    logLevel: 'error',
    server: { middlewareMode: true, hmr: false },
  })
}

export function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://127.0.0.1/',
  })

  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  Object.defineProperty(globalThis, 'window', { configurable: true, value: dom.window })
  Object.defineProperty(globalThis, 'document', { configurable: true, value: dom.window.document })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
  globalThis.HTMLElement = dom.window.HTMLElement
  globalThis.HTMLInputElement = dom.window.HTMLInputElement
  globalThis.HTMLTextAreaElement = dom.window.HTMLTextAreaElement
  globalThis.Event = dom.window.Event
  globalThis.MouseEvent = dom.window.MouseEvent

  return () => {
    dom.window.close()
    delete globalThis.window
    delete globalThis.document
    delete globalThis.navigator
    delete globalThis.HTMLElement
    delete globalThis.HTMLInputElement
    delete globalThis.HTMLTextAreaElement
    delete globalThis.Event
    delete globalThis.MouseEvent
    delete globalThis.IS_REACT_ACT_ENVIRONMENT
  }
}

export async function render(element) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)

  await act(async () => {
    root.render(element)
  })

  return {
    container,
    text: () => normalizeText(container.textContent),
    rerender: async (nextElement) => {
      await act(async () => {
        root.render(nextElement)
      })
    },
    unmount: async () => {
      await act(async () => {
        root.unmount()
      })
      container.remove()
    },
  }
}

export async function click(element) {
  assert.ok(element, 'Expected element to click')
  await act(async () => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
  })
}

export async function hover(element) {
  assert.ok(element, 'Expected element to hover')
  await act(async () => {
    element.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true }))
  })
}

export async function flushEffects() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

export async function waitFor(assertion, { timeoutMs = 1000, intervalMs = 10 } = {}) {
  const started = Date.now()
  let lastError

  while (Date.now() - started < timeoutMs) {
    try {
      return assertion()
    } catch (err) {
      lastError = err
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, intervalMs))
      })
    }
  }

  throw lastError
}

export function byText(container, text) {
  const needle = String(text)
  return Array.from(container.querySelectorAll('*')).find((node) =>
    normalizeText(node.textContent).includes(needle),
  )
}

export function normalizeText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

export { React }
