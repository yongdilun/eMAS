/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'

const ToastContext = createContext(null)

let _uid = 0
const MAX_VISIBLE_TOASTS = 5
const AUTH_EXPIRED_MESSAGE = 'Your session has expired. Please refresh and try again.'
const AUTH_EXPIRED_DEDUPE_KEY = 'auth-expired'

/**
 * Supported variants: 'success' | 'error' | 'warning' | 'info'
 */
export function ToastProvider({ children }) {
    const [toasts, setToasts] = useState([])
    const toastsRef = useRef([])
    const suppressedToastsRef = useRef(new Set())
    const timers = useRef({})

    const updateToasts = useCallback((updater) => {
        const next = typeof updater === 'function' ? updater(toastsRef.current) : updater
        toastsRef.current = next
        setToasts(next)
        return next
    }, [])

    const dismiss = useCallback((id) => {
        clearTimeout(timers.current[id])
        updateToasts((prev) => prev.map((t) => (t.id === id ? { ...t, leaving: true } : t)))
        // Remove from DOM after animation
        timers.current[`remove_${id}`] = setTimeout(() => {
            updateToasts((prev) => prev.filter((t) => t.id !== id))
        }, 300)
    }, [updateToasts])

    const toast = useCallback(
        (variant, message, options = {}) => {
            const dedupeMessage = String(message)
            const dedupeKey =
                options.dedupeKey ??
                (dedupeMessage === AUTH_EXPIRED_MESSAGE ? AUTH_EXPIRED_DEDUPE_KEY : null)
            const suppressAfterFirst =
                options.suppressAfterFirst === true ||
                (dedupeKey === AUTH_EXPIRED_DEDUPE_KEY && dedupeMessage === AUTH_EXPIRED_MESSAGE)
            const suppressionKey = suppressAfterFirst && dedupeKey != null
                ? `${dedupeKey}::${dedupeMessage}`
                : null
            if (suppressionKey && suppressedToastsRef.current.has(suppressionKey)) {
                return null
            }
            if (dedupeKey != null) {
                const existing = toastsRef.current.find((t) =>
                    !t.leaving &&
                    t.dedupeKey === dedupeKey &&
                    t.dedupeMessage === dedupeMessage
                )
                if (existing) return existing.id
            }

            const id = ++_uid
            if (suppressionKey) suppressedToastsRef.current.add(suppressionKey)
            const duration = options.duration ?? (variant === 'error' ? 6000 : 4000)
            const nextToast = {
                id,
                variant,
                message,
                dedupeKey,
                dedupeMessage,
                leaving: false,
            }
            const next = [...toastsRef.current, nextToast]
            const visible = next.slice(-MAX_VISIBLE_TOASTS)
            if (visible.length < next.length) {
                next.slice(0, next.length - visible.length).forEach((removed) => {
                    clearTimeout(timers.current[removed.id])
                    clearTimeout(timers.current[`remove_${removed.id}`])
                })
            }
            updateToasts(visible)
            if (duration > 0) {
                timers.current[id] = setTimeout(() => dismiss(id), duration)
            }
            return id
        },
        [dismiss, updateToasts],
    )

    useEffect(() => {
        return () => {
            Object.values(timers.current).forEach((timerId) => clearTimeout(timerId))
        }
    }, [])

    const value = useMemo(() => ({
        success: (msg, opts) => toast('success', msg, opts),
        error: (msg, opts) => toast('error', msg, opts),
        warning: (msg, opts) => toast('warning', msg, opts),
        info: (msg, opts) => toast('info', msg, opts),
        dismiss,
    }), [dismiss, toast])

    return (
        <ToastContext.Provider value={value}>
            {children}
            <ToastContainer toasts={toasts} onDismiss={dismiss} />
        </ToastContext.Provider>
    )
}

export function useToast() {
    const ctx = useContext(ToastContext)
    if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
    return ctx
}

// ─── Internal components ─────────────────────────────────────────────────────

const CONFIG = {
    success: {
        icon: 'check_circle',
        bar: 'bg-emerald-500',
        iconColor: 'text-emerald-400',
        ring: 'border-emerald-500/30',
    },
    error: {
        icon: 'error',
        bar: 'bg-red-500',
        iconColor: 'text-red-400',
        ring: 'border-red-500/30',
    },
    warning: {
        icon: 'warning',
        bar: 'bg-amber-500',
        iconColor: 'text-amber-400',
        ring: 'border-amber-500/30',
    },
    info: {
        icon: 'info',
        bar: 'bg-sky-500',
        iconColor: 'text-sky-400',
        ring: 'border-sky-500/30',
    },
}

function ToastContainer({ toasts, onDismiss }) {
    if (!toasts.length) return null
    return (
        <div
            className="fixed bottom-6 right-6 z-[9999] flex flex-col gap-2 pointer-events-none"
            style={{ maxWidth: 380 }}
        >
            {toasts.map((t) => (
                <Toast key={t.id} toast={t} onDismiss={onDismiss} />
            ))}
        </div>
    )
}

function Toast({ toast, onDismiss }) {
    const cfg = CONFIG[toast.variant] || CONFIG.info

    return (
        <div
            className={`
 pointer-events-auto relative flex items-start gap-3
 rounded-xl border px-4 py-3
 bg-[#0f1e23]/95 dark:bg-[#0f1e23]/95
 backdrop-blur-md -2xl
 ${cfg.ring}
 transition-all duration-300 ease-out
 ${toast.leaving ? 'opacity-0 translate-x-4 scale-95' : 'opacity-100 translate-x-0 scale-100'}
 `}
            style={{ minWidth: 280 }}
        >
            {/* Accent bar */}
            <span className={`absolute left-0 top-3 bottom-3 w-1 rounded-full ${cfg.bar}`} />

            {/* Icon */}
            <span className={`material-symbols-outlined text-[20px] mt-0.5 flex-shrink-0 ${cfg.iconColor}`} aria-hidden="true">
                {cfg.icon}
            </span>

            {/* Message */}
            <p className="flex-1 text-sm text-gray-100 leading-snug pr-2">{toast.message}</p>

            {/* Dismiss */}
            <button
                onClick={() => onDismiss(toast.id)}
                className="flex h-5 w-5 flex-shrink-0 items-center justify-center text-gray-400 hover:text-gray-200 transition-colors mt-0.5"
                aria-label="Dismiss"
            >
                <span className="material-symbols-outlined text-[16px]" aria-hidden="true">close</span>
            </button>
        </div>
    )
}
