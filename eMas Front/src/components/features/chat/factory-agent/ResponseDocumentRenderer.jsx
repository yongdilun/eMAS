import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import ActivityTimeline from './ActivityTimeline'
import {
  activityStepsFromResponseDocument,
  humanizeResponseDocumentKey,
  responseDocumentMessage,
  tablePresentationFromResponseRows,
} from './responseDocumentContract.js'
import { TablePresentation } from '../turns/TurnBlocks'
import { buildFactoryAgentUrl } from '../../../../services/factoryAgentApi.js'
import { stripPrematureTerminalActivitySteps } from './activityTimelineUtils.js'

const PREVIEW_LIMIT = 5
const EVIDENCE_DRAWER_DEFAULT_WIDTH = 440
const EVIDENCE_DRAWER_MIN_WIDTH = 320
const EVIDENCE_DRAWER_MAX_WIDTH = 720
const SOURCE_TOOLTIP_WIDTH = 288
const SOURCE_TOOLTIP_MIN_WIDTH = 180
const SOURCE_TOOLTIP_EDGE_GAP = 8
const SOURCE_TOOLTIP_OFFSET = 6
const TECHNICAL_REDACTION_RE = /\b(api[_-]?key|authorization|bearer|password|secret|token)\b\s*[:=]?\s*[^\s,;]+/gi
const SAFETY_ADMONITION_RE = /(?:^|\n)[ \t]*:::\s*safety\b[\s\S]*?(?:\n[ \t]*:::[ \t]*(?=\n|$)|$)/gi
const FOOTNOTE_DEFINITION_RE = /^[ \t]*\[\^[^\]\n]+\]:[^\n]*(?:\n[ \t]+[^\n]*)*/gm
const FOOTNOTE_MARKER_RE = /\[\^[^\]\n]+\]/g

function hasRetryStoryActivity(steps) {
  return (Array.isArray(steps) ? steps : []).some((step) => {
    const label = String(step?.label || '')
    const detail = String(step?.detail || '')
    return step?.state === 'retry' || label.startsWith('Replanning') || label.startsWith('Retrying') || /Attempt \d+ of \d+/.test(detail)
  })
}

function safeText(value) {
  if (value == null) return ''
  return String(value)
    .replace(SAFETY_ADMONITION_RE, '\n')
    .replace(/^[ \t]*:::\s*safety\b[ \t]*$/gim, '')
    .replace(/^[ \t]*:::[ \t]*$/gim, '')
    .replace(FOOTNOTE_DEFINITION_RE, '')
    .replace(FOOTNOTE_MARKER_RE, '')
    .replace(/\s+([,.;:!?])/g, '$1')
    .trim()
}

function clampNumber(value, min, max) {
  const number = Number(value)
  if (!Number.isFinite(number)) return min
  return Math.min(max, Math.max(min, number))
}

function rowLabel(row, index) {
  const keys = ['display_id', 'display_name', 'record_id', 'job_id', 'machine_id', 'product_id', 'material_id', 'inventory_id', 'entity_id', 'id', 'name']
  for (const key of keys) {
    if (row?.[key] != null && row[key] !== '') return String(row[key])
  }
  const metadataIds = new Set(['operation_id', 'step_id', 'tool_id', 'approval_id', 'row_id'])
  const identity = Object.entries(row || {}).find(([key, value]) => (
    /_id$/i.test(key) && !metadataIds.has(key) && value != null && value !== ''
  ))
  if (identity) return String(identity[1])
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
  const entity = safeText(group?.entity_type) || 'record'
  const singular = entity.endsWith('s') ? entity.slice(0, -1) || entity : entity
  return safeText(group?.summary) || `${label}: ${count} ${count === 1 ? singular : `${singular}s`}`
}

function hasSupportedMutationContract(block) {
  if (safeText(block?.contract) === 'business_change_v1') return true
  const groups = Array.isArray(block?.groups) ? block.groups : []
  return groups.some((group) => ['business_change_v1', 'entity_agnostic_no_matching_records_v1'].includes(safeText(group?.contract)))
}

function fieldChangeSummary(changes) {
  if (!Array.isArray(changes) || !changes.length) return ''
  return changes
    .map((change) => {
      const label = safeText(change?.label || change?.field) || 'Value'
      const before = safeText(change?.from)
      const after = safeText(change?.to)
      if (before && after) return `${label}: ${before} -> ${after}`
      if (after) return `${label}: ${after}`
      if (before) return `${label}: ${before}`
      return label
    })
    .filter(Boolean)
    .join('; ')
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
            data-response-contract={safeText(group.contract) || undefined}
            data-entity-type={safeText(group.entity_type) || undefined}
            data-change-type={safeText(group.change_type) || undefined}
            data-source-state-basis={safeText(group.source_state_basis) || undefined}
            data-field-change-count={Array.isArray(group.field_changes) ? group.field_changes.length : undefined}
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
          || fieldChangeSummary(row.field_changes)
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
              data-response-contract={safeText(group.contract) || undefined}
              data-entity-type={safeText(group.entity_type) || undefined}
              data-change-type={safeText(group.change_type) || undefined}
              data-source-state-basis={safeText(group.source_state_basis) || undefined}
              data-field-change-count={Array.isArray(group.field_changes) ? group.field_changes.length : undefined}
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

function dataText(value) {
  return safeText(value) || undefined
}

function dataNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : undefined
}

function dataBoolean(value) {
  if (value === null || value === undefined) return undefined
  return String(Boolean(value))
}

function requestedFieldsData(value) {
  return Array.isArray(value) && value.length ? value.map((item) => safeText(item)).filter(Boolean).join(',') : undefined
}

function CompactCard({
  title,
  children,
  tone = 'default',
  blockType = null,
  blockId = null,
  contract = null,
  entityType = null,
  readScope = null,
  requestedFields = [],
  displayMode = null,
  entityCount = null,
  previewLimit = null,
  detailsCollapsed = null,
  fieldCount = null,
  secondaryFieldCount = null,
}) {
  const toneClass = tone === 'error'
    ? 'border-hairline bg-surface-1'
    : tone === 'warning'
      ? 'border-hairline bg-surface-1'
      : 'border-hairline bg-surface-1'
  return (
    <div
      className={`mt-3 w-full min-w-0 max-w-full rounded-md border px-3 py-3 text-sm ${toneClass}`}
      data-response-block-type={blockType || undefined}
      data-response-block-id={blockId || undefined}
      data-response-contract={dataText(contract)}
      data-entity-type={dataText(entityType)}
      data-read-scope={dataText(readScope)}
      data-requested-fields={requestedFieldsData(requestedFields)}
      data-display-mode={dataText(displayMode)}
      data-entity-count={dataNumber(entityCount)}
      data-preview-limit={dataNumber(previewLimit)}
      data-details-collapsed={dataBoolean(detailsCollapsed)}
      data-status-field-count={dataNumber(fieldCount)}
      data-secondary-field-count={dataNumber(secondaryFieldCount)}
    >
      {title ? <h3 className="text-sm font-semibold text-ink">{title}</h3> : null}
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

function ExpandableTable({ title, rows, defaultCollapsed = true, blockId = null, requestedFields = [] }) {
  const presentation = tablePresentationFromResponseRows(rows, title, requestedFields)
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

function citationKey(value) {
  return safeText(value?.citation_id || value?.citationId || value?.source_id || value?.sourceId || value?.doc_id || value?.docId || value?.source_number || value?.sourceNumber)
}

const DIRECT_EVIDENCE_KEYS = ['evidence', 'evidenceItems']

function rawEvidenceItemsFromSource(source) {
  if (!source || typeof source !== 'object') return []
  const output = []
  for (const key of DIRECT_EVIDENCE_KEYS) {
    const items = Array.isArray(source[key]) ? source[key] : []
    for (const item of items) {
      if (!item || typeof item !== 'object') continue
      output.push({
        ...withoutNestedEvidenceFields(withoutPrecisionLocatorFields(source)),
        ...withoutNestedEvidenceFields(item),
      })
    }
  }
  return output
}

function citationFromSource(source) {
  if (!source || typeof source !== 'object') return null
  const sourceId = safeText(source.source_id || source.sourceId || source.doc_id || source.docId)
  const sourceNumber = source.source_number || source.sourceNumber
  const citationId = safeText(source.citation_id || source.citationId) || `citation:${sourceId || sourceNumber || 'source'}`
  const rawEvidence = rawEvidenceItemsFromSource(source)
  const evidence = rawEvidence
    .map((item, index) => (item && typeof item === 'object'
      ? citationFromSource({
        ...withoutNestedEvidenceFields(withoutPrecisionLocatorFields(source)),
        ...item,
        evidence: [],
        citation_id: safeText(item.evidence_id || item.evidenceId || item.citation_id || item.citationId)
          || `${citationId}:evidence-${index + 1}`,
        source_id: safeText(item.source_id || item.sourceId) || `${sourceId || citationId}:evidence-${index + 1}`,
        source_number: item.source_number || item.sourceNumber || sourceNumber,
        title: item.title || source.title,
        organization: item.organization || source.organization,
        pdf_url: item.pdf_url || item.pdfUrl || source.pdf_url || source.pdfUrl,
        page_count: item.page_count || item.pageCount || source.page_count || source.pageCount,
      })
      : null))
    .filter(Boolean)
  return {
    ...source,
    contract: safeText(source.contract) === 'source_citation_v1' ? 'source_citation_v1' : 'source_citation_v1',
    citation_id: citationId,
    source_id: sourceId,
    source_number: sourceNumber,
    doc_id: safeText(source.doc_id || source.docId),
    chunk_id: safeText(source.chunk_id || source.chunkId),
    title: safeText(source.title || source.doc_id || source.docId || `Source ${sourceNumber || ''}`),
    organization: safeText(source.organization),
    snippet: safeText(source.snippet),
    page: source.page,
    page_label: safeText(source.page_label || source.pageLabel),
    pdf_url: safeText(source.pdf_url || source.pdfUrl),
    bbox: source.bbox || source.bounding_box || source.boundingBox || null,
    char_range: source.char_range || source.charRange || source.text_range || source.textRange || null,
    text_search: safeText(source.text_search || source.textSearch || source.highlight_text || source.highlightText),
    page_count: source.page_count || source.pageCount || null,
    locator_confidence: safeText(source.locator_confidence || source.locatorConfidence),
    evidence,
    reference_only: Boolean(source.reference_only || source.referenceOnly),
    policy_only: Boolean(source.policy_only || source.policyOnly),
  }
}

function withoutPrecisionLocatorFields(source) {
  if (!source || typeof source !== 'object') return source
  const {
    bbox,
    bounding_box,
    boundingBox,
    char_range,
    charRange,
    text_range,
    textRange,
    text_search,
    textSearch,
    highlight_text,
    highlightText,
    locator_confidence,
    locatorConfidence,
    ...rest
  } = source
  return rest
}

function withoutNestedEvidenceFields(source) {
  if (!source || typeof source !== 'object') return source
  const {
    evidence,
    evidenceItems,
    evidence_snippets,
    evidenceSnippets,
    source_chunk_evidence,
    sourceChunkEvidence,
    ...rest
  } = source
  return rest
}

function sourceLocationLabel(source) {
  const page = safeText(source?.page)
  const chunk = safeText(source?.chunk_id || source?.chunkId)
  if (page && chunk) return `Page ${page} / Chunk ${chunk}`
  if (page) return `Page ${page}`
  if (chunk) return `Chunk ${chunk}`
  return null
}

function normalCharRange(value) {
  if (Array.isArray(value) && value.length >= 2) {
    const start = Number(value[0])
    const end = Number(value[1])
    if (Number.isFinite(start) && Number.isFinite(end) && end >= start) return { start, end }
  }
  if (value && typeof value === 'object') {
    const start = Number(value.start ?? value.from ?? value[0])
    const end = Number(value.end ?? value.to ?? value[1])
    if (Number.isFinite(start) && Number.isFinite(end) && end >= start) return { start, end }
  }
  return null
}

function appendPdfFragment(url, params) {
  const entries = Object.entries(params).filter(([, value]) => value != null && value !== '')
  if (!entries.length) return url
  const fragment = new URLSearchParams(entries.map(([key, value]) => [key, String(value)])).toString()
  const separator = url.includes('#') ? '&' : '#'
  return `${url}${separator}${fragment}`
}

function resolvePdfUrl(url) {
  const value = safeText(url)
  if (!value) return ''
  return buildFactoryAgentUrl(value)
}

function sourceOpenTarget(source) {
  const url = resolvePdfUrl(source?.pdf_url || source?.pdfUrl)
  if (!url) return { mode: 'drawer', href: null, highlightKind: null }
  const page = safeText(source?.page)
  if (source?.reference_only || source?.referenceOnly) {
    if (page) return { mode: 'page', href: appendPdfFragment(url, { page }), highlightKind: null }
    return { mode: 'pdf', href: url, highlightKind: null }
  }
  const charRange = normalCharRange(source?.char_range || source?.charRange)
  const bbox = source?.bbox || source?.bounding_box || source?.boundingBox
  const searchText = safeText(source?.text_search || source?.textSearch || source?.highlight_text || source?.highlightText)
  if (charRange) {
    return {
      mode: 'exact',
      href: appendPdfFragment(url, {
        page,
        highlight: 'char_range',
        char_start: charRange.start,
        char_end: charRange.end,
      }),
      highlightKind: 'char_range',
    }
  }
  if (bbox) {
    return {
      mode: 'exact',
      href: appendPdfFragment(url, {
        page,
        highlight: 'bbox',
        bbox: JSON.stringify(bbox),
      }),
      highlightKind: 'bbox',
    }
  }
  if (page && searchText) {
    return {
      mode: 'search',
      href: appendPdfFragment(url, { page, search: searchText }),
      highlightKind: 'text_search',
    }
  }
  if (page) {
    return { mode: 'page', href: appendPdfFragment(url, { page }), highlightKind: null }
  }
  return { mode: 'pdf', href: url, highlightKind: null }
}

function sourceLookupKeys(source) {
  const safeSource = citationFromSource(source)
  if (!safeSource) return []
  const sourceId = safeText(safeSource.source_id)
  const docId = safeText(safeSource.doc_id)
  const chunkId = safeText(safeSource.chunk_id)
  const number = safeText(safeSource.source_number)
  return [
    safeText(safeSource.citation_id),
    citationKey(safeSource),
    sourceId,
    sourceId ? `citation:${sourceId}` : '',
    docId && chunkId ? `${docId}#${chunkId}` : '',
    docId && chunkId ? `citation:${docId}#${chunkId}` : '',
    docId && number ? `${docId}#source-${number}` : '',
    number ? `source-number:${number}` : '',
    number ? `citation:${number}` : '',
  ].filter(Boolean)
}

function sourcesReferToSame(left, right) {
  const leftKeys = new Set(sourceLookupKeys(left))
  if (!leftKeys.size) return false
  return sourceLookupKeys(right).some((key) => leftKeys.has(key))
}

function sourceMatchesKeys(source, keys) {
  if (!keys?.size) return false
  return sourceLookupKeys(source).some((key) => keys.has(key))
}

function hasSourceValue(value) {
  if (value == null) return false
  if (typeof value === 'string') return value.trim() !== ''
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value).length > 0
  return true
}

function generalReferenceSource(source) {
  const safeSource = citationFromSource(source)
  if (!safeSource) return null
  return citationFromSource({
    ...withoutNestedEvidenceFields(withoutPrecisionLocatorFields(safeSource)),
    source_id: safeSource.source_id,
    source_number: safeSource.source_number,
    citation_id: safeSource.citation_id,
    hide_evidence_list: true,
    reference_only: true,
  })
}

const PRECISE_SOURCE_LOCATOR_KEYS = new Set([
  'bbox',
  'bounding_box',
  'boundingBox',
  'char_range',
  'charRange',
  'highlight_text',
  'highlightText',
  'text_range',
  'textRange',
  'text_search',
  'textSearch',
])

function mergeSourceDetails(primary, fallback) {
  const primarySource = citationFromSource(primary) || {}
  const fallbackSource = citationFromSource(fallback) || {}
  const merged = { ...fallbackSource, ...primarySource }
  for (const [key, value] of Object.entries(fallbackSource)) {
    if (PRECISE_SOURCE_LOCATOR_KEYS.has(key)) continue
    if (!hasSourceValue(primarySource[key]) && hasSourceValue(value)) merged[key] = value
  }
  return citationFromSource(merged)
}

function addSourceLookupEntries(lookup, source) {
  const safeSource = citationFromSource(source)
  if (!safeSource) return
  for (const key of sourceLookupKeys(safeSource)) {
    const existing = lookup.get(key)
    lookup.set(key, existing ? mergeSourceDetails(existing, safeSource) : safeSource)
  }
}

function collectDocumentSources(document) {
  const sources = []
  for (const block of document?.blocks || []) {
    if (block?.type !== 'source_list' || !Array.isArray(block.sources)) continue
    for (const source of block.sources) {
      const safeSource = citationFromSource(source)
      if (!safeSource) continue
      if (sources.some((item) => sourcesReferToSame(item, safeSource))) continue
      sources.push(safeSource)
    }
  }
  return sources
}

function sourcePdfActionLabel(source, openTarget = sourceOpenTarget(source)) {
  if (openTarget.mode === 'exact') return source?.page ? `View highlighted page ${source.page}` : 'View highlighted PDF'
  if (openTarget.mode === 'search') return source?.page ? `View matching text on page ${source.page}` : 'View matching text'
  if (source?.page) return `View page ${source.page}`
  return 'View PDF'
}

function sourcePdfEvidenceText(source, openTarget = sourceOpenTarget(source)) {
  const page = safeText(source?.page)
  const search = safeText(source?.text_search || source?.textSearch || source?.snippet)
  if (openTarget.mode === 'exact' && openTarget.highlightKind === 'char_range') {
    return page ? `Highlighted evidence on page ${page}.` : 'Highlighted evidence available.'
  }
  if (openTarget.mode === 'exact' && openTarget.highlightKind === 'bbox') {
    return page ? `Highlighted PDF area on page ${page}.` : 'Highlighted PDF area available.'
  }
  if (openTarget.mode === 'search') {
    return `Matching text on page ${page}${search ? `: ${search}` : '.'}`
  }
  if (openTarget.mode === 'page') {
    return `Showing page ${page}${search ? ` with source excerpt: ${search}` : '.'}`
  }
  if (openTarget.mode === 'pdf') return 'PDF available, but page metadata was not provided.'
  return 'PDF locator unavailable. Showing source metadata and snippet evidence.'
}

function rectFromElement(element) {
  if (!element?.getBoundingClientRect) return null
  const rect = element.getBoundingClientRect()
  return {
    left: rect.left,
    top: rect.top,
    right: rect.right,
    bottom: rect.bottom,
    width: rect.width,
    height: rect.height,
  }
}

function intersectRects(leftRect, rightRect) {
  const left = Math.max(leftRect.left, rightRect.left)
  const top = Math.max(leftRect.top, rightRect.top)
  const right = Math.min(leftRect.right, rightRect.right)
  const bottom = Math.min(leftRect.bottom, rightRect.bottom)
  if (right <= left || bottom <= top) return leftRect
  return { left, top, right, bottom, width: right - left, height: bottom - top }
}

function tooltipBoundaryForAnchor(anchor) {
  const viewport = {
    left: SOURCE_TOOLTIP_EDGE_GAP,
    top: SOURCE_TOOLTIP_EDGE_GAP,
    right: Math.max(SOURCE_TOOLTIP_EDGE_GAP, window.innerWidth - SOURCE_TOOLTIP_EDGE_GAP),
    bottom: Math.max(SOURCE_TOOLTIP_EDGE_GAP, window.innerHeight - SOURCE_TOOLTIP_EDGE_GAP),
  }
  const container = anchor?.closest?.('[data-source-drawer]')
    || anchor?.closest?.('[data-response-document-root]')
    || anchor?.closest?.('[role="dialog"]')
  const containerRect = rectFromElement(container)
  if (!containerRect) return { ...viewport, width: viewport.right - viewport.left, height: viewport.bottom - viewport.top }
  const bounded = intersectRects(viewport, containerRect)
  return { ...bounded, width: bounded.right - bounded.left, height: bounded.bottom - bounded.top }
}

function clampPlacement(value, min, max) {
  if (max < min) return min
  return Math.min(max, Math.max(min, value))
}

function placementFits(placement, bounds) {
  return (
    placement.left >= bounds.left &&
    placement.top >= bounds.top &&
    placement.left + placement.width <= bounds.right &&
    placement.top + placement.height <= bounds.bottom
  )
}

function placementOverflow(placement, bounds) {
  return (
    Math.max(bounds.left - placement.left, 0) +
    Math.max(placement.left + placement.width - bounds.right, 0) +
    Math.max(bounds.top - placement.top, 0) +
    Math.max(placement.top + placement.height - bounds.bottom, 0)
  )
}

function sourceTooltipPlacement(anchorRect, tooltipSize, bounds) {
  const placements = [
    {
      placement: 'bottom-right',
      left: anchorRect.left,
      top: anchorRect.bottom + SOURCE_TOOLTIP_OFFSET,
    },
    {
      placement: 'bottom-left',
      left: anchorRect.right - tooltipSize.width,
      top: anchorRect.bottom + SOURCE_TOOLTIP_OFFSET,
    },
    {
      placement: 'top-right',
      left: anchorRect.left,
      top: anchorRect.top - tooltipSize.height - SOURCE_TOOLTIP_OFFSET,
    },
    {
      placement: 'top-left',
      left: anchorRect.right - tooltipSize.width,
      top: anchorRect.top - tooltipSize.height - SOURCE_TOOLTIP_OFFSET,
    },
  ].map((placement) => ({ ...placement, ...tooltipSize }))

  const exact = placements.find((placement) => placementFits(placement, bounds))
  if (exact) return exact

  const fallback = [...placements].sort((leftPlacement, rightPlacement) => (
    placementOverflow(leftPlacement, bounds) - placementOverflow(rightPlacement, bounds)
  ))[0] || placements[0]
  return {
    ...fallback,
    placement: `${fallback.placement}-clamped`,
    left: clampPlacement(fallback.left, bounds.left, bounds.right - tooltipSize.width),
    top: clampPlacement(fallback.top, bounds.top, bounds.bottom - tooltipSize.height),
  }
}

function SourceHoverCard({ source, anchorRef }) {
  const tooltipRef = useRef(null)
  const [position, setPosition] = useState({
    left: 0,
    top: 0,
    width: SOURCE_TOOLTIP_WIDTH,
    maxHeight: 320,
    placement: 'measuring',
    visibility: 'hidden',
  })
  const location = source ? sourceLocationLabel(source) : null

  useLayoutEffect(() => {
    if (!source) return undefined
    const anchor = anchorRef?.current
    const tooltip = tooltipRef.current
    if (!anchor || !tooltip) return undefined

    const updatePosition = () => {
      const anchorRect = rectFromElement(anchor)
      if (!anchorRect) return
      const bounds = tooltipBoundaryForAnchor(anchor)
      const width = Math.max(
        Math.min(SOURCE_TOOLTIP_WIDTH, bounds.width),
        Math.min(SOURCE_TOOLTIP_MIN_WIDTH, bounds.width),
      )
      const maxHeight = Math.max(0, bounds.height)
      tooltip.style.width = `${width}px`
      tooltip.style.maxHeight = `${maxHeight}px`
      const tooltipRect = rectFromElement(tooltip) || { height: 0 }
      const next = sourceTooltipPlacement(
        anchorRect,
        { width, height: tooltipRect.height },
        bounds,
      )
      setPosition({
        left: next.left,
        top: next.top,
        width,
        maxHeight,
        placement: next.placement,
        visibility: 'visible',
      })
    }

    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [anchorRef, source])

  if (!source || typeof document === 'undefined') return null

  return createPortal(
    <div
      ref={tooltipRef}
      role="tooltip"
      className="pointer-events-none fixed z-50 block rounded-md border border-hairline bg-surface-1 px-3 py-2 text-left text-[11px] font-normal text-ink shadow-lg"
      style={{
        display: 'block',
        left: position.left,
        top: position.top,
        width: position.width,
        maxHeight: position.maxHeight,
        overflowY: 'auto',
        visibility: position.visibility,
      }}
      data-source-chip-hover=""
      data-source-chip-hover-placement={position.placement}
    >
      <span className="block font-semibold text-ink">{safeText(source.title) || 'Source'}</span>
      {source.organization ? <span className="mt-0.5 block text-ink-muted">{source.organization}</span> : null}
      {location ? <span className="mt-1 block text-ink-subtle">{location}</span> : null}
      {source.snippet ? <span className="mt-1.5 block text-ink-muted">{source.snippet}</span> : null}
    </div>,
    document.body,
  )
}

function SourceChip({ citation, index, hoverId, activeHoverId, setActiveHoverId, onOpenSource }) {
  const source = citationFromSource(citation)
  const chipRef = useRef(null)
  if (!source) return null
  const sourceId = citationKey(source) || `citation:${index + 1}`
  const citationId = safeText(source.citation_id)
  const id = hoverId || `${sourceId}:chip:${index}`
  const label = `[${source.source_number || index + 1}]`
  const openTarget = sourceOpenTarget(source)
  return (
    <span className="relative inline-flex align-baseline">
      <button
        ref={chipRef}
        type="button"
        className="mx-1 inline-flex h-5 min-w-5 items-center justify-center rounded-md border border-hairline bg-surface-2 px-1.5 text-[11px] font-semibold leading-none text-primary hover:bg-surface-3 focus:outline-none focus:ring-2 focus:ring-primary/30"
        aria-label={`Open source ${source.source_number || index + 1}`}
        data-source-chip=""
        data-citation-id={citationId || undefined}
        data-source-id={safeText(source.source_id) || undefined}
        data-doc-id={safeText(source.doc_id) || undefined}
        data-chunk-id={safeText(source.chunk_id) || undefined}
        data-source-number={safeText(source.source_number) || undefined}
        data-source-title={safeText(source.title) || undefined}
        data-source-open-mode={openTarget.mode}
        data-source-highlight-kind={openTarget.highlightKind || undefined}
        onMouseEnter={() => setActiveHoverId(id)}
        onMouseLeave={() => setActiveHoverId((current) => (current === id ? null : current))}
        onFocus={() => setActiveHoverId(id)}
        onBlur={() => setActiveHoverId((current) => (current === id ? null : current))}
        onClick={() => onOpenSource?.(source)}
      >
        {label}
      </button>
      {activeHoverId === id ? <SourceHoverCard source={source} anchorRef={chipRef} /> : null}
    </span>
  )
}

function SourceEvidenceEntry({ source, role, onOpenPdf }) {
  const safeSource = citationFromSource(source)
  if (!safeSource) return null
  const location = sourceLocationLabel(safeSource)
  const openTarget = sourceOpenTarget(safeSource)
  const pdfHref = openTarget.href
  const sourceNumber = safeText(safeSource.source_number)
  const evidenceItems = safeSource.hide_evidence_list ? [] : (Array.isArray(safeSource.evidence) ? safeSource.evidence : [])
  const showSourcePdfAction = Boolean(pdfHref && !evidenceItems.length)
  return (
    <article
      className="rounded-md border border-hairline bg-surface-2 px-3 py-3"
      data-source-drawer-entry=""
      data-source-role={role}
      data-source-id={safeText(safeSource.source_id) || undefined}
      data-doc-id={safeText(safeSource.doc_id) || undefined}
      data-chunk-id={safeText(safeSource.chunk_id) || undefined}
      data-source-number={sourceNumber || undefined}
      data-source-title={safeText(safeSource.title) || undefined}
      data-source-open-mode={openTarget.mode}
      data-source-highlight-kind={openTarget.highlightKind || undefined}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase text-ink-subtle">
            {safeSource.reference_only ? 'General reference' : role === 'cited' ? 'Cited source' : 'Related source'}
            {sourceNumber ? ` ${sourceNumber}` : ''}
          </div>
          <div className="mt-0.5 break-words text-sm font-semibold text-ink">{safeSource.title || 'Source details'}</div>
          {safeSource.organization ? <div className="mt-0.5 text-xs text-ink-muted">{safeSource.organization}</div> : null}
        </div>
      </div>
      <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
        {safeSource.doc_id ? (
          <div className="min-w-0 rounded-md bg-surface-1 px-2.5 py-2">
            <dt className="font-semibold text-ink-muted">Document</dt>
            <dd className="mt-0.5 break-words text-ink">{safeSource.doc_id}</dd>
          </div>
        ) : null}
        {safeSource.chunk_id ? (
          <div className="min-w-0 rounded-md bg-surface-1 px-2.5 py-2">
            <dt className="font-semibold text-ink-muted">Chunk</dt>
            <dd className="mt-0.5 break-words text-ink">{safeSource.chunk_id}</dd>
          </div>
        ) : null}
        {location ? (
          <div className="min-w-0 rounded-md bg-surface-1 px-2.5 py-2">
            <dt className="font-semibold text-ink-muted">Location</dt>
            <dd className="mt-0.5 break-words text-ink">{location}</dd>
          </div>
        ) : null}
        {sourceNumber ? (
          <div className="min-w-0 rounded-md bg-surface-1 px-2.5 py-2">
            <dt className="font-semibold text-ink-muted">Citation</dt>
            <dd className="mt-0.5 break-words text-ink">Source {sourceNumber}</dd>
          </div>
        ) : null}
      </dl>
      {safeSource.snippet ? (
        <div className="mt-3 rounded-md bg-surface-1 px-3 py-2 text-xs text-ink" data-source-drawer-snippet="">
          {safeSource.snippet}
        </div>
      ) : null}
      {evidenceItems.length ? (
        <div className="mt-3 space-y-2" data-source-evidence-list="">
          {evidenceItems.map((item, evidenceIndex) => {
            const evidenceSource = citationFromSource(item)
            const evidenceTarget = sourceOpenTarget(evidenceSource)
            const evidenceHref = evidenceTarget.href
            return (
              <div
                key={safeText(evidenceSource?.citation_id) || `${safeText(safeSource.citation_id)}:evidence:${evidenceIndex}`}
                className="rounded-md border border-hairline bg-surface-1 px-3 py-2 text-xs"
                data-source-evidence-item=""
                data-source-id={safeText(evidenceSource?.source_id) || undefined}
                data-doc-id={safeText(evidenceSource?.doc_id) || undefined}
                data-chunk-id={safeText(evidenceSource?.chunk_id) || undefined}
                data-source-page={safeText(evidenceSource?.page) || undefined}
                data-source-open-mode={evidenceTarget.mode}
                data-source-highlight-kind={evidenceTarget.highlightKind || undefined}
                data-source-locator-confidence={safeText(evidenceSource?.locator_confidence) || undefined}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-semibold text-ink-muted">Evidence {evidenceIndex + 1}</div>
                  {safeText(evidenceSource?.locator_confidence) ? (
                    <div className="text-[11px] uppercase text-ink-subtle">{safeText(evidenceSource.locator_confidence).replace(/_/g, ' ')}</div>
                  ) : null}
                </div>
                {sourceLocationLabel(evidenceSource) ? (
                  <div className="mt-1 text-ink-subtle">{sourceLocationLabel(evidenceSource)}</div>
                ) : null}
                {evidenceSource?.snippet ? (
                  <div className="mt-1.5 text-ink">{evidenceSource.snippet}</div>
                ) : null}
                <div className="mt-1.5 text-ink-subtle" data-source-evidence-summary="">
                  {sourcePdfEvidenceText(evidenceSource, evidenceTarget)}
                </div>
                {evidenceHref ? (
                  <button
                    type="button"
                    className="mt-2 inline-flex items-center rounded-md bg-surface-3 px-2.5 py-1 text-[11px] font-semibold text-primary hover:bg-surface-2 focus:outline-none focus:ring-2 focus:ring-primary/30"
                    data-source-pdf-link=""
                    data-source-pdf-href={evidenceHref}
                    data-source-id={safeText(evidenceSource?.source_id) || undefined}
                    data-doc-id={safeText(evidenceSource?.doc_id) || undefined}
                    data-chunk-id={safeText(evidenceSource?.chunk_id) || undefined}
                    data-source-number={sourceNumber || undefined}
                    data-source-title={safeText(evidenceSource?.title) || undefined}
                    data-source-open-mode={evidenceTarget.mode}
                    data-source-highlight-kind={evidenceTarget.highlightKind || undefined}
                    onClick={(event) => {
                      event.preventDefault()
                      onOpenPdf?.(evidenceSource)
                    }}
                  >
                    {sourcePdfActionLabel(evidenceSource, evidenceTarget)}
                  </button>
                ) : null}
              </div>
            )
          })}
        </div>
      ) : null}
      {!evidenceItems.length ? (
        <div className="mt-3 text-xs text-ink-subtle" data-source-pdf-evidence-summary="">
          {sourcePdfEvidenceText(safeSource, openTarget)}
        </div>
      ) : null}
      {showSourcePdfAction ? (
        <button
          type="button"
          className="mt-3 inline-flex items-center rounded-md bg-surface-3 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-surface-1 focus:outline-none focus:ring-2 focus:ring-primary/30"
          data-source-pdf-link=""
          data-source-pdf-href={pdfHref}
          data-source-id={safeText(safeSource.source_id) || undefined}
          data-doc-id={safeText(safeSource.doc_id) || undefined}
          data-chunk-id={safeText(safeSource.chunk_id) || undefined}
          data-source-number={sourceNumber || undefined}
          data-source-title={safeText(safeSource.title) || undefined}
          data-source-open-mode={openTarget.mode}
          data-source-highlight-kind={openTarget.highlightKind || undefined}
          onClick={(event) => {
            event.preventDefault()
            onOpenPdf?.(safeSource)
          }}
        >
          {sourcePdfActionLabel(safeSource, openTarget)}
        </button>
      ) : null}
    </article>
  )
}

let pdfJsRuntimePromise = null

function loadPdfJsRuntime() {
  if (!pdfJsRuntimePromise) {
    pdfJsRuntimePromise = Promise.all([
      import('pdfjs-dist/legacy/build/pdf.mjs'),
      import('pdfjs-dist/legacy/build/pdf.worker.mjs?url'),
    ]).then(([pdfjs, workerUrl]) => {
      pdfjs.GlobalWorkerOptions.workerSrc = workerUrl.default
      return pdfjs
    })
  }
  return pdfJsRuntimePromise
}

function pdfRequestUrl(pdfHref) {
  const value = safeText(pdfHref)
  return value ? value.split('#')[0] : ''
}

function optionalPositiveInt(value) {
  const number = Number(value)
  if (!Number.isFinite(number) || number < 1) return null
  return Math.floor(number)
}

function normalizedTextWithMap(value) {
  const text = String(value || '')
  const chars = []
  const map = []
  let pendingSpace = false
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]
    if (/\s/.test(char)) {
      pendingSpace = chars.length > 0
      continue
    }
    if (pendingSpace) {
      chars.push(' ')
      map.push(index)
      pendingSpace = false
    }
    chars.push(char.toLowerCase())
    map.push(index)
  }
  return { text: chars.join(''), map }
}

function normalizedNeedle(value) {
  return safeText(value).replace(/\s+/g, ' ').trim().toLowerCase()
}

function findNormalizedRange(haystack, needle) {
  const normalizedSearch = normalizedNeedle(needle)
  if (!normalizedSearch) return null
  const normalizedHaystack = normalizedTextWithMap(haystack)
  let index = normalizedHaystack.text.indexOf(normalizedSearch)
  if (index < 0) {
    const words = normalizedSearch.split(' ').filter(Boolean)
    for (let size = Math.min(8, words.length); size >= 3 && index < 0; size -= 1) {
      const phrase = words.slice(0, size).join(' ')
      index = normalizedHaystack.text.indexOf(phrase)
      if (index >= 0) {
        const start = normalizedHaystack.map[index]
        const end = normalizedHaystack.map[index + phrase.length - 1] + 1
        return { start, end, matchedText: phrase, matchKind: 'text_search' }
      }
    }
    return null
  }
  const start = normalizedHaystack.map[index]
  const end = normalizedHaystack.map[index + normalizedSearch.length - 1] + 1
  return { start, end, matchedText: normalizedSearch, matchKind: 'text_search' }
}

function rectFromTextItem(item, viewport) {
  if (!item?.str) return null
  const tx = viewport.transform
  const tr = item.transform || [1, 0, 0, 1, 0, 0]
  const a = tx[0] * tr[0] + tx[2] * tr[1]
  const c = tx[0] * tr[2] + tx[2] * tr[3]
  const d = tx[1] * tr[2] + tx[3] * tr[3]
  const e = tx[0] * tr[4] + tx[2] * tr[5] + tx[4]
  const f = tx[1] * tr[4] + tx[3] * tr[5] + tx[5]
  const height = Math.max(6, Math.hypot(c, d))
  const width = Math.max(4, (Number(item.width) || safeText(item.str).length * 5) * viewport.scale)
  const left = Math.min(e, e + a)
  const top = f - height
  return { left, top, width, height }
}

function clampHighlightRect(rect, viewport) {
  const pageWidth = Math.max(1, Number(viewport?.width) || 1)
  const pageHeight = Math.max(1, Number(viewport?.height) || 1)
  const left = Number(rect?.left)
  const top = Number(rect?.top)
  const width = Number(rect?.width)
  const height = Number(rect?.height)
  if (![left, top, width, height].every(Number.isFinite) || width <= 0 || height <= 0) return null
  const clampedLeft = clampNumber(left, 0, pageWidth)
  const clampedTop = clampNumber(top, 0, pageHeight)
  const clampedRight = clampNumber(left + width, 0, pageWidth)
  const clampedBottom = clampNumber(top + Math.max(height, 8), 0, pageHeight)
  const clampedWidth = clampedRight - clampedLeft
  const clampedHeight = clampedBottom - clampedTop
  if (clampedWidth <= 0 || clampedHeight <= 0) return null
  return { left: clampedLeft, top: clampedTop, width: clampedWidth, height: clampedHeight }
}

function bboxHighlightRects(bbox, viewport) {
  const box = Array.isArray(bbox)
    ? bbox
    : bbox && typeof bbox === 'object'
      ? [bbox.x0 ?? bbox.left ?? bbox.x, bbox.y0 ?? bbox.top ?? bbox.y, bbox.x1 ?? bbox.right, bbox.y1 ?? bbox.bottom]
      : null
  if (!Array.isArray(box) || box.length < 4) return []
  const values = box.slice(0, 4).map(Number)
  if (values.some((value) => !Number.isFinite(value))) return []
  const [x1, y1, x2, y2] = values
  const [left, top, right, bottom] = viewport.convertToViewportRectangle
    ? viewport.convertToViewportRectangle([x1, y1, x2, y2])
    : [x1, y1, x2, y2]
  const rect = clampHighlightRect({
    left: Math.min(left, right),
    top: Math.min(top, bottom),
    width: Math.abs(right - left),
    height: Math.abs(bottom - top),
  }, viewport)
  return rect ? [rect] : []
}

function sourceHighlightRects({ source, openTarget, textContent, viewport }) {
  if (openTarget?.highlightKind === 'bbox') {
    const rects = bboxHighlightRects(source?.bbox || source?.bounding_box || source?.boundingBox, viewport)
    if (rects.length) return { rects, kind: 'bbox', matchedText: '' }
  }

  let pageText = ''
  const textItems = []
  for (const item of textContent?.items || []) {
    const text = safeText(item?.str)
    if (!text) continue
    const start = pageText.length
    pageText += text
    const end = pageText.length
    const rect = rectFromTextItem(item, viewport)
    if (rect) textItems.push({ start, end, rect, text })
    pageText += ' '
  }
  const textLength = textItems.length
    ? Math.max(...textItems.map((item) => item.end))
    : pageText.trimEnd().length

  const search = openTarget?.highlightKind === 'text_search'
    ? safeText(source?.text_search || source?.textSearch || source?.highlight_text || source?.highlightText)
    : ''
  const searchRange = findNormalizedRange(pageText, search)
  const charRange = normalCharRange(source?.char_range || source?.charRange)
  const range = searchRange || (openTarget?.highlightKind === 'char_range' && charRange ? {
    start: clampNumber(charRange.start, 0, Math.max(0, textLength - 1)),
    end: clampNumber(charRange.end, 0, textLength),
    matchedText: '',
    matchKind: 'char_range',
  } : null)
  if (!range || range.end <= range.start) return { rects: [], kind: null, matchedText: '' }

  const rects = textItems
    .filter((item) => item.end > range.start && item.start < range.end)
    .map((item) => item.rect)
    .map((rect) => clampHighlightRect(rect, viewport))
    .filter(Boolean)
  return {
    rects,
    kind: searchRange ? 'text_search' : 'char_range',
    matchedText: range.matchedText,
  }
}

function isTestDomRuntime() {
  return typeof navigator !== 'undefined' && /\bjsdom\b/i.test(navigator.userAgent || '')
}

function SourcePdfCanvasView({ source, pdfHref, openTarget }) {
  const frameRef = useRef(null)
  const canvasRef = useRef(null)
  const pageRef = useRef(null)
  const [state, setState] = useState({ status: 'loading', pageNumber: null, pageCount: null, error: '' })
  const [highlightState, setHighlightState] = useState({ rects: [], kind: null, matchedText: '', width: 0, height: 0 })
  const [zoom, setZoom] = useState(1)
  const requestedPage = clampNumber(source?.page || 1, 1, 100000)
  const sourcePageCount = optionalPositiveInt(source?.page_count || source?.pageCount)
  const [activePage, setActivePage] = useState(requestedPage)
  const requestUrl = pdfRequestUrl(pdfHref)
  const zoomLabel = `${Math.round(zoom * 100)}%`
  const pageCount = optionalPositiveInt(state.pageCount) || sourcePageCount
  const currentPage = clampNumber(state.pageNumber || activePage || requestedPage, 1, pageCount || 100000)
  const activePdfHref = activePage === requestedPage || !requestUrl
    ? pdfHref
    : appendPdfFragment(requestUrl, { page: activePage })

  const updateZoom = useCallback((delta) => {
    setZoom((current) => clampNumber(Number((current + delta).toFixed(2)), 0.5, 2.5))
  }, [])

  const goToPage = useCallback((delta) => {
    setActivePage((current) => clampNumber((Number(current) || requestedPage) + delta, 1, pageCount || 100000))
  }, [pageCount, requestedPage])

  useEffect(() => {
    setActivePage(requestedPage)
  }, [requestUrl, requestedPage])

  useEffect(() => {
    let cancelled = false
    let pdfDocument = null
    let renderTask = null
    let resizeObserver = null
    let resizeTimer = null
    const controller = new AbortController()

    async function renderPage(pdf, pageNumber) {
      const canvas = canvasRef.current
      const context = canvas?.getContext?.('2d')
      if (!canvas || !context) throw new Error('PDF canvas rendering is not available in this browser.')

      const page = await pdf.getPage(pageNumber)
      if (cancelled) return
      const baseViewport = page.getViewport({ scale: 1 })
      const availableWidth = Math.max(220, (frameRef.current?.clientWidth || 520) - 24)
      const fitScale = availableWidth / baseViewport.width
      const scale = clampNumber(fitScale * zoom, 0.35, 3)
      const viewport = page.getViewport({ scale })
      const devicePixelRatio = clampNumber(window.devicePixelRatio || 1, 1, 2)

      if (renderTask) {
        renderTask.cancel()
        renderTask = null
      }

      canvas.width = Math.floor(viewport.width * devicePixelRatio)
      canvas.height = Math.floor(viewport.height * devicePixelRatio)
      canvas.style.width = `${Math.floor(viewport.width)}px`
      canvas.style.height = `${Math.floor(viewport.height)}px`
      if (pageRef.current) {
        pageRef.current.style.width = `${Math.floor(viewport.width)}px`
        pageRef.current.style.height = `${Math.floor(viewport.height)}px`
      }
      context.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0)
      context.clearRect(0, 0, viewport.width, viewport.height)

      const textContent = await page.getTextContent()
      if (cancelled) return
      const highlight = sourceHighlightRects({ source, openTarget, textContent, viewport })
      setHighlightState({
        ...highlight,
        width: Math.floor(viewport.width),
        height: Math.floor(viewport.height),
      })

      renderTask = page.render({ canvasContext: context, viewport })
      try {
        await renderTask.promise
      } catch (err) {
        if (err?.name !== 'RenderingCancelledException') throw err
      } finally {
        renderTask = null
      }
    }

    async function loadAndRender() {
      if (!requestUrl) {
        setState({ status: 'error', pageNumber: null, pageCount: null, error: 'No PDF route is available for this source.' })
        return
      }

      const canvas = canvasRef.current
      if (!canvas || isTestDomRuntime()) {
        setHighlightState({ rects: [], kind: openTarget.highlightKind || null, matchedText: '', width: 0, height: 0 })
        setState({ status: 'ready', pageNumber: activePage, pageCount: sourcePageCount, error: '' })
        return
      }

      setState({ status: 'loading', pageNumber: activePage, pageCount: sourcePageCount, error: '' })
      const response = await fetch(requestUrl, { signal: controller.signal })
      if (!response.ok) throw new Error(`PDF request failed with ${response.status}.`)
      const pdfData = new Uint8Array(await response.arrayBuffer())
      const pdfjs = await loadPdfJsRuntime()
      if (cancelled) return
      pdfDocument = await pdfjs.getDocument({ data: pdfData, disableRange: true, disableStream: true }).promise
      const pageNumber = clampNumber(activePage, 1, pdfDocument.numPages || 1)
      setState({ status: 'rendering', pageNumber, pageCount: pdfDocument.numPages || null, error: '' })
      await renderPage(pdfDocument, pageNumber)
      if (cancelled) return
      setState({ status: 'ready', pageNumber, pageCount: pdfDocument.numPages || null, error: '' })

      if (typeof ResizeObserver !== 'undefined' && frameRef.current) {
        resizeObserver = new ResizeObserver(() => {
          window.clearTimeout(resizeTimer)
          resizeTimer = window.setTimeout(() => {
            if (!cancelled && pdfDocument) renderPage(pdfDocument, pageNumber).catch(() => {})
          }, 120)
        })
        resizeObserver.observe(frameRef.current)
      }
    }

    loadAndRender().catch((err) => {
      if (cancelled || err?.name === 'AbortError') return
      setState({
        status: 'error',
        pageNumber: activePage,
        pageCount: null,
        error: safeText(err?.message) || 'The PDF could not be rendered in the side panel.',
      })
    })

    return () => {
      cancelled = true
      controller.abort()
      if (resizeTimer) window.clearTimeout(resizeTimer)
      resizeObserver?.disconnect()
      renderTask?.cancel()
      pdfDocument?.destroy?.()
    }
  }, [requestUrl, activePage, sourcePageCount, source, openTarget, zoom])

  const statusText = state.status === 'ready'
    ? `Rendered page ${state.pageNumber || activePage}${state.pageCount ? ` of ${state.pageCount}` : ''}`
    : state.status === 'rendering'
      ? `Rendering page ${state.pageNumber || activePage}${state.pageCount ? ` of ${state.pageCount}` : ''}`
      : state.status === 'error'
        ? 'PDF preview unavailable'
        : `Loading page ${activePage}`

  return (
    <div
      className="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface-2"
      data-source-pdf-frame=""
      data-source-pdf-renderer="pdfjs"
      data-source-pdf-src={activePdfHref}
      data-source-id={safeText(source?.source_id) || undefined}
      data-doc-id={safeText(source?.doc_id) || undefined}
      data-chunk-id={safeText(source?.chunk_id) || undefined}
      data-source-number={safeText(source?.source_number) || undefined}
      data-source-title={safeText(source?.title) || undefined}
      data-source-open-mode={openTarget.mode}
      data-source-highlight-kind={openTarget.highlightKind || undefined}
    >
      <div className="shrink-0 px-3 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-hairline bg-surface-1 px-3 py-2 text-xs text-ink-muted">
          <div data-source-pdf-status="">
            {statusText}
            {state.status === 'error' && state.error ? <span className="block pt-1 text-red-500">{state.error}</span> : null}
          </div>
          <div className="flex items-center gap-1" data-source-pdf-page-controls="">
            <button
              type="button"
              className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-hairline bg-surface-2 text-ink-muted hover:bg-surface-3 focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:opacity-50"
              aria-label="Previous PDF page"
              title="Previous page"
              disabled={currentPage <= 1 || state.status === 'loading'}
              onClick={() => goToPage(-1)}
              data-source-pdf-previous-page=""
            >
              <span className="material-symbols-outlined text-base">chevron_left</span>
            </button>
            <button
              type="button"
              className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-hairline bg-surface-2 text-ink-muted hover:bg-surface-3 focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:opacity-50"
              aria-label="Next PDF page"
              title="Next page"
              disabled={Boolean(pageCount && currentPage >= pageCount) || state.status === 'loading'}
              onClick={() => goToPage(1)}
              data-source-pdf-next-page=""
            >
              <span className="material-symbols-outlined text-base">chevron_right</span>
            </button>
          </div>
          <div className="flex items-center gap-1" data-source-pdf-zoom-controls="">
            <button
              type="button"
              className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-hairline bg-surface-2 text-ink-muted hover:bg-surface-3 focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:opacity-50"
              aria-label="Zoom out PDF"
              title="Zoom out"
              disabled={zoom <= 0.5}
              onClick={() => updateZoom(-0.1)}
              data-source-pdf-zoom-out=""
            >
              <span className="material-symbols-outlined text-base">zoom_out</span>
            </button>
            <button
              type="button"
              className="inline-flex h-7 min-w-[3.25rem] items-center justify-center rounded-md border border-hairline bg-surface-2 px-2 text-[11px] font-semibold text-ink-muted hover:bg-surface-3 focus:outline-none focus:ring-2 focus:ring-primary/30"
              aria-label="Fit PDF to panel width"
              title="Fit to panel width"
              onClick={() => setZoom(1)}
              data-source-pdf-fit-width=""
              data-source-pdf-zoom-value={zoomLabel}
            >
              {zoomLabel}
            </button>
            <button
              type="button"
              className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-hairline bg-surface-2 text-ink-muted hover:bg-surface-3 focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:opacity-50"
              aria-label="Zoom in PDF"
              title="Zoom in"
              disabled={zoom >= 2.5}
              onClick={() => updateZoom(0.1)}
              data-source-pdf-zoom-in=""
            >
              <span className="material-symbols-outlined text-base">zoom_in</span>
            </button>
          </div>
        </div>
      </div>
      <div
        ref={frameRef}
        className="min-h-0 flex-1 overflow-auto px-3 pb-3"
        data-source-pdf-scroll-frame=""
      >
        <div className="flex min-h-full w-max min-w-full justify-center py-3">
          <div
            ref={pageRef}
            className="relative rounded-sm border border-hairline bg-white shadow-sm"
            data-source-pdf-page=""
          >
            <canvas
              ref={canvasRef}
              className="block bg-white"
              data-source-pdf-canvas=""
            />
            <div
              className="pointer-events-none absolute left-0 top-0"
              style={{
                width: highlightState.width ? `${highlightState.width}px` : '100%',
                height: highlightState.height ? `${highlightState.height}px` : '100%',
              }}
              data-source-pdf-highlight-layer=""
              data-source-pdf-highlight-kind={highlightState.kind || undefined}
              data-source-pdf-highlight-count={String(highlightState.rects.length)}
            >
              {highlightState.rects.map((rect, index) => (
                <span
                  key={`${Math.round(rect.left)}:${Math.round(rect.top)}:${index}`}
                  className="absolute rounded-[2px] bg-yellow-300/45 ring-1 ring-yellow-500/60 mix-blend-multiply"
                  style={{
                    left: `${rect.left}px`,
                    top: `${rect.top}px`,
                    width: `${rect.width}px`,
                    height: `${Math.max(rect.height, 8)}px`,
                  }}
                  data-source-pdf-highlight=""
                  data-source-pdf-highlight-kind={highlightState.kind || undefined}
                  data-source-pdf-highlight-text={highlightState.matchedText || undefined}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function SourcePdfView({ source, onBack }) {
  const safeSource = citationFromSource(source)
  if (!safeSource) return null
  const openTarget = sourceOpenTarget(safeSource)
  const pdfHref = openTarget.href
  return (
    <div className="flex min-h-0 flex-1 flex-col" data-source-pdf-view="">
      <div className="border-b border-hairline px-4 py-3">
        <button
          type="button"
          className="inline-flex items-center rounded-md px-2 py-1 text-xs font-semibold text-primary hover:bg-surface-2 focus:outline-none focus:ring-2 focus:ring-primary/30"
          onClick={onBack}
          data-source-pdf-back=""
        >
          Back to evidence
        </button>
        <div className="mt-2 text-sm font-semibold text-ink">
          {safeSource.source_number ? `Source ${safeSource.source_number}: ` : ''}{safeSource.title || 'PDF evidence'}
        </div>
        <div className="mt-1 text-xs text-ink-muted" data-source-pdf-evidence="">
          {sourcePdfEvidenceText(safeSource, openTarget)}
        </div>
      </div>
      {pdfHref ? (
        <SourcePdfCanvasView source={safeSource} pdfHref={pdfHref} openTarget={openTarget} />
      ) : (
        <div className="px-4 py-4 text-sm text-ink-muted">No PDF locator is available for this source.</div>
      )}
    </div>
  )
}

export function SourceDrawer({ source, sources = [], pdfSource, onOpenPdf, onBack, onClose }) {
  const safeSource = citationFromSource(source)
  const [drawerWidth, setDrawerWidth] = useState(EVIDENCE_DRAWER_DEFAULT_WIDTH)
  if (!safeSource) return null
  const sourceList = (Array.isArray(sources) ? sources : []).map(citationFromSource).filter(Boolean)
  const matchingSource = sourceList.find((item) => sourcesReferToSame(item, safeSource))
  const citedSource = mergeSourceDetails(safeSource, matchingSource)
  const relatedSources = sourceList
    .filter((item) => !sourcesReferToSame(item, citedSource))
    .map((item) => citationFromSource(item))
    .filter(Boolean)
  const activePdfSource = pdfSource
    ? mergeSourceDetails(pdfSource, sourceList.find((item) => sourcesReferToSame(item, pdfSource)))
    : null
  const drawerSource = activePdfSource || citedSource
  const openTarget = sourceOpenTarget(drawerSource)
  const view = activePdfSource ? 'pdf' : 'list'

  function handleResizePointerDown(event) {
    event.preventDefault()
    const startX = event.clientX
    const startWidth = drawerWidth
    const handlePointerMove = (moveEvent) => {
      const delta = startX - moveEvent.clientX
      setDrawerWidth(clampNumber(startWidth + delta, EVIDENCE_DRAWER_MIN_WIDTH, EVIDENCE_DRAWER_MAX_WIDTH))
    }
    const handlePointerUp = () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
    }
    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
  }

  return (
    <aside
      role="complementary"
      aria-label="Side evidence drawer"
      className="relative z-10 flex h-full max-w-[48%] shrink-0 flex-col overflow-hidden border-l border-hairline bg-surface-1 text-sm shadow-[-12px_0_24px_rgba(15,23,42,0.08)]"
      style={{
        width: `min(${drawerWidth}px, 48%)`,
        minWidth: `min(${EVIDENCE_DRAWER_MIN_WIDTH}px, 48%)`,
      }}
      data-source-drawer=""
      data-source-evidence-drawer=""
      data-shell-evidence-panel=""
      data-source-drawer-view={view}
      data-source-id={safeText(drawerSource.source_id) || undefined}
      data-doc-id={safeText(drawerSource.doc_id) || undefined}
      data-chunk-id={safeText(drawerSource.chunk_id) || undefined}
      data-source-number={safeText(drawerSource.source_number) || undefined}
      data-source-title={safeText(drawerSource.title) || undefined}
      data-source-open-mode={openTarget.mode}
      data-source-highlight-kind={openTarget.highlightKind || undefined}
    >
      <div
        className="absolute bottom-0 left-0 top-0 w-2 cursor-ew-resize border-l border-transparent hover:border-primary/40"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize evidence drawer"
        data-source-drawer-resize-handle=""
        onPointerDown={handleResizePointerDown}
      />
      <div className="flex items-start justify-between gap-3 border-b border-hairline px-4 py-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-ink">Side evidence</div>
          <div className="mt-0.5 truncate text-xs text-ink-muted">
            {drawerSource.source_number ? `Source ${drawerSource.source_number}` : 'Source'} · {drawerSource.title || drawerSource.doc_id || 'Evidence'}
          </div>
        </div>
        <button
          type="button"
          className="rounded-md px-2 py-1 text-xs font-semibold text-ink-muted hover:bg-surface-2 focus:outline-none focus:ring-2 focus:ring-primary/30"
          onClick={onClose}
          data-source-drawer-close=""
        >
          Close
        </button>
      </div>
      {activePdfSource ? (
        <SourcePdfView source={activePdfSource} onBack={onBack} />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          <div className="space-y-3">
            <SourceEvidenceEntry source={citedSource} role="cited" onOpenPdf={onOpenPdf} />
            {relatedSources.length ? (
              <section className="space-y-2" data-related-source-section="">
                <div className="text-xs font-semibold uppercase text-ink-subtle">Related supporting sources</div>
                {relatedSources.map((relatedSource, index) => (
                  <SourceEvidenceEntry
                    key={`${citationKey(relatedSource) || relatedSource.source_id || relatedSource.doc_id || 'related'}:${index}`}
                    source={relatedSource}
                    role="related"
                    onOpenPdf={onOpenPdf}
                  />
                ))}
              </section>
            ) : null}
          </div>
        </div>
      )}
    </aside>
  )
}

function ApprovalBlock({
  block,
  pendingApproval,
  showApprovalActions,
  decideApproval,
  isDecidingApproval,
  approvalReason,
  setApprovalReason,
}) {
  const rows = Array.isArray(block.rows) ? block.rows : []
  return (
    <CompactCard title={block.title || 'Approval required'} blockType="approval_required" blockId={block.id} contract={block.contract}>
      <div className="mt-1 text-sm text-ink">{block.summary || 'Review the proposed change before it is applied.'}</div>
      <RowPreview rows={rows} limit={5} />
      {showApprovalActions ? (
        <div className="mt-3 space-y-2">
          <textarea
            value={approvalReason || ''}
            onChange={(event) => setApprovalReason?.(event.target.value)}
            placeholder="Optional rejection reason"
            rows={2}
            disabled={isDecidingApproval}
            className="w-full rounded-md border border-hairline bg-white px-3 py-2 text-xs text-ink placeholder:text-ink-subtle focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-60"
          />
          <div className="flex flex-wrap items-center gap-2">
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
    <CompactCard
      title={block.title || 'Mutation result'}
      blockType="mutation_result"
      blockId={block.id}
      contract={block.contract}
    >
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
      contract={mutationBlock?.contract}
    >
      <div
        data-final-result-card=""
        data-response-block-type="mutation_result"
        data-response-block-id={mutationBlock?.id}
        data-response-contract={safeText(mutationBlock?.contract) || undefined}
      >
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
  const previewLimit = Number.isFinite(Number(block.preview_limit)) ? Number(block.preview_limit) : PREVIEW_LIMIT
  return (
    <CompactCard
      title={block.title || 'Records'}
      blockType="record_preview"
      blockId={block.id}
      contract={block.contract}
      entityType={block.entity_type}
      readScope={block.read_scope}
      requestedFields={block.requested_fields}
      displayMode={block.display_mode}
      entityCount={block.entity_count}
      previewLimit={previewLimit}
      detailsCollapsed={block.details_collapsed}
    >
      <RowPreview rows={rows} limit={previewLimit} />
      {rows.length > previewLimit ? <ExpandableTable title={block.title || 'Records'} rows={rows} defaultCollapsed={block.details_collapsed !== false} blockId={block.id} /> : null}
    </CompactCard>
  )
}

function ResultTableBlock({ block }) {
  const rows = Array.isArray(block.rows) ? block.rows : []
  const previewLimit = Number.isFinite(Number(block.preview_limit)) ? Number(block.preview_limit) : PREVIEW_LIMIT
  const defaultCollapsed = block.details_collapsed === true || block.display_mode === 'collapsed_collection_table'
  return (
    <CompactCard
      title={block.title || 'Results'}
      blockType="result_table"
      blockId={block.id}
      contract={block.contract}
      entityType={block.entity_type}
      readScope={block.read_scope}
      requestedFields={block.requested_fields}
      displayMode={block.display_mode}
      entityCount={block.entity_count}
      previewLimit={previewLimit}
      detailsCollapsed={block.details_collapsed}
    >
      <RowPreview rows={rows} limit={previewLimit} />
      <ExpandableTable
        title={block.title || 'Results'}
        rows={rows}
        defaultCollapsed={defaultCollapsed}
        blockId={block.id}
        requestedFields={block.requested_fields}
      />
    </CompactCard>
  )
}

function SafetyNoticeBlock({ block }) {
  const safetyContent = safeText(block.safety_content || block.safetyContent || block.message || block.summary)
  if (!safetyContent) return null
  return (
    <CompactCard
      title={block.title || 'Safety notice'}
      tone="warning"
      blockType="safety_notice"
      blockId={block.id}
      contract={block.contract || 'safety_notice_v1'}
    >
      <div className="mt-1 text-sm text-ink" data-safety-notice-content="">{safetyContent}</div>
    </CompactCard>
  )
}

function KnowledgeAnswerBlock({ block, sourceLookup, selectedSourceKeys, selectedCitationId, activeHoverId, setActiveHoverId, onOpenSource }) {
  const blockCitations = Array.isArray(block.citations) ? block.citations : []
  const citationsById = new Map(sourceLookup)
  for (const citation of blockCitations) {
    const safeCitation = citationFromSource(citation)
    const existing = sourceLookupKeys(safeCitation)
      .map((key) => citationsById.get(key))
      .find(Boolean)
    const mergedCitation = mergeSourceDetails(safeCitation, existing)
    addSourceLookupEntries(citationsById, mergedCitation)
  }
  const segments = Array.isArray(block.segments) && block.segments.length
    ? block.segments
    : [{ text: safeText(block.answer), citation_ids: blockCitations.map((citation) => citationKey(citationFromSource(citation))).filter(Boolean) }]
  const procedureStepSegments = segments.length > 1 && segments.every((segment) => /^\s*\d+[\.)]\s+/.test(safeText(segment.text)))
  const exactSelectedCitationId = safeText(selectedCitationId)
  const blockHasExactSelectedCitation = Boolean(
    exactSelectedCitationId &&
    blockCitations.some((citation) => safeText(citation?.citation_id || citation?.citationId) === exactSelectedCitationId),
  )
  return (
    <CompactCard
      title={block.title || 'Procedure guidance'}
      blockType="knowledge_answer"
      blockId={block.id}
      contract={block.contract || 'knowledge_answer_v1'}
    >
      <div className="mt-1 w-full max-w-none whitespace-pre-wrap break-words text-sm text-ink" data-knowledge-answer="">
        {segments.map((segment, segmentIndex) => {
          const text = safeText(segment.text)
          if (!text) return null
          const citationIds = Array.isArray(segment.citation_ids || segment.citationIds)
            ? (segment.citation_ids || segment.citationIds).map((item) => safeText(item)).filter(Boolean)
            : []
          const citations = citationIds.map((id) => citationsById.get(id)).filter(Boolean)
          const selectedCitation = blockHasExactSelectedCitation
            ? citations.find((citation) => safeText(citation?.citation_id || citation?.citationId) === exactSelectedCitationId)
            : citations.find((citation) => sourceMatchesKeys(citation, selectedSourceKeys))
          const primaryCitation = selectedCitation ? citationFromSource(selectedCitation) : null
          const answerText = selectedCitation ? (
            <mark
              className="rag-citation-highlight"
              data-cited-answer-text=""
              data-citation-id={safeText(primaryCitation?.citation_id) || undefined}
              data-source-id={safeText(primaryCitation?.source_id) || undefined}
              data-doc-id={safeText(primaryCitation?.doc_id) || undefined}
              data-chunk-id={safeText(primaryCitation?.chunk_id) || undefined}
              data-source-number={safeText(primaryCitation?.source_number) || undefined}
              data-source-title={safeText(primaryCitation?.title) || undefined}
            >
              {text}
            </mark>
          ) : text
          const SegmentElement = procedureStepSegments ? 'div' : 'span'
          return (
            <SegmentElement
              key={`${block.id}:segment:${segmentIndex}`}
              className={procedureStepSegments ? 'block pb-1 last:pb-0' : undefined}
              data-knowledge-answer-segment=""
              data-procedure-answer-segment={procedureStepSegments ? '' : undefined}
              data-cited-answer-segment={selectedCitation ? '' : undefined}
              data-source-id={safeText(primaryCitation?.source_id) || undefined}
            >
              {segmentIndex > 0 && !procedureStepSegments ? ' ' : ''}
              {answerText}
              {citations.map((citation, citationIndex) => (
                <SourceChip
                  key={`${citationKey(citation)}:${citationIndex}`}
                  citation={citation}
                  index={citationIndex}
                  hoverId={`${block.id || 'knowledge'}:segment:${segmentIndex}:citation:${citationIndex}:${citationKey(citation) || 'source'}`}
                  activeHoverId={activeHoverId}
                  setActiveHoverId={setActiveHoverId}
                  onOpenSource={onOpenSource}
                />
              ))}
            </SegmentElement>
          )
        })}
      </div>
    </CompactCard>
  )
}

function SourceListBlock({ block, onOpenSource }) {
  const sources = Array.isArray(block.sources) ? block.sources : []
  if (!sources.length) return null
  return (
    <CompactCard title={block.title || 'Knowledge sources'} blockType="source_list" blockId={block.id} contract={block.contract || 'source_list_v1'}>
      <div className="mt-2 space-y-2 text-xs text-ink-muted">
        {sources.map((source, index) => {
          const safeSource = citationFromSource(source)
          const displaySource = generalReferenceSource(safeSource) || safeSource
          const title = safeText(displaySource?.title || displaySource?.doc_id || `Source ${index + 1}`)
          const snippet = safeText(displaySource?.snippet)
          return (
            <button
              type="button"
              key={`${displaySource?.source_id || displaySource?.doc_id || title}-${index}`}
              className="block w-full rounded-md bg-surface-2 px-2.5 py-2 text-left transition-colors hover:bg-surface-3 focus:outline-none focus:ring-2 focus:ring-primary/30"
              onClick={() => onOpenSource?.(displaySource)}
              aria-label={`Toggle source evidence for ${title}`}
              data-response-contract={safeText(source?.contract) || undefined}
              data-source-list-open=""
              data-source-id={safeText(displaySource?.source_id) || undefined}
              data-doc-id={safeText(displaySource?.doc_id) || undefined}
              data-chunk-id={safeText(displaySource?.chunk_id) || undefined}
              data-source-number={safeText(displaySource?.source_number) || undefined}
              data-source-title={title || undefined}
            >
              <span className="block font-semibold text-ink">{title}</span>
              <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                {['doc_id', 'chunk_id', 'page', 'machine_id', 'organization'].map((key) => (
                  displaySource?.[key] ? <span key={key}>{humanizeResponseDocumentKey(key)}: {String(displaySource[key])}</span> : null
                ))}
              </span>
              {snippet ? <span className="mt-1.5 block line-clamp-2 text-ink-subtle">{snippet}</span> : null}
            </button>
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
    <CompactCard
      title={block.title || 'Status'}
      blockType="status_result"
      blockId={block.id}
      contract={block.contract}
      entityType={block.entity_type}
      readScope={block.read_scope}
      requestedFields={block.requested_fields}
      displayMode={block.display_mode}
      entityCount={block.entity_count}
      previewLimit={block.preview_limit}
      detailsCollapsed={block.details_collapsed}
      fieldCount={fields.length}
      secondaryFieldCount={secondaryFields.length}
    >
      {shouldShowSummary ? <div className="mt-1 text-sm text-ink">{summary}</div> : null}
      {fields.length ? (
        <dl className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
          {fields.map((field, index) => (
            <div
              key={`${field.key || field.label}-${index}`}
              className="min-w-0 rounded-md bg-surface-2 px-2.5 py-2"
              data-status-field=""
              data-status-field-key={dataText(field.key)}
            >
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
          data-status-details=""
        >
          <dl className="grid gap-2 border-t border-hairline px-3 py-3 text-xs sm:grid-cols-2">
            {secondaryFields.map((field, index) => (
              <div
                key={`${field.key || field.label}-${index}`}
                className="min-w-0"
                data-status-secondary-field=""
                data-status-field-key={dataText(field.key)}
              >
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
  if (block.type === 'result_table') return <ResultTableBlock key={block.id} block={block} />
  if (block.type === 'status_result') return <StatusResultBlock key={block.id} block={block} documentMessage={props.documentMessage} />
  if (block.type === 'record_preview') return <RecordPreviewBlock key={block.id} block={block} />
  if (block.type === 'safety_notice') return <SafetyNoticeBlock key={block.id} block={block} />
  if (block.type === 'knowledge_answer') return <KnowledgeAnswerBlock key={block.id} block={block} {...props} />
  if (block.type === 'source_list') return <SourceListBlock key={block.id} block={block} onOpenSource={props.onOpenSource} />
  if (block.type === 'warning' || block.type === 'diagnostic') return <DiagnosticBlock key={block.id} block={block} />
  return null
}

export default function ResponseDocumentRenderer({
  document,
  liveActivitySteps = [],
  isLatestTurn = false,
  sessionStatus = '',
  pendingApproval,
  showApprovalActions,
  decideApproval,
  isDecidingApproval,
  approvalReason,
  setApprovalReason,
  onOpenSourceEvidence,
  selectedSourceEvidence,
}) {
  const [activeHoverId, setActiveHoverId] = useState(null)
  const sourceListSources = useMemo(() => collectDocumentSources(document), [document])
  const sourceLookup = useMemo(() => {
    const lookup = new Map()
    for (const source of sourceListSources) addSourceLookupEntries(lookup, source)
    return lookup
  }, [sourceListSources])
  const selectedSource = useMemo(() => {
    const selected = citationFromSource(selectedSourceEvidence?.source)
    if (!selected || !document) return null
    const documentId = document.document_id || document.id || null
    const selectedDocumentId = selectedSourceEvidence?.documentId || null
    if (documentId && selectedDocumentId && documentId !== selectedDocumentId) return null
    if (
      selectedSourceEvidence?.revision != null &&
      document.revision != null &&
      String(selectedSourceEvidence.revision) !== String(document.revision)
    ) {
      return null
    }
    return mergeSourceDetails(selected, sourceListSources.find((item) => sourcesReferToSame(item, selected)))
  }, [document, selectedSourceEvidence, sourceListSources])
  const selectedSourceKeys = useMemo(() => new Set(sourceLookupKeys(selectedSource)), [selectedSource])
  const selectedCitationId = safeText(selectedSource?.citation_id || selectedSource?.citationId)
  const documentActivitySteps = activityStepsFromResponseDocument(document)
  const activeSessionStatus = new Set(['PLANNING', 'EXECUTING', 'WAITING_APPROVAL', 'WAITING_CONFIRMATION'])
  const liveActivityHasRetryStory = hasRetryStoryActivity(liveActivitySteps)
  const shouldUseLiveActivitySteps = Boolean(
    isLatestTurn &&
      (activeSessionStatus.has(String(sessionStatus || '').toUpperCase()) || liveActivityHasRetryStory) &&
      Array.isArray(liveActivitySteps) &&
      liveActivitySteps.length > 0,
  )
  const activitySteps = shouldUseLiveActivitySteps
    ? stripPrematureTerminalActivitySteps(liveActivitySteps, sessionStatus)
    : documentActivitySteps
  const message = responseDocumentMessage(document)
  const finalSummaryBlock = (document?.blocks || []).find((block) =>
    block?.type === 'result_summary' &&
    block.status === 'completed',
  )
  const finalMutationBlock = (document?.blocks || []).find((block) =>
    block?.type === 'mutation_result' &&
    block.status === 'completed' &&
    Array.isArray(block.groups) &&
    block.groups.length > 0 &&
    hasSupportedMutationContract(block),
  )
  const shouldRenderFinalBusinessResult = Boolean(finalSummaryBlock && finalMutationBlock)
  const duplicateTableOwners = useMemo(() => {
    const approvalOwners = new Set()
    const mutationOwners = new Set()
    const readOnlyResultOwners = new Set()
    for (const block of document?.blocks || []) {
      const approvalId = block.approval_id || ''
      const operationId = block.operation_id || ''
      if (block?.type === 'approval_required') approvalOwners.add(`${approvalId}:${operationId}`)
      if (block?.type === 'mutation_result') mutationOwners.add(`${approvalId}:${operationId}`)
      if (
        block?.type === 'result_table' &&
        !approvalId &&
        (block.read_scope || block.display_mode || block.entity_count)
      ) {
        readOnlyResultOwners.add(`${approvalId}:${operationId}`)
      }
    }
    return { approvalOwners, mutationOwners, readOnlyResultOwners }
  }, [document])
  if (!document) return null
  const renderedBlocks = (document.blocks || [])
    .filter((block) => {
      if (!['result_table', 'record_preview'].includes(block?.type)) return true
      const ownerKey = `${block.approval_id || ''}:${block.operation_id || ''}`
      if (duplicateTableOwners.approvalOwners.has(ownerKey)) return false
      if (
        block.type === 'record_preview' &&
        duplicateTableOwners.readOnlyResultOwners.has(ownerKey) &&
        safeText(block.title).toLowerCase() === 'preview'
      ) {
        return false
      }
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
        approvalReason,
        setApprovalReason,
        documentMessage: message,
        sourceLookup,
        selectedSourceKeys,
        selectedCitationId,
        activeHoverId,
        setActiveHoverId,
        onOpenSource: (source) => {
          onOpenSourceEvidence?.({
            source,
            sources: sourceListSources,
            documentId: document.document_id || document.id || null,
            revision: document.revision ?? null,
          })
        },
      })]
    })
    .filter(Boolean)

  return (
    <div className="min-w-0 max-w-full" data-response-document-root="">
      <ActivityTimeline steps={activitySteps} />
      {message ? <div className="w-full max-w-none whitespace-pre-wrap break-words text-ink" data-response-document-prose="">{message}</div> : null}
      {renderedBlocks}
    </div>
  )
}
