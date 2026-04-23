import { Link, useLocation } from 'react-router-dom'
import logoHori from '../../assets/logoHori.png'

const Sidebar = () => {
  const location = useLocation()

  const menuItems = [
    { path: '/', label: 'Dashboard', icon: 'dashboard' },
    { path: '/jobs', label: 'Jobs', icon: 'work' },
    { path: '/scheduling', label: 'Scheduling', icon: 'calendar_today' },
    { path: '/scheduling/shortage-resolution', label: 'Shortage Resolution', icon: 'rule' },
    { path: '/production-data', label: 'Production Data', icon: 'leaderboard' },
    { path: '/predictive-analysis', label: 'Predictive Analysis', icon: 'trending_up' },
    { path: '/reports', label: 'Reports', icon: 'description' },
    { path: '/storage-inventory', label: 'Storage & Inventory', icon: 'inventory_2' },
    { path: '/products', label: 'Products & BOM', icon: 'category' },
    { path: '/machine-resources', label: 'Machine & Resources', icon: 'precision_manufacturing' },
  ]

  const isActive = (path) => {
    if (path === '/') {
      return location.pathname === '/'
    }
    return location.pathname.startsWith(path)
  }

  return (
    <aside className="sticky top-0 h-screen w-64 bg-gray-100 dark:bg-[#111618] border-r border-gray-200 dark:border-gray-800 p-4 shrink-0">
      <div className="flex flex-col h-full">
        <Link to="/" className="flex items-center mb-8 group py-2 px-2">
          <img
            src={logoHori}
            alt="eMAS Logo"
            className="h-12 w-auto object-contain transition-transform group-hover:scale-105"
          />
        </Link>

        <nav className="flex flex-col gap-2">
          {menuItems.map((item) => {
            const active = isActive(item.path)
            return (
              <Link
                key={item.path}
                to={item.path}
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
    </aside>
  )
}

export default Sidebar


