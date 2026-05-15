import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

function normalizePathForSqlite(value) {
  return value.replace(/\\/g, '/')
}

export function seededPortPlan() {
  const base = Number(process.env.PLAYWRIGHT_SEEDED_PORT_BASE || 20_000 + (process.pid % 20_000))
  return {
    goApiPort: Number(process.env.PLAYWRIGHT_SEEDED_GO_API_PORT || base + 11),
    factoryAgentPort: Number(process.env.PLAYWRIGHT_SEEDED_FACTORY_AGENT_PORT || base + 12),
    vitePort: Number(process.env.PLAYWRIGHT_SEEDED_VITE_PORT || base + 13),
  }
}

export function seededArtifactDir(repoRoot = path.resolve(process.cwd(), '..')) {
  return path.resolve(
    process.env.PLAYWRIGHT_SEEDED_ARTIFACT_DIR || path.join(repoRoot, 'eMas Front', 'test-results', 'seeded-stack'),
  )
}

export function seededRuntimeEnv(repoRoot = path.resolve(process.cwd(), '..')) {
  const ports = seededPortPlan()
  const artifactDir = seededArtifactDir(repoRoot)
  const dbDir = path.join(artifactDir, 'db')
  fs.mkdirSync(dbDir, { recursive: true })

  const goApiBaseUrl = `http://127.0.0.1:${ports.goApiPort}/api/v1`
  const factoryAgentBaseUrl = `http://127.0.0.1:${ports.factoryAgentPort}`
  const viteBaseUrl = `http://127.0.0.1:${ports.vitePort}`
  const goDbPath = path.join(dbDir, `emas-${ports.goApiPort}.sqlite`)
  const factoryAgentDbPath = path.join(dbDir, `factory-agent-${ports.factoryAgentPort}.sqlite`)

  return {
    ...ports,
    repoRoot,
    artifactDir,
    goApiBaseUrl,
    factoryAgentBaseUrl,
    viteBaseUrl,
    goApiHealthUrl: `http://127.0.0.1:${ports.goApiPort}/health`,
    factoryAgentReadyUrl: `${factoryAgentBaseUrl}/ready`,
    openApiUrl: `http://127.0.0.1:${ports.goApiPort}/swagger/doc.json`,
    goDbPath,
    factoryAgentDbPath,
    factoryAgentDatabaseUrl: `sqlite+aiosqlite:///${normalizePathForSqlite(factoryAgentDbPath)}`,
    fingerprintPath: path.join(artifactDir, 'env-fingerprint.json'),
    platform: {
      pid: process.pid,
      node: process.version,
      cwd: process.cwd(),
      tmpdir: os.tmpdir(),
    },
  }
}
