import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import logoHori from '../../assets/logoHori.png'

const MobileMenu = () => {
  const [isOpen, setIsOpen] = useState(false)
  const location = useLocation()

  const menuItems = [
    { path: '/', label: 'Dashboard', icon: 'dashboard' },
    { path: '/jobs', label: 'Jobs', icon: 'work' },
    { path: '/scheduling', label: 'Scheduling', icon: 'calendar_today' },
    { path: '/production-data', label: 'Production Data', icon: 'leaderboard' },
    { path: '/predictive-analysis', label: 'Predictive Analysis', icon: 'trending_up' },
    { path: '/reports', label: 'Reports', icon: 'description' },
    { path: '/storage-inventory', label: 'Storage & Inventory', icon: 'inventory_2' },
    { path: '/machine-resources', label: 'Machine & Resources', icon: 'precision_manufacturing' },
  ]

  const isActive = (path) => {
    if (path === '/') {
      return location.pathname === '/'
    }
    return location.pathname.startsWith(path)
  }

  return (
    <div className="lg:hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="p-2 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-white"
      >
        <span className="material-symbols-outlined">
          {isOpen ? 'close' : 'menu'}
        </span>
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-50 bg-background-light dark:bg-[#111618] p-4">
          <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center">
                <img
                  src={logoHori}
                  alt="eMAS Logo"
                  className="h-12 w-auto object-contain"
                />
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-900 dark:text-white"
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>

            <nav className="flex flex-col gap-2">
              {menuItems.map((item) => {
                const active = isActive(item.path)
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    onClick={() => setIsOpen(false)}
                    className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${
                      active
                        ? 'bg-primary/20 text-primary'
                        : 'text-gray-700 dark:text-[#9cb3ba] hover:bg-gray-200 dark:hover:bg-[#283539] hover:text-gray-900 dark:hover:text-white'
                    }`}
                  >
                    <span
                      className={`material-symbols-outlined ${
                        active ? 'text-primary' : 'text-gray-700 dark:text-[#9cb3ba]'
                      }`}
                      style={
                        active
                          ? { fontVariationSettings: "'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24" }
                          : {}
                      }
                    >
                      {item.icon}
                    </span>
                    <p className="text-sm font-medium leading-normal">{item.label}</p>
                  </Link>
                )
              })}
            </nav>
            
            <div className="mt-auto">
              <Link
                to="/settings"
                onClick={() => setIsOpen(false)}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${
                  isActive('/settings')
                    ? 'bg-primary/20 text-primary'
                    : 'text-gray-700 dark:text-[#9cb3ba] hover:bg-gray-200 dark:hover:bg-[#283539] hover:text-gray-900 dark:hover:text-white'
                }`}
              >
                <span
                  className={`material-symbols-outlined ${
                    isActive('/settings') ? 'text-primary' : 'text-gray-700 dark:text-[#9cb3ba]'
                  }`}
                  style={
                    isActive('/settings')
                      ? { fontVariationSettings: "'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24" }
                      : {}
                  }
                >
                  settings
                </span>
                <p className="text-sm font-medium leading-normal">Settings</p>
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default MobileMenu

