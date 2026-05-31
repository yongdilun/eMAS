import {
  invalidResponseDocumentDiagnostic,
  normalizeResponseDocument,
} from './responseDocumentContract.js'

const ABSENT_REVISION = -1

function cleanString(value) {
  return value == null ? '' : String(value).trim()
}

function finiteRevision(value) {
  const n = Number(value)
  return Number.isFinite(n) && n >= 0 ? n : null
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map((item) => stableJson(item)).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function responseDocumentIdentity(document, rawDocument = null) {
  const raw = rawDocument && typeof rawDocument === 'object' && !Array.isArray(rawDocument) ? rawDocument : {}
  const doc = document && typeof document === 'object' && !Array.isArray(document) ? document : {}
  return {
    documentId: cleanString(raw.document_id || raw.documentId || raw.id || doc.document_id || doc.documentId || doc.id),
    turnId: cleanString(raw.turn_id || raw.turnId || doc.turn_id || doc.turnId),
  }
}

function sameDocumentScope(a, b) {
  if (!a || !b) return false
  return cleanString(a.sessionId) === cleanString(b.sessionId)
    && cleanString(a.documentId) === cleanString(b.documentId)
    && cleanString(a.turnId) === cleanString(b.turnId)
}

function materializeInvalidDocument(rawDocument, violations, revision, snapshotRevision) {
  const base = invalidResponseDocumentDiagnostic(violations)
  const raw = rawDocument && typeof rawDocument === 'object' && !Array.isArray(rawDocument) ? rawDocument : {}
  const rawIdentity = responseDocumentIdentity(null, raw)
  const documentId = rawIdentity.documentId || base.document_id
  const turnId = rawIdentity.turnId || null
  return {
    ...base,
    id: documentId,
    document_id: documentId,
    turn_id: turnId,
    operation_id: cleanString(raw.operation_id || raw.operationId) || null,
    revision,
    revision_source: cleanString(raw.revision_source || raw.revisionSource) || 'frontend_validation',
    snapshot_revision: snapshotRevision,
    diagnostics: {
      ...base.diagnostics,
      violations,
      incoming_revision: revision,
      incoming_snapshot_revision: snapshotRevision,
    },
    blocks: (base.blocks || []).map((block) => (
      block.type === 'diagnostic'
        ? {
            ...block,
            technical_details: {
              ...(block.technical_details || {}),
              violations,
              incoming_revision: revision,
              incoming_snapshot_revision: snapshotRevision,
            },
          }
        : block
    )),
  }
}

function stateFromDocument({
  status,
  document,
  sessionId,
  snapshotRevision,
  transport,
  violations = [],
}) {
  const identity = responseDocumentIdentity(document)
  const revision = finiteRevision(document?.revision) ?? ABSENT_REVISION
  return {
    status,
    document,
    sessionId: cleanString(sessionId),
    documentId: identity.documentId,
    turnId: identity.turnId,
    revision,
    snapshotRevision: finiteRevision(snapshotRevision) ?? revision,
    contentHash: document ? stableJson(document) : null,
    violations,
    lastAcceptedTransport: cleanString(transport) || 'unknown',
  }
}

export function createResponseDocumentReducerState(overrides = {}) {
  return {
    status: 'absent',
    document: null,
    sessionId: '',
    documentId: '',
    turnId: '',
    revision: ABSENT_REVISION,
    snapshotRevision: ABSENT_REVISION,
    contentHash: null,
    violations: [],
    lastAcceptedTransport: null,
    ...overrides,
  }
}

export function responseDocumentUpdateFromSnapshot(snapshot, meta = {}) {
  const hasResponseDocument = Object.prototype.hasOwnProperty.call(snapshot || {}, 'response_document')
  const sessionId = cleanString(
    snapshot?.session?.session_id ||
    snapshot?.session_id ||
    meta.sessionId ||
    meta.requestedSessionId,
  )
  return {
    hasResponseDocument,
    rawDocument: hasResponseDocument ? snapshot?.response_document : undefined,
    sessionId,
    snapshotRevision: finiteRevision(snapshot?.snapshot_revision) ?? finiteRevision(snapshot?.cursor),
    transport: cleanString(meta.transport) || 'unknown',
  }
}

function normalizeIncoming(incoming) {
  if (!incoming?.hasResponseDocument || incoming.rawDocument == null) {
    return {
      status: 'absent',
      document: null,
      sessionId: cleanString(incoming?.sessionId),
      documentId: '',
      turnId: '',
      revision: ABSENT_REVISION,
      snapshotRevision: finiteRevision(incoming?.snapshotRevision) ?? ABSENT_REVISION,
      contentHash: null,
      violations: [],
      transport: cleanString(incoming?.transport) || 'unknown',
    }
  }

  const rawRevision = finiteRevision(incoming.rawDocument?.revision)
  const snapshotRevision = finiteRevision(incoming.snapshotRevision)
  const revision = rawRevision ?? snapshotRevision ?? 0
  const normalized = normalizeResponseDocument(incoming.rawDocument)
  const document = normalized.status === 'invalid'
    ? materializeInvalidDocument(incoming.rawDocument, normalized.violations || [], revision, snapshotRevision)
    : normalized.document
  const identity = responseDocumentIdentity(document, incoming.rawDocument)
  return {
    status: normalized.status,
    document,
    sessionId: cleanString(incoming.sessionId),
    documentId: identity.documentId,
    turnId: identity.turnId,
    revision,
    snapshotRevision: snapshotRevision ?? revision,
    contentHash: stableJson(document),
    violations: normalized.violations || [],
    transport: cleanString(incoming.transport) || 'unknown',
  }
}

function accept(incoming, decision) {
  return {
    accepted: true,
    decision,
    state: stateFromDocument(incoming),
  }
}

function reject(current, incoming, decision) {
  return {
    accepted: false,
    decision,
    state: current,
    ignored: incoming,
  }
}

function compareOrder(incoming, current) {
  if (incoming.snapshotRevision !== current.snapshotRevision) {
    return incoming.snapshotRevision - current.snapshotRevision
  }
  return incoming.revision - current.revision
}

const TERMINAL_DOCUMENT_STATES = new Set(['completed', 'failed', 'blocked', 'rejected', 'expired', 'cancelled'])
const WAITING_DOCUMENT_STATES = new Set(['waiting_approval', 'waiting_confirmation', 'waiting_user_action'])

function documentState(value) {
  return cleanString(value?.state || value?.status).toLowerCase()
}

function terminalStateSupersedesCurrent(incoming, current) {
  const incomingState = documentState(incoming?.document)
  const currentState = documentState(current?.document)
  return TERMINAL_DOCUMENT_STATES.has(incomingState) && !TERMINAL_DOCUMENT_STATES.has(currentState)
}

function waitingStateSupersedesActiveCurrent(incoming, current) {
  const incomingState = documentState(incoming?.document)
  const currentState = documentState(current?.document)
  return WAITING_DOCUMENT_STATES.has(incomingState)
    && !WAITING_DOCUMENT_STATES.has(currentState)
    && !TERMINAL_DOCUMENT_STATES.has(currentState)
}

export function applyResponseDocumentUpdate(currentState, rawIncoming) {
  const current = createResponseDocumentReducerState(currentState || {})
  const incoming = normalizeIncoming(rawIncoming)

  if (incoming.status === 'absent') {
    if (current.status !== 'absent' && cleanString(current.sessionId) === cleanString(incoming.sessionId)) {
      return incoming.snapshotRevision > current.snapshotRevision
        ? accept(incoming, 'accepted_newer_absent_response_document')
        : reject(current, incoming, 'ignored_absent_after_response_document')
    }
    return accept(incoming, 'accepted_absent')
  }

  if (current.status === 'absent') {
    return accept(incoming, incoming.status === 'valid' ? 'accepted_first_valid' : 'accepted_first_invalid')
  }

  const currentScope = {
    sessionId: current.sessionId,
    documentId: current.documentId,
    turnId: current.turnId,
  }
  const incomingScope = {
    sessionId: incoming.sessionId,
    documentId: incoming.documentId,
    turnId: incoming.turnId,
  }

  if (cleanString(current.sessionId) !== cleanString(incoming.sessionId)) {
    return accept(incoming, 'accepted_new_session_scope')
  }

  if (!sameDocumentScope(currentScope, incomingScope)) {
    return compareOrder(incoming, current) >= 0
      ? accept(incoming, 'accepted_newer_document_scope')
      : reject(current, incoming, 'ignored_older_document_scope')
  }

  if (terminalStateSupersedesCurrent(incoming, current)) {
    return accept(
      incoming,
      incoming.revision < current.revision
        ? 'accepted_terminal_lower_revision_over_active'
        : 'accepted_terminal_equal_revision_over_active',
    )
  }

  if (waitingStateSupersedesActiveCurrent(incoming, current)) {
    return accept(
      incoming,
      incoming.revision < current.revision
        ? 'accepted_waiting_lower_revision_over_active'
        : 'accepted_waiting_equal_revision_over_active',
    )
  }

  if (incoming.revision < current.revision) {
    return reject(current, incoming, 'ignored_stale_revision')
  }

  if (incoming.revision > current.revision) {
    return accept(incoming, incoming.status === 'valid' ? 'accepted_newer_valid_revision' : 'accepted_newer_invalid_revision')
  }

  if (current.status === 'invalid' && incoming.status === 'valid') {
    return accept(incoming, 'accepted_valid_same_revision_over_invalid')
  }

  if (current.status === 'valid' && incoming.status === 'invalid') {
    return reject(current, incoming, 'ignored_invalid_same_revision_after_valid')
  }

  if (incoming.contentHash === current.contentHash) {
    return reject(current, incoming, 'ignored_duplicate_revision')
  }

  return reject(current, incoming, 'ignored_conflicting_equal_revision')
}

export function applyResponseDocumentSnapshotUpdate(currentState, snapshot, meta = {}) {
  return applyResponseDocumentUpdate(
    currentState,
    responseDocumentUpdateFromSnapshot(snapshot, meta),
  )
}
