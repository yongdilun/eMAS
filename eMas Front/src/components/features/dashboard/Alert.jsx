const Alert = ({ type = 'info', title, time, icon }) => {
  const iconColors = {
    error: 'text-red-500',
    warning: 'text-yellow-500',
    info: 'text-blue-400',
    success: 'text-green-400',
  }

  const defaultIcons = {
    error: 'error',
    warning: 'warning',
    info: 'info',
    success: 'check_circle',
  }

  return (
    <div className="flex items-start gap-3">
      <span className={`material-symbols-outlined ${iconColors[type]} mt-0.5`}>
        {icon || defaultIcons[type]}
      </span>
      <div className="flex flex-col">
        <p className="text-gray-900 dark:text-white text-sm font-medium">{title}</p>
        {time && <p className="text-gray-600 dark:text-white/60 text-xs">{time}</p>}
      </div>
    </div>
  )
}

export default Alert


