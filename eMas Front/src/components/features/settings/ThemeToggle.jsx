const ThemeToggle = ({ isDark, onToggle }) => {
  return (
    <div className="flex items-center gap-4">
      <span className="text-sm text-gray-500 dark:text-[#9ab4bc]">Light</span>
      <label className="relative inline-flex items-center cursor-pointer">
        <input
          type="checkbox"
          checked={isDark}
          onChange={onToggle}
          className="sr-only peer"
        />
        <div className="w-11 h-6 bg-gray-200 dark:bg-[#27363a] rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
      </label>
      <span className="text-sm text-gray-900 dark:text-white">Dark</span>
    </div>
  )
}

export default ThemeToggle

