export const navSections = [
  {
    label: 'Overview',
    items: [
      { path: '/', label: 'Dashboard', icon: 'dashboard' },
      { path: '/reports', label: 'Reports', icon: 'description' },
    ],
  },
  {
    label: 'Planning',
    items: [
      { path: '/jobs', label: 'Jobs', icon: 'work' },
      { path: '/scheduling', label: 'Scheduling', icon: 'calendar_today' },
      { path: '/scheduling/shortage-resolution', label: 'Shortage Resolution', icon: 'rule' },
    ],
  },
  {
    label: 'Operations',
    items: [
      { path: '/production-data', label: 'Production Data', icon: 'leaderboard' },
      { path: '/storage-inventory', label: 'Storage & Inventory', icon: 'inventory_2' },
      { path: '/products', label: 'Products & BOM', icon: 'category' },
      { path: '/machine-resources', label: 'Machine & Resources', icon: 'precision_manufacturing' },
    ],
  },
]

export const utilityNavItems = [
  { path: '/settings', label: 'Settings', icon: 'settings' },
]

const navItems = [
  ...navSections.flatMap((section) => section.items),
  ...utilityNavItems,
]

export const isNavItemActive = (pathname, path) => {
  const activePath = navItems
    .filter((item) => {
      if (item.path === '/') return pathname === '/'
      return pathname === item.path || pathname.startsWith(`${item.path}/`)
    })
    .sort((a, b) => b.path.length - a.path.length)[0]?.path

  return activePath === path
}
