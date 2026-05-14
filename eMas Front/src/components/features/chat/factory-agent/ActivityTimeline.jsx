/* eslint-disable react/prop-types */
import { useEffect, useMemo, useState } from 'react'
import { shouldAutoCollapseActivity, shouldShowActivityTimeline } from './activityTimelineUtils'

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

function latestStep(steps) {
 if (!Array.isArray(steps) || !steps.length) return null
 return steps[steps.length - 1]
}

function isCurrentStep(step, latest) {
 if (!step || !latest) return false
 if (step.id === latest.id) return latest.state === 'running' || latest.state === 'retry' || latest.state === 'waiting'
 return false
}

const ActivityTimeline = ({ steps = [] }) => {
 const rows = useMemo(() => (Array.isArray(steps) ? steps.filter(Boolean) : []), [steps])
 const [expanded, setExpanded] = useState(false)
 const latest = latestStep(rows)

 useEffect(() => {
 if (shouldAutoCollapseActivity(rows)) setExpanded(false)
 }, [rows])

 if (!rows.length || !latest || !shouldShowActivityTimeline(rows)) return null

 const icon = stateIcon[latest.state] || 'progress_activity'
 const tone = stateTone[latest.state] || stateTone.running
 const iconMotion = latest.state === 'running' || latest.state === 'retry' ? 'animate-spin' : ''
 const summaryLabel = latest.label
 const summaryDetail = latest.detail

 return (
 <div className="mb-3 rounded-md border border-hairline bg-surface-2/70 px-3 py-2 text-xs text-ink-muted">
 <button
 type="button"
 onClick={() => setExpanded((prev) => !prev)}
 className="flex w-full items-center justify-between gap-3 text-left"
 aria-expanded={expanded}
 >
 <span className="flex min-w-0 items-center gap-2">
 <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${tone}`}>
 <span className={`material-symbols-outlined text-[14px] ${iconMotion}`}>{icon}</span>
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
 <span className="material-symbols-outlined text-base">
 {expanded ? 'expand_less' : 'expand_more'}
 </span>
 </span>
 </button>

 {expanded ? (
 <div className="mt-2 border-t border-hairline pt-2">
 <ol className="space-y-2">
 {rows.map((step) => {
 const stepTone = stateTone[step.state] || stateTone.running
 const stepIcon = stateIcon[step.state] || 'progress_activity'
 const stepMotion = step.state === 'running' || step.state === 'retry' ? 'animate-spin' : ''
 const current = isCurrentStep(step, latest)
 return (
 <li
 key={step.id}
 className={`flex gap-2 rounded-md px-2 py-1.5 ${
 current ? 'bg-primary/10 ring-1 ring-inset ring-primary/20' : ''
 }`}
 >
 <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${stepTone}`}>
 <span className={`material-symbols-outlined text-[11px] ${stepMotion}`}>{stepIcon}</span>
 </span>
 <span className="min-w-0 flex-1">
 <span className="flex items-center gap-2 text-ink-muted">
 <span>{step.label}</span>
 {current ? (
 <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
 Current
 </span>
 ) : null}
 </span>
 {step.detail ? (
 <span className="block text-[11px] text-ink-subtle">{step.detail}</span>
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
