/**
 * LangGraph / bundle-style approvals repeat the same job list in `content`,
 * timeline copy, and `risk_summary`. These helpers keep one concise headline
 * in the main bubble and strip enumeration from the risk line.
 *
 * Rich tables use the same shape as `TablePresentation` in `TurnBlocks.jsx`:
 * `{ render_hint: 'table', table: { columns: [{ key, label }], rows: [...], displayed_rows, total_rows } }`.
 */

const PRIO = '(low|medium|high|urgent)'

export function isInterruptBundleApprovalText(text) {
  const s = String(text || '').toLowerCase()
  return (
    s.includes('jobs affected:') ||
    s.includes('current vs requested priority') ||
    s.includes('current priority vs requested priority')
  )
}

/**
 * @returns {{ jobs: { jobId: string, previousPriority: string, newPriority: string }[], fromPriority: string, toPriority: string, headline: string } | null}
 */
export function parseInterruptApprovalBundle(text) {
  const raw = String(text || '')
  if (!isInterruptBundleApprovalText(raw)) return null

  const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
  const byJob = new Map()

  const addRow = (jobId, prev, next) => {
    const id = String(jobId || '').toUpperCase()
    if (!/^JOB-/.test(id)) return
    const p = String(prev || '').toLowerCase()
    const n = String(next || '').toLowerCase()
    if (!p || !n) return
    byJob.set(id, { jobId: id, previousPriority: p, newPriority: n })
  }

  /** Rows from "N. JOB-… (priority set to X)" — previous comes from global context. */
  const numberedOnly = []

  for (const line of lines) {
    const curReq = line.match(
      new RegExp(`^[-*]\\s*(JOB-[A-Z0-9-]+):\\s*.*?\\(current:\\s*${PRIO}\\s*,\\s*requested:\\s*${PRIO}\\)`, 'i'),
    )
    if (curReq) {
      addRow(curReq[1], curReq[2], curReq[3])
      continue
    }
    const fromReq = line.match(
      new RegExp(
        `^[-*]\\s*(JOB-[A-Z0-9-]+):\\s*priority\\s+set\\s+to\\s+${PRIO}\\s*\\(\\s*from\\s+${PRIO}\\s*\\)`,
        'i',
      ),
    )
    if (fromReq) {
      addRow(fromReq[1], fromReq[3], fromReq[2])
      continue
    }
    const numList = line.match(
      new RegExp(`^\\d+\\.\\s*(JOB-[A-Z0-9-]+)\\s*\\(\\s*priority\\s+set\\s+to\\s+${PRIO}\\s*\\)`, 'i'),
    )
    if (numList) {
      numberedOnly.push({
        jobId: numList[1].toUpperCase(),
        newPriority: numList[2].toLowerCase(),
      })
    }
  }

  const globalFrom =
    raw.match(new RegExp(`\\(from\\s+${PRIO}\\)`, 'i'))?.[1]?.toLowerCase() ||
    raw.match(new RegExp(`current:\\s*${PRIO}\\s*,\\s*requested:\\s*${PRIO}`, 'i'))?.[1]?.toLowerCase() ||
    ''

  const globalTo =
    raw.match(new RegExp(`requested:\\s*${PRIO}`, 'i'))?.[1]?.toLowerCase() ||
    raw.match(new RegExp(`priority\\s+set\\s+to\\s+${PRIO}`, 'i'))?.[1]?.toLowerCase() ||
    ''

  for (const { jobId, newPriority } of numberedOnly) {
    if (byJob.has(jobId)) continue
    const prev = globalFrom
    const next = newPriority || globalTo
    if (prev && next) addRow(jobId, prev, next)
  }

  const jobs = []
  for (const [, row] of byJob) {
    const prev = row.previousPriority || globalFrom
    const next = row.newPriority || globalTo
    if (prev && next) jobs.push({ jobId: row.jobId, previousPriority: prev, newPriority: next })
  }

  if (!jobs.length) return null

  const fromPriority = jobs[0].previousPriority
  const toPriority = jobs[0].newPriority
  const sameFrom = jobs.every((j) => j.previousPriority === fromPriority)
  const sameTo = jobs.every((j) => j.newPriority === toPriority)
  if (!sameFrom || !sameTo) {
    jobs.sort((a, b) => a.jobId.localeCompare(b.jobId))
    return {
      jobs,
      fromPriority: '',
      toPriority: '',
      headline: `${jobs.length} job${jobs.length === 1 ? '' : 's'} pending approval (mixed priority changes).`,
    }
  }

  jobs.sort((a, b) => a.jobId.localeCompare(b.jobId))
  const n = jobs.length
  const headline = `${n} job${n === 1 ? '' : 's'} will be updated from ${fromPriority} to ${toPriority} priority.`

  return { jobs, fromPriority, toPriority, headline }
}

/** Map backend ``bundle_ui`` (job_priority_bundle) to `TablePresentation` input. */
export function presentationFromBundleUi(bundleUi) {
  if (!bundleUi || typeof bundleUi !== 'object') return null
  if (bundleUi.kind !== 'job_priority_bundle') return null
  const rows = bundleUi.rows
  if (!Array.isArray(rows) || !rows.length) return null
  return {
    render_hint: 'table',
    table: {
      columns: [
        { key: 'job_id', label: 'Job ID' },
        { key: 'previous_priority', label: 'Previous Priority' },
        { key: 'new_priority', label: 'New Priority' },
      ],
      rows: rows.map((r) => ({
        job_id: String(r.job_id ?? ''),
        previous_priority: String(r.previous_priority ?? ''),
        new_priority: String(r.new_priority ?? ''),
      })),
      displayed_rows: rows.length,
      total_rows: rows.length,
    },
  }
}

/** Structured table from parsed free-text (legacy sessions without `bundle_ui`). */
export function buildApprovalBundleTablePresentation(parsed) {
  if (!parsed?.jobs?.length) return null
  return {
    render_hint: 'table',
    table: {
      columns: [
        { key: 'job_id', label: 'Job ID' },
        { key: 'previous_priority', label: 'Previous Priority' },
        { key: 'new_priority', label: 'New Priority' },
      ],
      rows: parsed.jobs.map((j) => ({
        job_id: j.jobId,
        previous_priority: j.previousPriority,
        new_priority: j.newPriority,
      })),
      displayed_rows: parsed.jobs.length,
      total_rows: parsed.jobs.length,
    },
  }
}

/**
 * Strip the leading "Waiting for your approval:" prefix from timeline `content`
 * so interrupt parsers see the raw bundle body.
 */
export function extractApprovalInterruptBody(content) {
  const c = String(content || '').trim()
  if (!c) return ''
  const m = c.match(/^waiting\s+for\s+your\s+approval\s*:\s*(.+)/is)
  if (m) return m[1].trim()
  return c
}

/**
 * Prefer structured ``bundle_ui``; otherwise parse legacy interrupt markdown from
 * `risk_summary`-style text (timeline `content` or DB `risk_summary`).
 */
export function resolveApprovalTablePresentation(approvalLike) {
  if (!approvalLike) return null
  const args =
    approvalLike.details?.args && typeof approvalLike.details.args === 'object' && !Array.isArray(approvalLike.details.args)
      ? approvalLike.details.args
      : approvalLike.args && typeof approvalLike.args === 'object' && !Array.isArray(approvalLike.args)
        ? approvalLike.args
        : {}
  const bui = args.bundle_ui
  if (bui && typeof bui === 'object') {
    const fromStruct = presentationFromBundleUi(bui)
    if (fromStruct) return fromStruct
  }
  const chunks = [
    extractApprovalInterruptBody(approvalLike.content),
    String(approvalLike.risk_summary || '').trim(),
    String(approvalLike.details?.risk_summary || '').trim(),
  ].filter(Boolean)
  for (const chunk of chunks) {
    const parsed = parseInterruptApprovalBundle(chunk)
    const pres = buildApprovalBundleTablePresentation(parsed)
    if (pres) return pres
  }
  return null
}

/**
 * Lead-in before the first "Jobs affected:" (or similar) bulk list — safe to show as Risk.
 */
export function shortenApprovalRiskSummary(riskSummary) {
  const s = String(riskSummary || '').trim()
  if (!s) return ''
  const byJobs = s.split(/\bJobs affected:\s*/i)
  if (byJobs.length > 1) {
    const lead = byJobs[0].trim()
    if (lead.length >= 12) return lead.replace(/\s+$/, '')
  }
  const byCurrent = s.split(/\bCurrent vs requested priority:\s*/i)
  if (byCurrent.length > 1) {
    const lead = byCurrent[0].trim()
    if (lead.length >= 12) return lead.replace(/\s+$/, '')
  }
  const byCurAlt = s.split(/\bCurrent priority vs requested priority:\s*/i)
  if (byCurAlt.length > 1) {
    const lead = byCurAlt[0].trim()
    if (lead.length >= 12) return lead.replace(/\s+$/, '')
  }
  if (s.length > 220) return `${s.slice(0, 200).trim()}…`
  return s
}

/**
 * Short assistant headline when the raw approval body is a long interrupt bundle.
 */
export function compactInterruptApprovalHeadline(text) {
  const parsed = parseInterruptApprovalBundle(String(text || ''))
  if (parsed?.headline) return parsed.headline
  if (isInterruptBundleApprovalText(text)) return 'A bundled factory change needs your approval.'
  return null
}
