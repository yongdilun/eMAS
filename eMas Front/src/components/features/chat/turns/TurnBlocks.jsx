/* eslint-disable react/prop-types */
import { getReadableAction } from './turnAssembler'
import { useEffect, useState } from 'react'

function JsonDetails({ summary, value }) {
 if (value == null) return null
 return (
 <details className="mt-2">
 <summary className="cursor-pointer text-ink-subtle">{summary}</summary>
 <pre className="mt-2 overflow-x-auto rounded-md border border-hairline bg-surface-2 p-2 text-[11px] text-ink">
{JSON.stringify(value, null, 2)}
 </pre>
 </details>
 )
}

export function TablePresentation({ presentation, animate = false, animateKey = 'table', defaultCollapsed = false }) {
 const table = presentation?.table
 const columns = Array.isArray(table?.columns) ? table.columns : []
 const rows = Array.isArray(table?.rows) ? table.rows : []
 const analysisFacts = Array.isArray(presentation?.analysis?.facts) ? presentation.analysis.facts : []
 const [visibleRows, setVisibleRows] = useState(animate ? 0 : rows.length)

 useEffect(() => {
 if (!animate) {
 setVisibleRows(rows.length)
 return undefined
 }
 setVisibleRows(0)
 if (!rows.length) return undefined

 let index = 0
 const timer = window.setInterval(() => {
 index += 1
 setVisibleRows(Math.min(index, rows.length))
 if (index >= rows.length) window.clearInterval(timer)
 }, 55)

 return () => window.clearInterval(timer)
 }, [animate, animateKey, rows.length])

 if (!columns.length || !rows.length) return null
 const renderedRows = animate ? rows.slice(0, visibleRows) : rows

 const tableSurfaceClass = defaultCollapsed
  ? 'overflow-hidden bg-surface-1'
  : 'overflow-hidden rounded-lg border border-hairline bg-surface-1'

 const tableBlock = (
 <div className={tableSurfaceClass}>
 {analysisFacts.length ? (
 <div className="border-b border-hairline bg-surface-2 px-3 py-2 text-[11px] text-ink-muted">
 <div className="space-y-1">
 {analysisFacts.map((fact) => (
 <div key={fact} className="break-words">
 {fact}
 </div>
 ))}
 </div>
 </div>
 ) : null}
 <div className="overflow-x-auto">
 <table className="min-w-full text-left text-[11px]">
 <thead className="bg-surface-2 text-ink-muted">
 <tr>
 {columns.map((column) => (
 <th key={column.key} className="px-3 py-2 font-medium whitespace-nowrap">
 {column.label || column.key}
 </th>
 ))}
 </tr>
 </thead>
 <tbody className="divide-y divide-hairline bg-surface-1 text-ink">
 {renderedRows.map((row, rowIndex) => (
 <tr key={`${rowIndex}-${String(row?.[columns[0]?.key] ?? rowIndex)}`}>
 {columns.map((column) => (
 <td key={column.key} className="px-3 py-2 align-top whitespace-nowrap">
 {row?.[column.key] == null ? '—' : String(row[column.key])}
 </td>
 ))}
 </tr>
 ))}
 </tbody>
 </table>
 </div>
 {(table?.displayed_rows || 0) < (table?.total_rows || 0) ? (
 <div className="border-t border-hairline bg-surface-2 px-3 py-2 text-[11px] text-ink-subtle">
 Showing {table.displayed_rows} of {table.total_rows} rows.
 </div>
 ) : null}
 </div>
 )

 if (!defaultCollapsed) {
 return <div className="mt-3">{tableBlock}</div>
 }

 const rowCount = rows.length
 const summaryLabel =
  rowCount > 0 ? `Affected records (${rowCount}) — tap to expand` : 'Affected records — tap to expand'

 return (
 <details className="mt-3 group rounded-lg border border-hairline bg-surface-1">
 <summary className="cursor-pointer list-none px-3 py-2 text-xs font-medium text-ink-subtle marker:content-none [&::-webkit-details-marker]:hidden">
 <span className="inline-flex items-center gap-1">
 <span className="material-symbols-outlined text-sm text-ink-muted transition-transform group-open:rotate-180">
 expand_more
 </span>
 {summaryLabel}
 </span>
 </summary>
 <div className="border-t border-hairline px-0 pb-0 pt-2">{tableBlock}</div>
 </details>
 )
}

export function ThinkingBlock({ items = [] }) {
 const rows = Array.isArray(items) ? items : []
 if (!rows.length) return null

 const latest = rows[rows.length - 1]
 const content = latest?.details?.plan_explanation || latest?.content || ''
 const risk = latest?.details?.risk_summary

 return (
 <div className="mt-2 rounded-lg border border-hairline bg-surface-2 p-3 text-xs">
 <details>
 <summary className="cursor-pointer font-semibold text-ink">
 Thinking (View Plan)
 </summary>
 {content ? (
 <div className="mt-2 whitespace-pre-wrap text-ink">{content}</div>
 ) : (
 <div className="mt-2 text-ink-subtle">No plan explanation available.</div>
 )}
 {risk ? (
 <div className="mt-2 rounded-md bg-surface-3 px-2.5 py-2 text-ink-muted">
 Risk summary: {risk}
 </div>
 ) : null}
 <JsonDetails summary="Show debug payload" value={latest?.details} />
 </details>
 </div>
 )
}

export function ToolBlocks({ tools = [] }) {
 const rows = Array.isArray(tools) ? tools : []
 if (!rows.length) return null

 return (
 <div className="mt-2 space-y-2">
 {rows.map((t) => {
 const label = `${getReadableAction(t.tool_name)}`
 const status = (t.status || 'DONE').toString()
 const title = label
 const upper = String(status).toUpperCase()
 const pill = upper === 'DONE'
 ? 'bg-primary/10 text-primary'
 : upper === 'FAILED'
 ? 'bg-surface-3 text-ink'
 : upper === 'IN_PROGRESS'
 ? 'bg-surface-3 text-ink-muted'
 : 'bg-surface-3 text-ink-muted'

 return (
 <div key={t.id} className="rounded-lg border border-hairline bg-surface-2 p-3 text-xs">
 <details>
 <summary className="cursor-pointer flex items-center justify-between gap-2">
 <span className="min-w-0 truncate text-ink">
 {title}
 </span>
 <span className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold uppercase ${pill}`}>
 {status}
 </span>
 </summary>
 {t.tool_name ? (
 <div className="mt-2 text-[11px] text-ink-subtle">
 Tool: {t.tool_name}
 </div>
 ) : null}
 {t.content ? (
 <div className="mt-2 whitespace-pre-wrap text-ink">{t.content}</div>
 ) : null}
 {t?.details?.presentation?.render_hint === 'table' ? (
 <TablePresentation presentation={t.details.presentation} />
 ) : null}
 <JsonDetails summary="Show args/result" value={t.details} />
 </details>
 </div>
 )
 })}
 </div>
 )
}

export function ApprovalBlocks({ approvals = [] }) {
 const rows = Array.isArray(approvals) ? approvals : []
 if (!rows.length) return null

 return (
 <div className="mt-2 space-y-2">
 {rows.map((a) => {
 const title = a.event_type === 'approval_required' ? 'Approval required' : 'Approval decided'
 const tone = a.event_type === 'approval_required'
 ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
 : 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300'
 return (
 <div key={a.id} className="rounded-lg border border-hairline bg-surface-2 p-3 text-xs">
 <details>
 <summary className="cursor-pointer flex items-center justify-between gap-2">
 <span className="min-w-0 truncate text-ink">
 {title}
 </span>
 <span className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold uppercase ${tone}`}>
 {a.status || a.event_type}
 </span>
 </summary>
 {a.tool_name ? (
 <div className="mt-2 text-[11px] text-ink-subtle">
 Tool: {a.tool_name}
 </div>
 ) : null}
 {a.content ? (
 <div className="mt-2 whitespace-pre-wrap text-ink">{a.content}</div>
 ) : null}
 <JsonDetails summary="Show details" value={a.details} />
 </details>
 </div>
 )
 })}
 </div>
 )
}

export function LegacyBlocks({ blocks = [] }) {
 const rows = Array.isArray(blocks) ? blocks : []
 if (!rows.length) return null

 return (
 <div className="mt-2 space-y-2">
 {rows.map((b, idx) => {
 if (b.type === 'thinking') {
 return (
 <div key={`${b.type}-${idx}`} className="rounded-lg border border-hairline bg-surface-2 p-3 text-xs">
 <details>
 <summary className="cursor-pointer font-semibold text-ink">
 Thinking (View)
 </summary>
 <pre className="mt-2 overflow-x-auto rounded-md border border-hairline bg-surface-1 p-2 text-[11px] text-ink">
{JSON.stringify(b.payload, null, 2)}
 </pre>
 </details>
 </div>
 )
 }

 if (b.type === 'tool_call') {
 const action = getReadableAction(b.action || b.tool_name)
 return (
 <div key={`${b.type}-${idx}`} className="rounded-lg border border-hairline bg-surface-2 p-3 text-xs">
 <details>
 <summary className="cursor-pointer flex items-center justify-between gap-2">
 <span className="min-w-0 truncate text-ink">
 {action}
 </span>
 <span className="shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold uppercase bg-surface-3 text-ink-muted">
 {b.status || 'SUGGESTED'}
 </span>
 </summary>
 {(b.title || b.tool_name) ? (
 <div className="mt-2 text-[11px] text-ink-subtle">
 Tool: {b.title || b.tool_name}
 </div>
 ) : null}
 <pre className="mt-2 overflow-x-auto rounded-md border border-hairline bg-surface-1 p-2 text-[11px] text-ink">
{JSON.stringify(b.payload, null, 2)}
 </pre>
 </details>
 </div>
 )
 }

 return null
 })}
 </div>
 )
}
