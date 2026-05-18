import { useMemo, useState } from 'react'
import ActivityTimeline from './ActivityTimeline'
import {
  activityStepsFromResponseDocument,
  humanizeResponseDocumentKey,
  responseDocumentMessage,
  tablePresentationFromResponseRows,
} from './responseDocumentContract.js'
import { TablePresentation } from '../turns/TurnBlocks'

const PREVIEW_LIMIT = 5
const TECHNICAL_REDACTION_RE = /\b(api[_-]?key|authorization|bearer|password|secret|token)\b\s*[:=]?\s*[^\s,;]+/gi

function safeText(value) {
  return value == null ? '' : String(value).trim()
}

function rowLabel(row, index) {
  const keys = ['job_id', 'machine_id', 'id', 'record_id', 'name']
  for (const key of keys) {
    if (row?.[key] != null && row[key] !== '') return String(row[key])
  }
  const first = Object.values(row || {}).find((value) => value != null && value !== '')
  return first == null ? `Record ${index + 1}` : String(first)
}

function rowRecordId(row, index) {
  return rowLabel(row, index)
}

function businessChangeLabel(value, fallback = 'Business change') {
  return safeText(value) || fallback
}

function businessChangeCount(group) {
  const explicit = Number(group?.record_count)
  if (Number.isFinite(explicit)) return explicit
  return Array.isArray(group?.rows) ? group.rows.length : 0
}

function businessChangeSummary(group, fallback) {
  const label = businessChangeLabel(group?.business_change, fallback)
  const count = businessChangeCount(group)
  return safeText(group?.summary) || `${label}: ${count} ${count === 1 ? 'job' : 'jobs'}`
}

function RowPreview({ rows = [], limit = PREVIEW_LIMIT }) {
  const safeRows = Array.isArray(rows) ? rows : []
  if (!safeRows.length) return null
  const preview = safeRows.slice(0, limit)
  const remaining = Math.max(0, safeRows.length - preview.length)
  return (
    <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-ink-muted" data-affected-record-preview="">
      {preview.map((row, index) => (
        <span
          key={`${rowLabel(row, index)}-${index}`}
          className="rounded-md bg-surface-3 px-2 py-1"
          data-affected-record-row=""
          data-record-id={rowRecordId(row, index)}
        >
          {rowLabel(row, index)}
        </span>
      ))}
      {remaining > 0 ? (
        <span className="rounded-md bg-surface-3 px-2 py-1">+{remaining} more</span>
      ) : null}
    </div>
  )
}

function BusinessChangeList({ groups = [] }) {
  const safeGroups = Array.isArray(groups) ? groups : []
  if (!safeGroups.length) return null
  return (
    <div className="mt-2 space-y-1.5" data-business-change-list="">
      {safeGroups.map((group, index) => {
        const label = businessChangeLabel(group.business_change, `Change ${index + 1}`)
        const count = businessChangeCount(group)
        const summary = businessChangeSummary(group, label)
        return (
          <div
            key={`${label}-${index}`}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-surface-2 px-2.5 py-2 text-xs text-ink-muted"
            data-business-change-group=""
            data-business-change-label={label}
            data-business-change-count={count}
          >
            <span className="font-semibold text-ink-muted">{summary}</span>
          </div>
        )
      })}
    </div>
  )
}

function CleanAuditRows({ rows = [] }) {
  const safeRows = Array.isArray(rows) ? rows : []
  if (!safeRows.length) return null
  return (
    <div className="mt-2 divide-y divide-hairline overflow-hidden rounded-md border border-hairline bg-surface-1 text-[11px]">
      {safeRows.map((row, index) => {
        const recordId = rowRecordId(row, index)
        const change = safeText(row.change)
          || [row.previous_priority, row.new_priority || row.current_priority]
            .filter((value) => value != null && value !== '')
            .join(' -> ')
        const status = safeText(row.status || row.outcome)
        return (
          <div
            key={`${recordId}-${index}`}
            className="grid gap-1 px-2.5 py-2 text-ink sm:grid-cols-[minmax(8rem,1fr)_minmax(7rem,1fr)_auto]"
            data-affected-record-row=""
            data-record-id={recordId}
          >
            <span className="font-medium">{recordId}</span>
            {change ? <span className="text-ink-muted">{change}</span> : <span />}
            {status ? <span className="text-ink-subtle">{status}</span> : null}
          </div>
        )
      })}
    </div>
  )
}

function CleanAuditDisclosure({ groups = [], totalCount = 0, defaultCollapsed = true, blockId = null }) {
  const safeGroups = Array.isArray(groups) ? groups : []
  if (!safeGroups.length) return null
  return (
    <Disclosure
      className="mt-3 rounded-md border border-hairline bg-surface-2"
      summaryClassName="cursor-pointer px-3 py-2 text-xs font-medium text-ink-subtle"
      title={`Full clean audit (${totalCount})`}
      defaultCollapsed={defaultCollapsed}
      data-clean-audit=""
      key={blockId || 'clean-audit'}
    >
      <div className="space-y-3 border-t border-hairline px-3 py-3" data-clean-audit-content="">
        {safeGroups.map((group, index) => {
          const label = businessChangeLabel(group.business_change, `Change ${index + 1}`)
          const count = businessChangeCount(group)
          return (
            <section
              key={`${label}-${index}`}
              data-clean-audit-group=""
              data-business-change-label={label}
              data-business-change-count={count}
            >
              <div className="text-xs font-semibold text-ink">{businessChangeSummary(group, label)}</div>
              <CleanAuditRows rows={group.rows} />
            </section>
          )
        })}
      </div>
    </Disclosure>
  )
}

function redactTechnicalText(value) {
  return String(value == null ? '' : value)
    .replace(TECHNICAL_REDACTION_RE, (match) => {
      const key = match.split(/[:=\s]/)[0] || 'secret'
      return `${key}=[redacted]`
    })
    .replace(/traceback\s+\(most recent call last\):[\s\S]*/i, '[stack trace redacted]')
}

function formatDiagnosticValue(value) {
  if (Array.isArray(value)) {
    return value.map((item) => formatDiagnosticValue(item)).join(', ')
  }
  if (value && typeof value === 'object') {
    return Object.entries(value)
      .slice(0, 6)
      .map(([key, item]) => `${humanizeResponseDocumentKey(key)}: ${formatDiagnosticValue(item)}`)
      .join('; ')
  }
  return redactTechnicalText(value)
}

function CompactCard({ title, children, tone = 'default', blockType = null, blockId = null }) {
  const toneClass = tone === 'error'
    ? 'border-hairline bg-surface-1'
    : tone === 'warning'
      ? 'border-hairline bg-surface-1'
      : 'border-hairline bg-surface-1'
  return (
    <div
      className={`mt-3 min-w-0 max-w-full rounded-md border px-3 py-3 text-sm ${toneClass}`}
      data-response-block-type={blockType || undefined}
      data-response-block-id={blockId || undefined}
    >
      {title ? <div className="text-sm font-semibold text-ink">{title}</div> : null}
      {children}
    </div>
  )
}

function Disclosure({ title, children, defaultCollapsed = true, className = '', summaryClassName = '', ...detailsProps }) {
  const [open, setOpen] = useState(defaultCollapsed === false)
  return (
    <details
      className={className}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      {...detailsProps}
    >
      <summary className={summaryClassName}>{title}</summary>
      {children}
    </details>
  )
}

function ExpandableTable({ title, rows, defaultCollapsed = true, blockId = null }) {
  const presentation = tablePresentationFromResponseRows(rows, title)
  if (!presentation) return null
  if (!defaultCollapsed) {
    return <TablePresentation presentation={presentation} />
  }
  return (
    <Disclosure
      className="mt-2 rounded-md border border-hairline bg-surface-2"
      summaryClassName="cursor-pointer px-3 py-2 text-xs font-medium text-ink-subtle"
      title={`${title} (${rows.length})`}
      defaultCollapsed={defaultCollapsed}
      key={blockId || title}
    >
      <div className="max-h-80 overflow-auto border-t border-hairline">
        <TablePresentation presentation={presentation} defaultCollapsed={false} />
      </div>
    </Disclosure>
  )
}

function ApprovalBlock({
  block,
  pendingApproval,
  showApprovalActions,
  decideApproval,
  isDecidingApproval,
}) {
  const rows = Array.isArray(block.rows) ? block.rows : []
  return (
    <CompactCard title={block.title || 'Approval required'} blockType="approval_required" blockId={block.id}>
      <div className="mt-1 text-sm text-ink">{block.summary || 'Review the proposed change before it is applied.'}</div>
      <RowPreview rows={rows} limit={5} />
      {showApprovalActions ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={isDecidingApproval}
            aria-busy={isDecidingApproval ? 'true' : 'false'}
            onClick={() => decideApproval?.('approve', pendingApproval?.args, pendingApproval)}
            className="inline-flex min-w-[6.5rem] items-center justify-center gap-2 rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover disabled:opacity-70"
          >
            {isDecidingApproval ? 'Approving...' : 'Approve'}
          </button>
          <button
            type="button"
            disabled={isDecidingApproval}
            onClick={() => decideApproval?.('reject', undefined, pendingApproval)}
            className="rounded-md bg-inverse-canvas px-3 py-1.5 text-xs font-semibold text-inverse-ink hover:opacity-90 disabled:opacity-60"
          >
            Reject
          </button>
        </div>
      ) : null}
      {rows.length > 5 ? (
        <ExpandableTable title="Affected records" rows={rows} defaultCollapsed={block.details_collapsed !== false} blockId={block.id} />
      ) : null}
    </CompactCard>
  )
}

function CompletedStepBlock({ block }) {
  const rows = Array.isArray(block.rows) ? block.rows : []
  return (
    <CompactCard title={block.title || 'Completed step'} blockType="completed_step" blockId={block.id}>
      <div className="mt-1 text-sm text-ink">{block.summary}</div>
      <RowPreview rows={rows} limit={3} />
      {rows.length > 3 ? (
        <ExpandableTable title="Completed records" rows={rows} defaultCollapsed={block.details_collapsed !== false} blockId={block.id} />
      ) : null}
    </CompactCard>
  )
}

function ResultSummaryBlock({ block }) {
  const steps = Array.isArray(block.steps) ? block.steps : []
  return (
    <CompactCard title={block.title || 'Result summary'} blockType="result_summary" blockId={block.id}>
      <div className="mt-1 text-sm text-ink" data-final-summary="">{block.summary}</div>
      {steps.length ? (
        <div className="mt-2 space-y-1 text-xs text-ink-muted">
          {steps.map((step, index) => (
            <div key={`${step.approval_id || step.operation_id || index}`} className="rounded-md bg-surface-2 px-2.5 py-2">
              <span className="font-semibold text-ink-muted">Step {step.step_number || index + 1}</span>
              {step.summary ? <span>: {step.summary}</span> : null}
            </div>
          ))}
        </div>
      ) : null}
    </CompactCard>
  )
}

function MutationResultBlock({ block }) {
  const rows = Array.isArray(block.rows) ? block.rows : []
  return (
    <CompactCard title={block.title || 'Mutation result'} blockType="mutation_result" blockId={block.id}>
      <div className="mt-1 text-sm text-ink" data-final-summary="">{block.summary}</div>
      <RowPreview rows={rows} limit={block.preview_limit || PREVIEW_LIMIT} />
      {rows.length > 5 ? <ExpandableTable title="Affected records" rows={rows} blockId={block.id} /> : null}
    </CompactCard>
  )
}

function FinalBusinessResultBlock({ summaryBlock, mutationBlock }) {
  const groups = Array.isArray(mutationBlock?.groups) && mutationBlock.groups.length
    ? mutationBlock.groups
    : Array.isArray(summaryBlock?.steps)
      ? summaryBlock.steps
      : []
  const rows = Array.isArray(mutationBlock?.rows) ? mutationBlock.rows : []
  const previewLimit = Number.isFinite(Number(mutationBlock?.preview_limit))
    ? Number(mutationBlock.preview_limit)
    : PREVIEW_LIMIT
  const totalCount = Number.isFinite(Number(summaryBlock?.total_count))
    ? Number(summaryBlock.total_count)
    : rows.length

  return (
    <CompactCard
      title={summaryBlock?.title || 'Changes completed'}
      blockType="result_summary"
      blockId={summaryBlock?.id}
    >
      <div data-final-result-card="" data-response-block-type="mutation_result" data-response-block-id={mutationBlock?.id}>
        <div className="mt-1 text-sm text-ink" data-final-summary="">
          {summaryBlock?.summary || mutationBlock?.summary}
        </div>
        <BusinessChangeList groups={groups} />
        <RowPreview rows={rows} limit={previewLimit} />
        <CleanAuditDisclosure
          groups={groups}
          totalCount={totalCount}
          defaultCollapsed={mutationBlock?.details_collapsed !== false}
          blockId={mutationBlock?.id}
        />
      </div>
    </CompactCard>
  )
}

function RecordPreviewBlock({ block }) {
  const rows = Array.isArray(block.rows) ? block.rows : []
  return (
    <CompactCard title={block.title || 'Records'} blockType="record_preview" blockId={block.id}>
      <RowPreview rows={rows} limit={5} />
      {rows.length > 5 ? <ExpandableTable title={block.title || 'Records'} rows={rows} defaultCollapsed={block.details_collapsed !== false} blockId={block.id} /> : null}
    </CompactCard>
  )
}

function SourceListBlock({ block }) {
  const sources = Array.isArray(block.sources) ? block.sources : []
  if (!sources.length) return null
  return (
    <CompactCard title={block.title || 'Knowledge sources'} blockType="source_list" blockId={block.id}>
      <div className="mt-2 space-y-2 text-xs text-ink-muted">
        {sources.map((source, index) => {
          const title = safeText(source.title || source.doc_id || `Source ${index + 1}`)
          return (
            <div key={`${source.doc_id || title}-${index}`} className="rounded-md bg-surface-2 px-2.5 py-2">
              <div className="font-semibold text-ink">{title}</div>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                {['doc_id', 'machine_id', 'organization'].map((key) => (
                  source[key] ? <span key={key}>{humanizeResponseDocumentKey(key)}: {String(source[key])}</span> : null
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </CompactCard>
  )
}

function StatusResultBlock({ block, documentMessage }) {
  const fields = Array.isArray(block.fields) ? block.fields : []
  const secondaryFields = Array.isArray(block.secondary_fields) ? block.secondary_fields : []
  const summary = safeText(block.summary)
  const shouldShowSummary = summary && summary !== safeText(documentMessage)
  return (
    <CompactCard title={block.title || 'Status'} blockType="status_result" blockId={block.id}>
      {shouldShowSummary ? <div className="mt-1 text-sm text-ink">{summary}</div> : null}
      {fields.length ? (
        <dl className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
          {fields.map((field, index) => (
            <div key={`${field.key || field.label}-${index}`} className="min-w-0 rounded-md bg-surface-2 px-2.5 py-2">
              <dt className="font-semibold text-ink-muted">{field.label}</dt>
              <dd className="mt-0.5 break-words text-ink">{String(field.value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {secondaryFields.length ? (
        <Disclosure
          className="mt-3 rounded-md border border-hairline bg-surface-2"
          summaryClassName="cursor-pointer px-3 py-2 text-xs font-medium text-ink-subtle"
          title="Technical details"
          defaultCollapsed={block.details_collapsed !== false}
        >
          <dl className="grid gap-2 border-t border-hairline px-3 py-3 text-xs sm:grid-cols-2">
            {secondaryFields.map((field, index) => (
              <div key={`${field.key || field.label}-${index}`} className="min-w-0">
                <dt className="font-semibold text-ink-muted">{field.label}</dt>
                <dd className="mt-0.5 break-words text-ink">{String(field.value)}</dd>
              </div>
            ))}
          </dl>
        </Disclosure>
      ) : null}
    </CompactCard>
  )
}

function DiagnosticBlock({ block }) {
  const technicalDetails = block.technical_details && typeof block.technical_details === 'object'
    ? block.technical_details
    : {}
  return (
    <CompactCard title={block.title || 'Needs attention'} tone={block.severity === 'error' ? 'error' : 'warning'} blockType="diagnostic" blockId={block.id}>
      <div className="mt-1 text-sm text-ink">{block.user_message || block.summary || 'The request could not be completed.'}</div>
      <div className="mt-2 space-y-1 text-xs text-ink-muted">
        {block.cause ? <div><span className="font-semibold text-ink-muted">Cause:</span> {block.cause}</div> : null}
        {block.current_state ? <div><span className="font-semibold text-ink-muted">Current state:</span> {block.current_state}</div> : null}
        {block.next_action ? <div><span className="font-semibold text-ink-muted">Next action:</span> {block.next_action}</div> : null}
      </div>
      {block.impact && Object.keys(block.impact).length ? (
        <Disclosure
          className="mt-2"
          summaryClassName="cursor-pointer text-xs font-medium text-ink-subtle"
          title="Impact details"
        >
          <div className="mt-2 space-y-1 text-xs text-ink-muted">
            {Object.entries(block.impact).slice(0, 8).map(([key, value]) => (
              <div key={key}>
                <span className="font-semibold text-ink-muted">{humanizeResponseDocumentKey(key)}:</span>{' '}
                {formatDiagnosticValue(value)}
              </div>
            ))}
          </div>
        </Disclosure>
      ) : null}
      <Disclosure
        className="mt-2"
        summaryClassName="cursor-pointer text-xs font-medium text-ink-subtle"
        title="Technical details"
        defaultCollapsed={block.details_collapsed !== false}
      >
        <div className="mt-2 rounded-md bg-surface-2 px-2.5 py-2 text-xs text-ink-muted">
          {Object.keys(technicalDetails).length ? (
            Object.entries(technicalDetails).slice(0, 12).map(([key, value]) => (
              <div key={key} className="break-words">
                <span className="font-semibold">{humanizeResponseDocumentKey(key)}:</span>{' '}
                {formatDiagnosticValue(value)}
              </div>
            ))
          ) : (
            <div>No technical details were provided.</div>
          )}
        </div>
      </Disclosure>
    </CompactCard>
  )
}

function renderBlock(block, props) {
  if (!block || block.type === 'run_activity' || block.type === 'short_message') return null
  if (block.type === 'approval_required') return <ApprovalBlock key={block.id} block={block} {...props} />
  if (block.type === 'completed_step') return <CompletedStepBlock key={block.id} block={block} />
  if (block.type === 'result_summary') return <ResultSummaryBlock key={block.id} block={block} />
  if (block.type === 'mutation_result') return <MutationResultBlock key={block.id} block={block} />
  if (block.type === 'result_table') return <ExpandableTable key={block.id} title={block.title || 'Affected records'} rows={block.rows} defaultCollapsed blockId={block.id} />
  if (block.type === 'status_result') return <StatusResultBlock key={block.id} block={block} documentMessage={props.documentMessage} />
  if (block.type === 'record_preview') return <RecordPreviewBlock key={block.id} block={block} />
  if (block.type === 'knowledge_answer') return <div key={block.id} className="mt-3 whitespace-pre-wrap break-words text-sm text-ink">{block.answer}</div>
  if (block.type === 'source_list') return <SourceListBlock key={block.id} block={block} />
  if (block.type === 'warning' || block.type === 'diagnostic') return <DiagnosticBlock key={block.id} block={block} />
  return null
}

export default function ResponseDocumentRenderer({
  document,
  pendingApproval,
  showApprovalActions,
  decideApproval,
  isDecidingApproval,
}) {
  if (!document) return null
  const activitySteps = activityStepsFromResponseDocument(document)
  const message = responseDocumentMessage(document)
  const finalSummaryBlock = (document.blocks || []).find((block) =>
    block?.type === 'result_summary' &&
    block.status === 'completed',
  )
  const finalMutationBlock = (document.blocks || []).find((block) =>
    block?.type === 'mutation_result' &&
    block.status === 'completed' &&
    Array.isArray(block.groups) &&
    block.groups.length > 0,
  )
  const shouldRenderFinalBusinessResult = Boolean(finalSummaryBlock && finalMutationBlock)
  const duplicateTableOwners = useMemo(() => {
    const approvalOwners = new Set()
    const mutationOwners = new Set()
    for (const block of document.blocks || []) {
      const approvalId = block.approval_id || ''
      const operationId = block.operation_id || ''
      if (block?.type === 'approval_required') approvalOwners.add(`${approvalId}:${operationId}`)
      if (block?.type === 'mutation_result') mutationOwners.add(`${approvalId}:${operationId}`)
    }
    return { approvalOwners, mutationOwners }
  }, [document])
  const renderedBlocks = (document.blocks || [])
    .filter((block) => {
      if (!['result_table', 'record_preview'].includes(block?.type)) return true
      const ownerKey = `${block.approval_id || ''}:${block.operation_id || ''}`
      if (duplicateTableOwners.approvalOwners.has(ownerKey)) return false
      if (
        block.type === 'result_table' &&
        duplicateTableOwners.mutationOwners.has(ownerKey) &&
        Array.isArray(block.rows) &&
        block.rows.length > PREVIEW_LIMIT
      ) {
        return false
      }
      return true
    })
    .flatMap((block) => {
      if (shouldRenderFinalBusinessResult && block === finalSummaryBlock) {
        return [(
          <FinalBusinessResultBlock
            key={`${finalSummaryBlock.id}:${finalMutationBlock.id}`}
            summaryBlock={finalSummaryBlock}
            mutationBlock={finalMutationBlock}
          />
        )]
      }
      if (shouldRenderFinalBusinessResult && block === finalMutationBlock) return []
      return [renderBlock(block, {
        pendingApproval,
        showApprovalActions,
        decideApproval,
        isDecidingApproval,
        documentMessage: message,
      })]
    })
    .filter(Boolean)

  return (
    <div className="min-w-0 max-w-full" data-response-document-root="">
      <ActivityTimeline steps={activitySteps} />
      {message ? <div className="whitespace-pre-wrap break-words text-ink">{message}</div> : null}
      {renderedBlocks}
    </div>
  )
}
