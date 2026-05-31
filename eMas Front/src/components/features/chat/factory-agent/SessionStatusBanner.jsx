const statusCopy = {
    IDLE: {
        tone: 'bg-surface-2 border-hairline text-ink-muted',
        text: 'Session idle. You can start a new task.',
    },
    PLANNING: {
        tone: 'bg-surface-2 border-hairline text-ink-muted',
        text: 'Planning in progress.',
    },
    WAITING_APPROVAL: {
        tone: 'bg-surface-2 border-hairline text-ink-muted',
        text: 'Waiting for operator approval.',
    },
    WAITING_USER_ACTION: {
        tone: 'bg-surface-2 border-hairline text-ink-muted',
        text: 'Waiting for schedule review.',
    },
    EXECUTING: {
        tone: 'bg-primary/10 border-primary/20 text-primary',
        text: 'Execution in progress.',
    },
    BLOCKED: {
        tone: 'bg-surface-2 border-hairline text-inak-muted',
        text: 'Execution blocked. Review and retry or cancel.',
    },
    FAILED: {
        tone: 'bg-surface-2 border-hairline text-ink-muted',
        text: 'Session failed. Start a new session or retry from current state.',
    },
    COMPLETED: {
        tone: 'bg-primary/10 border-primary/20 text-primary',
        text: 'Session completed successfully.',
    },
}

const SessionStatusBanner = ({ session, onRetry }) => {
    if (!session?.status) return null
    const info = statusCopy[session.status] || statusCopy.IDLE

    return (
        <div className={`mb-3 rounded-lg border px-3 py-2 text-xs ${info.tone}`}>
            <div className="flex items-center justify-between gap-3">
                <div className="font-medium">{info.text}</div>
                {(session.status === 'BLOCKED' || session.status === 'FAILED') && (
                    <button
                        type="button"
                        onClick={onRetry}
                        className="px-2 py-1 rounded-md text-xs font-semibold bg-surface-1 hover:bg-surface-2"
                    >
                        Retry
                    </button>
                )}
            </div>
            {session.error ? <div className="mt-1 opacity-90">Reason: {session.error}</div> : null}
        </div>
    )
}

export default SessionStatusBanner
