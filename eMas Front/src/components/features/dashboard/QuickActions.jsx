const QuickActions = () => {
  const actions = [
    {
      icon: 'play_arrow',
      label: 'Start New Batch',
      primary: true,
    },
    {
      icon: 'build_circle',
      label: 'Run Diagnostics',
      primary: false,
    },
    {
      icon: 'summarize',
      label: 'Generate Report',
      primary: false,
    },
  ]

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-white/5 p-6">
      <p className="text-gray-900 dark:text-white text-lg font-medium leading-normal">Quick Actions</p>
      <div className="flex flex-col gap-3">
        {actions.map((action, index) => (
          <button
            key={index}
            className={`w-full text-left flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
              action.primary
                ? 'bg-primary hover:bg-primary/90'
                : 'bg-gray-100 dark:bg-white/10 hover:bg-gray-200 dark:hover:bg-white/20'
            }`}
          >
            <span
              className={`material-symbols-outlined ${
                action.primary ? 'text-background-dark' : 'text-gray-700 dark:text-white/80'
              }`}
            >
              {action.icon}
            </span>
            <p
              className={`text-sm font-medium ${
                action.primary ? 'text-background-dark' : 'text-gray-700 dark:text-white/80'
              }`}
            >
              {action.label}
            </p>
          </button>
        ))}
      </div>
    </div>
  )
}

export default QuickActions

