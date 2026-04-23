const InventoryTable = ({ items, onActionClick }) => {
  const getStatusBadge = (status) => {
    const statusConfig = {
      'In Stock': {
        bg: 'bg-green-500/20',
        text: 'text-green-400',
        dot: 'bg-green-400',
      },
      'Low Stock': {
        bg: 'bg-yellow-500/20',
        text: 'text-yellow-400',
        dot: 'bg-yellow-400',
      },
      'Out of Stock': {
        bg: 'bg-red-500/20',
        text: 'text-red-400',
        dot: 'bg-red-400',
      },
    }

    const config = statusConfig[status] || statusConfig['In Stock']

    return (
      <span
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${config.bg} ${config.text}`}
      >
        <span className={`w-2 h-2 ${config.dot} rounded-full`}></span>
        {status}
      </span>
    )
  }

  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl overflow-hidden border border-gray-300 dark:border-gray-700">
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead className="bg-gray-100 dark:bg-gray-800">
            <tr className="border-b border-gray-300 dark:border-gray-700">
              <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300">Material ID</th>
              <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300">Material Name</th>
              <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300">Current Stock</th>
              <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300">Min Required</th>
              <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300">Status</th>
              <th className="px-6 py-4 font-semibold text-sm text-gray-700 dark:text-gray-300"></th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr
                key={item.id}
                className="border-b border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors last:border-b-0"
              >
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600 dark:text-gray-400">{item.id}</td>
                <td className="px-6 py-4 whitespace-nowrap font-medium text-gray-900 dark:text-white">
                  {item.name}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-gray-900 dark:text-white">{item.currentStock}</td>
                <td className="px-6 py-4 whitespace-nowrap text-gray-900 dark:text-white">{item.minStock}</td>
                <td className="px-6 py-4 whitespace-nowrap">{getStatusBadge(item.status)}</td>
                <td className="px-6 py-4 text-right">
                  <button
                    onClick={() => onActionClick && onActionClick(item)}
                    className="p-1.5 text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                  >
                    <span className="material-symbols-outlined text-lg">more_horiz</span>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default InventoryTable

