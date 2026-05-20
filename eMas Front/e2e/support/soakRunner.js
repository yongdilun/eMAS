import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn, spawnSync } from 'node:child_process'

import { waitForPortsClosed } from './resourceMetrics.js'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const frontendRoot = path.resolve(__dirname, '..', '..')
const defaultArtifactDir = path.join(frontendRoot, 'test-results', 'reliability-soak')

function npmCommandArgs(playwrightArgs) {
  const npmCli =
    process.env.npm_execpath ||
    path.join(path.dirname(process.execPath), 'node_modules', 'npm', 'bin', 'npm-cli.js')
  return [process.execPath, [npmCli, 'run', 'test:e2e', '--', ...playwrightArgs]]
}

function tail(value, max = 12_000) {
  const text = String(value || '')
  return text.length > max ? text.slice(text.length - max) : text
}

function killProcessTree(pid) {
  if (!pid) return
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true })
    return
  }
  try {
    process.kill(pid, 'SIGTERM')
  } catch {
    // Process already exited.
  }
}

function childEnv(extra = {}) {
  const env = { ...process.env, ...extra }
  for (const key of [
    'PLAYWRIGHT_FACTORY_AGENT_PORT',
    'PLAYWRIGHT_VITE_PORT',
    'PLAYWRIGHT_SEEDED_GO_API_PORT',
    'PLAYWRIGHT_SEEDED_FACTORY_AGENT_PORT',
    'PLAYWRIGHT_SEEDED_VITE_PORT',
    'PLAYWRIGHT_RELEASE_GO_API_PORT',
    'PLAYWRIGHT_RELEASE_FACTORY_AGENT_PORT',
    'PLAYWRIGHT_RELEASE_PROXY_PORT',
  ]) {
    if (!(key in extra)) delete env[key]
  }
  return env
}

function childOutputArgs(options, iteration, label) {
  const root = path.join(options.artifactDir || defaultArtifactDir, 'child-results', `iteration-${iteration + 1}`, label)
  return ['--output', root, '--reporter=list']
}

function commandMatrixForIteration(iteration, options = {}) {
  const base = Number(options.portBase || process.env.PLAYWRIGHT_RELIABILITY_PORT_BASE || 35_000 + (process.pid % 2_000))
  const offset = iteration * 500
  const mockedFactoryAgentPort = base + offset + 11
  const mockedVitePort = base + offset + 12
  const seededBase = base + offset + 100
  const releaseBase = base + offset + 250

  const commands = [
    {
      label: 'mocked-chromium-smoke',
      args: ['--project=chromium', 'e2e/specs/chat-happy-path.spec.js', ...childOutputArgs(options, iteration, 'mocked-chromium-smoke')],
      env: childEnv({
        PLAYWRIGHT_FACTORY_AGENT_PORT: String(mockedFactoryAgentPort),
        PLAYWRIGHT_VITE_PORT: String(mockedVitePort),
        PLAYWRIGHT_RELIABILITY_CHILD: '1',
      }),
      ports: [mockedFactoryAgentPort, mockedVitePort],
      timeoutMs: 120_000,
    },
    {
      label: 'seeded-chromium-smoke',
      args: [
        '--project=chromium-seeded',
        'e2e/specs/full-stack-seeded.spec.js',
        '--grep',
        'scenario 31',
        ...childOutputArgs(options, iteration, 'seeded-chromium-smoke'),
      ],
      env: childEnv({
        PLAYWRIGHT_SEEDED_PORT_BASE: String(seededBase),
        PLAYWRIGHT_RELIABILITY_CHILD: '1',
      }),
      ports: [seededBase + 11, seededBase + 12, seededBase + 13],
      timeoutMs: 180_000,
    },
  ]

  if (options.includeRelease !== false) {
    commands.push({
      label: 'release-chromium-smoke',
      args: [
        '--project=chromium-release',
        'e2e/specs/release-validation.spec.js',
        '--grep',
        'scenario 53',
        ...childOutputArgs(options, iteration, 'release-chromium-smoke'),
      ],
      env: childEnv({
        PLAYWRIGHT_RELEASE_PORT_BASE: String(releaseBase),
        PLAYWRIGHT_RELIABILITY_CHILD: '1',
      }),
      ports: [releaseBase + 1, releaseBase + 2, releaseBase + 3],
      timeoutMs: 240_000,
    })
  }

  return commands
}

export function reliabilitySoakPlan(options = {}) {
  const repeat = Number(options.repeat || process.env.PLAYWRIGHT_RELIABILITY_SOAK_REPEAT || 1)
  const runs = []
  for (let iteration = 0; iteration < repeat; iteration += 1) {
    for (const command of commandMatrixForIteration(iteration, options)) {
      runs.push({ iteration: iteration + 1, ...command })
    }
  }
  return runs
}

async function runCommand(command) {
  const [cmd, args] = npmCommandArgs(command.args)
  const startedAt = Date.now()
  let stdout = ''
  let stderr = ''
  let timedOut = false

  const child = spawn(cmd, args, {
    cwd: frontendRoot,
    env: command.env,
    shell: false,
    windowsHide: true,
  })

  const timeout = setTimeout(() => {
    timedOut = true
    killProcessTree(child.pid)
  }, command.timeoutMs)

  child.stdout.on('data', (chunk) => {
    stdout += chunk.toString()
  })
  child.stderr.on('data', (chunk) => {
    stderr += chunk.toString()
  })

  const exit = await new Promise((resolve) => {
    child.on('exit', (code, signal) => resolve({ code, signal }))
    child.on('error', (error) => resolve({ code: null, signal: null, error }))
  })
  clearTimeout(timeout)

  const ports = await waitForPortsClosed(command.ports)
  const result = {
    label: command.label,
    iteration: command.iteration,
    args: command.args,
    ports: command.ports,
    duration_ms: Date.now() - startedAt,
    exit_code: exit.code,
    signal: exit.signal,
    timed_out: timedOut,
    ports_closed: ports.closed,
    open_ports: ports.open_ports,
    stdout_tail: tail(stdout),
    stderr_tail: tail(stderr),
  }

  if (exit.error) {
    result.error = exit.error.message || String(exit.error)
  }
  return result
}

export async function runReliabilitySoak(options = {}) {
  const artifactDir = options.artifactDir || defaultArtifactDir
  fs.mkdirSync(artifactDir, { recursive: true })
  const startedAt = new Date().toISOString()
  const commands = reliabilitySoakPlan(options)
  const results = []

  for (const command of commands) {
    results.push(await runCommand(command))
  }

  const failures = results.filter(
    (result) => result.exit_code !== 0 || result.timed_out || !result.ports_closed || result.error,
  )
  const summary = {
    kind: 'phase15-reliability-soak',
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    repeat: Number(options.repeat || process.env.PLAYWRIGHT_RELIABILITY_SOAK_REPEAT || 1),
    include_release: options.includeRelease !== false,
    results,
    failures,
  }
  const resultPath = path.join(artifactDir, 'soak-results.json')
  fs.writeFileSync(resultPath, JSON.stringify(summary, null, 2))
  summary.result_path = resultPath
  return summary
}

function argValue(name, fallback = null) {
  const index = process.argv.indexOf(name)
  if (index >= 0 && process.argv[index + 1]) return process.argv[index + 1]
  const inline = process.argv.find((arg) => arg.startsWith(`${name}=`))
  return inline ? inline.slice(name.length + 1) : fallback
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  const repeat = Number(argValue('--repeat', process.env.PLAYWRIGHT_RELIABILITY_SOAK_REPEAT || 1))
  const includeRelease = !process.argv.includes('--skip-release')
  runReliabilitySoak({ repeat, includeRelease })
    .then((summary) => {
      console.log(JSON.stringify({
        result_path: summary.result_path,
        failures: summary.failures.length,
        results: summary.results.length,
      }, null, 2))
      process.exit(summary.failures.length ? 1 : 0)
    })
    .catch((err) => {
      console.error(err?.stack || err)
      process.exit(1)
    })
}
