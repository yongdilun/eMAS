import net from 'node:net'

export async function browserResourceSnapshot(page) {
  return page.evaluate(() => {
    const memory = performance && 'memory' in performance ? performance.memory : null
    return {
      collected_at: new Date().toISOString(),
      dom_nodes: document.querySelectorAll('*').length,
      js_heap_used: memory?.usedJSHeapSize || null,
      js_heap_limit: memory?.jsHeapSizeLimit || null,
    }
  })
}

export function assertStableBrowserResources(expect, before, after, options = {}) {
  const maxDomNodes = options.maxDomNodes || 7_500
  const maxHeapBytes = options.maxHeapBytes || 180 * 1024 * 1024
  const maxHeapGrowthBytes = options.maxHeapGrowthBytes || 90 * 1024 * 1024

  expect(after.dom_nodes).toBeLessThan(maxDomNodes)
  if (after.js_heap_used != null) {
    expect(after.js_heap_used).toBeLessThan(maxHeapBytes)
  }
  if (before.js_heap_used != null && after.js_heap_used != null) {
    expect(after.js_heap_used - before.js_heap_used).toBeLessThan(maxHeapGrowthBytes)
  }
}

export function canConnectToPort(port, host = '127.0.0.1') {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port })
    socket.setTimeout(350)
    socket.on('connect', () => {
      socket.destroy()
      resolve(true)
    })
    socket.on('timeout', () => {
      socket.destroy()
      resolve(false)
    })
    socket.on('error', () => resolve(false))
  })
}

export async function waitForPortsClosed(ports, options = {}) {
  const timeoutMs = options.timeoutMs || 12_000
  const intervalMs = options.intervalMs || 250
  const deadline = Date.now() + timeoutMs
  const normalized = [...new Set((ports || []).map(Number).filter((port) => Number.isFinite(port) && port > 0))]

  while (Date.now() < deadline) {
    const open = []
    for (const port of normalized) {
      if (await canConnectToPort(port)) open.push(port)
    }
    if (open.length === 0) return { closed: true, open_ports: [] }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }

  const open = []
  for (const port of normalized) {
    if (await canConnectToPort(port)) open.push(port)
  }
  return { closed: open.length === 0, open_ports: open }
}
