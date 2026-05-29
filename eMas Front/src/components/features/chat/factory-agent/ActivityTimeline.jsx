import { useEffect, useMemo, useRef, useState } from 'react'
import {
    shouldAutoCollapseActivity,
    shouldShowActivityTimeline,
    truncateActivityAfterTerminal,
} from './activityTimelineUtils'

const stateIcon = {
    running: 'progress_activity',
    success: 'check',
    retry: 'sync',
    waiting: 'hourglass_empty',
    error: 'priority_high',
    complete: 'done_all',
}

const stateTone = {
    running: 'text-ink-muted bg-surface-3',
    success: 'text-primary bg-primary/10',
    retry: 'text-ink-muted bg-surface-3',
    waiting: 'text-ink-muted bg-surface-3',
    error: 'text-ink bg-surface-3',
    complete: 'text-primary bg-primary/10',
}

function MaterialActivityIcon({ icon, className = '' }) {
    return (
        <span
            aria-hidden="true"
            className={`material-symbols-outlined ${className}`}
            data-icon={icon}
        />
    )
}

function latestStep(steps) {
    if (!Array.isArray(steps) || !steps.length) return null
    return steps[steps.length - 1]
}

function findActiveStepIndex(rows) {
    if (!Array.isArray(rows) || !rows.length) return -1
    for (let i = rows.length - 1; i >= 0; i -= 1) {
        const st = rows[i]?.state
        if (st === 'running' || st === 'retry' || st === 'waiting') return i
    }
    const latest = rows[rows.length - 1]
    if (latest?.state === 'success') return rows.length - 1
    return -1
}

/** Marks the row still representing the active action, even if ids differ (e.g. server + client rows). */
function isCurrentStep(step, rows) {
    const idx = Array.isArray(rows) ? rows.indexOf(step) : -1
    if (idx < 0) return false
    return idx === findActiveStepIndex(rows)
}

function visualStateForStep(step, rows, isTerminal) {
    if (!isTerminal && !isCurrentStep(step, rows)) {
        const state = step?.state
        if (state === 'running' || state === 'retry' || state === 'waiting') return 'success'
    }
    if (!isTerminal && isCurrentStep(step, rows) && step?.state === 'success') {
        return 'running'
    }
    return step?.state
}

function hasRetryStory(rows) {
    return (Array.isArray(rows) ? rows : []).some((step) => {
        const label = String(step?.label || '')
        const detail = String(step?.detail || '')
        return step?.state === 'retry' || label.startsWith('Replanning') || label.startsWith('Retrying') || /Attempt \d+ of \d+/.test(detail)
    })
}

const ActivityTimeline = ({ steps = [] }) => {
    const rows = useMemo(() => truncateActivityAfterTerminal(steps), [steps])
    const rowIds = useMemo(() => rows.map((step) => String(step?.id || '')).filter(Boolean), [rows])
    const rowIdsKey = rowIds.join('\u001f')
    const latest = latestStep(rows)
    const isTerminal = latest?.state === 'complete' || latest?.state === 'error'
    const retryStory = hasRetryStory(rows)

    // Default collapsed; open while multiple in-flight steps arrive. When the run
    // finishes (complete / error), fold back to the summary strip once (user can
    // still expand to review the full list).
    const [expanded, setExpanded] = useState(() => Boolean(isTerminal && retryStory))
    const wasTerminalRef = useRef(isTerminal)
    const userCollapsedRef = useRef(false)
    const knownRowIdsRef = useRef(new Set(rowIds))
    const entryTimersRef = useRef([])
    const [enteringRowIds, setEnteringRowIds] = useState(() => new Set())

    useEffect(() => () => {
        entryTimersRef.current.forEach((timer) => clearTimeout(timer))
        entryTimersRef.current = []
    }, [])

    useEffect(() => {
        const becameTerminal = isTerminal && !wasTerminalRef.current
        wasTerminalRef.current = isTerminal

        if (becameTerminal) {
            userCollapsedRef.current = false
            setExpanded(Boolean(retryStory))
        } else if (!isTerminal && rows.length > 1 && !userCollapsedRef.current) {
            // While several steps are arriving (SSE + poll), keep the list open so
            // intermediates are visible; the header alone only reflects `latest`.
            setExpanded(true)
        } else if (!isTerminal && shouldAutoCollapseActivity(rows)) {
            userCollapsedRef.current = false
            setExpanded(false)
        } else if (rows.length <= 1) {
            userCollapsedRef.current = false
        }
    }, [isTerminal, retryStory, rows])

    useEffect(() => {
        const known = knownRowIdsRef.current
        const previousRowIds = Array.from(known)
        const appendedAfterKnownRows = previousRowIds.length > 0
            && previousRowIds.length < rowIds.length
            && previousRowIds.every((id, index) => rowIds[index] === id)
        const added = appendedAfterKnownRows ? rowIds.slice(previousRowIds.length) : []
        knownRowIdsRef.current = new Set(rowIds)
        if (!added.length) return

        setEnteringRowIds((prev) => new Set([...prev, ...added]))
        const timer = setTimeout(() => {
            setEnteringRowIds((prev) => {
                const next = new Set(prev)
                added.forEach((id) => next.delete(id))
                return next
            })
            entryTimersRef.current = entryTimersRef.current.filter((item) => item !== timer)
        }, 700)
        entryTimersRef.current.push(timer)
    }, [rowIdsKey, rowIds])

    if (!rows.length || !latest || !shouldShowActivityTimeline(rows)) return null

    const latestVisualState = visualStateForStep(latest, rows, isTerminal)
    const icon = stateIcon[latestVisualState] || 'progress_activity'
    const tone = stateTone[latestVisualState] || stateTone.running
    const iconMotion = latestVisualState === 'running' || latestVisualState === 'retry' ? 'animate-spin' : ''
    // Collapsed: mirror the latest row. Expanded: generic header so the list is not a duplicate of the title.
    const summaryLabel = expanded ? 'Session activity' : latest.label
    const summaryDetail = expanded ? null : latest.detail

    return (
        <div className="mb-3 rounded-md border border-hairline bg-surface-2/70 px-3 py-2 text-xs text-ink-muted">
            <button
                type="button"
                onClick={() => setExpanded((prev) => {
                    const next = !prev
                    userCollapsedRef.current = !next
                    return next
                })}
                className="flex w-full items-center justify-between gap-3 text-left"
                aria-expanded={expanded}
            >
                <span className="flex min-w-0 items-center gap-2">
                    <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${tone}`}>
                        <MaterialActivityIcon icon={icon} className={`text-[14px] ${iconMotion}`} />
                    </span>
                    <span className="min-w-0">
                        <span className="block truncate font-medium text-ink-muted">{summaryLabel}</span>
                        {summaryDetail ? (
                            <span className="block truncate text-[11px] text-ink-subtle">{summaryDetail}</span>
                        ) : null}
                    </span>
                </span>
                <span className="flex shrink-0 items-center gap-1 text-[11px] text-ink-subtle">
                    {rows.length} update{rows.length === 1 ? '' : 's'}
                    <MaterialActivityIcon icon={expanded ? 'expand_less' : 'expand_more'} className="text-base" />
                </span>
            </button>

            {expanded ? (
                <div className="mt-2 border-t border-hairline pt-2">
                    <ol className="space-y-2">
                        {rows.map((step) => {
                            const current = isCurrentStep(step, rows)
                            const stepVisualState = visualStateForStep(step, rows, isTerminal)
                            const stepTone = stateTone[stepVisualState] || stateTone.running
                            const stepIcon = stateIcon[stepVisualState] || 'progress_activity'
                            const stepMotion = stepVisualState === 'running' || stepVisualState === 'retry' ? 'animate-spin' : ''
                            const entering = enteringRowIds.has(String(step.id))
                            return (
                                <li
                                    key={step.id}
                                    data-step-id={step.id}
                                    data-activity-entry={entering ? 'appended' : undefined}
                                    className={`activity-timeline-row flex gap-2 rounded-md px-2 py-1.5 ${entering ? 'activity-timeline-row--new' : ''
                                        } ${current ? 'bg-primary/10 ring-1 ring-inset ring-primary/20' : ''
                                        }`}
                                >
                                    <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${stepTone}`}>
                                        <MaterialActivityIcon icon={stepIcon} className={`text-[11px] ${stepMotion}`} />
                                    </span>
                                    <span className="min-w-0 flex-1">
                                        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-ink-muted">
                                            <span className="min-w-0 max-w-full break-words leading-snug">{step.label}</span>
                                            {current ? (
                                                <span className="shrink-0 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                                                    Current
                                                </span>
                                            ) : null}
                                        </span>
                                        {step.detail ? (
                                            <span className="block break-words text-[11px] leading-snug text-ink-subtle">{step.detail}</span>
                                        ) : null}
                                    </span>
                                </li>
                            )
                        })}
                    </ol>
                </div>
            ) : null}
        </div>
    )
}

export default ActivityTimeline
