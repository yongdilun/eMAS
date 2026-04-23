const Modal = ({ isOpen, onClose, title, children, size = 'default', zIndex }) => {
  if (!isOpen) return null

  const isFullScreen = size === 'fullscreen'
  const baseZ = zIndex ?? 50
  const contentZ = isFullScreen ? baseZ + 1 : baseZ
  const contentClass = isFullScreen
    ? 'fixed inset-4 sm:inset-6 md:inset-8 bg-white dark:bg-gray-900 rounded-xl shadow-xl flex flex-col overflow-hidden'
    : 'bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-2xl w-full mx-4 flex flex-col max-h-[90vh] overflow-hidden'

  return (
    <div className="fixed inset-0 bg-black/50 dark:bg-black/60 flex items-center justify-center p-0" style={{ zIndex: baseZ }} onClick={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className={contentClass} style={{ zIndex: contentZ }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 sm:p-6 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <h2 className="text-lg sm:text-xl font-semibold text-gray-900 dark:text-white">{title}</h2>
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            aria-label="Close"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>
        <div className={`flex-1 min-h-0 ${isFullScreen ? 'flex flex-col overflow-hidden p-4 sm:p-6' : 'overflow-auto p-6'}`}>{children}</div>
      </div>
    </div>
  )
}

export default Modal


