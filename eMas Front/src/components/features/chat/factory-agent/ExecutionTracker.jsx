/* eslint-disable react/prop-types */
import { friendlySessionStatus } from './activityTimelineUtils'

const statusTone = {
 IDLE: 'text-ink-muted',
 PLANNING: 'text-ink-muted',
 WAITING_APPROVAL: 'text-ink-muted',
 EXECUTING: 'text-primary',
 BLOCKED: 'text-ink-muted',
 FAILED: 'text-ink',
 COMPLETED: 'text-primary',
}

const ExecutionTracker = ({ session, lastSyncedAt, isPollingSession }) => {
 if (!session) return null
 const tone = statusTone[session.status] || statusTone.IDLE

 return (
 <div className="mb-3 rounded-lg border border-hairline bg-surface-1 p-3">
 <div className="flex items-center justify-between">
 <span className="text-xs font-semibold text-ink-subtle">Activity</span>
 <span className={`text-xs font-semibold ${tone}`}>{friendlySessionStatus(session.status)}</span>
 </div>
 <div className="mt-2 text-xs text-ink-muted">
 {session.status === 'WAITING_APPROVAL'
 ? 'Waiting for your approval before continuing.'
 : session.status === 'WAITING_CONFIRMATION'
 ? 'Waiting for your confirmation before continuing.'
 : session.status === 'FAILED' || session.status === 'BLOCKED'
 ? 'Something needs attention before this can continue.'
 : 'The assistant is working through your request.'}
 </div>
 {session.pending_user_message ? (
 <div className="mt-2 text-xs text-ink-muted">
 Pending operator message queued.
 </div>
 ) : null}
 {session.error ? (
 <div className="mt-2 text-xs text-ink-muted">Something needs attention.</div>
 ) : null}
 <div className="mt-2 flex items-center justify-between text-[10px] text-ink-subtle">
 <span>{isPollingSession ? 'Updating automatically' : 'Up to date'}</span>
 <span>{lastSyncedAt ? `Synced ${new Date(lastSyncedAt).toLocaleTimeString()}` : 'Not synced yet'}</span>
 </div>
 </div>
 )
}

export default ExecutionTracker
