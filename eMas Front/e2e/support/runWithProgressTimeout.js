import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

const args = process.argv.slice(2)

function readNumberOption(name, fallback) {
  const prefix = `${name}=`
  const inlineIndex = args.findIndex((arg) => arg.startsWith(prefix))
  if (inlineIndex >= 0) {
    const value = Number(args.splice(inlineIndex, 1)[0].slice(prefix.length))
    return Number.isFinite(value) && value > 0 ? value : fallback
  }

  const separateIndex = args.indexOf(name)
  if (separateIndex >= 0) {
    const value = Number(args[separateIndex + 1])
    args.splice(separateIndex, 2)
    return Number.isFinite(value) && value > 0 ? value : fallback
  }

  return fallback
}

const idleTimeoutMs = readNumberOption('--idle-timeout-ms', 120_000)
const hardTimeoutMs = readNumberOption('--hard-timeout-ms', 300_000)
const commandStart = args.indexOf('--')
const commandArgs = commandStart >= 0 ? args.slice(commandStart + 1) : args

if (commandArgs.length === 0) {
  console.error('[progress-timeout] missing command after --')
  process.exit(2)
}

const [command, ...commandRest] = commandArgs
const startedAt = Date.now()
let lastOutputAt = startedAt
let timedOut = false

function elapsedSeconds(since) {
  return Math.floor((Date.now() - since) / 1000)
}

function stopProcessTree(child) {
  if (!child.pid) return
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
    return
  }
  try {
    process.kill(-child.pid, 'SIGTERM')
  } catch {
    child.kill('SIGTERM')
  }
}

function resolveWindowsCommand(command) {
  if (process.platform !== 'win32') return command
  if (path.extname(command)) return command

  const pathDirs = (process.env.PATH || '').split(path.delimiter).filter(Boolean)
  const extensions = ['.cmd', '.exe', '.bat', '']
  for (const dir of pathDirs) {
    for (const extension of extensions) {
      const candidate = path.join(dir, `${command}${extension}`)
      if (fs.existsSync(candidate)) return candidate
    }
  }
  return command
}

function buildSpawnArgs(command, commandRest) {
  const resolvedCommand = resolveWindowsCommand(command)
  const extension = path.extname(resolvedCommand).toLowerCase()
  if (process.platform === 'win32' && (extension === '.cmd' || extension === '.bat')) {
    return { command: process.env.ComSpec || 'cmd.exe', args: ['/d', '/c', resolvedCommand, ...commandRest] }
  }
  return { command: resolvedCommand, args: commandRest }
}

const spawnArgs = buildSpawnArgs(command, commandRest)
const child = spawn(spawnArgs.command, spawnArgs.args, {
  stdio: ['ignore', 'pipe', 'pipe'],
  detached: process.platform !== 'win32',
  windowsHide: true,
})

console.error(
  `[progress-timeout] started: ${commandArgs.join(' ')} (idle ${Math.floor(idleTimeoutMs / 1000)}s, hard ${Math.floor(hardTimeoutMs / 1000)}s)`,
)

child.stdout.on('data', (chunk) => {
  lastOutputAt = Date.now()
  process.stdout.write(chunk)
})

child.stderr.on('data', (chunk) => {
  lastOutputAt = Date.now()
  process.stderr.write(chunk)
})

child.on('error', (err) => {
  console.error(`[progress-timeout] failed to start command: ${err.message}`)
})

const timer = setInterval(() => {
  const idleSeconds = elapsedSeconds(lastOutputAt)
  const totalSeconds = elapsedSeconds(startedAt)
  console.error(`[progress-timeout] waiting ${totalSeconds}s, no child output for ${idleSeconds}s`)

  if (Date.now() - lastOutputAt >= idleTimeoutMs) {
    timedOut = true
    console.error(`[progress-timeout] idle timeout after ${idleSeconds}s without child output`)
    stopProcessTree(child)
  } else if (Date.now() - startedAt >= hardTimeoutMs) {
    timedOut = true
    console.error(`[progress-timeout] hard timeout after ${totalSeconds}s`)
    stopProcessTree(child)
  }
}, 10_000)

child.on('exit', (code, signal) => {
  clearInterval(timer)
  if (timedOut) process.exit(124)
  if (signal) {
    console.error(`[progress-timeout] command exited with signal ${signal}`)
    process.exit(1)
  }
  process.exit(code ?? 0)
})

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    stopProcessTree(child)
    process.exit(signal === 'SIGINT' ? 130 : 143)
  })
}
