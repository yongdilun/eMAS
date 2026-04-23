import React, { createContext, useCallback, useContext, useRef, useState } from 'react'

const ToastContext = createContext(null)

let _uid = 0

/**
 * Supported variants: 'success' | 'error' | 'warning' | 'info'
 */
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const timers = useRef({})

  const dismiss = useCallback((id) => {
    clearTimeout(timers.current[id])
    setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, leaving: true } : t)))
    // Remove from DOM after animation
    timers.current[`remove_${id}`] = setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 300)
  }, [])

  const toast = useCallback(
    (variant, message, options = {}) => {
      const id = ++_uid
      const duration = options.duration ?? (variant === 'error' ? 6000 : 4000)
      setToasts((prev) => [...prev, { id, variant, message, leaving: false }])
      if (duration > 0) {
        timers.current[id] = setTimeout(() => dismiss(id), duration)
      }
      return id
    },
    [dismiss],
  )

  const value = {
    success: (msg, opts) => toast('success', msg, opts),
    error:   (msg, opts) => toast('error',   msg, opts),
    warning: (msg, opts) => toast('warning', msg, opts),
    info:    (msg, opts) => toast('info',    msg, opts),
    dismiss,
  }

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
    bar:  'bg-emerald-500',
    iconColor: 'text-emerald-400',
    ring: 'border-emerald-500/30',
  },
  error: {
    icon: 'error',
    bar:  'bg-red-500',
    iconColor: 'text-red-400',
    ring: 'border-red-500/30',
  },
  warning: {
    icon: 'warning',
    bar:  'bg-amber-500',
    iconColor: 'text-amber-400',
    ring: 'border-amber-500/30',
  },
  info: {
    icon: 'info',
    bar:  'bg-sky-500',
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
        backdrop-blur-md shadow-2xl
        ${cfg.ring}
        transition-all duration-300 ease-out
        ${toast.leaving ? 'opacity-0 translate-x-4 scale-95' : 'opacity-100 translate-x-0 scale-100'}
      `}
      style={{ minWidth: 280 }}
    >
      {/* Accent bar */}
      <span className={`absolute left-0 top-3 bottom-3 w-1 rounded-full ${cfg.bar}`} />

      {/* Icon */}
      <span className={`material-icons text-[20px] mt-0.5 flex-shrink-0 ${cfg.iconColor}`}>
        {cfg.icon}
      </span>

      {/* Message */}
      <p className="flex-1 text-sm text-gray-100 leading-snug pr-2">{toast.message}</p>

      {/* Dismiss */}
      <button
        onClick={() => onDismiss(toast.id)}
        className="flex-shrink-0 text-gray-500 hover:text-gray-200 transition-colors mt-0.5"
        aria-label="Dismiss"
      >
        <span className="material-icons text-[16px]">close</span>
      </button>
    </div>
  )
}
