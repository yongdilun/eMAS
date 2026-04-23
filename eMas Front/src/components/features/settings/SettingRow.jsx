const SettingRow = ({ title, description, children }) => {
  return (
    <div className="flex items-center justify-between">
      <div>
        <h3 className="text-base font-medium text-gray-900 dark:text-white">{title}</h3>
        <p className="text-sm text-gray-500 dark:text-[#9ab4bc]">{description}</p>
      </div>
      <div>{children}</div>
    </div>
  )
}

export default SettingRow

